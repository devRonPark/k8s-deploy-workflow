from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


KUBECONFORM_VERSION = "v0.8.0"
KUBECONFORM_BASE_URL = "https://github.com/yannh/kubeconform/releases/download"


class KubeconformToolError(RuntimeError):
    """Raised when managed kubeconform setup cannot continue."""


@dataclass(frozen=True)
class KubeconformArtifact:
    target: str
    archive_name: str
    sha256: str
    executable_name: str

    @property
    def url(self) -> str:
        return f"{KUBECONFORM_BASE_URL}/{KUBECONFORM_VERSION}/{self.archive_name}"


KUBECONFORM_ARTIFACTS: dict[str, KubeconformArtifact] = {
    "linux-amd64": KubeconformArtifact(
        target="linux-amd64",
        archive_name="kubeconform-linux-amd64.tar.gz",
        sha256="9bc2bffbf71f261128533edaf912153948b7ff238f9a531ae6d34466ec287883",
        executable_name="kubeconform",
    ),
    "linux-arm64": KubeconformArtifact(
        target="linux-arm64",
        archive_name="kubeconform-linux-arm64.tar.gz",
        sha256="1f53fc8e81258197a35e8603054162a5af1de8c5af13746c71ab680d9534ed87",
        executable_name="kubeconform",
    ),
    "windows-amd64": KubeconformArtifact(
        target="windows-amd64",
        archive_name="kubeconform-windows-amd64.zip",
        sha256="e3f56102bcf4f50b034a567e2482a1c5330799983ddd655952310211aef73d93",
        executable_name="kubeconform.exe",
    ),
}


def normalize_kubeconform_platform(system: str, machine: str) -> str:
    normalized_system = system.strip().lower()
    normalized_machine = machine.strip().lower()
    if normalized_system == "linux" and normalized_machine in {"x86_64", "amd64"}:
        return "linux-amd64"
    if normalized_system == "linux" and normalized_machine in {"aarch64", "arm64"}:
        return "linux-arm64"
    if normalized_system == "windows" and normalized_machine in {"amd64", "x86_64"}:
        return "windows-amd64"
    raise KubeconformToolError(f"unsupported kubeconform platform: {system}/{machine}")


def current_platform_target(system: str | None = None, machine: str | None = None) -> str:
    return normalize_kubeconform_platform(system or platform.system(), machine or platform.machine())


def managed_kubeconform_path(repo_root: Path, target: str) -> Path:
    artifact = KUBECONFORM_ARTIFACTS[target]
    return repo_root / ".tools" / "kubeconform" / KUBECONFORM_VERSION / target / artifact.executable_name


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, target: Path, opener: Callable = urllib.request.urlopen) -> None:
    request = urllib.request.Request(url, method="GET")
    try:
        with opener(request, timeout=60) as response:
            target.write_bytes(response.read())
    except OSError as exc:
        raise KubeconformToolError(f"download failed: {url}") from exc


def _extract_executable(archive_path: Path, artifact: KubeconformArtifact, install_path: Path) -> None:
    tmpdir = Path(tempfile.mkdtemp(prefix="kubeconform-extract-"))
    try:
        candidate = tmpdir / artifact.executable_name
        if artifact.archive_name.endswith(".tar.gz"):
            with tarfile.open(archive_path, mode="r:gz") as archive:
                member = next(
                    (item for item in archive.getmembers() if Path(item.name).name == artifact.executable_name),
                    None,
                )
                if member is None:
                    raise KubeconformToolError(f"archive missing executable: {artifact.executable_name}")
                source = archive.extractfile(member)
                if source is None:
                    raise KubeconformToolError(f"archive missing executable data: {artifact.executable_name}")
                candidate.write_bytes(source.read())
        elif artifact.archive_name.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as archive:
                member_name = next(
                    (name for name in archive.namelist() if Path(name).name == artifact.executable_name),
                    None,
                )
                if member_name is None:
                    raise KubeconformToolError(f"archive missing executable: {artifact.executable_name}")
                candidate.write_bytes(archive.read(member_name))
        else:
            raise KubeconformToolError(f"unsupported archive format: {artifact.archive_name}")

        install_path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            candidate.chmod(0o755)
        os.replace(candidate, install_path)
        if os.name != "nt":
            install_path.chmod(0o755)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def install_kubeconform(
    repo_root: Path,
    target: str | None = None,
    force: bool = False,
    opener: Callable = urllib.request.urlopen,
) -> Path:
    resolved_target = target or current_platform_target()
    artifact = KUBECONFORM_ARTIFACTS[resolved_target]
    install_path = managed_kubeconform_path(repo_root, resolved_target)
    if install_path.exists() and not force:
        return install_path

    download_dir = repo_root / ".tools" / ".downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    archive_path = download_dir / artifact.archive_name
    _download(artifact.url, archive_path, opener=opener)
    actual = sha256_file(archive_path)
    if actual != artifact.sha256:
        archive_path.unlink(missing_ok=True)
        raise KubeconformToolError(
            f"checksum mismatch for {artifact.archive_name}: expected {artifact.sha256}, got {actual}"
        )
    _extract_executable(archive_path, artifact, install_path)
    return install_path


def preflight_kubeconform(repo_root: Path, target: str | None = None, force: bool = False) -> Path:
    path = install_kubeconform(repo_root, target=target, force=force)
    proc = subprocess.run([str(path), "-v"], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stdout or proc.stderr).strip()
        raise KubeconformToolError(f"kubeconform preflight failed: {detail[:200]}")
    return path


def _is_executable(path: Path) -> bool:
    return path.is_file() and (os.name == "nt" or os.access(path, os.X_OK))


def resolve_kubeconform(repo_root: Path, explicit_path: Path | None = None) -> str | None:
    if explicit_path is not None and _is_executable(explicit_path):
        return str(explicit_path)
    try:
        target = current_platform_target()
    except KubeconformToolError:
        target = None
    if target is not None:
        managed = managed_kubeconform_path(repo_root, target)
        if _is_executable(managed):
            return str(managed)
    found = shutil.which("kubeconform")
    return found
