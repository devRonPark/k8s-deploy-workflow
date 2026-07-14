from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from k8s_agent.cli import PrepareRequest
from k8s_agent.errors import AgentError
from k8s_agent.models.run import RunEvent, RunRecord, RunSource, RunState, TERMINAL_STATES
from k8s_agent.run.events import EventLog
from k8s_agent.run.store import RunStore
from k8s_agent.source.github import sanitize_github_url


ALLOWED_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.CREATED: {RunState.ACQUIRING_SOURCE, RunState.FAILED, RunState.CANCELLED},
    RunState.ACQUIRING_SOURCE: {RunState.ANALYZING, RunState.FAILED, RunState.CANCELLED},
    RunState.ANALYZING: {
        RunState.WAITING_FOR_USER,
        RunState.READY,
        RunState.BLOCKED,
        RunState.FAILED,
        RunState.CANCELLED,
    },
    RunState.WAITING_FOR_USER: {RunState.ANALYZING, RunState.BLOCKED, RunState.CANCELLED},
}


class RunManager:
    def __init__(
        self,
        store: RunStore,
        clock: Callable[[], datetime] | None = None,
        run_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.run_id_factory = run_id_factory or (lambda: f"run-{uuid4().hex}")

    def create(self, request: PrepareRequest) -> RunRecord:
        run_id = self.run_id_factory()
        now = self.clock()
        source = _source_from_request(request)
        record = RunRecord(
            run_id=run_id,
            run_root=self.store.run_path(run_id),
            state=RunState.CREATED,
            target=request.target,
            source=source,
            created_at=now,
            updated_at=now,
            last_successful_state=RunState.CREATED,
        )
        with self.store.acquire_lock(run_id):
            saved = self.store.save(record)
            self._events(run_id).append(
                RunEvent(
                    event_id=self._event_id(),
                    run_id=run_id,
                    event_type="run_created",
                    created_at=now,
                    summary="run created",
                    details={"state": RunState.CREATED.value, "target": request.target},
                )
            )
        return saved

    def transition(self, run_id: str, target: RunState, summary: str) -> RunRecord:
        with self.store.acquire_lock(run_id):
            current = self.store.load(run_id)
            _ensure_transition_allowed(current.state, target, run_id)
            now = self.clock()
            last_successful_state = current.last_successful_state
            if target not in {RunState.FAILED, RunState.CANCELLED}:
                last_successful_state = target
            updated = current.model_copy(
                update={
                    "state": target,
                    "updated_at": now,
                    "last_successful_state": last_successful_state,
                }
            )
            saved = self.store.save(updated)
            self._events(run_id).append(
                RunEvent(
                    event_id=self._event_id(),
                    run_id=run_id,
                    event_type="state_transition",
                    created_at=now,
                    summary=summary,
                    details={"from": current.state.value, "to": target.value},
                )
            )
            return saved

    def append_event(self, run_id: str, event_type: str, summary: str, details: dict[str, str] | None = None) -> None:
        self._events(run_id).append(
            RunEvent(
                event_id=self._event_id(),
                run_id=run_id,
                event_type=event_type,
                created_at=self.clock(),
                summary=summary,
                details=details or {},
            )
        )

    def _events(self, run_id: str) -> EventLog:
        return EventLog(self.store.event_file(run_id))

    def _event_id(self) -> str:
        return f"event-{uuid4().hex}"


def _source_from_request(request: PrepareRequest) -> RunSource:
    if request.local_path is not None:
        return RunSource(kind="local", value=str(Path(request.local_path)), ref=None)
    if request.repo_url is not None:
        return RunSource(kind="github", value=sanitize_github_url(request.repo_url), ref=request.ref)
    raise AgentError(
        code="RUN-102",
        exit_code=2,
        message="run creation requires a source.",
        resolution="Create runs from a validated prepare request.",
        context={},
    )


def _ensure_transition_allowed(current: RunState, target: RunState, run_id: str) -> None:
    if current in TERMINAL_STATES or target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise AgentError(
            code="RUN-201",
            exit_code=8,
            message=f"cannot transition run '{run_id}' from {current.value} to {target.value}.",
            resolution="Resume from the last successful state or start a new run.",
            context={"run_id": run_id, "from": current.value, "to": target.value},
        )
