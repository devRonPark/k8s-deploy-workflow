from __future__ import annotations

import re
from typing import Any

from preanalyzer.semantic.tools.common import redacted


_URL_USERINFO_RE = re.compile(r"(?P<scheme>https?://)[^/@\s]+@")
_SECRET_OPTION_RE = re.compile(
    r"(?i)(?P<prefix>(?:--(?:password|passwd|token|secret|api-key|api_key)|"
    r"(?:password|passwd|token|secret|api[_-]?key))"
    r"(?P<sep>\s+|=|:))(?P<value>[^\s,;]+)"
)


def redact_text(value: str) -> str:
    without_userinfo = _URL_USERINFO_RE.sub(r"\g<scheme>[REDACTED]@", value)
    return _SECRET_OPTION_RE.sub(_redact_secret_option, redacted(without_userinfo))


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            result[key_text] = "[REDACTED]" if _is_sensitive_key(key_text) else redact_value(item)
        return result
    return value


def _redact_secret_option(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}[REDACTED]"


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in ("password", "passwd", "token", "secret", "api_key", "api-key"))
