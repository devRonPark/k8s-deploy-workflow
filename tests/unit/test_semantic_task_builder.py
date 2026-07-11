import unittest

from preanalyzer.models.runtime_command_analysis import (
    ResolvedRuntimeCommand,
    RuntimeCommandAlternative,
    RuntimeCommandAnalysis,
    RuntimeCommandGap,
    RuntimeCommandGapReason,
    RuntimeCommandResolutionStatus,
)
from preanalyzer.models.semantic import SemanticTaskBuildDisposition
from preanalyzer.semantic.task_builder import (
    build_runtime_command_semantic_tasks,
    route_runtime_command_gap_reason,
    runtime_command_target_field,
)


FORBIDDEN_TOOLS = {
    "shell_execute",
    "run_application",
    "write_file",
    "network_access",
    "install_dependency",
}


def gap(
    reason_code,
    *,
    component_id="api",
    status=RuntimeCommandResolutionStatus.REQUIRES_SOURCE_ANALYSIS,
    evidence_refs=None,
    candidate_commands=None,
    candidate_alternatives=None,
):
    return RuntimeCommandGap(
        component_id=component_id,
        status=status,
        reason_code=reason_code,
        description=f"input description for {reason_code}",
        evidence_refs=evidence_refs or ["F001"],
        candidate_commands=candidate_commands or [],
        candidate_alternatives=candidate_alternatives or [],
    )


def resolved(
    command="node server.js",
    *,
    component_id="api",
    evidence_refs=None,
    source="dockerfile_cmd",
    confidence="high",
):
    return ResolvedRuntimeCommand(
        component_id=component_id,
        command=command,
        source=source,
        confidence=confidence,
        evidence_refs=evidence_refs or ["F010"],
        resolution_method="exec_command",
    )


def alternative(
    command="node server.js",
    *,
    source="dockerfile_cmd",
    confidence="high",
    classification="deterministic_runtime_command_analysis",
    evidence_refs=None,
):
    return RuntimeCommandAlternative(
        command=command,
        source=source,
        confidence=confidence,
        classification=classification,
        evidence_refs=evidence_refs or ["F020"],
    )


