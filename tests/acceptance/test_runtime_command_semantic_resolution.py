from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from k8s_agent.agent.orchestrator import AgentOrchestrator
from k8s_agent.agent.actions import SemanticActionExecutor
from k8s_agent.analysis.phase1_adapter import Phase1Adapter
from k8s_agent.analysis.topology_builder import TOPOLOGY_ARTIFACT, TopologyBuilder
from k8s_agent.cli import PrepareRequest
from k8s_agent.llm.gateway import LLMGateway
from k8s_agent.models.run import RunState
from k8s_agent.models.source import GitMetadata, RepositorySource, SourceFingerprint
from k8s_agent.run.manager import RunManager
from k8s_agent.run.store import RunStore
from preanalyzer.models.semantic import SemanticCandidate, SemanticResolution, SemanticResolutionStatus
from preanalyzer.models.semantic_agent import ResolutionAction, ToolCallAction


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"
FIXED_TIME = datetime(2026, 7, 13, 6, 7, 8, tzinfo=timezone.utc)


def source_for(path: Path) -> RepositorySource:
    return RepositorySource(
        kind="local",
        path=path,
        acquired_at=FIXED_TIME,
        git=GitMetadata(is_repository=False),
        fingerprint=SourceFingerprint(value="sha256:test", file_count=1),
    )


class RuntimeCommandSemanticResolutionAcceptanceTests(unittest.TestCase):
    def test_shell_entrypoint_runtime_command_is_verified_with_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = RunStore(root / "runs")
            run_id = "run-semantic"
            store.run_path(run_id).mkdir(parents=True)
            source = source_for(FIXTURES / "fastapi-shell-entrypoint")
            phase1 = Phase1Adapter(store=store, clock=lambda: FIXED_TIME).run(source, run_id)
            topology = TopologyBuilder().build(phase1)
            before_topology = (phase1.analysis_dir / TOPOLOGY_ARTIFACT).read_bytes()

            gateway = LLMGateway(provider=EntryPointProvider(), provider_name="fake", model="fake-semantic-model")
            resolution_set = SemanticActionExecutor(gateway=gateway).resolve_runtime_commands(topology, phase1)

            after_topology = (phase1.analysis_dir / TOPOLOGY_ARTIFACT).read_bytes()

        self.assertEqual(before_topology, after_topology)
        self.assertEqual(len(resolution_set.results), 1)
        result = resolution_set.results[0]
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.verification_status, "accepted")
        self.assertEqual(result.accepted_commands, ["uvicorn main:app --host 0.0.0.0 --port 8000"])
        self.assertTrue(result.task_id.startswith("SEM-RC-"))
        self.assertTrue(result.evidence_refs)
        self.assertEqual(result.model, "fake-semantic-model")
        self.assertEqual(result.prompt_version, "runtime-command-semantic/v1")

    def test_prepare_pipeline_merges_verified_semantic_command_into_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = RunManager(
                RunStore(root / "runs"),
                clock=lambda: FIXED_TIME,
                run_id_factory=lambda: "run-semantic-prepare",
            )
            source = source_for(FIXTURES / "fastapi-shell-entrypoint")
            run = manager.create(
                PrepareRequest(
                    repo_url=None,
                    local_path=source.path,
                    ref=None,
                    target="development",
                    non_interactive=False,
                    answers_file=None,
                )
            )
            manager.store.save_yaml(run.run_id, "source.yaml", source.model_dump(mode="json"))
            manager.transition(run.run_id, RunState.ACQUIRING_SOURCE, "source acquisition started")
            gateway = LLMGateway(provider=EntryPointProvider(), provider_name="fake", model="fake-semantic-model")

            outcome = AgentOrchestrator(
                run_manager=manager,
                semantic_executor=SemanticActionExecutor(gateway=gateway),
            ).run(run.run_id)

            profile = yaml.safe_load((outcome.run_root / "profile" / "deployment-profile.yaml").read_text(encoding="utf-8"))
            semantic = yaml.safe_load((outcome.run_root / "agent" / "semantic-resolution.yaml").read_text(encoding="utf-8"))

        command = profile["deployment_profile"]["values"]["/components/backend/workload/command"]
        self.assertEqual(outcome.state, RunState.WAITING_FOR_USER)
        self.assertEqual(command["value"], "uvicorn main:app --host 0.0.0.0 --port 8000")
        self.assertEqual(command["classification"], "llm_semantic_inference")
        self.assertEqual(semantic["semantic_resolution"]["results"][0]["verification_status"], "accepted")


class EntryPointProvider:
    def decide(self, context):
        if not context.collected_evidence:
            return ToolCallAction(
                tool_name="read_source_range",
                arguments={"path": "entrypoint.sh", "start_line": 1, "end_line": 1},
            )
        evidence_id = context.collected_evidence[0]["evidence_id"]
        command = "uvicorn main:app --host 0.0.0.0 --port 8000"
        return ResolutionAction(
            resolution=SemanticResolution(
                task_id=context.task_id,
                status=SemanticResolutionStatus.RESOLVED,
                candidates=[
                    SemanticCandidate(
                        candidate_id="SC-001",
                        component_id=context.component_id,
                        target_field=context.target_field,
                        value={"command": command},
                        classification="llm_semantic_inference",
                        confidence="medium",
                        evidence_refs=[evidence_id],
                    )
                ],
                recommended_candidate_id="SC-001",
                tool_trace_refs=[evidence_id],
            )
        )


if __name__ == "__main__":
    unittest.main()
