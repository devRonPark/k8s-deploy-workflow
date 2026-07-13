from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from k8s_agent.models.validation import ValidationReport, ValidationStage
from k8s_agent.validation.internal import _finding


class KustomizeValidator:
    def __init__(self, *, binary: Path | None = None, timeout_seconds: int = 30) -> None:
        self.binary = binary
        self.timeout_seconds = timeout_seconds

    def validate(self, paths: list[Path]) -> ValidationReport:
        if self.binary is None:
            return ValidationReport(
                status="not-run",
                manifest_ready=False,
                stages=[ValidationStage(stage="kustomize", status="not-run")],
            )
        kustomizations = sorted({path.parent for path in paths if path.name == "kustomization.yaml"})
        for directory in kustomizations:
            command = [str(self.binary), "build", str(directory)]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=self.timeout_seconds,
                )
            except FileNotFoundError:
                finding = _finding("kustomize", "error", None, "/", "kustomize_missing", f"kustomize binary not found: {self.binary}")
                return ValidationReport(
                    status="tool-missing",
                    manifest_ready=False,
                    stages=[ValidationStage(stage="kustomize", status="tool-missing")],
                    findings=[finding],
                )
            except subprocess.TimeoutExpired as exc:
                finding = _finding("kustomize", "error", None, "/", "kustomize_timeout", f"kustomize timed out after {exc.timeout} seconds")
                return ValidationReport(
                    status="fail",
                    manifest_ready=False,
                    stages=[ValidationStage(stage="kustomize", status="fail")],
                    findings=[finding],
                )
            except OSError as exc:
                finding = _finding("kustomize", "error", None, "/", "kustomize_execution_error", f"kustomize execution failed: {exc}")
                return ValidationReport(
                    status="fail",
                    manifest_ready=False,
                    stages=[ValidationStage(stage="kustomize", status="fail")],
                    findings=[finding],
                )
            if completed.returncode != 0:
                finding = _finding("kustomize", "error", None, "/", "kustomize_failed", _detail(completed.stdout, completed.stderr))
                return ValidationReport(
                    status="fail",
                    manifest_ready=False,
                    stages=[ValidationStage(stage="kustomize", status="fail")],
                    findings=[finding],
                )
        return ValidationReport(status="pass", manifest_ready=True, stages=[ValidationStage(stage="kustomize", status="pass")])


def path_kustomize_binary() -> Path | None:
    resolved = shutil.which("kustomize")
    return Path(resolved) if resolved is not None else None


def _detail(stdout: str, stderr: str) -> str:
    text = "\n".join(part.strip() for part in (stdout, stderr) if part and part.strip())
    return text[:1000] if text else "kustomize validation failed"
