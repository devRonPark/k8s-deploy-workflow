from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator


class SemanticToolName(str, Enum):
    SEARCH_CODE = "search_code"
    READ_SOURCE_RANGE = "read_source_range"
    INSPECT_ENTRYPOINT_SCRIPT = "inspect_entrypoint_script"
    FIND_COMMAND_TARGET = "find_command_target"


class SemanticToolResultStatus(str, Enum):
    OK = "ok"
    NO_MATCH = "no_match"
    BLOCKED = "blocked"
    INVALID_INPUT = "invalid_input"
    NOT_FOUND = "not_found"
    UNSUPPORTED = "unsupported"
    ERROR = "error"
    BUDGET_EXHAUSTED = "budget_exhausted"


class _SemanticToolBase(BaseModel):
    model_config = ConfigDict(frozen=True, use_enum_values=True)


class SemanticToolEvidence(_SemanticToolBase):
    evidence_id: str
    tool_name: SemanticToolName
    path: str
    start_line: PositiveInt
    end_line: PositiveInt
    excerpt: str
    excerpt_hash: str

    @field_validator("evidence_id", "path", "excerpt", "excerpt_hash")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value

    @model_validator(mode="after")
    def _line_range_is_ordered(self) -> SemanticToolEvidence:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class SemanticToolUsage(_SemanticToolBase):
    files_read: int = 0
    source_lines_returned: int = 0
    matches_examined: int = 0
    truncated: bool = False


class SemanticToolResult(_SemanticToolBase):
    tool_name: SemanticToolName
    status: SemanticToolResultStatus
    evidence: list[SemanticToolEvidence] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    usage: SemanticToolUsage = Field(default_factory=SemanticToolUsage)
    message: str | None = None


class SearchCodeInput(_SemanticToolBase):
    query: str
    path_prefix: str | None = None
    max_matches: int = 10
    context_lines: int = 1
    case_sensitive: bool = True

    @field_validator("query")
    @classmethod
    def _query_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("query must not be empty")
        return value


class ReadSourceRangeInput(_SemanticToolBase):
    path: str
    start_line: PositiveInt
    end_line: PositiveInt

    @field_validator("path")
    @classmethod
    def _path_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("path must not be empty")
        return value

    @model_validator(mode="after")
    def _line_range_is_ordered(self) -> ReadSourceRangeInput:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class InspectEntrypointScriptInput(_SemanticToolBase):
    path: str
    max_candidates: int = 10

    @field_validator("path")
    @classmethod
    def _path_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("path must not be empty")
        return value


class FindCommandTargetInput(_SemanticToolBase):
    command: str
    max_results: int = 10

    @field_validator("command")
    @classmethod
    def _command_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("command must not be empty")
        return value
