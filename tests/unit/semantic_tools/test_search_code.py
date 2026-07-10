from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from preanalyzer.semantic.tools import build_semantic_tool_context, execute_semantic_tool

from tests.unit.semantic_tools.helpers import evidence_model, rules_for, task, write


class SearchCodeTests(unittest.TestCase):
    def context(self, repo: Path, max_source_lines: int = 20):
        return build_semantic_tool_context(repo, task(allowed_tools=["search_code"], max_source_lines=max_source_lines), rules_for(), evidence_model("F001"))

    def test_literal_search_is_sorted_and_returns_match_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "b.py", "print('serve')\n")
            write(repo / "backend" / "a.py", "serve()\n")

            result = execute_semantic_tool("search_code", {"query": "serve", "max_matches": 5, "context_lines": 0}, self.context(repo))

        self.assertEqual(result.status, "ok")
        self.assertEqual([obs["path"] for obs in result.observations], ["backend/a.py", "backend/b.py"])
        self.assertEqual(result.observations[0]["line"], 1)
        self.assertEqual(result.observations[0]["evidence_ref"], result.evidence[0].evidence_id)

    def test_case_sensitivity_path_prefix_exclusions_limits_and_no_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "src" / "app.py", "Run()\nrun()\n")
            write(repo / "backend" / "tests" / "app.py", "run()\n")
            write(repo / "backend" / "node_modules" / "pkg.js", "run()\n")
            context = self.context(repo)

            sensitive = execute_semantic_tool("search_code", {"query": "run", "path_prefix": "src", "case_sensitive": True}, context)
            insensitive = execute_semantic_tool("search_code", {"query": "run", "path_prefix": "src", "case_sensitive": False}, context)
            limited = execute_semantic_tool("search_code", {"query": "run", "max_matches": 1}, context)
            no_match = execute_semantic_tool("search_code", {"query": "missing"}, context)

        self.assertEqual(len(sensitive.observations), 1)
        self.assertEqual(len(insensitive.observations), 2)
        self.assertEqual(limited.status, "ok")
        self.assertTrue(limited.usage.truncated)
        self.assertEqual(no_match.status, "no_match")
        self.assertNotIn("node_modules", str([obs["path"] for obs in insensitive.observations]))

    def test_invalid_query_prefix_and_source_line_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "app.py", "run()\nrun()\nrun()\n")
            context = self.context(repo, max_source_lines=2)

            empty = execute_semantic_tool("search_code", {"query": ""}, context)
            traversal = execute_semantic_tool("search_code", {"query": "run", "path_prefix": "../"}, context)
            budget = execute_semantic_tool("search_code", {"query": "run", "context_lines": 1, "max_matches": 3}, context)

        self.assertEqual(empty.status, "invalid_input")
        self.assertEqual(traversal.status, "blocked")
        self.assertEqual(budget.status, "ok")
        self.assertLessEqual(budget.usage.source_lines_returned, 2)
        self.assertTrue(budget.usage.truncated)

    def test_secret_like_match_text_is_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "settings.py", "API_TOKEN = 'abc123secretvalue'\n")

            result = execute_semantic_tool("search_code", {"query": "API_TOKEN"}, self.context(repo))

        self.assertEqual(result.status, "ok")
        self.assertNotIn("abc123secretvalue", str(result.model_dump()))
