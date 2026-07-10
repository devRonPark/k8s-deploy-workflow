from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from preanalyzer.models.semantic import (
    SemanticCandidate,
    SemanticResolution,
    SemanticResolutionStatus,
)
from preanalyzer.models.semantic_agent import ResolutionAction, ToolCallAction
from preanalyzer.pipeline import run_phase1_analysis


FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_TIME


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_shell_entrypoint_repo(root: Path, *, secret_text: str = "changethis") -> None:
    write(
        root / "Dockerfile",
        "\n".join(
            [
                "FROM python:3.12-slim",
                "ENTRYPOINT [\"./entrypoint.sh\"]",
                "",
            ]
        ),
    )
    write(root / "entrypoint.sh", "exec uvicorn main:app --host 0.0.0.0\n")
    write(root / ".env", f"SEMANTIC_LLM_API_KEY={secret_text}\n")


class ResolveFromContextProvider:
    def __init__(self) -> None:
        self.contexts = []

    def decide(self, context):
        self.contexts.append(context)
        if len(self.contexts) == 1:
            return ToolCallAction(
                tool_name="read_source_range",
                arguments={"path": "entrypoint.sh", "start_line": 1, "end_line": 1},
            )
        evidence_ref = context.collected_evidence[0]["evidence_id"]
        return ResolutionAction(
            resolution=SemanticResolution(
                task_id=context.task_id,
                status=SemanticResolutionStatus.RESOLVED,
                candidates=[
                    SemanticCandidate(
                        candidate_id="SC-PIPELINE-001",
                        component_id=context.component_id,
                        target_field=context.target_field,
                        value={"command": "uvicorn main:app --host 0.0.0.0"},
                        classification="llm_semantic_inference",
                        confidence="medium",
                        evidence_refs=[evidence_ref],
                    )
                ],
                recommended_candidate_id="SC-PIPELINE-001",
                tool_trace_refs=[evidence_ref],
            )
        )


class ExhaustedProvider:
    def decide(self, context):
        raise RuntimeError("provider unavailable")


class SemanticPipelineIntegrationTests(unittest.TestCase):
    def test_disabled_mode_writes_audit_without_running_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            out_dir = Path(tmp) / "out"
            make_shell_entrypoint_repo(repo)

            run_phase1_analysis(repo=repo, output_dir=out_dir, url="fixture://semantic", ref="fixture", clock=fixed_clock)

            audit = yaml.safe_load((out_dir / "04-semantic-analysis.yaml").read_text(encoding="utf-8"))

        self.assertFalse(audit["semantic_analysis"]["enabled"])
        self.assertEqual(audit["semantic_analysis"]["provider"], "disabled")
        self.assertEqual(audit["semantic_analysis"]["runs"], [])
        self.assertEqual(audit["semantic_analysis"]["summary"]["tasks_created"], 1)
        self.assertEqual(audit["semantic_analysis"]["summary"]["runs_attempted"], 0)

    def test_fake_mode_runs_agent_and_writes_sanitized_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            out_dir = Path(tmp) / "out"
            make_shell_entrypoint_repo(repo)
            provider = ResolveFromContextProvider()

            run_phase1_analysis(
                repo=repo,
                output_dir=out_dir,
                url="fixture://semantic",
                ref="fixture",
                clock=fixed_clock,
                semantic_mode="fake",
                semantic_decision_provider=provider,
                semantic_model="scripted-fake",
            )

            audit_text = (out_dir / "04-semantic-analysis.yaml").read_text(encoding="utf-8")
            audit = yaml.safe_load(audit_text)

        semantic = audit["semantic_analysis"]
        self.assertTrue(semantic["enabled"])
        self.assertEqual(semantic["provider"], "fake")
        self.assertEqual(semantic["model"], "scripted-fake")
        self.assertEqual(semantic["summary"]["runs_attempted"], 1)
        self.assertEqual(semantic["summary"]["accepted"], 1)
        self.assertEqual(semantic["runs"][0]["run_status"], "completed")
        self.assertEqual(semantic["runs"][0]["verification_result"]["status"], "accepted")
        self.assertNotIn(str(repo), audit_text)
        self.assertNotIn("changethis", audit_text)
        self.assertNotIn("SEMANTIC_LLM_API_KEY", audit_text)
        self.assertNotIn("uvicorn main:app --host 0.0.0.0", audit_text)

    def test_provider_error_is_audited_without_stopping_phase1_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            out_dir = Path(tmp) / "out"
            make_shell_entrypoint_repo(repo)

            run_phase1_analysis(
                repo=repo,
                output_dir=out_dir,
                url="fixture://semantic",
                ref="fixture",
                clock=fixed_clock,
                semantic_mode="fake",
                semantic_decision_provider=ExhaustedProvider(),
            )

            audit = yaml.safe_load((out_dir / "04-semantic-analysis.yaml").read_text(encoding="utf-8"))
            self.assertTrue((out_dir / "03-rule-inference.yaml").is_file())

        self.assertEqual(audit["semantic_analysis"]["runs"][0]["run_status"], "provider_error")
        self.assertEqual(audit["semantic_analysis"]["summary"]["provider_error"], 1)

    def test_openai_compatible_without_env_is_audited_without_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            out_dir = Path(tmp) / "out"
            make_shell_entrypoint_repo(repo)

            with patch.dict(
                "os.environ",
                {
                    "SEMANTIC_LLM_BASE_URL": "",
                    "SEMANTIC_LLM_MODEL": "",
                    "SEMANTIC_LLM_API_KEY": "",
                },
                clear=False,
            ):
                run_phase1_analysis(
                    repo=repo,
                    output_dir=out_dir,
                    url="fixture://semantic",
                    ref="fixture",
                    clock=fixed_clock,
                    semantic_mode="openai_compatible",
                )

            audit_text = (out_dir / "04-semantic-analysis.yaml").read_text(encoding="utf-8")
            audit = yaml.safe_load(audit_text)

        self.assertTrue(audit["semantic_analysis"]["enabled"])
        self.assertEqual(audit["semantic_analysis"]["summary"]["provider_config_error"], 1)
        self.assertEqual(audit["semantic_analysis"]["summary"]["runs_attempted"], 0)
        self.assertNotIn("SEMANTIC_LLM_API_KEY", audit_text)


if __name__ == "__main__":
    unittest.main()
