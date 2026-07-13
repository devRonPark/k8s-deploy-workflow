import unittest

from k8sagent.errors import ChangeSetError
from k8sagent.gaps import find_unresolved
from k8sagent.models.intent import (
    AgentKubernetesIntent,
    ComponentIntentSpec,
    ImageSpec,
    IngressSpec,
    SecretRefSpec,
    ServiceSpec,
    WorkloadSpec,
    set_intent_path,
)
from k8sagent.models.topology import ApplicationTopology, TopologyComponent
from k8sagent.questions import Question, apply_answer, build_questions, parse_answer
from preanalyzer.models.fields import Confidence, Tracked


def tracked(value):
    return Tracked(value=value, source="test", confidence=Confidence.HIGH, evidence_refs=[])


def make_intent() -> AgentKubernetesIntent:
    return AgentKubernetesIntent(
        components=[
            ComponentIntentSpec(
                component_id="api",
                role="application",
                workload=WorkloadSpec(image=ImageSpec(name=tracked("api"))),
            )
        ]
    )


class GapQuestionTests(unittest.TestCase):
    def test_empty_intent_reports_blocking_namespace_registry_and_optional_tag(self):
        gaps = find_unresolved(make_intent())
        by_path = {gap.path: gap for gap in gaps}
        self.assertEqual(by_path["namespace"].severity, "blocking")
        self.assertEqual(
            by_path["components.api.workload.image.registry"].severity, "blocking"
        )
        self.assertEqual(by_path["components.api.workload.image.tag"].severity, "optional")

    def test_service_port_gaps(self):
        intent = make_intent()
        intent.components[0].service = ServiceSpec()
        paths = [gap.path for gap in find_unresolved(intent)]
        self.assertIn("components.api.service.port", paths)
        self.assertIn("components.api.workload.container_port", paths)

    def test_secret_refs_create_name_and_key_gaps(self):
        intent = make_intent()
        intent.components[0].secret_refs = [
            SecretRefSpec(env_name="DB_PASSWORD"),
            SecretRefSpec(env_name="API_TOKEN"),
        ]
        paths = [gap.path for gap in find_unresolved(intent)]
        self.assertIn("components.api.secret_refs.DB_PASSWORD.secret_name", paths)
        self.assertIn("components.api.secret_refs.DB_PASSWORD.secret_key", paths)
        self.assertIn("components.api.secret_refs.API_TOKEN.secret_name", paths)
        self.assertIn("components.api.secret_refs.API_TOKEN.secret_key", paths)

    def test_resolved_blocking_gaps_are_zero(self):
        intent = make_intent()
        for path, value in [
            ("namespace", "prod"),
            ("components.api.workload.image.registry", "registry.example.com"),
            ("components.api.workload.image.tag", "v1"),
        ]:
            intent = set_intent_path(intent, path, value, source="user_decision")
        blocking = [gap for gap in find_unresolved(intent) if gap.severity == "blocking"]
        self.assertEqual(blocking, [])

    def test_questions_are_deterministic_and_tag_defaults_latest(self):
        gaps = find_unresolved(make_intent())
        topology = ApplicationTopology(
            components=[TopologyComponent(component_id="api", role="application", port=tracked(8080))]
        )
        first = build_questions(gaps, topology)
        second = build_questions(gaps, topology)
        self.assertEqual(first, second)
        tag = next(q for q in first if q.path.endswith(".image.tag"))
        self.assertEqual(tag.default, "latest")

    def test_parse_answer_valid_and_invalid_values(self):
        gaps = find_unresolved(make_intent())
        topology = ApplicationTopology(
            components=[TopologyComponent(component_id="api", role="application", port=tracked(8080))]
        )
        questions = {q.path: q for q in build_questions(gaps, topology)}
        self.assertEqual(
            parse_answer(questions["components.api.workload.image.registry"], "registry.example.com"),
            "registry.example.com",
        )
        port_question = build_questions(
            [
                find_unresolved(
                    AgentKubernetesIntent(
                        namespace=tracked("prod"),
                        components=[
                            ComponentIntentSpec(
                                component_id="api",
                                role="application",
                                workload=WorkloadSpec(
                                    image=ImageSpec(
                                        registry=tracked("registry.example.com"),
                                        name=tracked("api"),
                                        tag=tracked("v1"),
                                    )
                                ),
                                service=ServiceSpec(),
                            )
                        ],
                    )
                )[0]
            ],
            topology,
        )[0]
        self.assertEqual(parse_answer(port_question, "8080"), 8080)
        with self.assertRaises(ChangeSetError):
            parse_answer(port_question, "70000")

    def test_parse_quantity_and_bool(self):
        pvc_gaps = find_unresolved(
            AgentKubernetesIntent(
                namespace=tracked("prod"),
                components=[
                    ComponentIntentSpec(
                        component_id="api",
                        role="application",
                        pvc={"size": None, "mount_path": None},
                    )
                ],
            )
        )
        quantity = next(q for q in build_questions(pvc_gaps, ApplicationTopology()) if q.path.endswith(".pvc.size"))
        self.assertEqual(parse_answer(quantity, "1Gi"), "1Gi")
        with self.assertRaises(ChangeSetError):
            parse_answer(quantity, "1TB")
        bool_question = Question(
            id="Q-create_namespace",
            path="create_namespace",
            text="Create namespace?",
            answer_type="bool",
            severity="optional",
        )
        self.assertTrue(parse_answer(bool_question, "y"))
        self.assertFalse(parse_answer(bool_question, "n"))

    def test_apply_answer_tracks_user_decision(self):
        intent = make_intent()
        question = next(q for q in build_questions(find_unresolved(intent), ApplicationTopology()) if q.path == "namespace")
        updated = apply_answer(intent, question, "prod")
        self.assertEqual(updated.namespace.source, "user_decision")


if __name__ == "__main__":
    unittest.main()
