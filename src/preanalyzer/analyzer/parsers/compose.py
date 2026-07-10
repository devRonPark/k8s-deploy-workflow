from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re

import yaml

from preanalyzer.analyzer.env_safety import HOST_ENVIRONMENT
from preanalyzer.analyzer.parsers.result import (
    CODE_INVALID_ENCODING,
    CODE_INVALID_SYNTAX,
    CODE_INVALID_YAML,
    CODE_READ_ERROR,
    ParseWarning,
)


@dataclass(frozen=True)
class ComposePort:
    """A single Compose port mapping.

    ``raw`` always preserves the original expression. When the host/container
    ports cannot be pinned to a single integer — an unresolved ``${VAR}`` with
    no default, or a port range — ``resolved`` is ``False``/the field is
    ``None`` and ``warning`` explains why, rather than guessing a value.
    """

    raw: str
    host_ip: str | None = None
    host_port: int | None = None
    container_port: int | None = None
    protocol: str | None = None
    resolved: bool = True
    resolution_source: str | None = None
    warning: str | None = None

    def model_dump(self) -> dict:
        return {
            "raw": self.raw,
            "host_ip": self.host_ip,
            "host_port": self.host_port,
            "container_port": self.container_port,
            "protocol": self.protocol,
            "resolved": self.resolved,
            "resolution_source": self.resolution_source,
            "warning": self.warning,
        }


@dataclass(frozen=True)
class ComposeService:
    name: str
    image: str | None
    build_context: str | None
    ports: list[ComposePort]
    environment: dict[str, Any]
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


SUPPORTED_SERVICE_KEYS = {
    "image",
    "build",
    "ports",
    "environment",
    "volumes",
    "depends_on",
    "labels",
    "command",
    "entrypoint",
    "healthcheck",
    "secrets",
    "configs",
}

# Service keys the Compose merge spec replaces wholesale instead of merging.
REPLACE_SERVICE_KEYS = {"command", "entrypoint"}


# --- Custom loader: recognize the Compose 2.24+ merge tags --------------------


@dataclass(frozen=True)
class _Override:
    value: Any


class _Reset:
    __slots__ = ()


_RESET = _Reset()


class _ComposeLoader(yaml.SafeLoader):
    pass


def _construct_override(loader: yaml.Loader, node: yaml.Node) -> _Override:
    if isinstance(node, yaml.ScalarNode):
        return _Override(loader.construct_scalar(node))
    if isinstance(node, yaml.SequenceNode):
        return _Override(loader.construct_sequence(node))
    return _Override(loader.construct_mapping(node))


def _construct_reset(loader: yaml.Loader, node: yaml.Node) -> _Reset:
    return _RESET


_ComposeLoader.add_constructor("!override", _construct_override)
_ComposeLoader.add_constructor("!reset", _construct_reset)


def _load(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader) or {}


# --- Entry points -------------------------------------------------------------


def parse(path: Path) -> ParsedCompose:
    return _parse_document(path, _load(path))


def parse_with_override(base_path: Path, override_path: Path | None) -> ParsedCompose:
    base = _load(base_path)
    if override_path is None:
        document = base
    else:
        document = _merge_compose_documents(base, _load(override_path))
    return _parse_document(base_path, document)


def try_parse(path: Path) -> ParsedCompose | ParseWarning:
    return _guard(path, lambda: parse(path))


def try_parse_with_override(base_path: Path, override_path: Path | None) -> ParsedCompose | ParseWarning:
    return _guard(base_path, lambda: parse_with_override(base_path, override_path))


def _guard(path: Path, call) -> ParsedCompose | ParseWarning:
    try:
        return call()
    except yaml.YAMLError as exc:
        message = getattr(exc, "problem", None) or "YAML parsing failed"
        return ParseWarning(path=str(path), parser="compose", message=str(message), code=CODE_INVALID_YAML)
    except UnicodeDecodeError:
        return ParseWarning(
            path=str(path), parser="compose", message="invalid text encoding", code=CODE_INVALID_ENCODING
        )
    except OSError as exc:
        return ParseWarning(
            path=str(path), parser="compose", message=exc.strerror or "read error", code=CODE_READ_ERROR
        )
    except (ValueError, TypeError, AttributeError) as exc:
        return ParseWarning(path=str(path), parser="compose", message=str(exc), code=CODE_INVALID_SYNTAX)


