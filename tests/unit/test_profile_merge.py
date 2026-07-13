import unittest
from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.fields import Confidence
from preanalyzer.models.rule_inference import RuleInferenceSet, ComponentCandidate, RoleCandidate, RuntimePortCandidate
from preanalyzer.models.profile import DeploymentProfile
from preanalyzer.reconciliation.engine import reconcile
from preanalyzer.reconciliation.profile_merge import merge


def _base():
    rules = RuleInferenceSet(
        component_candidates=[ComponentCandidate("backend", "backend", "compose", ["EV-1"])],
        role_candidates=[RoleCandidate("backend", "application", "rule", "high", ["EV-1"])],
        runtime_port_candidates=[RuntimePortCandidate("backend", 8000, "dockerfile_expose", "high", ["EV-2"])])
    return reconcile(rules, EvidenceModel())


def _port_conflict():
    rules = RuleInferenceSet(
        component_candidates=[ComponentCandidate("web", "web", "compose", ["EV-1"])],
        role_candidates=[RoleCandidate("web", "application", "rule", "high", ["EV-1"])],
        runtime_port_candidates=[
            RuntimePortCandidate("web", 8080, "dockerfile_expose", "high", ["EV-2"]),
            RuntimePortCandidate("web", 3000, "compose_ports", "high", ["EV-3"]),
        ])
    return reconcile(rules, EvidenceModel())


class ProfileMergeTests(unittest.TestCase):
    def test_registry_namespace_resolved_and_questions_dropped(self):
        res = _base()
        m = merge(res, DeploymentProfile(registry="reg.internal", namespace="demo"))
        ci = m.intent.components[0]
        self.assertEqual(ci.workload.image_registry.value, "reg.internal")
        self.assertEqual(m.intent.namespace.value, "demo")
        ids = {q.id for q in m.questions.questions}
        self.assertNotIn("Q-REG-001", ids)
        self.assertNotIn("Q-NS-001", ids)

    def test_ready_for_level2_when_no_blocking_questions(self):
        res = _base()
        m = merge(res, DeploymentProfile(registry="reg.internal", namespace="demo"))
        self.assertTrue(m.ready_for_level2)

    def test_component_service_port_profile_resolves_port_question(self):
        res = _port_conflict()
        profile = DeploymentProfile.model_validate({
            "components": {
                "web": {
                    "service": {
                        "port": 8081,
                    },
                },
            },
        })

        m = merge(res, profile)

        ci = m.intent.components[0]
        self.assertEqual(ci.service.port.value, 8081)
        self.assertEqual(ci.workload.port.value, 8081)
        self.assertEqual(ci.service.port.source, "deployment_profile")
        self.assertEqual(ci.service.port.confidence, Confidence.HIGH)
        self.assertEqual(ci.service.port.evidence_refs, [])
        ids = {q.id for q in m.questions.questions}
        self.assertNotIn("Q-PORT-web", ids)

    def test_component_service_port_unknown_component_rejected(self):
        res = _base()
        profile = DeploymentProfile.model_validate({
            "components": {
                "ghost": {
                    "service": {
                        "port": 8081,
                    },
                },
            },
        })

        with self.assertRaisesRegex(ValueError, "unknown deployment profile component: ghost"):
            merge(res, profile)
