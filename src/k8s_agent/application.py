from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from k8s_agent.agent.orchestrator import AgentOrchestrator, RunOutcome
from k8s_agent.cli import PrepareRequest
from k8s_agent.models.run import RunState
from k8s_agent.models.source import AcquiredSource, RepositorySource
from k8s_agent.run.manager import RunManager
from k8s_agent.run.store import RunStore
from k8s_agent.source.github import GitHubSourceResolver
from k8s_agent.source.local import LocalSourceResolver
from k8s_agent.source.workspace import WorkspaceManager


PrepareOutcome = RunOutcome


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


def _default_state_home() -> Path:
    configured = os.environ.get("K8S_AGENT_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "state" / "k8s-agent"


def _repository_source(acquired: AcquiredSource) -> RepositorySource:
    return acquired.source


def _source_payload(source: RepositorySource) -> dict:
    return source.model_dump(mode="json")
