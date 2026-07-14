from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from k8s_agent.render.renderer import ManifestRenderer
from k8s_agent.validation.kubeconform import KubeconformValidator, project_kubeconform_binary
from k8s_agent.validation.orchestrator import ValidationOrchestrator
from tests.acceptance.test_manifest_renderer import profile_for


class ManifestValidationAcceptanceTests(unittest.TestCase):
    def test_internal_validation_does_not_claim_manifest_ready_without_kubeconform(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            profile = profile_for(external="private")
            bundle = ManifestRenderer().render(profile, destination)
            report = ValidationOrchestrator(run_external=False).validate(bundle, profile, destination)

        self.assertFalse(report.manifest_ready)
        self.assertEqual(report.findings, [])
        self.assertEqual([stage.stage for stage in report.stages], ["yaml-syntax", "internal", "kustomize", "kubeconform"])
        self.assertEqual(report.stages[-1].status, "not-run")

    def test_rendered_bundle_is_manifest_ready_with_project_kubeconform(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            profile = profile_for(external="private")
            bundle = ManifestRenderer().render(profile, destination)
            report = ValidationOrchestrator(run_external=True).validate(bundle, profile, destination)

        self.assertTrue(report.manifest_ready)
        self.assertEqual(report.findings, [])
        self.assertEqual(report.stages[-1].status, "pass")

    def test_invalid_manifest_fails_project_kubeconform(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            profile = profile_for(external="private")
            bundle = ManifestRenderer().render(profile, destination)
            deployment_path = destination / "base" / "api-deployment.yaml"
            deployment = yaml.safe_load(deployment_path.read_text(encoding="utf-8"))
            deployment["spec"]["template"]["spec"]["containers"][0]["badField"] = True
            deployment_path.write_text(yaml.safe_dump(deployment, sort_keys=False), encoding="utf-8")
            binary = project_kubeconform_binary(Path(__file__).resolve().parents[2])
            report = KubeconformValidator(binary=binary).validate([deployment_path])

        self.assertEqual(report.status, "fail")
        self.assertFalse(report.manifest_ready)
        self.assertEqual(report.findings[0].code, "kubeconform_failed")


if __name__ == "__main__":
    unittest.main()
