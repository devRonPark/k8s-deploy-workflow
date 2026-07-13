import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from preanalyzer.pipeline import run_analysis


FIXED = datetime(2026, 7, 12, 9, 0, 0, tzinfo=timezone.utc)
REPO = Path("tests/fixtures/repos/node-express-like")
PROFILE = Path("tests/fixtures/profiles/dev-profile.yaml")


def clock():
    return FIXED


class FullOutputTests(unittest.TestCase):
    def test_writes_05_to_13_with_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            report = run_analysis(
                REPO,
                output_dir,
                url=None,
                ref=None,
                clock=clock,
                semantic_mode="disabled",
                profile_path=PROFILE,
            )

            for name in [
                "05-reconciliation-report.yaml",
                "06-component-model.yaml",
                "07-runtime-model.yaml",
                "08-dependency-model.yaml",
                "09-kubernetes-intent.yaml",
                "10-unresolved-questions.yaml",
                "13-validation-report.yaml",
            ]:
                self.assertTrue((output_dir / name).is_file(), name)
            self.assertTrue((output_dir / "12-generated-manifests").is_dir())
            self.assertIn(report.achieved_level, (0, 1))

    def test_determinism_two_runs_identical(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for output_dir in (Path(first), Path(second)):
                run_analysis(
                    REPO,
                    output_dir,
                    url=None,
                    ref=None,
                    clock=clock,
                    semantic_mode="disabled",
                    profile_path=PROFILE,
                )

            for name in ["06-component-model.yaml", "09-kubernetes-intent.yaml"]:
                self.assertEqual(
                    Path(first, name).read_bytes(),
                    Path(second, name).read_bytes(),
                    name,
                )


if __name__ == "__main__":
    unittest.main()
