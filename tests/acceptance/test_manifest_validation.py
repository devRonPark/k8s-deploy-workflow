from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from k8s_agent.render.renderer import ManifestRenderer
from k8s_agent.validation.orchestrator import ValidationOrchestrator
from tests.acceptance.test_manifest_renderer import profile_for


class ManifestValidationAcceptanceTests(unittest.TestCase):
    def test_rendered_bundle_is_manifest_ready_for_internal_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            profile = profile_for(external="private")
            bundle = ManifestRenderer().render(profile, destination)
            report = ValidationOrchestrator(run_external=False).validate(bundle, profile, destination)

        self.assertTrue(report.manifest_ready)
        self.assertEqual(report.findings, [])
        self.assertEqual([stage.stage for stage in report.stages], ["yaml-syntax", "internal", "kustomize", "kubeconform"])
        self.assertEqual(report.stages[-1].status, "not-run")


if __name__ == "__main__":
    unittest.main()
