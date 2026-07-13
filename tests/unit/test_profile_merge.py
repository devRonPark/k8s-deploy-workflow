import unittest
from preanalyzer.models.evidence import EvidenceModel
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
