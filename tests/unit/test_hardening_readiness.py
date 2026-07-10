from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from preanalyzer.pipeline import run_phase1_analysis
from preanalyzer.semantic.tools import build_semantic_tool_context, execute_semantic_tool

from tests.unit.semantic_tools.helpers import evidence_model, rules_for, task, write


FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_TIME


def read_all_outputs(output_dir: Path) -> str:
    return "\n".join(
        (output_dir / filename).read_text(encoding="utf-8")
        for filename in [
            "00-repository-snapshot.yaml",
            "01-artifact-inventory.yaml",
            "02-evidence-model.yaml",
            "03-rule-inference.yaml",
        ]
    )


class HardeningReadinessSecretTests(unittest.TestCase):
    def test_phase1_outputs_and_warnings_do_not_include_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            output = root / "out"
            write(
                repo / "docker-compose.yml",
                "services:\n"
                "  api:\n"
                "    image: app\n"
                "    environment:\n"
                "      DATABASE_URL: postgresql://admin:real-password@db:5432/app\n"
                "  db:\n"
                "    image: postgres:16\n",
            )
            write(
                repo / "package.json",
                '{"scripts":{"start":"node server.js"},"password":"json-secret",\n',
            )

            _, _, evidence, _ = run_phase1_analysis(
                repo=repo,
                output_dir=output,
                url="fixture://hardening-readiness",
                ref="fixture",
                clock=fixed_clock,
            )

            serialized = read_all_outputs(output)
            warning_text = "\n".join(evidence.warnings)

        self.assertNotIn("real-password", serialized)
        self.assertNotIn("admin:real-password", serialized)
        self.assertNotIn("json-secret", serialized)
        self.assertNotIn("real-password", warning_text)
        self.assertNotIn("json-secret", warning_text)
        self.assertIn("package.json", warning_text)

    def test_semantic_tool_results_do_not_include_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "backend" / "settings.py",
                "API_TOKEN = 'semantic-secret-value'\n"
                "def serve():\n"
                "    return 'ok'\n",
            )
            write(
                repo / "backend" / "entrypoint.sh",
                "PASSWORD=entrypoint-secret\n"
                "exec python settings.py\n",
            )
            context = build_semantic_tool_context(
                repo,
                task(
                    allowed_tools=[
                        "read_source_range",
                        "search_code",
                        "inspect_entrypoint_script",
                    ],
                    max_source_lines=20,
                ),
                rules_for(),
                evidence_model("F001"),
            )

            read_result = execute_semantic_tool(
                "read_source_range",
                {"path": "settings.py", "start_line": 1, "end_line": 3},
                context,
            )
            search_result = execute_semantic_tool(
                "search_code",
                {"query": "API_TOKEN", "max_matches": 5},
                context,
            )
            inspect_result = execute_semantic_tool(
                "inspect_entrypoint_script",
                {"path": "entrypoint.sh", "max_candidates": 5},
                context,
            )

        combined = "\n".join(
            str(result.model_dump())
            for result in [read_result, search_result, inspect_result]
        )
        self.assertNotIn("semantic-secret-value", combined)
        self.assertNotIn("entrypoint-secret", combined)
        self.assertIn("[REDACTED]", combined)


if __name__ == "__main__":
    unittest.main()
