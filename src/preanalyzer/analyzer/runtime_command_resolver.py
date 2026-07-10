from __future__ import annotations

from dataclasses import dataclass, field
import json
import shlex
from typing import Literal

from preanalyzer.models.evidence import EvidenceFact, EvidenceModel
from preanalyzer.models.rule_inference import ComponentCandidate, RuleInferenceSet, RuntimeCommandCandidate
from preanalyzer.models.runtime_command_analysis import (
    ResolvedRuntimeCommand,
    RuntimeCommandAnalysis,
    RuntimeCommandAlternative,
    RuntimeCommandGap,
    RuntimeCommandGapReason,
    RuntimeCommandResolutionStatus,
)


MAX_SCRIPT_CHAIN_DEPTH = 5
SHELL_INTERPRETERS = {"sh", "bash", "/bin/sh", "/bin/bash"}
PACKAGE_MANAGERS = {"npm", "yarn", "pnpm", "bun"}


@dataclass(frozen=True)
class _ParsedCommand:
    form: Literal["exec", "shell", "invalid"]
    raw: str
    tokens: tuple[str, ...] = ()


@dataclass(frozen=True)
class _CommandResult:
    command: str
    source: str
    confidence: Literal["low", "medium", "high"]
    evidence_refs: tuple[str, ...]
    resolution_method: str


@dataclass(frozen=True)
class _GapResult:
    status: RuntimeCommandResolutionStatus
    reason_code: RuntimeCommandGapReason
    evidence_refs: tuple[str, ...] = ()
    candidate_commands: tuple[str, ...] = ()
    candidate_alternatives: tuple[RuntimeCommandAlternative, ...] = ()


@dataclass
class _ComponentWork:
    resolved: list[_CommandResult] = field(default_factory=list)
    gaps: list[_GapResult] = field(default_factory=list)


@dataclass(frozen=True)
class _ScriptFact:
    name: str
    command: str
    evidence_id: str
    artifact_ref: str


def analyze_runtime_commands(
    evidence: EvidenceModel,
    rules: RuleInferenceSet,
) -> RuntimeCommandAnalysis:
    components = rules.component_candidates or [ComponentCandidate("root", ".", "implicit_root", [])]
    work = {component.component_id: _ComponentWork() for component in components}
    facts_by_id = {fact.evidence_id: fact for fact in evidence.facts}
    entrypoint_by_artifact = {
        fact.artifact_ref: fact
        for fact in evidence.facts_by_type("dockerfile_entrypoint")
        if _component_for_artifact(fact.artifact_ref, components) is not None
    }
    cmd_artifacts = {
        fact.artifact_ref
        for fact in evidence.facts_by_type("dockerfile_cmd")
        if _component_for_artifact(fact.artifact_ref, components) is not None
    }
    scripts_by_component = _package_scripts_by_component(evidence, components)

    docker_command_artifacts: set[str] = set()
    for candidate in rules.runtime_command_candidates:
        component_work = work.setdefault(candidate.component_id, _ComponentWork())
        fact = _first_fact(candidate.evidence_refs, facts_by_id)
        if candidate.source == "dockerfile_cmd":
            artifact_ref = fact.artifact_ref if fact is not None else None
            docker_command_artifacts.add(artifact_ref or "")
            entrypoint = entrypoint_by_artifact.get(artifact_ref or "")
            result = _resolve_docker_cmd(candidate, fact, entrypoint, scripts_by_component.get(candidate.component_id, []))
        else:
            result = _resolve_standalone_command(
                component_id=candidate.component_id,
                raw=candidate.command,
                source=candidate.source,
                confidence=candidate.confidence,
                evidence_refs=tuple(candidate.evidence_refs),
                scripts=scripts_by_component.get(candidate.component_id, []),
            )
        _append_result(component_work, result)

    for artifact_ref, entrypoint in sorted(entrypoint_by_artifact.items()):
        if artifact_ref in cmd_artifacts or artifact_ref in docker_command_artifacts:
            continue
        component_id = _component_for_artifact(artifact_ref, components)
        if component_id is None:
            continue
        result = _resolve_entrypoint_alone(entrypoint, scripts_by_component.get(component_id, []))
        _append_result(work.setdefault(component_id, _ComponentWork()), result)

    if not rules.runtime_command_candidates and not entrypoint_by_artifact:
        for component in components:
            result = _resolve_start_script_fallback(scripts_by_component.get(component.component_id, []))
            if result is not None:
                _append_result(work.setdefault(component.component_id, _ComponentWork()), result)

    resolved_commands: list[ResolvedRuntimeCommand] = []
    gaps: list[RuntimeCommandGap] = []
    for component in components:
        component_work = work.get(component.component_id, _ComponentWork())
        component_resolved, component_gaps = _reconcile_component(component.component_id, component_work)
        resolved_commands.extend(component_resolved)
        gaps.extend(component_gaps)

    return RuntimeCommandAnalysis(
        resolved_commands=sorted(resolved_commands, key=lambda command: (command.component_id, command.command)),
        gaps=sorted(gaps, key=lambda gap: (gap.component_id, gap.reason_code, gap.description)),
    )


