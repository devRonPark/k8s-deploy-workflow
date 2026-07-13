# Kubeconform Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `kubeconform` a required, reproducible validation tool for agent-run Kubernetes manifest checks.

**Architecture:** Add a focused tool metadata/helper module that owns platform mapping, pinned release metadata, managed paths, and resolver behavior. Add a stdlib-only setup script that installs and preflights the pinned binary under `.tools/`. Update `ValidationPipeline` to prefer explicit and managed binaries while preserving skipped reporting as a last-resort artifact state.

**Tech Stack:** Python 3.11+, `unittest`, standard library only for setup script downloads/extraction/checksum, existing `ValidationPipeline`, pinned kubeconform `v0.8.0`.

## Global Constraints

- Supported platforms: Linux `x86_64` / `amd64`, Linux `aarch64` / `arm64`, Windows `x86_64` / `amd64`.
- Kubeconform version: `v0.8.0`.
- Release metadata source: `https://github.com/yannh/kubeconform/releases/tag/v0.8.0`.
- Supported artifacts and SHA256:
  - `kubeconform-linux-amd64.tar.gz`: `9bc2bffbf71f261128533edaf912153948b7ff238f9a531ae6d34466ec287883`
  - `kubeconform-linux-arm64.tar.gz`: `1f53fc8e81258197a35e8603054162a5af1de8c5af13746c71ab680d9534ed87`
  - `kubeconform-windows-amd64.zip`: `e3f56102bcf4f50b034a567e2482a1c5330799983ddd655952310211aef73d93`
- Managed install paths:
  - `.tools/kubeconform/v0.8.0/linux-amd64/kubeconform`
  - `.tools/kubeconform/v0.8.0/linux-arm64/kubeconform`
  - `.tools/kubeconform/v0.8.0/windows-amd64/kubeconform.exe`
- `.tools/` is generated local state and must be ignored by git.
- `ValidationPipeline.run(...)` must never download tools during analysis.
- `kubeconform: skipped (tool_not_found)` remains a valid artifact state, but agent-run sample validation must not report completion when kubeconform is skipped.
- Use `unittest`; do not introduce new dependencies.

---

## File Structure

- Create `src/preanalyzer/validator/kubeconform_tool.py`
  - Owns pinned metadata, platform mapping, managed path construction, executable checks, resolver, and preflight helpers.
- Modify `src/preanalyzer/validator/pipeline.py`
  - Accepts optional `kubeconform_path`; calls resolver; runs resolved binary.
- Create `scripts/ensure_kubeconform.py`
  - CLI wrapper around helper functions for install and preflight.
- Modify `scripts/CLAUDE.md`
  - Documents the new setup script.
- Modify `.gitignore`
  - Adds `.tools/`.
- Modify `AGENTS.md`
  - Adds required kubeconform preflight to project completion/setup guidance.
- Modify `README.md`
  - Adds setup command before sample pipeline validation.
- Modify `tests/unit/test_validator.py`
  - Adds resolver and pipeline tests.
- Create `tests/unit/test_kubeconform_tool.py`
  - Adds platform, path, checksum, archive, and preflight tests.

---

### Task 1: Kubeconform Metadata And Platform Resolver

**목표:** 지원 플랫폼, 고정 릴리스 메타데이터, 관리형 설치 경로를 결정론적으로 계산하는 기반을 완성한다.

**변경 범위:** `kubeconform_tool.py`의 상수/데이터 모델/플랫폼 매핑/경로 계산, 해당 단위 테스트, `.tools/` git ignore만 포함한다.

**완료 조건:** Linux amd64, Linux arm64, Windows amd64 매핑과 관리형 경로 계산이 테스트로 검증되고, 미지원 플랫폼은 명확한 오류를 낸다.

**실행할 테스트 범위:** 개발 중 및 태스크 완료 시 `tests.unit.test_kubeconform_tool`만 실행한다.

**전체 테스트 필요 여부:** 필요 없음. 아직 validator 실행 경로를 바꾸지 않는 순수 helper 추가이므로 전체 테스트는 기능 묶음 완료 후 실행한다.

