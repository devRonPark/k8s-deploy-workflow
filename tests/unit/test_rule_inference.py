from datetime import datetime, timezone
from pathlib import Path
import unittest

from preanalyzer.analyzer.evidence_builder import build as build_evidence
from preanalyzer.analyzer.parsers.compose import parse as parse_compose
from preanalyzer.analyzer.parsers.dockerfile import parse as parse_dockerfile
from preanalyzer.analyzer.parsers.maven import parse as parse_maven
from preanalyzer.analyzer.parsers.nodejs import parse as parse_nodejs
from preanalyzer.analyzer.parsers.python_pkg import parse_pyproject
from preanalyzer.analyzer.rule_inference import infer
from preanalyzer.analyzer.scanner import build_inventory, snapshot


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"
FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_TIME


def fixture_evidence(repo_name: str):
    repo = FIXTURES / repo_name
    inventory = build_inventory(repo, snapshot(repo, None, None, fixed_clock))
    parsed_artifacts = {}
    if repo_name == "jpetstore-like":
        parsed_artifacts["pom.xml"] = parse_maven(repo / "pom.xml")
    if repo_name == "fastapi-fullstack-like":
        parsed_artifacts["docker-compose.yml"] = parse_compose(repo / "docker-compose.yml")
        parsed_artifacts["backend/Dockerfile"] = parse_dockerfile(repo / "backend" / "Dockerfile")
        parsed_artifacts["backend/pyproject.toml"] = parse_pyproject(repo / "backend" / "pyproject.toml")
        parsed_artifacts["frontend/Dockerfile"] = parse_dockerfile(repo / "frontend" / "Dockerfile")
        parsed_artifacts["frontend/package.json"] = parse_nodejs(repo / "frontend" / "package.json")
    if repo_name == "node-express-like":
        parsed_artifacts["Dockerfile"] = parse_dockerfile(repo / "Dockerfile")
        parsed_artifacts["package.json"] = parse_nodejs(repo / "package.json")
    return build_evidence(inventory, parsed_artifacts)


class RuleInferenceTests(unittest.TestCase):
    def test_jpetstore_single_java_boundary_candidate(self):
        rules = infer(fixture_evidence("jpetstore-like"))

        self.assertEqual(
            [candidate.model_dump() for candidate in rules.component_candidates],
            [{"component_id": "root", "root_path": ".", "source": "pom.xml", "evidence_refs": ["F0004"]}],
        )
        self.assertIn(
            {
                "component_id": "root",
                "language": "java",
                "framework": None,
                "build_tool": "maven",
                "build_strategy": "dockerfile_needed",
                "source": "pom.xml",
                "confidence": "high",
                "evidence_refs": ["F0004"],
            },
            [candidate.model_dump() for candidate in rules.runtime_candidates],
        )

    def test_fastapi_rule_candidates_with_roles(self):
        rules = infer(fixture_evidence("fastapi-fullstack-like"))

        self.assertEqual(
            [candidate.model_dump() for candidate in rules.component_candidates],
            [
                {"component_id": "backend", "root_path": "backend", "source": "compose_service", "evidence_refs": ["F0012"]},
                {"component_id": "db", "root_path": None, "source": "compose_service", "evidence_refs": ["F0017"]},
                {"component_id": "frontend", "root_path": "frontend", "source": "compose_service", "evidence_refs": ["F0020"]},
            ],
        )
        self.assertIn(
            {"component_id": "backend", "role": "application", "source": "compose_build", "confidence": "medium", "evidence_refs": ["F0013"]},
            [candidate.model_dump() for candidate in rules.role_candidates],
        )
        self.assertIn(
            {"component_id": "db", "role": "dependency", "source": "infra_image_pattern", "confidence": "high", "evidence_refs": ["F0018"]},
            [candidate.model_dump() for candidate in rules.role_candidates],
        )

    def test_rule_inference_priority_for_package_and_dockerfile(self):
        rules = infer(fixture_evidence("node-express-like"))

        self.assertIn(
            {
                "component_id": "root",
                "language": "nodejs",
                "framework": "express",
                "build_tool": "npm",
                "build_strategy": "dockerfile",
                "source": "package.json",
                "confidence": "high",
                "evidence_refs": ["F0006"],
            },
            [candidate.model_dump() for candidate in rules.runtime_candidates],
        )

    def test_secret_value_never_serialized(self):
        rules = infer(fixture_evidence("fastapi-fullstack-like"))

        self.assertIn(
            {"component_id": "db", "name": "POSTGRES_PASSWORD", "source": "compose_environment", "evidence_refs": ["F0019"]},
            [candidate.model_dump() for candidate in rules.env_classification.secret_candidates],
        )
        self.assertNotIn("changethis", repr(rules.model_dump()))


if __name__ == "__main__":
    unittest.main()
