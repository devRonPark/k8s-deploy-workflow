from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceLinkedValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any
    source: str
    confidence: str | None = None
    classification: str
    evidence_refs: list[str] = Field(default_factory=list)


class RuntimeInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str
    framework: str | None = None
    build_tool: str
    build_strategy: str
    source: str
    confidence: str
    classification: str
    evidence_refs: list[str] = Field(default_factory=list)


class DependencyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str
    dependency_type: str
    source: str
    confidence: str
    classification: str
    evidence_refs: list[str] = Field(default_factory=list)


class SecretUse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: str
    classification: str
    evidence_refs: list[str] = Field(default_factory=list)


class TopologyConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str
    reason: str
    candidates: list[EvidenceLinkedValue] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ApplicationComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str
    root_path: str | None = None
    role: str = "application"
    evidence_refs: list[str] = Field(default_factory=list)
    runtime: RuntimeInfo | None = None
    command: EvidenceLinkedValue | None = None
    ports: list[EvidenceLinkedValue] = Field(default_factory=list)
    secrets: list[SecretUse] = Field(default_factory=list)
    dependencies: list[DependencyEdge] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class ApplicationTopology(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "application-topology/v1"
    components: list[ApplicationComponent] = Field(default_factory=list)
    conflicts: list[TopologyConflict] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)

    def component(self, component_id: str) -> ApplicationComponent:
        for component in self.components:
            if component.component_id == component_id:
                return component
        raise KeyError(component_id)
