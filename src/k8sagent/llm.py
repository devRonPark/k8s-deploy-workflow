from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, Protocol
from urllib import request

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from k8sagent.changeset import ChangeSet, validate_changeset
from k8sagent.models.intent import AgentKubernetesIntent
from k8sagent.models.topology import ApplicationTopology
from k8sagent.questions import Question

DEFAULT_LOCAL_LLM_BASE_URL = "http://192.168.30.167:30000/v1"


class AgentLLMSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    base_url: str = DEFAULT_LOCAL_LLM_BASE_URL
    model: str | None = None
    timeout_seconds: float = 30.0


class TextResponse(BaseModel):
    text: str


class LLMProtocol(Protocol):
    def explain_analysis(self, topology: ApplicationTopology) -> str | None: ...
    def phrase_question(self, question: Question) -> str | None: ...
    def nl_to_changeset(
        self,
        request: str,
        intent: AgentKubernetesIntent,
        allowed_paths: list[str],
    ) -> ChangeSet | None: ...
    def explain_validation_failure(self, report: Any) -> str | None: ...
    def propose_correction(
        self,
        report_payload: dict,
        intent: AgentKubernetesIntent,
        allowed_paths: list[str],
    ) -> ChangeSet | None: ...


class NoAuthHTTPChatClient:
    def __init__(
        self,
        settings: AgentLLMSettings,
        transport: Callable[..., str] | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport or _default_transport
        self._discovered_model: str | None = None
        self.chat = _ChatNamespace(self)

    def create_completion(self, **kwargs):
        model = kwargs.get("model") or self._model_id()
        payload = dict(kwargs)
        payload["model"] = model
        content = self._transport(
            "POST",
            f"{self.settings.base_url.rstrip('/')}/chat/completions",
            {"Content-Type": "application/json"},
            json.dumps(payload, sort_keys=True).encode("utf-8"),
            self.settings.timeout_seconds,
        )
        data = json.loads(content)
        return _response(data["choices"][0]["message"]["content"])

    def _model_id(self) -> str:
        if self.settings.model:
            return self.settings.model
        if self._discovered_model is None:
            content = self._transport(
                "GET",
                f"{self.settings.base_url.rstrip('/')}/models",
                {"Content-Type": "application/json"},
                None,
                self.settings.timeout_seconds,
            )
            data = json.loads(content)
            models = data.get("data") or []
            if not models or not isinstance(models[0].get("id"), str):
                raise ValueError("no model id returned from local endpoint")
            self._discovered_model = models[0]["id"]
        return self._discovered_model


class _ChatNamespace:
    def __init__(self, client: NoAuthHTTPChatClient) -> None:
        self.completions = _CompletionsNamespace(client)


class _CompletionsNamespace:
    def __init__(self, client: NoAuthHTTPChatClient) -> None:
        self._client = client

    def create(self, **kwargs):
        return self._client.create_completion(**kwargs)


def _response(content: str):
    class Message:
        def __init__(self, content: str) -> None:
            self.content = content

    class Choice:
        def __init__(self, content: str) -> None:
            self.message = Message(content)

    class Response:
        def __init__(self, content: str) -> None:
            self.choices = [Choice(content)]

    return Response(content)


def _default_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None = None,
    timeout: float = 30.0,
) -> str:
    req = request.Request(url, data=body, headers=dict(headers), method=method)
    with request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8")


