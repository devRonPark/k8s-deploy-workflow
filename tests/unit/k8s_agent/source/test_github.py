from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from k8s_agent.errors import AgentError
from k8s_agent.source.git_runner import GitResult
from k8s_agent.source.github import GitHubSourceResolver, sanitize_github_url
from k8s_agent.source.workspace import WorkspaceManager


FIXED_TIME = datetime(2026, 7, 13, 4, 5, 6, tzinfo=timezone.utc)


class FakeGitRunner:
    def __init__(self, head: str = "abc123", fail_fetch: GitResult | None = None) -> None:
        self.head = head
        self.fail_fetch = fail_fetch
        self.calls: list[tuple[Path, list[str], dict[str, str] | None]] = []

    def run(self, cwd: Path, args: list[str], env: dict[str, str] | None = None) -> GitResult:
        self.calls.append((cwd, args, env))
        if "fetch" in args and self.fail_fetch is not None:
            return self.fail_fetch
        return GitResult(returncode=0, stdout="", stderr="")

    def output(self, cwd: Path, args: list[str], env: dict[str, str] | None = None) -> str | None:
        self.calls.append((cwd, args, env))
        if args == ["rev-parse", "HEAD"]:
            return self.head
        return None


class GitHubSourceResolverTests(unittest.TestCase):
    def test_acquire_pins_ref_with_depth_one_fetch_and_detached_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceManager(Path(tmp)).create("run-001")
            git = FakeGitRunner(head="deadbeef")

            acquired = GitHubSourceResolver(git=git).acquire(
                "https://github.com/example/app.git",
                "main",
                workspace,
                FIXED_TIME,
            )

            self.assertEqual(acquired.requested_ref, "main")
            self.assertEqual(acquired.resolved_commit, "deadbeef")
            self.assertEqual(acquired.source.git.head, "deadbeef")
            self.assertEqual(acquired.source.path, workspace.source_path)
            commands = [args for _, args, _ in git.calls]
            self.assertIn(["init"], commands)
            self.assertIn(["remote", "add", "origin", "https://github.com/example/app.git"], commands)
            fetch = [args for args in commands if "fetch" in args][0]
            checkout = [args for args in commands if "checkout" in args][0]
            self.assertIn("core.hooksPath=/dev/null", fetch)
            self.assertIn("submodule.recurse=false", fetch)
            self.assertIn("fetch", fetch)
            self.assertIn("--depth", fetch)
            self.assertIn("checkout", checkout)
            self.assertIn("--detach", checkout)
            envs = [env for _, _, env in git.calls if env is not None]
            self.assertTrue(envs)
            self.assertTrue(all(env.get("GIT_CONFIG_GLOBAL") == "/dev/null" for env in envs))

    def test_embedded_credentials_are_removed_from_saved_url_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceManager(Path(tmp)).create("run-002")
            token_url = "https://token123@github.com/example/private.git"
            git = FakeGitRunner(fail_fetch=GitResult(returncode=128, stdout="", stderr="fatal: token123 denied"))

            with self.assertRaises(AgentError) as raised:
                GitHubSourceResolver(git=git).acquire(token_url, "main", workspace, FIXED_TIME)

            text = str(raised.exception)
            self.assertIn("SOURCE-202", text)
            self.assertNotIn("token123", text)
            remote_add = [args for _, args, _ in git.calls if args[:3] == ["remote", "add", "origin"]][0]
            self.assertEqual(remote_add[-1], "https://github.com/example/private.git")

    def test_missing_ref_is_reported_as_source_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceManager(Path(tmp)).create("run-003")
            git = FakeGitRunner(fail_fetch=GitResult(returncode=128, stdout="", stderr="fatal: couldn't find remote ref nope"))

            with self.assertRaisesRegex(AgentError, "SOURCE-201"):
                GitHubSourceResolver(git=git).acquire(
                    "git@github.com:example/app.git",
                    "nope",
                    workspace,
                    FIXED_TIME,
                )

    def test_sanitizes_credential_bearing_url_variants(self):
        self.assertEqual(
            sanitize_github_url("ssh://token123@github.com/example/private.git"),
            "ssh://github.com/example/private.git",
        )
        self.assertEqual(
            sanitize_github_url("token123@github.com:example/private.git"),
            "github.com:example/private.git",
        )


if __name__ == "__main__":
    unittest.main()
