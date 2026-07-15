from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from .common import StrictBaseModel, has_at_least_two_distinct_values
from .lifecycle import LifecycleModel
from .repository import RepositoryIdentity
from .topology import ApplicationTopology


class EvidenceRef(StrictBaseModel):
    evidence_id: str
    artifact_ref: str
    fact_type: str
    source: str
    classification: str


class ConfirmedFact(StrictBaseModel):
    fact_id: str
    field_path: str
    value: Any
    source: str
    confidence: str
    classification: str
    evidence_refs: list[str]

    @field_validator("evidence_refs")
    @classmethod
    def require_evidence(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("confirmed facts require evidence_refs")
        return value


class UnknownFinding(StrictBaseModel):
    field_path: str
    reason: str
    evidence_refs: list[str] = Field(default_factory=list)


class ConflictFinding(StrictBaseModel):
    field_path: str
    candidates: list[Any]
    evidence_refs: list[str]
    reason: str

    @model_validator(mode="after")
    def validate_conflict(self) -> "ConflictFinding":
        if not has_at_least_two_distinct_values(self.candidates):
            raise ValueError("conflicts require at least two distinct candidates")
        if not self.evidence_refs:
            raise ValueError("conflicts require evidence_refs")
        return self


class UnderstandingCoverage(StrictBaseModel):
    analyzed_artifacts: int
    supported_artifacts: int
    unsupported_artifacts: list[str] = Field(default_factory=list)


class RepositoryUnderstanding(StrictBaseModel):
    schema_version: str
    repository: RepositoryIdentity
    topology: ApplicationTopology
    lifecycle: LifecycleModel
    confirmed_facts: list[ConfirmedFact] = Field(default_factory=list)
    unknowns: list[UnknownFinding] = Field(default_factory=list)
    conflicts: list[ConflictFinding] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    coverage: UnderstandingCoverage

    @model_validator(mode="after")
    def validate_evidence_links(self) -> "RepositoryUnderstanding":
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence IDs must be unique")

        known = set(evidence_ids)
        for fact in self.confirmed_facts:
            missing = sorted(set(fact.evidence_refs) - known)
            if missing:
                raise ValueError(f"confirmed fact references unknown evidence: {missing}")

        for conflict in self.conflicts:
            missing = sorted(set(conflict.evidence_refs) - known)
            if missing:
                raise ValueError(f"conflict references unknown evidence: {missing}")

        for unknown in self.unknowns:
            missing = sorted(set(unknown.evidence_refs) - known)
            if missing:
                raise ValueError(f"unknown references unknown evidence: {missing}")

        return self
