from __future__ import annotations

from .common import StrictBaseModel


class RepositoryIdentity(StrictBaseModel):
    path: str
    commit_sha: str | None = None
    workspace_hash: str | None = None
    analyzed_at: str | None = None
    analyzer_version: str | None = None
    rules_version: str | None = None
