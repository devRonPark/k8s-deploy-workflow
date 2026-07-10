from __future__ import annotations

import hashlib
import json
import re
import shlex
from pathlib import Path, PurePosixPath
from typing import Any

from preanalyzer.models.evidence import EvidenceFact, EvidenceModel
from preanalyzer.models.semantic import (
    SemanticCandidate,
    SemanticCandidateVerification,
    SemanticResolution,
    SemanticResolutionStatus,
    SemanticTask,
    VerificationReasonCode,
    VerificationResult,
    VerificationStatus,
)
from preanalyzer.models.semantic_tools import (
    SemanticToolEvidence,
    SemanticToolResult,
    SemanticToolResultStatus,
)
from preanalyzer.semantic.tools.common import (
    is_excluded_rel_path,
    is_sensitive_rel_path,
    line_excerpt,
    read_text_file,
)


_GROUNDING_PHASE1_FACT_TYPES = {
    "dockerfile_cmd",
    "dockerfile_entrypoint",
    "package_script",
    "runtime_command",
}

_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b[A-Z0-9_.-]*(?:password|passwd|token|secret|api[_-]?key)[A-Z0-9_.-]*\b"
    r"\s*[:=]\s*"
    r"(?P<value>['\"]?[^'\"\s#]+['\"]?)"
)
_SECRET_OPTION_RE = re.compile(
    r"(?i)(?:--(?:password|passwd|token|secret|api-key|api_key)|"
    r"(?:password|passwd|token|secret|api[_-]?key))"
    r"(?:=|\s+)"
    r"(?P<value>['\"]?[^'\"\s#]+['\"]?)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/\-]{16,}=*")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
_API_KEY_RE = re.compile(r"\b(?:sk|pk|AKIA)[A-Za-z0-9_\-]{12,}\b")
_LINE_PREFIX_RE = re.compile(r"^\s*\d+:\s?")


class _SemanticEvidenceRecord:
    def __init__(self, evidence: SemanticToolEvidence, result: SemanticToolResult):
        self.evidence = evidence
        self.result = result


def verify_semantic_resolution(
    *,
    repository_root: Path,
    task: SemanticTask,
    resolution: SemanticResolution,
    phase1_evidence: EvidenceModel,
    tool_results: list[SemanticToolResult],
) -> VerificationResult:
    repo_root = Path(repository_root).resolve()
    phase1_index = {fact.evidence_id: fact for fact in phase1_evidence.facts}
    semantic_index = _semantic_tool_evidence_index(tool_results)
    task_phase1_refs = _task_phase1_refs(task)
    task_semantic_refs = _task_semantic_refs(task)

    global_reasons: set[str] = set()
    if resolution.task_id != task.task_id:
        global_reasons.add(VerificationReasonCode.TASK_ID_MISMATCH.value)

    if _contains_secret_literal(resolution.analysis_summary):
        global_reasons.add(VerificationReasonCode.SECRET_VALUE_DETECTED.value)

    trace_reasons = _verify_trace_refs(resolution.tool_trace_refs, semantic_index, task_semantic_refs)
    global_reasons.update(trace_reasons)

    candidate_results = [
        _verify_candidate(
            repo_root=repo_root,
            task=task,
            candidate=item,
            phase1_index=phase1_index,
            semantic_index=semantic_index,
            task_phase1_refs=task_phase1_refs,
            task_semantic_refs=task_semantic_refs,
        )
        for item in resolution.candidates
    ]

    if global_reasons:
        candidate_results = [
            SemanticCandidateVerification(
                candidate_id=result.candidate_id,
                accepted=False,
                reason_codes=_merge(result.reason_codes, global_reasons),
                verified_evidence_refs=result.verified_evidence_refs,
                warnings=result.warnings,
            )
            for result in candidate_results
        ]

    accepted_candidate_ids = sorted(result.candidate_id for result in candidate_results if result.accepted)
    status = _overall_status(resolution, accepted_candidate_ids, global_reasons, candidate_results)
    if status in {
        VerificationStatus.REJECTED.value,
        VerificationStatus.INSUFFICIENT_EVIDENCE.value,
        VerificationStatus.BUDGET_EXHAUSTED.value,
        VerificationStatus.TOOL_ERROR.value,
    }:
        accepted_candidate_ids = []
        if any(result.accepted for result in candidate_results):
            candidate_results = [
                SemanticCandidateVerification(
                    candidate_id=result.candidate_id,
                    accepted=False,
                    reason_codes=_merge(result.reason_codes, {VerificationReasonCode.RESOLUTION_STATUS_INCONSISTENT.value}),
                    verified_evidence_refs=result.verified_evidence_refs,
                    warnings=result.warnings,
                )
                for result in candidate_results
            ]

    return VerificationResult(
        task_id=task.task_id,
        status=status,
        accepted_candidate_ids=accepted_candidate_ids,
        reasons=sorted(global_reasons),
        candidate_results=candidate_results,
    )


