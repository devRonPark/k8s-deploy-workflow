from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from preanalyzer.models.report import StageResult, ValidationReport
from preanalyzer.validator.kubeconform_tool import resolve_kubeconform


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

    def run(self, manifest_dir: Path, rendered_placeholders: bool = False) -> ValidationReport:
        stages: list[StageResult] = []
        yaml_ok = self._yaml_syntax(manifest_dir, stages)

        kubeconform_status = "skipped"
        if yaml_ok:
            kubeconform_status = self._kubeconform(manifest_dir, stages)
        else:
            stages.append(
                StageResult(stage="kubeconform", status="skipped", detail="prior stage failed")
            )

        if yaml_ok and kubeconform_status == "pass":
            self._dry_run(manifest_dir, stages)
        else:
            stages.append(StageResult(stage="dry_run", status="skipped", detail="prior stage not pass"))

        achieved = 1 if yaml_ok and kubeconform_status == "pass" and not rendered_placeholders else 0
        return ValidationReport(target_level=1, achieved_level=achieved, stages=stages)

    def _yaml_syntax(self, directory: Path, stages: list[StageResult]) -> bool:
        for path in sorted(directory.rglob("*.yaml")):
            try:
                yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                stages.append(
                    StageResult(stage="yaml_syntax", status="fail", detail=f"{path.name}: {exc}")
                )
                return False
        stages.append(StageResult(stage="yaml_syntax", status="pass"))
        return True

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

    def _dry_run(self, directory: Path, stages: list[StageResult]) -> None:
        import shutil

        if shutil.which("kubectl") is None:
            stages.append(StageResult(stage="dry_run", status="skipped", detail="tool_not_found"))
            return

        proc = subprocess.run(
            ["kubectl", "apply", "--dry-run=client", "-f", str(directory)],
            capture_output=True,
            text=True,
            check=False,
        )
        stages.append(
            StageResult(
                stage="dry_run",
                status="pass" if proc.returncode == 0 else "fail",
                detail=(proc.stdout or proc.stderr).strip()[:500],
            )
        )
