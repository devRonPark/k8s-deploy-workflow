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
- Follow tool_contracts exactly. Unknown, missing, null, or wrongly typed arguments are invalid.
- Tool path arguments must be component-relative paths: no leading slash, no repository prefix, no '..'.
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
            raise SemanticProviderError(_schema_error_code(payload)) from exc

    def _build_client(self, settings: SemanticLLMSettings):
        from openai import OpenAI

        return OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
        )

    def _context_payload(self, context: SemanticDecisionContext) -> str:
        payload = context.model_dump()
        payload["action_policy"] = [
            "Do not repeat a tool call with the same tool_name and arguments.",
            "If observations contain kind=exec_command or kind=runtime_command with command_text, use that command_text as a grounded candidate instead of calling another tool.",
            "If a tool result was unsupported, no_match, not_found, blocked, or invalid_input, do not call the same tool with the same arguments again.",
            "Return a resolution as soon as collected evidence directly grounds the runtime command.",
        ]
        payload["resolution_contract"] = _resolution_contract(context)
        payload["tool_contracts"] = _tool_contracts(context.available_tools)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

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


def _schema_error_code(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "provider_schema_error"
    action_type = payload.get("action_type")
    if action_type == "tool_call":
        return "provider_schema_error_tool_call"
    if action_type != "resolution":
        return "provider_schema_error_action_type"
    resolution = payload.get("resolution")
    if not isinstance(resolution, dict):
        return "provider_schema_error_resolution"
    candidates = resolution.get("candidates")
    recommended = resolution.get("recommended_candidate_id")
    if resolution.get("status") == "resolved":
        if not candidates:
            return "provider_schema_error_resolution_candidates"
        candidate_ids = {candidate.get("candidate_id") for candidate in candidates if isinstance(candidate, dict)}
        if recommended not in candidate_ids:
            return "provider_schema_error_resolution_recommendation"
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                return "provider_schema_error_candidate"
            if candidate.get("classification") != "llm_semantic_inference":
                return "provider_schema_error_candidate_classification"
            if candidate.get("confidence") not in {"low", "medium"}:
                return "provider_schema_error_candidate_confidence"
    return "provider_schema_error_resolution"


def _tool_contracts(available_tools: list[str]) -> dict[str, dict[str, Any]]:
    all_contracts: dict[str, dict[str, Any]] = {
        "search_code": {
            "purpose": "Search source text inside the component.",
            "arguments": {
                "query": "required non-empty string",
                "path_prefix": "optional component-relative path",
                "max_matches": "optional integer 1-50",
                "context_lines": "optional integer 0-5",
                "case_sensitive": "optional boolean",
            },
            "path_rule": "path_prefix is a component-relative path with no leading slash, no repository prefix, and no '..'.",
        },
        "read_source_range": {
            "purpose": "Read a bounded source line range from one component file.",
            "arguments": {
                "path": "required component-relative path",
                "start_line": "required integer >= 1",
                "end_line": "required integer >= start_line",
            },
            "path_rule": "path is component-relative, for example entrypoint.sh; do not use /entrypoint.sh or backend/entrypoint.sh for a backend component.",
        },
        "inspect_entrypoint_script": {
            "purpose": "Inspect a shell entrypoint script and return grounded command observations.",
            "arguments": {
                "path": "required component-relative script path",
                "max_candidates": "optional integer 1-20",
            },
            "path_rule": "path is component-relative, for example entrypoint.sh; do not use an absolute path, repository prefix, or '..'.",
        },
        "find_command_target": {
            "purpose": "Find source files likely referenced by a runtime command.",
            "arguments": {
                "command": "required non-empty command string",
                "max_results": "optional integer 1-20",
            },
        },
    }
    return {tool: all_contracts[tool] for tool in available_tools if tool in all_contracts}


def _resolution_contract(context: SemanticDecisionContext) -> dict[str, Any]:
    return {
        "resolved_action_shape": {
            "action_type": "resolution",
            "resolution": {
                "task_id": context.task_id,
                "status": "resolved",
                "candidates": [
                    {
                        "candidate_id": "SC-001",
                        "component_id": context.component_id,
                        "target_field": context.target_field,
                        "value": {"command": "exact grounded command string"},
                        "classification": "llm_semantic_inference",
                        "confidence": "low or medium",
                        "evidence_refs": ["use collected_evidence evidence_id values only"],
                    }
                ],
                "recommended_candidate_id": "SC-001",
                "analysis_summary": "short summary without secrets",
                "tool_trace_refs": ["use collected_evidence evidence_id values only"],
            },
        },
        "insufficient_evidence_action_shape": {
            "action_type": "resolution",
            "resolution": {
                "task_id": context.task_id,
                "status": "insufficient_evidence",
                "candidates": [],
                "recommended_candidate_id": None,
                "analysis_summary": "short reason without secrets",
                "tool_trace_refs": [],
            },
        },
        "rules": [
            "Use status resolved only with at least one candidate and recommended_candidate_id.",
            "Candidate confidence must be low or medium; never high.",
            "Candidate classification must be llm_semantic_inference.",
            "Candidate value must be an object with command.",
            "evidence_refs and tool_trace_refs must use collected_evidence evidence_id values, not phase1 ids, tool_call_id values, or file paths.",
        ],
    }


__all__ = ["OpenAIChatDecisionProvider", "SemanticProviderError"]
