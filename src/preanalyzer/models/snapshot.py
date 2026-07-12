"""Repository Snapshot 계약 (Step 0 산출물, commit SHA·메타데이터)."""

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
    # "commit": inputs come from the extracted commit tree, so a given commit
    # reproduces byte-identical output regardless of working-tree state.
    # "workspace": inputs come from the working tree as-is; ``workspace_hash``
    # is the reproducibility key.
    snapshot_mode: str = "workspace"
    # Content hash of the exact set of analyzed files (sha256:...). Stable for
    # identical inputs and independent of filesystem traversal order.
    workspace_hash: str | None = None
    # Workspace-mode git state. ``None`` when the analyzed root is not a git
    # worktree top-level (e.g. commit mode, or a nested subdirectory).
    workspace_dirty: bool | None = None
    modified_files: list[str] = Field(default_factory=list)
    untracked_files: list[str] = Field(default_factory=list)
    excluded_patterns: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
