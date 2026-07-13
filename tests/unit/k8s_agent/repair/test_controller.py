from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from k8s_agent.models.validation import ResourceRef, ValidationFinding, ValidationReport
from k8s_agent.repair.controller import RepairController
from k8s_agent.render.renderer import GeneratedFile, ManifestBundle, ResourceRef as BundleResourceRef
from tests.unit.k8s_agent.validation.test_internal import deployment, service, write
from tests.acceptance.test_manifest_renderer import profile_for


class RepairControllerTests(unittest.TestCase):
    def test_repairs_generated_service_selector_and_target_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "base").mkdir()
            write(root / "base" / "api-deployment.yaml", deployment())
            svc = service()
            svc["spec"]["selector"] = {"app.kubernetes.io/name": "other"}
            svc["spec"]["ports"][0]["targetPort"] = 9000
            write(root / "base" / "api-service.yaml", svc)
            bundle = bundle_for(root)
            report = ValidationReport(status="fail", manifest_ready=False, findings=[
                finding("service_selector_mismatch"),
                finding("service_target_port_mismatch"),
            ])

            result = RepairController(destination=root).repair(bundle, profile_for(external="private"), report)

            repaired = yaml.safe_load((root / "base" / "api-service.yaml").read_text(encoding="utf-8"))
            self.assertTrue(result.repaired)
            self.assertTrue(result.validation_result.manifest_ready)
            self.assertEqual(repaired["spec"]["selector"], {"app.kubernetes.io/name": "api"})
            self.assertEqual(repaired["spec"]["ports"][0]["targetPort"], 8000)
            self.assertTrue((root / "repairs" / "attempt-1.yaml").is_file())

    def test_rejects_finding_path_outside_generated_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "base").mkdir()
            write(root / "base" / "api-deployment.yaml", deployment())
            write(root / "base" / "api-service.yaml", service())
            report = ValidationReport(status="fail", manifest_ready=False, findings=[finding("service_selector_mismatch", path="../source.yaml")])

            result = RepairController(destination=root).repair(bundle_for(root), profile_for(external="private"), report)

            self.assertFalse(result.repaired)
            self.assertIn("generated_path_guard", result.blocked_reasons)


def bundle_for(root: Path) -> ManifestBundle:
    return ManifestBundle(
        resource_refs=[BundleResourceRef(kind="Service", name="api-svc", path="base/api-service.yaml")],
        files=[
            GeneratedFile(path="base/api-deployment.yaml", checksum="sha256:test"),
            GeneratedFile(path="base/api-service.yaml", checksum="sha256:test"),
        ],
        checksum="sha256:test",
    )


def finding(code: str, path: str = "base/api-service.yaml") -> ValidationFinding:
    return ValidationFinding(
        finding_id=f"VF-{code}",
        validator="internal",
        severity="error",
        resource_ref=ResourceRef(kind="Service", name="api-svc", path=path),
        field_path="/spec",
        code=code,
        message=code,
        repairable=True,
    )


if __name__ == "__main__":
    unittest.main()
