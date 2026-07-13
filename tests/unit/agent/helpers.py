from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from k8sagent.procutil import ProcResult


def make_git_repo(base: Path, *, files: dict[str, str] | None = None) -> Path:
    repo = base / "origin-repo"
    repo.mkdir()
    for rel, text in (
        files or {"Dockerfile": 'FROM python:3.11\nCMD ["python", "app.py"]\n'}
    ).items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    for argv in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "t"],
        ["git", "config", "commit.gpgsign", "false"],
        ["git", "add", "."],
        ["git", "commit", "-q", "-m", "init"],
    ):
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    return repo


def git_output(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


class FakeRunner:
    def __init__(self, results: list[ProcResult] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv, **kwargs) -> ProcResult:
        self.calls.append({"argv": list(argv), **kwargs})
        result = self.results.pop(0) if self.results else ProcResult(returncode=0, stdout="", stderr="")
        if result.returncode == 0 and list(argv)[:3] == ["git", "clone", "--no-tags"]:
            (Path(argv[-1]) / ".git").mkdir(parents=True, exist_ok=True)
        return result
