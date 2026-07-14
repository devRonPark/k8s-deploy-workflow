from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from k8s_agent.validation.kubeconform import KubeconformValidator
from k8s_agent.validation.kustomize import KustomizeValidator


class ExternalAdapterTests(unittest.TestCase):
    def test_missing_kubeconform_is_normalized(self):
        report = KubeconformValidator(binary=None).validate([])

        self.assertEqual(report.status, "tool-missing")
        self.assertEqual(report.findings[0].code, "kubeconform_missing")
        self.assertFalse(report.manifest_ready)

    def test_missing_kustomize_is_not_run_status(self):
        report = KustomizeValidator(binary=None).validate([])

        self.assertEqual(report.status, "not-run")
        self.assertEqual(report.findings, [])

    def test_kubeconform_runs_external_binary_without_shell(self):
        completed = Mock(returncode=0, stdout="ok", stderr="")

        with patch("k8s_agent.validation.kubeconform.subprocess.run", return_value=completed) as run:
            report = KubeconformValidator(binary=Path("/tools/kubeconform")).validate([Path("deployment.yaml")])

        self.assertEqual(report.status, "pass")
        self.assertTrue(report.manifest_ready)
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/tools/kubeconform")
        self.assertIn("-schema-location", command)
        self.assertIn("-skip", command)
        self.assertEqual(run.call_args.kwargs["check"], False)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_kubeconform_failure_blocks_manifest_ready(self):
        completed = Mock(returncode=1, stdout="deployment badField is invalid", stderr="")

        with patch("k8s_agent.validation.kubeconform.subprocess.run", return_value=completed):
            report = KubeconformValidator(binary=Path("/tools/kubeconform")).validate([Path("deployment.yaml")])

        self.assertEqual(report.status, "fail")
        self.assertFalse(report.manifest_ready)
        self.assertEqual(report.findings[0].code, "kubeconform_failed")

    def test_kustomize_runs_each_kustomization_without_shell(self):
        completed = Mock(returncode=0, stdout="", stderr="")

        with patch("k8s_agent.validation.kustomize.subprocess.run", return_value=completed) as run:
            report = KustomizeValidator(binary=Path("/tools/kustomize")).validate(
                [Path("base/kustomization.yaml"), Path("base/deployment.yaml")]
            )

        self.assertEqual(report.status, "pass")
        self.assertEqual(run.call_args.args[0], ["/tools/kustomize", "build", "base"])
        self.assertEqual(run.call_args.kwargs["check"], False)
        self.assertNotIn("shell", run.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
