"""Shared path-safety utilities.

Scanner (Phase 1) and the semantic tool layer must enforce the same
repository-boundary and sensitive-file rules. This module is the single source
of truth for those checks. It deliberately imports nothing from the analyzer or
semantic packages so it can be a dependency of both without a cycle.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path, PurePosixPath
import fnmatch
import os


REPO_EXCLUDED_GLOBS = [
    ".git/**",
    "**/.git/**",
    "node_modules/**",
    "**/node_modules/**",
    "**/*.png",
    "**/*.jpg",
    "**/*.jpeg",
    "**/*.gif",
]

EXCLUDED_DIR_NAMES = {
    ".git",
    "node_modules",
    "vendor",
    "target",
    "dist",
    "build",
    "__pycache__",
    ".venv",
    "venv",
    "coverage",
    ".cache",
}

SENSITIVE_FILE_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
    "credentials*",
    "secret*",
    "secrets*",
)


def resolve_repository_path(repo: Path | str) -> Path:
    """Return the canonical (symlink-resolved) repository root path."""
    return Path(repo).resolve()


def is_within(path: Path, root: Path) -> bool:
    """Return True if ``path`` is lexically contained in ``root``.

    Both arguments are expected to already be resolved when a symlink-safe
    decision is required.
    """
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def is_excluded_rel_path(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    if any(part in EXCLUDED_DIR_NAMES for part in parts):
        return True
    return any(fnmatch.fnmatch(rel, pattern) for pattern in REPO_EXCLUDED_GLOBS)


def is_sensitive_rel_path(rel: str) -> bool:
    name = PurePosixPath(rel).name
    return any(fnmatch.fnmatch(name, pattern) for pattern in SENSITIVE_FILE_PATTERNS)


def iter_repository_files(repo_root: Path) -> tuple[list[Path], list[str]]:
    """Walk ``repo_root`` returning only files that stay inside the repository.

    Symlink policy:
      * symlink directories are not descended into (``os.walk`` followlinks=False),
      * symlinks whose real target escapes the repository are skipped,
      * broken symlinks are skipped,
      * symlinks that resolve to a file inside the repository are allowed.

    Returns ``(files, warnings)`` where ``files`` is sorted by repository-relative
    POSIX path and ``warnings`` is a sorted, de-duplicated list of skip reasons.
    Warnings reference only the in-repository link path, never the external
    target, to avoid leaking paths outside the repository.
    """
    root = resolve_repository_path(repo_root)
    files: list[Path] = []
    warnings: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            candidate = Path(dirpath) / name
            rel = candidate.relative_to(root).as_posix()
            try:
                real = candidate.resolve()
            except OSError:
                warnings.add(f"skipped unreadable path: {rel}")
                continue
            if not real.exists():
                warnings.add(f"skipped broken symlink: {rel}")
                continue
            if not is_within(real, root):
                warnings.add(f"skipped symlink escaping repository: {rel}")
                continue
            if not real.is_file():
                continue
            files.append(candidate)

    files.sort(key=lambda p: p.relative_to(root).as_posix())
    return files, sorted(warnings)


def repository_files(repo_root: Path) -> Iterable[Path]:
    """Convenience iterator over :func:`iter_repository_files` files only."""
    files, _ = iter_repository_files(repo_root)
    return files
