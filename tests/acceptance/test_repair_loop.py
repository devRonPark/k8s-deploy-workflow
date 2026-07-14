from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from k8s_agent.repair.controller import RepairController
from k8s_agent.render.renderer import ManifestRenderer
from k8s_agent.validation.orchestrator import ValidationOrchestrator
from tests.acceptance.test_manifest_renderer import profile_for


class RepairLoopAcceptanceTests(unittest.TestCase):
    def test_repair_loop_fixes_service_target_port_and_revalidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = profile_for(external="private")
            bundle = ManifestRenderer().render(profile, root)
            service_path = root / "base" / "api-service.yaml"
            service = yaml.safe_load(service_path.read_text(encoding="utf-8"))
            service["spec"]["ports"][0]["targetPort"] = 9000
            service_path.write_text(yaml.safe_dump(service, sort_keys=False), encoding="utf-8")
            report = ValidationOrchestrator(run_external=True).validate(bundle, profile, root)

            result = RepairController(destination=root).repair(bundle, profile, report)

        self.assertTrue(result.repaired)
        self.assertTrue(result.validation_result.manifest_ready)
        self.assertEqual(len(result.attempts), 1)


if __name__ == "__main__":
    unittest.main()
