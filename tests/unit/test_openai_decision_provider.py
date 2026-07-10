from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from preanalyzer.models.semantic import (
    SemanticCandidate,
    SemanticResolution,
    SemanticResolutionStatus,
)
from preanalyzer.models.semantic_agent import (
    ResolutionAction,
    SemanticDecisionContext,
    ToolCallAction,
)
from preanalyzer.semantic.llm_config import SemanticLLMSettings
from preanalyzer.semantic.openai_provider import OpenAIChatDecisionProvider, SemanticProviderError


def context() -> SemanticDecisionContext:
    return SemanticDecisionContext(
        task_id="ST-001",
        task_type="resolve_runtime_command",
        component_id="backend",
        target_field="/components/backend/runtime/command",
        reason={"code": "missing_runtime_command", "description": "command is missing", "evidence_refs": ["F001"]},
        known_candidates=[],
        available_tools=["search_code", "read_source_range"],
        collected_evidence=[],
        observations=[],
        remaining_budget={"tool_calls": 4, "source_lines": 40},
    )


def settings() -> SemanticLLMSettings:
    return SemanticLLMSettings(
        base_url="https://llm.example.test/v1",
        model="semantic-model",
        api_key="secret-key",
        timeout_seconds=12.0,
    )


def resolution_payload() -> dict:
    return {
        "action_type": "resolution",
        "resolution": SemanticResolution(
            task_id="ST-001",
            status=SemanticResolutionStatus.INSUFFICIENT_EVIDENCE,
            candidates=[],
            recommended_candidate_id=None,
            analysis_summary="No grounded command was found.",
            tool_trace_refs=[],
        ).model_dump(),
    }


class FakeCompletions:
    def __init__(self, content: str):
        self.content = content
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


class FakeClient:
    def __init__(self, content: str):
        self.chat = SimpleNamespace(completions=FakeCompletions(content))

    @property
    def calls(self) -> list[dict]:
        return self.chat.completions.calls


class OpenAIChatDecisionProviderTests(unittest.TestCase):
    def test_sends_bounded_chat_completion_request(self):
        client = FakeClient(json.dumps({"action_type": "tool_call", "tool_name": "search_code", "arguments": {"query": "serve"}}))
        provider = OpenAIChatDecisionProvider(settings(), client=client)

        action = provider.decide(context())

        self.assertIsInstance(action, ToolCallAction)
        request = client.calls[0]
        self.assertEqual(request["model"], "semantic-model")
        self.assertEqual(request["temperature"], 0)
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertEqual([message["role"] for message in request["messages"]], ["system", "user"])
        self.assertNotIn("secret-key", json.dumps(request, sort_keys=True))
        self.assertIn("available_tools", request["messages"][1]["content"])

    def test_parses_tool_call_action(self):
        client = FakeClient(
            json.dumps(
                {
                    "action_type": "tool_call",
                    "tool_name": "read_source_range",
                    "arguments": {"path": "app.py", "start_line": 1, "end_line": 4},
                    "reason_code": "inspect_entrypoint",
                }
            )
        )
        provider = OpenAIChatDecisionProvider(settings(), client=client)

        action = provider.decide(context())

        self.assertIsInstance(action, ToolCallAction)
        self.assertEqual(action.tool_name, "read_source_range")
        self.assertEqual(action.arguments["path"], "app.py")

    def test_parses_resolution_action(self):
        client = FakeClient(json.dumps(resolution_payload()))
        provider = OpenAIChatDecisionProvider(settings(), client=client)

        action = provider.decide(context())

        self.assertIsInstance(action, ResolutionAction)
        self.assertEqual(action.resolution.status, "insufficient_evidence")

    def test_rejects_non_json_content(self):
        provider = OpenAIChatDecisionProvider(settings(), client=FakeClient("not json"))

        with self.assertRaises(SemanticProviderError) as raised:
            provider.decide(context())

        self.assertEqual(raised.exception.code, "provider_schema_error")

    def test_rejects_schema_invalid_content(self):
        provider = OpenAIChatDecisionProvider(settings(), client=FakeClient(json.dumps({"action_type": "tool_call"})))

        with self.assertRaises(SemanticProviderError) as raised:
            provider.decide(context())

        self.assertEqual(raised.exception.code, "provider_schema_error")


if __name__ == "__main__":
    unittest.main()
