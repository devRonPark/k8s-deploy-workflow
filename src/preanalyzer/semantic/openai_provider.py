from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import TypeAdapter, ValidationError

from preanalyzer.models.semantic_agent import AgentAction, SemanticDecisionContext
from preanalyzer.semantic.llm_config import SemanticLLMSettings, load_semantic_llm_settings


_ACTION_ADAPTER = TypeAdapter(AgentAction)

_DEVELOPER_PROMPT = """You are a bounded semantic analysis decision provider.
Return exactly one JSON object matching one of these shapes:
{"action_type":"tool_call","tool_name":"...","arguments":{},"reason_code":"..."}
{"action_type":"resolution","resolution":{...}}

Rules:
- Choose exactly one action per turn.
- Use only tool names listed in available_tools.
- Keep tool arguments minimal and component-scoped.
- Do not request repository edits, dependency installation, shell commands, or network access.
- Do not include secret values, passwords, tokens, credentials, or API keys.
- If evidence is insufficient, return an insufficient_evidence resolution.
- If multiple grounded answers conflict, return an ambiguous resolution.
- Resolved candidates must use classification llm_semantic_inference and confidence low or medium.
- Cite only evidence refs visible in the decision context.
"""


class OpenAIChatDecisionProvider:
    """OpenAI-compatible chat completions provider for semantic agent actions."""

    def __init__(self, settings: SemanticLLMSettings, client: Any | None = None):
        self.settings = settings
        self._client = client if client is not None else self._build_client(settings)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> OpenAIChatDecisionProvider:
        return cls(load_semantic_llm_settings(env))

    def decide(self, context: SemanticDecisionContext) -> AgentAction:
        try:
            response = self._client.chat.completions.create(
                model=self.settings.model,
                messages=[
                    {"role": "system", "content": _DEVELOPER_PROMPT},
                    {"role": "user", "content": self._context_payload(context)},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            raise SemanticProviderError(_provider_error_code(exc)) from exc
        content = self._message_content(response)
        try:
            payload = json.loads(content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise SemanticProviderError("provider_schema_error") from exc
        try:
            return _ACTION_ADAPTER.validate_python(payload)
        except (ValidationError, ValueError, TypeError) as exc:
            raise SemanticProviderError("provider_schema_error") from exc

    def _build_client(self, settings: SemanticLLMSettings):
        from openai import OpenAI

        return OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
        )

    def _context_payload(self, context: SemanticDecisionContext) -> str:
        return json.dumps(context.model_dump(), sort_keys=True, separators=(",", ":"))

    def _message_content(self, response) -> str:
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise SemanticProviderError("provider_empty_response") from exc
        if not isinstance(content, str) or not content.strip():
            raise SemanticProviderError("provider_empty_response")
        return content


class SemanticProviderError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _provider_error_code(exc: Exception) -> str:
    status_code = getattr(exc, "status_code", None)
    if status_code in {401, 403}:
        return "provider_auth_error"
    if status_code == 404:
        return "provider_model_or_endpoint_error"
    if isinstance(status_code, int):
        return "provider_http_error"
    name = exc.__class__.__name__.lower()
    if "timeout" in name:
        return "provider_timeout"
    if "connection" in name:
        return "provider_connection_error"
    return "provider_error"


__all__ = ["OpenAIChatDecisionProvider", "SemanticProviderError"]
