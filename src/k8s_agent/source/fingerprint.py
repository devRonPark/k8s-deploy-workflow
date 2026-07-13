from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path

from k8s_agent.models.source import ScanLimits, SourceFingerprint
from preanalyzer.path_safety import (
    is_excluded_rel_path,
    is_sensitive_rel_path,
    iter_repository_files,
    resolve_repository_path,
)


AGENT_STATE_PATTERNS = (".k8s-agent/**", "**/.k8s-agent/**")


def build_source_fingerprint(root: Path, limits: ScanLimits) -> SourceFingerprint:
    resolved = resolve_repository_path(root)
    files, safety_warnings = iter_repository_files(resolved)
    digest = hashlib.sha256()
    included: list[str] = []
    excluded: set[str] = set()
    warnings = set(safety_warnings)

    for path in files:
        rel = path.relative_to(resolved).as_posix()
        if _is_agent_excluded(rel) or is_excluded_rel_path(rel) or is_sensitive_rel_path(rel):
            excluded.add(rel)
            continue
        try:
            size = path.stat().st_size
        except OSError:
            warnings.add(f"skipped unreadable path: {rel}")
            continue
        if size > limits.max_file_bytes:
            excluded.add(rel)
            warnings.add(f"skipped oversized file: {rel}")
            continue
        try:
            data = path.read_bytes()
        except OSError:
            warnings.add(f"skipped unreadable path: {rel}")
            continue
        if b"\0" in data:
            excluded.add(rel)
            warnings.add(f"skipped binary file: {rel}")
            continue
        included.append(rel)
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
        digest.update(b"\n")

    return SourceFingerprint(
        value=f"sha256:{digest.hexdigest()}",
        file_count=len(included),
        included_files=sorted(included),
        excluded_paths=sorted(excluded),
        warnings=sorted(warnings),
    )


def _is_agent_excluded(rel: str) -> bool:
    return any(fnmatch.fnmatch(rel, pattern) for pattern in AGENT_STATE_PATTERNS)
