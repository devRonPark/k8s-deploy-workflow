from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

import yaml

from preanalyzer.output.scanner_artifacts import run_scanner_analysis


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"
FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_TIME


class SampleRepoScannerAcceptanceTests(unittest.TestCase):
    def test_sample_repositories_generate_snapshot_and_inventory_artifacts(self):
        expectations = {
            "jpetstore-like": {
                "build_files": [{"path": "pom.xml", "type": "maven"}],
                "container_files": [{"path": "Dockerfile", "type": "dockerfile", "present": False}],
                "compose_files": [],
            },
            "fastapi-fullstack-like": {
                "build_files": [
                    {"path": "backend/pyproject.toml", "type": "python_pyproject"},
                    {"path": "frontend/package.json", "type": "nodejs"},
                ],
                "container_files": [
                    {"path": "backend/Dockerfile", "type": "dockerfile", "present": True},
                    {"path": "frontend/Dockerfile", "type": "dockerfile", "present": True},
                ],
                "compose_files": [{"path": "docker-compose.yml", "type": "compose"}],
            },
            "node-express-like": {
                "build_files": [{"path": "package.json", "type": "nodejs"}],
                "container_files": [{"path": "Dockerfile", "type": "dockerfile", "present": True}],
                "compose_files": [],
            },
            "compose-variant-like": {
                "build_files": [],
                "container_files": [{"path": "Dockerfile", "type": "dockerfile", "present": False}],
                "compose_files": [
                    {"path": "compose.override.yml", "type": "compose"},
                    {"path": "compose.yaml", "type": "compose"},
                    {"path": "docker-compose.dev.yml", "type": "compose"},
                ],
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)

            for repo_name, expected in expectations.items():
                out_dir = output_root / repo_name
                run_scanner_analysis(
                    repo=FIXTURES / repo_name,
                    output_dir=out_dir,
                    url=f"fixture://{repo_name}",
                    ref="fixture",
                    clock=fixed_clock,
                )

                snapshot_path = out_dir / "00-repository-snapshot.yaml"
                inventory_path = out_dir / "01-artifact-inventory.yaml"
                self.assertTrue(snapshot_path.is_file(), repo_name)
                self.assertTrue(inventory_path.is_file(), repo_name)

                snapshot = yaml.safe_load(snapshot_path.read_text(encoding="utf-8"))
                inventory = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))

                self.assertEqual(snapshot["repository_snapshot"]["url"], f"fixture://{repo_name}")
                self.assertEqual(snapshot["repository_snapshot"]["ref"], "fixture")
                self.assertEqual(snapshot["repository_snapshot"]["analyzed_at"], "2026-07-10T09:00:00Z")
                self.assertEqual(inventory["artifact_inventory"]["build_files"], expected["build_files"])
                self.assertEqual(inventory["artifact_inventory"]["container_files"], expected["container_files"])
                self.assertEqual(inventory["artifact_inventory"]["compose_files"], expected["compose_files"])

                serialized_inventory = inventory_path.read_text(encoding="utf-8")
                self.assertNotIn("changethis", serialized_inventory)


if __name__ == "__main__":
    unittest.main()
