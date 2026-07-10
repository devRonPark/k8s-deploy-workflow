from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from preanalyzer.models.semantic import SemanticResolution, VerificationResult


class _SemanticAgentBaseModel(BaseModel):
    model_config = ConfigDict(frozen=True, use_enum_values=True)


class ToolCallAction(_SemanticAgentBaseModel):
    action_type: Literal["tool_call"] = "tool_call"
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason_code: str = "unspecified"

    @field_validator("tool_name", "reason_code")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value

    @field_validator("arguments")
    @classmethod
    def _single_tool_call_only(cls, value: dict[str, Any]) -> dict[str, Any]:
        if "tool_calls" in value or "parallel_tool_calls" in value:
            raise ValueError("tool call actions must contain exactly one tool")
        return value


class ResolutionAction(_SemanticAgentBaseModel):
    action_type: Literal["resolution"] = "resolution"
    resolution: SemanticResolution


AgentAction = ToolCallAction | ResolutionAction


class SemanticDecisionContext(_SemanticAgentBaseModel):
    task_id: str
    task_type: str
    component_id: str
    target_field: str
    reason: dict[str, Any]
    known_candidates: list[dict[str, Any]] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
    collected_evidence: list[dict[str, Any]] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    remaining_budget: dict[str, int] = Field(default_factory=dict)

    @field_validator("task_id", "task_type", "component_id", "target_field")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value


class SemanticToolCallRecord(_SemanticAgentBaseModel):
    tool_call_id: str
    turn_index: int
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_status: str
    evidence_refs: list[str] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tool_call_id", "tool_name", "result_status")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value

    @model_validator(mode="after")
    def _turn_index_is_positive(self) -> SemanticToolCallRecord:
        if self.turn_index < 1:
            raise ValueError("turn_index must be positive")
        return self


class SemanticAgentRunStatus(str, Enum):
    COMPLETED = "completed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TOOL_ERROR = "tool_error"
    PROVIDER_ERROR = "provider_error"
    INVALID_ACTION = "invalid_action"
    VERIFICATION_REJECTED = "verification_rejected"


class SemanticAgentRunResult(_SemanticAgentBaseModel):
    task_id: str
    status: SemanticAgentRunStatus
    resolution: SemanticResolution | None = None
    verification_result: VerificationResult | None = None
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    tool_call_records: list[SemanticToolCallRecord] = Field(default_factory=list)
    turn_count: int = 0
    tool_call_count: int = 0
    distinct_tools_used: int = 0
    files_read: int = 0
    source_lines_returned: int = 0
    messages: list[str] = Field(default_factory=list)

    @field_validator("task_id")
    @classmethod
    def _task_id_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("task_id must not be empty")
        return value


def deterministic_tool_call_id(task_id: str, turn_index: int, tool_name: str, arguments: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "task_id": task_id,
            "turn_index": turn_index,
            "tool_name": tool_name,
            "arguments": arguments,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12].upper()
    return f"TC-{digest}"
