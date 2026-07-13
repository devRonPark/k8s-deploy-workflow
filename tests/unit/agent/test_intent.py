import unittest

from pydantic import ValidationError

from k8sagent.errors import ChangeSetError
from k8sagent.models.intent import (
    AgentKubernetesIntent,
    ComponentIntentSpec,
    SecretRefSpec,
    build_intent,
    get_intent_path,
    intent_path_exists,
    set_intent_path,
)
from k8sagent.models.topology import ApplicationTopology, TopologyComponent
from preanalyzer.models.fields import Confidence, Tracked
from preanalyzer.models.intent import ComponentIntent, KubernetesIntent, ServiceIntent, Workload


def tracked(value, source="test"):
    return Tracked(value=value, source=source, confidence=Confidence.HIGH, evidence_refs=["E1"])


def make_topology() -> ApplicationTopology:
    return ApplicationTopology(
        components=[
            TopologyComponent(
                component_id="api",
                root_path="api",
                role="application",
                port=tracked(8080, "runtime"),
                command=tracked("python app.py", "runtime"),
                secret_env=["DB_PASSWORD"],
                config_env=["LOG_LEVEL"],
            ),
            TopologyComponent(component_id="db", role="dependency"),
        ]
    )


def make_baseline() -> KubernetesIntent:
    return KubernetesIntent(
        components=[
            ComponentIntent(
                component_id="api",
                role="application",
                workload=Workload(
                    image_name=tracked("api", "component_id"),
                    port=tracked(8080, "runtime"),
                    command=tracked("python app.py", "runtime"),
                    secret_env=["DB_PASSWORD"],
                    config_env=["LOG_LEVEL"],
                ),
                service=ServiceIntent(port=tracked(8080, "runtime")),
            ),
            ComponentIntent(component_id="db", role="dependency"),
        ]
    )


class IntentTests(unittest.TestCase):
    def test_build_intent_preserves_baseline_tracked_sources(self):
        intent = build_intent(make_topology(), make_baseline())
        api = intent.components[0]
        self.assertEqual(api.workload.container_port.source, "runtime")
        self.assertEqual(api.workload.command.source, "runtime")
        self.assertEqual(api.workload.image.name.source, "component_id")
        self.assertEqual(api.secret_refs[0].env_name, "DB_PASSWORD")
        self.assertIn("LOG_LEVEL", api.configmap)

    def test_set_namespace_tracks_user_decision(self):
        intent = set_intent_path(
            build_intent(make_topology(), make_baseline()),
            "namespace",
            "prod",
            source="user_decision",
        )
        self.assertEqual(intent.namespace.value, "prod")
        self.assertEqual(intent.namespace.source, "user_decision")
        self.assertEqual(intent.namespace.confidence, Confidence.HIGH)

    def test_invalid_port_rejected(self):
        with self.assertRaises(ChangeSetError):
            set_intent_path(
                build_intent(make_topology(), make_baseline()),
                "components.api.service.port",
                70000,
                source="user_decision",
            )

    def test_unknown_path_rejected(self):
        with self.assertRaises(ChangeSetError):
            set_intent_path(
                build_intent(make_topology(), make_baseline()),
                "components.api.workload.cpu",
                "1",
                source="user_decision",
            )

    def test_unknown_component_rejected(self):
        with self.assertRaises(ChangeSetError):
            set_intent_path(
                build_intent(make_topology(), make_baseline()),
                "components.missing.service.port",
                80,
                source="user_decision",
            )

    def test_service_created_when_setting_port(self):
        intent = AgentKubernetesIntent(
            components=[ComponentIntentSpec(component_id="api", role="application")]
        )
        updated = set_intent_path(
            intent, "components.api.service.port", 80, source="user_decision"
        )
        self.assertEqual(updated.components[0].service.port.value, 80)

    def test_unset_removes_empty_ingress(self):
        intent = set_intent_path(
            build_intent(make_topology(), make_baseline()),
            "components.api.ingress.host",
            "app.example.com",
            source="user_decision",
        )
        self.assertIsNotNone(intent.components[0].ingress)
        updated = set_intent_path(
            intent, "components.api.ingress.host", None, source="user_decision"
        )
        self.assertIsNone(updated.components[0].ingress)

    def test_secret_refs_cannot_invent_env(self):
        with self.assertRaises(ChangeSetError):
            set_intent_path(
                build_intent(make_topology(), make_baseline()),
                "components.api.secret_refs.NEW_SECRET.secret_name",
                "existing-secret",
                source="user_decision",
            )

    def test_set_intent_path_is_pure(self):
        intent = build_intent(make_topology(), make_baseline())
        updated = set_intent_path(
            intent, "components.api.workload.replicas", 3, source="user_decision"
        )
        self.assertIsNone(intent.components[0].workload.replicas)
        self.assertEqual(updated.components[0].workload.replicas.value, 3)

    def test_dump_roundtrip_and_get_path(self):
        intent = set_intent_path(
            build_intent(make_topology(), make_baseline()),
            "components.api.workload.image.tag",
            "v1",
            source="user_decision",
        )
        self.assertTrue(intent_path_exists(intent, "components.api.workload.image.tag"))
        self.assertEqual(get_intent_path(intent, "components.api.workload.image.tag"), "v1")
        self.assertEqual(AgentKubernetesIntent.model_validate(intent.model_dump()), intent)

    def test_invalid_model_rejected(self):
        with self.assertRaises(ValidationError):
            SecretRefSpec(env_name="")


if __name__ == "__main__":
    unittest.main()
