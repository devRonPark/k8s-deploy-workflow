from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

import yaml

from k8s_agent.agent.orchestrator import AgentOrchestrator, RunOutcome, TOOL_VERSIONS
from k8s_agent.agent.planner import AgentPlan, AgentPlanner, PlanningContext
from k8s_agent.analysis.intent_builder import IntentBuilder
from k8s_agent.analysis.phase1_adapter import Phase1Adapter
from k8s_agent.analysis.topology_builder import TopologyBuilder
from k8s_agent.cli import PrepareRequest
from k8s_agent.errors import AgentError
from k8s_agent.models.profile import DeploymentProfile
from k8s_agent.models.report import ExportResult
from k8s_agent.models.run import RunRecord, RunState
from k8s_agent.models.source import AcquiredSource, RepositorySource
from k8s_agent.models.topology import ApplicationTopology
from k8s_agent.models.validation import ValidationReport
from k8s_agent.profile.builder import DeploymentProfileBuilder, ProfileInputs
from k8s_agent.questions.manager import QuestionManager
from k8s_agent.render.renderer import ManifestBundle, ManifestRenderer
from k8s_agent.reporting.final_report import FinalReportBuilder
from k8s_agent.run.manager import RunManager
from k8s_agent.run.store import RunStore
from k8s_agent.source.github import GitHubSourceResolver
from k8s_agent.source.git_runner import CommandAudit, GitRunner
from k8s_agent.source.local import LocalSourceResolver
from k8s_agent.source.workspace import WorkspaceManager
from k8s_agent.validation.orchestrator import ValidationOrchestrator


PrepareOutcome = RunOutcome


class DriftPolicy(StrEnum):
    CONTINUE_PINNED = "continue-pinned"
    REPLAN = "replan"
    NEW_RUN = "new-run"


