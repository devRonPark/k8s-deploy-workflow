from __future__ import annotations

from preanalyzer.models.semantic_tools import (
    SearchCodeInput,
    SemanticToolName,
    SemanticToolResult,
    SemanticToolResultStatus,
    SemanticToolUsage,
)
from preanalyzer.semantic.tools.common import (
    MAX_SEARCH_CONTEXT_LINES,
    MAX_SEARCH_MATCHES,
    SemanticToolExecutionContext,
    ToolBlockedError,
    ToolUnsupportedError,
    iter_component_files,
    line_excerpt,
    make_evidence,
    ok_result,
    read_text_file,
    redacted,
    relative_repo_path,
    resolve_component_path,
    result,
    source_line_budget,
)


def search_code(tool_input: SearchCodeInput, context: SemanticToolExecutionContext) -> SemanticToolResult:
    tool_name = SemanticToolName.SEARCH_CODE
    try:
        root = resolve_component_path(context, tool_input.path_prefix) if tool_input.path_prefix else context.component_root
    except ToolBlockedError as exc:
        return result(tool_name, SemanticToolResultStatus.BLOCKED, str(exc))

    if tool_input.max_matches < 1 or tool_input.max_matches > MAX_SEARCH_MATCHES:
        return result(tool_name, SemanticToolResultStatus.INVALID_INPUT, "max_matches is outside allowed range")
    if tool_input.context_lines < 0 or tool_input.context_lines > MAX_SEARCH_CONTEXT_LINES:
        return result(tool_name, SemanticToolResultStatus.INVALID_INPUT, "context_lines is outside allowed range")
    observations: list[dict] = []
    evidence_items = []
    files_read = 0
    matches_examined = 0
    truncated = False
    source_lines_returned = 0
    query = tool_input.query if tool_input.case_sensitive else tool_input.query.lower()

    for path in iter_component_files(context, root):
        if len(observations) >= tool_input.max_matches:
            truncated = True
            break
        try:
            text = read_text_file(path)
        except ToolUnsupportedError:
            continue
        files_read += 1
        lines = text.splitlines()
        for line_no, line in enumerate(lines, start=1):
            haystack = line if tool_input.case_sensitive else line.lower()
            if query not in haystack:
                continue
            matches_examined += 1
            start_line = max(1, line_no - tool_input.context_lines)
            end_line = min(len(lines), line_no + tool_input.context_lines)
            excerpt_lines = end_line - start_line + 1
            if source_lines_returned + excerpt_lines > source_line_budget(context):
                truncated = True
                break
            excerpt = line_excerpt(lines, start_line, end_line)
            evidence = make_evidence(tool_name, context, path, start_line, end_line, excerpt)
            evidence_items.append(evidence)
            source_lines_returned += excerpt_lines
            observations.append({
                "path": relative_repo_path(context, path),
                "line": line_no,
                "matched_text": redacted(line.strip()),
                "evidence_ref": evidence.evidence_id,
            })
            if len(observations) >= tool_input.max_matches:
                truncated = True
                break

    if not observations:
        return result(
            tool_name,
            SemanticToolResultStatus.NO_MATCH,
            "literal query was not found",
            usage=SemanticToolUsage(files_read=files_read, matches_examined=matches_examined),
        )
    return ok_result(
        tool_name,
        evidence=evidence_items,
        observations=observations,
        usage=SemanticToolUsage(
            files_read=files_read,
            source_lines_returned=sum(item.end_line - item.start_line + 1 for item in evidence_items),
            matches_examined=matches_examined,
            truncated=truncated,
        ),
    )
