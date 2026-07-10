from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RuntimeCommandResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    REQUIRES_SOURCE_ANALYSIS = "requires_source_analysis"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INVALID_REFERENCE = "invalid_reference"
    CYCLE_DETECTED = "cycle_detected"


class RuntimeCommandGapReason(str, Enum):
    SHELL_SCRIPT_ENTRYPOINT = "shell_script_entrypoint"
    COMPOUND_SHELL_COMMAND = "compound_shell_command"
    UNRESOLVED_PACKAGE_SCRIPT = "unresolved_package_script"
    PACKAGE_SCRIPT_CYCLE = "package_script_cycle"
    CONFLICTING_EXPLICIT_COMMANDS = "conflicting_explicit_commands"
    UNSUPPORTED_COMMAND_FORM = "unsupported_command_form"
    MISSING_RUNTIME_COMMAND = "missing_runtime_command"


class _RuntimeCommandAnalysisBase(BaseModel):
    model_config = ConfigDict(frozen=True, use_enum_values=True)


class ResolvedRuntimeCommand(_RuntimeCommandAnalysisBase):
    component_id: str
    command: str
    source: str
    confidence: Literal["low", "medium", "high"]
    evidence_refs: list[str] = Field(default_factory=list)
    resolution_method: str
    classification: Literal["deterministic_runtime_command_analysis"] = "deterministic_runtime_command_analysis"

    @field_validator("component_id", "command", "source", "resolution_method")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value


class RuntimeCommandAlternative(_RuntimeCommandAnalysisBase):
    command: str
    source: str
    confidence: Literal["low", "medium", "high"]
    classification: str
    evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("command", "source", "classification")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value


class RuntimeCommandGap(_RuntimeCommandAnalysisBase):
    component_id: str
    status: RuntimeCommandResolutionStatus
    reason_code: RuntimeCommandGapReason
    description: str
    evidence_refs: list[str] = Field(default_factory=list)
    candidate_commands: list[str] = Field(default_factory=list)
    candidate_alternatives: list[RuntimeCommandAlternative] = Field(default_factory=list)

    @field_validator("component_id", "description")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value


class RuntimeCommandAnalysis(_RuntimeCommandAnalysisBase):
    resolved_commands: list[ResolvedRuntimeCommand] = Field(default_factory=list)
    gaps: list[RuntimeCommandGap] = Field(default_factory=list)

    @model_validator(mode="after")
    def _resolved_commands_are_unique_per_component(self) -> RuntimeCommandAnalysis:
        seen: set[tuple[str, str]] = set()
        for command in self.resolved_commands:
            key = (command.component_id, command.command)
            if key in seen:
                raise ValueError("resolved command must not be duplicated for a component")
            seen.add(key)
        return self