class AgentApplication:
    def __init__(
        self,
        state_home: Path | None = None,
        clock=None,
        run_manager: RunManager | None = None,
    ) -> None:
        self.state_home = state_home or _default_state_home()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.store = run_manager.store if run_manager else RunStore(self.state_home / "runs")
        self.run_manager = run_manager or RunManager(self.store, clock=self.clock)

    def prepare(self, request: PrepareRequest) -> PrepareOutcome:
        run = self.run_manager.create(request)
        self.run_manager.transition(run.run_id, RunState.ACQUIRING_SOURCE, "source acquisition started")
        try:
            source = self._acquire_source(request, run.run_id)
            self.store.save_yaml(run.run_id, "source.yaml", _source_payload(source))
        except Exception:
            self.run_manager.transition(run.run_id, RunState.FAILED, "source acquisition failed")
            raise
        return AgentOrchestrator(run_manager=self.run_manager).run(run.run_id)

    def analyze(self, request: PrepareRequest) -> RunOutcome:
        run = self.run_manager.create(request)
        self.run_manager.transition(run.run_id, RunState.ACQUIRING_SOURCE, "source acquisition started")
        try:
            source = self._acquire_source(request, run.run_id)
            self.store.save_yaml(run.run_id, "source.yaml", _source_payload(source))
            self.run_manager.transition(run.run_id, RunState.ANALYZING, "stage analyze started")
            phase1 = Phase1Adapter(store=self.store, clock=self.clock).run(source, run.run_id)
            TopologyBuilder().build(phase1)
            self.store.save_yaml(run.run_id, "agent/runtime-metadata.yaml", {"tool_versions": TOOL_VERSIONS})
            self.run_manager.append_event(run.run_id, "stage_analyze_completed", "stage analyze completed", {"command": "analyze"})
            record = self.run_manager.transition(run.run_id, RunState.WAITING_FOR_USER, "analysis completed; run plan")
            return _resume_outcome(record, 0, "analysis completed; run plan")
        except Exception:
            self.run_manager.transition(run.run_id, RunState.FAILED, "stage analyze failed")
            raise

    def plan(self, run_id: str) -> AgentPlan:
        run_root = self.store.run_path(run_id)
        topology_path = run_root / "analysis" / "04-application-topology.yaml"
        if not topology_path.is_file():
            raise _stage_error("STAGE-101", "analysis artifacts are required before plan.", "Run k8s-agent analyze first.", run_id)
        record = self.store.load(run_id)
        topology = _load_topology(topology_path)
        intent = IntentBuilder(output_dir=run_root / "analysis").build(topology, record.target)
        plan = AgentPlanner().plan(PlanningContext(topology=topology, intent=intent))
        questions = QuestionManager().build(intent, plan)
        profile = DeploymentProfileBuilder().build(ProfileInputs(intent=intent, decisions=[]))
        self.store.save_yaml(run_id, "agent/plan.yaml", {"agent_plan": plan.model_dump(mode="json")})
        self.store.save_yaml(run_id, "agent/questions.yaml", {"question_set": questions.model_dump(mode="json")})
        self.store.save_yaml(run_id, "profile/deployment-profile.yaml", {"deployment_profile": profile.model_dump(mode="json")})
        self.run_manager.append_event(run_id, "stage_plan_completed", "stage plan completed", {"command": "plan"})
        return plan

    def generate(self, run_id: str, profile_revision: int | None = None) -> ManifestBundle:
        profile = _load_profile(self.store.run_path(run_id))
        if profile is None or not profile.renderable:
            raise _stage_error("STAGE-201", "renderable deployment profile is required before generate.", "Resolve questions or provide a renderable profile.", run_id)
        if profile_revision is not None and profile.revision != profile_revision:
            raise _stage_error("STAGE-202", "requested profile revision is not available.", "Use the current profile revision.", run_id)
        destination = self.store.run_path(run_id) / "generated"
        bundle = ManifestRenderer().render(profile, destination)
        self.store.save_yaml(run_id, "generated/manifest-bundle.yaml", {"manifest_bundle": bundle.model_dump(mode="json")})
        self.run_manager.append_event(run_id, "stage_generate_completed", "stage generate completed", {"command": "generate", "profile_revision": str(profile.revision)})
        return bundle

    def validate(self, run_id: str) -> ValidationReport:
        run_root = self.store.run_path(run_id)
        profile = _load_profile(run_root)
        bundle = _load_bundle(run_root)
        if profile is None or bundle is None:
            raise _stage_error("STAGE-301", "generated manifest bundle is required before validate.", "Run k8s-agent generate first.", run_id)
        report = ValidationOrchestrator(run_external=False).validate(bundle, profile, run_root / "generated")
        self.store.save_yaml(run_id, "validation/13-validation-report.yaml", {"validation_report": report.model_dump(mode="json")})
        self.run_manager.append_event(run_id, "stage_validate_completed", "stage validate completed", {"command": "validate", "manifest_ready": str(report.manifest_ready)})
        return report

    def resume(self, run_id: str, drift_policy: DriftPolicy | None = None) -> RunOutcome:
        record = self.store.load(run_id)
        if record.state in {RunState.READY, RunState.FAILED, RunState.BLOCKED, RunState.CANCELLED}:
            return _resume_outcome(record, _terminal_resume_exit_code(record.state), f"run state {record.state.value} is not resumable")

        source = _load_source(self.store.run_path(run_id) / "source.yaml")
        drift = self._source_drift(source)
        if drift and drift_policy is None:
            self.store.save_yaml(run_id, "resume/source-drift.yaml", {"source_drift": drift})
            self.run_manager.append_event(run_id, "resume_source_drift", "source drift detected", {"run_id": run_id})
            return _resume_outcome(record, 3, "source drift detected; choose a drift policy before continuing")
        if drift and drift_policy == DriftPolicy.NEW_RUN:
            self.run_manager.append_event(run_id, "resume_source_drift", "source drift starts a new run", {"run_id": run_id})
            return self.prepare(
                PrepareRequest(
                    repo_url=None,
                    local_path=source.path,
                    ref=None,
                    target=record.target,
                    non_interactive=False,
                    answers_file=None,
                )
            )
        if drift and drift_policy == DriftPolicy.REPLAN:
            current = LocalSourceResolver(git=self._audited_git_runner(run_id)).resolve(source.path, self.clock())
            self.store.save_yaml(run_id, "source.yaml", _source_payload(current))
            self.run_manager.append_event(run_id, "resume_source_replan", "source drift accepted for replan", {"run_id": run_id})
            return AgentOrchestrator(run_manager=self.run_manager, reuse_completed_analysis=False).run(run_id)
        if drift and drift_policy == DriftPolicy.CONTINUE_PINNED:
            self.run_manager.append_event(run_id, "resume_source_pinned", "source drift ignored for pinned resume", {"run_id": run_id})
            return AgentOrchestrator(run_manager=self.run_manager, reuse_completed_analysis=True).run(run_id)

        self.run_manager.append_event(run_id, "resume_source_check", "resume source unchanged", {"run_id": run_id})
        return AgentOrchestrator(run_manager=self.run_manager, reuse_completed_analysis=True).run(run_id)

    def status(self, run_id: str):
        return FinalReportBuilder(self.store).build(run_id)

    def explain(self, run_id: str, subject: str | None):
        return FinalReportBuilder(self.store).explain(run_id, subject)

    def export(self, run_id: str, output: Path, overwrite: bool = False) -> ExportResult:
        run_root = self.store.run_path(run_id)
        generated = run_root / "generated"
        if not generated.is_dir():
            raise AgentError(
                code="EXPORT-102",
                exit_code=3,
                message="generated manifests are not available for export.",
                resolution="Run prepare/resume until manifests are generated.",
                context={"run_id": run_id},
            )
        destination = output.expanduser().resolve()
        if destination.exists() and not overwrite:
            raise AgentError(
                code="EXPORT-101",
                exit_code=2,
                message=f"export output already exists: {destination}",
                resolution="Choose a new output path or pass --overwrite.",
                context={"run_id": run_id, "output": str(destination)},
            )
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(generated, destination)
        file_count = len([path for path in destination.rglob("*") if path.is_file()])
        return ExportResult(run_id=run_id, output=str(destination), file_count=file_count)

    def _acquire_source(self, request: PrepareRequest, run_id: str) -> RepositorySource:
        acquired_at = self.clock()
        git = self._audited_git_runner(run_id)
        if request.local_path is not None:
            return LocalSourceResolver(git=git).resolve(request.local_path, acquired_at)
        workspace = WorkspaceManager(self.state_home / "runs").create(run_id)
        try:
            acquired = GitHubSourceResolver(git=git).acquire(request.repo_url or "", request.ref, workspace, acquired_at)
        except Exception:
            WorkspaceManager(self.state_home / "runs").cleanup(workspace)
            raise
        return _repository_source(acquired)

    def _source_drift(self, source: RepositorySource) -> dict | None:
        if source.kind == "github":
            return None
        current = LocalSourceResolver().resolve(source.path, self.clock())
        drift: dict[str, str] = {}
        if current.fingerprint.value != source.fingerprint.value:
            drift["fingerprint"] = "changed"
            drift["saved_fingerprint"] = source.fingerprint.value
            drift["current_fingerprint"] = current.fingerprint.value
        if source.git.head and current.git.head and current.git.head != source.git.head:
            drift["git_head"] = "changed"
            drift["saved_head"] = source.git.head
            drift["current_head"] = current.git.head
        return drift or None

    def _audited_git_runner(self, run_id: str) -> GitRunner:
        def append(audit: CommandAudit) -> None:
            self.run_manager.append_event(run_id, "tool_execution", "tool executed", audit.details())

        return GitRunner(audit_sink=append)


