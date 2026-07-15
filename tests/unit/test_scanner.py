from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from preanalyzer.analyzer.scanner import build_inventory, snapshot
from preanalyzer.rules_version import RULES_VERSION


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"
FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_TIME


def paths(items):
    return [item["path"] for item in items]


class ScannerTests(unittest.TestCase):
    def test_snapshot_is_deterministic(self):
        repo = FIXTURES / "node-express-like"

        first = snapshot(repo, url="file://node-express-like", ref="main", clock=fixed_clock)
        second = snapshot(repo, url="file://node-express-like", ref="main", clock=fixed_clock)

        self.assertEqual(first.model_dump(), second.model_dump())

    def test_inventory_detects_artifacts_per_fixture(self):
        jpetstore = FIXTURES / "jpetstore-like"
        fastapi = FIXTURES / "fastapi-fullstack-like"
        node = FIXTURES / "node-express-like"

        jpetstore_inventory = build_inventory(jpetstore, snapshot(jpetstore, None, None, fixed_clock))
        fastapi_inventory = build_inventory(fastapi, snapshot(fastapi, None, None, fixed_clock))
        node_inventory = build_inventory(node, snapshot(node, None, None, fixed_clock))

        self.assertEqual(jpetstore_inventory.build_files, [{"path": "pom.xml", "type": "maven"}])
        self.assertEqual(
            jpetstore_inventory.container_files,
            [{"path": "Dockerfile", "type": "dockerfile", "present": False}],
        )

        self.assertEqual(paths(fastapi_inventory.compose_files), ["docker-compose.yml"])
        self.assertEqual(
            fastapi_inventory.container_files,
            [
                {"path": "backend/Dockerfile", "type": "dockerfile", "present": True},
                {"path": "frontend/Dockerfile", "type": "dockerfile", "present": True},
            ],
        )

        self.assertEqual(node_inventory.build_files, [{"path": "package.json", "type": "nodejs"}])
        self.assertEqual(
            node_inventory.container_files,
            [{"path": "Dockerfile", "type": "dockerfile", "present": True}],
        )

    def test_inventory_detects_k8s_manifest_by_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "deployment.yaml").write_text(
                "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: api\n",
                encoding="utf-8",
            )
            (repo / "values.yaml").write_text("image:\n  tag: latest\n", encoding="utf-8")

            inventory = build_inventory(repo, snapshot(repo, None, None, fixed_clock))

        self.assertEqual(
            inventory.kubernetes_manifests,
            [{"path": "deployment.yaml", "type": "kubernetes_manifest"}],
        )

    def test_excluded_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".git").mkdir()
            (repo / ".git" / "config").write_text("[core]\n", encoding="utf-8")
            (repo / "node_modules").mkdir()
            (repo / "node_modules" / "package.json").write_text("{}", encoding="utf-8")
            (repo / "package.json").write_text('{"dependencies": {}}\n', encoding="utf-8")

            snap = snapshot(repo, None, None, fixed_clock)
            inventory = build_inventory(repo, snap)

        self.assertEqual(inventory.build_files, [{"path": "package.json", "type": "nodejs"}])
        self.assertIn(".git/**", snap.excluded_patterns)
        self.assertIn("**/node_modules/**", snap.excluded_patterns)

    def test_inventory_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "z").mkdir()
            (repo / "a").mkdir()
            (repo / "z" / "package.json").write_text("{}", encoding="utf-8")
            (repo / "a" / "pom.xml").write_text("<project></project>", encoding="utf-8")
            (repo / "Dockerfile").write_text("FROM node:20\n", encoding="utf-8")

            inventory = build_inventory(repo, snapshot(repo, None, None, fixed_clock))

        self.assertEqual(paths(inventory.build_files), ["a/pom.xml", "z/package.json"])
        self.assertEqual(paths(inventory.container_files), ["Dockerfile"])

    def test_snapshot_records_versions(self):
        repo = FIXTURES / "node-express-like"

        snap = snapshot(repo, url=None, ref=None, clock=fixed_clock)

        self.assertEqual(snap.analyzer_version, "0.1.0")
        self.assertEqual(snap.rules_version, RULES_VERSION)
        self.assertTrue(hasattr(snap, "commit_sha"))

    def test_compose_variants_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            for name in [
                "docker-compose.yml",
                "docker-compose.override.yml",
                "docker-compose.dev.yml",
                "compose.yaml",
                "compose.prod.yaml",
            ]:
                (repo / name).write_text("services: {}\n", encoding="utf-8")

            inventory = build_inventory(repo, snapshot(repo, None, None, fixed_clock))

        self.assertEqual(
            paths(inventory.compose_files),
            [
                "compose.prod.yaml",
                "compose.yaml",
                "docker-compose.dev.yml",
                "docker-compose.override.yml",
                "docker-compose.yml",
            ],
        )

    def test_env_template_detected_but_env_value_not_inventoried(self):
        repo = FIXTURES / "fastapi-fullstack-like"

        inventory = build_inventory(repo, snapshot(repo, None, None, fixed_clock))
        dumped = inventory.model_dump()

        self.assertIn({"path": ".env", "type": "env"}, dumped["app_configs"])
        self.assertNotIn("changethis", repr(dumped))

    def test_yaml_without_apiversion_not_k8s_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "ci.yaml").write_text("jobs:\n  build: {}\n", encoding="utf-8")

            inventory = build_inventory(repo, snapshot(repo, None, None, fixed_clock))

        self.assertEqual(inventory.kubernetes_manifests, [])

    def test_non_git_directory_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "README.md").write_text("# local\n", encoding="utf-8")

            snap = snapshot(repo, url=None, ref=None, clock=fixed_clock)

        self.assertIsNone(snap.commit_sha)
        self.assertIn("not a git repository", snap.warnings)


class FixtureSanityTests(unittest.TestCase):
    def test_fixture_directories_exist(self):
        for name in ["jpetstore-like", "fastapi-fullstack-like", "node-express-like"]:
            self.assertTrue((FIXTURES / name).is_dir(), name)


if __name__ == "__main__":
    unittest.main()