def _resolve_docker_cmd(
    candidate: RuntimeCommandCandidate,
    cmd_fact: EvidenceFact | None,
    entrypoint_fact: EvidenceFact | None,
    scripts: list[_ScriptFact],
) -> _CommandResult | _GapResult:
    evidence_refs = tuple(candidate.evidence_refs)
    if entrypoint_fact is None:
        return _resolve_standalone_command(
            component_id=candidate.component_id,
            raw=candidate.command,
            source=candidate.source,
            confidence=candidate.confidence,
            evidence_refs=evidence_refs,
            scripts=scripts,
        )

    entrypoint = _parse_command(str(entrypoint_fact.value))
    cmd = _parse_command(candidate.command if cmd_fact is None else str(cmd_fact.value))
    combined_refs = _merge_refs((entrypoint_fact.evidence_id,), evidence_refs)
    if entrypoint.form == "invalid" or cmd.form == "invalid":
        return _gap(RuntimeCommandResolutionStatus.INSUFFICIENT_EVIDENCE, RuntimeCommandGapReason.UNSUPPORTED_COMMAND_FORM, combined_refs)
    if entrypoint.form != "exec" or cmd.form != "exec":
        if _has_compound_shell(entrypoint.raw) or _has_compound_shell(cmd.raw):
            return _gap(
                RuntimeCommandResolutionStatus.REQUIRES_SOURCE_ANALYSIS,
                RuntimeCommandGapReason.COMPOUND_SHELL_COMMAND,
                combined_refs,
            )
        return _gap(RuntimeCommandResolutionStatus.INSUFFICIENT_EVIDENCE, RuntimeCommandGapReason.UNSUPPORTED_COMMAND_FORM, combined_refs)

    tokens = entrypoint.tokens + cmd.tokens
    if _is_shell_script_entrypoint(tokens):
        return _gap(
            RuntimeCommandResolutionStatus.REQUIRES_SOURCE_ANALYSIS,
            RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT,
            combined_refs,
        )
    if _requires_variable_expansion(tokens):
        return _gap(RuntimeCommandResolutionStatus.INSUFFICIENT_EVIDENCE, RuntimeCommandGapReason.UNSUPPORTED_COMMAND_FORM, combined_refs)
    package_script = _package_script_invocation(tokens)
    if package_script is not None:
        return _resolve_package_script(
            package_script,
            scripts,
            leading_refs=combined_refs,
            source="dockerfile_entrypoint+dockerfile_cmd+package_script",
            confidence="high",
        )
    return _CommandResult(
        command=_join_tokens(tokens),
        source="dockerfile_entrypoint+dockerfile_cmd",
        confidence="high",
        evidence_refs=combined_refs,
        resolution_method="exec_entrypoint_and_exec_cmd",
    )


