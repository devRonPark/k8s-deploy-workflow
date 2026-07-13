import unittest

import yaml

from preanalyzer.models.fields import Confidence, Tracked
from preanalyzer.models.intent import ComponentIntent, KubernetesIntent, ServiceIntent, Workload
from preanalyzer.renderer.engine import TemplateRenderer


def _t(v, s="x"):
    return Tracked(value=v, source=s, confidence=Confidence.HIGH, evidence_refs=["EV"])


def _app_intent(registry=True):
    workload = Workload(
        image_name=_t("backend"),
        image_tag=_t("v0"),
        port=_t(8000),
        command=_t("uvicorn main:app"),
        secret_env=["POSTGRES_PASSWORD"],
    )
    if registry:
        workload.image_registry = _t("reg.internal")
    return KubernetesIntent(
        namespace=_t("demo"),
        components=[
            ComponentIntent(
                component_id="backend",
                role="application",
                workload=workload,
                service=ServiceIntent(port=_t(8000)),
            )
        ],
    )


class RendererTests(unittest.TestCase):
    def test_renders_deployment_service_sa_secret(self):
        result = TemplateRenderer(commit_sha="abc123", rules_version="2026.07").render(_app_intent())
        paths = set(result.files)
        self.assertTrue(any(path.endswith("backend/deployment.yaml") for path in paths))
        self.assertTrue(any(path.endswith("backend/service.yaml") for path in paths))
        self.assertTrue(any(path.endswith("backend/serviceaccount.yaml") for path in paths))
        self.assertTrue(any(path.endswith("backend/secret.yaml") for path in paths))

        deployment = yaml.safe_load(
            next(text for path, text in result.files.items() if path.endswith("deployment.yaml"))
        )
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(container["image"], "reg.internal/backend:v0")
        self.assertEqual(container["ports"][0]["containerPort"], 8000)
        self.assertNotIn("resources", container)
        self.assertEqual(deployment["metadata"]["namespace"], "demo")
        self.assertEqual(deployment["metadata"]["labels"]["app.kubernetes.io/managed-by"], "preanalyzer")

    def test_secret_placeholder_value_is_replace_me(self):
        result = TemplateRenderer("abc", "2026.07").render(_app_intent())
        secret = yaml.safe_load(next(text for path, text in result.files.items() if path.endswith("secret.yaml")))
        self.assertEqual(secret["stringData"]["POSTGRES_PASSWORD"], "__REPLACE_ME__")

    def test_defers_deployment_without_registry(self):
        result = TemplateRenderer("abc", "2026.07").render(_app_intent(registry=False))
        self.assertFalse(any(path.endswith("deployment.yaml") for path in result.files))
        self.assertTrue(
            any(
                deferred.resource == "Deployment" and deferred.reason == "unresolved_image_registry"
                for deferred in result.deferred
            )
        )

    def test_dependency_component_renders_nothing(self):
        intent = KubernetesIntent(components=[ComponentIntent(component_id="db", role="dependency")])
        result = TemplateRenderer("abc", "2026.07").render(intent)
        self.assertEqual(result.files, {})


if __name__ == "__main__":
    unittest.main()
