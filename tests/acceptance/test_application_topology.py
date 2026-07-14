from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from k8s_agent.analysis.phase1_adapter import Phase1Adapter
from k8s_agent.analysis.topology_builder import TOPOLOGY_ARTIFACT, TopologyBuilder
from k8s_agent.models.source import GitMetadata, RepositorySource, SourceFingerprint
from k8s_agent.run.store import RunStore


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


def build_topology_artifact(tmp_root: Path, repo_name: str) -> bytes:
    store = RunStore(tmp_root / "runs")
    run_id = f"run-{repo_name}"
    store.run_path(run_id).mkdir(parents=True)
    result = Phase1Adapter(store=store, clock=lambda: FIXED_TIME).run(source_for(FIXTURES / repo_name), run_id)

    topology = TopologyBuilder().build(result)
    artifact = result.analysis_dir / TOPOLOGY_ARTIFACT

    self_check = yaml.safe_load(artifact.read_text(encoding="utf-8"))
    assert self_check["application_topology"]["schema_version"] == topology.schema_version
    return artifact.read_bytes()


class ApplicationTopologyAcceptanceTests(unittest.TestCase):
    def test_topology_artifact_is_deterministic_and_omits_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = build_topology_artifact(root / "first", "fastapi-fullstack-like")
            second = build_topology_artifact(root / "second", "fastapi-fullstack-like")

        self.assertEqual(first, second)
        payload = yaml.safe_load(first)
        topology = payload["application_topology"]
        self.assertEqual([component["component_id"] for component in topology["components"]], ["backend", "db", "frontend"])
        self.assertIn("POSTGRES_PASSWORD", first.decode("utf-8"))
        self.assertNotIn("changethis", first.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
