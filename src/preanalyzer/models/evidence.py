"""Evidence Model 계약: 결정론 분석 산출물을 observed_fact로 정규화."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvidenceFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_id: str
    fact_type: str
    artifact_ref: str
    source: str
    classification: str
    value: Any

    @field_validator("classification")
    @classmethod
    def _classification_observed(cls, value: str) -> str:
        if value != "observed_fact":
            raise ValueError("phase-1 evidence facts must be observed_fact")
        return value


class EvidenceModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    facts: list[EvidenceFact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def facts_by_type(self, fact_type: str) -> list[EvidenceFact]:
        return [fact for fact in self.facts if fact.fact_type == fact_type]
