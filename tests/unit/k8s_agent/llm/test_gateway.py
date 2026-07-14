from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from k8s_agent.llm.gateway import LLMGateway, SemanticContext
from k8s_agent.llm.openai_compatible import OpenAICompatibleDecisionProvider, resolve_model_id
from preanalyzer.models.evidence import EvidenceFact, EvidenceModel
from preanalyzer.models.rule_inference import ComponentCandidate, RuleInferenceSet
from preanalyzer.models.semantic import (
    EvidenceReference,
    SemanticCandidate,
    SemanticResolution,
    SemanticResolutionStatus,
    SemanticTask,
    SemanticTaskBudget,
    SemanticTaskType,
    TaskReason,
)
from preanalyzer.models.semantic_agent import ResolutionAction, SemanticAgentRunStatus, ToolCallAction


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def evidence(value='["./entrypoint.sh"]') -> EvidenceModel:
    return EvidenceModel(
        facts=[
            EvidenceFact(
                evidence_id="F001",
                fact_type="dockerfile_entrypoint",
                artifact_ref="backend/Dockerfile",
                source="dockerfile_entrypoint",
                classification="observed_fact",
                value=value,
            )
        ]
    )


def rules() -> RuleInferenceSet:
    return RuleInferenceSet(
        component_candidates=[
            ComponentCandidate(component_id="backend", root_path="backend", source="test", evidence_refs=["F001"])
        ]
    )


def task(*, allowed_tools: list[str] | None = None) -> SemanticTask:
    return SemanticTask(
        task_id="ST-001",
        task_type=SemanticTaskType.RESOLVE_RUNTIME_COMMAND,
        component_id="backend",
        target_field="/components/backend/runtime/command",
        reason=TaskReason(code="shell_script_entrypoint", description="script needs inspection", evidence_refs=["F001"]),
        evidence_refs=[EvidenceReference(evidence_id="F001", origin="phase1")],
        allowed_tools=allowed_tools or ["read_source_range"],
        budget=SemanticTaskBudget(max_agent_turns=4, max_tool_calls=4, max_source_lines=40),
    )


def candidate(*, command: str = "uvicorn main:app --host 0.0.0.0", evidence_refs: list[str]) -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id="SC-001",
        component_id="backend",
        target_field="/components/backend/runtime/command",
        value={"command": command},
        classification="llm_semantic_inference",
        confidence="medium",
        evidence_refs=evidence_refs,
    )


def resolution(*, command: str = "uvicorn main:app --host 0.0.0.0", evidence_refs: list[str]) -> SemanticResolution:
    return SemanticResolution(
        task_id="ST-001",
        status=SemanticResolutionStatus.RESOLVED,
        candidates=[candidate(command=command, evidence_refs=evidence_refs)],
        recommended_candidate_id="SC-001",
        tool_trace_refs=evidence_refs,
    )


class CapturingProvider:
    def __init__(self, actions):
        self.actions = list(actions)
        self.contexts = []

    def decide(self, context):
        self.contexts.append(context)
        if not self.actions:
            raise RuntimeError("provider_model_or_endpoint_error")
        action = self.actions.pop(0)
        if action == "resolve_from_context":
            evidence_id = context.collected_evidence[0]["evidence_id"]
            return ResolutionAction(resolution=resolution(evidence_refs=[evidence_id]))
        return action


