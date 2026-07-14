from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from k8s_agent.llm.redaction import Redactor


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str
    audit: "CommandAudit | None" = None

    def audit_details(self) -> dict[str, str]:
        if self.audit is None:
            return {}
        return self.audit.details()


@dataclass(frozen=True)
class CommandAudit:
    tool: str
    cwd: str
    args: list[str]
    shell: bool
    env_keys: list[str]
    exit_code: int

    def details(self) -> dict[str, str]:
        redactor = Redactor()
        return {
            "tool": self.tool,
            "cwd": redactor.redact_text(self.cwd),
            "args": " ".join(redactor.redact_text(arg) for arg in self.args),
            "shell": str(self.shell),
            "env_keys": ",".join(sorted(self.env_keys)),
            "exit_code": str(self.exit_code),
        }


class GitRunner:
    def __init__(self, timeout_seconds: float = 60.0, audit_sink: Callable[[CommandAudit], None] | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.audit_sink = audit_sink

    def run(self, cwd: Path, args: list[str], env: dict[str, str] | None = None) -> GitResult:
        process_env = _base_environment()
        if env:
            process_env.update(env)
        command = ["git", "-C", str(cwd), *args]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                shell=False,
                env=process_env,
                timeout=self.timeout_seconds,
            )
            audit = self._audit(cwd, args, process_env, result.returncode)
        except subprocess.TimeoutExpired as exc:
            audit = self._audit(cwd, args, process_env, 124)
            return self._result(GitResult(returncode=124, stdout=exc.stdout or "", stderr="git command timed out", audit=audit))
        except OSError as exc:
            audit = self._audit(cwd, args, process_env, 127)
            return self._result(GitResult(returncode=127, stdout="", stderr=str(exc), audit=audit))
        return self._result(GitResult(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr, audit=audit))

    def output(self, cwd: Path, args: list[str], env: dict[str, str] | None = None) -> str | None:
        result = self.run(cwd, args, env=env)
        if result.returncode != 0:
            return None
        output = result.stdout.strip()
        return output or None

    def _audit(self, cwd: Path, args: list[str], process_env: dict[str, str], exit_code: int) -> CommandAudit:
        return CommandAudit(
            tool="git",
            cwd=str(cwd),
            args=list(args),
            shell=False,
            env_keys=sorted(process_env),
            exit_code=exit_code,
        )

    def _result(self, result: GitResult) -> GitResult:
        if self.audit_sink and result.audit:
            self.audit_sink(result.audit)
        return result


def _base_environment() -> dict[str, str]:
    allowed = {
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "SYSTEMROOT",
        "TMP",
        "TMPDIR",
        "TEMP",
        "USERPROFILE",
        "WINDIR",
    }
    return {key: value for key, value in os.environ.items() if key in allowed}
