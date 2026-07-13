from __future__ import annotations

import subprocess
import io
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


class FakeLLM:
    def __init__(self, responses: dict[str, list[Any]] | None = None) -> None:
        self.responses = {key: list(value) for key, value in (responses or {}).items()}

    def _pop(self, name: str):
        values = self.responses.get(name, [])
        return values.pop(0) if values else None

    def explain_analysis(self, topology):
        return self._pop("explain_analysis")

    def phrase_question(self, question):
        return self._pop("phrase_question")

    def nl_to_changeset(self, request, intent, allowed_paths):
        return self._pop("nl_to_changeset")

    def explain_validation_failure(self, report):
        return self._pop("explain_validation_failure")

    def propose_correction(self, report_payload, intent, allowed_paths):
        return self._pop("propose_correction")


class ScriptedConsole:
    def __init__(self, inputs: list[str]) -> None:
        self.inputs = list(inputs)
        self.out = io.StringIO()

    def ask(self, prompt: str) -> str:
        self.out.write(prompt)
        if not self.inputs:
            raise AssertionError(f"no scripted input left for {prompt!r}")
        value = self.inputs.pop(0)
        self.out.write(value + "\n")
        return value

    def say(self, text: str) -> None:
        self.out.write(text + "\n")

    def confirm(self, prompt: str) -> bool:
        return self.ask(prompt).strip().lower() in {"y", "yes"}