def _verify_candidate(
    *,
    repo_root: Path,
    task: SemanticTask,
    candidate: SemanticCandidate,
    phase1_index: dict[str, EvidenceFact],
    semantic_index: dict[str, _SemanticEvidenceRecord],
    task_phase1_refs: set[str],
    task_semantic_refs: set[str],
) -> SemanticCandidateVerification:
    reasons: set[str] = set()
    verified_refs: set[str] = set()
    warnings: set[str] = set()

    if candidate.component_id != task.component_id:
        reasons.add(VerificationReasonCode.COMPONENT_MISMATCH.value)
    if candidate.target_field != task.target_field:
        reasons.add(VerificationReasonCode.TARGET_FIELD_MISMATCH.value)
    if _candidate_contains_secret(candidate):
        reasons.add(VerificationReasonCode.SECRET_VALUE_DETECTED.value)

    for evidence_ref in candidate.evidence_refs:
        if evidence_ref.startswith("SE-"):
            semantic_reasons = _verify_semantic_evidence_ref(
                repo_root,
                evidence_ref,
                semantic_index,
                task_semantic_refs,
                task.allowed_tools,
            )
            if semantic_reasons:
                reasons.update(semantic_reasons)
            else:
                verified_refs.add(evidence_ref)
            continue

        phase1_reasons = _verify_phase1_evidence_ref(evidence_ref, phase1_index, task_phase1_refs)
        if phase1_reasons:
            reasons.update(phase1_reasons)
        else:
            verified_refs.add(evidence_ref)

    if not candidate.evidence_refs:
        reasons.add(VerificationReasonCode.UNKNOWN_EVIDENCE_REFERENCE.value)

    command = _candidate_command(candidate.value)
    if command is None or not _is_grounded(command, verified_refs, phase1_index, semantic_index):
        reasons.add(VerificationReasonCode.CANDIDATE_NOT_GROUNDED.value)

    if _has_high_confidence_deterministic_conflict(task, command):
        warnings.add(VerificationReasonCode.DETERMINISTIC_CANDIDATE_CONFLICT.value)

    return SemanticCandidateVerification(
        candidate_id=candidate.candidate_id,
        accepted=not reasons,
        reason_codes=sorted(reasons),
        verified_evidence_refs=sorted(verified_refs),
        warnings=sorted(warnings),
    )


def _semantic_tool_evidence_index(tool_results: list[SemanticToolResult]) -> dict[str, _SemanticEvidenceRecord]:
    index: dict[str, _SemanticEvidenceRecord] = {}
    for result in tool_results:
        for evidence in result.evidence:
            index[evidence.evidence_id] = _SemanticEvidenceRecord(evidence, result)
    return index


def _task_phase1_refs(task: SemanticTask) -> set[str]:
    refs = {ref.evidence_id for ref in task.evidence_refs if ref.origin == "phase1"}
    refs.update(task.reason.evidence_refs)
    for known in task.known_candidates:
        refs.update(known.evidence_refs)
    return {ref for ref in refs if ref and not ref.startswith("SE-")}


def _task_semantic_refs(task: SemanticTask) -> set[str]:
    return {ref.evidence_id for ref in task.evidence_refs if ref.origin == "semantic_tool"}


def _verify_phase1_evidence_ref(
    evidence_ref: str,
    phase1_index: dict[str, EvidenceFact],
    task_phase1_refs: set[str],
) -> set[str]:
    if evidence_ref not in phase1_index:
        return {VerificationReasonCode.UNKNOWN_EVIDENCE_REFERENCE.value}
    if evidence_ref not in task_phase1_refs:
        return {VerificationReasonCode.EVIDENCE_OUTSIDE_TASK_SCOPE.value}
    return set()


