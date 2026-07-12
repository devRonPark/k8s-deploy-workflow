import unittest
from pydantic import ValidationError
from preanalyzer.models.fields import Tracked, Confidence
from preanalyzer.models.component import ComponentModel, ComponentEntry
from preanalyzer.models.runtime import RuntimeModel, RuntimeEntry
from preanalyzer.models.dependency import DependencyModel, DependencyEdge, EnvBinding
from preanalyzer.models.intent import KubernetesIntent, ComponentIntent, Workload, ServiceIntent
from preanalyzer.models.questions import UnresolvedQuestions, UnresolvedQuestion
from preanalyzer.models.profile import DeploymentProfile
from preanalyzer.models.report import ValidationReport, StageResult


class IntermediateModelTests(unittest.TestCase):
    def test_component_roundtrip(self):
        m = ComponentModel(components=[ComponentEntry(
            component_id="backend",
            role=Tracked(value="application", source="rule", confidence=Confidence.HIGH, evidence_refs=["EV-1"]),
            root_path="backend")])
        again = ComponentModel.model_validate(m.model_dump())
        self.assertEqual(again.components[0].role.value, "application")

    def test_runtime_optional_port_command(self):
        e = RuntimeEntry(component_id="backend", language=Tracked(value="python", source="rule",
            confidence=Confidence.HIGH, evidence_refs=["EV-2"]), build_strategy="dockerfile")
        self.assertIsNone(e.port)
        self.assertIsNone(e.command)

    def test_dependency_model_shapes(self):
        d = DependencyModel(
            edges=[DependencyEdge(source_component="backend", target="db", dependency_type="database",
                confidence=Tracked(value="high", source="compose_depends_on", confidence=Confidence.HIGH, evidence_refs=["EV-3"]))],
            env_bindings=[EnvBinding(component_id="backend", name="DATABASE_URL", kind="configmap")])
        self.assertEqual(d.edges[0].target, "db")
        self.assertEqual(d.env_bindings[0].kind, "configmap")


class IntentModelTests(unittest.TestCase):
    def test_dependency_component_has_no_workload(self):
        intent = KubernetesIntent(components=[ComponentIntent(component_id="db", role="dependency")])
        self.assertIsNone(intent.components[0].workload)

    def test_application_workload_roundtrip(self):
        intent = KubernetesIntent(components=[ComponentIntent(
            component_id="backend", role="application",
            workload=Workload(port=Tracked(value=8000, source="dockerfile_expose", confidence=Confidence.HIGH, evidence_refs=["EV-4"]),
                              secret_env=["POSTGRES_PASSWORD"]),
            service=ServiceIntent(port=Tracked(value=8000, source="dockerfile_expose", confidence=Confidence.HIGH, evidence_refs=["EV-4"])))])
        again = KubernetesIntent.model_validate(intent.model_dump())
        self.assertEqual(again.components[0].workload.port.value, 8000)
        self.assertEqual(again.components[0].workload.secret_env, ["POSTGRES_PASSWORD"])


class QuestionProfileReportTests(unittest.TestCase):
    def test_profile_rejects_unknown_key(self):
        with self.assertRaises(ValidationError):
            DeploymentProfile.model_validate({"registr": "r.io"})  # typo

    def test_profile_defaults(self):
        p = DeploymentProfile.model_validate({"registry": "r.io", "namespace": "demo"})
        self.assertEqual(p.image_tag, "latest")

    def test_question_roundtrip(self):
        q = UnresolvedQuestions(questions=[UnresolvedQuestion(
            id="Q-REG-001", field="image_registry", question="Which registry?", reason="no registry evidence",
            answer_type="registry", blocking_level="application_runnable", profile_field="registry")])
        self.assertEqual(UnresolvedQuestions.model_validate(q.model_dump()).questions[0].id, "Q-REG-001")

    def test_report_levels(self):
        r = ValidationReport(target_level=1, achieved_level=1, stages=[StageResult(stage="kubeconform", status="pass")])
        self.assertEqual(r.achieved_level, 1)
