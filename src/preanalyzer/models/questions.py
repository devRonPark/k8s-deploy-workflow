from __future__ import annotations
from pydantic import BaseModel, Field


class UnresolvedQuestion(BaseModel):
    id: str
    field: str
    question: str
    reason: str
    answer_type: str
    candidates: list[str] = Field(default_factory=list)
    blocking_level: str
    profile_field: str | None = None


class UnresolvedQuestions(BaseModel):
    questions: list[UnresolvedQuestion] = Field(default_factory=list)
