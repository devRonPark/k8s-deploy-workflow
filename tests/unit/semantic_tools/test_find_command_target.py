from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from preanalyzer.semantic.tools import build_semantic_tool_context, execute_semantic_tool

from tests.unit.semantic_tools.helpers import evidence_model, rules_for, task, write


class FindCommandTargetTests(unittest.TestCase):
    def context(self, repo: Path):
        return build_semantic_tool_context(repo, task(allowed_tools=["find_command_target"], max_source_lines=20), rules_for(), evidence_model("F001"))

    def test_finds_direct_files_python_module_and_asgi_wsgi_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "app.py", "print('app')\n")
            write(repo / "backend" / "server.js", "console.log('server')\n")
            write(repo / "backend" / "pkg" / "main.py", "def main(): pass\n")
            write(repo / "backend" / "pkg" / "api.py", "app = object()\n")
            write(repo / "backend" / "project" / "wsgi.py", "application = object()\n")
            context = self.context(repo)

            py_file = execute_semantic_tool("find_command_target", {"command": "python app.py"}, context)
            node_file = execute_semantic_tool("find_command_target", {"command": "node server.js"}, context)
            py_module = execute_semantic_tool("find_command_target", {"command": "python -m pkg.main"}, context)
            uvicorn = execute_semantic_tool("find_command_target", {"command": "uvicorn pkg.api:app"}, context)
            gunicorn = execute_semantic_tool("find_command_target", {"command": "gunicorn project.wsgi:application"}, context)

        self.assertEqual(py_file.observations[0]["path"], "backend/app.py")
        self.assertEqual(node_file.observations[0]["path"], "backend/server.js")
        self.assertEqual(py_module.observations[0]["path"], "backend/pkg/main.py")
        self.assertEqual(uvicorn.observations[0]["symbol_hint"], "app")
        self.assertEqual(gunicorn.observations[0]["symbol_hint"], "application")

    def test_missing_outside_and_unsupported_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "outside.py", "print('outside')\n")
            context = self.context(repo)

            missing = execute_semantic_tool("find_command_target", {"command": "python missing.py"}, context)
            outside = execute_semantic_tool("find_command_target", {"command": "python ../outside.py"}, context)
            unsupported = execute_semantic_tool("find_command_target", {"command": "java -cp app.jar com.example.Main"}, context)

        self.assertEqual(missing.status, "no_match")
        self.assertEqual(outside.status, "blocked")
        self.assertEqual(unsupported.status, "unsupported")