def _resolve_entrypoint_alone(entrypoint_fact: EvidenceFact, scripts: list[_ScriptFact]) -> _CommandResult | _GapResult:
    evidence_refs = (entrypoint_fact.evidence_id,)
    parsed = _parse_command(str(entrypoint_fact.value))
    if parsed.form == "invalid":
        return _gap(RuntimeCommandResolutionStatus.INSUFFICIENT_EVIDENCE, RuntimeCommandGapReason.UNSUPPORTED_COMMAND_FORM, evidence_refs)
    return _resolve_parsed_command(
        parsed=parsed,
        evidence_refs=evidence_refs,
        source="dockerfile_entrypoint",
        confidence="high",
        resolution_method=f"{parsed.form}_entrypoint",
        scripts=scripts,
    )


def _resolve_standalone_command(
    *,
    component_id: str,
    raw: str,
    source: str,
    confidence: str,
    evidence_refs: tuple[str, ...],
    scripts: list[_ScriptFact],
) -> _CommandResult | _GapResult:
    del component_id
    parsed = _parse_command(raw)
    if parsed.form == "invalid":
        return _gap(RuntimeCommandResolutionStatus.INSUFFICIENT_EVIDENCE, RuntimeCommandGapReason.UNSUPPORTED_COMMAND_FORM, evidence_refs)
    return _resolve_parsed_command(
        parsed=parsed,
        evidence_refs=evidence_refs,
        source=source,
        confidence=_confidence(confidence),
        resolution_method=f"{parsed.form}_command",
        scripts=scripts,
    )


def _resolve_parsed_command(
    *,
    parsed: _ParsedCommand,
    evidence_refs: tuple[str, ...],
    source: str,
    confidence: Literal["low", "medium", "high"],
    resolution_method: str,
    scripts: list[_ScriptFact],
) -> _CommandResult | _GapResult:
    if _has_compound_shell(parsed.raw):
        return _gap(RuntimeCommandResolutionStatus.REQUIRES_SOURCE_ANALYSIS, RuntimeCommandGapReason.COMPOUND_SHELL_COMMAND, evidence_refs)
    if _is_shell_script_entrypoint(parsed.tokens):
        return _gap(RuntimeCommandResolutionStatus.REQUIRES_SOURCE_ANALYSIS, RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT, evidence_refs)
    if _requires_variable_expansion(parsed.tokens):
        return _gap(RuntimeCommandResolutionStatus.INSUFFICIENT_EVIDENCE, RuntimeCommandGapReason.UNSUPPORTED_COMMAND_FORM, evidence_refs)

    package_script = _package_script_invocation(parsed.tokens)
    if package_script is not None:
        return _resolve_package_script(
            package_script,
            scripts,
            leading_refs=evidence_refs,
            source=f"{source}+package_script",
            confidence=confidence,
        )

    command = parsed.raw.strip() if parsed.form == "shell" else _join_tokens(parsed.tokens)
    if not command:
        return _gap(RuntimeCommandResolutionStatus.INSUFFICIENT_EVIDENCE, RuntimeCommandGapReason.MISSING_RUNTIME_COMMAND, evidence_refs)
    return _CommandResult(command, source, confidence, evidence_refs, resolution_method)


def _resolve_start_script_fallback(scripts: list[_ScriptFact]) -> _CommandResult | _GapResult | None:
    start_scripts = [script for script in scripts if script.name == "start"]
    if not start_scripts:
        return None
    if len(start_scripts) > 1:
        commands = tuple(sorted({script.command for script in start_scripts}))
        refs = tuple(script.evidence_id for script in start_scripts)
        alternatives = tuple(
            RuntimeCommandAlternative(
                command=script.command,
                source="package_script",
                confidence="medium",
                classification="deterministic_runtime_command_analysis",
                evidence_refs=[script.evidence_id],
            )
            for script in sorted(start_scripts, key=lambda script: (script.command, script.evidence_id))
        )
        return _gap(
            RuntimeCommandResolutionStatus.AMBIGUOUS,
            RuntimeCommandGapReason.CONFLICTING_EXPLICIT_COMMANDS,
            refs,
            commands,
            alternatives,
        )
    return _resolve_package_script(
        "start",
        scripts,
        leading_refs=(),
        source="package_script",
        confidence="medium",
    )


