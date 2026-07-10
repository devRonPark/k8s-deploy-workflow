from datetime import datetime, timezone
from pathlib import Path
import unittest

from preanalyzer.analyzer.evidence_builder import build as build_evidence
from preanalyzer.analyzer.parsers.compose import parse as parse_compose
from preanalyzer.analyzer.rule_inference import infer
from preanalyzer.analyzer.scanner import build_inventory, snapshot


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"
FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def fixed_clock():
    return FIXED_TIME


class RuleDependencyEdgeTests(unittest.TestCase):
    def test_depends_on_becomes_internal_dependency_edge(self):
        repo = FIXTURES / "fastapi-fullstack-like"
        inventory = build_inventory(repo, snapshot(repo, None, None, fixed_clock))
        evidence = build_evidence(inventory, {"docker-compose.yml": parse_compose(repo / "docker-compose.yml")})
        rules = infer(evidence)

        self.assertIn(
            {
                "source_component": "backend",
                "target": "db",
                "dependency_type": "internal",
                "source": "compose_depends_on",
                "confidence": "high",
                "evidence_refs": ["F0009"],
                "classification": "rule_inference",
            },
            [candidate.model_dump() for candidate in rules.dependency_edge_candidates],
        )

    def test_database_url_becomes_database_dependency_signal(self):
        repo = FIXTURES / "fastapi-fullstack-like"
        inventory = build_inventory(repo, snapshot(repo, None, None, fixed_clock))
        evidence = build_evidence(inventory, {"docker-compose.yml": parse_compose(repo / "docker-compose.yml")})
        rules = infer(evidence)

        self.assertIn(
            {
                "source_component": "backend",
                "target": "db",
                "dependency_type": "database",
                "source": "compose_environment",
                "confidence": "medium",
                "evidence_refs": ["F0011"],
                "classification": "rule_inference",
            },
            [candidate.model_dump() for candidate in rules.dependency_edge_candidates],
        )


if __name__ == "__main__":
    unittest.main()
