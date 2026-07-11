from __future__ import annotations

from typing import Protocol

from pydantic import TypeAdapter, ValidationError

from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.semantic import (
    EvidenceReference,
    SemanticResolution,
    SemanticResolutionStatus,
    SemanticTask,
    VerificationStatus,
)
from preanalyzer.models.semantic_agent import (
    AgentAction,
    ResolutionAction,
    SemanticAgentRunResult,
    SemanticAgentRunStatus,
    SemanticDecisionContext,
    SemanticToolCallRecord,
    ToolCallAction,
    deterministic_tool_call_id,
)
from preanalyzer.models.semantic_tools import SemanticToolResult, SemanticToolResultStatus
from preanalyzer.semantic.budget import SemanticToolSession
from preanalyzer.semantic.tools.common import SemanticToolExecutionContext, redacted
from preanalyzer.semantic.verifier import verify_semantic_resolution


_ACTION_ADAPTER = TypeAdapter(AgentAction)
_CONTINUABLE_TOOL_STATUSES = {
    SemanticToolResultStatus.OK.value,
    SemanticToolResultStatus.NO_MATCH.value,
    SemanticToolResultStatus.NOT_FOUND.value,
    SemanticToolResultStatus.UNSUPPORTED.value,
}


class AgentDecisionProvider(Protocol):
    def decide(self, context: SemanticDecisionContext) -> AgentAction:
        ...


def run_semantic_agent(
    *,
    task: SemanticTask,
    tool_context: SemanticToolExecutionContext,
    decision_provider: AgentDecisionProvider,
    phase1_evidence: EvidenceModel,
) -> SemanticAgentRunResult:
    state = _AgentState(task=task, tool_context=tool_context, phase1_evidence=phase1_evidence)
    if not state.context_matches_task():
        return state.result(SemanticAgentRunStatus.INVALID_ACTION, messages=["task_context_mismatch"])

    while True:
        if state.provider_budget_exhausted():
            return state.budget_exhausted_result()

        context = state.decision_context()
        state.turn_count += 1
        try:
            action = _ACTION_ADAPTER.validate_python(decision_provider.decide(context))
        except (ValidationError, ValueError, TypeError):
            return state.result(SemanticAgentRunStatus.INVALID_ACTION, messages=["invalid_action"])
        except Exception as exc:
            message = _provider_error_message(exc)
            if state.handle_provider_schema_error(message):
                continue
            return state.result(SemanticAgentRunStatus.PROVIDER_ERROR, messages=[message])

        if isinstance(action, ToolCallAction):
            terminal = state.handle_tool_call(action)
            if terminal is not None:
                return terminal
            continue

        if isinstance(action, ResolutionAction):
            return state.handle_resolution(action.resolution)

        return state.result(SemanticAgentRunStatus.INVALID_ACTION, messages=["invalid_action"])