def _resolve_package_script(
    script_name: str,
    scripts: list[_ScriptFact],
    *,
    leading_refs: tuple[str, ...],
    source: str,
    confidence: Literal["low", "medium", "high"],
) -> _CommandResult | _GapResult:
    by_name: dict[str, list[_ScriptFact]] = {}
    for script in scripts:
        by_name.setdefault(script.name, []).append(script)
    return _resolve_script_name(
        script_name,
        by_name,
        leading_refs=leading_refs,
        source=source,
        confidence=confidence,
        visited=(),
        depth=0,
    )


def _resolve_script_name(
    script_name: str,
    by_name: dict[str, list[_ScriptFact]],
    *,
    leading_refs: tuple[str, ...],
    source: str,
    confidence: Literal["low", "medium", "high"],
    visited: tuple[str, ...],
    depth: int,
) -> _CommandResult | _GapResult:
    if script_name in visited:
        cycle_refs = _refs_for_scripts(by_name, visited + (script_name,))
        return _gap(
            RuntimeCommandResolutionStatus.CYCLE_DETECTED,
            RuntimeCommandGapReason.PACKAGE_SCRIPT_CYCLE,
            _merge_refs(leading_refs, cycle_refs),
        )
    if depth >= MAX_SCRIPT_CHAIN_DEPTH:
        return _gap(
            RuntimeCommandResolutionStatus.REQUIRES_SOURCE_ANALYSIS,
            RuntimeCommandGapReason.UNRESOLVED_PACKAGE_SCRIPT,
            _merge_refs(leading_refs, _refs_for_scripts(by_name, visited)),
        )

    matches = by_name.get(script_name, [])
    if not matches:
        return _gap(RuntimeCommandResolutionStatus.INVALID_REFERENCE, RuntimeCommandGapReason.UNRESOLVED_PACKAGE_SCRIPT, leading_refs)

    results: list[_CommandResult] = []
    gaps: list[_GapResult] = []
    for script in matches:
        refs = _merge_refs(leading_refs, (script.evidence_id,))
        parsed = _parse_command(script.command)
        if parsed.form == "invalid":
            gaps.append(_gap(RuntimeCommandResolutionStatus.INSUFFICIENT_EVIDENCE, RuntimeCommandGapReason.UNSUPPORTED_COMMAND_FORM, refs))
            continue
        if _has_compound_shell(parsed.raw):
            gaps.append(_gap(RuntimeCommandResolutionStatus.REQUIRES_SOURCE_ANALYSIS, RuntimeCommandGapReason.COMPOUND_SHELL_COMMAND, refs))
            continue
        if _is_shell_script_entrypoint(parsed.tokens):
            gaps.append(_gap(RuntimeCommandResolutionStatus.REQUIRES_SOURCE_ANALYSIS, RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT, refs))
            continue
        next_script = _package_script_invocation(parsed.tokens)
        if next_script is not None:
            result = _resolve_script_name(
                next_script,
                by_name,
                leading_refs=refs,
                source=source,
                confidence=confidence,
                visited=visited + (script_name,),
                depth=depth + 1,
            )
            if isinstance(result, _CommandResult):
                results.append(result)
            else:
                gaps.append(result)
            continue
        command = parsed.raw.strip() if parsed.form == "shell" else _join_tokens(parsed.tokens)
        results.append(_CommandResult(command, source, confidence, refs, "package_script_lookup"))

    if results:
        distinct = {result.command for result in results}
        if len(distinct) > 1:
            refs = tuple(ref for result in results for ref in result.evidence_refs)
            return _gap(
                RuntimeCommandResolutionStatus.AMBIGUOUS,
                RuntimeCommandGapReason.CONFLICTING_EXPLICIT_COMMANDS,
                _merge_refs(refs),
                tuple(sorted(distinct)),
                _alternatives_from_command_results(results),
            )
        return _merge_command_results(results)
    if gaps:
        return _merge_gap_results(gaps)
    return _gap(RuntimeCommandResolutionStatus.INVALID_REFERENCE, RuntimeCommandGapReason.UNRESOLVED_PACKAGE_SCRIPT, leading_refs)


