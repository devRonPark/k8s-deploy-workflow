from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from preanalyzer.analyzer.parsers.compose import _merge_compose_documents, parse_with_override
from preanalyzer.models.semantic import SemanticTaskBudget
from preanalyzer.models.semantic_tools import SemanticToolResultStatus
from preanalyzer.pipeline import run_phase1_analysis
from preanalyzer.semantic.budget import SemanticToolSession
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


class HardeningReadinessComposeMergeTests(unittest.TestCase):
    def test_command_entrypoint_and_healthcheck_test_are_replaced(self):
        base = {
            "services": {
                "api": {
                    "image": "api",
                    "command": ["python", "old.py"],
                    "entrypoint": ["/old-entrypoint.sh"],
                    "healthcheck": {
                        "test": ["CMD", "curl", "-f", "http://localhost/old"],
                        "interval": "10s",
                        "timeout": "5s",
                    },
                }
            }
        }
        override = {
            "services": {
                "api": {
                    "command": ["python", "new.py"],
                    "entrypoint": ["/new-entrypoint.sh"],
                    "healthcheck": {
                        "test": ["CMD-SHELL", "curl -f http://localhost/new"],
                    },
                }
            }
        }

        merged = _merge_compose_documents(base, override)
        api = merged["services"]["api"]

        self.assertEqual(api["command"], ["python", "new.py"])
        self.assertEqual(api["entrypoint"], ["/new-entrypoint.sh"])
        self.assertEqual(api["healthcheck"]["test"], ["CMD-SHELL", "curl -f http://localhost/new"])
        self.assertEqual(api["healthcheck"]["interval"], "10s")
        self.assertEqual(api["healthcheck"]["timeout"], "5s")

    def test_secrets_and_configs_merge_by_source_or_target(self):
        base = {
            "services": {
                "api": {
                    "image": "api",
                    "secrets": [
                        {"source": "db_password", "target": "db_password"},
                        {"source": "api_token", "target": "api_token"},
                    ],
                    "configs": [
                        {"source": "app_config", "target": "/etc/app/config.yml"},
                        "shared_config",
                    ],
                }
            },
            "secrets": {
                "db_password": {"file": "./db.txt"},
                "api_token": {"file": "./api-token.txt"},
            },
            "configs": {
                "app_config": {"file": "./config.yml"},
                "shared_config": {"file": "./shared.yml"},
            },
        }
        override = {
            "services": {
                "api": {
                    "secrets": [
                        {"source": "db_password", "target": "database_password"},
                        {"source": "session_key", "target": "session_key"},
                    ],
                    "configs": [
                        {"source": "app_config", "target": "/etc/app/config.yml", "mode": 292},
                        "worker_config",
                    ],
                }
            },
            "secrets": {
                "session_key": {"file": "./session.txt"},
            },
            "configs": {
                "worker_config": {"file": "./worker.yml"},
            },
        }

        merged = _merge_compose_documents(base, override)
        api = merged["services"]["api"]

        self.assertEqual(
            api["secrets"],
            [
                {"source": "db_password", "target": "database_password"},
                {"source": "api_token", "target": "api_token"},
                {"source": "session_key", "target": "session_key"},
            ],
        )
        self.assertEqual(
            api["configs"],
            [
                {"source": "app_config", "target": "/etc/app/config.yml", "mode": 292},
                "shared_config",
                "worker_config",
            ],
        )
        self.assertEqual(merged["secrets"]["db_password"], {"file": "./db.txt"})
        self.assertEqual(merged["secrets"]["session_key"], {"file": "./session.txt"})
        self.assertEqual(merged["configs"]["worker_config"], {"file": "./worker.yml"})

    def test_parse_with_override_does_not_warn_for_implemented_merge_only_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "docker-compose.yml"
            override = root / "docker-compose.override.yml"
            base.write_text(
                "services:\n"
                "  api:\n"
                "    image: api\n"
                "    command: [\"python\", \"old.py\"]\n"
                "    entrypoint: [\"/old-entrypoint.sh\"]\n"
                "    healthcheck:\n"
                "      test: [\"CMD\", \"curl\", \"-f\", \"http://localhost/old\"]\n"
                "    secrets:\n"
                "      - source: db_password\n"
                "        target: db_password\n"
                "    configs:\n"
                "      - source: app_config\n"
                "        target: /etc/app/config.yml\n",
                encoding="utf-8",
            )
            override.write_text(
                "services:\n"
                "  api:\n"
                "    command: [\"python\", \"new.py\"]\n"
                "    entrypoint: [\"/new-entrypoint.sh\"]\n"
                "    healthcheck:\n"
                "      test: [\"CMD-SHELL\", \"curl -f http://localhost/new\"]\n"
                "    secrets:\n"
                "      - source: session_key\n"
                "        target: session_key\n"
                "    configs:\n"
                "      - worker_config\n",
                encoding="utf-8",
            )

            parsed = parse_with_override(base, override)

        self.assertEqual(parsed.warnings, [])
        self.assertEqual(parsed.service("api").image, "api")


class HardeningReadinessSemanticBudgetTests(unittest.TestCase):
    def test_semantic_tool_session_reports_budget_status_after_exhaustion(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "app.py", "print('one')\nprint('two')\n")
            context = build_semantic_tool_context(
                repo,
                task(allowed_tools=["read_source_range"], max_source_lines=10),
                rules_for(),
                evidence_model("F001"),
            )
            session = SemanticToolSession(
                context,
                budget=SemanticTaskBudget(max_tool_calls=1, max_source_lines=10),
            )

            first = session.call(
                "read_source_range",
                {"path": "app.py", "start_line": 1, "end_line": 1},
            )
            second = session.call(
                "read_source_range",
                {"path": "app.py", "start_line": 2, "end_line": 2},
            )
            status = session.budget_status()

        self.assertEqual(first.status, SemanticToolResultStatus.OK.value)
        self.assertEqual(second.status, SemanticToolResultStatus.BUDGET_EXHAUSTED.value)
        self.assertEqual(status["status"], "budget_exhausted")
        self.assertEqual(status["reason"], "max_tool_calls")
        self.assertEqual(status["budget"]["max_tool_calls"], 1)
        self.assertEqual(status["budget"]["used_tool_calls"], 1)
        self.assertEqual(status["budget"]["used_files_read"], 1)
        self.assertEqual(status["budget"]["used_source_lines"], 1)
        self.assertTrue(status["partial_evidence_preserved"])


if __name__ == "__main__":
    unittest.main()