def _default_state_home() -> Path:
    configured = os.environ.get("K8S_AGENT_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "state" / "k8s-agent"


def _repository_source(acquired: AcquiredSource) -> RepositorySource:
    return acquired.source


def _source_payload(source: RepositorySource) -> dict:
    return source.model_dump(mode="json")


def _load_source(path: Path) -> RepositorySource:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return RepositorySource.model_validate(payload)


def _load_topology(path: Path) -> ApplicationTopology:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ApplicationTopology.model_validate(payload.get("application_topology") or payload)


def _load_profile(run_root: Path) -> DeploymentProfile | None:
    path = run_root / "profile" / "deployment-profile.yaml"
    if not path.is_file():
        return None
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return DeploymentProfile.model_validate(payload.get("deployment_profile") or payload)


def _load_bundle(run_root: Path) -> ManifestBundle | None:
    path = run_root / "generated" / "manifest-bundle.yaml"
    if not path.is_file():
        return None
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ManifestBundle.model_validate(payload.get("manifest_bundle") or payload)


def _resume_outcome(record: RunRecord, exit_code: int, message: str) -> RunOutcome:
    return RunOutcome(
        run_id=record.run_id,
        run_root=record.run_root,
        target=record.target,
        source_kind=record.source.kind,
        state=record.state,
        exit_code=exit_code,
        message=message,
    )


def _terminal_resume_exit_code(state: RunState) -> int:
    if state == RunState.READY:
        return 0
    return 8


def _stage_error(code: str, message: str, resolution: str, run_id: str) -> AgentError:
    return AgentError(code=code, exit_code=3, message=message, resolution=resolution, context={"run_id": run_id})
