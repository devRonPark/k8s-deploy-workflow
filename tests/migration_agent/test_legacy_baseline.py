from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from preanalyzer.pipeline import run_phase1_analysis


FIXED_TIME = datetime(2026, 7, 15, 0, 0, 0, tzinfo=timezone.utc)
FIXTURE_ROOT = Path("tests/fixtures/migration_agent")


def fixed_clock() -> datetime:
    return FIXED_TIME


class LegacyBaselineTests(unittest.TestCase):
    def test_node_docker_fixture_has_stable_phase1_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _snapshot, inventory, evidence, rules = run_phase1_analysis(
                repo=FIXTURE_ROOT / "node-docker",
                output_dir=Path(tmp),
                url=None,
                ref=None,
                clock=fixed_clock,
                semantic_mode="disabled",
            )

        self.assertEqual(
            sorted(item["path"] for item in inventory.build_files),
            ["package.json"],
        )
        self.assertEqual(
            sorted(item["path"] for item in inventory.container_files),
            ["Dockerfile"],
        )
        self.assertEqual(evidence.facts_by_type("dockerfile_expose")[0].value, 3000)
        self.assertEqual(evidence.facts_by_type("package_dependency")[0].value["package"], "express")
        self.assertEqual(rules.runtime_candidates[0].framework, "express")
        self.assertEqual(rules.runtime_port_candidates[0].port, 3000)
        self.assertEqual(rules.runtime_command_candidates[0].command, '["node", "server.js"]')

    def test_compose_conflict_fixture_preserves_dockerfile_and_compose_ports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _snapshot, _inventory, evidence, rules = run_phase1_analysis(
                repo=FIXTURE_ROOT / "node-compose-conflict",
                output_dir=Path(tmp),
                url=None,
                ref=None,
                clock=fixed_clock,
                semantic_mode="disabled",
            )

        docker_ports = [fact.value for fact in evidence.facts_by_type("dockerfile_expose")]
        compose_ports = [fact.value["container_port"] for fact in evidence.facts_by_type("compose_port")]
        candidate_ports = [candidate.port for candidate in rules.runtime_port_candidates]

        self.assertEqual(docker_ports, [8080])
        self.assertEqual(compose_ports, [8081])
        self.assertEqual(candidate_ports, [8080, 8081])


if __name__ == "__main__":
    unittest.main()
