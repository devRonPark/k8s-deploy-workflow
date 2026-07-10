from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
from preanalyzer.semantic.agent import run_semantic_agent
from preanalyzer.semantic.fake_provider import ScriptedFakeDecisionProvider
from preanalyzer.semantic.tools import build_semantic_tool_context


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def phase1_evidence() -> EvidenceModel:
    return EvidenceModel(
        facts=[
            EvidenceFact(
                evidence_id="F001",
                fact_type="dockerfile_cmd",
                artifact_ref="backend/Dockerfile",
                source="dockerfile_cmd",
                classification="observed_fact",
                value='["./entrypoint.sh"]',
            )
        ]
    )


def rules() -> RuleInferenceSet:
    return RuleInferenceSet(
        component_candidates=[
            ComponentCandidate(component_id="backend", root_path="backend", source="test", evidence_refs=["F001"])
        ]
    )


def task(*, allowed_tools: list[str] | None = None, budget: SemanticTaskBudget | None = None) -> SemanticTask:
    return SemanticTask(
        task_id="ST-001",
        task_type=SemanticTaskType.RESOLVE_RUNTIME_COMMAND,
        component_id="backend",
        target_field="/components/backend/runtime/command",
        reason=TaskReason(code="shell_script_entrypoint", description="script needs inspection", evidence_refs=["F001"]),
        evidence_refs=[EvidenceReference(evidence_id="F001", origin="phase1")],
        allowed_tools=allowed_tools or ["read_source_range", "inspect_entrypoint_script"],
        budget=budget or SemanticTaskBudget(max_agent_turns=4, max_tool_calls=4, max_source_lines=40),
    )


def candidate(*, evidence_refs: list[str], command: str = "uvicorn main:app --host 0.0.0.0") -> SemanticCandidate:
    return SemanticCandidate(
        candidate_id="SC-001",
        component_id="backend",
        target_field="/components/backend/runtime/command",
        value={"command": command},
        classification="llm_semantic_inference",
        confidence="medium",
        evidence_refs=evidence_refs,
    )


def resolution(*, evidence_refs: list[str], command: str = "uvicorn main:app --host 0.0.0.0") -> SemanticResolution:
    return SemanticResolution(
        task_id="ST-001",
        status=SemanticResolutionStatus.RESOLVED,
        candidates=[candidate(evidence_refs=evidence_refs, command=command)],
        recommended_candidate_id="SC-001",
        tool_trace_refs=evidence_refs,
    )


