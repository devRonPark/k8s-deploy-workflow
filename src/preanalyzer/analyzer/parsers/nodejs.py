from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


@dataclass(frozen=True)
class ParsedNodePackage:
    path: str
    scripts: dict[str, str]
    dependencies: list[str]


@dataclass(frozen=True)
class ParseWarning:
    path: str
    parser: str
    message: str


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
    except Exception as exc:
        return ParseWarning(path=str(path), parser="nodejs", message=str(exc))
