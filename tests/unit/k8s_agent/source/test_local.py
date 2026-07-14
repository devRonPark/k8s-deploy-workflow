from __future__ import annotations

import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from k8s_agent.errors import AgentError
from k8s_agent.source.local import LocalSourceResolver


FIXED_TIME = datetime(2026, 7, 13, 3, 4, 5, tzinfo=timezone.utc)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "commit.gpgsign", "false")


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


class LocalSourceResolverTests(unittest.TestCase):
    def test_resolves_clean_git_repo_to_real_absolute_path_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            init_repo(repo)
            (repo / "package.json").write_text('{"name":"app"}', encoding="utf-8")
            commit_all(repo, "init")

            source = LocalSourceResolver().resolve(repo / ".", FIXED_TIME)

            self.assertEqual(source.kind, "local")
            self.assertEqual(source.path, repo.resolve())
            self.assertTrue(source.git.is_repository)
            self.assertEqual(source.git.head, git(repo, "rev-parse", "HEAD"))
            self.assertFalse(source.git.dirty)
            self.assertEqual(source.git.modified_files, [])
            self.assertEqual(source.git.untracked_files, [])
            self.assertTrue(source.fingerprint.value.startswith("sha256:"))

    def test_dirty_and_untracked_files_are_recorded_and_change_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            init_repo(repo)
            target = repo / "package.json"
            target.write_text('{"name":"app"}', encoding="utf-8")
            commit_all(repo, "init")
            clean = LocalSourceResolver().resolve(repo, FIXED_TIME)

            target.write_text('{"name":"changed"}', encoding="utf-8")
            (repo / "local.txt").write_text("scratch", encoding="utf-8")
            dirty = LocalSourceResolver().resolve(repo, FIXED_TIME)

            self.assertTrue(dirty.git.dirty)
            self.assertEqual(dirty.git.modified_files, ["package.json"])
            self.assertEqual(dirty.git.untracked_files, ["local.txt"])
            self.assertNotEqual(clean.fingerprint.value, dirty.fingerprint.value)

    def test_non_git_directory_is_allowed_with_unknown_git_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "plain"
            repo.mkdir()
            (repo / "app.py").write_text("print('hello')\n", encoding="utf-8")

            source = LocalSourceResolver().resolve(repo, FIXED_TIME)

            self.assertFalse(source.git.is_repository)
            self.assertIsNone(source.git.head)
            self.assertIsNone(source.git.dirty)

    def test_missing_path_is_source_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"

            with self.assertRaisesRegex(AgentError, "SOURCE-101"):
                LocalSourceResolver().resolve(missing, FIXED_TIME)

    def test_git_metadata_queries_disable_optional_locks(self):
        class FakeGit:
            def __init__(self, root: Path) -> None:
                self.root = root
                self.run_envs: list[dict[str, str] | None] = []
                self.output_envs: list[dict[str, str] | None] = []

            def output(self, cwd: Path, args: list[str], env: dict[str, str] | None = None) -> str | None:
                del cwd
                self.output_envs.append(env)
                if args == ["rev-parse", "--show-toplevel"]:
                    return str(self.root)
                if args == ["branch", "--show-current"]:
                    return "main"
                if args == ["rev-parse", "HEAD"]:
                    return "abc123"
                return None

            def run(self, cwd: Path, args: list[str], env: dict[str, str] | None = None):
                del cwd, args
                from k8s_agent.source.git_runner import GitResult

                self.run_envs.append(env)
                return GitResult(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "app.py").write_text("print('hello')\n", encoding="utf-8")
            fake_git = FakeGit(repo.resolve())

            LocalSourceResolver(git=fake_git).resolve(repo, FIXED_TIME)

            envs = fake_git.output_envs + fake_git.run_envs
            self.assertTrue(envs)
            self.assertTrue(all(env and env.get("GIT_OPTIONAL_LOCKS") == "0" for env in envs))


if __name__ == "__main__":
    unittest.main()