def _verify_semantic_evidence_ref(
    repo_root: Path,
    evidence_ref: str,
    semantic_index: dict[str, _SemanticEvidenceRecord],
    task_semantic_refs: set[str],
    allowed_tools: list[str],
) -> set[str]:
    if evidence_ref not in semantic_index:
        return {VerificationReasonCode.UNKNOWN_EVIDENCE_REFERENCE.value}
    if evidence_ref not in task_semantic_refs:
        return {VerificationReasonCode.EVIDENCE_OUTSIDE_TASK_SCOPE.value}

    record = semantic_index[evidence_ref]
    if record.result.status != SemanticToolResultStatus.OK.value:
        return {VerificationReasonCode.INVALID_TOOL_TRACE_REFERENCE.value}
    if str(record.evidence.tool_name) not in set(allowed_tools):
        return {VerificationReasonCode.TOOL_NOT_ALLOWED.value}
    return _verify_tool_evidence_against_repository(repo_root, record.evidence)


def _verify_tool_evidence_against_repository(repo_root: Path, evidence: SemanticToolEvidence) -> set[str]:
    rel = PurePosixPath(evidence.path)
    if rel.is_absolute() or any(part == ".." for part in rel.parts) or not str(evidence.path).strip():
        return {VerificationReasonCode.TOOL_EVIDENCE_PATH_INVALID.value}
    if is_excluded_rel_path(evidence.path) or is_sensitive_rel_path(evidence.path):
        return {VerificationReasonCode.TOOL_EVIDENCE_PATH_INVALID.value}

    path = (repo_root / Path(*rel.parts)).resolve()
    if not _is_relative_to(path, repo_root) or not path.exists() or not path.is_file():
        return {VerificationReasonCode.TOOL_EVIDENCE_PATH_INVALID.value}
    if path.is_symlink() and not _is_relative_to(path.resolve(), repo_root):
        return {VerificationReasonCode.TOOL_EVIDENCE_PATH_INVALID.value}

    try:
        text = read_text_file(path)
    except Exception:
        return {VerificationReasonCode.TOOL_EVIDENCE_PATH_INVALID.value}

    lines = text.splitlines()
    if evidence.start_line < 1 or evidence.end_line < evidence.start_line or evidence.end_line > len(lines):
        return {VerificationReasonCode.TOOL_EVIDENCE_RANGE_INVALID.value}

    current_excerpt = line_excerpt(lines, evidence.start_line, evidence.end_line)
    current_hash = hashlib.sha256(current_excerpt.encode("utf-8")).hexdigest()
    if current_hash != evidence.excerpt_hash:
        return {VerificationReasonCode.TOOL_EVIDENCE_HASH_MISMATCH.value}
    if current_excerpt != evidence.excerpt:
        return {VerificationReasonCode.TOOL_EVIDENCE_HASH_MISMATCH.value}
    return set()


def _verify_trace_refs(
    trace_refs: list[str],
    semantic_index: dict[str, _SemanticEvidenceRecord],
    task_semantic_refs: set[str],
) -> set[str]:
    reasons: set[str] = set()
    for trace_ref in trace_refs:
        if not trace_ref.startswith("SE-") or trace_ref not in semantic_index or trace_ref not in task_semantic_refs:
            reasons.add(VerificationReasonCode.INVALID_TOOL_TRACE_REFERENCE.value)
    return reasons


def _overall_status(
    resolution: SemanticResolution,
    accepted_candidate_ids: list[str],
    global_reasons: set[str],
    candidate_results: list[SemanticCandidateVerification],
) -> str:
    if global_reasons:
        return VerificationStatus.REJECTED.value

    if resolution.status == SemanticResolutionStatus.INSUFFICIENT_EVIDENCE.value:
        return VerificationStatus.INSUFFICIENT_EVIDENCE.value
    if resolution.status == SemanticResolutionStatus.BUDGET_EXHAUSTED.value:
        return VerificationStatus.BUDGET_EXHAUSTED.value
    if resolution.status == SemanticResolutionStatus.TOOL_ERROR.value:
        return VerificationStatus.TOOL_ERROR.value

    if resolution.status == SemanticResolutionStatus.RESOLVED.value:
        if resolution.recommended_candidate_id in accepted_candidate_ids:
            return VerificationStatus.ACCEPTED.value
        return VerificationStatus.REJECTED.value

    if resolution.status == SemanticResolutionStatus.AMBIGUOUS.value:
        if accepted_candidate_ids:
            return VerificationStatus.AMBIGUOUS.value
        return VerificationStatus.REJECTED.value

    if any(not result.accepted for result in candidate_results):
        return VerificationStatus.REJECTED.value
    return VerificationStatus.REJECTED.value


