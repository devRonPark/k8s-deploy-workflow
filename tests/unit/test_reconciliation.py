import unittest
from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.rule_inference import (
    RuleInferenceSet, ComponentCandidate, RoleCandidate, RuntimePortCandidate,
    RuntimeCommandCandidate)
from preanalyzer.reconciliation.engine import reconcile, AcceptedSemanticCommand


def _rules(**kw):
    return RuleInferenceSet(**kw)


class ReconciliationTests(unittest.TestCase):
    def test_application_component_gets_workload_and_service(self):
        rules = _rules(
            component_candidates=[ComponentCandidate("backend", "backend", "compose", ["EV-1"])],
            role_candidates=[RoleCandidate("backend", "application", "rule", "high", ["EV-1"])],
            runtime_port_candidates=[RuntimePortCandidate("backend", 8000, "dockerfile_expose", "high", ["EV-2"])],
            runtime_command_candidates=[RuntimeCommandCandidate("backend", "uvicorn main:app", "dockerfile_cmd", "high", ["EV-3"])])
        r = reconcile(rules, EvidenceModel())
        ci = r.intent.components[0]
        self.assertEqual(ci.role, "application")
        self.assertEqual(ci.workload.port.value, 8000)
        self.assertEqual(ci.workload.command.value, "uvicorn main:app")
        self.assertIsNotNone(ci.service)

    def test_dependency_component_has_no_workload(self):
        rules = _rules(
            component_candidates=[ComponentCandidate("db", None, "compose", ["EV-9"])],
            role_candidates=[RoleCandidate("db", "dependency", "infra_image_pattern", "high", ["EV-9"])])
        r = reconcile(rules, EvidenceModel())
        self.assertIsNone(r.intent.components[0].workload)

    def test_registry_and_namespace_questions_emitted(self):
        rules = _rules(
            component_candidates=[ComponentCandidate("backend", "backend", "compose", ["EV-1"])],
            role_candidates=[RoleCandidate("backend", "application", "rule", "high", ["EV-1"])])
        r = reconcile(rules, EvidenceModel())
        ids = {q.id for q in r.questions.questions}
        self.assertIn("Q-REG-001", ids)
        self.assertIn("Q-NS-001", ids)

    def test_port_conflict_routes_question_not_guess(self):
        rules = _rules(
            component_candidates=[ComponentCandidate("web", "web", "compose", ["EV-1"])],
            role_candidates=[RoleCandidate("web", "application", "rule", "high", ["EV-1"])],
            runtime_port_candidates=[
                RuntimePortCandidate("web", 8080, "dockerfile_expose", "high", ["EV-2"]),
                RuntimePortCandidate("web", 8081, "compose_ports", "high", ["EV-3"])])
        r = reconcile(rules, EvidenceModel())
        rt = r.runtime_model.runtimes[0]
        self.assertIsNone(rt.port)
        pq = [q for q in r.questions.questions if q.answer_type == "port"]
        self.assertEqual(len(pq), 1)
        self.assertEqual(sorted(pq[0].candidates), ["8080", "8081"])

    def test_accepted_semantic_command_flows_into_runtime(self):
        rules = _rules(
            component_candidates=[ComponentCandidate("backend", "backend", "compose", ["EV-1"])],
            role_candidates=[RoleCandidate("backend", "application", "rule", "high", ["EV-1"])],
            runtime_port_candidates=[RuntimePortCandidate("backend", 8000, "dockerfile_expose", "high", ["EV-2"])])
        r = reconcile(rules, EvidenceModel(),
            [AcceptedSemanticCommand("backend", "uvicorn main:app --host 0.0.0.0", ["EV-ENTRY-1"])])
        rt = r.runtime_model.runtimes[0]
        self.assertEqual(rt.command.value, "uvicorn main:app --host 0.0.0.0")
        self.assertEqual(rt.command.source, "llm_semantic_inference")
