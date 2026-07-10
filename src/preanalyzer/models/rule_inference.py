from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class ComponentCandidate:
    component_id: str
    root_path: str | None
    source: str
    evidence_refs: list[str]

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RoleCandidate:
    component_id: str
    role: str
    source: str
    confidence: str
    evidence_refs: list[str]

    def model_dump(self) -> dict:
        return asdict(self)


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

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SecretCandidate:
    component_id: str
    name: str
    source: str
    evidence_refs: list[str]

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EnvClassification:
    secret_candidates: list[SecretCandidate] = field(default_factory=list)

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RuleInferenceSet:
    component_candidates: list[ComponentCandidate] = field(default_factory=list)
    role_candidates: list[RoleCandidate] = field(default_factory=list)
    runtime_candidates: list[RuntimeCandidate] = field(default_factory=list)
    env_classification: EnvClassification = field(default_factory=EnvClassification)

    def model_dump(self) -> dict:
        return asdict(self)
