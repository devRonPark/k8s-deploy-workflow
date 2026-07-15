from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import yaml

from preanalyzer.analyzer.parsers.result import (
    CODE_INVALID_ENCODING,
    CODE_INVALID_SYNTAX,
    CODE_INVALID_YAML,
    CODE_READ_ERROR,
    ParseWarning,
)


@dataclass(frozen=True)
class SpringDependencyHint:
    kind: str
    target: str
    key: str


@dataclass(frozen=True)
class ParsedSpringConfig:
    path: str
    configuration_keys: list[str] = field(default_factory=list)
    service_name: str | None = None
    server_port: int | None = None
    dependency_hints: list[SpringDependencyHint] = field(default_factory=list)


def parse_spring_config(path: Path) -> ParsedSpringConfig:
    document = _load(path)
    flat = _flatten(document)
    service_name = _string(flat.get("spring.application.name"))
    server_port = _integer(flat.get("server.port"))
    dependency_hints = _dependency_hints(flat)
    return ParsedSpringConfig(
        path=path.as_posix(),
        configuration_keys=sorted(flat),
        service_name=service_name,
        server_port=server_port,
        dependency_hints=dependency_hints,
    )


def try_parse_spring_config(path: Path) -> ParsedSpringConfig | ParseWarning:
    try:
        return parse_spring_config(path)
    except yaml.YAMLError as exc:
        message = getattr(exc, "problem", None) or "YAML parsing failed"
        return ParseWarning(path=str(path), parser="spring_config", message=str(message), code=CODE_INVALID_YAML)
    except UnicodeDecodeError:
        return ParseWarning(path=str(path), parser="spring_config", message="invalid text encoding", code=CODE_INVALID_ENCODING)
    except OSError as exc:
        return ParseWarning(path=str(path), parser="spring_config", message=exc.strerror or "read error", code=CODE_READ_ERROR)
    except (TypeError, ValueError) as exc:
        return ParseWarning(path=str(path), parser="spring_config", message=str(exc), code=CODE_INVALID_SYNTAX)


def _load(path: Path) -> object:
    if path.suffix.lower() == ".properties":
        return _load_properties(path)
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_properties(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            key, separator, value = line.partition(":")
        if not separator:
            continue
        key = key.strip()
        if key:
            result[key] = value.strip()
    return result


def _flatten(document: object) -> dict[str, object]:
    values: dict[str, object] = {}

    def walk(prefix: str, value: object) -> None:
        if isinstance(value, dict):
            for key, child in sorted(value.items()):
                path = f"{prefix}.{key}" if prefix else str(key)
                values[path] = child
                walk(path, child)

    walk("", document)
    return values


def _dependency_hints(flat: dict[str, object]) -> list[SpringDependencyHint]:
    hints: list[SpringDependencyHint] = []
    config_uri = flat.get("spring.cloud.config.uri")
    config_target = _url_host(config_uri)
    if config_target is not None:
        hints.append(SpringDependencyHint(kind="config_server", target=config_target, key="spring.cloud.config.uri"))

    eureka_url = flat.get("eureka.client.service-url.defaultZone")
    eureka_target = _url_host(eureka_url)
    if eureka_target is not None:
        hints.append(
            SpringDependencyHint(
                kind="service_discovery",
                target=eureka_target,
                key="eureka.client.service-url.defaultZone",
            )
        )
    return sorted(hints, key=lambda hint: (hint.kind, hint.target, hint.key))


def _url_host(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    host = parsed.hostname
    if not host or "$" in host:
        return None
    return host


def _integer(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
