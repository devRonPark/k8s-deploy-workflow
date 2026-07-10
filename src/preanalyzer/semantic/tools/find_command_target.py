from __future__ import annotations

import shlex
from pathlib import Path

from preanalyzer.models.semantic_tools import (
    FindCommandTargetInput,
    SemanticToolName,
    SemanticToolResult,
    SemanticToolResultStatus,
    SemanticToolUsage,
)
from preanalyzer.semantic.tools.common import (
    MAX_TARGET_RESULTS,
    SemanticToolExecutionContext,
    ToolBlockedError,
    ToolUnsupportedError,
    line_excerpt,
    make_evidence,
    ok_result,
    read_text_file,
    relative_repo_path,
    resolve_component_path,
    result,
)


def find_command_target(tool_input: FindCommandTargetInput, context: SemanticToolExecutionContext) -> SemanticToolResult:
    tool_name = SemanticToolName.FIND_COMMAND_TARGET
    if tool_input.max_results < 1 or tool_input.max_results > MAX_TARGET_RESULTS:
        return result(tool_name, SemanticToolResultStatus.INVALID_INPUT, "max_results is outside allowed range")

    try:
        tokens = shlex.split(tool_input.command)
    except ValueError:
        return result(tool_name, SemanticToolResultStatus.INVALID_INPUT, "command cannot be parsed")
    candidates = _candidate_targets(tokens)
    if candidates is None:
        return result(tool_name, SemanticToolResultStatus.UNSUPPORTED, "command target form is unsupported")

    observations: list[dict] = []
    evidence_items = []
    for target_kind, target_path, symbol_hint in candidates:
        if len(observations) >= tool_input.max_results:
            break
        try:
            path = resolve_component_path(context, target_path)
        except ToolBlockedError as exc:
            return result(tool_name, SemanticToolResultStatus.BLOCKED, str(exc))
        if not path.exists() or not path.is_file():
            continue
        try:
            text = read_text_file(path)
        except ToolUnsupportedError:
            continue
        first_line = text.splitlines()[:1] or [""]
        excerpt = line_excerpt(first_line, 1, 1)
        evidence = make_evidence(tool_name, context, path, 1, 1, excerpt)
        evidence_items.append(evidence)
        observations.append({
            "target_kind": target_kind,
            "path": relative_repo_path(context, path),
            "symbol_hint": symbol_hint,
            "evidence_ref": evidence.evidence_id,
        })

    if not observations:
        return result(tool_name, SemanticToolResultStatus.NO_MATCH, "command target was not found")
    observations.sort(key=lambda obs: (obs["path"], obs["target_kind"], obs.get("symbol_hint") or ""))
    return ok_result(
        tool_name,
        evidence=evidence_items,
        observations=observations,
        usage=SemanticToolUsage(files_read=len(evidence_items), source_lines_returned=len(evidence_items), matches_examined=len(observations)),
    )


def _candidate_targets(tokens: list[str]) -> list[tuple[str, str, str | None]] | None:
    if not tokens:
        return None
    executable = Path(tokens[0]).name
    if executable in {"python", "python3"}:
        if len(tokens) >= 3 and tokens[1] == "-m":
            return _python_module(tokens[2])
        direct = _first_path_like(tokens[1:])
        return [("direct_file", direct, None)] if direct else None
    if executable == "node":
        direct = _first_path_like(tokens[1:])
        return [("direct_file", direct, None)] if direct else None
    if executable == "java" and "-jar" in tokens:
        index = tokens.index("-jar")
        if index + 1 < len(tokens):
            return [("direct_file", tokens[index + 1], None)]
        return None
    if executable == "java":
        return None
    if executable in {"uvicorn", "gunicorn"} and len(tokens) >= 2:
        target = next((token for token in tokens[1:] if not token.startswith("-")), "")
        if ":" not in target:
            return None
        module, symbol = target.split(":", 1)
        return [(f"{executable}_module", f"{module.replace('.', '/')}.py", symbol or None)]
    direct = _first_path_like(tokens)
    if direct:
        return [("direct_file", direct, None)]
    return None


def _python_module(module: str) -> list[tuple[str, str, str | None]]:
    base = module.replace(".", "/")
    return [
        ("python_module", f"{base}.py", None),
        ("python_module", f"{base}/__main__.py", None),
    ]


def _first_path_like(tokens: list[str]) -> str | None:
    for token in tokens:
        if token.startswith("-"):
            continue
        if token.endswith((".py", ".js", ".jar", ".sh")) or "/" in token or token.startswith("."):
            return token
    return None