def _parse_document(path: Path, document: dict) -> ParsedCompose:
    raw_services = document.get("services") or {}
    warnings: list[str] = []
    services: list[ComposeService] = []
    for name, value in sorted(raw_services.items()):
        raw = value or {}
        warnings.extend(
            f"{name}: unsupported key {key}" for key in sorted(set(raw) - SUPPORTED_SERVICE_KEYS)
        )
        service, port_warnings = _parse_service(name, raw)
        warnings.extend(port_warnings)
        services.append(service)
    return ParsedCompose(path=path.as_posix(), services=services, warnings=sorted(warnings))


# --- Merge (Compose override semantics) ---------------------------------------


def _merge_compose_documents(base: dict, override: dict) -> dict:
    merged = _merge_mapping(base, override)
    base_services = base.get("services") or {}
    override_services = override.get("services") or {}
    merged_services: dict[str, Any] = {name: dict(value or {}) for name, value in base_services.items()}
    for name, value in override_services.items():
        if isinstance(value, _Reset):
            merged_services.pop(name, None)
            continue
        current = merged_services.get(name, {})
        merged_services[name] = _merge_service(dict(current or {}), dict(value or {}))
    merged["services"] = merged_services
    return merged


def _merge_service(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, _Reset):
            result.pop(key, None)
            continue
        if isinstance(value, _Override):
            result[key] = value.value
            continue
        if key not in result:
            result[key] = value
            continue
        current = result[key]
        if key in {"environment", "labels"}:
            result[key] = _merge_env_like(current, value)
        elif key == "ports":
            result[key] = _merge_keyed_list(current, value, _port_merge_key)
        elif key == "volumes":
            result[key] = _merge_keyed_list(current, value, _volume_merge_key)
        elif key in {"secrets", "configs"}:
            result[key] = _merge_keyed_list(current, value, _named_ref_key)
        elif key in REPLACE_SERVICE_KEYS:
            result[key] = value
        elif key == "healthcheck":
            result[key] = _merge_healthcheck(current, value)
        elif isinstance(current, dict) and isinstance(value, dict):
            result[key] = _merge_mapping(current, value)
        elif isinstance(current, list) and isinstance(value, list):
            result[key] = current + value
        else:
            result[key] = value
    return result


def _merge_mapping(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, _Reset):
            result.pop(key, None)
        elif isinstance(value, _Override):
            result[key] = value.value
        elif key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_mapping(result[key], value)
        else:
            result[key] = value
    return result


def _merge_healthcheck(base: Any, override: Any) -> Any:
    if not (isinstance(base, dict) and isinstance(override, dict)):
        return override
    merged = _merge_mapping(base, override)
    if "test" in override:  # healthcheck.test is replaced, never merged
        merged["test"] = override["test"]
    return merged


def _merge_env_like(base: Any, override: Any) -> dict[str, Any]:
    merged = dict(_normalize_env_map(base))
    merged.update(_normalize_env_map(override))
    return merged


def _merge_keyed_list(base: Any, override: Any, key_of) -> list[Any]:
    """Merge two sequences by a per-entry identity key.

    Entries in ``override`` replace base entries sharing the same key; new keys
    are appended in override order. Entries whose key is ``None`` (unkeyable)
    are concatenated verbatim.
    """
    result: list[Any] = list(base or [])
    index: dict[Any, int] = {}
    for i, entry in enumerate(result):
        key = key_of(entry)
        if key is not None:
            index[key] = i
    for entry in override or []:
        key = key_of(entry)
        if key is not None and key in index:
            result[index[key]] = entry
        else:
            if key is not None:
                index[key] = len(result)
            result.append(entry)
    return result


