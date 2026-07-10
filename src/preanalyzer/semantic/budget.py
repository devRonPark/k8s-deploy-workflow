"""Task-level cumulative budget enforcement for the semantic tool layer.

Individual tools cap their own single-call output, but nothing stops an agent
from issuing many small calls that together blow past a task's budget. The
:class:`SemanticToolSession` runs every tool call through a shared
:class:`BudgetLedger`, pre-checking call/tool ceilings before execution and
folding actual usage (unique files, source lines, schema retries) in after,
so the *task total* is enforced centrally. Once any ceiling is reached the
ledger latches "exhausted" and further calls are refused without execution —
evidence already gathered is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading

from preanalyzer.models.semantic import SemanticTaskBudget
from preanalyzer.models.semantic_tools import (
    SemanticToolName,
    SemanticToolResult,
    SemanticToolResultStatus,
    SemanticToolUsage,
)
from preanalyzer.semantic.tools import execute_semantic_tool
from preanalyzer.semantic.tools.common import SemanticToolExecutionContext


@dataclass
class BudgetLedger:
    tool_calls: int = 0
    distinct_tools: set[str] = field(default_factory=set)
    files_read: set[str] = field(default_factory=set)
    source_lines_returned: int = 0
    schema_retries: int = 0


class SemanticToolSession:
    """Serialized, budget-enforcing wrapper around ``execute_semantic_tool``."""

    def __init__(
        self,
        context: SemanticToolExecutionContext,
        budget: SemanticTaskBudget | None = None,
        executor=execute_semantic_tool,
    ):
        self.context = context
        self.budget = budget or getattr(context, "task_budget", None) or SemanticTaskBudget()
        self.ledger = BudgetLedger()
        self._executor = executor
        self._exhausted_reason: str | None = None
        self._lock = threading.Lock()

    @property
    def exhausted(self) -> bool:
        return self._exhausted_reason is not None

    @property
    def exhausted_reason(self) -> str | None:
        return self._exhausted_reason

    def call(self, tool_name: SemanticToolName | str, tool_input) -> SemanticToolResult:
        with self._lock:
            reason = self._precheck(str(tool_name))
            if reason is not None:
                self._exhausted_reason = self._exhausted_reason or reason
                return self._budget_exhausted_result(tool_name, reason)

            result = self._executor(tool_name, tool_input, self.context)
            self._record(str(tool_name), result)
            return result

    def _precheck(self, tool_name: str) -> str | None:
        if self._exhausted_reason is not None:
            return self._exhausted_reason
        if self.ledger.tool_calls + 1 > self.budget.max_tool_calls:
            return "max_tool_calls"
        if tool_name not in self.ledger.distinct_tools:
            if len(self.ledger.distinct_tools) + 1 > self.budget.max_distinct_tools:
                return "max_distinct_tools"
        return None

    def _record(self, tool_name: str, result: SemanticToolResult) -> None:
        self.ledger.tool_calls += 1
        self.ledger.distinct_tools.add(tool_name)
        for evidence in result.evidence:
            self.ledger.files_read.add(evidence.path)
        self.ledger.source_lines_returned += result.usage.source_lines_returned
        if result.status == SemanticToolResultStatus.INVALID_INPUT.value:
            self.ledger.schema_retries += 1

        # Post-hoc ceilings (usage is only known after execution). Latching here
        # blocks the *next* call while preserving this call's evidence.
        if len(self.ledger.files_read) > self.budget.max_files_read:
            self._exhausted_reason = "max_files_read"
        elif self.ledger.source_lines_returned > self.budget.max_source_lines:
            self._exhausted_reason = "max_source_lines"
        elif self.ledger.schema_retries > self.budget.max_schema_retries:
            self._exhausted_reason = "max_schema_retries"
        elif self.ledger.tool_calls >= self.budget.max_tool_calls:
            self._exhausted_reason = "max_tool_calls"

    def _budget_exhausted_result(self, tool_name, reason: str) -> SemanticToolResult:
        try:
            name = SemanticToolName(str(tool_name))
        except ValueError:
            name = SemanticToolName.SEARCH_CODE
        return SemanticToolResult(
            tool_name=name,
            status=SemanticToolResultStatus.BUDGET_EXHAUSTED,
            usage=SemanticToolUsage(),
            message=f"task budget exhausted: {reason}",
        )

    def budget_status(self) -> dict:
        """Structured budget usage for the final semantic output."""
        return {
            "status": "budget_exhausted" if self.exhausted else "within_budget",
            "reason": self._exhausted_reason,
            "budget": {
                "max_tool_calls": self.budget.max_tool_calls,
                "used_tool_calls": self.ledger.tool_calls,
                "max_distinct_tools": self.budget.max_distinct_tools,
                "used_distinct_tools": len(self.ledger.distinct_tools),
                "max_files_read": self.budget.max_files_read,
                "used_files_read": len(self.ledger.files_read),
                "max_source_lines": self.budget.max_source_lines,
                "used_source_lines": self.ledger.source_lines_returned,
                "max_schema_retries": self.budget.max_schema_retries,
                "used_schema_retries": self.ledger.schema_retries,
            },
            "partial_evidence_preserved": True,
        }


__all__ = ["BudgetLedger", "SemanticToolSession"]
