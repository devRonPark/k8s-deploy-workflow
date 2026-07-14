from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml
from pydantic import ValidationError

from k8s_agent.analysis.topology_builder import write_topology_artifact
from k8s_agent.models.topology import (
    AnalysisCoverage,
    ApplicationComponent,
    ApplicationTopology,
    DeploymentVariant,
    EvidenceLinkedValue,
    RepositoryModule,
    TopologyField,
)


class TopologyModelTests(unittest.TestCase):
    def test_canonical_topology_round_trips_with_modules_variants_coverage_and_fields(self):
        topology = ApplicationTopology(
            repository_modules=[
                RepositoryModule(
                    module_id="root",
                    root_path=".",
                    build_system="npm",
                    evidence_refs=["F0001"],
                    package_dependencies=[
                        EvidenceLinkedValue(
                            value="express",
                            source="package.json",
                            confidence="high",
                            classification="observed_fact",
                            evidence_refs=["F0002"],
                        )
                    ],
                )
            ],
            deployment_variants=[
                DeploymentVariant(
                    variant_id="common",
                    source="implicit_common",
                    evidence_refs=[],
                )
            ],
            analysis_coverage=[
                AnalysisCoverage(
                    artifact_ref="Dockerfile",
                    artifact_type="dockerfile",
                    status="analyzed",
                    evidence_refs=["F0003"],
                    field_paths=[
                        "/components/root/effective_runtime_command",
                        "/components/root/runtime_port",
                    ],
                )
            ],
            components=[
                ApplicationComponent(
                    component_id="root",
                    fields=[
                        TopologyField(
                            field_path="/components/root/runtime_port",
                            group="core",
                            state="resolved",
                            value=3000,
                            source="dockerfile_expose",
                            confidence="high",
                            classification="rule_inference",
                            evidence_refs=["F0004"],
                            candidates=[
                                EvidenceLinkedValue(
                                    value=3000,
                                    source="dockerfile_expose",
                                    confidence="high",
                                    classification="rule_inference",
                                    evidence_refs=["F0004"],
                                )
                            ],
                        )
                    ],
                )
            ],
        )

        round_tripped = ApplicationTopology.model_validate(
            topology.model_dump(mode="json")
        )

        self.assertEqual(round_tripped, topology)
        serialized = topology.model_dump_json()
        self.assertNotIn("policy_default", serialized)
        self.assertNotIn("target_policy", serialized)

    def test_topology_artifact_yaml_round_trips(self):
        topology = ApplicationTopology(
            repository_modules=[
                RepositoryModule(module_id="root", root_path=".", build_system="npm")
            ],
            deployment_variants=[
                DeploymentVariant(variant_id="common", source="implicit_common")
            ],
            analysis_coverage=[
                AnalysisCoverage(
                    artifact_ref="package.json",
                    artifact_type="nodejs",
                    status="coverage_gap",
                    evidence_refs=["F0001"],
                    limitation="artifact_not_interpreted_by_topology_builder",
                )
            ],
            components=[
                ApplicationComponent(
                    component_id="root",
                    fields=[
                        TopologyField(
                            field_path="/components/root/runtime_port",
                            group="core",
                            state="unresolved",
                            reason="runtime_port_not_detected",
                        )
                    ],
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "04-application-topology.yaml"
            write_topology_artifact(path, topology)
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        self.assertEqual(
            ApplicationTopology.model_validate(payload["application_topology"]),
            topology,
        )

    def test_resolved_field_requires_value_source_classification_and_evidence(self):
        with self.assertRaisesRegex(ValidationError, "resolved topology fields"):
            TopologyField(
                field_path="/components/root/runtime_port",
                group="core",
                state="resolved",
                source="dockerfile_expose",
                classification="rule_inference",
                evidence_refs=["F0001"],
            )

        with self.assertRaisesRegex(ValidationError, "resolved topology fields"):
            TopologyField(
                field_path="/components/root/runtime_port",
                group="core",
                state="resolved",
                value=3000,
                source="dockerfile_expose",
                classification="rule_inference",
            )

        with self.assertRaisesRegex(ValidationError, "resolved topology fields"):
            TopologyField(
                field_path="/components/root/runtime_port",
                group="core",
                state="resolved",
                value=3000,
                source="dockerfile_expose",
                classification="rule_inference",
                evidence_refs=["F0001"],
            )

    def test_conflict_field_requires_candidates_and_unresolved_field_requires_reason(self):
        with self.assertRaisesRegex(ValidationError, "conflict topology fields"):
            TopologyField(
                field_path="/components/root/runtime_port",
                group="core",
                state="conflict",
                evidence_refs=["F0001", "F0002"],
            )

        with self.assertRaisesRegex(ValidationError, "unresolved topology fields"):
            TopologyField(
                field_path="/components/root/effective_runtime_command",
                group="core",
                state="unresolved",
            )

    def test_invalid_canonical_aggregate_values_are_rejected(self):
        with self.assertRaises(ValidationError):
            RepositoryModule(module_id="", root_path=".")

        with self.assertRaises(ValidationError):
            DeploymentVariant(variant_id="", source="implicit_common")

        with self.assertRaises(ValidationError):
            AnalysisCoverage(
                artifact_ref="package.json",
                artifact_type="nodejs",
                status="unknown",
            )

        with self.assertRaises(ValidationError):
            TopologyField(
                field_path="/components/root/secret_classification",
                group="core",
                state="resolved",
                value="secret",
                source="secret_classification",
                confidence="high",
                classification="negative_finding",
                evidence_refs=["F0001"],
            )


if __name__ == "__main__":
    unittest.main()
