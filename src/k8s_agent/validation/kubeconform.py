from __future__ import annotations

import subprocess
from pathlib import Path

from k8s_agent.models.validation import ValidationFinding, ValidationReport, ValidationStage
from k8s_agent.validation.internal import _finding
from preanalyzer.validator.kubeconform_tool import resolve_kubeconform


SCHEMA_DIR = Path(__file__).resolve().parent / "schemas" / "kubeconform"


class KubeconformValidator:
    def __init__(
        self,
        *,
        binary: Path | None = None,
        schema_dir: Path = SCHEMA_DIR,
        timeout_seconds: int = 30,
    ) -> None:
        self.binary = binary
        self.schema_dir = schema_dir
        self.timeout_seconds = timeout_seconds

    def validate(self, paths: list[Path]) -> ValidationReport:
        if self.binary is None:
            finding: ValidationFinding = _finding(
                "kubeconform",
                "error",
                None,
                "/",
                "kubeconform_missing",
                "kubeconform binary is not configured; run scripts/ensure_kubeconform.py.",
            )
            return ValidationReport(
                status="tool-missing",
                manifest_ready=False,
                stages=[ValidationStage(stage="kubeconform", status="tool-missing")],
                findings=[finding],
            )

        command = [
            str(self.binary),
            "-strict",
            "-summary",
            "-schema-location",
            f"file://{self.schema_dir}/{{{{.ResourceKind}}}}{{{{.StrictSuffix}}}}.json",
            "-skip",
            "Kustomization",
            *[str(path) for path in paths],
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError:
            finding = _finding(
                "kubeconform",
                "error",
                None,
                "/",
                "kubeconform_missing",
                f"kubeconform binary not found: {self.binary}",
            )
            return ValidationReport(
                status="tool-missing",
                manifest_ready=False,
                stages=[ValidationStage(stage="kubeconform", status="tool-missing")],
                findings=[finding],
            )
        except subprocess.TimeoutExpired as exc:
            finding = _finding(
                "kubeconform",
                "error",
                None,
                "/",
                "kubeconform_timeout",
                f"kubeconform timed out after {exc.timeout} seconds",
            )
            return ValidationReport(
                status="fail",
                manifest_ready=False,
                stages=[ValidationStage(stage="kubeconform", status="fail")],
                findings=[finding],
            )
        except OSError as exc:
            finding = _finding(
                "kubeconform",
                "error",
                None,
                "/",
                "kubeconform_execution_error",
                f"kubeconform execution failed: {exc}",
            )
            return ValidationReport(
                status="fail",
                manifest_ready=False,
                stages=[ValidationStage(stage="kubeconform", status="fail")],
                findings=[finding],
            )

        if completed.returncode == 0:
            return ValidationReport(
                status="pass",
                manifest_ready=True,
                stages=[ValidationStage(stage="kubeconform", status="pass")],
            )
        finding = _finding("kubeconform", "error", None, "/", "kubeconform_failed", _detail(completed.stdout, completed.stderr))
        return ValidationReport(
            status="fail",
            manifest_ready=False,
            stages=[ValidationStage(stage="kubeconform", status="fail")],
            findings=[finding],
        )


def project_kubeconform_binary(repo_root: Path) -> Path | None:
    resolved = resolve_kubeconform(repo_root)
    return Path(resolved) if resolved is not None else None


def _detail(stdout: str, stderr: str) -> str:
    text = "\n".join(part.strip() for part in (stdout, stderr) if part and part.strip())
    return text[:1000] if text else "kubeconform validation failed"