**Files:**
- Create: `src/preanalyzer/validator/kubeconform_tool.py`
- Create: `tests/unit/test_kubeconform_tool.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces:
  - `KUBECONFORM_VERSION: str`
  - `KUBECONFORM_ARTIFACTS: dict[str, KubeconformArtifact]`
  - `KubeconformToolError(RuntimeError)`
  - `KubeconformArtifact`
  - `normalize_kubeconform_platform(system: str, machine: str) -> str`
  - `managed_kubeconform_path(repo_root: Path, target: str) -> Path`
  - `current_platform_target(system: str | None = None, machine: str | None = None) -> str`
- Consumes: standard library `platform`, `dataclasses`, `pathlib`.

- [ ] **Step 1: Write failing tests for platform mapping and managed paths**

Add to `tests/unit/test_kubeconform_tool.py`:

```python
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
        self.assertEqual(KUBECONFORM_ARTIFACTS["linux-amd64"].sha256, "9bc2bffbf71f261128533edaf912153948b7ff238f9a531ae6d34466ec287883")
        self.assertEqual(KUBECONFORM_ARTIFACTS["linux-arm64"].sha256, "1f53fc8e81258197a35e8603054162a5af1de8c5af13746c71ab680d9534ed87")
        self.assertEqual(KUBECONFORM_ARTIFACTS["windows-amd64"].sha256, "e3f56102bcf4f50b034a567e2482a1c5330799983ddd655952310211aef73d93")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_kubeconform_tool -v
