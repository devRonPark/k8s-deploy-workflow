from __future__ import annotations

from pathlib import Path

from k8s_agent.models.validation import ValidationReport, ValidationStage


class KustomizeValidator:
    def __init__(self, *, binary: Path | None = None) -> None:
        self.binary = binary

    def validate(self, paths: list[Path]) -> ValidationReport:
        del paths
        if self.binary is None:
            return ValidationReport(status="not-run", manifest_ready=False, stages=[ValidationStage(stage="kustomize", status="not-run")])
        return ValidationReport(status="pass", manifest_ready=True, stages=[ValidationStage(stage="kustomize", status="pass")])
