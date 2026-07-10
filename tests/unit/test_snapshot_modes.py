from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

from preanalyzer.analyzer.scanner import snapshot
from preanalyzer.pipeline import run_phase1_analysis


FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_TIME


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _snapshot_document(out_dir: Path) -> dict:
    text = (out_dir / "00-repository-snapshot.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)["repository_snapshot"]


class WorkspaceHashTests(unittest.TestCase):
    def test_snapshot_records_mode_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "package.json").write_text('{"name": "app"}', encoding="utf-8")
            snap = snapshot(repo, url=None, ref=None, clock=fixed_clock)

        self.assertEqual(snap.snapshot_mode, "workspace")
        self.assertTrue(snap.workspace_hash.startswith("sha256:"))

    def test_workspace_hash_changes_when_file_content_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = repo / "package.json"
            target.write_text('{"name": "a"}', encoding="utf-8")
            before = snapshot(repo, None, None, fixed_clock).workspace_hash

            target.write_text('{"name": "b"}', encoding="utf-8")
            after = snapshot(repo, None, None, fixed_clock).workspace_hash

        self.assertNotEqual(before, after)

    def test_workspace_hash_is_stable_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "a.txt").write_text("a", encoding="utf-8")
            (repo / "b.txt").write_text("b", encoding="utf-8")
            first = snapshot(repo, None, None, fixed_clock).workspace_hash
            second = snapshot(repo, None, None, fixed_clock).workspace_hash

        self.assertEqual(first, second)


class WorkspaceGitStatusTests(unittest.TestCase):
    def test_clean_worktree_is_not_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_repo(repo)
            (repo / "package.json").write_text('{"name": "app"}', encoding="utf-8")
            _commit_all(repo, "init")

            snap = snapshot(repo, None, None, fixed_clock)

        self.assertFalse(snap.workspace_dirty)
        self.assertEqual(snap.modified_files, [])
        self.assertEqual(snap.untracked_files, [])

    def test_modified_and_untracked_files_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_repo(repo)
            (repo / "package.json").write_text('{"name": "app"}', encoding="utf-8")
            _commit_all(repo, "init")

            (repo / "package.json").write_text('{"name": "app2"}', encoding="utf-8")
            (repo / "local.txt").write_text("scratch", encoding="utf-8")

            snap = snapshot(repo, None, None, fixed_clock)

        self.assertTrue(snap.workspace_dirty)
        self.assertEqual(snap.modified_files, ["package.json"])
        self.assertEqual(snap.untracked_files, ["local.txt"])

    def test_non_git_directory_reports_unknown_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "package.json").write_text('{"name": "app"}', encoding="utf-8")
            snap = snapshot(repo, None, None, fixed_clock)

        self.assertIsNone(snap.workspace_dirty)


class CommitModeReproducibilityTests(unittest.TestCase):
    def _run(self, repo: Path, out_dir: Path, mode: str) -> dict:
        run_phase1_analysis(
            repo=repo,
            output_dir=out_dir,
            url="fixture://commit-mode",
            ref="fixture",
            clock=fixed_clock,
            mode=mode,
        )
        return _snapshot_document(out_dir)

    def test_commit_mode_ignores_dirty_working_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            _init_repo(repo)
            (repo / "Dockerfile").write_text("FROM node:18\nEXPOSE 3000\n", encoding="utf-8")
            _commit_all(repo, "init")

            clean_out = root / "clean"
            clean_snap = self._run(repo, clean_out, "commit")
            clean_bytes = (clean_out / "03-rule-inference.yaml").read_bytes()

            # Dirty the working tree with an uncommitted edit + an untracked file.
            (repo / "Dockerfile").write_text("FROM node:20\nEXPOSE 9999\n", encoding="utf-8")
            (repo / "extra.env").write_text("SECRET=leak", encoding="utf-8")

            dirty_out = root / "dirty"
            dirty_snap = self._run(repo, dirty_out, "commit")
            dirty_bytes = (dirty_out / "03-rule-inference.yaml").read_bytes()

        self.assertEqual(clean_snap["snapshot_mode"], "commit")
        self.assertEqual(clean_snap["workspace_hash"], dirty_snap["workspace_hash"])
        self.assertEqual(clean_bytes, dirty_bytes)
        # Uncommitted content must never appear in commit-mode output.
        self.assertNotIn(b"9999", dirty_bytes)
        self.assertNotIn(b"leak", dirty_bytes)

    def test_workspace_mode_reflects_dirty_edit_in_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            _init_repo(repo)
            (repo / "Dockerfile").write_text("FROM node:18\nEXPOSE 3000\n", encoding="utf-8")
            _commit_all(repo, "init")

            clean_snap = self._run(repo, root / "clean", "workspace")

            (repo / "Dockerfile").write_text("FROM node:20\nEXPOSE 8080\n", encoding="utf-8")
            dirty_snap = self._run(repo, root / "dirty", "workspace")

        self.assertNotEqual(clean_snap["workspace_hash"], dirty_snap["workspace_hash"])
        self.assertTrue(dirty_snap["workspace_dirty"])


if __name__ == "__main__":
    unittest.main()
