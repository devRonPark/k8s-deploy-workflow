from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RepositorySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str | None
    ref: str | None
    commit_sha: str | None
    analyzed_at: str
    archived: bool
    default_branch: str | None
    analyzer_version: str
    rules_version: str
    file_count: int
    excluded_patterns: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
