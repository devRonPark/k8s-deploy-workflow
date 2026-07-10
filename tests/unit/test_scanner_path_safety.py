from datetime import datetime, timezone
from pathlib import Path
import os
import tempfile
import unittest

from preanalyzer.analyzer.scanner import build_inventory, snapshot
from preanalyzer.pipeline import run_phase1_analysis


FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_TIME


def _inventory_paths(inventory) -> set[str]:
    paths: set[str] = set()
    for group in inventory.model_dump().values():
        for item in group:
            paths.add(str(item["path"]))
    return paths


class ScannerPathSafetyTests(unittest.TestCase):
    def test_external_file_symlink_excluded_and_warned(self):
        with tempfile.TemporaryDirectory() as outside, tempfile.TemporaryDirectory() as tmp:
            secret = Path(outside) / "secret.env"
            secret.write_text("SECRET=leaked-value", encoding="utf-8")
            repo = Path(tmp)
            (repo / "app.py").write_text("print('ok')", encoding="utf-8")
            os.symlink(secret, repo / "linked.env")

            snap = snapshot(repo, None, None, fixed_clock)
            inventory = build_inventory(repo, snap)

            self.assertNotIn("linked.env", _inventory_paths(inventory))
            self.assertIn("skipped symlink escaping repository: linked.env", snap.warnings)

    def test_external_dir_symlink_not_descended(self):
        with tempfile.TemporaryDirectory() as outside, tempfile.TemporaryDirectory() as tmp:
            ext = Path(outside) / "conf"
            ext.mkdir()
            (ext / "Dockerfile").write_text("FROM scratch", encoding="utf-8")
            repo = Path(tmp)
            (repo / "app.py").write_text("x = 1", encoding="utf-8")
            os.symlink(ext, repo / "external")

            snap = snapshot(repo, None, None, fixed_clock)
            inventory = build_inventory(repo, snap)

            self.assertNotIn("external/Dockerfile", _inventory_paths(inventory))

    def test_internal_symlink_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            os.symlink(repo / "compose.yaml", repo / "docker-compose.yaml")

            inventory = build_inventory(repo, snapshot(repo, None, None, fixed_clock))
            paths = _inventory_paths(inventory)

            self.assertIn("compose.yaml", paths)
            self.assertIn("docker-compose.yaml", paths)

    def test_broken_symlink_does_not_abort_and_is_warned(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "app.py").write_text("x = 1", encoding="utf-8")
            os.symlink(repo / "missing", repo / "dangling.txt")

            snap = snapshot(repo, None, None, fixed_clock)

            self.assertIn("skipped broken symlink: dangling.txt", snap.warnings)

    def test_external_content_not_in_serialized_output(self):
        with tempfile.TemporaryDirectory() as outside, tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            secret = Path(outside) / "secret.txt"
            secret.write_text("SUPER-SECRET-EXTERNAL", encoding="utf-8")
            repo = Path(tmp)
            (repo / "compose.yaml").write_text(
                "services:\n  api:\n    image: api\n", encoding="utf-8"
            )
            os.symlink(secret, repo / "leak.txt")

            run_phase1_analysis(
                repo=repo,
                output_dir=Path(out),
                url=None,
                ref=None,
                clock=fixed_clock,
            )

            serialized = "\n".join(
                p.read_text(encoding="utf-8") for p in sorted(Path(out).glob("*.yaml"))
            )

            # External file content must never reach any output artifact.
            self.assertNotIn("SUPER-SECRET-EXTERNAL", serialized)
            # The skipped link is recorded as a warning by its in-repo name only.
            self.assertIn("skipped symlink escaping repository: leak.txt", serialized)


if __name__ == "__main__":
    unittest.main()
