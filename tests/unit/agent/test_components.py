import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from shutil import copytree

from k8sagent.analysis import AnalysisBundle, run_agent_analysis
from k8sagent.components import apply_selection, extract_candidates
from k8sagent.errors import AnalysisError
from preanalyzer.models.component import ComponentEntry, ComponentModel
from preanalyzer.models.dependency import DependencyEdge, DependencyModel, EnvBinding
from preanalyzer.models.fields import Confidence, Tracked
from preanalyzer.models.intent import ComponentIntent, KubernetesIntent, ServiceIntent, Workload
from preanalyzer.models.runtime import RuntimeEntry, RuntimeModel
from preanalyzer.reconciliation.engine import ReconciliationResult

FIXTURE = Path("tests/fixtures/repos/node-express-like")
CLOCK = lambda: datetime(2026, 7, 13, tzinfo=timezone.utc)


def tracked(value, source="test"):
    return Tracked(value=value, source=source, confidence=Confidence.HIGH, evidence_refs=[])


def make_bundle() -> AnalysisBundle:
    reconciliation = ReconciliationResult(
        component_model=ComponentModel(
            components=[
                ComponentEntry(component_id="api", role=tracked("application"), root_path="api"),
                ComponentEntry(component_id="db", role=tracked("dependency"), root_path=None),
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
                )
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
                    source_component="api",
                    target="external-cache",
                    dependency_type="cache",
                    confidence=tracked("medium"),
                ),
            ],
            env_bindings=[EnvBinding(component_id="api", name="DB_PASSWORD", kind="secret")],
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
            ]
        ),
        questions=None,
    )
    return AnalysisBundle(None, None, None, None, reconciliation)


class ComponentSelectionTests(unittest.TestCase):
    def test_extract_candidates_from_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            copytree(FIXTURE, repo)
            bundle = run_agent_analysis(repo, url=None, ref=None, clock=CLOCK)
            candidates = extract_candidates(bundle)
            self.assertGreaterEqual(len(candidates), 1)
            self.assertEqual([c.component_id for c in candidates], sorted(c.component_id for c in candidates))
            self.assertTrue(any(c.deployable for c in candidates))

    def test_non_application_selection_warns_without_excluding_it(self):
        bundle = make_bundle()
        result = apply_selection(bundle, ["api", "db"])
        self.assertEqual(result.selected, ["api", "db"])
        self.assertEqual(result.excluded, [])
        self.assertEqual(result.warnings, ["component 'db' has role 'dependency'"])

    def test_excluded_candidate_dependency_warns_without_changing_selection(self):
        result = apply_selection(make_bundle(), ["api"])
        self.assertEqual(result.selected, ["api"])
        self.assertEqual(result.excluded, ["db"])
        self.assertIn("selected 'api' depends on excluded 'db' (database)", result.warnings)

    def test_unknown_component_rejected(self):
        with self.assertRaises(AnalysisError):
            apply_selection(make_bundle(), ["missing"])

    def test_external_dependency_target_does_not_warn(self):
        result = apply_selection(make_bundle(), ["api"])
        self.assertFalse(any("external-cache" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
