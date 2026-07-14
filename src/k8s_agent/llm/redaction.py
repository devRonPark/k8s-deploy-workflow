from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from preanalyzer.semantic.tools.common import redacted


_SENSITIVE_KEY_RE = re.compile(r"(?i)(password|passwd|token|secret|api[_-]?key|authorization|credential)")
_URL_USERINFO_RE = re.compile(r"\b(?P<scheme>https?|ssh)://(?P<userinfo>[^\s/@]+(?:/[^\s/@]+)*?)@(?P<rest>[^\s'\"<>]+)")


class Redactor:
    def redact_text(self, text: str) -> str:
        without_userinfo = _URL_USERINFO_RE.sub(lambda match: f"{match.group('scheme')}://{match.group('rest')}", text)
        return redacted(without_userinfo)

    def redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, list):
            return [self.redact_value(item) for item in value]
        if isinstance(value, tuple):
            return [self.redact_value(item) for item in value]
        if isinstance(value, Mapping):
            result = {}
            for key, item in value.items():
                key_text = str(key)
                result[key_text] = "[REDACTED]" if _SENSITIVE_KEY_RE.search(key_text) else self.redact_value(item)
            return result
        return value


def redact_semantic_payload(value: Any) -> Any:
    return Redactor().redact_value(value)
