from __future__ import annotations
from pydantic import BaseModel, Field


class StageResult(BaseModel):
    stage: str
    status: str  # pass | fail | skipped | not_run
    detail: str | None = None


class ValidationReport(BaseModel):
    target_level: int
    achieved_level: int
    stages: list[StageResult] = Field(default_factory=list)
