from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from k8s_agent.errors import AgentError
from k8s_agent.models.source import GitMetadata, RepositorySource, ScanLimits
from k8s_agent.source.fingerprint import build_source_fingerprint
from k8s_agent.source.git_runner import GitRunner


READ_ONLY_GIT_ENV = {"GIT_OPTIONAL_LOCKS": "0"}


class LocalSourceResolver:
    def __init__(self, git: GitRunner | None = None, limits: ScanLimits | None = None) -> None:
        self.git = git or GitRunner()
        self.limits = limits or ScanLimits()

    def resolve(self, path: Path, acquired_at: datetime) -> RepositorySource:
        root = path.expanduser().resolve()
        _ensure_readable_directory(root)
        return RepositorySource(
            kind="local",
            path=root,
            acquired_at=acquired_at,
            git=self._git_metadata(root),
            fingerprint=build_source_fingerprint(root, self.limits),
        )

    def _git_metadata(self, root: Path) -> GitMetadata:
        toplevel = self.git.output(root, ["rev-parse", "--show-toplevel"], env=READ_ONLY_GIT_ENV)
        if toplevel is None or Path(toplevel).resolve() != root:
            return GitMetadata(is_repository=False)
        modified, untracked = _workspace_status(root, self.git)
        return GitMetadata(
            is_repository=True,
            branch=self.git.output(root, ["branch", "--show-current"], env=READ_ONLY_GIT_ENV),
            head=self.git.output(root, ["rev-parse", "HEAD"], env=READ_ONLY_GIT_ENV),
            dirty=bool(modified or untracked),
            modified_files=modified,
            untracked_files=untracked,
        )


def _ensure_readable_directory(path: Path) -> None:
    if not path.exists():
        raise AgentError(
            code="SOURCE-101",
            exit_code=2,
            message=f"local source path does not exist: {path}",
            resolution="Pass an existing directory with --local-path.",
            context={"path": str(path)},
        )
    if not path.is_dir():
        raise AgentError(
            code="SOURCE-102",
            exit_code=2,
            message=f"local source path is not a directory: {path}",
            resolution="Pass a repository directory with --local-path.",
            context={"path": str(path)},
        )
    if not os.access(path, os.R_OK | os.X_OK):
        raise AgentError(
            code="SOURCE-103",
            exit_code=2,
            message=f"local source path is not readable: {path}",
            resolution="Grant read access or choose another directory.",
            context={"path": str(path)},
        )


def _workspace_status(root: Path, git: GitRunner) -> tuple[list[str], list[str]]:
    result = git.run(root, ["status", "--porcelain"], env=READ_ONLY_GIT_ENV)
    if result.returncode != 0:
        return [], []
    modified: set[str] = set()
    untracked: set[str] = set()
    for line in result.stdout.splitlines():
        if not line:
            continue
        code = line[:2]
        rel = line[3:].strip().strip('"')
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
        if code == "??":
            untracked.add(rel)
        else:
            modified.add(rel)
    return sorted(modified), sorted(untracked)
