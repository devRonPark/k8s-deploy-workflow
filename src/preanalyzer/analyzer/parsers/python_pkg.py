from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class ParsedPythonPackage:
    path: str
    dependencies: list[str]


def parse_pyproject(path: Path) -> ParsedPythonPackage:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    project = document.get("project") or {}
    dependencies = [_dependency_name(value) for value in project.get("dependencies") or []]
    poetry = document.get("tool", {}).get("poetry", {}).get("dependencies", {})
    dependencies.extend(_dependency_name(name) for name in poetry if name.lower() != "python")
    return ParsedPythonPackage(path=path.as_posix(), dependencies=sorted(set(dependencies)))


def parse_requirements(path: Path) -> ParsedPythonPackage:
    dependencies = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        dependencies.append(_dependency_name(line))
    return ParsedPythonPackage(path=path.as_posix(), dependencies=dependencies)


def _dependency_name(value: str) -> str:
    for separator in ["==", ">=", "<=", "~=", ">", "<", "["]:
        value = value.split(separator, 1)[0]
    return value.strip()
