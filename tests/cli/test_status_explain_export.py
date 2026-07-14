from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.cli.test_prepare_arguments import run_agent
from tests.unit.k8s_agent.reporting.test_final_report import _ready_run


class StatusExplainExportCliTests(unittest.TestCase):
    def test_status_prints_readiness_limitations_and_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            _ready_run(Path(tmp))

            result = run_agent("status", "run-ready", extra_env={"K8S_AGENT_HOME": tmp})

            text = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, text)
            self.assertIn("run_id=run-ready", text)
            self.assertIn("state=READY", text)
            self.assertIn("summary=manifest-ready", text)
            self.assertIn("build-verified not executed", text)
            self.assertIn("cluster-verified not executed", text)
            self.assertIn("next=export manifests or review generated bundle", text)
            self.assertNotIn("production-ready", text)

    def test_explain_prints_decision_trace_without_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            _ready_run(Path(tmp), include_secret=True)

            result = run_agent("explain", "run-ready", "D-secret", extra_env={"K8S_AGENT_HOME": tmp})

            text = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, text)
            self.assertIn("subject=D-secret", text)
            self.assertIn("decision=D-secret", text)
            self.assertIn("profile_field=/components/api/secret_ref", text)
            self.assertIn("resource=Deployment/api-app", text)
            self.assertIn("Evidence -> Decision -> Profile field -> Resource", text)
            self.assertNotIn("changethis", text)

    def test_export_requires_explicit_overwrite_and_copies_generated_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            _ready_run(Path(tmp), include_secret=True)
            output = Path(tmp) / "exported"

            first = run_agent("export", "run-ready", "--output", str(output), extra_env={"K8S_AGENT_HOME": tmp})
            second = run_agent("export", "run-ready", "--output", str(output), extra_env={"K8S_AGENT_HOME": tmp})
            third = run_agent("export", "run-ready", "--output", str(output), "--overwrite", extra_env={"K8S_AGENT_HOME": tmp})

            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(second.returncode, 2, second.stdout + second.stderr)
            self.assertIn("EXPORT-101", second.stdout + second.stderr)
            self.assertEqual(third.returncode, 0, third.stdout + third.stderr)
            self.assertTrue((output / "base" / "api-deployment.yaml").is_file())
            self.assertFalse((output / "source.yaml").exists())
            exported_text = "\n".join(path.read_text(encoding="utf-8") for path in output.rglob("*.yaml"))
            self.assertNotIn("changethis", exported_text)


if __name__ == "__main__":
    unittest.main()
