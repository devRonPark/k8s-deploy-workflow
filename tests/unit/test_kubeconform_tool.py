import io
import os
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from preanalyzer.validator.kubeconform_tool import (
    KUBECONFORM_ARTIFACTS,
    KUBECONFORM_VERSION,
    KubeconformArtifact,
    KubeconformToolError,
    install_kubeconform,
    managed_kubeconform_path,
    normalize_kubeconform_platform,
    preflight_kubeconform,
    sha256_file,
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


def _tar_with_kubeconform(text: bytes = b"#!/bin/sh\nexit 0\n") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as archive:
        info = tarfile.TarInfo("kubeconform")
        info.mode = 0o755
        info.size = len(text)
        archive.addfile(info, io.BytesIO(text))
    return buf.getvalue()


def _zip_with_kubeconform(text: bytes = b"windows exe") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as archive:
        archive.writestr("kubeconform.exe", text)
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, data: bytes):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._data


class KubeconformInstallTests(unittest.TestCase):
    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.bin"
            path.write_bytes(b"abc")
            self.assertEqual(
                sha256_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )

    def test_checksum_mismatch_does_not_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            with self.assertRaisesRegex(KubeconformToolError, "checksum mismatch"):
                install_kubeconform(
                    repo,
                    target="linux-amd64",
                    opener=lambda request, timeout: _FakeResponse(_tar_with_kubeconform()),
                )
            self.assertFalse(
                (repo / ".tools" / "kubeconform" / "v0.8.0" / "linux-amd64" / "kubeconform").exists()
            )

    def test_tar_archive_installs_expected_executable_when_checksum_matches(self):
        data = _tar_with_kubeconform()
        artifact = KubeconformArtifact(
            target="linux-amd64",
            archive_name="kubeconform-linux-amd64.tar.gz",
            sha256=__import__("hashlib").sha256(data).hexdigest(),
            executable_name="kubeconform",
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            with patch.dict("preanalyzer.validator.kubeconform_tool.KUBECONFORM_ARTIFACTS", {"linux-amd64": artifact}):
                path = install_kubeconform(
                    repo,
                    target="linux-amd64",
                    opener=lambda request, timeout: _FakeResponse(data),
                )
            self.assertEqual(path.name, "kubeconform")
            self.assertTrue(path.exists())
            self.assertTrue(os.access(path, os.X_OK))

    def test_zip_archive_installs_expected_windows_executable(self):
        data = _zip_with_kubeconform()
        artifact = KubeconformArtifact(
            target="windows-amd64",
            archive_name="kubeconform-windows-amd64.zip",
            sha256=__import__("hashlib").sha256(data).hexdigest(),
            executable_name="kubeconform.exe",
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            with patch.dict(
                "preanalyzer.validator.kubeconform_tool.KUBECONFORM_ARTIFACTS",
                {"windows-amd64": artifact},
            ):
                path = install_kubeconform(
                    repo,
                    target="windows-amd64",
                    opener=lambda request, timeout: _FakeResponse(data),
                )
            self.assertEqual(path.name, "kubeconform.exe")
            self.assertTrue(path.exists())

    def test_preflight_runs_version_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            exe = repo / ".tools" / "kubeconform" / "v0.8.0" / "linux-amd64" / "kubeconform"
            exe.parent.mkdir(parents=True)
            exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            exe.chmod(0o755)
            with patch("preanalyzer.validator.kubeconform_tool.current_platform_target", return_value="linux-amd64"):
                with patch("preanalyzer.validator.kubeconform_tool.subprocess.run") as run:
                    run.return_value.returncode = 0
                    path = preflight_kubeconform(repo)
            self.assertEqual(path, exe)
            self.assertEqual(run.call_args.args[0], [str(exe), "-v"])


if __name__ == "__main__":
    unittest.main()
