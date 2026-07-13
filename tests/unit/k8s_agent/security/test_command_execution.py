from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from k8s_agent.source.git_runner import GitRunner


class CommandExecutionSecurityTests(unittest.TestCase):
    def test_git_runner_executes_argv_without_shell_and_returns_redacted_audit_details(self):
        captured: dict[str, object] = {}
        canary = "task19-command-canary"

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["shell"] = kwargs.get("shell")

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        with tempfile.TemporaryDirectory() as tmp, patch("subprocess.run", fake_run):
            result = GitRunner().run(
                Path(tmp),
                ["remote", "add", "origin", f"https://oauth2:{canary}@github.com/example/app.git"],
            )

        audit = result.audit_details()
        self.assertIsInstance(captured["command"], list)
        self.assertEqual(captured["shell"], False)
        self.assertEqual(audit["tool"], "git")
        self.assertEqual(audit["shell"], "False")
        self.assertIn("remote", audit["args"])
        self.assertNotIn(canary, repr(audit))

    def test_git_runner_audit_environment_lists_only_explicit_keys_without_values(self):
        captured_env: dict[str, str] = {}

        def fake_run(command, **kwargs):
            del command
            captured_env.update(kwargs["env"])

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"PATH": os.environ.get("PATH", "")}, clear=True):
            with patch("subprocess.run", fake_run):
                result = GitRunner().run(Path(tmp), ["status"], env={"GIT_TERMINAL_PROMPT": "0"})

        audit = result.audit_details()
        self.assertIn("GIT_TERMINAL_PROMPT", audit["env_keys"])
        self.assertNotIn("0", audit["env_keys"])
        self.assertIn("GIT_TERMINAL_PROMPT", captured_env)


if __name__ == "__main__":
    unittest.main()