def _port_merge_key(entry: Any) -> Any:
    if isinstance(entry, dict):
        return ("long", entry.get("host_ip"), entry.get("published"), entry.get("target"), entry.get("protocol"))
    port = _parse_short_port(str(entry))
    return ("short", port.host_ip, port.host_port, port.container_port, port.protocol, port.raw if not port.resolved else None)


def _volume_merge_key(entry: Any) -> Any:
    if isinstance(entry, dict):
        return entry.get("target")
    text = str(entry)
    parts = text.split(":")
    if len(parts) >= 2:  # host:container[:mode] or name:container[:mode]
        return parts[1]
    return text  # anonymous volume — key on the container path itself


def _named_ref_key(entry: Any) -> Any:
    if isinstance(entry, dict):
        return entry.get("source") or entry.get("target")
    return str(entry)


# --- Service parsing ----------------------------------------------------------


def _parse_service(name: str, raw: dict[str, Any]) -> tuple[ComposeService, list[str]]:
    ports, warnings = _parse_ports(name, raw.get("ports") or [])
    service = ComposeService(
        name=name,
        image=raw.get("image"),
        build_context=_parse_build_context(raw.get("build")),
        ports=ports,
        environment=_normalize_env_map(raw.get("environment") or {}),
        volumes=[str(value) for value in raw.get("volumes") or []],
        depends_on=_parse_depends_on(raw.get("depends_on") or []),
        labels=_parse_key_values(raw.get("labels") or {}),
    )
    return service, warnings


def _parse_build_context(raw: Any) -> str | None:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        context = raw.get("context")
        return str(context) if context is not None else None
    return None


def _parse_ports(service: str, raw_ports: list[Any]) -> tuple[list[ComposePort], list[str]]:
    ports: list[ComposePort] = []
    warnings: list[str] = []
    for raw in raw_ports:
        if isinstance(raw, dict):
            port = _parse_long_port(raw)
        else:
            port = _parse_short_port(str(raw))
        ports.append(port)
        if port.warning is not None:
            warnings.append(f"{service}: {port.warning}")
    return ports, warnings


_INTERP_DEFAULT_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*:[-?](?P<default>[^}]*)\}$")
_INTERP_PLAIN_RE = re.compile(r"^\$\{?[A-Za-z_][A-Za-z0-9_]*\}?$")


def _parse_short_port(raw: str) -> ComposePort:
    text = raw.strip()
    host_ip: str | None = None
    rest = text

    if rest.startswith("["):  # IPv6 host ip: [::1]:8080:80
        end = rest.find("]")
        if end != -1:
            host_ip = rest[1:end]
            rest = rest[end + 1 :]
            if rest.startswith(":"):
                rest = rest[1:]

    protocol: str | None = None
    if "/" in rest:
        rest, protocol = rest.rsplit("/", 1)
        protocol = protocol or None

    parts = _split_port_segments(rest)
    if host_ip is None and len(parts) == 3:
        host_ip, host_token, container_token = parts[0], parts[1], parts[2]
    elif len(parts) >= 2:
        host_token, container_token = parts[-2], parts[-1]
    else:
        host_token, container_token = None, parts[0]

    warnings: list[str] = []
    resolution_source: str | None = None
    resolved = True

    host_port = None
    if host_token not in (None, ""):
        host_port, h_resolved, h_source, h_warn = _resolve_port_token(host_token)
        resolved = resolved and h_resolved
        resolution_source = resolution_source or h_source
        if h_warn:
            warnings.append(h_warn)

    container_port, c_resolved, c_source, c_warn = _resolve_port_token(container_token)
    resolved = resolved and c_resolved
    resolution_source = resolution_source or c_source
    if c_warn:
        warnings.append(c_warn)

    return ComposePort(
        raw=text,
        host_ip=host_ip,
        host_port=host_port,
        container_port=container_port,
        protocol=protocol,
        resolved=resolved,
        resolution_source=resolution_source,
        warning="; ".join(warnings) or None,
    )