def _is_grounded(
    command: str,
    verified_refs: set[str],
    phase1_index: dict[str, EvidenceFact],
    semantic_index: dict[str, _SemanticEvidenceRecord],
) -> bool:
    normalized = _normalize_command(command)
    if normalized is None:
        return False

    for ref in sorted(verified_refs):
        if ref.startswith("SE-"):
            record = semantic_index.get(ref)
            if record is not None and _semantic_evidence_grounds(normalized, ref, record):
                return True
            continue
        fact = phase1_index.get(ref)
        if fact is not None and _phase1_fact_grounds(normalized, fact):
            return True
    return False


def _semantic_evidence_grounds(normalized_command: str, evidence_ref: str, record: _SemanticEvidenceRecord) -> bool:
    for observation in record.result.observations:
        if observation.get("evidence_ref") != evidence_ref:
            continue
        for key in ("command_text", "matched_text", "target_command"):
            value = observation.get(key)
            if isinstance(value, str) and _normalize_command(value) == normalized_command:
                return True

    for line in record.evidence.excerpt.splitlines():
        text = _LINE_PREFIX_RE.sub("", line).strip()
        if _normalize_command(text) == normalized_command:
            return True
    return False


def _phase1_fact_grounds(normalized_command: str, fact: EvidenceFact) -> bool:
    if fact.fact_type not in _GROUNDING_PHASE1_FACT_TYPES:
        return False
    return any(_normalize_command(value) == normalized_command for value in _explicit_command_values(fact.value))


def _explicit_command_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return [" ".join(value)]
        return [item for entry in value for item in _explicit_command_values(entry)]
    if isinstance(value, dict):
        values: list[str] = []
        for key in ("command", "cmd", "entrypoint", "script"):
            if key in value:
                values.extend(_explicit_command_values(value[key]))
        return values
    return []


def _candidate_command(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return " ".join(value)
    if isinstance(value, dict):
        command = value.get("command")
        if isinstance(command, str):
            return command
        if isinstance(command, list) and all(isinstance(item, str) for item in command):
            return " ".join(command)
    return None


def _normalize_command(command: str | None) -> str | None:
    if command is None:
        return None
    text = command.strip()
    if not text:
        return None
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, list) and all(isinstance(item, str) for item in decoded):
        tokens = decoded
    else:
        try:
            tokens = shlex.split(text)
        except ValueError:
            tokens = text.split()
    if tokens and tokens[0] == "exec":
        tokens = tokens[1:]
    if not tokens:
        return None
    return " ".join(tokens)


def _candidate_contains_secret(candidate: SemanticCandidate) -> bool:
    texts = [
        *_string_values(candidate.value),
        *candidate.supporting_observations,
        *candidate.contradicting_observations,
    ]
    return any(_contains_secret_literal(text) for text in texts)


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for entry in value for item in _string_values(entry)]
    if isinstance(value, dict):
        return [item for entry in value.values() for item in _string_values(entry)]
    return []


def _contains_secret_literal(text: str | None) -> bool:
    if not text:
        return False
    if _PRIVATE_KEY_RE.search(text) or _BEARER_RE.search(text) or _API_KEY_RE.search(text):
        return True
    for regex in (_SECRET_ASSIGNMENT_RE, _SECRET_OPTION_RE):
        for match in regex.finditer(text):
            if not _is_env_reference(match.group("value")):
                return True
    return False


def _is_env_reference(value: str) -> bool:
    stripped = value.strip().strip("'\"")
    return stripped.startswith("$") or stripped.startswith("${")


def _has_high_confidence_deterministic_conflict(task: SemanticTask, command: str | None) -> bool:
    normalized = _normalize_command(command)
    if normalized is None:
        return False
    for known in task.known_candidates:
        if known.confidence != "high":
            continue
        if known.classification not in {"rule_inference", "deterministic_runtime_command_analysis"}:
            continue
        known_command = _candidate_command(known.value)
        if known_command is not None and _normalize_command(known_command) != normalized:
            return True
    return False


def _merge(existing: list[str], additions: set[str]) -> list[str]:
    return sorted(set(existing).union(additions))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
