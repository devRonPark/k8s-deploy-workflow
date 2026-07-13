from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from k8s_agent.models.profile import DeploymentProfile
from k8s_agent.models.validation import ValidationReport
from k8s_agent.render.renderer import ManifestBundle
from k8s_agent.repair.strategies import apply_strategy, strategy_for
from k8s_agent.validation.orchestrator import ValidationOrchestrator


class RepairAttempt(BaseModel):
    attempt: int
    finding_refs: list[str] = Field(default_factory=list)
    strategy: str
    files_changed: list[str] = Field(default_factory=list)
    validation_result: ValidationReport


class RepairResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repaired: bool
    attempts: list[RepairAttempt] = Field(default_factory=list)
    validation_result: ValidationReport
    blocked_reasons: list[str] = Field(default_factory=list)


class RepairController:
    def __init__(self, *, destination: Path, max_attempts: int = 3) -> None:
        self.destination = destination
        self.max_attempts = max_attempts

    def repair(self, bundle: ManifestBundle, profile: DeploymentProfile, report: ValidationReport) -> RepairResult:
        allowed = {file.path for file in bundle.files}
        attempts: list[RepairAttempt] = []
        used: set[tuple[str, str]] = set()
        current = report
        blocked: list[str] = []
        for attempt_no in range(1, self.max_attempts + 1):
            finding = next((item for item in current.findings if strategy_for(item) is not None), None)
            if finding is None:
                return RepairResult(repaired=bool(attempts), attempts=attempts, validation_result=current, blocked_reasons=blocked)
            strategy = strategy_for(finding) or ""
            key = (finding.code, strategy)
            if key in used:
                blocked.append("repeated_strategy_suppressed")
                break
            used.add(key)
            path = _relative_finding_path(self.destination, finding.resource_ref.path if finding.resource_ref else None)
            if path not in allowed:
                blocked.append("generated_path_guard")
                break
            service_path = self.destination / path
            deployment_path = _first_deployment_path(self.destination, allowed)
            changed = apply_strategy(strategy, service_path, deployment_path)
            current = ValidationOrchestrator(run_external=True).validate(bundle, profile, self.destination)
            record = RepairAttempt(
                attempt=attempt_no,
                finding_refs=[finding.finding_id],
                strategy=strategy,
                files_changed=[path.relative_to(self.destination).as_posix() for path in changed],
                validation_result=current,
            )
            attempts.append(record)
            _write_attempt(self.destination, record)
            if current.manifest_ready:
                return RepairResult(repaired=True, attempts=attempts, validation_result=current, blocked_reasons=blocked)
        if not blocked:
            blocked.append("max_attempts_exceeded")
        return RepairResult(repaired=bool(attempts), attempts=attempts, validation_result=current, blocked_reasons=blocked)


def _first_deployment_path(destination: Path, allowed: set[str]) -> Path:
    for path in sorted(allowed):
        if path.endswith("-deployment.yaml"):
            return destination / path
    raise ValueError("deployment file not found")


def _relative_finding_path(destination: Path, path: str | None) -> str | None:
    if path is None:
        return None
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(destination.resolve()).as_posix()
        except ValueError:
            return path
    return path


def _write_attempt(destination: Path, attempt: RepairAttempt) -> None:
    repair_dir = destination / "repairs"
    repair_dir.mkdir(parents=True, exist_ok=True)
    (repair_dir / f"attempt-{attempt.attempt}.yaml").write_text(
        yaml.safe_dump(attempt.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
