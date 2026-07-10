from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceFact:
    evidence_id: str
    fact_type: str
    artifact_ref: str
    source: str
    classification: str
    value: Any

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceModel:
    facts: list[EvidenceFact] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def facts_by_type(self, fact_type: str) -> list[EvidenceFact]:
        return [fact for fact in self.facts if fact.fact_type == fact_type]

    def model_dump(self) -> dict:
        return asdict(self)