def _parse_command(raw: str) -> _ParsedCommand:
    text = raw.strip()
    if not text:
        return _ParsedCommand("invalid", raw)
    if text.startswith("["):
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return _ParsedCommand("invalid", raw)
        if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
            return _ParsedCommand("invalid", raw)
        return _ParsedCommand("exec", raw, tuple(value))
    try:
        tokens = tuple(shlex.split(text))
    except ValueError:
        return _ParsedCommand("invalid", raw)
    if not tokens:
        return _ParsedCommand("invalid", raw)
    return _ParsedCommand("shell", raw, tokens)


def _has_compound_shell(raw: str) -> bool:
    lexer = shlex.shlex(raw, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return False
    return any(token in {"&&", "||", ";", "|"} for token in tokens)


def _is_shell_script_entrypoint(tokens: tuple[str, ...]) -> bool:
    if not tokens:
        return False
    executable = tokens[0]
    if _is_script_path(executable):
        return True
    if executable in SHELL_INTERPRETERS and len(tokens) >= 2:
        return _is_script_path(tokens[1])
    return False


def _is_script_path(token: str) -> bool:
    return token.endswith(".sh") and ("/" in token or token.startswith(".") or token.endswith(".sh"))


def _requires_variable_expansion(tokens: tuple[str, ...]) -> bool:
    return any("$" in token for token in tokens)


def _package_script_invocation(tokens: tuple[str, ...]) -> str | None:
    if not tokens:
        return None
    manager = tokens[0]
    if manager not in PACKAGE_MANAGERS:
        return None
    if manager == "npm":
        if tokens == ("npm", "start"):
            return "start"
        if len(tokens) == 3 and tokens[1] == "run":
            return tokens[2]
        return None
    if manager in {"yarn", "pnpm"}:
        if len(tokens) == 2:
            return tokens[1]
        if len(tokens) == 3 and tokens[1] == "run":
            return tokens[2]
        return None
    if manager == "bun" and len(tokens) == 3 and tokens[1] == "run":
        return tokens[2]
    return None


def _join_tokens(tokens: tuple[str, ...]) -> str:
    return shlex.join(tokens)


def _package_scripts_by_component(
    evidence: EvidenceModel,
    components: list[ComponentCandidate],
) -> dict[str, list[_ScriptFact]]:
    by_component: dict[str, list[_ScriptFact]] = {component.component_id: [] for component in components}
    for fact in evidence.facts_by_type("package_script"):
        if not isinstance(fact.value, dict):
            continue
        component_id = _component_for_artifact(fact.artifact_ref, components)
        if component_id is None:
            continue
        name = str(fact.value.get("name", ""))
        command = str(fact.value.get("command", ""))
        if name and command:
            by_component.setdefault(component_id, []).append(_ScriptFact(name, command, fact.evidence_id, fact.artifact_ref))
    for component_scripts in by_component.values():
        component_scripts.sort(key=lambda script: (script.name, script.artifact_ref, script.evidence_id))
    return by_component


def _component_for_artifact(artifact_ref: str, component_candidates: list[ComponentCandidate]) -> str | None:
    for candidate in component_candidates:
        if _artifact_belongs_to_component(artifact_ref, candidate.root_path):
            return candidate.component_id
    return None


def _artifact_belongs_to_component(artifact_ref: str, root_path: str | None) -> bool:
    if root_path in {None, "."}:
        return "/" not in artifact_ref
    normalized = root_path.removeprefix("./").rstrip("/") or "."
    return artifact_ref.startswith(f"{normalized}/")


def _first_fact(evidence_refs: list[str], facts_by_id: dict[str, EvidenceFact]) -> EvidenceFact | None:
    for evidence_ref in evidence_refs:
        fact = facts_by_id.get(evidence_ref)
        if fact is not None:
            return fact
    return None


def _append_result(component_work: _ComponentWork, result: _CommandResult | _GapResult | None) -> None:
    if result is None:
        return
    if isinstance(result, _CommandResult):
        component_work.resolved.append(result)
    else:
        component_work.gaps.append(result)


def _reconcile_component(component_id: str, work: _ComponentWork) -> tuple[list[ResolvedRuntimeCommand], list[RuntimeCommandGap]]:
    if work.resolved:
        by_command: dict[str, list[_CommandResult]] = {}
        for result in work.resolved:
            by_command.setdefault(result.command, []).append(result)
        if len(by_command) > 1:
            refs = tuple(ref for results in by_command.values() for result in results for ref in result.evidence_refs)
            commands = tuple(sorted(by_command))
            return [], [
                RuntimeCommandGap(
                    component_id=component_id,
                    status=RuntimeCommandResolutionStatus.AMBIGUOUS,
                    reason_code=RuntimeCommandGapReason.CONFLICTING_EXPLICIT_COMMANDS,
                    description=_description(RuntimeCommandGapReason.CONFLICTING_EXPLICIT_COMMANDS),
                    evidence_refs=list(_merge_refs(refs)),
                    candidate_commands=list(commands),
                    candidate_alternatives=list(_alternatives_from_command_results(
                        [_merge_command_results(results) for _, results in sorted(by_command.items())]
                    )),
                )
            ]
        merged = _merge_command_results(next(iter(by_command.values())))
        return [
            ResolvedRuntimeCommand(
                component_id=component_id,
                command=merged.command,
                source=merged.source,
                confidence=merged.confidence,
                evidence_refs=list(merged.evidence_refs),
                resolution_method=merged.resolution_method,
            )
        ], []

    return [], [
        RuntimeCommandGap(
            component_id=component_id,
            status=gap.status,
            reason_code=gap.reason_code,
            description=_description(gap.reason_code),
            evidence_refs=list(gap.evidence_refs),
            candidate_commands=list(gap.candidate_commands),
            candidate_alternatives=list(gap.candidate_alternatives),
        )
        for gap in _dedupe_gaps(work.gaps)
    ]


def _merge_command_results(results: list[_CommandResult]) -> _CommandResult:
    first = results[0]
    return _CommandResult(
        command=first.command,
        source="+".join(sorted({result.source for result in results})),
        confidence=_max_confidence(result.confidence for result in results),
        evidence_refs=_merge_refs(tuple(ref for result in results for ref in result.evidence_refs)),
        resolution_method="+".join(sorted({result.resolution_method for result in results})),
    )


def _merge_gap_results(gaps: list[_GapResult]) -> _GapResult:
    first = gaps[0]
    return _GapResult(
        status=first.status,
        reason_code=first.reason_code,
        evidence_refs=_merge_refs(tuple(ref for gap in gaps for ref in gap.evidence_refs)),
        candidate_commands=tuple(sorted({command for gap in gaps for command in gap.candidate_commands})),
        candidate_alternatives=_dedupe_alternatives(tuple(
            alternative for gap in gaps for alternative in gap.candidate_alternatives
        )),
    )


def _dedupe_gaps(gaps: list[_GapResult]) -> list[_GapResult]:
    deduped: dict[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[tuple[str, str, str, tuple[str, ...]], ...]], _GapResult] = {}
    for gap in gaps:
        key = (
            gap.status.value,
            gap.reason_code.value,
            gap.evidence_refs,
            gap.candidate_commands,
            tuple(_alternative_key(alternative) for alternative in gap.candidate_alternatives),
        )
        deduped[key] = gap
    return list(deduped.values())


