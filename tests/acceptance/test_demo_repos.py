import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from preanalyzer.models.semantic import SemanticCandidate, SemanticResolution, SemanticResolutionStatus
from preanalyzer.models.semantic_agent import ResolutionAction, ToolCallAction
from preanalyzer.pipeline import run_analysis


FIXED = datetime(2026, 7, 12, 9, 0, 0, tzinfo=timezone.utc)
PROFILE = Path("tests/fixtures/profiles/dev-profile.yaml")


def clock():
    return FIXED


class _ResolveShellEntrypoint:
    def __init__(self) -> None:
        self.contexts = []

    def decide(self, context):
        self.contexts.append(context)
        if len(self.contexts) == 1:
            return ToolCallAction(
                tool_name="inspect_entrypoint_script",
                arguments={"path": "entrypoint.sh"},
            )
        evidence_ref = context.collected_evidence[0]["evidence_id"]
        return ResolutionAction(
            resolution=SemanticResolution(
                task_id=context.task_id,
                status=SemanticResolutionStatus.RESOLVED,
                candidates=[
                    SemanticCandidate(
                        candidate_id="SC-1",
                        component_id=context.component_id,
                        target_field=context.target_field,
                        value={"command": "uvicorn main:app --host 0.0.0.0 --port 8000"},
                        classification="llm_semantic_inference",
                        confidence="medium",
                        evidence_refs=[evidence_ref],
                    )
                ],
                recommended_candidate_id="SC-1",
                tool_trace_refs=[evidence_ref],
            )
        )


class ShellEntrypointTests(unittest.TestCase):
    def test_shell_entrypoint_agent_resolves_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            run_analysis(
                Path("tests/fixtures/repos/fastapi-shell-entrypoint"),
                output_dir,
                url=None,
                ref=None,
                clock=clock,
                semantic_mode="fake",
                semantic_decision_provider=_ResolveShellEntrypoint(),
                profile_path=PROFILE,
            )
            intent = yaml.safe_load((output_dir / "09-kubernetes-intent.yaml").read_text())

        backend = next(
            component
            for component in intent["kubernetes_intent"]["components"]
            if component["component_id"] == "backend"
        )
        self.assertEqual(
            backend["workload"]["command"]["value"],
            "uvicorn main:app --host 0.0.0.0 --port 8000",
        )
        self.assertEqual(backend["workload"]["command"]["source"], "llm_semantic_inference")


if __name__ == "__main__":
    unittest.main()
