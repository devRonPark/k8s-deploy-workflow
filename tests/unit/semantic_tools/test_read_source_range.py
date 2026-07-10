from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from preanalyzer.semantic.tools import build_semantic_tool_context, execute_semantic_tool

from tests.unit.semantic_tools.helpers import evidence_model, rules_for, task, write


class ReadSourceRangeTests(unittest.TestCase):
    def context(self, repo: Path):
        return build_semantic_tool_context(repo, task(allowed_tools=["read_source_range"], max_source_lines=5), rules_for(), evidence_model("F001"))

    def test_reads_limited_range_with_line_numbers_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "app.py", "one\ntwo\nthree\n")

            result = execute_semantic_tool("read_source_range", {"path": "app.py", "start_line": 2, "end_line": 3}, self.context(repo))

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.evidence[0].path, "backend/app.py")
        self.assertEqual(result.evidence[0].start_line, 2)
        self.assertIn("2: two", result.evidence[0].excerpt)
        self.assertEqual(result.usage.source_lines_returned, 2)

    def test_rejects_bad_line_ranges_and_budget_excess(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "app.py", "one\ntwo\nthree\nfour\nfive\nsix\n")
            context = self.context(repo)

            bad_range = execute_semantic_tool("read_source_range", {"path": "app.py", "start_line": 3, "end_line": 2}, context)
            too_many = execute_semantic_tool("read_source_range", {"path": "app.py", "start_line": 1, "end_line": 6}, context)
            beyond_eof = execute_semantic_tool("read_source_range", {"path": "app.py", "start_line": 1, "end_line": 99}, context)

        self.assertEqual(bad_range.status, "invalid_input")
        self.assertEqual(too_many.status, "invalid_input")
        self.assertEqual(beyond_eof.status, "invalid_input")

    def test_blocks_traversal_absolute_symlink_sensitive_binary_and_large_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "app.py", "print('safe')\n")
            write(repo / "backend" / ".env", "TOKEN=secret\n")
            write(repo / "backend" / "id_rsa", "PRIVATE KEY\n")
            write(repo / "backend" / "binary.dat", b"abc\x00def")
            write(repo / "backend" / "huge.py", "x" * (1024 * 1024 + 1))
            write(repo / "outside.py", "print('outside')\n")
            (repo / "backend" / "outside.py").symlink_to(repo / "outside.py")
            context = self.context(repo)

            traversal = execute_semantic_tool("read_source_range", {"path": "../outside.py", "start_line": 1, "end_line": 1}, context)
            absolute = execute_semantic_tool("read_source_range", {"path": (repo / "backend" / "app.py").as_posix(), "start_line": 1, "end_line": 1}, context)
            symlink = execute_semantic_tool("read_source_range", {"path": "outside.py", "start_line": 1, "end_line": 1}, context)
            env = execute_semantic_tool("read_source_range", {"path": ".env", "start_line": 1, "end_line": 1}, context)
            key = execute_semantic_tool("read_source_range", {"path": "id_rsa", "start_line": 1, "end_line": 1}, context)
            binary = execute_semantic_tool("read_source_range", {"path": "binary.dat", "start_line": 1, "end_line": 1}, context)
            large = execute_semantic_tool("read_source_range", {"path": "huge.py", "start_line": 1, "end_line": 1}, context)

        self.assertEqual(traversal.status, "blocked")
        self.assertEqual(absolute.status, "blocked")
        self.assertEqual(symlink.status, "blocked")
        self.assertEqual(env.status, "blocked")
        self.assertEqual(key.status, "blocked")
        self.assertEqual(binary.status, "unsupported")
        self.assertEqual(large.status, "unsupported")
        self.assertNotIn(str(repo), traversal.message or "")

    def test_redacts_secret_like_values_before_hashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "settings.py", "API_TOKEN = 'abc123secretvalue'\npassword: hunter2\n")
            context = self.context(repo)

            first = execute_semantic_tool("read_source_range", {"path": "settings.py", "start_line": 1, "end_line": 2}, context)
            second = execute_semantic_tool("read_source_range", {"path": "settings.py", "start_line": 1, "end_line": 2}, context)

        excerpt = first.evidence[0].excerpt
        self.assertNotIn("abc123secretvalue", excerpt)
        self.assertNotIn("hunter2", excerpt)
        self.assertEqual(first.evidence[0].evidence_id, second.evidence[0].evidence_id)
        self.assertTrue(first.evidence[0].evidence_id.startswith("SE-"))

    def test_evidence_id_changes_with_range_or_excerpt_and_hash_matches_excerpt(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "app.py", "one\ntwo\nthree\n")
            context = self.context(repo)

            first = execute_semantic_tool("read_source_range", {"path": "app.py", "start_line": 1, "end_line": 1}, context)
            second = execute_semantic_tool("read_source_range", {"path": "app.py", "start_line": 2, "end_line": 2}, context)
            repeat = execute_semantic_tool("read_source_range", {"path": "app.py", "start_line": 1, "end_line": 1}, context)

        self.assertNotEqual(first.evidence[0].evidence_id, second.evidence[0].evidence_id)
        self.assertEqual(first.evidence[0].evidence_id, repeat.evidence[0].evidence_id)
        self.assertEqual(first.evidence[0].path, "backend/app.py")
        self.assertEqual(
            first.evidence[0].excerpt_hash,
            hashlib.sha256(first.evidence[0].excerpt.encode("utf-8")).hexdigest(),
        )
