from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from k8s_agent.versions import RUN_SCHEMA_VERSION


class RunState(StrEnum):
    CREATED = "CREATED"
    ACQUIRING_SOURCE = "ACQUIRING_SOURCE"
    ANALYZING = "ANALYZING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    READY = "READY"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = frozenset(
    {
        RunState.READY,
        RunState.BLOCKED,
        RunState.FAILED,
        RunState.CANCELLED,
    }
)


class RunSource(BaseModel):
    kind: str
    value: str
    ref: str | None = None


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = RUN_SCHEMA_VERSION
    run_id: str
    run_root: Path
    state: RunState
    target: str
    source: RunSource
    created_at: datetime
    updated_at: datetime
    last_successful_state: RunState


class RunEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    run_id: str
    event_type: str
    created_at: datetime
    summary: str
    details: dict[str, str] = Field(default_factory=dict)
