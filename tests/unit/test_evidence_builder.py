from datetime import datetime, timezone
from pathlib import Path
import unittest

from preanalyzer.analyzer.evidence_builder import build as build_evidence
from preanalyzer.analyzer.parsers.compose import parse as parse_compose
from preanalyzer.analyzer.parsers.dockerfile import parse as parse_dockerfile
from preanalyzer.analyzer.parsers.maven import parse as parse_maven
from preanalyzer.analyzer.parsers.nodejs import parse as parse_nodejs
from preanalyzer.analyzer.parsers.python_pkg import parse_pyproject
from preanalyzer.analyzer.scanner import build_inventory, snapshot


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"
FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_TIME


def inventory_for(repo: Path):
    return build_inventory(repo, snapshot(repo, None, None, fixed_clock))


def without_id(fact):
    dumped = fact.model_dump()
    dumped.pop("evidence_id")
    return dumped


class EvidenceBuilderTests(unittest.TestCase):
    def test_evidence_records_file_presence_and_absence(self):
        repo = FIXTURES / "jpetstore-like"

        evidence = build_evidence(inventory_for(repo), parsed_artifacts={})

        facts = evidence.facts_by_type("artifact_presence")
        self.assertIn(
            {
                "fact_type": "artifact_presence",
                "artifact_ref": "pom.xml",
                "source": "artifact_inventory",
                "classification": "observed_fact",
                "value": {"path": "pom.xml", "type": "maven", "present": True},
            },
            [without_id(fact) for fact in facts],
        )
        self.assertIn(
            {
                "fact_type": "artifact_presence",
                "artifact_ref": "Dockerfile",
                "source": "artifact_inventory",
                "classification": "observed_fact",
                "value": {"path": "Dockerfile", "type": "dockerfile", "present": False},
            },
            [without_id(fact) for fact in facts],
        )

    def test_parsed_fields_become_observed_facts(self):
        repo = FIXTURES / "fastapi-fullstack-like"
        parsed_artifacts = {
            "backend/Dockerfile": parse_dockerfile(repo / "backend" / "Dockerfile"),
            "docker-compose.yml": parse_compose(repo / "docker-compose.yml"),
            "backend/pyproject.toml": parse_pyproject(repo / "backend" / "pyproject.toml"),
            "frontend/package.json": parse_nodejs(repo / "frontend" / "package.json"),
        }

        evidence = build_evidence(inventory_for(repo), parsed_artifacts)

        dumped = [without_id(fact) for fact in evidence.facts]
        self.assertIn(
            {
                "fact_type": "dockerfile_expose",
                "artifact_ref": "backend/Dockerfile",
                "source": "dockerfile_expose",
                "classification": "observed_fact",
                "value": 8000,
            },
            dumped,
        )
        self.assertIn(
            {
                "fact_type": "compose_depends_on",
                "artifact_ref": "docker-compose.yml",
                "source": "compose_depends_on",
                "classification": "observed_fact",
                "value": {"service": "backend", "depends_on": "db"},
            },
            dumped,
        )
        self.assertIn(
            {
                "fact_type": "package_dependency",
                "artifact_ref": "backend/pyproject.toml",
                "source": "pyproject.toml",
                "classification": "observed_fact",
                "value": {"package": "fastapi"},
            },
            dumped,
        )

    def test_evidence_does_not_classify_roles(self):
        repo = FIXTURES / "fastapi-fullstack-like"
        parsed_artifacts = {"docker-compose.yml": parse_compose(repo / "docker-compose.yml")}

        evidence = build_evidence(inventory_for(repo), parsed_artifacts)
        serialized = repr(evidence.model_dump())

        self.assertIn("postgres:16", serialized)
        self.assertNotIn("'role'", serialized)
        self.assertNotIn("dependency", serialized)

    def test_evidence_sorted_and_deterministic(self):
        repo = FIXTURES / "node-express-like"
        parsed_artifacts = {
            "Dockerfile": parse_dockerfile(repo / "Dockerfile"),
            "package.json": parse_nodejs(repo / "package.json"),
        }

        first = build_evidence(inventory_for(repo), parsed_artifacts)
        second = build_evidence(inventory_for(repo), parsed_artifacts)

        self.assertEqual(first.model_dump(), second.model_dump())
        self.assertEqual(
            [fact.evidence_id for fact in first.facts],
            [f"F{index:04d}" for index in range(1, len(first.facts) + 1)],
        )

    def test_evidence_excludes_secret_values(self):
        repo = FIXTURES / "fastapi-fullstack-like"
        parsed_artifacts = {"docker-compose.yml": parse_compose(repo / "docker-compose.yml")}

        evidence = build_evidence(inventory_for(repo), parsed_artifacts)

        self.assertNotIn("changethis", repr(evidence.model_dump()))


if __name__ == "__main__":
    unittest.main()
