from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from migration_agent.cli.main import main


FIXTURE_ROOT = Path("tests/fixtures/migration_agent")
LIMITATION_MESSAGE = "Kubernetes manifests are not generated in v1."


def run_assess(fixture_name: str, output: Path) -> tuple[str, dict, dict]:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(["assess", str(FIXTURE_ROOT / fixture_name), "--output", str(output)])
    if code != 0:
        raise AssertionError(f"repository-agent assess failed with {code}: {stdout.getvalue()}")
    understanding = yaml.safe_load((output / "repository-understanding.yaml").read_text(encoding="utf-8"))
    assessment = json.loads((output / "repository-assessment.json").read_text(encoding="utf-8"))
    return stdout.getvalue(), understanding, assessment


class V1BetaEndToEndTests(unittest.TestCase):
    def test_clear_node_docker_resolves_execution_port_and_container_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "node-docker"

            console, understanding, assessment = run_assess("node-docker", output)

            variant = understanding["lifecycle"]["variants"][0]
            self.assertEqual(variant["run_command"]["state"], "resolved")
            self.assertEqual(variant["runtime_port"]["state"], "resolved")
            self.assertEqual(variant["runtime_port"]["value"], 3000)
            self.assertEqual(variant["container_build_strategy"]["state"], "resolved")
            self.assertEqual(assessment["execution"], "complete")
            self.assertEqual(assessment["container"], "complete")
            self.assertIn(LIMITATION_MESSAGE, console)
            self.assert_no_forbidden_outputs(output)

    def test_port_conflict_is_preserved_without_effective_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "node-compose-conflict"

            console, understanding, assessment = run_assess("node-compose-conflict", output)

            runtime_port = understanding["lifecycle"]["variants"][0]["runtime_port"]
            self.assertEqual(runtime_port["state"], "conflict")
            self.assertIsNone(runtime_port["value"])
            self.assertEqual([candidate["value"] for candidate in runtime_port["candidates"]], [8080, 8081])
            self.assertEqual(assessment["execution"], "conflicted")
            self.assertIn("8080, 8081", console)
            self.assert_no_forbidden_outputs(output)

    def test_missing_dockerfile_reports_unknown_container_without_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "node-no-dockerfile"

            console, understanding, assessment = run_assess("node-no-dockerfile", output)

            container_strategy = understanding["lifecycle"]["variants"][0]["container_build_strategy"]
            self.assertEqual(container_strategy["state"], "unresolved")
            self.assertEqual(assessment["container"], "unknown")
            self.assertNotIn("Dockerfile proposal", console)
            self.assert_no_forbidden_outputs(output)

    def test_coverage_summary_explains_partial_and_unsupported_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "node-compose-unresolved"

            console, understanding, assessment = run_assess("node-compose-unresolved", output)

            runtime_port = understanding["lifecycle"]["variants"][0]["runtime_port"]
            runtime_port_unknown = next(
                item
                for item in understanding["unknowns"]
                if item["field_path"] == "lifecycle.variants[0].runtime_port"
            )
            build_command_unknown = next(
                item
                for item in understanding["unknowns"]
                if item["field_path"] == "lifecycle.variants[0].build_command"
            )
            coverage = assessment["coverage"]
            items = {item["artifact_ref"]: item for item in coverage["items"]}

            self.assertEqual(runtime_port["state"], "unresolved")
            self.assertEqual(runtime_port_unknown["reason_code"], "unresolved_interpolation")
            self.assertIn("F", runtime_port_unknown["evidence_refs"][0])
            self.assertEqual(build_command_unknown["reason_code"], "unsupported_artifact")
            self.assertTrue(build_command_unknown["evidence_refs"])
            self.assertEqual(items["docker-compose.yml"]["status"], "partial")
            self.assertEqual(items["docker-compose.yml"]["reason_code"], "unresolved_interpolation")
            self.assertEqual(items["go.mod"]["status"], "unsupported")
            self.assertIn("docker-compose.yml: partial", console)
            self.assertIn("go.mod: unsupported", console)
            self.assertIn("Coverage", console)
            self.assertIn("partial", (output / "repository-assessment.md").read_text(encoding="utf-8"))
            self.assert_no_forbidden_outputs(output)

    def test_compose_variant_files_contribute_runtime_port_without_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "fastapi-compose-variant"

            console, understanding, assessment = run_assess("fastapi-compose-variant", output)

            runtime_port = understanding["lifecycle"]["variants"][0]["runtime_port"]
            coverage_items = {item["artifact_ref"]: item for item in assessment["coverage"]["items"]}
            serialized = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (
                    output / "discovery.json",
                    output / "repository-understanding.yaml",
                    output / "repository-assessment.json",
                    output / "repository-assessment.md",
                )
            )

            self.assertEqual(runtime_port["state"], "resolved")
            self.assertEqual(runtime_port["value"], 8000)
            self.assertEqual([component["component_id"] for component in understanding["topology"]["components"]], ["api"])
            self.assertEqual(coverage_items["docker-compose.dev.yml"]["status"], "parsed")
            self.assertIn("docker-compose.dev.yml", serialized)
            self.assertNotIn("API_SECRET_KEY=", serialized)
            self.assertIn("Coverage", console)
            self.assert_no_forbidden_outputs(output)

    def test_unresolved_compose_variant_port_stays_unknown_with_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "compose-variant-unresolved-port"

            _, understanding, assessment = run_assess("compose-variant-unresolved-port", output)

            runtime_port = understanding["lifecycle"]["variants"][0]["runtime_port"]
            runtime_port_unknown = next(
                item
                for item in understanding["unknowns"]
                if item["field_path"] == "lifecycle.variants[0].runtime_port"
            )
            coverage_items = {item["artifact_ref"]: item for item in assessment["coverage"]["items"]}

            self.assertEqual(runtime_port["state"], "unresolved")
            self.assertEqual(runtime_port_unknown["reason_code"], "unresolved_interpolation")
            self.assertTrue(runtime_port_unknown["evidence_refs"])
            self.assertEqual(coverage_items["docker-compose.dev.yml"]["status"], "partial")
            self.assert_no_forbidden_outputs(output)

    def test_existing_kubernetes_and_helm_inputs_are_read_only_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "kubernetes-readonly-input"

            _, understanding, assessment = run_assess("kubernetes-readonly-input", output)

            runtime_port = understanding["lifecycle"]["variants"][0]["runtime_port"]
            discovery = json.loads((output / "discovery.json").read_text(encoding="utf-8"))
            fact_types = {
                fact["fact_type"]
                for fact in discovery["evidence_model"]["facts"]
            }
            coverage_items = {
                item["artifact_ref"]: item
                for item in assessment["coverage"]["items"]
            }

            self.assertEqual([component["component_id"] for component in understanding["topology"]["components"]], ["api"])
            self.assertEqual(runtime_port["state"], "resolved")
            self.assertEqual(runtime_port["value"], 8000)
            self.assertIn("kubernetes_resource", fact_types)
            self.assertIn("kubernetes_container_image", fact_types)
            self.assertIn("kubernetes_container_port", fact_types)
            self.assertIn("helm_chart_metadata", fact_types)
            self.assertEqual(coverage_items["k8s/api.yaml"]["status"], "parsed")
            self.assertEqual(coverage_items["chart/Chart.yaml"]["status"], "parsed")
            self.assert_no_forbidden_outputs(output)

    def test_dotnet_configuration_inputs_reduce_unknowns_without_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dotnet-web-config"

            _, understanding, assessment = run_assess("dotnet-web-config", output)

            runtime_port = understanding["lifecycle"]["variants"][0]["runtime_port"]
            discovery = json.loads((output / "discovery.json").read_text(encoding="utf-8"))
            fact_types = {fact["fact_type"] for fact in discovery["evidence_model"]["facts"]}
            coverage_items = {
                item["artifact_ref"]: item
                for item in assessment["coverage"]["items"]
            }
            serialized = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (
                    output / "discovery.json",
                    output / "repository-understanding.yaml",
                    output / "repository-assessment.json",
                    output / "repository-assessment.md",
                )
            )

            self.assertEqual(
                [component["component_id"] for component in understanding["topology"]["components"]],
                ["Catalog.Api"],
            )
            self.assertEqual(runtime_port["state"], "resolved")
            self.assertEqual(runtime_port["value"], 5000)
            self.assertIn("dotnet_project_metadata", fact_types)
            self.assertIn("dotnet_launch_port", fact_types)
            self.assertIn("dotnet_connection_string_name", fact_types)
            self.assertEqual(coverage_items["src/Catalog.Api/Catalog.Api.csproj"]["status"], "parsed")
            self.assertEqual(coverage_items["src/Catalog.Api/appsettings.json"]["status"], "parsed")
            self.assertEqual(coverage_items["src/Catalog.Api/Properties/launchSettings.json"]["status"], "parsed")
            self.assertNotIn("Password=", serialized)
            self.assertNotIn("${DB_PASSWORD}", serialized)
            self.assertNotIn("${API_TOKEN}", serialized)
            self.assert_no_forbidden_outputs(output)

    def test_same_input_outputs_are_semantically_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first_output = Path(tmp) / "first"
            second_output = Path(tmp) / "second"

            run_assess("node-docker", first_output)
            run_assess("node-docker", second_output)

            self.assertEqual(
                (first_output / "repository-understanding.yaml").read_text(encoding="utf-8"),
                (second_output / "repository-understanding.yaml").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (first_output / "repository-assessment.json").read_text(encoding="utf-8"),
                (second_output / "repository-assessment.json").read_text(encoding="utf-8"),
            )

    def test_verification_script_and_report_are_present(self) -> None:
        self.assertTrue(Path("scripts/verify-v1-beta.sh").is_file())
        self.assertTrue(Path("scripts/verify-v1-beta-real-repos.sh").is_file())
        report = Path("docs/releases/v1-beta-verification.md").read_text(encoding="utf-8")
        self.assertIn("repository-agent assess tests/fixtures/migration_agent/node-docker", report)
        self.assertIn("repository-agent assess tests/fixtures/migration_agent/node-compose-conflict", report)
        self.assertIn("repository-agent assess tests/fixtures/migration_agent/node-no-dockerfile", report)
        for repository, sha in (
            ("mybatis/jpetstore-6", "5a7cc780505b88a60779b3e3c0a50b0e404cfb2d"),
            ("fastapi/full-stack-fastapi-template", "4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8"),
            ("GoogleCloudPlatform/microservices-demo", "9a4616e77f0f9cbcbecaf27d711c38890dda1404"),
            ("spring-petclinic/spring-petclinic-microservices", "305a1f13e4f961001d4e6cb50a9db51dc3fc5967"),
            ("dotnet/eShop", "9b4f9434f46fdc5c1a6e9e936af2868340cdbc48"),
        ):
            self.assertIn(repository, report)
            self.assertIn(sha, report)

    def assert_no_forbidden_outputs(self, output: Path) -> None:
        paths = [path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()]
        allowed = {"repository-assessment.md"}
        self.assertFalse(any("manifest" in path and Path(path).name not in allowed for path in paths), paths)
        self.assertFalse(any("proposal" in path for path in paths), paths)
        self.assertFalse(any("decision" in path for path in paths), paths)
        self.assertFalse(any("validation" in path for path in paths), paths)


if __name__ == "__main__":
    unittest.main()
