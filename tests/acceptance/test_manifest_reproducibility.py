from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from k8s_agent.render.renderer import ManifestRenderer
from tests.acceptance.test_manifest_renderer import profile_for


class ManifestReproducibilityTests(unittest.TestCase):
    def test_same_profile_produces_byte_identical_bundle(self):
        profile = profile_for(external="public", host="api.example.com")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = ManifestRenderer().render(profile, root / "first")
            second = ManifestRenderer().render(profile, root / "second")

            first_files = {path.relative_to(root / "first").as_posix(): path.read_bytes() for path in (root / "first").rglob("*") if path.is_file()}
            second_files = {path.relative_to(root / "second").as_posix(): path.read_bytes() for path in (root / "second").rglob("*") if path.is_file()}

        self.assertEqual(first.checksum, second.checksum)
        self.assertEqual(first_files, second_files)


if __name__ == "__main__":
    unittest.main()
