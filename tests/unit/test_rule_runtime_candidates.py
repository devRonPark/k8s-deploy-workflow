from datetime import datetime, timezone
from pathlib import Path
import unittest

from preanalyzer.analyzer.evidence_builder import build as build_evidence
from preanalyzer.analyzer.parsers.dockerfile import parse as parse_dockerfile
from preanalyzer.analyzer.parsers.nodejs import parse as parse_nodejs
from preanalyzer.analyzer.parsers.python_pkg import parse_pyproject
from preanalyzer.analyzer.rule_inference import infer
from preanalyzer.analyzer.scanner import build_inventory, snapshot


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"
FIXED_TIME = datetime(2026, 7, 10, 9, 0, 0, tzinfo=timezone.utc)


def fixed_clock():
    return FIXED_TIME


def rules_for_fastapi():
    repo = FIXTURES / "fastapi-fullstack-like"
    inventory = build_inventory(repo, snapshot(repo, None, None, fixed_clock))
    evidence = build_evidence(
        inventory,
        {
            "backend/Dockerfile": parse_dockerfile(repo / "backend" / "Dockerfile"),
            "backend/pyproject.toml": parse_pyproject(repo / "backend" / "pyproject.toml"),
            "frontend/Dockerfile": parse_dockerfile(repo / "frontend" / "Dockerfile"),
            "frontend/package.json": parse_nodejs(repo / "frontend" / "package.json"),
        },
    )
    return infer(evidence)


class RuleRuntimeCandidateTests(unittest.TestCase):
    def test_runtime_versions_promoted_from_dockerfile_base_images(self):
        rules = rules_for_fastapi()

        self.assertIn(
            {
                "component_id": "backend",
                "language": "python",
                "version": "3.11",
                "source": "dockerfile_from",
                "confidence": "high",
                "evidence_refs": ["F0007"],
            },
            [candidate.model_dump() for candidate in rules.runtime_version_candidates],
        )
        self.assertIn(
            {
                "component_id": "frontend",
                "language": "nodejs",
                "version": "20",
                "source": "dockerfile_from",
                "confidence": "high",
                "evidence_refs": ["F0012"],
            },
            [candidate.model_dump() for candidate in rules.runtime_version_candidates],
        )

    def test_ports_and_commands_promoted_from_dockerfile(self):
        rules = rules_for_fastapi()

        self.assertIn(
            {
                "component_id": "backend",
                "port": 8000,
                "source": "dockerfile_expose",
                "confidence": "high",
                "evidence_refs": ["F0008"],
            },
            [candidate.model_dump() for candidate in rules.runtime_port_candidates],
        )
        self.assertIn(
            {
                "component_id": "backend",
                "command": "[\"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]",
                "source": "dockerfile_cmd",
                "confidence": "high",
                "evidence_refs": ["F0009"],
            },
            [candidate.model_dump() for candidate in rules.runtime_command_candidates],
        )


if __name__ == "__main__":
    unittest.main()
