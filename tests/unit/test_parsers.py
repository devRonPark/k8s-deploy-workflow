from pathlib import Path
import tempfile
import unittest

from preanalyzer.analyzer.parsers.compose import parse as parse_compose
from preanalyzer.analyzer.parsers.dockerfile import parse as parse_dockerfile
from preanalyzer.analyzer.parsers.maven import parse as parse_maven
from preanalyzer.analyzer.parsers.nodejs import parse as parse_nodejs
from preanalyzer.analyzer.parsers.python_pkg import parse_pyproject, parse_requirements
from preanalyzer.models.fields import Confidence


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"


class DockerfileParserTests(unittest.TestCase):
    def test_expose_extracted_high_confidence(self):
        parsed = parse_dockerfile(FIXTURES / "fastapi-fullstack-like" / "backend" / "Dockerfile")

        self.assertEqual([port.model_dump() for port in parsed.expose_ports], [
            {
                "value": 8000,
                "source": "dockerfile_expose",
                "confidence": "high",
                "evidence_refs": [],
            }
        ])

    def test_no_expose_yields_empty_ports(self):
        with tempfile.TemporaryDirectory() as tmp:
            dockerfile = Path(tmp) / "Dockerfile"
            dockerfile.write_text("FROM node:20\nCMD node server.js\n", encoding="utf-8")

            parsed = parse_dockerfile(dockerfile)

        self.assertEqual(parsed.expose_ports, [])

    def test_cmd_exec_form_and_shell_form(self):
        node = parse_dockerfile(FIXTURES / "node-express-like" / "Dockerfile")
        self.assertEqual(node.cmd.value, '["node", "server.js"]')
        self.assertEqual(node.cmd.source, "dockerfile_cmd")
        self.assertEqual(node.cmd.confidence, Confidence.HIGH)

        with tempfile.TemporaryDirectory() as tmp:
            dockerfile = Path(tmp) / "Dockerfile"
            dockerfile.write_text("FROM node:20\nCMD node server.js\n", encoding="utf-8")
            shell = parse_dockerfile(dockerfile)

        self.assertEqual(shell.cmd.value, "node server.js")

    def test_base_image_and_user_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            dockerfile = Path(tmp) / "Dockerfile"
            dockerfile.write_text("FROM python:3.11-slim\nUSER app\n", encoding="utf-8")

            parsed = parse_dockerfile(dockerfile)

        self.assertEqual(parsed.base_image.value, "python:3.11-slim")
        self.assertEqual(parsed.user.value, "app")

    def test_expose_multiple_ports(self):
        with tempfile.TemporaryDirectory() as tmp:
            dockerfile = Path(tmp) / "Dockerfile"
            dockerfile.write_text("FROM nginx\nEXPOSE 8080 9090/tcp\n", encoding="utf-8")

            parsed = parse_dockerfile(dockerfile)

        self.assertEqual([port.value for port in parsed.expose_ports], [8080, 9090])


class ComposeParserTests(unittest.TestCase):
    def test_three_services_parsed(self):
        parsed = parse_compose(FIXTURES / "fastapi-fullstack-like" / "docker-compose.yml")

        self.assertEqual([service.name for service in parsed.services], ["backend", "db", "frontend"])
        backend = parsed.service("backend")
        self.assertEqual(backend.depends_on, ["db"])
        self.assertEqual(backend.labels, {"traefik.enable": "true"})

    def test_env_values_pass_through_raw(self):
        parsed = parse_compose(FIXTURES / "fastapi-fullstack-like" / "docker-compose.yml")

        db = parsed.service("db")

        self.assertEqual(db.environment["POSTGRES_PASSWORD"], "changethis")

    def test_ports_short_and_long_syntax(self):
        with tempfile.TemporaryDirectory() as tmp:
            compose = Path(tmp) / "docker-compose.yml"
            compose.write_text(
                """
services:
  api:
    image: example/api
    ports:
      - "8080:80"
      - target: 9090
        published: 19090
""",
                encoding="utf-8",
            )

            parsed = parse_compose(compose)

        self.assertEqual(
            [port.model_dump() for port in parsed.service("api").ports],
            [
                {
                    "raw": "8080:80",
                    "host_ip": None,
                    "host_port": 8080,
                    "container_port": 80,
                    "protocol": None,
                    "resolved": True,
                    "resolution_source": "literal",
                    "warning": None,
                },
                {
                    "raw": "long:published=19090,target=9090",
                    "host_ip": None,
                    "host_port": 19090,
                    "container_port": 9090,
                    "protocol": None,
                    "resolved": True,
                    "resolution_source": "literal",
                    "warning": None,
                },
            ],
        )


class PackageParserTests(unittest.TestCase):
    def test_maven_war_packaging_no_modules(self):
        parsed = parse_maven(FIXTURES / "jpetstore-like" / "pom.xml")

        self.assertEqual(parsed.packaging.value, "war")
        self.assertFalse(parsed.is_multi_module)
        self.assertEqual(parsed.modules, [])

    def test_nodejs_scripts_and_deps(self):
        parsed = parse_nodejs(FIXTURES / "node-express-like" / "package.json")

        self.assertEqual(parsed.scripts["start"], "node server.js")
        self.assertIn("express", parsed.dependencies)

    def test_python_poetry_and_requirements(self):
        pyproject = parse_pyproject(FIXTURES / "fastapi-fullstack-like" / "backend" / "pyproject.toml")
        self.assertIn("fastapi", pyproject.dependencies)

        with tempfile.TemporaryDirectory() as tmp:
            requirements = Path(tmp) / "requirements.txt"
            requirements.write_text("fastapi==0.111.0\nuvicorn\n", encoding="utf-8")
            parsed_requirements = parse_requirements(requirements)

        self.assertEqual(parsed_requirements.dependencies, ["fastapi", "uvicorn"])


if __name__ == "__main__":
    unittest.main()
