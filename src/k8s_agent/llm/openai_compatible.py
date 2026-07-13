from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any
from urllib import request

from pydantic import TypeAdapter, ValidationError

from k8s_agent.agent.actions import SemanticActionExecutor
from k8s_agent.llm.gateway import LLMGateway
from preanalyzer.models.semantic_agent import AgentAction, SemanticDecisionContext
from preanalyzer.semantic.openai_provider import SemanticProviderError


_ACTION_ADAPTER = TypeAdapter(AgentAction)

Transport = Callable[[dict[str, Any], int], dict[str, Any]]


class OpenAICompatibleDecisionProvider:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        transport: Transport | None = None,
        api_key: str | None = None,
        timeout_seconds: int = 30,
        max_retries: int = 1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._transport = transport or self._default_transport

    def decide(self, context: SemanticDecisionContext) -> AgentAction:
        payload = self._payload(context)
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                response = self._transport(payload, self.timeout_seconds)
                return _action_from_response(response, context.task_id)
            except TimeoutError as exc:
                if attempt + 1 >= attempts:
                    raise SemanticProviderError("provider_timeout") from exc
        raise SemanticProviderError("provider_timeout")

    def _payload(self, context: SemanticDecisionContext) -> dict[str, Any]:
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return exactly one valid JSON semantic action. Use only available tools.",
                },
                {"role": "user", "content": json.dumps(context.model_dump(), sort_keys=True, separators=(",", ":"))},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        return {
            "url": f"{self.base_url}/chat/completions",
            "headers": _headers(self.api_key),
            "body": body,
            "method": "POST",
        }

    def _default_transport(self, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
        return _json_request(payload, timeout_seconds)


def semantic_executor_from_env(env: dict[str, str] | None = None) -> SemanticActionExecutor | None:
    settings = env or os.environ
    base_url = settings.get("K8S_AGENT_LLM_BASE_URL") or settings.get("SEMANTIC_LLM_BASE_URL")
    if not base_url:
        return None
    timeout_seconds = int(settings.get("K8S_AGENT_LLM_TIMEOUT_SECONDS") or settings.get("SEMANTIC_LLM_TIMEOUT_SECONDS") or "30")
    api_key = settings.get("K8S_AGENT_LLM_API_KEY") or settings.get("SEMANTIC_LLM_API_KEY")
    model = settings.get("K8S_AGENT_LLM_MODEL") or settings.get("SEMANTIC_LLM_MODEL")
    if not model:
        model = resolve_model_id(base_url, api_key=api_key, timeout_seconds=timeout_seconds)
    provider = OpenAICompatibleDecisionProvider(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    return SemanticActionExecutor(gateway=LLMGateway(provider=provider, provider_name="openai_compatible", model=model))


def resolve_model_id(
    base_url: str,
    *,
    api_key: str | None = None,
    timeout_seconds: int = 30,
    transport: Transport | None = None,
) -> str:
    payload = {
        "url": f"{base_url.rstrip('/')}/models",
        "headers": _headers(api_key),
        "method": "GET",
    }
    response = (transport or _json_request)(payload, timeout_seconds)
    data = response.get("data")
    if not isinstance(data, list):
        raise SemanticProviderError("provider_empty_response")
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
            return item["id"]
    raise SemanticProviderError("provider_empty_response")


def _headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _json_request(payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    body = payload.get("body")
    data = json.dumps(body, sort_keys=True).encode("utf-8") if body is not None else None
    req = request.Request(
        payload["url"],
        data=data,
        headers=payload["headers"],
        method=payload.get("method", "POST"),
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _action_from_response(response: dict[str, Any], task_id: str) -> AgentAction:
    content = _message_content(response)
    try:
        payload = json.loads(_strip_code_fence(content))
    except (TypeError, json.JSONDecodeError) as exc:
        raise SemanticProviderError("provider_schema_error") from exc
    if isinstance(payload, dict) and payload.get("action_type") == "resolution":
        resolution = payload.get("resolution")
        if isinstance(resolution, dict):
            resolution["task_id"] = task_id
    try:
        return _ACTION_ADAPTER.validate_python(payload)
    except (ValidationError, ValueError, TypeError) as exc:
        raise SemanticProviderError("provider_schema_error") from exc


def _message_content(response: dict[str, Any]) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SemanticProviderError("provider_empty_response") from exc
    if not isinstance(content, str) or not content.strip():
        raise SemanticProviderError("provider_empty_response")
    return content


def _strip_code_fence(content: str) -> str:
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
