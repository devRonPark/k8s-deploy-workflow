from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


FieldState = Literal["resolved", "unresolved", "conflict", "not_applicable"]
FieldGroup = Literal["core", "extended"]
CoverageStatus = Literal["analyzed", "absent", "coverage_gap"]
TopologyClassification = Literal[
    "observed_fact",
    "rule_inference",
    "llm_interpretation",
    "user_decision",
]


class EvidenceLinkedValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any
    source: str
    confidence: str | None = None
    classification: str
    evidence_refs: list[str] = Field(default_factory=list)


class RepositoryModule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str = Field(min_length=1)
    root_path: str = Field(min_length=1)
    build_system: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    package_dependencies: list[EvidenceLinkedValue] = Field(default_factory=list)


class DeploymentVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class AnalysisCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_ref: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    status: CoverageStatus
    evidence_refs: list[str] = Field(default_factory=list)
    field_paths: list[str] = Field(default_factory=list)
    limitation: str | None = None


class TopologyField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str
    group: FieldGroup
    variant_id: str = "common"
    state: FieldState
    value: Any | None = None
    source: str | None = None
    confidence: str | None = None
    classification: TopologyClassification | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    candidates: list[EvidenceLinkedValue] = Field(default_factory=list)
    reason: str | None = None

    @model_validator(mode="after")
    def validate_state_payload(self) -> "TopologyField":
        if self.state == "resolved":
            if (
                self.value is None
                or self.source is None
                or self.confidence is None
                or self.classification is None
                or not self.evidence_refs
            ):
                raise ValueError(
                    "resolved topology fields require value, source, confidence, "
                    "classification, and evidence_refs"
                )
        elif self.state == "conflict":
            if not self.candidates:
                raise ValueError("conflict topology fields require candidates")
        elif self.state == "unresolved":
            if not self.reason:
                raise ValueError("unresolved topology fields require reason")
        elif self.state == "not_applicable":
            if not self.reason:
                raise ValueError("not_applicable topology fields require reason")
        return self


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
    fields: list[TopologyField] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class ApplicationTopology(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "application-topology/v2"
    rules_version: str | None = None
    repository_modules: list[RepositoryModule] = Field(default_factory=list)
    deployment_variants: list[DeploymentVariant] = Field(default_factory=list)
    analysis_coverage: list[AnalysisCoverage] = Field(default_factory=list)
    components: list[ApplicationComponent] = Field(default_factory=list)
    conflicts: list[TopologyConflict] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)

    def component(self, component_id: str) -> ApplicationComponent:
        for component in self.components:
            if component.component_id == component_id:
                return component
        raise KeyError(component_id)
