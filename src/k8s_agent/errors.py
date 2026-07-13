from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentError(Exception):
    code: str
    exit_code: int
    message: str
    resolution: str
    context: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("AgentError.code is required")
        if self.exit_code <= 0:
            raise ValueError("AgentError.exit_code must be non-zero")
        if not self.message:
            raise ValueError("AgentError.message is required")
        if not self.resolution:
            raise ValueError("AgentError.resolution is required")
        normalized = {str(key): str(value) for key, value in self.context.items()}
        self.context = normalized
        Exception.__init__(self, f"[{self.code}] {self.message}")


def format_agent_error(error: AgentError) -> str:
    lines = [
        f"[{error.code}] {error.message}",
        f"Resolution: {error.resolution}",
    ]
    if error.context:
        lines.append("Context:")
        for key in sorted(error.context):
            lines.append(f"  {key}: {error.context[key]}")
    return "\n".join(lines)
