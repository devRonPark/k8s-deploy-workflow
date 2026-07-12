"""결정론이 LLM 필요 지점만 SemanticTask로 빌드 (1 태스크=1 target_field). 안전 하네스."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field

from preanalyzer.models.runtime_command_analysis import (
    ResolvedRuntimeCommand,
    RuntimeCommandAlternative,
    RuntimeCommandAnalysis,
    RuntimeCommandGap,
    RuntimeCommandGapReason,
)
from preanalyzer.models.semantic import (
    EvidenceReference,
    KnownCandidate,
    SemanticTask,
    SemanticTaskBuildDecision,
    SemanticTaskBuildDisposition,
    SemanticTaskBuildResult,
    SemanticTaskType,
    TaskReason,
)


TARGET_TASK_TYPE = SemanticTaskType.RESOLVE_RUNTIME_COMMAND

_AGENT_ACTIONABLE_REASONS = {
    RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT.value,
    RuntimeCommandGapReason.COMPOUND_SHELL_COMMAND.value,
    RuntimeCommandGapReason.MISSING_RUNTIME_COMMAND.value,
    RuntimeCommandGapReason.CONFLICTING_EXPLICIT_COMMANDS.value,
}

_NOT_AGENT_ACTIONABLE_REASONS = {
    RuntimeCommandGapReason.UNRESOLVED_PACKAGE_SCRIPT.value,
    RuntimeCommandGapReason.PACKAGE_SCRIPT_CYCLE.value,
}

_TOOL_ALLOWLIST_BY_REASON = {
    RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT.value: [
        "inspect_entrypoint_script",
        "read_source_range",
    ],
    RuntimeCommandGapReason.COMPOUND_SHELL_COMMAND.value: [
        "read_source_range",
        "search_code",
        "find_command_target",
    ],
    RuntimeCommandGapReason.MISSING_RUNTIME_COMMAND.value: [
        "search_code",
        "find_command_target",
        "read_source_range",
    ],
    RuntimeCommandGapReason.CONFLICTING_EXPLICIT_COMMANDS.value: [
        "search_code",
        "read_source_range",
        "find_command_target",
    ],
}


@dataclass
class _TaskGroup:
    component_id: str
    target_field: str
    gaps: list[RuntimeCommandGap] = field(default_factory=list)


def build_runtime_command_semantic_tasks(
    analysis: RuntimeCommandAnalysis,
) -> SemanticTaskBuildResult:
    groups: dict[tuple[str, str, str], _TaskGroup] = {}
    gap_keys: dict[int, tuple[str, str, str]] = {}

    for gap in analysis.gaps:
        disposition = route_runtime_command_gap_reason(gap.reason_code)
        if disposition != SemanticTaskBuildDisposition.TASK_CREATED:
            continue
        target_field = runtime_command_target_field(gap.component_id)
        key = (TARGET_TASK_TYPE.value, gap.component_id, target_field)
        groups.setdefault(key, _TaskGroup(gap.component_id, target_field)).gaps.append(gap)
        gap_keys[id(gap)] = key

    task_by_key = {
        key: _build_task(group, analysis.resolved_commands)
        for key, group in sorted(groups.items(), key=lambda item: (item[0][1], item[0][2], item[0][0]))
    }

    decisions: list[SemanticTaskBuildDecision] = []
    for gap in sorted(analysis.gaps, key=_gap_sort_key):
        target_field = runtime_command_target_field(gap.component_id)
        disposition = route_runtime_command_gap_reason(gap.reason_code)
        task_id = None
        if disposition == SemanticTaskBuildDisposition.TASK_CREATED:
            task_id = task_by_key[gap_keys[id(gap)]].task_id
        decisions.append(
            SemanticTaskBuildDecision(
                component_id=gap.component_id,
                target_field=target_field,
                gap_status=str(gap.status),
                gap_reason_code=str(gap.reason_code),
                disposition=disposition,
                task_id=task_id,
                description=_decision_description(disposition),
                evidence_refs=_sorted_unique(gap.evidence_refs),
            )
        )

    tasks = sorted(task_by_key.values(), key=lambda task: (task.component_id, task.target_field))
    return SemanticTaskBuildResult(tasks=tasks, decisions=decisions)


def route_runtime_command_gap_reason(reason_code: RuntimeCommandGapReason | str) -> SemanticTaskBuildDisposition:
    reason = str(reason_code)
    if reason in _AGENT_ACTIONABLE_REASONS:
        return SemanticTaskBuildDisposition.TASK_CREATED
    if reason in _NOT_AGENT_ACTIONABLE_REASONS:
        return SemanticTaskBuildDisposition.NOT_AGENT_ACTIONABLE
    return SemanticTaskBuildDisposition.UNSUPPORTED_FOR_MVP


def runtime_command_target_field(component_id: str) -> str:
    return f"/components/{_json_pointer_escape(component_id)}/runtime/command"


def _build_task(group: _TaskGroup, resolved_commands: list[ResolvedRuntimeCommand]) -> SemanticTask:
    reason_codes = _sorted_unique(str(gap.reason_code) for gap in group.gaps)
    evidence_ids = _sorted_unique(ref for gap in group.gaps for ref in gap.evidence_refs)
    known_candidates = _known_candidates(group.component_id, group.gaps, resolved_commands)

    return SemanticTask(
        task_id=_task_id(group.component_id, group.target_field, reason_codes, evidence_ids),
        task_type=TARGET_TASK_TYPE,
        component_id=group.component_id,
        target_field=group.target_field,
        reason=TaskReason(
            code=reason_codes[0] if len(reason_codes) == 1 else "multiple_runtime_command_gaps",
            description=_reason_description(reason_codes),
            evidence_refs=evidence_ids,
        ),
        known_candidates=known_candidates,
        evidence_refs=[EvidenceReference(evidence_id=evidence_id, origin="phase1") for evidence_id in evidence_ids],
        allowed_tools=_allowed_tools(reason_codes),
    )


def _known_candidates(
    component_id: str,
    gaps: list[RuntimeCommandGap],
    resolved_commands: list[ResolvedRuntimeCommand],
) -> list[KnownCandidate]:
    candidates: list[KnownCandidate] = []
    for command in sorted(
        (command for command in resolved_commands if command.component_id == component_id),
        key=lambda command: (command.command, command.source, command.confidence, tuple(command.evidence_refs)),
    ):
        if command.evidence_refs:
            candidates.append(
                KnownCandidate(
                    value=command.command,
                    source=command.source,
                    confidence=command.confidence,
                    classification=command.classification,
                    evidence_refs=_sorted_unique(command.evidence_refs),
                )
            )

    alternatives = [
        alternative
        for gap in gaps
        for alternative in gap.candidate_alternatives
        if alternative.evidence_refs
    ]
    for alternative in sorted(alternatives, key=_alternative_sort_key):
        candidates.append(_candidate_from_alternative(alternative))

    deduped: dict[str, KnownCandidate] = {}
    for candidate in candidates:
        key = json.dumps(candidate.model_dump(), sort_keys=True, separators=(",", ":"))
        deduped.setdefault(key, candidate)
    return [deduped[key] for key in sorted(deduped)]


def _candidate_from_alternative(alternative: RuntimeCommandAlternative) -> KnownCandidate:
    return KnownCandidate(
        value=alternative.command,
        source=alternative.source,
        confidence=alternative.confidence,
        classification=alternative.classification,
        evidence_refs=_sorted_unique(alternative.evidence_refs),
    )


def _allowed_tools(reason_codes: list[str]) -> list[str]:
    if len(reason_codes) == 1:
        return list(_TOOL_ALLOWLIST_BY_REASON[reason_codes[0]])
    tools = {
        tool
        for reason in reason_codes
        for tool in _TOOL_ALLOWLIST_BY_REASON[reason]
    }
    return sorted(tools)


def _task_id(component_id: str, target_field: str, reason_codes: list[str], evidence_ids: list[str]) -> str:
    payload = {
        "task_type": TARGET_TASK_TYPE.value,
        "component_id": component_id,
        "target_field": target_field,
        "reason_codes": reason_codes,
        "evidence_ids": evidence_ids,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12].upper()
    return f"SEM-RC-{digest}"


def _reason_description(reason_codes: list[str]) -> str:
    if len(reason_codes) == 1:
        return f"Runtime command semantic analysis requested for reason: {reason_codes[0]}."
    return f"Runtime command semantic analysis requested for reasons: {', '.join(reason_codes)}."


def _decision_description(disposition: SemanticTaskBuildDisposition) -> str:
    descriptions = {
        SemanticTaskBuildDisposition.TASK_CREATED: "Runtime command gap routed to semantic task.",
        SemanticTaskBuildDisposition.NOT_AGENT_ACTIONABLE: "Runtime command gap is not source-analysis actionable for the MVP semantic agent.",
        SemanticTaskBuildDisposition.UNSUPPORTED_FOR_MVP: "Runtime command gap is unsupported by the MVP semantic task builder.",
    }
    return descriptions[disposition]


def _json_pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _sorted_unique(values) -> list[str]:
    return sorted({str(value) for value in values if str(value)})


def _gap_sort_key(gap: RuntimeCommandGap) -> tuple[str, str, str, tuple[str, ...]]:
    return (gap.component_id, str(gap.reason_code), str(gap.status), tuple(sorted(gap.evidence_refs)))


def _alternative_sort_key(alternative: RuntimeCommandAlternative) -> tuple[str, str, str, tuple[str, ...]]:
    return (
        alternative.command,
        alternative.source,
        alternative.confidence,
        tuple(sorted(alternative.evidence_refs)),
    )
