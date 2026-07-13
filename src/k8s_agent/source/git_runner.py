from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str


class GitRunner:
    def run(self, cwd: Path, args: list[str]) -> GitResult:
        try:
            result = subprocess.run(
                ["git", "-C", str(cwd), *args],
                check=False,
                capture_output=True,
                text=True,
                shell=False,
            )
        except OSError as exc:
            return GitResult(returncode=127, stdout="", stderr=str(exc))
        return GitResult(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)

    def output(self, cwd: Path, args: list[str]) -> str | None:
        result = self.run(cwd, args)
        if result.returncode != 0:
            return None
        output = result.stdout.strip()
        return output or None
