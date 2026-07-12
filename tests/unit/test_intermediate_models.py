import unittest
from preanalyzer.models.fields import Tracked, Confidence
from preanalyzer.models.component import ComponentModel, ComponentEntry
from preanalyzer.models.runtime import RuntimeModel, RuntimeEntry
from preanalyzer.models.dependency import DependencyModel, DependencyEdge, EnvBinding


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
