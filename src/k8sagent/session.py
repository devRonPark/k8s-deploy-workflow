from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from k8sagent.errors import SessionError


class SessionState(str, Enum):
    CREATED = "created"
    REPO_READY = "repo_ready"
    ANALYZED = "analyzed"
    COMPONENTS_SELECTED = "components_selected"
    INTENT_DRAFTED = "intent_drafted"
    INTENT_RESOLVED = "intent_resolved"
    PLAN_APPROVED = "plan_approved"
    GENERATED = "generated"
    VALIDATED = "validated"
    COMPLETED = "completed"
    FAILED = "failed"


class RepoSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["local", "git_url"]
    location: str
    ref: str | None = None
    commit_sha: str | None = None
    cache_path: str | None = None


class AgentSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    created_at: str
    updated_at: str
    state: SessionState
    source: RepoSource | None = None
    repo_path: str | None = None
    output_dir: str | None = None
    selected_components: list[str] = Field(default_factory=list)
    excluded_components: list[str] = Field(default_factory=list)
    answers: dict[str, str | int | bool] = Field(default_factory=dict)
    applied_changes: list[dict] = Field(default_factory=list)
    k8s_version: str
    llm_enabled: bool


_FORWARD = [
    SessionState.CREATED,
    SessionState.REPO_READY,
    SessionState.ANALYZED,
    SessionState.COMPONENTS_SELECTED,
    SessionState.INTENT_DRAFTED,
    SessionState.INTENT_RESOLVED,
    SessionState.PLAN_APPROVED,
    SessionState.GENERATED,
    SessionState.VALIDATED,
    SessionState.COMPLETED,
]
ALLOWED_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    state: {nxt} for state, nxt in zip(_FORWARD, _FORWARD[1:])
}
ALLOWED_TRANSITIONS[SessionState.PLAN_APPROVED].add(SessionState.INTENT_RESOLVED)
ALLOWED_TRANSITIONS[SessionState.VALIDATED].add(SessionState.GENERATED)
for state in list(SessionState):
    if state is not SessionState.FAILED:
        ALLOWED_TRANSITIONS.setdefault(state, set()).add(SessionState.FAILED)


def _fmt(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def advance(
    session: AgentSession,
    new_state: SessionState,
    clock: Callable[[], datetime],
) -> AgentSession:
    if new_state not in ALLOWED_TRANSITIONS.get(session.state, set()):
        raise SessionError(f"illegal transition {session.state.value} -> {new_state.value}")
    return session.model_copy(update={"state": new_state, "updated_at": _fmt(clock())})


class SessionStore:
    def __init__(
        self,
        home: Path,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.home = home
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.id_factory = id_factory or self._default_id

    def _default_id(self) -> str:
        return f"{self.clock():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"

    @property
    def sessions_dir(self) -> Path:
        return self.home / "sessions"

    def create(self, *, k8s_version: str, llm_enabled: bool) -> AgentSession:
        now = _fmt(self.clock())
        return AgentSession(
            session_id=self.id_factory(),
            created_at=now,
            updated_at=now,
            state=SessionState.CREATED,
            k8s_version=k8s_version,
            llm_enabled=llm_enabled,
        )

    def save(self, session: AgentSession) -> None:
        session_dir = self.sessions_dir / session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        target = session_dir / "session.json"
        tmp = session_dir / "session.json.tmp"
        tmp.write_text(session.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, target)

    def load(self, session_id: str) -> AgentSession:
        path = self.sessions_dir / session_id / "session.json"
        if not path.is_file():
            raise SessionError(f"session not found: {session_id}")
        try:
            return AgentSession.model_validate_json(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValidationError, OSError) as exc:
            raise SessionError(f"invalid session file: {path}") from exc

    def list_sessions(self) -> list[AgentSession]:
        if not self.sessions_dir.is_dir():
            return []
        sessions = []
        for path in sorted(self.sessions_dir.glob("*/session.json")):
            sessions.append(self.load(path.parent.name))
        return sessions
