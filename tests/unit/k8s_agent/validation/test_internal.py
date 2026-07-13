from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from k8s_agent.validation.internal import InternalManifestValidator


class InternalValidationTests(unittest.TestCase):
    def test_valid_bundle_has_no_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "deployment.yaml", deployment())
            write(root / "service.yaml", service())

            findings = InternalManifestValidator().validate_paths([root / "deployment.yaml", root / "service.yaml"])

        self.assertEqual(findings, [])

    def test_duplicate_resource_and_selector_target_port_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dep = deployment()
            svc = service()
            svc["spec"]["selector"] = {"app.kubernetes.io/name": "other"}
            svc["spec"]["ports"][0]["targetPort"] = 9000
            write(root / "deployment-a.yaml", dep)
            write(root / "deployment-b.yaml", dep)
            write(root / "service.yaml", svc)

            findings = InternalManifestValidator().validate_paths(sorted(root.glob("*.yaml")))

        codes = [finding.code for finding in findings]
        self.assertIn("duplicate_resource", codes)
        self.assertIn("service_selector_mismatch", codes)
        self.assertIn("service_target_port_mismatch", codes)


def write(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def deployment() -> dict:
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "api-deployment"},
        "spec": {
            "selector": {"matchLabels": {"app.kubernetes.io/name": "api"}},
            "template": {
                "metadata": {"labels": {"app.kubernetes.io/name": "api"}},
                "spec": {"containers": [{"name": "api", "image": "api:latest", "ports": [{"containerPort": 8000}]}]},
            },
        },
    }


def service() -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": "api-svc"},
        "spec": {"selector": {"app.kubernetes.io/name": "api"}, "ports": [{"port": 8000, "targetPort": 8000}]},
    }


if __name__ == "__main__":
    unittest.main()
