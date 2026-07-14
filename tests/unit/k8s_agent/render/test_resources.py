from __future__ import annotations

import unittest

from k8s_agent.render.resources import build_deployment, build_ingress, build_service


class RenderResourceTests(unittest.TestCase):
    def test_deployment_service_labels_and_ports_match(self):
        deployment = build_deployment(
            component_id="api",
            image="api:latest",
            replicas=2,
            port=8000,
            command="uvicorn main:app",
            secret_names=["api-secret"],
        )
        service = build_service("api", 8000)

        pod_labels = deployment["spec"]["template"]["metadata"]["labels"]
        selector = service["spec"]["selector"]
        self.assertEqual(selector, pod_labels)
        self.assertEqual(service["spec"]["ports"][0]["targetPort"], 8000)
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(container["ports"][0]["containerPort"], 8000)
        self.assertEqual(container["envFrom"][0]["secretRef"]["name"], "api-secret")
        self.assertNotIn("changethis", str(deployment))

    def test_ingress_uses_service_name_and_host(self):
        ingress = build_ingress("api", "api.example.com", 8000)

        backend = ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]
        self.assertEqual(backend["name"], "api-svc")
        self.assertEqual(backend["port"]["number"], 8000)


if __name__ == "__main__":
    unittest.main()