class _AgentState:
    def __init__(self, *, task: SemanticTask, tool_context: SemanticToolExecutionContext, phase1_evidence: EvidenceModel):
        self.task = task
        self.tool_context = tool_context
        self.phase1_evidence = phase1_evidence
        self.session = SemanticToolSession(tool_context, task.budget)
        self.turn_count = 0
        self.tool_results: list[SemanticToolResult] = []
        self.tool_call_records: list[SemanticToolCallRecord] = []
        self.provider_schema_errors: list[str] = []
        self.messages: list[str] = []

    def context_matches_task(self) -> bool:
        return (
            self.tool_context.component_id == self.task.component_id
            and self.tool_context.target_field == self.task.target_field
            and tuple(self.task.allowed_tools) == tuple(self.tool_context.allowed_tools)
        )

    def provider_budget_exhausted(self) -> bool:
        return self.turn_count >= self.task.budget.max_agent_turns or self.session.exhausted

    def decision_context(self) -> SemanticDecisionContext:
        return SemanticDecisionContext(
            task_id=self.task.task_id,
            task_type=str(self.task.task_type),
            component_id=self.task.component_id,
            target_field=self.task.target_field,
            reason=self.task.reason.model_dump(),
            known_candidates=[candidate.model_dump() for candidate in self.task.known_candidates],
            available_tools=list(self.task.allowed_tools),
            collected_evidence=self._collected_evidence(),
            observations=self._observations(),
            remaining_budget=self._remaining_budget(),
        )

    def handle_tool_call(self, action: ToolCallAction) -> SemanticAgentRunResult | None:
        if action.tool_name not in self.task.allowed_tools:
            return self.result(SemanticAgentRunStatus.INVALID_ACTION, messages=["tool_not_allowed"])
        if action.tool_name not in self.session.ledger.distinct_tools:
            if len(self.session.ledger.distinct_tools) + 1 > self.task.budget.max_distinct_tools:
                return self.budget_exhausted_result()

        result = self.session.call(action.tool_name, action.arguments)
        self.tool_results.append(result)
        self.tool_call_records.append(
            SemanticToolCallRecord(
                tool_call_id=deterministic_tool_call_id(
                    self.task.task_id,
                    self.turn_count,
                    action.tool_name,
                    _redact_arguments(action.arguments),
                ),
                turn_index=self.turn_count,
                tool_name=action.tool_name,
                arguments=_redact_arguments(action.arguments),
                result_status=str(result.status),
                evidence_refs=[evidence.evidence_id for evidence in result.evidence],
                usage=result.usage.model_dump(),
            )
        )

        if result.status in {SemanticToolResultStatus.BLOCKED.value, SemanticToolResultStatus.INVALID_INPUT.value}:
            return self.result(SemanticAgentRunStatus.INVALID_ACTION)
        if result.status == SemanticToolResultStatus.ERROR.value:
            return self.result(SemanticAgentRunStatus.TOOL_ERROR)
        if self.session.exhausted:
            return self.budget_exhausted_result()
        if result.status in _CONTINUABLE_TOOL_STATUSES:
            return None
        return self.result(SemanticAgentRunStatus.INVALID_ACTION)

    def handle_provider_schema_error(self, message: str) -> bool:
        if not message.startswith("provider_schema_error"):
            return False
        if self.session.ledger.schema_retries >= self.task.budget.max_schema_retries:
            return False
        self.session.ledger.schema_retries += 1
        self.provider_schema_errors.append(message)
        self.messages.append("provider_schema_retry")
        return True

    def handle_resolution(self, resolution: SemanticResolution) -> SemanticAgentRunResult:
        if resolution.task_id != self.task.task_id:
            return self._verified_result(resolution)
        return self._verified_result(resolution)

    def budget_exhausted_result(self) -> SemanticAgentRunResult:
        resolution = SemanticResolution(
            task_id=self.task.task_id,
            status=SemanticResolutionStatus.BUDGET_EXHAUSTED,
            candidates=[],
            recommended_candidate_id=None,
            analysis_summary=None,
            tool_trace_refs=[],
        )
        return self._verified_result(resolution)

    def _verified_result(self, resolution: SemanticResolution) -> SemanticAgentRunResult:
        verification = verify_semantic_resolution(
            repository_root=self.tool_context.repository_root,
            task=self._task_with_semantic_evidence(),
            resolution=resolution,
            phase1_evidence=self.phase1_evidence,
            tool_results=self.tool_results,
        )
        return self.result(_run_status_for_verification(str(verification.status)), resolution, verification)

    def _task_with_semantic_evidence(self) -> SemanticTask:
        existing = {ref.evidence_id for ref in self.task.evidence_refs}
        semantic_refs: list[EvidenceReference] = []
        for result in self.tool_results:
            for evidence in result.evidence:
                if evidence.evidence_id in existing:
                    continue
                semantic_refs.append(
                    EvidenceReference(
                        evidence_id=evidence.evidence_id,
                        origin="semantic_tool",
                        path=evidence.path,
                        start_line=evidence.start_line,
                        end_line=evidence.end_line,
                    )
                )
                existing.add(evidence.evidence_id)
        return self.task.model_copy(update={"evidence_refs": [*self.task.evidence_refs, *semantic_refs]})

    def result(
        self,
        status: SemanticAgentRunStatus,
        resolution: SemanticResolution | None = None,
        verification_result=None,
        *,
        messages: list[str] | None = None,
    ) -> SemanticAgentRunResult:
        return SemanticAgentRunResult(
            task_id=self.task.task_id,
            status=status,
            resolution=resolution,
            verification_result=verification_result,
            tool_results=[result.model_dump() for result in self.tool_results],
            tool_call_records=self.tool_call_records,
            turn_count=self.turn_count,
            tool_call_count=self.session.ledger.tool_calls,
            distinct_tools_used=len(self.session.ledger.distinct_tools),
            files_read=len(self.session.ledger.files_read),
            source_lines_returned=self.session.ledger.source_lines_returned,
            messages=[*self.messages, *(messages or [])],
        )

    def _collected_evidence(self) -> list[dict]:
        items: list[dict] = []
        for result in self.tool_results:
            for evidence in result.evidence:
                items.append(
                    {
                        "evidence_id": evidence.evidence_id,
                        "tool_name": str(evidence.tool_name),
                        "path": evidence.path,
                        "start_line": evidence.start_line,
                        "end_line": evidence.end_line,
                        "excerpt": evidence.excerpt,
                    }
                )
        return items

    def _observations(self) -> list[dict]:
        observations: list[dict] = []
        for result in self.tool_results:
            for observation in result.observations:
                observations.append({"tool_name": str(result.tool_name), **observation})
        for error_code in self.provider_schema_errors:
            observations.append(
                {
                    "kind": "provider_schema_retry",
                    "error_code": error_code,
                    "instruction": "Return exactly one valid JSON object matching the action and resolution contracts.",
                }
            )
        return observations

    def _remaining_budget(self) -> dict[str, int]:
        return {
            "agent_turns": max(self.task.budget.max_agent_turns - self.turn_count, 0),
            "tool_calls": max(self.task.budget.max_tool_calls - self.session.ledger.tool_calls, 0),
            "distinct_tools": max(self.task.budget.max_distinct_tools - len(self.session.ledger.distinct_tools), 0),
            "files": max(self.task.budget.max_files_read - len(self.session.ledger.files_read), 0),
            "source_lines": max(self.task.budget.max_source_lines - self.session.ledger.source_lines_returned, 0),
        }


def _run_status_for_verification(status: str) -> SemanticAgentRunStatus:
    # Ambiguous and insufficient evidence are completed agent runs, not accepted facts.
    # The verifier preserves those unresolved outcomes for later reconciliation.
    if status in {VerificationStatus.ACCEPTED.value, VerificationStatus.AMBIGUOUS.value, VerificationStatus.INSUFFICIENT_EVIDENCE.value}:
        return SemanticAgentRunStatus.COMPLETED
    if status == VerificationStatus.BUDGET_EXHAUSTED.value:
        return SemanticAgentRunStatus.BUDGET_EXHAUSTED
    if status == VerificationStatus.TOOL_ERROR.value:
        return SemanticAgentRunStatus.TOOL_ERROR
    return SemanticAgentRunStatus.VERIFICATION_REJECTED


def _redact_arguments(value):
    if isinstance(value, str):
        return redacted(value)
    if isinstance(value, list):
        return [_redact_arguments(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_arguments(item) for key, item in value.items()}
    return value


def _provider_error_message(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.startswith("provider_"):
        return code
    text = str(exc).strip().split()[0] if str(exc).strip() else ""
    if text.startswith("provider_"):
        return text
    return "provider_error"
