import unittest
from pathlib import Path

from preanalyzer.validator.kubeconform_tool import (
    KUBECONFORM_ARTIFACTS,
    KUBECONFORM_VERSION,
    KubeconformToolError,
    managed_kubeconform_path,
    normalize_kubeconform_platform,
)


class KubeconformPlatformTests(unittest.TestCase):
    def test_linux_amd64_aliases(self):
        self.assertEqual(normalize_kubeconform_platform("Linux", "x86_64"), "linux-amd64")
        self.assertEqual(normalize_kubeconform_platform("Linux", "amd64"), "linux-amd64")

    def test_linux_arm64_aliases(self):
        self.assertEqual(normalize_kubeconform_platform("Linux", "aarch64"), "linux-arm64")
        self.assertEqual(normalize_kubeconform_platform("Linux", "arm64"), "linux-arm64")

    def test_windows_amd64_aliases(self):
        self.assertEqual(normalize_kubeconform_platform("Windows", "AMD64"), "windows-amd64")
        self.assertEqual(normalize_kubeconform_platform("Windows", "x86_64"), "windows-amd64")
        self.assertEqual(normalize_kubeconform_platform("Windows", "amd64"), "windows-amd64")

    def test_unsupported_platform_reports_system_and_machine(self):
        with self.assertRaisesRegex(KubeconformToolError, "unsupported kubeconform platform: Darwin/arm64"):
            normalize_kubeconform_platform("Darwin", "arm64")

    def test_managed_paths_are_platform_specific(self):
        repo = Path("/repo")
        self.assertEqual(
            managed_kubeconform_path(repo, "linux-amd64"),
            repo / ".tools" / "kubeconform" / KUBECONFORM_VERSION / "linux-amd64" / "kubeconform",
        )
        self.assertEqual(
            managed_kubeconform_path(repo, "windows-amd64"),
            repo / ".tools" / "kubeconform" / KUBECONFORM_VERSION / "windows-amd64" / "kubeconform.exe",
        )

    def test_release_metadata_contains_only_supported_targets(self):
        self.assertEqual(set(KUBECONFORM_ARTIFACTS), {"linux-amd64", "linux-arm64", "windows-amd64"})
        self.assertEqual(
            KUBECONFORM_ARTIFACTS["linux-amd64"].sha256,
            "9bc2bffbf71f261128533edaf912153948b7ff238f9a531ae6d34466ec287883",
        )
        self.assertEqual(
            KUBECONFORM_ARTIFACTS["linux-arm64"].sha256,
            "1f53fc8e81258197a35e8603054162a5af1de8c5af13746c71ab680d9534ed87",
        )
        self.assertEqual(
            KUBECONFORM_ARTIFACTS["windows-amd64"].sha256,
            "e3f56102bcf4f50b034a567e2482a1c5330799983ddd655952310211aef73d93",
        )


if __name__ == "__main__":
    unittest.main()
