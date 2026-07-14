from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from k8s_agent.models.profile import DeploymentProfile
from k8s_agent.models.report import ExplanationView, FinalReport, ReportResource, ReportSource, ReportValidation
from k8s_agent.models.run import RunRecord, RunState
from k8s_agent.models.source import RepositorySource
from k8s_agent.models.validation import ValidationReport
from k8s_agent.render.renderer import ManifestBundle
from k8s_agent.run.store import RunStore


class FinalReportBuilder:
    def __init__(self, store: RunStore) -> None:
        self.store = store

    def build(self, run_id: str) -> FinalReport:
        run = self.store.load(run_id)
        run_root = self.store.run_path(run_id)
        source = _load_source(run_root)
        validation = _load_validation(run_root)
        profile = _load_profile(run_root)
        bundle = _load_bundle(run_root)
        report = FinalReport(
            run_id=run.run_id,
            state=run.state.value,
            target=run.target,
            source=ReportSource(kind=run.source.kind, value=run.source.value, fingerprint=source.fingerprint.value if source else None),
            summary=_summary(run, validation),
            validation=ReportValidation(
                status=validation.status if validation else "not-run",
                manifest_ready=validation.manifest_ready if validation else False,
                finding_count=len(validation.findings) if validation else 0,
            ),
            resources=_resources(bundle),
            decision_count=len(profile.values) if profile else 0,
            limitations=_limitations(run, profile),
            next_action=_next_action(run, validation),
        )
        self.store.save_yaml(run_id, "final-report.yaml", {"final_report": report.model_dump(mode="json")})
        return report

    def explain(self, run_id: str, subject: str | None) -> ExplanationView:
        run_root = self.store.run_path(run_id)
        profile = _load_profile(run_root)
        bundle = _load_bundle(run_root)
        field, value = _profile_match(profile, subject)
        return ExplanationView(
            subject=subject,
            decision_id=value.decision_id if value else None,
            profile_field=field,
            evidence_refs=sorted(value.evidence_refs) if value else [],
            resources=_resources(bundle),
            trace="Evidence -> Decision -> Profile field -> Resource",
        )


def _load_source(run_root: Path) -> RepositorySource | None:
    payload = _load_yaml(run_root / "source.yaml")
    return RepositorySource.model_validate(payload) if payload else None


def _load_profile(run_root: Path) -> DeploymentProfile | None:
    payload = _load_yaml(run_root / "profile" / "deployment-profile.yaml").get("deployment_profile")
    return DeploymentProfile.model_validate(payload) if payload else None


def _load_validation(run_root: Path) -> ValidationReport | None:
    payload = _load_yaml(run_root / "validation" / "13-validation-report.yaml").get("validation_report")
    return ValidationReport.model_validate(payload) if payload else None


def _load_bundle(run_root: Path) -> ManifestBundle | None:
    payload = _load_yaml(run_root / "generated" / "manifest-bundle.yaml").get("manifest_bundle")
    return ManifestBundle.model_validate(payload) if payload else None


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _summary(run: RunRecord, validation: ValidationReport | None) -> str:
    if run.state == RunState.READY and validation is not None and validation.manifest_ready:
        return "manifest-ready"
    if run.state == RunState.BLOCKED:
        return "blocked"
    if run.state == RunState.FAILED:
        return "failed"
    if run.state == RunState.WAITING_FOR_USER:
        return "waiting-for-user"
    return run.state.value.lower()


def _resources(bundle: ManifestBundle | None) -> list[ReportResource]:
    if bundle is None:
        return []
    return [
        ReportResource(kind=ref.kind, name=ref.name, path=ref.path)
        for ref in sorted(bundle.resource_refs, key=lambda item: (item.kind, item.name, item.path))
    ]


def _limitations(run: RunRecord, profile: DeploymentProfile | None) -> list[str]:
    limitations = ["build-verified not executed", "cluster-verified not executed"]
    if profile is not None:
        limitations.extend(hold.reason_code for hold in profile.blocked)
        limitations.extend(hold.reason_code for hold in profile.unresolved)
    if run.state == RunState.CANCELLED:
        limitations.append("run cancelled")
    return sorted(set(limitations))


def _next_action(run: RunRecord, validation: ValidationReport | None) -> str:
    if run.state == RunState.READY and validation is not None and validation.manifest_ready:
        return "export manifests or review generated bundle"
    if run.state == RunState.BLOCKED:
        return "answer or resolve blockers before manifest generation"
    if run.state == RunState.FAILED:
        return "inspect validation findings and rerun resume"
    if run.state == RunState.WAITING_FOR_USER:
        return "answer required questions then resume"
    return "inspect run status"


def _profile_match(profile: DeploymentProfile | None, subject: str | None):
    if profile is None:
        return None, None
    for field, value in sorted(profile.values.items()):
        if subject in {value.decision_id, field}:
            return field, value
    return None, None
