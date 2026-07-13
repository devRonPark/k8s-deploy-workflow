from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from k8sagent.errors import AgentError


@dataclass(frozen=True)
class ProcResult:
    returncode: int
    stdout: str
    stderr: str


def redact_text(text: str, secrets: Sequence[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = 120.0,
    redact: Sequence[str] = (),
) -> ProcResult:
    run_env = dict(os.environ) if env is None else dict(env)
    try:
        proc = subprocess.run(
            list(argv),
            cwd=str(cwd) if cwd is not None else None,
            env=run_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        message = f"command timed out after {timeout}s: {argv[0]}"
        raise AgentError(redact_text(message, redact)) from exc
    except OSError as exc:
        message = f"command failed to start: {argv[0]}: {exc}"
        raise AgentError(redact_text(message, redact)) from exc
    return ProcResult(
        returncode=proc.returncode,
        stdout=redact_text(proc.stdout or "", redact),
        stderr=redact_text(proc.stderr or "", redact),
    )
