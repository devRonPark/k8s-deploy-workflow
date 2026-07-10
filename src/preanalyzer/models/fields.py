from __future__ import annotations

from dataclasses import field
from enum import Enum
from typing import Any

from pydantic import ConfigDict, TypeAdapter
from pydantic.dataclasses import dataclass


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass(frozen=True, config=ConfigDict(use_enum_values=True))
class Tracked:
    value: Any = None
    source: str | None = None
    confidence: Confidence = Confidence.NONE
    evidence_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.value is not None and (self.source is None or self.confidence == Confidence.NONE):
            raise ValueError("tracked values require source and non-none confidence")

    def model_dump(self) -> dict:
        return TypeAdapter(type(self)).dump_python(self)
