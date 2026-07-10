from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from preanalyzer.analyzer.parsers.result import (
    CODE_INVALID_ENCODING,
    CODE_INVALID_JSON,
    CODE_READ_ERROR,
    ParseWarning,
)

__all__ = ["ParsedNodePackage", "ParseWarning", "parse", "try_parse"]


@dataclass(frozen=True)
class ParsedNodePackage:
    path: str
    scripts: dict[str, str]
    dependencies: list[str]


def parse(path: Path) -> ParsedNodePackage:
    document = json.loads(path.read_text(encoding="utf-8"))
    dependencies = set((document.get("dependencies") or {}).keys())
    dependencies.update((document.get("devDependencies") or {}).keys())
    return ParsedNodePackage(
        path=path.as_posix(),
        scripts={str(key): str(value) for key, value in (document.get("scripts") or {}).items()},
        dependencies=sorted(dependencies),
    )


def try_parse(path: Path) -> ParsedNodePackage | ParseWarning:
    try:
        return parse(path)
    except json.JSONDecodeError as exc:
        return ParseWarning(path=str(path), parser="nodejs", message=str(exc), code=CODE_INVALID_JSON)
    except UnicodeDecodeError:
        return ParseWarning(
            path=str(path), parser="nodejs", message="invalid text encoding", code=CODE_INVALID_ENCODING
        )
    except OSError as exc:
        return ParseWarning(
            path=str(path), parser="nodejs", message=exc.strerror or "read error", code=CODE_READ_ERROR
        )
