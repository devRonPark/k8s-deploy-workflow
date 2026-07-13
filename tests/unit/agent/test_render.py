import sys
import tempfile
import unittest
from pathlib import Path

from k8sagent.models.intent import (
    AgentKubernetesIntent,
    ComponentIntentSpec,
    IngressSpec,
    PVCSpec,
    SecretRefSpec,
    ServiceSpec,
    set_intent_path,
)
from k8sagent.render import render_all, write_manifests
from preanalyzer.models.fields import Confidence, Tracked


def tracked(value):
    return Tracked(value=value, source="test", confidence=Confidence.HIGH, evidence_refs=[])


def complete_intent() -> AgentKubernetesIntent:
    intent = AgentKubernetesIntent(
        namespace=tracked("demo"),
        components=[
            ComponentIntentSpec(
                component_id="web",
                role="application",
                service=ServiceSpec(port=tracked(3000)),
                secret_refs=[
                    SecretRefSpec(
                        env_name="DB_PASSWORD",
                        secret_name=tracked("db-secret"),
                        secret_key=tracked("password"),
                    )
                ],
                configmap={
                    "EMPTY": Tracked(),
                    "LOG_LEVEL": tracked("info"),
                },
                ingress=IngressSpec(host=tracked("app.example.com")),
                pvc=PVCSpec(size=tracked("1Gi"), mount_path=tracked("/data")),
            )
        ],
    )
    for path, value in [
        ("components.web.workload.image.registry", "registry.example.com:5000"),
        ("components.web.workload.image.name", "web"),
        ("components.web.workload.image.tag", "1.0.0"),
        ("components.web.workload.container_port", 3000),
        ("components.web.workload.command", "python app.py"),
        ("components.web.workload.replicas", 2),
    ]:
        intent = set_intent_path(intent, path, value, source="user_decision")
    return intent


class RenderTests(unittest.TestCase):
    def test_complete_intent_renders_expected_files_and_deployment_yaml(self):
        rendered = render_all(complete_intent(), commit_sha="abc123")
        self.assertEqual(
            sorted(rendered.files),
            [
                "namespace.yaml",
                "web/configmap.yaml",
                "web/deployment.yaml",
                "web/ingress.yaml",
                "web/pvc.yaml",
                "web/service.yaml",
            ],
        )
        expected = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: demo
  labels:
    app.kubernetes.io/name: web
    app.kubernetes.io/part-of: web
    app.kubernetes.io/managed-by: k8s-agent
  annotations:
    k8s-agent/commit-sha: abc123
    k8s-agent/version: 0.1.0
spec:
  replicas: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: web
  template:
    metadata:
      labels:
        app.kubernetes.io/name: web
        app.kubernetes.io/part-of: web
        app.kubernetes.io/managed-by: k8s-agent
    spec:
      containers:
      - name: web
        image: registry.example.com:5000/web:1.0.0
        command:
        - python
        - app.py
        ports:
        - containerPort: 3000
        env:
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: db-secret
              key: password
        envFrom:
        - configMapRef:
            name: web-config
        volumeMounts:
        - name: web-data
          mountPath: /data
      volumes:
      - name: web-data
        persistentVolumeClaim:
          claimName: web-data
"""
        self.assertEqual(rendered.files["web/deployment.yaml"], expected)

    def test_rendering_is_deterministic(self):
        self.assertEqual(
            render_all(complete_intent(), commit_sha="abc123").files,
            render_all(complete_intent(), commit_sha="abc123").files,
        )

    def test_secret_refs_do_not_create_secret_documents_or_placeholders(self):
        text = "\n".join(render_all(complete_intent(), commit_sha=None).files.values())
        self.assertIn("secretKeyRef", text)
        self.assertNotIn("kind: Secret", text)
        self.assertNotIn("__REPLACE_ME__", text)
        self.assertNotIn("super-secret-value", text)

    def test_unresolved_image_defers_component(self):
        intent = complete_intent()
        intent = set_intent_path(
            intent,
            "components.web.workload.image.registry",
            None,
            source="user_decision",
        )
        rendered = render_all(intent, commit_sha=None)
        self.assertIn("web: image registry or name unresolved", rendered.deferred)
        self.assertFalse(any(path.startswith("web/") for path in rendered.files))

    def test_replicas_unset_omits_key(self):
        intent = set_intent_path(
            complete_intent(),
            "components.web.workload.replicas",
            None,
            source="user_decision",
        )
        self.assertNotIn("replicas:", render_all(intent, commit_sha=None).files["web/deployment.yaml"])

    def test_configmap_omits_unset_keys(self):
        configmap = render_all(complete_intent(), commit_sha=None).files["web/configmap.yaml"]
        self.assertIn("LOG_LEVEL: info", configmap)
        self.assertNotIn("EMPTY", configmap)

    def test_ingress_without_host_not_rendered(self):
        intent = set_intent_path(
            complete_intent(),
            "components.web.ingress.host",
            None,
            source="user_decision",
        )
        self.assertNotIn("web/ingress.yaml", render_all(intent, commit_sha=None).files)

    def test_import_boundary(self):
        sys.modules.pop("k8sagent.llm", None)
        sys.modules.pop("preanalyzer.analyzer.scanner", None)
        import k8sagent.render.resources  # noqa: F401

        self.assertNotIn("k8sagent.llm", sys.modules)
        self.assertNotIn("preanalyzer.analyzer.scanner", sys.modules)

    def test_write_manifests_replaces_stale_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = root / "web" / "stale.yaml"
            stale.parent.mkdir(parents=True)
            stale.write_text("old", encoding="utf-8")
            paths = write_manifests(render_all(complete_intent(), "abc123"), root)
            self.assertFalse(stale.exists())
            self.assertTrue(paths)


if __name__ == "__main__":
    unittest.main()
