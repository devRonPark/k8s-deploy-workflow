from pathlib import Path
import tempfile
import unittest

from preanalyzer.analyzer.evidence_builder import build as build_evidence
from preanalyzer.analyzer.parsers.result import ParseWarning
from preanalyzer.analyzer.parsers.spring import parse_spring_config, try_parse_spring_config
from preanalyzer.analyzer.rule_inference import infer
from preanalyzer.models.inventory import ArtifactInventory


class SpringInputTests(unittest.TestCase):
    def test_spring_yaml_records_service_port_dependencies_and_keys_without_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "application.yml"
            config.write_text(
                "\n".join(
                    [
                        "spring:",
                        "  application:",
                        "    name: catalog-service",
                        "  cloud:",
                        "    config:",
                        "      uri: http://${CONFIG_USER}:${CONFIG_PASSWORD}@config-server:8888",
                        "server:",
                        "  port: 8081",
                        "eureka:",
                        "  client:",
                        "    service-url:",
                        "      defaultZone: http://eureka:8761/eureka/",
                        "secret:",
                        "  token: ${SPRING_SECRET_TOKEN}",
                    ]
                ),
                encoding="utf-8",
            )

            parsed = parse_spring_config(config)
            evidence = build_evidence(
                inventory=ArtifactInventory(
                    app_configs=[{"path": "src/main/resources/application.yml", "type": "application_yaml"}],
                    build_files=[{"path": "pom.xml", "type": "maven"}],
                ),
                parsed_artifacts={"src/main/resources/application.yml": parsed},
            )

        facts = [_without_id(fact.model_dump()) for fact in evidence.facts]

        self.assertIn(
            {
                "fact_type": "spring_application_name",
                "artifact_ref": "src/main/resources/application.yml",
                "source": "spring_config",
                "classification": "observed_fact",
                "value": {"name": "catalog-service"},
            },
            facts,
        )
        self.assertIn(
            {
                "fact_type": "spring_server_port",
                "artifact_ref": "src/main/resources/application.yml",
                "source": "spring_config",
                "classification": "observed_fact",
                "value": {"port": 8081},
            },
            facts,
        )
        self.assertIn(
            {
                "fact_type": "spring_dependency_hint",
                "artifact_ref": "src/main/resources/application.yml",
                "source": "spring_config",
                "classification": "observed_fact",
                "value": {
                    "kind": "config_server",
                    "target": "config-server",
                    "key": "spring.cloud.config.uri",
                },
            },
            facts,
        )
        self.assertIn(
            {
                "fact_type": "spring_dependency_hint",
                "artifact_ref": "src/main/resources/application.yml",
                "source": "spring_config",
                "classification": "observed_fact",
                "value": {
                    "kind": "service_discovery",
                    "target": "eureka",
                    "key": "eureka.client.service-url.defaultZone",
                },
            },
            facts,
        )
        serialized = "\n".join(str(fact.value) for fact in evidence.facts)
        self.assertNotIn("${CONFIG_PASSWORD}", serialized)
        self.assertNotIn("${SPRING_SECRET_TOKEN}", serialized)

        rules = infer(evidence)
        self.assertEqual([candidate.component_id for candidate in rules.component_candidates], ["catalog-service"])
        self.assertEqual([candidate.role for candidate in rules.role_candidates], ["application"])
        self.assertEqual([candidate.framework for candidate in rules.runtime_candidates], ["spring"])
        self.assertEqual([candidate.build_tool for candidate in rules.runtime_candidates], ["maven"])
        self.assertEqual([candidate.port for candidate in rules.runtime_port_candidates], [8081])
        self.assertEqual(
            [(candidate.source_component, candidate.target, candidate.dependency_type) for candidate in rules.dependency_edge_candidates],
            [
                ("catalog-service", "config-server", "config_server"),
                ("catalog-service", "eureka", "service_discovery"),
            ],
        )

    def test_spring_properties_records_explicit_server_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "application.properties"
            config.write_text(
                "\n".join(
                    [
                        "spring.application.name=orders-service",
                        "server.port=9090",
                    ]
                ),
                encoding="utf-8",
            )

            parsed = parse_spring_config(config)

        self.assertEqual(parsed.service_name, "orders-service")
        self.assertEqual(parsed.server_port, 9090)

    def test_spring_runtime_uses_gradle_build_tool_when_gradle_file_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "application.yml"
            config.write_text("spring:\n  application:\n    name: orders-service\n", encoding="utf-8")

            evidence = build_evidence(
                inventory=ArtifactInventory(
                    app_configs=[{"path": "src/main/resources/application.yml", "type": "application_yaml"}],
                    build_files=[{"path": "build.gradle", "type": "gradle"}],
                ),
                parsed_artifacts={"src/main/resources/application.yml": parse_spring_config(config)},
            )

        rules = infer(evidence)

        self.assertEqual([candidate.build_tool for candidate in rules.runtime_candidates], ["gradle"])

    def test_test_profile_service_name_does_not_create_second_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            main_config = Path(tmp) / "application.yml"
            test_config = Path(tmp) / "application-test.yml"
            main_config.write_text("spring:\n  application:\n    name: catalog-service\n", encoding="utf-8")
            test_config.write_text(
                "spring:\n  application:\n    name: catalog-service-test\nserver:\n  port: 18081\n",
                encoding="utf-8",
            )

            evidence = build_evidence(
                inventory=ArtifactInventory(
                    app_configs=[
                        {"path": "src/main/resources/application.yml", "type": "application_yaml"},
                        {"path": "src/test/resources/application-test.yml", "type": "application_yaml"},
                    ],
                    build_files=[{"path": "pom.xml", "type": "maven"}],
                ),
                parsed_artifacts={
                    "src/main/resources/application.yml": parse_spring_config(main_config),
                    "src/test/resources/application-test.yml": parse_spring_config(test_config),
                },
            )

        rules = infer(evidence)

        self.assertEqual([candidate.component_id for candidate in rules.component_candidates], ["catalog-service"])
        self.assertEqual([candidate.component_id for candidate in rules.role_candidates], ["catalog-service"])
        self.assertEqual([candidate.component_id for candidate in rules.runtime_candidates], ["catalog-service"])
        self.assertEqual(
            [(candidate.component_id, candidate.port) for candidate in rules.runtime_port_candidates],
            [("catalog-service", 18081)],
        )

    def test_invalid_spring_yaml_becomes_parse_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "application.yml"
            config.write_text("spring:\n  application: [", encoding="utf-8")

            result = try_parse_spring_config(config)

        self.assertIsInstance(result, ParseWarning)


def _without_id(value):
    value = dict(value)
    value.pop("evidence_id")
    return value


if __name__ == "__main__":
    unittest.main()
