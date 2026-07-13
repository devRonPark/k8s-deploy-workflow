from __future__ import annotations

from pathlib import Path

from k8s_agent.models.validation import ValidationFinding, ValidationReport, ValidationStage
from k8s_agent.validation.internal import _finding


class KubeconformValidator:
    def __init__(self, *, binary: Path | None = None) -> None:
        self.binary = binary

    def validate(self, paths: list[Path]) -> ValidationReport:
        del paths
        if self.binary is None:
            finding: ValidationFinding = _finding(
                "kubeconform",
                "error",
                None,
                "/",
                "kubeconform_missing",
                "kubeconform binary is not configured; run scripts/ensure_kubeconform.py.",
            )
            return ValidationReport(status="tool-missing", manifest_ready=False, stages=[ValidationStage(stage="kubeconform", status="tool-missing")], findings=[finding])
        return ValidationReport(status="pass", manifest_ready=True, stages=[ValidationStage(stage="kubeconform", status="pass")])
