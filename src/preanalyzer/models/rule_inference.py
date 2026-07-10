from __future__ import annotations

from dataclasses import field

from pydantic import BaseModel, Field, TypeAdapter
from pydantic.dataclasses import dataclass


def _dump(instance: object) -> dict:
    return TypeAdapter(type(instance)).dump_python(instance)


@dataclass(frozen=True)
class ComponentCandidate:
    component_id: str
    root_path: str | None
    source: str
    evidence_refs: list[str]
    classification: str = "rule_inference"

    def model_dump(self) -> dict:
        return _dump(self)


@dataclass(frozen=True)
class RoleCandidate:
    component_id: str
    role: str
    source: str
    confidence: str
    evidence_refs: list[str]
    classification: str = "rule_inference"

    def model_dump(self) -> dict:
        return _dump(self)


@dataclass(frozen=True)
class RuntimeCandidate:
    component_id: str
    language: str
    framework: str | None
    build_tool: str
    build_strategy: str
    source: str
    confidence: str
    evidence_refs: list[str]
    classification: str = "rule_inference"

    def model_dump(self) -> dict:
        return _dump(self)


@dataclass(frozen=True)
class RuntimeVersionCandidate:
    component_id: str
    language: str
    version: str
    source: str
    confidence: str
    evidence_refs: list[str]
    classification: str = "rule_inference"

    def model_dump(self) -> dict:
        return _dump(self)


@dataclass(frozen=True)
class RuntimePortCandidate:
    component_id: str
    port: int
    source: str
    confidence: str
    evidence_refs: list[str]
    classification: str = "rule_inference"

    def model_dump(self) -> dict:
        return _dump(self)


@dataclass(frozen=True)
class RuntimeCommandCandidate:
    component_id: str
    command: str
    source: str
    confidence: str
    evidence_refs: list[str]
    classification: str = "rule_inference"

    def model_dump(self) -> dict:
        return _dump(self)


@dataclass(frozen=True)
class DependencyEdgeCandidate:
    source_component: str
    target: str
    dependency_type: str
    source: str
    confidence: str
    evidence_refs: list[str]
    classification: str = "rule_inference"

    def model_dump(self) -> dict:
        return _dump(self)


@dataclass(frozen=True)
class SecretCandidate:
    component_id: str
    name: str
    source: str
    evidence_refs: list[str]
    classification: str = "rule_inference"

    def model_dump(self) -> dict:
        return _dump(self)


@dataclass(frozen=True)
class EnvClassification:
    secret_candidates: list[SecretCandidate] = field(default_factory=list)

    def model_dump(self) -> dict:
        return _dump(self)


class RuleInferenceSet(BaseModel):
    component_candidates: list[ComponentCandidate] = Field(default_factory=list)
    role_candidates: list[RoleCandidate] = Field(default_factory=list)
    runtime_candidates: list[RuntimeCandidate] = Field(default_factory=list)
    runtime_version_candidates: list[RuntimeVersionCandidate] = Field(default_factory=list)
    runtime_port_candidates: list[RuntimePortCandidate] = Field(default_factory=list)
    runtime_command_candidates: list[RuntimeCommandCandidate] = Field(default_factory=list)
    dependency_edge_candidates: list[DependencyEdgeCandidate] = Field(default_factory=list)
    env_classification: EnvClassification = Field(default_factory=EnvClassification)
