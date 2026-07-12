"""도구: 엔트리포인트 스크립트를 논리 라인으로 분해·커맨드 분류."""

from __future__ import annotations

import shlex

from preanalyzer.models.semantic_tools import (
    InspectEntrypointScriptInput,
    SemanticToolName,
    SemanticToolResult,
    SemanticToolResultStatus,
    SemanticToolUsage,
)
from preanalyzer.semantic.tools.common import (
    MAX_SCRIPT_CANDIDATES,
    SemanticToolExecutionContext,
    ToolBlockedError,
    ToolUnsupportedError,
    line_excerpt,
    make_evidence,
    ok_result,
    read_text_file,
    redacted,
    relative_repo_path,
    resolve_existing_file,
    result,
)


_RUNTIME_COMMANDS = {"python", "python3", "node", "java", "gunicorn", "uvicorn"}
_PACKAGE_MANAGERS = {"npm", "yarn", "pnpm", "bun"}
_CONTROL_FLOW = {"if", "case", "for", "while", "until", "select", "then", "else", "elif", "fi", "do", "done", "esac"}


def inspect_entrypoint_script(tool_input: InspectEntrypointScriptInput, context: SemanticToolExecutionContext) -> SemanticToolResult:
    tool_name = SemanticToolName.INSPECT_ENTRYPOINT_SCRIPT
    if tool_input.max_candidates < 1 or tool_input.max_candidates > MAX_SCRIPT_CANDIDATES:
        return result(tool_name, SemanticToolResultStatus.INVALID_INPUT, "max_candidates is outside allowed range")

    try:
        path = resolve_existing_file(context, tool_input.path)
        text = read_text_file(path)
    except ToolBlockedError as exc:
        return result(tool_name, SemanticToolResultStatus.BLOCKED, str(exc))
    except ToolUnsupportedError as exc:
        return result(tool_name, SemanticToolResultStatus.UNSUPPORTED, str(exc))
    except FileNotFoundError:
        return result(tool_name, SemanticToolResultStatus.NOT_FOUND, "file was not found")

    physical_lines = text.splitlines()
    logical_lines = _logical_lines(physical_lines)
    evidence_items = []
    observations: list[dict] = []
    shebang_added = False

    if physical_lines and physical_lines[0].startswith("#!"):
        excerpt = line_excerpt(physical_lines, 1, 1)
        evidence = make_evidence(tool_name, context, path, 1, 1, excerpt)
        evidence_items.append(evidence)
        observations.append({
            "kind": "shebang",
            "command_text": redacted(physical_lines[0]),
            "path": relative_repo_path(context, path),
            "line_range": "1-1",
            "evidence_ref": evidence.evidence_id,
        })
        shebang_added = True

    for start_line, end_line, command in logical_lines:
        if len([obs for obs in observations if obs["kind"] != "shebang"]) >= tool_input.max_candidates:
            break
        stripped = command.strip()
        if not stripped or stripped.startswith("#") or stripped == physical_lines[0] and shebang_added:
            continue
        kind = _classify_command(stripped)
        if kind is None:
            continue
        excerpt = line_excerpt(physical_lines, start_line, end_line)
        evidence = make_evidence(tool_name, context, path, start_line, end_line, excerpt)
        evidence_items.append(evidence)
        observations.append({
            "kind": kind,
            "command_text": redacted(stripped),
            "path": relative_repo_path(context, path),
            "line_range": f"{start_line}-{end_line}",
            "evidence_ref": evidence.evidence_id,
        })

    if not observations:
        return result(tool_name, SemanticToolResultStatus.NO_MATCH, "no entrypoint script structure was found")

    return ok_result(
        tool_name,
        evidence=evidence_items,
        observations=observations,
        usage=SemanticToolUsage(files_read=1, source_lines_returned=sum(item.end_line - item.start_line + 1 for item in evidence_items)),
    )


def _logical_lines(lines: list[str]) -> list[tuple[int, int, str]]:
    logical: list[tuple[int, int, str]] = []
    buffer: list[str] = []
    start_line = 1
    for line_no, line in enumerate(lines, start=1):
        current = line.rstrip()
        if not buffer:
            start_line = line_no
        if current.endswith("\\"):
            buffer.append(current[:-1].rstrip())
            continue
        buffer.append(current)
        logical.append((start_line, line_no, " ".join(part.strip() for part in buffer if part.strip())))
        buffer = []
    if buffer:
        logical.append((start_line, len(lines), " ".join(part.strip() for part in buffer if part.strip())))
    return logical


def _classify_command(command: str) -> str | None:
    try:
        tokens = shlex.split(command, comments=False)
    except ValueError:
        tokens = command.split()
    if not tokens:
        return None
    first = tokens[0]
    if first in _CONTROL_FLOW:
        return "control_flow"
    if first == "eval":
        return "eval"
    if first in {"source", "."}:
        return "source_script"
    if first == "trap":
        return "trap"
    if any(token in {"|", "&&", "||", ";"} for token in tokens):
        return "compound_shell"
    if command.rstrip().endswith("&"):
        return "background_process"
    if "$(" in command or "`" in command:
        return "command_substitution"
    if first == "exec" and len(tokens) > 1:
        return "exec_command"
    executable = tokens[1] if first in {"sh", "bash", "/bin/sh", "/bin/bash"} and len(tokens) > 1 else first
    if executable.endswith(".sh") or executable.startswith("./"):
        return "nested_script"
    if first in _PACKAGE_MANAGERS:
        return "package_script"
    if first in _RUNTIME_COMMANDS:
        return "runtime_command"
    return None
