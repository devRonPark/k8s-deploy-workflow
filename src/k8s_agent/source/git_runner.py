from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str


class GitRunner:
    def __init__(self, timeout_seconds: float = 60.0) -> None:
        self.timeout_seconds = timeout_seconds

    def run(self, cwd: Path, args: list[str], env: dict[str, str] | None = None) -> GitResult:
        process_env = _base_environment()
        if env:
            process_env.update(env)
        try:
            result = subprocess.run(
                ["git", "-C", str(cwd), *args],
                check=False,
                capture_output=True,
                text=True,
                shell=False,
                env=process_env,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return GitResult(returncode=124, stdout=exc.stdout or "", stderr="git command timed out")
        except OSError as exc:
            return GitResult(returncode=127, stdout="", stderr=str(exc))
        return GitResult(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)

    def output(self, cwd: Path, args: list[str], env: dict[str, str] | None = None) -> str | None:
        result = self.run(cwd, args, env=env)
        if result.returncode != 0:
            return None
        output = result.stdout.strip()
        return output or None


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
