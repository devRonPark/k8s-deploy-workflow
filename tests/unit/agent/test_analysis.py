import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from shutil import copytree

from k8sagent.analysis import OUTPUT_DIR_NAME, run_agent_analysis

FIXTURE = Path("tests/fixtures/repos/node-express-like")
CLOCK = lambda: datetime(2026, 7, 13, tzinfo=timezone.utc)


class AnalysisAdapterTests(unittest.TestCase):
    def _copy_fixture(self, tmp: str) -> Path:
        repo = Path(tmp) / "repo"
        copytree(FIXTURE, repo)
        return repo

    def test_writes_phase1_and_reconciliation_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._copy_fixture(tmp)
            bundle = run_agent_analysis(repo, url=None, ref=None, clock=CLOCK)
            out = repo / OUTPUT_DIR_NAME / "analysis"
            for name in (
                "00-repository-snapshot.yaml",
                "03-rule-inference.yaml",
                "06-component-model.yaml",
                "09-kubernetes-intent.yaml",
                "10-unresolved-questions.yaml",
            ):
                self.assertTrue((out / name).is_file(), name)
            self.assertTrue(bundle.reconciliation.intent.components)

    def test_output_dir_not_reinventoried(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._copy_fixture(tmp)
            run_agent_analysis(repo, url=None, ref=None, clock=CLOCK)
            bundle = run_agent_analysis(repo, url=None, ref=None, clock=CLOCK)
            categories = bundle.inventory.model_dump().values()
            listed = [str(item["path"]) for items in categories for item in items]
            self.assertFalse([p for p in listed if OUTPUT_DIR_NAME in p])

    def test_deterministic_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._copy_fixture(tmp)
            first = run_agent_analysis(repo, url=None, ref=None, clock=CLOCK)
            second = run_agent_analysis(repo, url=None, ref=None, clock=CLOCK)
            self.assertEqual(first.rules, second.rules)
            self.assertEqual(first.evidence, second.evidence)


if __name__ == "__main__":
    unittest.main()
