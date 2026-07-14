from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from k8s_agent.llm.redaction import redact_semantic_payload
from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.rule_inference import RuleInferenceSet
from preanalyzer.models.semantic import SemanticTask
from preanalyzer.models.semantic_agent import AgentAction, SemanticAgentRunResult, SemanticAgentRunStatus, SemanticDecisionContext
from preanalyzer.semantic.agent import run_semantic_agent
from preanalyzer.semantic.tools import build_semantic_tool_context
from preanalyzer.semantic.tools.common import SemanticToolContextBuildError


PROMPT_VERSION = "runtime-command-semantic/v1"


class DecisionProvider(Protocol):
    def decide(self, context: SemanticDecisionContext) -> AgentAction:
        ...


@dataclass(frozen=True)
class SemanticContext:
    repository_root: Path
    evidence: EvidenceModel
    rules: RuleInferenceSet


class VerifiedSemanticResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, use_enum_values=True)

    task_id: str
    status: SemanticAgentRunStatus
    verification_status: str | None = None
    accepted_commands: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    provider: str
    model: str
    prompt_version: str
    run: SemanticAgentRunResult


class LLMGateway:
    def __init__(
        self,
        *,
        provider: DecisionProvider,
        provider_name: str,
        model: str,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self.provider = provider
        self.provider_name = provider_name
        self.model = model
        self.prompt_version = prompt_version

    def execute(self, task: SemanticTask, context: SemanticContext) -> VerifiedSemanticResult:
        try:
            tool_context = build_semantic_tool_context(context.repository_root, task, context.rules, context.evidence)
        except SemanticToolContextBuildError as exc:
            run = SemanticAgentRunResult(
                task_id=task.task_id,
                status=SemanticAgentRunStatus.INVALID_ACTION,
                messages=[exc.code],
            )
            return self._result(task, run)

        run = run_semantic_agent(
            task=task,
            tool_context=tool_context,
            decision_provider=_RedactingProvider(self.provider),
            phase1_evidence=context.evidence,
        )
        return self._result(task, run)

    def _result(self, task: SemanticTask, run: SemanticAgentRunResult) -> VerifiedSemanticResult:
        del task
        verification_status = None
        if run.verification_result is not None:
            verification_status = str(run.verification_result.status)
        accepted_commands, evidence_refs = _accepted_commands_and_refs(run)
        return VerifiedSemanticResult(
            task_id=run.task_id,
            status=run.status,
            verification_status=verification_status,
            accepted_commands=accepted_commands,
            evidence_refs=evidence_refs,
            provider=self.provider_name,
            model=self.model,
            prompt_version=self.prompt_version,
            run=run,
        )


class _RedactingProvider:
    def __init__(self, delegate: DecisionProvider) -> None:
        self.delegate = delegate

    def decide(self, context: SemanticDecisionContext) -> AgentAction:
        redacted = redact_semantic_payload(context.model_dump())
        return self.delegate.decide(SemanticDecisionContext.model_validate(redacted))


def _accepted_commands_and_refs(run: SemanticAgentRunResult) -> tuple[list[str], list[str]]:
    if run.resolution is None or run.verification_result is None:
        return [], []
    accepted = set(run.verification_result.accepted_candidate_ids)
    commands: list[str] = []
    refs: set[str] = set()
    for candidate in run.resolution.candidates:
        if candidate.candidate_id not in accepted:
            continue
        command = candidate.value.get("command") if isinstance(candidate.value, dict) else candidate.value
        if isinstance(command, str) and command.strip():
            commands.append(command)
        refs.update(candidate.evidence_refs)
    return sorted(dict.fromkeys(commands)), sorted(refs)
