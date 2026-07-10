from __future__ import annotations

from dataclasses import dataclass
import json


# Deterministic, non-sensitive error codes shared across parsers so that
# pipeline warnings can be grouped and asserted on without matching free-form
# messages. Codes are stable identifiers; messages remain human-readable.
CODE_INVALID_YAML = "invalid_yaml"
CODE_INVALID_JSON = "invalid_json"
CODE_INVALID_XML = "invalid_xml"
CODE_INVALID_TOML = "invalid_toml"
CODE_INVALID_ENCODING = "invalid_encoding"
CODE_INVALID_SYNTAX = "invalid_syntax"
CODE_READ_ERROR = "read_error"
CODE_PARSE_ERROR = "parse_error"


@dataclass(frozen=True)
class ParseWarning:
    """Uniform, non-fatal parser failure record.

    Every parser degrades a recoverable failure into one of these instead of
    raising into the pipeline. ``path`` is the repository-relative artifact
    path (never an absolute host path), ``code`` is a stable identifier from
    the ``CODE_*`` constants, and ``message`` is a human-readable summary with
    no sensitive values.
    """

    path: str
    parser: str
    message: str
    code: str = CODE_PARSE_ERROR
    fatal: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "parser": self.parser,
            "code": self.code,
            "message": self.message,
            "fatal": self.fatal,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True)


def is_parse_warning(value: object) -> bool:
    return isinstance(value, ParseWarning)
