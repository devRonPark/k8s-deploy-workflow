from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ResourceRef(BaseModel):
    kind: str
    name: str
    path: str | None = None


class ValidationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    validator: str
    severity: str
    resource_ref: ResourceRef | None = None
    field_path: str
    code: str
    message: str
    repairable: bool = False


class ValidationStage(BaseModel):
    stage: str
    status: str


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "validation-report/v1"
    status: str
    manifest_ready: bool
    stages: list[ValidationStage] = Field(default_factory=list)
    findings: list[ValidationFinding] = Field(default_factory=list)
