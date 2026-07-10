from __future__ import annotations

from dataclasses import dataclass, field
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
    "RequirementInclude",
    "DirectReference",
    "ParseWarning",
    "parse_pyproject",
    "parse_requirements",
    "try_parse_pyproject",
    "try_parse_requirements",
]


@dataclass(frozen=True)
class RequirementInclude:
    """A ``-r``/``--requirement`` or ``-c``/``--constraint`` include line."""

    kind: str  # "requirements" | "constraints"
    path: str


@dataclass(frozen=True)
class DirectReference:
    """An editable / VCS / direct-URL dependency.

    Only the resolvable package ``name`` is retained (from ``#egg=`` or a
    ``name @ url`` prefix); raw URLs are dropped because they may embed
    credentials.
    """

    kind: str  # "editable" | "vcs" | "url"
    name: str | None


@dataclass(frozen=True)
class ParsedPythonPackage:
    path: str
    dependencies: list[str]
    includes: list[RequirementInclude] = field(default_factory=list)
    direct_references: list[DirectReference] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_pyproject(path: Path) -> ParsedPythonPackage:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    project = document.get("project") or {}
    dependencies = [_dependency_name(value) for value in project.get("dependencies") or []]
    poetry = document.get("tool", {}).get("poetry", {}).get("dependencies", {})
    dependencies.extend(_dependency_name(name) for name in poetry if name.lower() != "python")
    return ParsedPythonPackage(path=path.as_posix(), dependencies=sorted(set(dependencies)))


_INCLUDE_OPTIONS = {"-r": "requirements", "--requirement": "requirements", "-c": "constraints", "--constraint": "constraints"}
_EDITABLE_OPTIONS = {"-e", "--editable"}
# Options that take a following value or are standalone; never a package.
_VALUE_OPTIONS = {
    "-i",
    "--index-url",
    "--extra-index-url",
    "-f",
    "--find-links",
    "--no-binary",
    "--only-binary",
    "--pre",
    "--trusted-host",
    "--use-feature",
    "--hash",
}
_VCS_SCHEMES = ("git+", "hg+", "svn+", "bzr+")


def parse_requirements(path: Path) -> ParsedPythonPackage:
    dependencies: list[str] = []
    includes: list[RequirementInclude] = []
    direct_references: list[DirectReference] = []
    warnings: list[str] = []

    for line in _logical_lines(path.read_text(encoding="utf-8")):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        stripped = _strip_inline_comment(stripped)
        if not stripped:
            continue

        token = stripped.split(maxsplit=1)
        head = token[0]
        rest = token[1].strip() if len(token) > 1 else ""

        if head in _INCLUDE_OPTIONS:
            if rest:
                includes.append(RequirementInclude(kind=_INCLUDE_OPTIONS[head], path=rest))
            continue
        if head in _EDITABLE_OPTIONS:
            direct_references.append(DirectReference(kind="editable", name=_direct_reference_name(rest)))
            continue
        if head in _VALUE_OPTIONS or head.startswith("--"):
            continue  # index / hash / feature options — not packages
        if stripped.startswith(_VCS_SCHEMES):
            direct_references.append(DirectReference(kind="vcs", name=_direct_reference_name(stripped)))
            continue
        if "://" in stripped and " @ " not in stripped:
            direct_references.append(DirectReference(kind="url", name=_direct_reference_name(stripped)))
            continue
        if " @ " in stripped:  # PEP 508 direct reference: name @ url
            direct_references.append(DirectReference(kind="url", name=_direct_reference_name(stripped)))
            continue

        name = _dependency_name(_requirement_without_marker(stripped))
        if name:
            dependencies.append(name)
        else:
            warnings.append(f"unparsable requirement: {stripped}")

    return ParsedPythonPackage(
        path=path.as_posix(),
        dependencies=dependencies,
        includes=includes,
        direct_references=direct_references,
        warnings=warnings,
    )


def _logical_lines(text: str) -> list[str]:
    """Join backslash line continuations into single logical lines."""
    lines: list[str] = []
    buffer = ""
    for raw in text.splitlines():
        if raw.rstrip().endswith("\\"):
            buffer += raw.rstrip()[:-1] + " "
            continue
        lines.append(buffer + raw)
        buffer = ""
    if buffer:
        lines.append(buffer)
    return lines


def _strip_inline_comment(line: str) -> str:
    # An inline comment starts with ' #' (space then hash); a bare '#' mid-token
    # (e.g. #egg=) is not a comment.
    index = line.find(" #")
    return line[:index].strip() if index != -1 else line


def _requirement_without_marker(value: str) -> str:
    # Drop the environment marker (kept implicitly by ignoring it for the name).
    return value.split(";", 1)[0].strip()


def _direct_reference_name(value: str) -> str | None:
    if "#egg=" in value:
        egg = value.split("#egg=", 1)[1]
        return egg.split("&", 1)[0].strip() or None
    if " @ " in value:
        return _dependency_name(value.split(" @ ", 1)[0]) or None
    return None


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
