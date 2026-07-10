from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from preanalyzer.semantic.tools import build_semantic_tool_context, execute_semantic_tool

from tests.unit.semantic_tools.helpers import evidence_model, rules_for, task, write


class InspectEntrypointScriptTests(unittest.TestCase):
    def context(self, repo: Path):
        return build_semantic_tool_context(repo, task(allowed_tools=["inspect_entrypoint_script"], max_source_lines=20), rules_for(), evidence_model("F001"))

    def test_exec_simple_nested_continuation_and_multiple_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "backend" / "entrypoint.sh",
                "#!/bin/sh\n"
                "# comment\n"
                "\n"
                "./scripts/run-server.sh\n"
                "exec gunicorn app.wsgi:application \\\n"
                "  --bind 0.0.0.0:8000\n"
                "uvicorn app.main:app\n",
            )

            result = execute_semantic_tool("inspect_entrypoint_script", {"path": "entrypoint.sh", "max_candidates": 5}, self.context(repo))

        kinds = [obs["kind"] for obs in result.observations]
        self.assertEqual(result.status, "ok")
        self.assertIn("nested_script", kinds)
        self.assertIn("exec_command", kinds)
        self.assertIn("runtime_command", kinds)
        self.assertTrue(any("gunicorn app.wsgi:application --bind" in obs["command_text"] for obs in result.observations))

    def test_complex_shell_constructs_are_observed_not_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "backend" / "entrypoint.sh",
                "TOKEN=supersecret\n"
                "if [ \"$DEBUG\" = 1 ]; then\n"
                "  eval \"$CMD\"\n"
                "fi\n"
                "trap 'echo stop' TERM\n"
                "python app.py &\n",
            )

            result = execute_semantic_tool("inspect_entrypoint_script", {"path": "entrypoint.sh"}, self.context(repo))

        self.assertEqual(result.status, "ok")
        self.assertIn("control_flow", [obs["kind"] for obs in result.observations])
        self.assertIn("eval", [obs["kind"] for obs in result.observations])
        self.assertIn("background_process", [obs["kind"] for obs in result.observations])
        self.assertNotIn("supersecret", str(result.model_dump()))

    def test_script_is_not_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "entrypoint.sh", "touch executed-marker\nexec python app.py\n")

            result = execute_semantic_tool("inspect_entrypoint_script", {"path": "entrypoint.sh"}, self.context(repo))

        self.assertEqual(result.status, "ok")
        self.assertFalse((repo / "backend" / "executed-marker").exists())