class AgentLLMClient:
    def __init__(self, settings: AgentLLMSettings, client: Any | None = None):
        self.settings = settings
        self._client = client if client is not None else NoAuthHTTPChatClient(settings)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AgentLLMClient | None":
        values = env or {}
        try:
            timeout = float(values.get("K8S_AGENT_LLM_TIMEOUT_SECONDS", "30.0"))
            settings = AgentLLMSettings(
                base_url=values.get("K8S_AGENT_LLM_BASE_URL", DEFAULT_LOCAL_LLM_BASE_URL),
                model=values.get("K8S_AGENT_LLM_MODEL") or None,
                timeout_seconds=timeout,
            )
        except (TypeError, ValueError):
            return None
        return cls(settings)

    def explain_analysis(self, topology: ApplicationTopology | dict) -> str | None:
        payload = topology.model_dump(mode="json") if hasattr(topology, "model_dump") else topology
        result = self._call_json(
            "Summarize this Kubernetes deployment analysis. Return JSON {\"text\":\"...\"}.",
            {"topology": payload},
            TypeAdapter(TextResponse),
        )
        return result.text if result is not None else None

    def phrase_question(self, question: Question) -> str | None:
        result = self._call_json(
            "Rewrite this question clearly. Return JSON {\"text\":\"...\"}.",
            {"question": question.model_dump(mode="json")},
            TypeAdapter(TextResponse),
        )
        return result.text if result is not None else None

    def nl_to_changeset(
        self,
        request_text: str,
        intent: AgentKubernetesIntent,
        allowed_paths: list[str],
    ) -> ChangeSet | None:
        system = (
            "Convert a natural-language Kubernetes intent request into one JSON ChangeSet. "
            "Use only allowed_paths. Do not output YAML or secret values."
        )
        return self._changeset_op(
            system,
            {
                "request": request_text,
                "intent": intent.model_dump(mode="json"),
                "allowed_paths": allowed_paths,
            },
            intent,
            allowed_paths,
            forced_origin="nl_request",
        )

    def explain_validation_failure(self, report: Any) -> str | None:
        payload = report.model_dump(mode="json") if hasattr(report, "model_dump") else report
        result = self._call_json(
            "Explain this Kubernetes validation failure. Return JSON {\"text\":\"...\"}.",
            {"report": payload},
            TypeAdapter(TextResponse),
        )
        return result.text if result is not None else None

    def propose_correction(
        self,
        report_payload: dict,
        intent: AgentKubernetesIntent,
        allowed_paths: list[str],
    ) -> ChangeSet | None:
        system = (
            "Propose a minimal Kubernetes intent correction as one JSON ChangeSet. "
            "Use only allowed_paths. Do not output YAML or secret values."
        )
        return self._changeset_op(
            system,
            {
                "report": report_payload,
                "intent": intent.model_dump(mode="json"),
                "allowed_paths": allowed_paths,
            },
            intent,
            allowed_paths,
            forced_origin="correction",
        )

    def _changeset_op(
        self,
        system: str,
        payload: dict,
        intent: AgentKubernetesIntent,
        allowed_paths: list[str],
        *,
        forced_origin: str,
    ) -> ChangeSet | None:
        adapter = TypeAdapter(ChangeSet)
        result = self._call_json(system, payload, adapter)
        if result is None:
            return None
        updated = result.model_copy(update={"origin": forced_origin})
        if any(change.path not in allowed_paths for change in updated.changes):
            retry = self._call_json(system, {**payload, "error": "path_not_allowed"}, adapter)
            if retry is None:
                return None
            updated = retry.model_copy(update={"origin": forced_origin})
        if any(change.path not in allowed_paths for change in updated.changes):
            return None
        try:
            validate_changeset(updated, intent)
        except Exception:
            return None
        return updated

    def _call_json(self, system: str, payload: dict, adapter: TypeAdapter):
        for attempt in range(2):
            try:
                response = self._client.chat.completions.create(
                    model=self.settings.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": json.dumps(payload, sort_keys=True)},
                    ],
                    temperature=0,
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content
                parsed = json.loads(_strip_code_fence(raw))
                return adapter.validate_python(parsed)
            except (Exception, ValidationError, json.JSONDecodeError, TypeError, IndexError, AttributeError):
                if attempt == 1:
                    return None
                payload = {**payload, "error": "previous_response_invalid"}
        return None


# Same code-fence normalization pattern as preanalyzer.semantic.openai_provider,
# kept local because that helper is private.
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