```

Expected: fail with `ModuleNotFoundError: No module named 'preanalyzer.validator.kubeconform_tool'`.

- [ ] **Step 3: Add metadata and platform implementation**

Create `src/preanalyzer/validator/kubeconform_tool.py`:

```python
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
```

Modify `.gitignore` by adding:

```gitignore
.tools/
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_kubeconform_tool -v
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add .gitignore src/preanalyzer/validator/kubeconform_tool.py tests/unit/test_kubeconform_tool.py
git commit -m "feat: add kubeconform tool metadata"
```

---

### Task 2: Setup Script Download, Checksum, Extraction, And Preflight

**목표:** 지원 플랫폼의 pinned kubeconform 바이너리를 `.tools/`에 설치하고 실행 가능 여부를 검증하는 필수 preflight를 완성한다.

**변경 범위:** 다운로드, SHA256 검증, tar/zip 추출, preflight 실행, CLI wrapper, scripts 문서, 관련 단위 테스트를 같은 태스크에 포함한다.

**완료 조건:** checksum mismatch는 설치하지 않고 실패하며, tar/zip fixture에서 실행 파일을 추출하고, `--check` 경로가 version command를 실행한다.

**실행할 테스트 범위:** 개발 중 및 태스크 완료 시 `tests.unit.test_kubeconform_tool`만 실행한다.

**전체 테스트 필요 여부:** 필요 없음. validator 파이프라인은 아직 연결하지 않았으므로 helper/script 관련 테스트만으로 충분하다.

**Files:**
- Modify: `src/preanalyzer/validator/kubeconform_tool.py`
- Create: `scripts/ensure_kubeconform.py`
- Modify: `tests/unit/test_kubeconform_tool.py`
- Modify: `scripts/CLAUDE.md`

**Interfaces:**
- Consumes:
  - `KUBECONFORM_ARTIFACTS`
  - `current_platform_target(system: str | None = None, machine: str | None = None) -> str`
  - `managed_kubeconform_path(repo_root: Path, target: str) -> Path`
- Produces:
  - `sha256_file(path: Path) -> str`
  - `install_kubeconform(repo_root: Path, target: str | None = None, force: bool = False, opener=urlopen) -> Path`
  - `preflight_kubeconform(repo_root: Path, target: str | None = None, force: bool = False) -> Path`
  - CLI: `python3 scripts/ensure_kubeconform.py --check`

- [ ] **Step 1: Write failing tests for checksum mismatch, archive extraction, and preflight**

Extend `tests/unit/test_kubeconform_tool.py`:

```python
import io
import os
import tarfile
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from preanalyzer.validator.kubeconform_tool import (
    KubeconformToolError,
    install_kubeconform,
    preflight_kubeconform,
    sha256_file,
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
            self.assertEqual(sha256_file(path), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_checksum_mismatch_does_not_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            with self.assertRaisesRegex(KubeconformToolError, "checksum mismatch"):
                install_kubeconform(
                    repo,
                    target="linux-amd64",
                    opener=lambda request, timeout: _FakeResponse(_tar_with_kubeconform()),
                )
            self.assertFalse((repo / ".tools" / "kubeconform" / "v0.8.0" / "linux-amd64" / "kubeconform").exists())

    def test_tar_archive_installs_expected_executable_when_checksum_matches(self):
        data = _tar_with_kubeconform()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            with patch("preanalyzer.validator.kubeconform_tool.KUBECONFORM_ARTIFACTS") as artifacts:
                from preanalyzer.validator.kubeconform_tool import KubeconformArtifact

                artifacts.__getitem__.side_effect = {
                    "linux-amd64": KubeconformArtifact(
                        target="linux-amd64",
                        archive_name="kubeconform-linux-amd64.tar.gz",
                        sha256=__import__("hashlib").sha256(data).hexdigest(),
                        executable_name="kubeconform",
                    )
                }.__getitem__
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
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            with patch("preanalyzer.validator.kubeconform_tool.KUBECONFORM_ARTIFACTS") as artifacts:
                from preanalyzer.validator.kubeconform_tool import KubeconformArtifact

                artifacts.__getitem__.side_effect = {
                    "windows-amd64": KubeconformArtifact(
                        target="windows-amd64",
                        archive_name="kubeconform-windows-amd64.zip",
                        sha256=__import__("hashlib").sha256(data).hexdigest(),
                        executable_name="kubeconform.exe",
                    )
                }.__getitem__
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_kubeconform_tool -v
```

Expected: fail with import errors for `install_kubeconform`, `preflight_kubeconform`, or `sha256_file`.

- [ ] **Step 3: Implement installer and preflight helper**

Append to `src/preanalyzer/validator/kubeconform_tool.py`:

```python
import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable


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
                member = next((item for item in archive.getmembers() if Path(item.name).name == artifact.executable_name), None)
                if member is None:
                    raise KubeconformToolError(f"archive missing executable: {artifact.executable_name}")
                source = archive.extractfile(member)
                if source is None:
                    raise KubeconformToolError(f"archive missing executable data: {artifact.executable_name}")
                candidate.write_bytes(source.read())
        elif artifact.archive_name.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as archive:
                member_name = next((name for name in archive.namelist() if Path(name).name == artifact.executable_name), None)
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
        raise KubeconformToolError(f"checksum mismatch for {artifact.archive_name}: expected {artifact.sha256}, got {actual}")
    _extract_executable(archive_path, artifact, install_path)
    return install_path


def preflight_kubeconform(repo_root: Path, target: str | None = None, force: bool = False) -> Path:
    path = install_kubeconform(repo_root, target=target, force=force)
    proc = subprocess.run([str(path), "-v"], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stdout or proc.stderr).strip()
        raise KubeconformToolError(f"kubeconform preflight failed: {detail[:200]}")
    return path
```

- [ ] **Step 4: Add CLI wrapper**

Create `scripts/ensure_kubeconform.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from preanalyzer.validator.kubeconform_tool import KubeconformToolError, install_kubeconform, preflight_kubeconform


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install and verify the pinned kubeconform binary.")
    parser.add_argument("--check", action="store_true", help="install if needed and verify the executable")
    parser.add_argument("--force", action="store_true", help="re-download and replace an existing managed binary")
    args = parser.parse_args(argv)

    try:
        path = preflight_kubeconform(REPO_ROOT, force=args.force) if args.check else install_kubeconform(REPO_ROOT, force=args.force)
    except KubeconformToolError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Update scripts documentation**

Modify `scripts/CLAUDE.md` Purpose list to include:

```text
scripts/ensure_kubeconform.py      # install/check required kubeconform binary
```

Add to Common Patterns:

```bash
python3 scripts/ensure_kubeconform.py --check
```

- [ ] **Step 6: Run targeted tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_kubeconform_tool -v
```

Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add src/preanalyzer/validator/kubeconform_tool.py scripts/ensure_kubeconform.py scripts/CLAUDE.md tests/unit/test_kubeconform_tool.py
git commit -m "feat: install managed kubeconform"
```

---

### Task 3: ValidationPipeline Uses Managed Kubeconform

**목표:** 기존 검증 파이프라인이 명시 경로, 관리형 `.tools` 바이너리, PATH 순서로 kubeconform을 찾아 실제 스키마 검증에 사용하도록 완성한다.

**변경 범위:** resolver, `ValidationPipeline` 생성자/실행 경로, validator 단위 테스트만 포함한다. 설치 스크립트나 문서 정책은 변경하지 않는다.

**완료 조건:** 명시 경로 우선, 관리형 경로 우선, PATH fallback, missing-tool skip, subprocess 인자가 모두 테스트로 검증된다.

**실행할 테스트 범위:** 개발 중에는 `tests.unit.test_validator`의 새/관련 테스트만 실행하고, 태스크 완료 시 `tests.unit.test_validator tests.unit.test_kubeconform_tool`을 실행한다.

**전체 테스트 필요 여부:** 이 태스크 단독 완료 시에는 필요 없음. 다만 공유 validator 경로를 바꾸므로 기능 묶음 최종 검증에서는 전체 테스트가 필요하다.

**Files:**
- Modify: `src/preanalyzer/validator/kubeconform_tool.py`
- Modify: `src/preanalyzer/validator/pipeline.py`
- Modify: `tests/unit/test_validator.py`

**Interfaces:**
- Consumes:
  - `managed_kubeconform_path(repo_root: Path, target: str) -> Path`
  - `current_platform_target() -> str`
- Produces:
  - `resolve_kubeconform(repo_root: Path, explicit_path: Path | None = None) -> str | None`
  - `ValidationPipeline(k8s_version: str = "1.29", kubeconform_path: Path | None = None, repo_root: Path | None = None)`

- [ ] **Step 1: Write failing tests for resolver precedence and subprocess command**

Extend `tests/unit/test_validator.py`:

```python
from unittest.mock import Mock

from preanalyzer.validator.kubeconform_tool import resolve_kubeconform


class KubeconformResolverTests(unittest.TestCase):
    def test_explicit_path_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "kc"
            exe.write_text("#!/bin/sh\n", encoding="utf-8")
            exe.chmod(0o755)
            self.assertEqual(resolve_kubeconform(Path(tmp), explicit_path=exe), str(exe))

    def test_managed_path_wins_over_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            managed = repo / ".tools" / "kubeconform" / "v0.8.0" / "linux-amd64" / "kubeconform"
            managed.parent.mkdir(parents=True)
            managed.write_text("#!/bin/sh\n", encoding="utf-8")
            managed.chmod(0o755)
            with patch("preanalyzer.validator.kubeconform_tool.current_platform_target", return_value="linux-amd64"):
                with patch("preanalyzer.validator.kubeconform_tool.shutil.which", return_value="/usr/bin/kubeconform"):
                    self.assertEqual(resolve_kubeconform(repo), str(managed))

    def test_missing_managed_and_path_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("preanalyzer.validator.kubeconform_tool.current_platform_target", return_value="linux-amd64"):
                with patch("preanalyzer.validator.kubeconform_tool.shutil.which", return_value=None):
                    self.assertIsNone(resolve_kubeconform(Path(tmp)))


class ValidatorKubeconformCommandTests(unittest.TestCase):
    def test_pipeline_uses_explicit_kubeconform_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write(directory, "ok.yaml", "apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: x\n")
            exe = directory / "kc"
            exe.write_text("#!/bin/sh\n", encoding="utf-8")
            exe.chmod(0o755)
            completed = Mock(returncode=0, stdout="summary ok", stderr="")
            with patch("preanalyzer.validator.pipeline.subprocess.run", return_value=completed) as run:
                report = ValidationPipeline(k8s_version="1.30", kubeconform_path=exe, repo_root=directory).run(directory)
        self.assertEqual(report.stages[1].stage, "kubeconform")
        self.assertEqual(report.stages[1].status, "pass")
        self.assertEqual(
            run.call_args_list[0].args[0],
            [str(exe), "-strict", "-summary", "-kubernetes-version", "1.30", str(directory)],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_validator -v
```

Expected: fail because `resolve_kubeconform` is missing and `ValidationPipeline.__init__` does not accept `kubeconform_path`.

- [ ] **Step 3: Implement resolver**

Append to `src/preanalyzer/validator/kubeconform_tool.py`:

```python
import shutil


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
```

- [ ] **Step 4: Update `ValidationPipeline` constructor and `_kubeconform`**

Modify `src/preanalyzer/validator/pipeline.py`:

```python
from preanalyzer.validator.kubeconform_tool import resolve_kubeconform
```

Replace constructor:

```python
class ValidationPipeline:
    def __init__(
        self,
        k8s_version: str = "1.29",
        kubeconform_path: Path | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self._k8s_version = k8s_version
        self._kubeconform_path = kubeconform_path
        self._repo_root = repo_root or Path.cwd()
```

Replace `_kubeconform` tool lookup and command:

```python
    def _kubeconform(self, directory: Path, stages: list[StageResult]) -> str:
        kubeconform = resolve_kubeconform(self._repo_root, self._kubeconform_path)
        if kubeconform is None:
            stages.append(StageResult(stage="kubeconform", status="skipped", detail="tool_not_found"))
            return "skipped"

        proc = subprocess.run(
            [
                kubeconform,
                "-strict",
                "-summary",
                "-kubernetes-version",
                self._k8s_version,
                str(directory),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        status = "pass" if proc.returncode == 0 else "fail"
        stages.append(
            StageResult(
                stage="kubeconform",
                status=status,
                detail=(proc.stdout or proc.stderr).strip()[:500],
            )
        )
        return status
```

- [ ] **Step 5: Update missing-tool test patch path**

In `tests/unit/test_validator.py`, replace:

```python
with patch("preanalyzer.validator.pipeline.shutil.which", return_value=None):
```

with:

```python
with patch("preanalyzer.validator.kubeconform_tool.current_platform_target", return_value="linux-amd64"):
    with patch("preanalyzer.validator.kubeconform_tool.shutil.which", return_value=None):
        report = ValidationPipeline(repo_root=directory).run(directory)
```

- [ ] **Step 6: Run targeted tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_validator tests.unit.test_kubeconform_tool -v
```

Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add src/preanalyzer/validator/kubeconform_tool.py src/preanalyzer/validator/pipeline.py tests/unit/test_validator.py tests/unit/test_kubeconform_tool.py
git commit -m "feat: resolve managed kubeconform in validator"
```

---

### Task 4: Required Preflight Documentation And Sample Validation Gate

**목표:** 에이전트 실행 규칙과 사용자 문서에 kubeconform preflight 필수 정책을 반영하고, 샘플 레포 5개가 더 이상 kubeconform skip 상태로 완료 보고되지 않게 검증한다.

**변경 범위:** `AGENTS.md`, `README.md`, 기존 샘플 보고서 보정, 새 kubeconform-required 샘플 검증 보고서 생성만 포함한다. production/test code는 변경하지 않는다.

**완료 조건:** 문서가 preflight 필수 규칙을 명시하고, 샘플 검증 명령이 `kubeconform: skipped`를 만나면 실패하며, 새 보고서에 5개 레포별 pass/fail 결과가 기록된다.

**실행할 테스트 범위:** 코드 테스트 대신 `python3 scripts/ensure_kubeconform.py --check`, 샘플 레포 5개 검증 명령, `git diff --check`, `python3 scripts/validate_context_paths.py .`를 실행한다.

**전체 테스트 필요 여부:** 필요 없음. 문서와 보고서 작업이며 production/test code를 바꾸지 않는다. 전체 테스트는 최종 기능 묶음 검증에서 한 번 실행한다.

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/reports/2026-07-13-sample-repo-agent-pipeline-test.md`
- Create: `docs/reports/2026-07-13-sample-repo-agent-pipeline-kubeconform.md`

**Interfaces:**
- Consumes:
  - `python3 scripts/ensure_kubeconform.py --check`
  - existing `run_analysis(...)`
  - `13-validation-report.yaml`
- Produces:
  - documented rule: agent-run sample validation is incomplete if kubeconform is skipped.

- [ ] **Step 1: Update `AGENTS.md` completion/setup rule**

Add this under the existing `Local LLM Endpoint` section or before `Completion`:

```markdown
## Required Tooling

Kubernetes manifest validation work requires project-managed `kubeconform`.

Before agent-run sample repo validation or completion claims involving generated manifests:

```bash
python3 scripts/ensure_kubeconform.py --check
```

If `13-validation-report.yaml` records `kubeconform: skipped`, the sample validation run is incomplete. Do not report Kubernetes schema validation as complete until kubeconform produces `pass` or `fail`.
```

- [ ] **Step 2: Update `README.md` setup instructions**

Add to development setup before test execution:

```markdown
## Required manifest validation tool

Install/check the project-managed kubeconform binary before running manifest validation:

```bash
python3 scripts/ensure_kubeconform.py --check
```

The binary is installed under `.tools/` and is not committed. Supported platforms are Linux amd64, Linux arm64, and Windows amd64.
```

- [ ] **Step 3: Update the existing sample report language**

In `docs/reports/2026-07-13-sample-repo-agent-pipeline-test.md`, replace statements that present skipped kubeconform as a normal limitation with language that says the run predates required preflight and must be rerun after `scripts/ensure_kubeconform.py --check`.

Use this wording:

```markdown
Note: this report was produced before kubeconform preflight became required. Because `kubeconform` was skipped, it is evidence of YAML generation and syntax parsing only, not a completed Kubernetes schema validation run.
```

- [ ] **Step 4: Run required preflight**

Run:

```bash
python3 scripts/ensure_kubeconform.py --check
```

Expected: prints a path under `.tools/kubeconform/v0.8.0/<platform>/...` and exits 0.

If network access is blocked by the sandbox, rerun the same command with escalated network approval.

- [ ] **Step 5: Re-run the 5 sample repos and fail on skipped kubeconform**

Run this command:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 - <<'PY'
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import tempfile

import yaml

from preanalyzer.pipeline import run_analysis

repos = [
    "fastapi-fullstack-like",
    "fastapi-shell-entrypoint",
    "jpetstore-like",
    "node-express-like",
    "port-conflict-node",
]
profile = Path("tests/fixtures/profiles/dev-profile.yaml")
root = Path(tempfile.mkdtemp(prefix="kubeconform-sample-repos-", dir="/tmp"))
fixed = datetime(2026, 7, 13, 0, 0, 0, tzinfo=timezone.utc)
summary = {"run_root": str(root), "repos": []}

for repo in repos:
    out = root / repo
    report = run_analysis(
        repo=Path("tests/fixtures/repos") / repo,
        output_dir=out,
        url=f"fixture://{repo}",
        ref="kubeconform-required",
        clock=lambda fixed=fixed: fixed,
        semantic_mode="disabled",
        profile_path=profile,
    )
    validation = yaml.safe_load((out / "13-validation-report.yaml").read_text(encoding="utf-8"))["validation_report"]
    stages = {stage["stage"]: stage for stage in validation["stages"]}
    kubeconform_status = stages["kubeconform"]["status"]
    if kubeconform_status == "skipped":
        raise SystemExit(f"{repo}: kubeconform skipped")
    manifests = sorted(path.relative_to(out / "12-generated-manifests").as_posix() for path in (out / "12-generated-manifests").rglob("*.yaml"))
    summary["repos"].append(
        {
            "repo": repo,
            "achieved_level": report.achieved_level,
            "manifest_count": len(manifests),
            "kubeconform": kubeconform_status,
            "kubeconform_detail": (stages["kubeconform"].get("detail") or "").replace("\n", " ")[:120],
        }
    )

report = Path("docs/reports/2026-07-13-sample-repo-agent-pipeline-kubeconform.md")
rows = [
    "| Sample repo | Generated YAML | Kubeconform | Achieved level | Notes |",
    "|---|---:|---|---:|---|",
]
for item in summary["repos"]:
    rows.append(
        f"| `{item['repo']}` | {item['manifest_count']} | {item['kubeconform']} | "
        f"{item['achieved_level']} | {item['kubeconform_detail']} |"
    )
report.write_text(
    "\n".join(
        [
            "# 2026-07-13 Kubeconform-Required Sample Repo Validation",
            "",
            "## Summary",
            "",
            "This report was produced after `kubeconform` became a required agent preflight.",
            "",
            "- Preflight command: `python3 scripts/ensure_kubeconform.py --check`",
            "- Sample command: current branch `run_analysis(...)` over 5 fixture repositories",
            "- Kubeconform skipped status: none",
            f"- Output root: `{root}`",
            "",
            "## Results",
            "",
            *rows,
            "",
            "## Interpretation",
            "",
            "`pass` means Kubernetes schema validation ran and accepted the generated YAML.",
            "`fail` means Kubernetes schema validation ran and found schema issues.",
            "`skipped` is not allowed in this required-preflight validation run.",
            "",
        ]
    ),
    encoding="utf-8",
)

print(json.dumps(summary, ensure_ascii=False, indent=2))
PY
```

Expected: command exits 0 only if every sample repo records `kubeconform` as `pass` or `fail`, not `skipped`, and writes `docs/reports/2026-07-13-sample-repo-agent-pipeline-kubeconform.md`.

- [ ] **Step 6: Run documentation/path checks**

Run:

```bash
git diff --check
python3 scripts/validate_context_paths.py .
```

Expected: both pass.

- [ ] **Step 7: Commit**

```bash
git add AGENTS.md README.md docs/reports/2026-07-13-sample-repo-agent-pipeline-test.md docs/reports/2026-07-13-sample-repo-agent-pipeline-kubeconform.md
git commit -m "docs: require kubeconform for sample validation"
```

---

## Final Verification Gate

This is not an implementation task. Run it after Tasks 1-4 are complete because Task 3 changes the shared validator path and Task 4 depends on a real managed `kubeconform` preflight.

- [ ] **Step 1: Run final status and diff checks**

Run:

```bash
git status --short
git diff --check
git diff --stat
```

Expected:
- no unstaged production/test changes except intentional local report artifacts;
- `git diff --check` exits 0.

- [ ] **Step 2: Run context path validation**

Run:

```bash
python3 scripts/validate_context_paths.py .
```

Expected: `context paths ok`.

- [ ] **Step 3: Run targeted tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest tests.unit.test_kubeconform_tool tests.unit.test_validator -v
```

Expected: `OK`.

- [ ] **Step 4: Run full suite**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3 -m unittest discover -s tests -v
```

Expected: all tests pass; existing environment-dependent skips may remain.

- [ ] **Step 5: Verify required preflight**

Run:

```bash
python3 scripts/ensure_kubeconform.py --check
```

Expected: exits 0 and prints `.tools/kubeconform/v0.8.0/<platform>/kubeconform` or `.tools/kubeconform/v0.8.0/windows-amd64/kubeconform.exe`.

- [ ] **Step 6: Verify sample validation no longer skips kubeconform**

Run the sample validation command from Task 4 Step 5.

Expected: no `kubeconform skipped` error. Record whether each repo has `kubeconform: pass` or `kubeconform: fail` in the final response. Do not convert `fail` into success; a fail means schema validation ran and found an issue.

- [ ] **Step 7: Confirm kubeconform report is committed**

Run:

```bash
git log --oneline -- docs/reports/2026-07-13-sample-repo-agent-pipeline-kubeconform.md
```

Expected: the Task 4 documentation commit appears in the output.
