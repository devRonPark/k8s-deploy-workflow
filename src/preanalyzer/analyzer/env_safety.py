"""Environment-variable sanitization for Phase 1 evidence.

Raw environment values may embed credentials even when the variable name has no
sensitive keyword (e.g. ``DATABASE_URL=postgresql://user:pass@db/app``). To keep
secrets out of Phase 1 output (which becomes LLM input), raw values are never
stored. Instead we record only the minimal structured facts needed downstream:
presence, value type, credential flag, ``${VAR}`` references, and — for URIs —
a sanitized ``{scheme, host, port}`` used for dependency inference.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit


class _HostEnvironment:
    """Sentinel for a bare Compose environment key (``- DEBUG``).

    A bare key passes the host environment's value through at runtime; it is
    neither "empty" nor a literal. Kept distinct so evidence can record
    ``source: host_environment`` without ever reading the host value.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return "HOST_ENVIRONMENT"


HOST_ENVIRONMENT = _HostEnvironment()


_SECRET_NAME_TOKENS = ["PASSWORD", "SECRET", "TOKEN", "KEY", "CREDENTIAL", "PRIVATE"]

_VARIABLE_REF_RE = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)[^}]*\}|\$([A-Za-z_][A-Za-z0-9_]*)"
)
_PURE_REFERENCE_RE = re.compile(
    r"^\$\{[A-Za-z_][A-Za-z0-9_]*[^}]*\}$|^\$[A-Za-z_][A-Za-z0-9_]*$"
)

_CREDENTIAL_QUERY_KEYS = {
    "token",
    "access_token",
    "password",
    "passwd",
    "secret",
    "apikey",
    "api_key",
    "accesskey",
    "access_key",
    "auth",
}


def is_secret_name(name: str) -> bool:
    upper = name.upper()
    return any(token in upper for token in _SECRET_NAME_TOKENS)


def extract_referenced_variables(value: str) -> list[str]:
    names: set[str] = set()
    for braced, bare in _VARIABLE_REF_RE.findall(value):
        names.add(braced or bare)
    return sorted(names)


def _strip_jdbc(value: str) -> str:
    if value.lower().startswith("jdbc:"):
        return value[len("jdbc:"):]
    return value


def sanitize_uri(value: str) -> dict[str, object] | None:
    """Return ``{scheme, host, port}`` for a URI value, or None if not a URI.

    Never returns userinfo, password, path, or query — only what dependency
    inference needs (host/port) plus the scheme.
    """
    candidate = _strip_jdbc(value.strip())
    if "://" not in candidate:
        return None
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    if not parts.hostname:
        return None
    sanitized: dict[str, object] = {}
    if parts.scheme:
        sanitized["scheme"] = parts.scheme
    sanitized["host"] = parts.hostname
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is not None:
        sanitized["port"] = port
    return sanitized


def contains_credentials(value: str) -> bool:
    candidate = _strip_jdbc(value.strip())
    if "://" not in candidate:
        return False
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return False
    if parts.username or parts.password:
        return True
    for key in parse_qs(parts.query):
        if key.lower() in _CREDENTIAL_QUERY_KEYS:
            return True
    return False


def build_env_fact(service_name: str, name: str, value: object) -> dict[str, object]:
    """Build a sanitized evidence fact for one environment variable.

    The raw value is intentionally never included in the returned mapping.
    """
    if value is HOST_ENVIRONMENT:
        return {
            "service": service_name,
            "name": name,
            "value_present": "unknown",
            "value_type": "host_environment",
            "source": "host_environment",
            "resolved": False,
            "contains_credentials": False,
        }

    referenced = extract_referenced_variables(value or "")
    fact: dict[str, object] = {
        "service": service_name,
        "name": name,
        "value_present": bool(value),
    }

    if not value:
        fact["value_type"] = "empty"
        fact["contains_credentials"] = False
        if referenced:
            fact["referenced_variables"] = referenced
        return fact

    sanitized = sanitize_uri(value)
    if sanitized is not None:
        fact["value_type"] = "uri"
    elif _PURE_REFERENCE_RE.match(value.strip()):
        fact["value_type"] = "reference"
    else:
        fact["value_type"] = "plain"

    fact["contains_credentials"] = contains_credentials(value)
    if referenced:
        fact["referenced_variables"] = referenced
    if sanitized is not None:
        fact["sanitized"] = sanitized
    return fact
