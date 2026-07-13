from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from preanalyzer.path_safety import resolve_repository_path

from k8sagent.errors import RepoAcquisitionError
from k8sagent.procutil import ProcResult, redact_text, run_command
from k8sagent.session import RepoSource


@dataclass(frozen=True)
class AcquiredRepo:
    repo_path: Path
    source: RepoSource


Runner = Callable[..., ProcResult]


def is_git_url(text: str) -> bool:
    return text.startswith(("https://", "http://", "git@", "ssh://", "file://"))


def acquire_local(
    path: str,
    ref: str | None = None,
    *,
    cache_root: Path | None = None,
    runner: Runner = run_command,
) -> AcquiredRepo:
    resolved = resolve_repository_path(path)
    if not resolved.is_dir():
        raise RepoAcquisitionError(f"repository path not found: {path}")
    if ref is not None:
        root = cache_root or (Path.home() / ".k8s-agent" / "cache")
        return acquire_git(
            resolved.as_uri(),
            ref,
            cache_root=root,
            token=None,
            runner=runner,
        )
    return AcquiredRepo(
        repo_path=resolved,
        source=RepoSource(kind="local", location=str(resolved), ref=None),
    )


def acquire_git(
    url: str,
    ref: str | None,
    *,
    cache_root: Path,
    token: str | None = None,
    runner: Runner = run_command,
    clock=None,
) -> AcquiredRepo:
    del clock
    if url.startswith(("git@", "ssh://")):
        raise RepoAcquisitionError("SSH URLs are not supported; use an HTTPS URL or a local path")

    cache_root.mkdir(parents=True, exist_ok=True)
    cache_dir = cache_root / hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    env = _git_env(cache_root, url, token)
    redact = [token] if token else []

    if (cache_dir / ".git").is_dir():
        _run_git(
            runner,
            ["git", "-C", str(cache_dir), "fetch", "origin", "--prune"],
            env=env,
            redact=redact,
            action="fetch repository",
        )
    else:
        _run_git(
            runner,
            ["git", "clone", "--no-tags", url, str(cache_dir)],
            env=env,
            redact=redact,
            action="clone repository",
        )

    resolved = _resolve_ref(runner, cache_dir, ref, env=env, redact=redact)
    _run_git(
        runner,
        ["git", "-C", str(cache_dir), "checkout", "--detach", resolved],
        env=env,
        redact=redact,
        action="checkout ref",
    )
    commit = _run_git(
        runner,
        ["git", "-C", str(cache_dir), "rev-parse", "HEAD"],
        env=env,
        redact=redact,
        action="read HEAD",
    ).stdout.strip()
    return AcquiredRepo(
        repo_path=cache_dir,
        source=RepoSource(
            kind="git_url",
            location=url,
            ref=ref,
            commit_sha=commit,
            cache_path=str(cache_dir),
        ),
    )


def _resolve_ref(
    runner: Runner,
    cache_dir: Path,
    ref: str | None,
    *,
    env: dict[str, str],
    redact: list[str],
) -> str:
    candidates = ["origin/HEAD"] if ref is None else [ref, f"origin/{ref}"]
    last_stderr = ""
    for candidate in candidates:
        result = runner(
            ["git", "-C", str(cache_dir), "rev-parse", "--verify", f"{candidate}^{{commit}}"],
            env=env,
            redact=redact,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        last_stderr = result.stderr
    if ref is None:
        raise RepoAcquisitionError(
            redact_text(f"ref not found: origin/HEAD {last_stderr}".strip(), redact)
        )
    raise RepoAcquisitionError(redact_text(f"ref not found: {ref}", redact))


def _run_git(
    runner: Runner,
    argv: list[str],
    *,
    env: dict[str, str],
    redact: list[str],
    action: str,
) -> ProcResult:
    result = runner(argv, env=env, redact=redact)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RepoAcquisitionError(redact_text(f"failed to {action}: {detail}", redact))
    return result


def _git_env(cache_root: Path, url: str, token: str | None) -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    if token and url.startswith(("https://", "http://")):
        askpass = _ensure_askpass(cache_root)
        env["GIT_ASKPASS"] = str(askpass)
        env["K8S_AGENT_GIT_ASKPASS_PASS"] = token
        env.setdefault("K8S_AGENT_GIT_ASKPASS_USER", "x-access-token")
    return env


def _ensure_askpass(cache_root: Path) -> Path:
    askpass = cache_root / "askpass.sh"
    if not askpass.exists():
        askpass.write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  Username*) echo \"${K8S_AGENT_GIT_ASKPASS_USER:-x-access-token}\" ;;\n"
            "  *) echo \"$K8S_AGENT_GIT_ASKPASS_PASS\" ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        askpass.chmod(0o700)
    return askpass
