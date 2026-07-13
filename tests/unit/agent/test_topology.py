import tempfile
import unittest
from pathlib import Path

import yaml

from k8sagent.analysis import AnalysisBundle
from k8sagent.components import SelectionResult
from k8sagent.models.topology import ApplicationTopology, build_topology, write_topology
from preanalyzer.models.component import ComponentEntry, ComponentModel
from preanalyzer.models.dependency import DependencyEdge, DependencyModel
from preanalyzer.models.fields import Confidence, Tracked
from preanalyzer.models.intent import ComponentIntent, KubernetesIntent, ServiceIntent, Workload
from preanalyzer.models.runtime import RuntimeEntry, RuntimeModel
from preanalyzer.reconciliation.engine import ReconciliationResult


def tracked(value, source="test"):
    return Tracked(value=value, source=source, confidence=Confidence.HIGH, evidence_refs=[])


class SnapshotStub:
    commit_sha = "abc123"


def make_bundle() -> AnalysisBundle:
    reconciliation = ReconciliationResult(
        component_model=ComponentModel(
            components=[
                ComponentEntry(component_id="api", role=tracked("application"), root_path="api"),
                ComponentEntry(component_id="db", role=tracked("dependency"), root_path=None),
                ComponentEntry(component_id="worker", role=tracked("application"), root_path="worker"),
            ]
        ),
        runtime_model=RuntimeModel(
            runtimes=[
                RuntimeEntry(
                    component_id="api",
                    language=tracked("python"),
                    build_strategy="dockerfile",
                    port=tracked(8080),
                    command=tracked("python app.py"),
                ),
                RuntimeEntry(
                    component_id="worker",
                    language=tracked("python"),
                    build_strategy="dockerfile",
                    port=None,
                    command=None,
                ),
            ]
        ),
        dependency_model=DependencyModel(
            edges=[
                DependencyEdge(
                    source_component="api",
                    target="db",
                    dependency_type="database",
                    confidence=tracked("high"),
                ),
                DependencyEdge(
                    source_component="worker",
                    target="api",
                    dependency_type="http",
                    confidence=tracked("medium"),
                ),
            ]
        ),
        intent=KubernetesIntent(
            components=[
                ComponentIntent(
                    component_id="api",
                    role="application",
                    workload=Workload(
                        image_name=tracked("api"),
                        port=tracked(8080),
                        command=tracked("python app.py"),
                        secret_env=["DB_PASSWORD"],
                        config_env=["LOG_LEVEL"],
                    ),
                    service=ServiceIntent(port=tracked(8080)),
                ),
                ComponentIntent(component_id="db", role="dependency"),
                ComponentIntent(component_id="worker", role="application", workload=Workload()),
            ]
        ),
        questions=None,
    )
    return AnalysisBundle(SnapshotStub(), None, None, None, reconciliation)


class TopologyTests(unittest.TestCase):
    def test_build_selected_components_and_edges(self):
        topology = build_topology(
            make_bundle(),
            SelectionResult(
                selected=["api", "worker"],
                excluded=["db"],
                warnings=["selected 'api' depends on excluded 'db' (database)"],
            ),
        )
        self.assertEqual([component.component_id for component in topology.components], ["api", "worker"])
        self.assertEqual(topology.excluded, ["db"])
        by_target = {edge.target: edge for edge in topology.edges}
        self.assertFalse(by_target["db"].target_selected)
        self.assertTrue(by_target["api"].target_selected)

    def test_yaml_roundtrip(self):
        topology = build_topology(
            make_bundle(),
            SelectionResult(selected=["api"], excluded=["db", "worker"], warnings=[]),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = write_topology(topology, Path(tmp))
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(ApplicationTopology.model_validate(loaded), topology)

    def test_deterministic_dump(self):
        selection = SelectionResult(selected=["worker", "api"], excluded=["db"], warnings=[])
        first = build_topology(make_bundle(), selection).model_dump()
        second = build_topology(make_bundle(), selection).model_dump()
        self.assertEqual(first, second)

    def test_secret_values_are_not_serialized(self):
        topology = build_topology(
            make_bundle(),
            SelectionResult(selected=["api"], excluded=["db", "worker"], warnings=[]),
        )
        dumped = str(topology.model_dump())
        self.assertIn("DB_PASSWORD", dumped)
        self.assertNotIn("super-secret-value", dumped)


if __name__ == "__main__":
    unittest.main()