def _gap(
    status: RuntimeCommandResolutionStatus,
    reason_code: RuntimeCommandGapReason,
    evidence_refs: tuple[str, ...],
    candidate_commands: tuple[str, ...] = (),
    candidate_alternatives: tuple[RuntimeCommandAlternative, ...] = (),
) -> _GapResult:
    return _GapResult(status, reason_code, _merge_refs(evidence_refs), candidate_commands, _dedupe_alternatives(candidate_alternatives))


def _alternatives_from_command_results(results: list[_CommandResult]) -> tuple[RuntimeCommandAlternative, ...]:
    alternatives = tuple(
        RuntimeCommandAlternative(
            command=result.command,
            source=result.source,
            confidence=result.confidence,
            classification="deterministic_runtime_command_analysis",
            evidence_refs=list(result.evidence_refs),
        )
        for result in results
    )
    return _dedupe_alternatives(alternatives)


def _dedupe_alternatives(alternatives: tuple[RuntimeCommandAlternative, ...]) -> tuple[RuntimeCommandAlternative, ...]:
    deduped: dict[tuple[str, str, str, tuple[str, ...]], RuntimeCommandAlternative] = {}
    for alternative in alternatives:
        deduped[_alternative_key(alternative)] = alternative
    return tuple(deduped[key] for key in sorted(deduped))


