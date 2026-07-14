from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from k8s_agent.cli import PrepareRequest
from k8s_agent.models.source import ScanLimits
from k8s_agent.run.manager import RunManager
from k8s_agent.run.store import RunStore
from k8s_agent.source.fingerprint import build_source_fingerprint


class SourceBoundarySecurityTests(unittest.TestCase):
    def test_token_git_url_is_sanitized_before_run_storage(self):
        canary = "ghp_task19_secret_canary"
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunManager(RunStore(Path(tmp)), run_id_factory=lambda: "run-source")
            record = manager.create(
                PrepareRequest(
                    repo_url=f"https://oauth2:{canary}@github.com/example/app.git",
                    local_path=None,
                    ref="main",
                    target="development",
                    non_interactive=False,
                    answers_file=None,
                )
            )

            run_yaml = (Path(tmp) / "run-source" / "run.yaml").read_text(encoding="utf-8")

        self.assertEqual(record.source.value, "https://github.com/example/app.git")
        self.assertNotIn(canary, run_yaml)

    def test_source_outside_symlink_is_not_read_or_fingerprinted(self):
        canary = "TASK19_SYMLINK_CANARY"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "app.py").write_text("print('safe')\n", encoding="utf-8")
            outside = Path(tmp) / "outside-secret.txt"
            outside.write_text(canary, encoding="utf-8")
            os.symlink(outside, root / "linked-secret.txt")

            fingerprint = build_source_fingerprint(root, ScanLimits())
            dumped = repr(fingerprint.model_dump())

        self.assertEqual(fingerprint.included_files, ["app.py"])
        self.assertNotIn(canary, dumped)
        self.assertTrue(any("linked-secret.txt" in warning for warning in fingerprint.warnings))


if __name__ == "__main__":
    unittest.main()
