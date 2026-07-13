import subprocess
import tempfile
import unittest
from pathlib import Path

from k8sagent.errors import RepoAcquisitionError
from k8sagent.procutil import ProcResult
from k8sagent.repo import acquire_git, acquire_local, is_git_url
from tests.unit.agent.helpers import FakeRunner, git_output, make_git_repo


class AcquireLocalTests(unittest.TestCase):
    def test_local_path_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            acquired = acquire_local(str(repo))
            self.assertEqual(acquired.repo_path, repo.resolve())
            self.assertEqual(acquired.source.kind, "local")
            self.assertEqual(acquired.source.location, str(repo.resolve()))

    def test_local_missing_path_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RepoAcquisitionError):
                acquire_local(str(Path(tmp) / "missing"))

    def test_local_with_ref_clones_to_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = make_git_repo(root)
            first = git_output(origin, "rev-parse", "HEAD")
            (origin / "app.py").write_text("print('new')\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=origin, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "second"],
                cwd=origin,
                check=True,
                capture_output=True,
            )
            origin_head = git_output(origin, "rev-parse", "HEAD")

            acquired = acquire_local(str(origin), ref=first, cache_root=root / "cache")

            self.assertTrue(acquired.repo_path.is_relative_to(root / "cache"))
            self.assertEqual(git_output(acquired.repo_path, "rev-parse", "HEAD"), first)
            self.assertEqual(git_output(origin, "rev-parse", "HEAD"), origin_head)
            self.assertEqual(acquired.source.kind, "git_url")
            self.assertTrue(acquired.source.location.startswith("file://"))


class AcquireGitTests(unittest.TestCase):
    def test_ssh_url_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for url in ("git@github.com:a/b.git", "ssh://github.com/a/b.git"):
                with self.assertRaisesRegex(RepoAcquisitionError, "SSH URLs are not supported"):
                    acquire_git(url, None, cache_root=Path(tmp), token=None)

    def test_clone_records_exact_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = make_git_repo(root)
            acquired = acquire_git(origin.resolve().as_uri(), None, cache_root=root / "cache")
            expected = git_output(origin, "rev-parse", "HEAD")
            self.assertEqual(acquired.source.commit_sha, expected)
            self.assertEqual(git_output(acquired.repo_path, "rev-parse", "HEAD"), expected)

    def test_second_acquire_uses_cache_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_root = Path(tmp) / "cache"
            runner = FakeRunner(
                [
                    ProcResult(0, "", ""),
                    ProcResult(0, "abc123\n", ""),
                    ProcResult(0, "", ""),
                    ProcResult(0, "abc123\n", ""),
                    ProcResult(0, "", ""),
                    ProcResult(0, "abc123\n", ""),
                    ProcResult(0, "", ""),
                    ProcResult(0, "abc123\n", ""),
                ]
            )
            acquire_git("file:///tmp/example.git", None, cache_root=cache_root, runner=runner)
            acquire_git("file:///tmp/example.git", None, cache_root=cache_root, runner=runner)
            commands = [call["argv"] for call in runner.calls]
            self.assertEqual(commands[0][:3], ["git", "clone", "--no-tags"])
            self.assertIn("fetch", commands[4])
            self.assertEqual(commands[0][-1], commands[4][2])

    def test_ref_branch_and_sha_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = make_git_repo(root)
            first = git_output(origin, "rev-parse", "HEAD")
            (origin / "app.py").write_text("print('new')\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=origin, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "second"],
                cwd=origin,
                check=True,
                capture_output=True,
            )
            by_sha = acquire_git(origin.resolve().as_uri(), first, cache_root=root / "cache-sha")
            by_branch = acquire_git(origin.resolve().as_uri(), "main", cache_root=root / "cache-branch")
            self.assertEqual(git_output(by_sha.repo_path, "rev-parse", "HEAD"), first)
            self.assertEqual(
                git_output(by_branch.repo_path, "rev-parse", "HEAD"),
                git_output(origin, "rev-parse", "HEAD"),
            )

    def test_unknown_ref_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = make_git_repo(root)
            with self.assertRaisesRegex(RepoAcquisitionError, "ref not found"):
                acquire_git(origin.resolve().as_uri(), "missing-ref", cache_root=root / "cache")

    def test_is_git_url(self):
        self.assertTrue(is_git_url("https://example.com/a.git"))
        self.assertTrue(is_git_url("file:///tmp/a.git"))
        self.assertTrue(is_git_url("git@github.com:a/b.git"))
        self.assertFalse(is_git_url("/tmp/a"))


class TokenSafetyTests(unittest.TestCase):
    def test_token_passed_via_env_not_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            token = "s3cr3t-token"
            runner = FakeRunner(
                [
                    ProcResult(0, "", ""),
                    ProcResult(0, "abc123\n", ""),
                    ProcResult(0, "", ""),
                    ProcResult(0, "abc123\n", ""),
                ]
            )
            acquire_git(
                "https://example.com/private.git",
                None,
                cache_root=Path(tmp),
                token=token,
                runner=runner,
            )
            self.assertFalse(
                any(token in part for call in runner.calls for part in call["argv"])
            )
            self.assertTrue(
                any(
                    call["env"].get("K8S_AGENT_GIT_ASKPASS_PASS") == token
                    for call in runner.calls
                )
            )
            self.assertTrue(all(token in call["redact"] for call in runner.calls))

    def test_askpass_script_contains_no_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            token = "s3cr3t-token"
            runner = FakeRunner(
                [
                    ProcResult(0, "", ""),
                    ProcResult(0, "abc123\n", ""),
                    ProcResult(0, "", ""),
                    ProcResult(0, "abc123\n", ""),
                ]
            )
            acquire_git(
                "https://example.com/private.git",
                None,
                cache_root=Path(tmp),
                token=token,
                runner=runner,
            )
            askpass = Path(tmp) / "askpass.sh"
            self.assertTrue(askpass.is_file())
            self.assertNotIn(token, askpass.read_text(encoding="utf-8"))

    def test_failure_message_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            token = "s3cr3t-token"
            runner = FakeRunner([ProcResult(1, "", f"fatal {token}\n")])
            with self.assertRaises(RepoAcquisitionError) as ctx:
                acquire_git(
                    "https://example.com/private.git",
                    None,
                    cache_root=Path(tmp),
                    token=token,
                    runner=runner,
                )
            self.assertNotIn(token, str(ctx.exception))
            self.assertIn("***", str(ctx.exception))

    def test_url_without_token_gets_no_askpass(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner(
                [
                    ProcResult(0, "", ""),
                    ProcResult(0, "abc123\n", ""),
                    ProcResult(0, "", ""),
                    ProcResult(0, "abc123\n", ""),
                ]
            )
            acquire_git(
                "file:///tmp/public.git",
                None,
                cache_root=Path(tmp),
                token=None,
                runner=runner,
            )
            self.assertFalse(
                any("K8S_AGENT_GIT_ASKPASS_PASS" in call["env"] for call in runner.calls)
            )


if __name__ == "__main__":
    unittest.main()
