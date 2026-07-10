from pathlib import Path
import os
import tempfile
import unittest

from preanalyzer.path_safety import (
    is_excluded_rel_path,
    is_sensitive_rel_path,
    is_within,
    iter_repository_files,
    resolve_repository_path,
)


class PathSafetyTests(unittest.TestCase):
    def test_is_within_true_and_false(self):
        root = Path("/repo").resolve()
        self.assertTrue(is_within(root / "a" / "b.txt", root))
        self.assertFalse(is_within(Path("/etc/passwd").resolve(), root))

    def test_sensitive_and_excluded_predicates(self):
        self.assertTrue(is_sensitive_rel_path("backend/.env"))
        self.assertTrue(is_sensitive_rel_path("keys/id_rsa"))
        self.assertTrue(is_sensitive_rel_path("app/server.pem"))
        self.assertFalse(is_sensitive_rel_path("app/main.py"))
        self.assertTrue(is_excluded_rel_path("node_modules/pkg/index.js"))
        self.assertTrue(is_excluded_rel_path("assets/logo.png"))
        self.assertFalse(is_excluded_rel_path("src/app.py"))

    def test_iter_repository_files_returns_sorted_regular_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.txt").write_text("b", encoding="utf-8")
            (root / "sub").mkdir()
            (root / "sub" / "a.txt").write_text("a", encoding="utf-8")

            files, warnings = iter_repository_files(root)

        rels = [p.relative_to(resolve_repository_path(root)).as_posix() for p in files]
        self.assertEqual(rels, ["b.txt", "sub/a.txt"])
        self.assertEqual(warnings, [])

    def test_internal_file_symlink_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real.txt").write_text("hi", encoding="utf-8")
            os.symlink(root / "real.txt", root / "link.txt")

            files, warnings = iter_repository_files(root)

        rels = {p.relative_to(resolve_repository_path(root)).as_posix() for p in files}
        self.assertIn("link.txt", rels)
        self.assertEqual(warnings, [])

    def test_external_file_symlink_is_blocked_and_warned(self):
        with tempfile.TemporaryDirectory() as outside, tempfile.TemporaryDirectory() as tmp:
            secret = Path(outside) / "secret.txt"
            secret.write_text("TOP-SECRET", encoding="utf-8")
            root = Path(tmp)
            os.symlink(secret, root / "leak.txt")

            files, warnings = iter_repository_files(root)

        rels = {p.relative_to(resolve_repository_path(root)).as_posix() for p in files}
        self.assertNotIn("leak.txt", rels)
        self.assertIn("skipped symlink escaping repository: leak.txt", warnings)

    def test_external_directory_symlink_is_not_descended(self):
        with tempfile.TemporaryDirectory() as outside, tempfile.TemporaryDirectory() as tmp:
            ext_dir = Path(outside) / "d"
            ext_dir.mkdir()
            (ext_dir / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")
            root = Path(tmp)
            os.symlink(ext_dir, root / "extlink")

            files, warnings = iter_repository_files(root)

        rels = {p.relative_to(resolve_repository_path(root)).as_posix() for p in files}
        self.assertEqual(rels, set())

    def test_broken_symlink_is_blocked_and_warned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.symlink(root / "does-not-exist", root / "dangling.txt")

            files, warnings = iter_repository_files(root)

        self.assertEqual(files, [])
        self.assertIn("skipped broken symlink: dangling.txt", warnings)


if __name__ == "__main__":
    unittest.main()
