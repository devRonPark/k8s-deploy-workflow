from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from migration_agent.adapters.models import LegacyAnalysisArtifacts
from migration_agent.adapters.preanalyzer_adapter import run_legacy_analysis
from migration_agent.capabilities.analysis_builder import build_repository_understanding
from migration_agent.domain.common import FieldState


FIXTURE_ROOT = Path("tests/fixtures/migration_agent")


def legacy_artifacts(fixture_name: str) -> LegacyAnalysisArtifacts:
    with tempfile.TemporaryDirectory() as tmp:
        return run_legacy_analysis(
            repository_path=FIXTURE_ROOT / fixture_name,
            output_dir=Path(tmp),
        )


class RepositoryUnderstandingBuilderTests(unittest.TestCase):
    def test_node_docker_fixture_resolves_command_port_and_container_strategy(self) -> None:
        repository_path = FIXTURE_ROOT / "node-docker"
        result = build_repository_understanding(
            repository_path=repository_path,
            artifacts=legacy_artifacts("node-docker"),
        )

        variant = result.lifecycle.variants[0]

        self.assertEqual(result.schema_version, "repository-understanding/v1-beta")
        self.assertEqual(result.repository.path, str(repository_path))
        self.assertEqual(result.topology.components[0].component_id, "root")
        self.assertEqual(result.topology.components[0].role, "application")
        self.assertEqual(variant.run_command.state, FieldState.RESOLVED)
        self.assertEqual(variant.run_command.value, '["node", "server.js"]')
        self.assertEqual(variant.run_command.source, "dockerfile_cmd")
        self.assertEqual(variant.run_command.confidence, "high")
        self.assertEqual(variant.run_command.classification, "rule_inference")
        self.assertEqual(variant.runtime_port.state, FieldState.RESOLVED)
        self.assertEqual(variant.runtime_port.value, 3000)
        self.assertEqual(variant.runtime_port.source, "dockerfile_expose")
        self.assertEqual(variant.runtime_port.confidence, "high")
        self.assertEqual(variant.runtime_port.classification, "rule_inference")
        self.assertEqual(variant.container_build_strategy.state, FieldState.RESOLVED)
        self.assertEqual(variant.container_build_strategy.value, "existing_dockerfile")
        self.assertEqual(variant.container_build_strategy.source, "artifact_inventory")
        self.assertEqual(variant.container_build_strategy.confidence, "high")
        self.assertEqual(variant.container_build_strategy.classification, "observed_fact")
        self.assertEqual(variant.container_entrypoint.state, FieldState.UNRESOLVED)
        self.assertNotIn(
            "lifecycle.variants[0].container_entrypoint",
            {fact.field_path for fact in result.confirmed_facts},
        )

        evidence_ids = {item.evidence_id for item in result.evidence}
        for fact in result.confirmed_facts:
            self.assertTrue(fact.evidence_refs)
            self.assertLessEqual(set(fact.evidence_refs), evidence_ids)

    def test_port_conflict_preserves_both_candidates_without_effective_value(self) -> None:
        result = build_repository_understanding(
            repository_path=FIXTURE_ROOT / "node-compose-conflict",
            artifacts=legacy_artifacts("node-compose-conflict"),
        )

        runtime_port = result.lifecycle.variants[0].runtime_port

        self.assertEqual(runtime_port.state, FieldState.CONFLICT)
        self.assertIsNone(runtime_port.value)
        self.assertEqual([candidate["value"] for candidate in runtime_port.candidates], [8080, 8081])
        self.assertEqual([candidate["source"] for candidate in runtime_port.candidates], ["dockerfile_expose", "compose_ports"])
        self.assertEqual([candidate["confidence"] for candidate in runtime_port.candidates], ["high", "medium"])
        self.assertEqual([candidate["classification"] for candidate in runtime_port.candidates], ["rule_inference", "rule_inference"])
        self.assertEqual(result.conflicts[0].field_path, "lifecycle.variants[0].runtime_port")
        self.assertEqual([candidate["value"] for candidate in result.conflicts[0].candidates], [8080, 8081])
        self.assertNotIn(
            "lifecycle.variants[0].runtime_port",
            {fact.field_path for fact in result.confirmed_facts},
        )

    def test_missing_port_and_missing_dockerfile_are_unknowns_not_failures(self) -> None:
        artifacts = legacy_artifacts("node-docker")
        no_port_no_dockerfile = artifacts.model_copy(
            update={
                "artifact_inventory": {
                    **artifacts.artifact_inventory,
                    "container_files": [],
                },
                "rule_inference": {
                    **artifacts.rule_inference,
                    "runtime_port_candidates": [],
                },
            }
        )

        result = build_repository_understanding(
            repository_path=FIXTURE_ROOT / "node-docker",
            artifacts=no_port_no_dockerfile,
        )

        variant = result.lifecycle.variants[0]
        unknown_paths = {unknown.field_path for unknown in result.unknowns}

        self.assertEqual(variant.runtime_port.state, FieldState.UNRESOLVED)
        self.assertEqual(variant.container_build_strategy.state, FieldState.UNRESOLVED)
        self.assertIn("lifecycle.variants[0].runtime_port", unknown_paths)
        self.assertIn("lifecycle.variants[0].container_build_strategy", unknown_paths)

    def test_package_build_script_projects_to_build_command(self) -> None:
        artifacts = legacy_artifacts("node-docker")
        with_build_script = artifacts.model_copy(
            update={
                "evidence_model": {
                    **artifacts.evidence_model,
                    "facts": [
                        *artifacts.evidence_model["facts"],
                        {
                            "evidence_id": "F9999",
                            "fact_type": "package_script",
                            "artifact_ref": "package.json",
                            "source": "package.json",
                            "classification": "observed_fact",
                            "value": {"name": "build", "command": "npm run compile"},
                        },
                    ],
                }
            }
        )

        result = build_repository_understanding(
            repository_path=FIXTURE_ROOT / "node-docker",
            artifacts=with_build_script,
        )
        build_command = result.lifecycle.variants[0].build_command

        self.assertEqual(build_command.state, FieldState.RESOLVED)
        self.assertEqual(build_command.value, "npm run compile")
        self.assertEqual(build_command.source, "package.json")
        self.assertEqual(build_command.confidence, "high")
        self.assertEqual(build_command.classification, "observed_fact")
        self.assertIn("lifecycle.variants[0].build_command", {fact.field_path for fact in result.confirmed_facts})

    def test_missing_component_candidates_do_not_invent_application_component(self) -> None:
        artifacts = legacy_artifacts("node-docker")
        without_components = artifacts.model_copy(
            update={
                "rule_inference": {
                    **artifacts.rule_inference,
                    "component_candidates": [],
                    "role_candidates": [],
                }
            }
        )

        result = build_repository_understanding(
            repository_path=FIXTURE_ROOT / "node-docker",
            artifacts=without_components,
        )

        self.assertEqual(result.topology.components, [])
        self.assertIn("topology.components", {unknown.field_path for unknown in result.unknowns})

    def test_environment_variable_names_are_kept_without_values(self) -> None:
        artifacts = legacy_artifacts("node-docker")
        with_secret_value = artifacts.model_copy(
            update={
                "rule_inference": {
                    **artifacts.rule_inference,
                    "env_classification": {
                        "secret_candidates": [
                            {
                                "component_id": "root",
                                "name": "DATABASE_URL",
                                "source": "package.json",
                                "evidence_refs": ["F0007"],
                                "classification": "rule_inference",
                                "value": "postgres://user:password@example/db",
                            }
                        ]
                    },
                }
            }
        )

        result = build_repository_understanding(
            repository_path=FIXTURE_ROOT / "node-docker",
            artifacts=with_secret_value,
        )
        dumped = yaml.safe_dump(result.model_dump(mode="json"), sort_keys=False)

        self.assertEqual(
            result.lifecycle.variants[0].environment_variable_names,
            ["DATABASE_URL"],
        )
        self.assertNotIn("postgres://user:password@example/db", dumped)

    def test_yaml_serialization_is_stable_and_has_no_target_or_manifest_values(self) -> None:
        result = build_repository_understanding(
            repository_path=FIXTURE_ROOT / "node-docker",
            artifacts=legacy_artifacts("node-docker"),
        )

        dumped = yaml.safe_dump(result.model_dump(mode="json"), sort_keys=False)

        self.assertEqual(dumped, yaml.safe_dump(yaml.safe_load(dumped), sort_keys=False))
        self.assertNotIn("target:", dumped)
        self.assertNotIn("manifest", dumped)
        self.assertNotIn("proposal", dumped)
        self.assertNotIn("decision", dumped)


if __name__ == "__main__":
    unittest.main()
