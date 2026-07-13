from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from k8s_agent.validation.internal import InternalManifestValidator


class ManifestPolicySecurityTests(unittest.TestCase):
    def test_internal_validator_blocks_privileged_hostpath_and_cluster_wide_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "danger.yaml"
            manifest.write_text(
                """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dangerous
spec:
  template:
    metadata:
      labels:
        app: dangerous
    spec:
      containers:
        - name: app
          image: example/app
          securityContext:
            privileged: true
      volumes:
        - name: host
          hostPath:
            path: /var/run/docker.sock
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: dangerous
rules: []
""".strip(),
                encoding="utf-8",
            )

            findings = InternalManifestValidator().validate_paths([manifest])

        codes = {finding.code for finding in findings}
        self.assertIn("privileged_container", codes)
        self.assertIn("host_path_volume", codes)
        self.assertIn("cluster_wide_resource", codes)
        self.assertTrue(all(finding.severity == "error" for finding in findings if finding.code in codes))


if __name__ == "__main__":
    unittest.main()