class GatewayTests(unittest.TestCase):
    def execute(self, repo: Path, provider, *, task_obj: SemanticTask | None = None, evidence_model: EvidenceModel | None = None):
        return LLMGateway(provider=provider, provider_name="fake", model="fake-model").execute(
            task_obj or task(),
            SemanticContext(repository_root=repo, evidence=evidence_model or evidence(), rules=rules()),
        )

    def test_provider_context_is_redacted_before_decision(self):
        provider = CapturingProvider([])
        with tempfile.TemporaryDirectory() as tmp:
            result = self.execute(
                Path(tmp),
                provider,
                evidence_model=evidence({"DATABASE_PASSWORD": "changethis", "Authorization": "Bearer abc.def"}),
            )

        self.assertEqual(result.status, SemanticAgentRunStatus.PROVIDER_ERROR)
        self.assertNotIn("changethis", provider.contexts[0].model_dump_json())
        self.assertNotIn("abc.def", provider.contexts[0].model_dump_json())

    def test_tool_outside_task_allowlist_is_rejected_before_execution(self):
        provider = CapturingProvider([ToolCallAction(tool_name="search_code", arguments={"query": "uvicorn"})])
        with tempfile.TemporaryDirectory() as tmp:
            result = self.execute(Path(tmp), provider, task_obj=task(allowed_tools=["read_source_range"]))

        self.assertEqual(result.status, SemanticAgentRunStatus.INVALID_ACTION)
        self.assertEqual(result.run.tool_call_count, 0)

    def test_provider_schema_error_retries_then_accepts_valid_action(self):
        provider = CapturingProvider([
            RuntimeError("provider_schema_error"),
            ToolCallAction(tool_name="read_source_range", arguments={"path": "entrypoint.sh", "start_line": 1, "end_line": 1}),
            "resolve_from_context",
        ])

        class RaisingProvider(CapturingProvider):
            def decide(self, context):
                self.contexts.append(context)
                action = self.actions.pop(0)
                if isinstance(action, Exception):
                    raise action
                if action == "resolve_from_context":
                    evidence_id = context.collected_evidence[0]["evidence_id"]
                    return ResolutionAction(resolution=resolution(evidence_refs=[evidence_id]))
                return action

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "entrypoint.sh", "exec uvicorn main:app --host 0.0.0.0\n")
            result = self.execute(repo, RaisingProvider(provider.actions))

        self.assertEqual(result.status, SemanticAgentRunStatus.COMPLETED)
        self.assertEqual(result.verification_status, "accepted")
        self.assertIn("provider_schema_retry", result.run.messages)

    def test_openai_compatible_transport_retries_timeout_and_rejects_invalid_schema(self):
        calls = []

        def transport(payload, timeout_seconds):
            calls.append((payload, timeout_seconds))
            if len(calls) == 1:
                raise TimeoutError("slow model")
            return {"choices": [{"message": {"content": json.dumps({"action_type": "tool_call", "tool_name": "read_source_range", "arguments": {"path": "entrypoint.sh", "start_line": 1, "end_line": 1}})}}]}

        provider = OpenAICompatibleDecisionProvider(
            base_url="http://llm.test/v1",
            model="local-model",
            transport=transport,
            timeout_seconds=3,
            max_retries=1,
        )

        action = provider.decide(_minimal_context())

        self.assertEqual(action.tool_name, "read_source_range")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("Authorization", calls[0][0]["headers"])

        bad = OpenAICompatibleDecisionProvider(
            base_url="http://llm.test/v1",
            model="local-model",
            transport=lambda payload, timeout_seconds: {"choices": [{"message": {"content": "not-json"}}]},
        )
        with self.assertRaisesRegex(RuntimeError, "provider_schema_error"):
            bad.decide(_minimal_context())

    def test_provider_unavailable_falls_back_to_structured_result(self):
        provider = CapturingProvider([])
        with tempfile.TemporaryDirectory() as tmp:
            result = self.execute(Path(tmp), provider)

        self.assertEqual(result.status, SemanticAgentRunStatus.PROVIDER_ERROR)
        self.assertEqual(result.verification_status, None)
        self.assertEqual(result.model, "fake-model")

    def test_verifier_rejection_is_not_stored_as_accepted(self):
        provider = CapturingProvider([
            ToolCallAction(tool_name="read_source_range", arguments={"path": "entrypoint.sh", "start_line": 1, "end_line": 1}),
            ResolutionAction(resolution=resolution(command="gunicorn missing:app", evidence_refs=["SE-PENDING"])),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "entrypoint.sh", "exec uvicorn main:app --host 0.0.0.0\n")
            result = self.execute(repo, provider)

        self.assertEqual(result.status, SemanticAgentRunStatus.VERIFICATION_REJECTED)
        self.assertEqual(result.verification_status, "rejected")
        self.assertEqual(result.accepted_commands, [])

    def test_resolve_model_id_fetches_models_without_authorization_when_key_absent(self):
        calls = []

        def transport(payload, timeout_seconds):
            calls.append((payload, timeout_seconds))
            return {"data": [{"id": "local-model"}]}

        model = resolve_model_id("http://llm.test/v1", api_key=None, timeout_seconds=7, transport=transport)

        self.assertEqual(model, "local-model")
        self.assertEqual(calls[0][0]["url"], "http://llm.test/v1/models")
        self.assertEqual(calls[0][0]["headers"], {"Content-Type": "application/json"})
        self.assertEqual(calls[0][1], 7)


def _minimal_context():
    from preanalyzer.models.semantic_agent import SemanticDecisionContext

    return SemanticDecisionContext(
        task_id="ST-001",
        task_type="resolve_runtime_command",
        component_id="backend",
        target_field="/components/backend/runtime/command",
        reason={"code": "test"},
        available_tools=["read_source_range"],
        remaining_budget={"tool_calls": 1},
    )


if __name__ == "__main__":
    unittest.main()