class SemanticTaskBuilderTests(unittest.TestCase):
    def build(self, analysis):
        return build_runtime_command_semantic_tasks(analysis)

    def assert_no_tasks(self, result):
        self.assertEqual(result.tasks, [])

    def assert_one_task(self, result):
        self.assertEqual(len(result.tasks), 1)
        return result.tasks[0]

    def test_gapless_analysis_creates_no_tasks_or_decisions(self):
        result = self.build(RuntimeCommandAnalysis())

        self.assertEqual(result.model_dump(), {"tasks": [], "decisions": []})

    def test_resolved_command_without_gap_creates_no_tasks(self):
        result = self.build(RuntimeCommandAnalysis(resolved_commands=[resolved()]))

        self.assert_no_tasks(result)
        self.assertEqual(result.decisions, [])

    def test_shell_script_entrypoint_gap_creates_task(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT)]))

        task = self.assert_one_task(result)
        self.assertEqual(task.task_type, "resolve_runtime_command")
        self.assertEqual(task.component_id, "api")
        self.assertEqual(task.target_field, "/components/api/runtime/command")
        self.assertEqual(result.decisions[0].disposition, "task_created")
        self.assertEqual(result.decisions[0].task_id, task.task_id)

    def test_compound_shell_command_gap_creates_task(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[gap(RuntimeCommandGapReason.COMPOUND_SHELL_COMMAND)]))

        task = self.assert_one_task(result)
        self.assertEqual(task.reason.code, "compound_shell_command")

    def test_missing_runtime_command_gap_creates_task(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[gap(RuntimeCommandGapReason.MISSING_RUNTIME_COMMAND)]))

        task = self.assert_one_task(result)
        self.assertEqual(task.reason.code, "missing_runtime_command")

    def test_conflicting_explicit_commands_gap_creates_task(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[
            gap(
                RuntimeCommandGapReason.CONFLICTING_EXPLICIT_COMMANDS,
                status=RuntimeCommandResolutionStatus.AMBIGUOUS,
                candidate_alternatives=[
                    alternative("node server.js", evidence_refs=["F001"]),
                    alternative("python -m app.main", source="existing_candidate", confidence="medium", evidence_refs=["F002"]),
                ],
            )
        ]))

        task = self.assert_one_task(result)
        self.assertEqual(task.reason.code, "conflicting_explicit_commands")
        self.assertEqual([candidate.value for candidate in task.known_candidates], ["node server.js", "python -m app.main"])

    def test_unresolved_package_script_is_not_agent_actionable(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[gap(RuntimeCommandGapReason.UNRESOLVED_PACKAGE_SCRIPT)]))

        self.assert_no_tasks(result)
        self.assertEqual(result.decisions[0].disposition, "not_agent_actionable")
        self.assertIsNone(result.decisions[0].task_id)

    def test_package_script_cycle_is_not_agent_actionable(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[gap(RuntimeCommandGapReason.PACKAGE_SCRIPT_CYCLE)]))

        self.assert_no_tasks(result)
        self.assertEqual(result.decisions[0].disposition, "not_agent_actionable")

    def test_unsupported_command_form_is_unsupported_for_mvp(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[gap(RuntimeCommandGapReason.UNSUPPORTED_COMMAND_FORM)]))

        self.assert_no_tasks(result)
        self.assertEqual(result.decisions[0].disposition, "unsupported_for_mvp")

    def test_unregistered_reason_fails_closed_to_unsupported(self):
        disposition = route_runtime_command_gap_reason("future_reason")

        self.assertEqual(disposition, SemanticTaskBuildDisposition.UNSUPPORTED_FOR_MVP)

    def test_same_component_eligible_gaps_merge_into_one_task_with_per_gap_decisions(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[
            gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT, evidence_refs=["F002", "F001"]),
            gap(RuntimeCommandGapReason.COMPOUND_SHELL_COMMAND, evidence_refs=["F001", "F003"]),
        ]))

        task = self.assert_one_task(result)
        self.assertEqual(len(result.decisions), 2)
        self.assertEqual(task.reason.code, "multiple_runtime_command_gaps")
        self.assertEqual(task.reason.description, "Runtime command semantic analysis requested for reasons: compound_shell_command, shell_script_entrypoint.")
        self.assertEqual([ref.evidence_id for ref in task.evidence_refs], ["F001", "F002", "F003"])
        self.assertEqual({decision.task_id for decision in result.decisions}, {task.task_id})

    def test_candidate_deduplication_preserves_metadata_once(self):
        alt = alternative("node server.js", evidence_refs=["F001"])
        result = self.build(RuntimeCommandAnalysis(gaps=[
            gap(RuntimeCommandGapReason.CONFLICTING_EXPLICIT_COMMANDS, candidate_alternatives=[alt, alt])
        ]))

        task = self.assert_one_task(result)
        self.assertEqual(len(task.known_candidates), 1)
        self.assertEqual(task.known_candidates[0].model_dump(), {
            "value": "node server.js",
            "source": "dockerfile_cmd",
            "confidence": "high",
            "classification": "deterministic_runtime_command_analysis",
            "evidence_refs": ["F001"],
        })

    def test_allowed_tools_are_reason_allowlist_union_in_stable_order(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[
            gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT),
            gap(RuntimeCommandGapReason.COMPOUND_SHELL_COMMAND),
        ]))

        task = self.assert_one_task(result)
        self.assertEqual(task.allowed_tools, [
            "find_command_target",
            "inspect_entrypoint_script",
            "read_source_range",
            "search_code",
        ])

    def test_duplicate_component_target_field_task_is_rejected_by_result_model(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[
            gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT),
            gap(RuntimeCommandGapReason.COMPOUND_SHELL_COMMAND),
        ]))

        self.assertEqual(len({(task.component_id, task.target_field) for task in result.tasks}), len(result.tasks))

    def test_same_input_produces_same_task_id(self):
        analysis = RuntimeCommandAnalysis(gaps=[gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT, evidence_refs=["F002", "F001"])])

        first = self.build(analysis)
        second = self.build(analysis)

        self.assertEqual(first.tasks[0].task_id, second.tasks[0].task_id)

    def test_gap_input_order_does_not_change_task_id(self):
        first = self.build(RuntimeCommandAnalysis(gaps=[
            gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT, evidence_refs=["F001"]),
            gap(RuntimeCommandGapReason.COMPOUND_SHELL_COMMAND, evidence_refs=["F002"]),
        ]))
        second = self.build(RuntimeCommandAnalysis(gaps=[
            gap(RuntimeCommandGapReason.COMPOUND_SHELL_COMMAND, evidence_refs=["F002"]),
            gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT, evidence_refs=["F001"]),
        ]))

        self.assertEqual(first.tasks[0].task_id, second.tasks[0].task_id)

    def test_evidence_order_does_not_change_task_id(self):
        first = self.build(RuntimeCommandAnalysis(gaps=[gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT, evidence_refs=["F001", "F002"])]))
        second = self.build(RuntimeCommandAnalysis(gaps=[gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT, evidence_refs=["F002", "F001"])]))

        self.assertEqual(first.tasks[0].task_id, second.tasks[0].task_id)

    def test_component_change_changes_task_id(self):
        first = self.build(RuntimeCommandAnalysis(gaps=[gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT, component_id="api")]))
        second = self.build(RuntimeCommandAnalysis(gaps=[gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT, component_id="worker")]))

        self.assertNotEqual(first.tasks[0].task_id, second.tasks[0].task_id)

    def test_tasks_are_sorted_by_component_and_target_field(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[
            gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT, component_id="worker"),
            gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT, component_id="api"),
        ]))

        self.assertEqual([task.component_id for task in result.tasks], ["api", "worker"])

    def test_target_field_for_plain_component_id(self):
        self.assertEqual(runtime_command_target_field("api"), "/components/api/runtime/command")

    def test_target_field_escapes_slash(self):
        self.assertEqual(runtime_command_target_field("api/v1"), "/components/api~1v1/runtime/command")

    def test_target_field_escapes_tilde(self):
        self.assertEqual(runtime_command_target_field("api~v1"), "/components/api~0v1/runtime/command")

    def test_phase1_evidence_reference_conversion_without_line_range(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT, evidence_refs=["F009"])]))

        ref = self.assert_one_task(result).evidence_refs[0]
        self.assertEqual(ref.model_dump(), {
            "evidence_id": "F009",
            "origin": "phase1",
            "path": None,
            "start_line": None,
            "end_line": None,
        })

    def test_resolved_command_is_preserved_as_known_candidate(self):
        result = self.build(RuntimeCommandAnalysis(
            resolved_commands=[resolved("node server.js", evidence_refs=["F010"], source="dockerfile_cmd", confidence="high")],
            gaps=[gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT, evidence_refs=["F001"])],
        ))

        task = self.assert_one_task(result)
        self.assertEqual(task.known_candidates[0].model_dump(), {
            "value": "node server.js",
            "source": "dockerfile_cmd",
            "confidence": "high",
            "classification": "deterministic_runtime_command_analysis",
            "evidence_refs": ["F010"],
        })

    def test_conflict_alternative_metadata_is_preserved_as_known_candidate(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[
            gap(
                RuntimeCommandGapReason.CONFLICTING_EXPLICIT_COMMANDS,
                candidate_alternatives=[
                    alternative("python -m app.main", source="existing_candidate", confidence="medium", evidence_refs=["F002"]),
                ],
            )
        ]))

        candidate = self.assert_one_task(result).known_candidates[0]
        self.assertEqual(candidate.value, "python -m app.main")
        self.assertEqual(candidate.source, "existing_candidate")
        self.assertEqual(candidate.confidence, "medium")
        self.assertEqual(candidate.classification, "deterministic_runtime_command_analysis")
        self.assertEqual(candidate.evidence_refs, ["F002"])

    def test_string_candidate_commands_do_not_invent_metadata(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[
            gap(RuntimeCommandGapReason.CONFLICTING_EXPLICIT_COMMANDS, candidate_commands=["node server.js"])
        ]))

        self.assert_one_task(result)
        self.assertEqual(result.tasks[0].known_candidates, [])

    def test_default_budget_is_used_for_every_task(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[gap(RuntimeCommandGapReason.MISSING_RUNTIME_COMMAND)]))

        self.assertEqual(self.assert_one_task(result).budget.model_dump(), {
            "max_agent_turns": 4,
            "max_tool_calls": 4,
            "max_distinct_tools": 3,
            "max_files_read": 5,
            "max_source_lines": 400,
            "max_schema_retries": 1,
        })

    def test_reason_specific_tool_allowlists(self):
        expected = {
            RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT: ["inspect_entrypoint_script", "read_source_range"],
            RuntimeCommandGapReason.COMPOUND_SHELL_COMMAND: ["read_source_range", "search_code", "find_command_target"],
            RuntimeCommandGapReason.MISSING_RUNTIME_COMMAND: ["search_code", "find_command_target", "read_source_range"],
            RuntimeCommandGapReason.CONFLICTING_EXPLICIT_COMMANDS: ["search_code", "read_source_range", "find_command_target"],
        }
        for reason, tools in expected.items():
            with self.subTest(reason=reason):
                task = self.assert_one_task(self.build(RuntimeCommandAnalysis(gaps=[gap(reason)])))
                self.assertEqual(task.allowed_tools, tools)

    def test_forbidden_tools_are_never_included(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[
            gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT),
            gap(RuntimeCommandGapReason.COMPOUND_SHELL_COMMAND),
            gap(RuntimeCommandGapReason.MISSING_RUNTIME_COMMAND),
            gap(RuntimeCommandGapReason.CONFLICTING_EXPLICIT_COMMANDS),
        ]))

        self.assertTrue(FORBIDDEN_TOOLS.isdisjoint(result.tasks[0].allowed_tools))

    def test_task_excludes_secret_values_and_repository_payloads_from_string_candidates(self):
        result = self.build(RuntimeCommandAnalysis(gaps=[
            gap(
                RuntimeCommandGapReason.CONFLICTING_EXPLICIT_COMMANDS,
                evidence_refs=["F001"],
                candidate_commands=["DATABASE_URL=postgres://user:secret@example/db node server.js"],
            )
        ]))

        dumped = str(result.model_dump())
        self.assertNotIn("secret@example", dumped)
        self.assertNotIn("DATABASE_URL=postgres", dumped)

    def test_repeated_builds_have_identical_dump(self):
        analysis = RuntimeCommandAnalysis(
            resolved_commands=[resolved("node server.js", evidence_refs=["F010"])],
            gaps=[
                gap(RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT, evidence_refs=["F002", "F001"]),
                gap(RuntimeCommandGapReason.COMPOUND_SHELL_COMMAND, evidence_refs=["F003"]),
            ],
        )

        self.assertEqual(self.build(analysis).model_dump(), self.build(analysis).model_dump())


if __name__ == "__main__":
    unittest.main()
