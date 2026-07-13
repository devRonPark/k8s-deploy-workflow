from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from k8s_agent.analysis.phase1_adapter import Phase1Adapter
from k8s_agent.models.source import GitMetadata, RepositorySource, SourceFingerprint
from k8s_agent.run.store import RunStore


FIXED_TIME = datetime(2026, 7, 13, 5, 6, 7, tzinfo=timezone.utc)


def clock() -> datetime:
    return FIXED_TIME


def source_for(path: Path) -> RepositorySource:
    return RepositorySource(
        kind="local",
        path=path,
        acquired_at=FIXED_TIME,
        git=GitMetadata(is_repository=False),
        fingerprint=SourceFingerprint(value="sha256:test", file_count=1),
    )


class Phase1AdapterTests(unittest.TestCase):
    def test_runs_phase1_into_analysis_dir_and_records_checksums_and_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "Dockerfile").write_text("FROM node:18\nEXPOSE 3000\n", encoding="utf-8")
            store = RunStore(root / "runs")
            run_id = "run-phase1"
            store.run_path(run_id).mkdir(parents=True)

            result = Phase1Adapter(store=store, clock=clock).run(source_for(repo), run_id)

            analysis_dir = store.run_path(run_id) / "analysis"
            expected = [
                "00-repository-snapshot.yaml",
                "01-artifact-inventory.yaml",
                "02-evidence-model.yaml",
                "03-rule-inference.yaml",
            ]
            for filename in expected:
                self.assertTrue((analysis_dir / filename).is_file(), filename)
                self.assertTrue(result.checksums[filename].startswith("sha256:"))
            event_lines = (store.event_file(run_id)).read_text(encoding="utf-8").splitlines()
            self.assertEqual(json.loads(event_lines[-1])["event_type"], "phase1_completed")

    def test_parse_warning_is_preserved_without_failing_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "package.json").write_text("{", encoding="utf-8")
            (repo / "Dockerfile").write_text("FROM node:18\nEXPOSE 3000\n", encoding="utf-8")
            store = RunStore(root / "runs")
            run_id = "run-warning"
            store.run_path(run_id).mkdir(parents=True)

            Phase1Adapter(store=store, clock=clock).run(source_for(repo), run_id)

            evidence = yaml.safe_load(
                (store.run_path(run_id) / "analysis" / "02-evidence-model.yaml").read_text(encoding="utf-8")
            )
            warnings = evidence["evidence_model"]["warnings"]
            self.assertEqual(len(warnings), 1)
            self.assertEqual(json.loads(warnings[0])["parser"], "nodejs")


if __name__ == "__main__":
    unittest.main()
