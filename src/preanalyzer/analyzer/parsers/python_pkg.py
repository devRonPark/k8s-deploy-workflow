from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from preanalyzer.analyzer.parsers.result import (
    CODE_INVALID_ENCODING,
    CODE_INVALID_TOML,
    CODE_READ_ERROR,
    ParseWarning,
)

__all__ = [
    "ParsedPythonPackage",
    "ParseWarning",
    "parse_pyproject",
    "parse_requirements",
    "try_parse_pyproject",
    "try_parse_requirements",
]


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


def try_parse_pyproject(path: Path) -> ParsedPythonPackage | ParseWarning:
    try:
        return parse_pyproject(path)
    except tomllib.TOMLDecodeError as exc:
        return ParseWarning(
            path=str(path), parser="python_pyproject", message=str(exc), code=CODE_INVALID_TOML
        )
    except UnicodeDecodeError:
        return ParseWarning(
            path=str(path), parser="python_pyproject", message="invalid text encoding", code=CODE_INVALID_ENCODING
        )
    except OSError as exc:
        return ParseWarning(
            path=str(path), parser="python_pyproject", message=exc.strerror or "read error", code=CODE_READ_ERROR
        )


def try_parse_requirements(path: Path) -> ParsedPythonPackage | ParseWarning:
    try:
        return parse_requirements(path)
    except UnicodeDecodeError:
        return ParseWarning(
            path=str(path), parser="python_requirements", message="invalid text encoding", code=CODE_INVALID_ENCODING
        )
    except OSError as exc:
        return ParseWarning(
            path=str(path), parser="python_requirements", message=exc.strerror or "read error", code=CODE_READ_ERROR
        )


def _dependency_name(value: str) -> str:
    for separator in ["==", ">=", "<=", "~=", ">", "<", "["]:
        value = value.split(separator, 1)[0]
    return value.strip()
