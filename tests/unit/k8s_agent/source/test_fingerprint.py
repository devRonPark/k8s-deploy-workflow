from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from k8s_agent.source.fingerprint import ScanLimits, build_source_fingerprint


class SourceFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_stable_and_changes_with_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("a", encoding="utf-8")
            (root / "b.txt").write_text("b", encoding="utf-8")

            first = build_source_fingerprint(root, ScanLimits())
            second = build_source_fingerprint(root, ScanLimits())
            (root / "b.txt").write_text("changed", encoding="utf-8")
            changed = build_source_fingerprint(root, ScanLimits())

            self.assertEqual(first.value, second.value)
            self.assertEqual(first.file_count, 2)
            self.assertNotEqual(first.value, changed.value)

    def test_excludes_git_agent_state_binary_oversized_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "app.py").write_text("print('safe')\n", encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "HEAD").write_text("secret metadata", encoding="utf-8")
            (root / ".k8s-agent").mkdir()
            (root / ".k8s-agent" / "run.yaml").write_text("agent metadata", encoding="utf-8")
            (root / ".env").write_text("TOKEN=super-secret", encoding="utf-8")
            (root / "binary.bin").write_bytes(b"abc\x00def")
            (root / "large.txt").write_text("0123456789" * 3, encoding="utf-8")
            outside = Path(tmp) / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            os.symlink(outside, root / "outside-link.txt")

            fingerprint = build_source_fingerprint(root, ScanLimits(max_file_bytes=20))

            self.assertEqual(fingerprint.included_files, ["app.py"])
            self.assertIn(".git/HEAD", fingerprint.excluded_paths)
            self.assertIn(".k8s-agent/run.yaml", fingerprint.excluded_paths)
            self.assertIn(".env", fingerprint.excluded_paths)
            self.assertIn("binary.bin", fingerprint.excluded_paths)
            self.assertIn("large.txt", fingerprint.excluded_paths)
            self.assertTrue(any("outside-link.txt" in warning for warning in fingerprint.warnings))


if __name__ == "__main__":
    unittest.main()
