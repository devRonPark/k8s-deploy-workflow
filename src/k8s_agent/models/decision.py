from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    question_id: str | None = None
    target_field: str
    value: Any
    raw_value: Any
    normalized_value: Any
    classification: str
    confidence: str
    evidence_refs: list[str] = Field(default_factory=list)
    actor: str
    alternatives: list[Any] = Field(default_factory=list)
    approval: str
    affected_resources: list[str] = Field(default_factory=list)
