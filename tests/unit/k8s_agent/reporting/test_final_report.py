from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from k8s_agent.cli import PrepareRequest
from k8s_agent.models.profile import DeploymentProfile, ProfileHold, ProfileValue
from k8s_agent.models.run import RunState
from k8s_agent.models.source import GitMetadata, RepositorySource, SourceFingerprint
from k8s_agent.models.validation import ResourceRef, ValidationFinding, ValidationReport, ValidationStage
from k8s_agent.render.renderer import GeneratedFile, ManifestBundle, ResourceRef as RenderResourceRef
from k8s_agent.reporting.final_report import FinalReportBuilder
from k8s_agent.run.manager import RunManager
from k8s_agent.run.store import RunStore


FIXED_TIME = datetime(2026, 7, 14, 3, 4, 5, tzinfo=timezone.utc)


class FinalReportBuilderTests(unittest.TestCase):
    def test_ready_report_includes_source_validation_resources_limitations_and_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = _ready_run(Path(tmp))

            report = FinalReportBuilder(manager.store).build("run-ready")

            self.assertEqual(report.run_id, "run-ready")
            self.assertEqual(report.state, "READY")
            self.assertEqual(report.summary, "manifest-ready")
            self.assertEqual(report.validation.status, "pass")
            self.assertEqual(report.resources[0].kind, "Deployment")
            self.assertIn("build-verified not executed", report.limitations)
            self.assertIn("cluster-verified not executed", report.limitations)
            self.assertEqual(report.next_action, "export manifests or review generated bundle")
            self.assertNotIn("production-ready", report.model_dump_json())

    def test_blocked_and_failed_reports_have_clear_next_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = _blocked_run(Path(tmp))
            blocked = FinalReportBuilder(manager.store).build("run-blocked")

            self.assertEqual(blocked.summary, "blocked")
            self.assertIn("stateful_requires_design_review", blocked.limitations)
            self.assertEqual(blocked.next_action, "answer or resolve blockers before manifest generation")

            manager = _failed_run(Path(tmp))
            failed = FinalReportBuilder(manager.store).build("run-failed")

            self.assertEqual(failed.summary, "failed")
            self.assertEqual(failed.validation.status, "fail")
            self.assertEqual(failed.next_action, "inspect validation findings and rerun resume")

    def test_explain_links_decision_profile_resource_and_never_includes_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = _ready_run(Path(tmp), include_secret=True)

            explanation = FinalReportBuilder(manager.store).explain("run-ready", "D-secret")

            self.assertEqual(explanation.subject, "D-secret")
            self.assertEqual(explanation.decision_id, "D-secret")
            self.assertEqual(explanation.profile_field, "/components/api/secret_ref")
            self.assertEqual(explanation.resources[0].kind, "Deployment")
            self.assertIn("E-secret", explanation.evidence_refs)
            self.assertIn("Evidence -> Decision -> Profile field -> Resource", explanation.trace)
            self.assertNotIn("changethis", explanation.model_dump_json())


def _ready_run(root: Path, *, include_secret: bool = False) -> RunManager:
    manager = _manager(root, "run-ready")
    _create_run(manager, "run-ready", RunState.READY)
    run_root = manager.store.run_path("run-ready")
    _write_source(manager, "run-ready")
    profile_values = {
        "/components/api/image": _value("api:latest", "D-image", ["E-image"]),
        "/components/api/service": _value({"port": 8000}, "D-service", ["E-port"]),
    }
    if include_secret:
        profile_values["/components/api/secret_ref"] = _value({"name": "api-secret"}, "D-secret", ["E-secret"])
    manager.store.save_yaml("run-ready", "profile/deployment-profile.yaml", {"deployment_profile": DeploymentProfile(revision=1, values=profile_values).model_dump(mode="json")})
    manager.store.save_yaml(
        "run-ready",
        "generated/manifest-bundle.yaml",
        {
            "manifest_bundle": ManifestBundle(
                resource_refs=[RenderResourceRef(kind="Deployment", name="api-app", path="base/api-deployment.yaml")],
                files=[GeneratedFile(path="base/api-deployment.yaml", checksum="sha256:test")],
                checksum="sha256:bundle",
            ).model_dump(mode="json")
        },
    )
    generated = run_root / "generated" / "base"
    generated.mkdir(parents=True, exist_ok=True)
    (generated / "api-deployment.yaml").write_text("kind: Deployment\nmetadata:\n  name: api-app\n", encoding="utf-8")
    manager.store.save_yaml(
        "run-ready",
        "validation/13-validation-report.yaml",
        {
            "validation_report": ValidationReport(
                status="pass",
                manifest_ready=True,
                stages=[ValidationStage(stage="internal", status="pass")],
            ).model_dump(mode="json")
        },
    )
    return manager


def _blocked_run(root: Path) -> RunManager:
    manager = _manager(root, "run-blocked")
    _create_run(manager, "run-blocked", RunState.BLOCKED)
    _write_source(manager, "run-blocked")
    manager.store.save_yaml(
        "run-blocked",
        "profile/deployment-profile.yaml",
        {
            "deployment_profile": DeploymentProfile(
                revision=1,
                blocked=[ProfileHold(target_field="/components/db/workload/stateful", reason_code="stateful_requires_design_review")],
                renderable=False,
            ).model_dump(mode="json")
        },
    )
    return manager


def _failed_run(root: Path) -> RunManager:
    manager = _manager(root, "run-failed")
    _create_run(manager, "run-failed", RunState.FAILED)
    _write_source(manager, "run-failed")
    manager.store.save_yaml(
        "run-failed",
        "validation/13-validation-report.yaml",
        {
            "validation_report": ValidationReport(
                status="fail",
                manifest_ready=False,
                stages=[ValidationStage(stage="internal", status="fail")],
                findings=[
                    ValidationFinding(
                        finding_id="VF-test",
                        validator="internal",
                        severity="error",
                        resource_ref=ResourceRef(kind="Service", name="api", path="base/api-service.yaml"),
                        field_path="/spec/selector",
                        code="selector_mismatch",
                        message="selector mismatch",
                    )
                ],
            ).model_dump(mode="json")
        },
    )
    return manager


def _manager(root: Path, run_id: str) -> RunManager:
    return RunManager(RunStore(root / "runs"), clock=lambda: FIXED_TIME, run_id_factory=lambda: run_id)


def _create_run(manager: RunManager, run_id: str, terminal: RunState) -> None:
    manager.create(
        PrepareRequest(
            repo_url=None,
            local_path=Path("/repo/app"),
            ref=None,
            target="development",
            non_interactive=False,
            answers_file=None,
        )
    )
    manager.transition(run_id, RunState.ACQUIRING_SOURCE, "source acquisition started")
    manager.transition(run_id, RunState.ANALYZING, "agent orchestration started")
    manager.transition(run_id, terminal, terminal.value.lower())


def _write_source(manager: RunManager, run_id: str) -> None:
    manager.store.save_yaml(
        run_id,
        "source.yaml",
        RepositorySource(
            kind="local",
            path=Path("/repo/app"),
            acquired_at=FIXED_TIME,
            git=GitMetadata(is_repository=False),
            fingerprint=SourceFingerprint(value="sha256:source", file_count=1),
        ).model_dump(mode="json"),
    )


def _value(value, decision_id: str, refs: list[str]) -> ProfileValue:
    return ProfileValue(
        value=value,
        decision_id=decision_id,
        classification="policy_default",
        confidence="high",
        evidence_refs=refs,
        actor="policy",
        approval="automatic",
    )


if __name__ == "__main__":
    unittest.main()