def _alternative_key(alternative: RuntimeCommandAlternative) -> tuple[str, str, str, tuple[str, ...]]:
    return (
        alternative.command,
        alternative.source,
        alternative.confidence,
        tuple(alternative.evidence_refs),
    )


def _merge_refs(*groups: tuple[str, ...]) -> tuple[str, ...]:
    refs: list[str] = []
    for group in groups:
        for ref in group:
            if ref and ref not in refs:
                refs.append(ref)
    return tuple(refs)


def _refs_for_scripts(by_name: dict[str, list[_ScriptFact]], script_names: tuple[str, ...]) -> tuple[str, ...]:
    refs: list[str] = []
    for name in script_names:
        refs.extend(script.evidence_id for script in by_name.get(name, []))
    return _merge_refs(tuple(refs))


def _confidence(value: str) -> Literal["low", "medium", "high"]:
    if value in {"low", "medium", "high"}:
        return value  # type: ignore[return-value]
    return "medium"


def _max_confidence(values) -> Literal["low", "medium", "high"]:
    rank = {"low": 0, "medium": 1, "high": 2}
    best = max(values, key=lambda value: rank.get(value, 1))
    return _confidence(best)


def _description(reason_code: RuntimeCommandGapReason | str) -> str:
    reason = RuntimeCommandGapReason(reason_code)
    return {
        RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT: "Runtime command points to a shell script and requires source analysis.",
        RuntimeCommandGapReason.COMPOUND_SHELL_COMMAND: "Runtime command contains shell control flow and requires source analysis.",
        RuntimeCommandGapReason.UNRESOLVED_PACKAGE_SCRIPT: "Runtime command references a package script that cannot be resolved deterministically.",
        RuntimeCommandGapReason.PACKAGE_SCRIPT_CYCLE: "Package script resolution detected a cycle.",
        RuntimeCommandGapReason.CONFLICTING_EXPLICIT_COMMANDS: "Multiple explicit runtime commands remain after deterministic analysis.",
        RuntimeCommandGapReason.UNSUPPORTED_COMMAND_FORM: "Runtime command form is not supported by deterministic analysis.",
        RuntimeCommandGapReason.MISSING_RUNTIME_COMMAND: "No runtime command evidence is available for deterministic analysis.",
    }[reason]
