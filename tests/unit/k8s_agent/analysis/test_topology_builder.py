from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from k8s_agent.analysis.phase1_adapter import Phase1Adapter
from k8s_agent.analysis.topology_builder import TopologyBuilder
from k8s_agent.models.source import GitMetadata, RepositorySource, SourceFingerprint
from k8s_agent.run.store import RunStore
from preanalyzer.models.evidence import EvidenceFact, EvidenceModel
from preanalyzer.models.rule_inference import ComponentCandidate, RuleInferenceSet, RuntimeCommandCandidate


FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "repos"
FIXED_TIME = datetime(2026, 7, 13, 6, 7, 8, tzinfo=timezone.utc)


def source_for(path: Path) -> RepositorySource:
    return RepositorySource(
        kind="local",
        path=path,
        acquired_at=FIXED_TIME,
        git=GitMetadata(is_repository=False),
        fingerprint=SourceFingerprint(value="sha256:test", file_count=1),
    )


def phase1_for(repo_name: str):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = RunStore(root / "runs")
        run_id = f"run-{repo_name}"
        store.run_path(run_id).mkdir(parents=True)
        result = Phase1Adapter(store=store, clock=lambda: FIXED_TIME).run(source_for(FIXTURES / repo_name), run_id)
        return TopologyBuilder().build(result)


class TopologyBuilderTests(unittest.TestCase):
    def test_node_single_service_component_runtime_port_and_command(self):
        topology = phase1_for("node-express-like")
        component = topology.component("root")

        self.assertEqual(component.root_path, ".")
        self.assertEqual(component.role, "application")
        self.assertEqual(component.runtime.language, "nodejs")
        self.assertEqual(component.runtime.framework, "express")
        self.assertEqual(component.ports[0].value, 3000)
        self.assertIn("F", component.ports[0].evidence_refs[0])
        self.assertEqual(component.command.value, '["node", "server.js"]')
        self.assertEqual(topology.conflicts, [])

    def test_fastapi_monorepo_components_dependencies_and_secret_names_only(self):
        topology = phase1_for("fastapi-fullstack-like")

        self.assertEqual([component.component_id for component in topology.components], ["backend", "db", "frontend"])
        backend = topology.component("backend")
        db = topology.component("db")
        self.assertEqual(backend.runtime.language, "python")
        self.assertEqual(backend.runtime.framework, "fastapi")
        self.assertEqual(db.role, "dependency")
        self.assertEqual([edge.target for edge in backend.dependencies], ["db", "db"])
        self.assertEqual([secret.name for secret in db.secrets], ["POSTGRES_PASSWORD"])
        self.assertNotIn("changethis", topology.model_dump_json())

    def test_conflicting_runtime_commands_are_recorded_as_conflict(self):
        evidence = EvidenceModel(
            facts=[
                EvidenceFact(
                    evidence_id="F001",
                    fact_type="dockerfile_cmd",
                    artifact_ref="Dockerfile",
                    source="dockerfile_cmd",
                    classification="observed_fact",
                    value="node server.js",
                ),
                EvidenceFact(
                    evidence_id="F002",
                    fact_type="runtime_command",
                    artifact_ref="deploy.yaml",
                    source="existing_candidate",
                    classification="observed_fact",
                    value="python -m app",
                ),
            ]
        )
        rules = RuleInferenceSet(
            component_candidates=[ComponentCandidate("api", ".", "manual", ["F001"])],
            runtime_command_candidates=[
                RuntimeCommandCandidate("api", "node server.js", "dockerfile_cmd", "high", ["F001"]),
                RuntimeCommandCandidate("api", "python -m app", "existing_candidate", "medium", ["F002"]),
            ],
        )

        topology = TopologyBuilder().build_from_models(evidence, rules)

        self.assertIsNone(topology.component("api").command)
        self.assertEqual(topology.conflicts[0].field_path, "/components/api/runtime/command")
        self.assertEqual(sorted(topology.conflicts[0].evidence_refs), ["F001", "F002"])


if __name__ == "__main__":
    unittest.main()
