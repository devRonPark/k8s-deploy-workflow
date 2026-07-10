from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, field_validator


DEFAULT_TIMEOUT_SECONDS = 30.0


class SemanticLLMConfigError(ValueError):
    """Configuration error that reports variable names, not secret values."""


class SemanticLLMSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    base_url: str
    model: str
    api_key: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @field_validator("base_url", "model", "api_key")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def _positive_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("timeout must be positive")
        return value


def load_semantic_llm_settings(env: Mapping[str, str] | None = None) -> SemanticLLMSettings:
    values = env if env is not None else os.environ
    missing = [
        name
        for name in ("SEMANTIC_LLM_BASE_URL", "SEMANTIC_LLM_MODEL", "SEMANTIC_LLM_API_KEY")
        if not values.get(name, "").strip()
    ]
    if missing:
        raise SemanticLLMConfigError(f"missing required semantic LLM settings: {', '.join(missing)}")

    raw_timeout = values.get("SEMANTIC_LLM_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise SemanticLLMConfigError("invalid semantic LLM setting: SEMANTIC_LLM_TIMEOUT_SECONDS") from exc

    try:
        return SemanticLLMSettings(
            base_url=str(values["SEMANTIC_LLM_BASE_URL"]),
            model=str(values["SEMANTIC_LLM_MODEL"]),
            api_key=str(values["SEMANTIC_LLM_API_KEY"]),
            timeout_seconds=timeout,
        )
    except ValueError as exc:
        raise SemanticLLMConfigError("invalid semantic LLM settings") from exc


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "SemanticLLMConfigError",
    "SemanticLLMSettings",
    "load_semantic_llm_settings",
]
