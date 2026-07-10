from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from preanalyzer.models.semantic_tools import SemanticToolResult
from preanalyzer.semantic.tools import build_semantic_tool_context, execute_semantic_tool

from tests.unit.semantic_tools.helpers import evidence_model, rules_for, task, write


class SemanticToolRegistryTests(unittest.TestCase):
    def test_dispatch_enforces_allowlist_unknown_tool_and_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "app.py", "print('ok')\n")
            context = build_semantic_tool_context(repo, task(allowed_tools=["read_source_range"]), rules_for(), evidence_model("F001"))

            allowed = execute_semantic_tool("read_source_range", {"path": "app.py", "start_line": 1, "end_line": 1}, context)
            not_allowed = execute_semantic_tool("search_code", {"query": "print"}, context)
            unknown = execute_semantic_tool("made_up", {}, context)
            invalid_schema = execute_semantic_tool("read_source_range", {"path": "app.py", "start_line": "x", "end_line": 1}, context)

        self.assertIsInstance(allowed, SemanticToolResult)
        self.assertEqual(allowed.status, "ok")
        self.assertEqual(not_allowed.status, "blocked")
        self.assertEqual(unknown.status, "unsupported")
        self.assertEqual(invalid_schema.status, "invalid_input")

    def test_unexpected_tool_error_is_structured(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            context = build_semantic_tool_context(repo, task(allowed_tools=["read_source_range"]), rules_for(), evidence_model("F001"))
            object.__setattr__(context, "component_root", None)

            result = execute_semantic_tool("read_source_range", {"path": "app.py", "start_line": 1, "end_line": 1}, context)

        self.assertEqual(result.status, "error")
