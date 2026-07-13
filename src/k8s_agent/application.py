from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

import yaml

from k8s_agent.agent.orchestrator import AgentOrchestrator, RunOutcome
from k8s_agent.cli import PrepareRequest
from k8s_agent.errors import AgentError
from k8s_agent.models.report import ExportResult
from k8s_agent.models.run import RunRecord, RunState
from k8s_agent.models.source import AcquiredSource, RepositorySource
from k8s_agent.reporting.final_report import FinalReportBuilder
from k8s_agent.run.manager import RunManager
from k8s_agent.run.store import RunStore
from k8s_agent.source.github import GitHubSourceResolver
from k8s_agent.source.local import LocalSourceResolver
from k8s_agent.source.workspace import WorkspaceManager


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
            current = LocalSourceResolver().resolve(source.path, self.clock())
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
        if request.local_path is not None:
            return LocalSourceResolver().resolve(request.local_path, acquired_at)
        workspace = WorkspaceManager(self.state_home / "runs").create(run_id)
        try:
            acquired = GitHubSourceResolver().acquire(request.repo_url or "", request.ref, workspace, acquired_at)
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
