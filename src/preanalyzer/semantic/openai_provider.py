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
        response = self._client.chat.completions.create(
            model=self.settings.model,
            messages=[
                {"role": "developer", "content": _DEVELOPER_PROMPT},
                {"role": "user", "content": self._context_payload(context)},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = self._message_content(response)
        try:
            payload = json.loads(content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("model output was not valid JSON") from exc
        try:
            return _ACTION_ADAPTER.validate_python(payload)
        except (ValidationError, ValueError, TypeError) as exc:
            raise ValueError("model output did not match semantic action schema") from exc

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
            raise ValueError("model response did not include message content") from exc
        if not isinstance(content, str) or not content.strip():
            raise ValueError("model response did not include message content")
        return content


__all__ = ["OpenAIChatDecisionProvider"]
