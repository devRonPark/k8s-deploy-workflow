from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FieldState(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    CONFLICT = "conflict"
    NOT_APPLICABLE = "not_applicable"


def _candidate_observed_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def normalized_values(values: list[Any]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        normalized.append(json.dumps(value, sort_keys=True, default=str))
    return normalized


def has_at_least_two_distinct_values(values: list[Any]) -> bool:
    normalized = normalized_values([_candidate_observed_value(value) for value in values])
    return len(set(normalized)) >= 2


def validate_conflict_candidates(candidates: list[Any]) -> None:
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("conflict candidates require value, source, confidence, classification, and evidence_refs")
        missing = []
        if "value" not in candidate or candidate["value"] is None:
            missing.append("value")
        for key in ("source", "confidence", "classification"):
            if not candidate.get(key):
                missing.append(key)
        if not candidate.get("evidence_refs"):
            missing.append("evidence_refs")
        if missing:
            raise ValueError(f"conflict candidate is missing metadata: {', '.join(missing)}")


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TrackedValue(StrictBaseModel):
    state: FieldState
    value: Any | None = None
    source: str | None = None
    confidence: str | None = None
    classification: str | None = None
    candidates: list[Any] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str | None = None
    reason_code: str | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def validate_state_payload(self) -> "TrackedValue":
        if self.state == FieldState.RESOLVED:
            if self.value is None:
                raise ValueError("resolved tracked values require a value")
            if not self.source or not self.confidence or not self.classification or not self.evidence_refs:
                raise ValueError(
                    "resolved tracked values require source, confidence, classification, and evidence_refs"
                )
        elif self.state == FieldState.CONFLICT:
            if self.value is not None:
                raise ValueError("conflict tracked values cannot carry an effective value")
            validate_conflict_candidates(self.candidates)
            if not has_at_least_two_distinct_values(self.candidates):
                raise ValueError("conflict tracked values require at least two distinct candidates")
            if not self.evidence_refs:
                raise ValueError("conflict tracked values require evidence_refs")
        elif self.state in {FieldState.UNRESOLVED, FieldState.NOT_APPLICABLE}:
            if not self.reason:
                raise ValueError(f"{self.state.value} tracked values require a reason")
        return self
