from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class RepositorySnapshot:
    url: str | None
    ref: str | None
    commit_sha: str | None
    analyzed_at: str
    archived: bool
    default_branch: str | None
    analyzer_version: str
    rules_version: str
    file_count: int
    excluded_patterns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def model_dump(self) -> dict:
        return asdict(self)
