from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from k8s_agent.analysis.phase1_adapter import Phase1Adapter
from k8s_agent.models.source import GitMetadata, RepositorySource, SourceFingerprint
from k8s_agent.run.store import RunStore


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"
FIXED_TIME = datetime(2026, 7, 13, 5, 6, 7, tzinfo=timezone.utc)


def source_for(path: Path) -> RepositorySource:
    return RepositorySource(
        kind="local",
        path=path,
        acquired_at=FIXED_TIME,
        git=GitMetadata(is_repository=False),
        fingerprint=SourceFingerprint(value="sha256:test", file_count=1),
    )


class AgentPhase1IntegrationTests(unittest.TestCase):
    def test_agent_phase1_outputs_match_existing_phase1_shape_for_sample_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = RunStore(root / "runs")
            run_id = "run-node"
            store.run_path(run_id).mkdir(parents=True)

            Phase1Adapter(store=store, clock=lambda: FIXED_TIME).run(
                source_for(FIXTURES / "node-express-like"),
                run_id,
            )

            analysis_dir = store.run_path(run_id) / "analysis"
            snapshot = yaml.safe_load((analysis_dir / "00-repository-snapshot.yaml").read_text(encoding="utf-8"))
            inventory = yaml.safe_load((analysis_dir / "01-artifact-inventory.yaml").read_text(encoding="utf-8"))
            evidence_text = (analysis_dir / "02-evidence-model.yaml").read_text(encoding="utf-8")
            rules = yaml.safe_load((analysis_dir / "03-rule-inference.yaml").read_text(encoding="utf-8"))

        self.assertIn("repository_snapshot", snapshot)
        self.assertIn("artifact_inventory", inventory)
        self.assertIn("evidence_model", yaml.safe_load(evidence_text))
        self.assertIn("rule_inference", rules)
        self.assertNotIn("changethis", evidence_text)


if __name__ == "__main__":
    unittest.main()
