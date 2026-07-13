from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from preanalyzer.semantic.tools.common import redacted


_SENSITIVE_KEY_RE = re.compile(r"(?i)(password|passwd|token|secret|api[_-]?key|authorization|credential)")


def redact_semantic_payload(value: Any) -> Any:
    if isinstance(value, str):
        return redacted(value)
    if isinstance(value, list):
        return [redact_semantic_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_semantic_payload(item) for item in value]
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            key_text = str(key)
            result[key_text] = "[REDACTED]" if _SENSITIVE_KEY_RE.search(key_text) else redact_semantic_payload(item)
        return result
    return value
