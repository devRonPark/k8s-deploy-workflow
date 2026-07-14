from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReportSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    value: str
    fingerprint: str | None = None


class ReportValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "not-run"
    manifest_ready: bool = False
    finding_count: int = 0


class ReportResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    name: str
    path: str | None = None


class FinalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "final-report/v1"
    run_id: str
    state: str
    target: str
    source: ReportSource
    summary: str
    validation: ReportValidation = Field(default_factory=ReportValidation)
    resources: list[ReportResource] = Field(default_factory=list)
    decision_count: int = 0
    limitations: list[str] = Field(default_factory=list)
    next_action: str


class ExplanationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str | None = None
    decision_id: str | None = None
    profile_field: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    resources: list[ReportResource] = Field(default_factory=list)
    trace: str


class ExportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    output: str
    file_count: int
