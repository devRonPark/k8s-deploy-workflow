"""제한된 semantic 읽기 도구 4종의 실행 디스패처 (allowed_tools·범위 강제)."""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from preanalyzer.models.semantic_tools import (
    FindCommandTargetInput,
    InspectEntrypointScriptInput,
    ReadSourceRangeInput,
    SearchCodeInput,
    SemanticToolName,
    SemanticToolResult,
    SemanticToolResultStatus,
    SemanticToolUsage,
)
from preanalyzer.semantic.tools.common import SemanticToolExecutionContext, build_semantic_tool_context
from preanalyzer.semantic.tools.find_command_target import find_command_target
from preanalyzer.semantic.tools.inspect_entrypoint_script import inspect_entrypoint_script
from preanalyzer.semantic.tools.read_source_range import read_source_range
from preanalyzer.semantic.tools.search_code import search_code


_TOOL_INPUTS = {
    SemanticToolName.SEARCH_CODE.value: SearchCodeInput,
    SemanticToolName.READ_SOURCE_RANGE.value: ReadSourceRangeInput,
    SemanticToolName.INSPECT_ENTRYPOINT_SCRIPT.value: InspectEntrypointScriptInput,
    SemanticToolName.FIND_COMMAND_TARGET.value: FindCommandTargetInput,
}

_TOOL_FUNCTIONS = {
    SemanticToolName.SEARCH_CODE.value: search_code,
    SemanticToolName.READ_SOURCE_RANGE.value: read_source_range,
    SemanticToolName.INSPECT_ENTRYPOINT_SCRIPT.value: inspect_entrypoint_script,
    SemanticToolName.FIND_COMMAND_TARGET.value: find_command_target,
}


def execute_semantic_tool(
    tool_name: SemanticToolName | str,
    tool_input: BaseModel | dict,
    context: SemanticToolExecutionContext,
) -> SemanticToolResult:
    try:
        name = SemanticToolName(str(tool_name))
    except ValueError:
        return _result(str(tool_name), SemanticToolResultStatus.UNSUPPORTED, "unknown semantic tool")

    if name.value not in context.allowed_tools:
        return _result(name.value, SemanticToolResultStatus.BLOCKED, "tool is not allowed for this task")

    input_model = _TOOL_INPUTS[name.value]
    try:
        parsed_input = tool_input if isinstance(tool_input, input_model) else input_model.model_validate(tool_input)
    except ValidationError:
        return _result(name.value, SemanticToolResultStatus.INVALID_INPUT, "tool input does not match schema")

    try:
        return _TOOL_FUNCTIONS[name.value](parsed_input, context)
    except Exception:
        return _result(name.value, SemanticToolResultStatus.ERROR, "tool execution failed")


def _result(tool_name: str, status: SemanticToolResultStatus, message: str) -> SemanticToolResult:
    try:
        name = SemanticToolName(tool_name)
    except ValueError:
        name = SemanticToolName.SEARCH_CODE
    return SemanticToolResult(tool_name=name, status=status, usage=SemanticToolUsage(), message=message)


__all__ = [
    "SemanticToolExecutionContext",
    "build_semantic_tool_context",
    "execute_semantic_tool",
]
