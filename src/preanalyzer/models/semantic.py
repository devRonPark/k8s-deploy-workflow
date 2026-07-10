from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator

from preanalyzer.models.fields import Confidence


class SemanticTaskType(str, Enum):
    RESOLVE_RUNTIME_COMMAND = "resolve_runtime_command"
    RESOLVE_RUNTIME_PORT = "resolve_runtime_port"
    RESOLVE_COMPONENT_ROLE = "resolve_component_role"
    RESOLVE_DEPENDENCY_EDGE = "resolve_dependency_edge"


class SemanticResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TOOL_ERROR = "tool_error"


class VerificationStatus(str, Enum):
    ACCEPTED = "accepted"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    REJECTED = "rejected"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TOOL_ERROR = "tool_error"


class _SemanticBaseModel(BaseModel):
    model_config = ConfigDict(frozen=True, use_enum_values=True)


class TaskReason(_SemanticBaseModel):
    code: str
    description: str
    evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("code", "description")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value


class EvidenceReference(_SemanticBaseModel):
    evidence_id: str
    origin: Literal["phase1", "semantic_tool"]
    path: str | None = None
    start_line: PositiveInt | None = None
    end_line: PositiveInt | None = None

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence_id must not be empty")
        return value

    @model_validator(mode="after")
    def _line_range_complete_and_ordered(self) -> EvidenceReference:
        has_start = self.start_line is not None
        has_end = self.end_line is not None
        if has_start != has_end:
            raise ValueError("start_line and end_line must be provided together")
        if self.start_line is not None and self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class KnownCandidate(_SemanticBaseModel):
    value: Any
    source: str
    confidence: Confidence
    classification: str
    evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("source", "classification")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value


class SemanticTaskBudget(_SemanticBaseModel):
    max_agent_turns: PositiveInt = 4
    max_tool_calls: PositiveInt = 4
    max_distinct_tools: PositiveInt = 3
    max_files_read: PositiveInt = 5
    max_source_lines: PositiveInt = 400
    max_schema_retries: PositiveInt = 1


class SemanticTask(_SemanticBaseModel):
    task_id: str
    task_type: SemanticTaskType
    component_id: str
    target_field: str
    reason: TaskReason
    known_candidates: list[KnownCandidate] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    budget: SemanticTaskBudget = Field(default_factory=SemanticTaskBudget)

    @field_validator("task_id", "component_id", "target_field")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value

    @field_validator("allowed_tools")
    @classmethod
    def _allowed_tools_unique_and_non_empty(cls, value: list[str]) -> list[str]:
        if any(not tool.strip() for tool in value):
            raise ValueError("allowed_tools must not contain empty names")
        if len(set(value)) != len(value):
            raise ValueError("allowed_tools must be unique")
        return value


SemanticConfidence = Literal["low", "medium"]


class SemanticCandidate(_SemanticBaseModel):
    candidate_id: str
    component_id: str
    target_field: str
    value: Any
    classification: Literal["llm_semantic_inference"]
    confidence: SemanticConfidence
    evidence_refs: list[str] = Field(default_factory=list)
    supporting_observations: list[str] = Field(default_factory=list)
    contradicting_observations: list[str] = Field(default_factory=list)

    @field_validator("candidate_id", "component_id", "target_field")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value


class SemanticResolution(_SemanticBaseModel):
    task_id: str
    status: SemanticResolutionStatus
    candidates: list[SemanticCandidate] = Field(default_factory=list)
    recommended_candidate_id: str | None = None
    analysis_summary: str | None = None
    tool_trace_refs: list[str] = Field(default_factory=list)

    @field_validator("task_id")
    @classmethod
    def _task_id_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("task_id must not be empty")
        return value

    @model_validator(mode="after")
    def _resolution_shape_is_consistent(self) -> SemanticResolution:
        if self.status == SemanticResolutionStatus.RESOLVED.value and not self.candidates:
            raise ValueError("resolved resolution requires at least one candidate")

        candidate_ids = {candidate.candidate_id for candidate in self.candidates}
        if self.recommended_candidate_id is not None and self.recommended_candidate_id not in candidate_ids:
            raise ValueError("recommended_candidate_id must refer to an existing candidate")

        unresolved_statuses = {
            SemanticResolutionStatus.INSUFFICIENT_EVIDENCE.value,
            SemanticResolutionStatus.BUDGET_EXHAUSTED.value,
            SemanticResolutionStatus.TOOL_ERROR.value,
        }
        if self.status in unresolved_statuses and self.recommended_candidate_id is not None:
            raise ValueError("unresolved resolutions must not recommend a candidate")
        return self


class VerificationResult(_SemanticBaseModel):
    task_id: str
    status: VerificationStatus
    accepted_candidate_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

    @field_validator("task_id")
    @classmethod
    def _task_id_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("task_id must not be empty")
        return value
