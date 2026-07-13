from __future__ import annotations
from typing import Any

from pydantic import BaseModel, Field


class StageResult(BaseModel):
    stage: str
    status: str  # pass | fail | skipped | not_run
    detail: str | None = None


class GenerationHoldCandidate(BaseModel):
    value: Any | None = None
    source: str | None = None
    confidence: str | None = None
    classification: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class GenerationHoldReason(BaseModel):
    code: str
    detail: str | None = None
    missing_field: str | None = None
    candidates: list[GenerationHoldCandidate] = Field(default_factory=list)


class GenerationHoldResource(BaseModel):
    kind: str
    name: str | None = None
    intended_path: str | None = None


class GenerationHoldResolution(BaseModel):
    status: str = "unresolved"
    profile_field: str | None = None
    question_id: str | None = None


class GenerationHold(BaseModel):
    component_id: str
    resource: GenerationHoldResource
    reason: GenerationHoldReason
    resolution: GenerationHoldResolution | None = None
    status: str = "generation_held"
    display_status: str = "생성 보류"


class ValidationReport(BaseModel):
    target_level: int
    achieved_level: int
    stages: list[StageResult] = Field(default_factory=list)
    generation_holds: list[GenerationHold] = Field(default_factory=list)
