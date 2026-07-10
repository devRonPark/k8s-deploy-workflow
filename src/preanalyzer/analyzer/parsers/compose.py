from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ComposePort:
    host_port: int | None
    container_port: int
    source: str = "compose_ports"

    def model_dump(self) -> dict:
        return {
            "host_port": self.host_port,
            "container_port": self.container_port,
            "source": self.source,
        }


@dataclass(frozen=True)
class ComposeService:
    name: str
    image: str | None
    build_context: str | None
    ports: list[ComposePort]
    environment: dict[str, str]
    volumes: list[str]
    depends_on: list[str]
    labels: dict[str, str]


@dataclass(frozen=True)
class ParsedCompose:
    path: str
    services: list[ComposeService]
    warnings: list[str]

    def service(self, name: str) -> ComposeService:
        for service in self.services:
            if service.name == name:
                return service
        raise KeyError(name)


def parse(path: Path) -> ParsedCompose:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_services = document.get("services") or {}
    services = [_parse_service(name, value or {}) for name, value in sorted(raw_services.items())]
    return ParsedCompose(path=path.as_posix(), services=services, warnings=[])


def _parse_service(name: str, raw: dict[str, Any]) -> ComposeService:
    return ComposeService(
        name=name,
        image=raw.get("image"),
        build_context=_parse_build_context(raw.get("build")),
        ports=_parse_ports(raw.get("ports") or []),
        environment=_parse_environment(raw.get("environment") or {}),
        volumes=[str(value) for value in raw.get("volumes") or []],
        depends_on=_parse_depends_on(raw.get("depends_on") or []),
        labels=_parse_key_values(raw.get("labels") or {}),
    )


def _parse_build_context(raw: Any) -> str | None:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        context = raw.get("context")
        return str(context) if context is not None else None
    return None


def _parse_ports(raw_ports: list[Any]) -> list[ComposePort]:
    ports: list[ComposePort] = []
    for raw in raw_ports:
        if isinstance(raw, str):
            host, container = _parse_short_port(raw)
            ports.append(ComposePort(host_port=host, container_port=container))
        elif isinstance(raw, dict) and raw.get("target") is not None:
            published = raw.get("published")
            ports.append(
                ComposePort(
                    host_port=int(published) if published is not None else None,
                    container_port=int(raw["target"]),
                )
            )
    return ports


def _parse_short_port(raw: str) -> tuple[int | None, int]:
    parts = raw.split(":")
    if len(parts) == 1:
        return None, int(parts[0].split("/", 1)[0])
    return int(parts[-2]), int(parts[-1].split("/", 1)[0])


def _parse_environment(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    result: dict[str, str] = {}
    for item in raw:
        key, _, value = str(item).partition("=")
        result[key] = value
    return result


def _parse_depends_on(raw: Any) -> list[str]:
    if isinstance(raw, dict):
        return sorted(str(name) for name in raw)
    return sorted(str(name) for name in raw)


def _parse_key_values(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    result: dict[str, str] = {}
    for item in raw:
        key, _, value = str(item).partition("=")
        result[key] = value
    return result
