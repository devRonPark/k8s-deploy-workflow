from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProfileValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any
    decision_id: str
    classification: str
    confidence: str
    evidence_refs: list[str] = Field(default_factory=list)
    actor: str
    approval: str


class ProfileConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_field: str
    selected_decision_id: str
    conflicting_decision_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ProfileHold(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_field: str
    reason_code: str
    evidence_refs: list[str] = Field(default_factory=list)


class DeploymentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "deployment-profile/v1"
    revision: int
    values: dict[str, ProfileValue] = Field(default_factory=dict)
    conflicts: list[ProfileConflict] = Field(default_factory=list)
    unresolved: list[ProfileHold] = Field(default_factory=list)
    blocked: list[ProfileHold] = Field(default_factory=list)
    renderable: bool = True

    def checksum(self) -> str:
        payload = self.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
