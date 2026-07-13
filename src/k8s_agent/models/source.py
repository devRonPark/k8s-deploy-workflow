from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ScanLimits(BaseModel):
    max_file_bytes: int = 1_000_000


class SourceFingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    algorithm: str = "sha256"
    file_count: int
    included_files: list[str] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GitMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_repository: bool
    branch: str | None = None
    head: str | None = None
    dirty: bool | None = None
    modified_files: list[str] = Field(default_factory=list)
    untracked_files: list[str] = Field(default_factory=list)


class RepositorySource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    path: Path
    acquired_at: datetime
    git: GitMetadata
    fingerprint: SourceFingerprint
