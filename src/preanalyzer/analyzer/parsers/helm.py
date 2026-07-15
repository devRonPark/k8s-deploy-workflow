from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from preanalyzer.analyzer.parsers.result import (
    CODE_INVALID_ENCODING,
    CODE_INVALID_YAML,
    CODE_READ_ERROR,
    ParseWarning,
)


@dataclass(frozen=True)
class ParsedHelmChart:
    path: str
    name: str | None
    version: str | None
    app_version: str | None
    chart_type: str | None


def parse(path: Path) -> ParsedHelmChart:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}
    return ParsedHelmChart(
        path=path.as_posix(),
        name=_string(raw.get("name")),
        version=_string(raw.get("version")),
        app_version=_string(raw.get("appVersion")),
        chart_type=_string(raw.get("type")),
    )


def try_parse(path: Path) -> ParsedHelmChart | ParseWarning:
    try:
        return parse(path)
    except yaml.YAMLError as exc:
        message = getattr(exc, "problem", None) or "YAML parsing failed"
        return ParseWarning(path=str(path), parser="helm", message=str(message), code=CODE_INVALID_YAML)
    except UnicodeDecodeError:
        return ParseWarning(path=str(path), parser="helm", message="invalid text encoding", code=CODE_INVALID_ENCODING)
    except OSError as exc:
        return ParseWarning(path=str(path), parser="helm", message=exc.strerror or "read error", code=CODE_READ_ERROR)


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None
