from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Generic, TypeVar


T = TypeVar("T")


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass(frozen=True)
class Tracked(Generic[T]):
    value: T | None = None
    source: str | None = None
    confidence: Confidence = Confidence.NONE
    evidence_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.value is not None and (self.source is None or self.confidence is Confidence.NONE):
            raise ValueError("tracked values require source and non-none confidence")

    def model_dump(self) -> dict:
        dumped = asdict(self)
        dumped["confidence"] = self.confidence.value
        return dumped