class SemanticAgentTests(unittest.TestCase):
    def make_context(self, repo: Path, task_obj: SemanticTask):
        return build_semantic_tool_context(repo, task_obj, rules(), phase1_evidence())

    def test_single_tool_then_verified_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "entrypoint.sh", "exec uvicorn main:app --host 0.0.0.0\n")
            task_obj = task()
            provider = ToolThenResolveFromContextProvider()

            result = run_semantic_agent(
                task=task_obj,
                tool_context=self.make_context(repo, task_obj),
                decision_provider=provider,
                phase1_evidence=phase1_evidence(),
            )

        self.assertEqual(result.status, SemanticAgentRunStatus.COMPLETED)
        self.assertEqual(result.verification_result.status, "accepted")
        self.assertEqual(result.turn_count, 2)
        self.assertEqual(result.tool_call_count, 1)
        self.assertRegex(result.tool_call_records[0].tool_call_id, r"^TC-[A-F0-9]{12}$")
        self.assertEqual(provider.call_count, 2)

    def test_next_context_contains_observations_and_remaining_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "entrypoint.sh", "exec uvicorn main:app --host 0.0.0.0\n")
            task_obj = task()
            provider = ScriptedFakeDecisionProvider([
                ToolCallAction(
                    tool_name="read_source_range",
                    arguments={"path": "entrypoint.sh", "start_line": 1, "end_line": 1},
                ),
                ResolutionAction(resolution=resolution(evidence_refs=["SE-PENDING"])),
            ])

            run_semantic_agent(
                task=task_obj,
                tool_context=self.make_context(repo, task_obj),
                decision_provider=provider,
                phase1_evidence=phase1_evidence(),
            )

        second_context = provider.contexts[1]
        self.assertEqual(second_context.available_tools, ["read_source_range", "inspect_entrypoint_script"])
        self.assertEqual(second_context.remaining_budget["tool_calls"], 3)
        self.assertEqual(len(second_context.collected_evidence), 1)
        self.assertNotIn(str(repo), str(second_context.model_dump()))

    def test_unauthorized_tool_is_blocked_before_registry(self):
        task_obj = task(allowed_tools=["read_source_range"])
        provider = ScriptedFakeDecisionProvider([
            ToolCallAction(tool_name="search_code", arguments={"query": "uvicorn"}),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            result = run_semantic_agent(
                task=task_obj,
                tool_context=self.make_context(Path(tmp), task_obj),
                decision_provider=provider,
                phase1_evidence=phase1_evidence(),
            )

        self.assertEqual(result.status, SemanticAgentRunStatus.INVALID_ACTION)
        self.assertEqual(result.tool_call_count, 0)
        self.assertEqual(provider.call_count, 1)

    def test_budget_exhaustion_stops_before_provider_recall(self):
        budget = SemanticTaskBudget(max_agent_turns=4, max_tool_calls=1, max_source_lines=40)
        task_obj = task(budget=budget)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "entrypoint.sh", "exec uvicorn main:app --host 0.0.0.0\n")
            provider = ScriptedFakeDecisionProvider([
                ToolCallAction(
                    tool_name="read_source_range",
                    arguments={"path": "entrypoint.sh", "start_line": 1, "end_line": 1},
                ),
                ResolutionAction(resolution=resolution(evidence_refs=["SE-PENDING"])),
            ])

            result = run_semantic_agent(
                task=task_obj,
                tool_context=self.make_context(repo, task_obj),
                decision_provider=provider,
                phase1_evidence=phase1_evidence(),
            )

        self.assertEqual(result.status, SemanticAgentRunStatus.BUDGET_EXHAUSTED)
        self.assertEqual(result.verification_result.status, "budget_exhausted")
        self.assertEqual(provider.call_count, 1)

    def test_tool_error_statuses_map_to_terminal_statuses(self):
        cases = [
            ("blocked", SemanticAgentRunStatus.INVALID_ACTION),
            ("invalid_input", SemanticAgentRunStatus.INVALID_ACTION),
            ("error", SemanticAgentRunStatus.TOOL_ERROR),
        ]
        for expected_tool_status, expected_run_status in cases:
            with self.subTest(expected_tool_status=expected_tool_status):
                task_obj = task(allowed_tools=["read_source_range"])
                arguments = {"path": "../outside", "start_line": 1, "end_line": 1}
                if expected_tool_status == "invalid_input":
                    arguments = {"path": "missing.py", "start_line": "x", "end_line": 1}
                if expected_tool_status == "error":
                    arguments = {"path": "entrypoint.sh", "start_line": 1, "end_line": 1}

                with tempfile.TemporaryDirectory() as tmp:
                    repo = Path(tmp)
                    if expected_tool_status == "error":
                        write(repo / "backend" / "entrypoint.sh", "ok\n")
                    provider = ScriptedFakeDecisionProvider([
                        ToolCallAction(tool_name="read_source_range", arguments=arguments),
                    ])
                    context = self.make_context(repo, task_obj)
                    if expected_tool_status == "error":
                        object.__setattr__(context, "component_root", None)
                    result = run_semantic_agent(
                        task=task_obj,
                        tool_context=context,
                        decision_provider=provider,
                        phase1_evidence=phase1_evidence(),
                    )

                self.assertEqual(result.status, expected_run_status)

    def test_provider_error_is_structured(self):
        task_obj = task()
        provider = ScriptedFakeDecisionProvider([])

        with tempfile.TemporaryDirectory() as tmp:
            result = run_semantic_agent(
                task=task_obj,
                tool_context=self.make_context(Path(tmp), task_obj),
                decision_provider=provider,
                phase1_evidence=phase1_evidence(),
            )

        self.assertEqual(result.status, SemanticAgentRunStatus.PROVIDER_ERROR)
        self.assertIn("provider_error", result.messages)

    def test_hallucinated_candidate_is_verification_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "entrypoint.sh", "exec uvicorn main:app --host 0.0.0.0\n")
            task_obj = task()
            provider = ScriptedFakeDecisionProvider([
                ToolCallAction(
                    tool_name="read_source_range",
                    arguments={"path": "entrypoint.sh", "start_line": 1, "end_line": 1},
                ),
                ResolutionAction(resolution=resolution(evidence_refs=["SE-PENDING"], command="gunicorn missing:app")),
            ])

            result = run_semantic_agent(
                task=task_obj,
                tool_context=self.make_context(repo, task_obj),
                decision_provider=provider,
                phase1_evidence=phase1_evidence(),
            )

        self.assertEqual(result.status, SemanticAgentRunStatus.VERIFICATION_REJECTED)
        self.assertEqual(result.verification_result.status, "rejected")

    def test_same_script_produces_same_dump(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "backend" / "entrypoint.sh", "exec uvicorn main:app --host 0.0.0.0\n")
            task_obj = task()
            actions = [
                ToolCallAction(
                    tool_name="read_source_range",
                    arguments={"end_line": 1, "path": "entrypoint.sh", "start_line": 1},
                ),
                ResolutionAction(resolution=resolution(evidence_refs=["SE-PENDING"])),
            ]

            first = run_semantic_agent(
                task=task_obj,
                tool_context=self.make_context(repo, task_obj),
                decision_provider=ScriptedFakeDecisionProvider(actions),
                phase1_evidence=phase1_evidence(),
            )
            second = run_semantic_agent(
                task=task_obj,
                tool_context=self.make_context(repo, task_obj),
                decision_provider=ScriptedFakeDecisionProvider(actions),
                phase1_evidence=phase1_evidence(),
            )

        self.assertEqual(first.model_dump(), second.model_dump())


class ToolThenResolveFromContextProvider:
    def __init__(self):
        self.contexts = []

    @property
    def call_count(self) -> int:
        return len(self.contexts)

    def decide(self, context):
        self.contexts.append(context)
        if not context.collected_evidence:
            return ToolCallAction(
                tool_name="read_source_range",
                arguments={"path": "entrypoint.sh", "start_line": 1, "end_line": 1},
            )
        evidence_id = context.collected_evidence[0]["evidence_id"]
        return ResolutionAction(resolution=resolution(evidence_refs=[evidence_id]))


if __name__ == "__main__":
    unittest.main()
