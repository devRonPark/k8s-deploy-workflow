from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from k8s_agent.analysis.intent_builder import INTENT_ARTIFACT, IntentBuilder
from k8s_agent.models.topology import (
    ApplicationComponent,
    ApplicationTopology,
    DependencyEdge,
    EvidenceLinkedValue,
    RuntimeInfo,
    SecretUse,
)
from k8s_agent.policy.target_policy import PolicyDisposition, Target


def app_component() -> ApplicationComponent:
    return ApplicationComponent(
        component_id="api",
        root_path="backend",
        role="application",
        evidence_refs=["F001"],
        runtime=RuntimeInfo(
            language="python",
            framework="fastapi",
            build_tool="pyproject",
            build_strategy="dockerfile",
            source="pyproject.toml",
            confidence="high",
            classification="rule_inference",
            evidence_refs=["F010"],
        ),
        command=EvidenceLinkedValue(
            value="uvicorn main:app --host 0.0.0.0 --port 8000",
            source="llm_semantic_inference",
            confidence="medium",
            classification="llm_semantic_inference",
            evidence_refs=["SE-001"],
        ),
        ports=[
            EvidenceLinkedValue(
                value=8000,
                source="dockerfile_expose",
                confidence="high",
                classification="rule_inference",
                evidence_refs=["F020"],
            )
        ],
        dependencies=[
            DependencyEdge(
                target="db",
                dependency_type="database",
                source="compose_depends_on",
                confidence="medium",
                classification="rule_inference",
                evidence_refs=["F030"],
            )
        ],
    )


def db_component() -> ApplicationComponent:
    return ApplicationComponent(
        component_id="db",
        root_path=None,
        role="dependency",
        evidence_refs=["F040"],
        secrets=[SecretUse(name="POSTGRES_PASSWORD", source="compose_environment", classification="rule_inference", evidence_refs=["F041"])],
    )


class IntentBuilderTests(unittest.TestCase):
    def test_builds_target_aware_intent_candidates_with_policy_decisions(self):
        topology = ApplicationTopology(components=[app_component(), db_component()])

        intent = IntentBuilder().build(topology, Target.STAGING)

        by_kind = {(candidate.component_id, candidate.kind): candidate for candidate in intent.candidates}
        self.assertEqual(by_kind[("api", "deployment")].decision.disposition, PolicyDisposition.AUTO_CONFIRM)
        self.assertEqual(by_kind[("api", "service")].value["port"], 8000)
        self.assertEqual(by_kind[("api", "replicas")].value, 2)
        self.assertEqual(by_kind[("api", "external_exposure")].decision.disposition, PolicyDisposition.REQUIRES_CONFIRMATION)
        self.assertEqual(by_kind[("db", "secret_ref")].value["name"], "POSTGRES_PASSWORD")
        self.assertNotIn("changethis", intent.model_dump_json())
        self.assertEqual(by_kind[("db", "stateful_workload")].decision.disposition, PolicyDisposition.BLOCKED)
        self.assertTrue(all(candidate.evidence_refs or candidate.policy_version for candidate in intent.candidates))

    def test_production_does_not_create_cluster_validation_action(self):
        topology = ApplicationTopology(components=[app_component()])

        production = IntentBuilder().build(topology, Target.PRODUCTION)
        development = IntentBuilder().build(topology, Target.DEVELOPMENT)

        self.assertNotIn("cluster_validation", [candidate.kind for candidate in production.candidates])
        self.assertIn("cluster_validation", [candidate.kind for candidate in development.candidates])

    def test_writes_stable_intent_yaml_when_output_dir_is_configured(self):
        topology = ApplicationTopology(components=[app_component(), db_component()])
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            first = IntentBuilder(output_dir=output_dir).build(topology, "development")
            first_bytes = (output_dir / INTENT_ARTIFACT).read_bytes()
            second = IntentBuilder(output_dir=output_dir).build(topology, "development")
            second_bytes = (output_dir / INTENT_ARTIFACT).read_bytes()

        self.assertEqual(first.model_dump(mode="json"), second.model_dump(mode="json"))
        self.assertEqual(first_bytes, second_bytes)
        payload = yaml.safe_load(first_bytes)
        self.assertEqual(payload["kubernetes_intent"]["schema_version"], "kubernetes-intent/v1")


if __name__ == "__main__":
    unittest.main()
