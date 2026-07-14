from __future__ import annotations

import re
from pathlib import Path

from k8s_agent.errors import AgentError


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def safe_run_path(base_dir: Path, run_id: str) -> Path:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise AgentError(
            code="RUN-001",
            exit_code=2,
            message=f"invalid run id: {run_id}",
            resolution="Use the run id printed by k8s-agent prepare or listed by status.",
            context={"run_id": run_id},
        )
    base = base_dir.resolve()
    candidate = (base / run_id).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise AgentError(
            code="RUN-001",
            exit_code=2,
            message=f"run id escapes the agent state root: {run_id}",
            resolution="Use the run id printed by k8s-agent prepare or listed by status.",
            context={"run_id": run_id},
        ) from exc
    return candidate
