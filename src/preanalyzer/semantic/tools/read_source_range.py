"""도구: 지정 파일의 한정된 라인 범위만 읽기."""

from __future__ import annotations

from preanalyzer.models.semantic_tools import (
    ReadSourceRangeInput,
    SemanticToolName,
    SemanticToolResult,
    SemanticToolResultStatus,
    SemanticToolUsage,
)
from preanalyzer.semantic.tools.common import (
    MAX_READ_SOURCE_LINES,
    SemanticToolExecutionContext,
    ToolBlockedError,
    ToolUnsupportedError,
    line_excerpt,
    make_evidence,
    ok_result,
    read_text_file,
    resolve_existing_file,
    result,
    source_line_budget,
)


def read_source_range(tool_input: ReadSourceRangeInput, context: SemanticToolExecutionContext) -> SemanticToolResult:
    tool_name = SemanticToolName.READ_SOURCE_RANGE
    requested_lines = tool_input.end_line - tool_input.start_line + 1
    if requested_lines > MAX_READ_SOURCE_LINES or requested_lines > source_line_budget(context):
        return result(tool_name, SemanticToolResultStatus.INVALID_INPUT, "requested line range exceeds limit")

    try:
        path = resolve_existing_file(context, tool_input.path)
        text = read_text_file(path)
    except ToolBlockedError as exc:
        return result(tool_name, SemanticToolResultStatus.BLOCKED, str(exc))
    except ToolUnsupportedError as exc:
        return result(tool_name, SemanticToolResultStatus.UNSUPPORTED, str(exc))
    except FileNotFoundError:
        return result(tool_name, SemanticToolResultStatus.NOT_FOUND, "file was not found")

    lines = text.splitlines()
    if tool_input.end_line > len(lines):
        return result(tool_name, SemanticToolResultStatus.INVALID_INPUT, "requested range extends past end of file")

    excerpt = line_excerpt(lines, tool_input.start_line, tool_input.end_line)
    evidence = make_evidence(tool_name, context, path, tool_input.start_line, tool_input.end_line, excerpt)
    return ok_result(
        tool_name,
        evidence=[evidence],
        observations=[{
            "path": evidence.path,
            "line_range": f"{tool_input.start_line}-{tool_input.end_line}",
            "evidence_ref": evidence.evidence_id,
        }],
        usage=SemanticToolUsage(files_read=1, source_lines_returned=requested_lines),
    )
