from pathlib import Path
import tempfile
import unittest

from preanalyzer.analyzer.evidence_builder import build as build_evidence
from preanalyzer.analyzer.parsers.helm import parse as parse_helm
from preanalyzer.analyzer.parsers.kubernetes import parse as parse_kubernetes
from preanalyzer.analyzer.rule_inference import infer
from preanalyzer.models.inventory import ArtifactInventory


class KubernetesHelmInputTests(unittest.TestCase):
    def test_kubernetes_manifest_records_workload_service_port_and_image_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "api.yaml"
            manifest.write_text(
                "\n".join(
                    [
                        "apiVersion: apps/v1",
                        "kind: Deployment",
                        "metadata:",
                        "  name: api",
                        "spec:",
                        "  template:",
                        "    metadata:",
                        "      labels:",
                        "        app: api",
                        "    spec:",
                        "      containers:",
                        "        - name: api",
                        "          image: ghcr.io/example/api:1.0.0",
                        "          ports:",
                        "            - name: http",
                        "              containerPort: 8000",
                        "---",
                        "apiVersion: v1",
                        "kind: Service",
                        "metadata:",
                        "  name: api",
                        "spec:",
                        "  selector:",
                        "    app: api",
                        "  ports:",
                        "    - port: 80",
                        "      targetPort: http",
                    ]
                ),
                encoding="utf-8",
            )

            parsed = parse_kubernetes(manifest)
            evidence = build_evidence(
                inventory=ArtifactInventory(
                    kubernetes_manifests=[{"path": "k8s/api.yaml", "type": "kubernetes_manifest"}]
                ),
                parsed_artifacts={"k8s/api.yaml": parsed},
            )

        facts = [_without_id(fact.model_dump()) for fact in evidence.facts]

        self.assertIn(
            {
                "fact_type": "kubernetes_resource",
                "artifact_ref": "k8s/api.yaml",
                "source": "kubernetes_manifest",
                "classification": "observed_fact",
                "value": {
                    "kind": "Deployment",
                    "name": "api",
                    "labels": {},
                },
            },
            facts,
        )
        self.assertIn(
            {
                "fact_type": "kubernetes_service_port",
                "artifact_ref": "k8s/api.yaml",
                "source": "kubernetes_manifest",
                "classification": "observed_fact",
                "value": {
                    "name": "api",
                    "port": 80,
                    "target_port": "http",
                    "protocol": None,
                },
            },
            facts,
        )
        self.assertIn(
            {
                "fact_type": "kubernetes_container_image",
                "artifact_ref": "k8s/api.yaml",
                "source": "kubernetes_manifest",
                "classification": "observed_fact",
                "value": {
                    "workload": "api",
                    "container": "api",
                    "image": "ghcr.io/example/api:1.0.0",
                },
            },
            facts,
        )
        self.assertIn(
            {
                "fact_type": "kubernetes_container_port",
                "artifact_ref": "k8s/api.yaml",
                "source": "kubernetes_manifest",
                "classification": "observed_fact",
                "value": {
                    "workload": "api",
                    "container": "api",
                    "name": "http",
                    "container_port": 8000,
                },
            },
            facts,
        )
        self.assertIn(
            {
                "fact_type": "kubernetes_workload_pod_labels",
                "artifact_ref": "k8s/api.yaml",
                "source": "kubernetes_manifest",
                "classification": "observed_fact",
                "value": {
                    "kind": "Deployment",
                    "name": "api",
                    "labels": {"app": "api"},
                },
            },
            facts,
        )
        self.assertIn(
            {
                "fact_type": "kubernetes_service_selector",
                "artifact_ref": "k8s/api.yaml",
                "source": "kubernetes_manifest",
                "classification": "observed_fact",
                "value": {
                    "name": "api",
                    "selector": {"app": "api"},
                },
            },
            facts,
        )

        rules = infer(evidence)
        self.assertEqual(
            [candidate.model_dump() for candidate in rules.runtime_port_candidates],
            [
                {
                    "component_id": "api",
                    "port": 8000,
                    "source": "kubernetes_manifest",
                    "confidence": "medium",
                    "evidence_refs": ["F0007", "F0008", "F0005", "F0004"],
                    "classification": "rule_inference",
                }
            ],
        )

    def test_kubernetes_service_port_targets_selected_workload_not_service_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "api.yaml"
            manifest.write_text(
                "\n".join(
                    [
                        "apiVersion: apps/v1",
                        "kind: Deployment",
                        "metadata:",
                        "  name: api",
                        "spec:",
                        "  template:",
                        "    metadata:",
                        "      labels:",
                        "        app: api",
                        "    spec:",
                        "      containers:",
                        "        - name: api",
                        "          image: ghcr.io/example/api:1.0.0",
                        "---",
                        "apiVersion: v1",
                        "kind: Service",
                        "metadata:",
                        "  name: api-svc",
                        "spec:",
                        "  selector:",
                        "    app: api",
                        "  ports:",
                        "    - port: 80",
                        "      targetPort: 9000",
                    ]
                ),
                encoding="utf-8",
            )

            parsed = parse_kubernetes(manifest)
            evidence = build_evidence(
                inventory=ArtifactInventory(
                    kubernetes_manifests=[{"path": "k8s/api.yaml", "type": "kubernetes_manifest"}]
                ),
                parsed_artifacts={"k8s/api.yaml": parsed},
            )

        rules = infer(evidence)

        self.assertEqual(
            [candidate.component_id for candidate in rules.component_candidates],
            ["api"],
        )
        self.assertEqual(
            [candidate.model_dump() for candidate in rules.runtime_port_candidates],
            [
                {
                    "component_id": "api",
                    "port": 9000,
                    "source": "kubernetes_manifest",
                    "confidence": "medium",
                    "evidence_refs": ["F0006", "F0007", "F0004"],
                    "classification": "rule_inference",
                }
            ],
        )

    def test_helm_chart_metadata_is_read_only_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            chart = Path(tmp) / "Chart.yaml"
            chart.write_text(
                'apiVersion: v2\nname: api\nversion: 0.1.0\nappVersion: "1.0.0"\n',
                encoding="utf-8",
            )

            parsed = parse_helm(chart)
            evidence = build_evidence(
                inventory=ArtifactInventory(helm_charts=[{"path": "chart/Chart.yaml", "type": "helm_chart"}]),
                parsed_artifacts={"chart/Chart.yaml": parsed},
            )

        facts = [_without_id(fact.model_dump()) for fact in evidence.facts]

        self.assertIn(
            {
                "fact_type": "helm_chart_metadata",
                "artifact_ref": "chart/Chart.yaml",
                "source": "helm_chart",
                "classification": "observed_fact",
                "value": {
                    "name": "api",
                    "version": "0.1.0",
                    "app_version": "1.0.0",
                    "chart_type": None,
                },
            },
            facts,
        )


def _without_id(value):
    value = dict(value)
    value.pop("evidence_id")
    return value


if __name__ == "__main__":
    unittest.main()
