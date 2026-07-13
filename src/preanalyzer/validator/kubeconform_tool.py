from __future__ import annotations

import platform
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
