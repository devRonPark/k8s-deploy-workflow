from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from k8s_agent.source.git_runner import GitRunner


class GitRunnerTests(unittest.TestCase):
    def test_scrubs_inherited_git_execution_environment(self):
        captured_env: dict[str, str] = {}

        def fake_run(command, **kwargs):
            del command
            captured_env.update(kwargs["env"])

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        poisoned = {
            "PATH": os.environ.get("PATH", ""),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.sshCommand",
            "GIT_CONFIG_VALUE_0": "evil",
            "GIT_SSH_COMMAND": "evil-ssh",
            "GIT_ASKPASS": "evil-askpass",
            "SSH_ASKPASS": "evil-ssh-askpass",
            "GIT_ALLOW_PROTOCOL": "ext:ssh:file",
        }

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, poisoned, clear=True):
            with patch("subprocess.run", fake_run):
                GitRunner().run(Path(tmp), ["status"])

        self.assertIn("PATH", captured_env)
        for key in poisoned:
            if key != "PATH":
                self.assertNotIn(key, captured_env)


if __name__ == "__main__":
    unittest.main()
