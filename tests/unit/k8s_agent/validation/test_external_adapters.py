from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