def _parse_long_port(raw: dict[str, Any]) -> ComposePort:
    target = raw.get("target")
    published = raw.get("published")
    protocol = raw.get("protocol")
    host_ip = raw.get("host_ip")

    warnings: list[str] = []
    resolution_source: str | None = None
    resolved = True

    host_port = None
    if published is not None:
        host_port, h_resolved, h_source, h_warn = _resolve_port_token(str(published))
        resolved = resolved and h_resolved
        resolution_source = resolution_source or h_source
        if h_warn:
            warnings.append(h_warn)

    container_port = None
    if target is not None:
        container_port, c_resolved, c_source, c_warn = _resolve_port_token(str(target))
        resolved = resolved and c_resolved
        resolution_source = resolution_source or c_source
        if c_warn:
            warnings.append(c_warn)

    raw_repr = "long:" + ",".join(
        f"{key}={raw[key]}" for key in sorted(raw) if raw.get(key) is not None
    )
    return ComposePort(
        raw=raw_repr,
        host_ip=str(host_ip) if host_ip is not None else None,
        host_port=host_port,
        container_port=container_port,
        protocol=str(protocol) if protocol is not None else None,
        resolved=resolved,
        resolution_source=resolution_source,
        warning="; ".join(warnings) or None,
    )


def _split_port_segments(text: str) -> list[str]:
    """Split ``host:container`` on top-level colons only.

    Colons inside a ``${VAR:-default}`` interpolation are not separators, so we
    track ``${ ... }`` nesting instead of a naive ``str.split(":")``.
    """
    segments: list[str] = []
    current: list[str] = []
    depth = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char == "$" and index + 1 < len(text) and text[index + 1] == "{":
            depth += 1
            current.append(text[index : index + 2])
            index += 2
            continue
        if char == "}" and depth > 0:
            depth -= 1
        elif char == ":" and depth == 0:
            segments.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    segments.append("".join(current))
    return segments


def _resolve_port_token(token: str) -> tuple[int | None, bool, str | None, str | None]:
    """Resolve one host/container port token.

    Returns ``(value, resolved, resolution_source, warning)``. A literal
    resolves to its int; ``${VAR:-8080}`` resolves via the in-file default; an
    unresolved ``${VAR}`` or a port range stays ``None`` rather than being
    guessed.
    """
    token = token.strip()
    if token.isdigit():
        return int(token), True, "literal", None

    range_parts = token.split("-")
    if len(range_parts) == 2 and all(part.strip().isdigit() for part in range_parts):
        return None, True, "range", f"port range not expanded: {token}"

    match = _INTERP_DEFAULT_RE.match(token)
    if match:
        default = match.group("default").strip()
        if default.isdigit():
            return int(default), True, "compose_default", None
        return None, False, None, f"unresolved interpolation: {token}"

    if _INTERP_PLAIN_RE.match(token):
        return None, False, None, f"unresolved interpolation: {token}"

    return None, False, None, f"unparsable port token: {token}"


def _normalize_env_map(raw: Any) -> dict[str, Any]:
    """Normalize ``environment`` (map or list form) to a mapping.

    A bare list key (``- DEBUG``) becomes :data:`HOST_ENVIRONMENT` so the
    host-passthrough semantics survive; ``- DEBUG=`` and ``DEBUG:`` stay as an
    explicit empty/unset value. Raw values are never resolved here.
    """
    if isinstance(raw, dict):
        return {str(key): _env_dict_value(value) for key, value in raw.items()}
    result: dict[str, Any] = {}
    for item in raw:
        if item is None:
            continue
        text = str(item)
        if "=" in text:
            key, _, value = text.partition("=")
            result[key] = value
        else:
            result[text] = HOST_ENVIRONMENT
    return result


def _env_dict_value(value: Any) -> Any:
    # Preserve the None (unset) and HOST_ENVIRONMENT (passthrough) markers so a
    # re-normalized (already merged) map does not stringify them.
    if value is None or value is HOST_ENVIRONMENT:
        return value
    return _env_scalar(value)


def _env_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


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
