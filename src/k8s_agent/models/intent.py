from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    disposition: str
    reason_code: str
    policy_version: str


class IntentCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    component_id: str
    kind: str
    field_path: str
    value: Any
    source: str
    confidence: str
    classification: str
    evidence_refs: list[str] = Field(default_factory=list)
    policy_version: str = "target-policy/v1"
    decision: PolicyDecision | None = None


class KubernetesIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "kubernetes-intent/v1"
    target: str
    candidates: list[IntentCandidate] = Field(default_factory=list)
