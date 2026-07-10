import unittest

from preanalyzer.analyzer.runtime_command_resolver import analyze_runtime_commands
from preanalyzer.models.evidence import EvidenceFact, EvidenceModel
from preanalyzer.models.rule_inference import ComponentCandidate, RuleInferenceSet, RuntimeCommandCandidate
from preanalyzer.models.runtime_command_analysis import (
    RuntimeCommandGapReason,
    RuntimeCommandResolutionStatus,
)


def fact(evidence_id, fact_type, artifact_ref, source, value):
    return EvidenceFact(
        evidence_id=evidence_id,
        fact_type=fact_type,
        artifact_ref=artifact_ref,
        source=source,
        classification="observed_fact",
        value=value,
    )


def model(*facts):
    return EvidenceModel(facts=list(facts))


def rules(*, components=None, commands=None):
    return RuleInferenceSet(
        component_candidates=components or [ComponentCandidate("api", ".", "test", ["FC"])],
        runtime_command_candidates=commands or [],
    )


def docker_cmd(command, evidence_id="F001", artifact_ref="Dockerfile", component_id="api"):
    return RuntimeCommandCandidate(component_id, command, "dockerfile_cmd", "high", [evidence_id])


class RuntimeCommandResolverTests(unittest.TestCase):
    def assert_resolved(self, analysis, command, evidence_refs=None, source=None, confidence=None):
        self.assertEqual(len(analysis.gaps), 0)
        self.assertEqual(len(analysis.resolved_commands), 1)
        resolved = analysis.resolved_commands[0]
        self.assertEqual(resolved.command, command)
        self.assertEqual(resolved.classification, "deterministic_runtime_command_analysis")
        if evidence_refs is not None:
            self.assertEqual(resolved.evidence_refs, evidence_refs)
        if source is not None:
            self.assertEqual(resolved.source, source)
        if confidence is not None:
            self.assertEqual(resolved.confidence, confidence)
        return resolved

    def assert_gap(self, analysis, status, reason_code, evidence_refs=None):
        self.assertEqual(len(analysis.resolved_commands), 0)
        self.assertEqual(len(analysis.gaps), 1)
        gap = analysis.gaps[0]
        self.assertEqual(gap.status, status)
        self.assertEqual(gap.reason_code, reason_code)
        if evidence_refs is not None:
            self.assertEqual(gap.evidence_refs, evidence_refs)
        return gap

    def test_exec_form_cmd_alone_resolved(self):
        analysis = analyze_runtime_commands(
            model(fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", '["node", "server.js"]')),
            rules(commands=[docker_cmd('["node", "server.js"]')]),
        )

        self.assert_resolved(analysis, "node server.js", ["F001"], "dockerfile_cmd", "high")

    def test_shell_form_simple_direct_command_resolved(self):
        analysis = analyze_runtime_commands(
            model(fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", "node server.js")),
            rules(commands=[docker_cmd("node server.js")]),
        )

        self.assert_resolved(analysis, "node server.js")

    def test_exec_form_entrypoint_alone_resolved(self):
        analysis = analyze_runtime_commands(
            model(fact("F001", "dockerfile_entrypoint", "Dockerfile", "dockerfile_entrypoint", '["python", "-m", "app.main"]')),
            rules(),
        )

        self.assert_resolved(analysis, "python -m app.main", ["F001"], "dockerfile_entrypoint", "high")

    def test_exec_form_entrypoint_and_exec_form_cmd_combined(self):
        analysis = analyze_runtime_commands(
            model(
                fact("F001", "dockerfile_entrypoint", "Dockerfile", "dockerfile_entrypoint", '["python"]'),
                fact("F002", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", '["-m", "app.main"]'),
            ),
            rules(commands=[docker_cmd('["-m", "app.main"]', evidence_id="F002")]),
        )

        self.assert_resolved(analysis, "python -m app.main", ["F001", "F002"], "dockerfile_entrypoint+dockerfile_cmd", "high")

    def test_entrypoint_and_cmd_evidence_refs_are_preserved(self):
        analysis = analyze_runtime_commands(
            model(
                fact("F010", "dockerfile_entrypoint", "Dockerfile", "dockerfile_entrypoint", '["uvicorn"]'),
                fact("F011", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", '["main:app"]'),
            ),
            rules(commands=[docker_cmd('["main:app"]', evidence_id="F011")]),
        )

        self.assertEqual(analysis.resolved_commands[0].evidence_refs, ["F010", "F011"])

    def test_shell_script_cmd_requires_source_analysis(self):
        analysis = analyze_runtime_commands(
            model(fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", "./entrypoint.sh")),
            rules(commands=[docker_cmd("./entrypoint.sh")]),
        )

        self.assert_gap(
            analysis,
            RuntimeCommandResolutionStatus.REQUIRES_SOURCE_ANALYSIS,
            RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT,
            ["F001"],
        )

    def test_shell_script_entrypoint_requires_source_analysis(self):
        analysis = analyze_runtime_commands(
            model(fact("F001", "dockerfile_entrypoint", "Dockerfile", "dockerfile_entrypoint", '["/app/start.sh"]')),
            rules(),
        )

        self.assert_gap(
            analysis,
            RuntimeCommandResolutionStatus.REQUIRES_SOURCE_ANALYSIS,
            RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT,
            ["F001"],
        )

    def test_sh_entrypoint_script_requires_source_analysis(self):
        analysis = analyze_runtime_commands(
            model(fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", "sh entrypoint.sh")),
            rules(commands=[docker_cmd("sh entrypoint.sh")]),
        )

        self.assert_gap(
            analysis,
            RuntimeCommandResolutionStatus.REQUIRES_SOURCE_ANALYSIS,
            RuntimeCommandGapReason.SHELL_SCRIPT_ENTRYPOINT,
        )

    def test_compound_shell_command_gap(self):
        analysis = analyze_runtime_commands(
            model(fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", "npm run build && node server.js")),
            rules(commands=[docker_cmd("npm run build && node server.js")]),
        )

        self.assert_gap(
            analysis,
            RuntimeCommandResolutionStatus.REQUIRES_SOURCE_ANALYSIS,
            RuntimeCommandGapReason.COMPOUND_SHELL_COMMAND,
        )

    def test_invalid_json_exec_form_gap(self):
        analysis = analyze_runtime_commands(
            model(fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", '["node",]')),
            rules(commands=[docker_cmd('["node",]')]),
        )

        self.assert_gap(
            analysis,
            RuntimeCommandResolutionStatus.INSUFFICIENT_EVIDENCE,
            RuntimeCommandGapReason.UNSUPPORTED_COMMAND_FORM,
        )

    def test_npm_start_resolves_package_script(self):
        analysis = analyze_runtime_commands(
            model(
                fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", "npm start"),
                fact("F002", "package_script", "package.json", "package.json", {"name": "start", "command": "node server.js"}),
            ),
            rules(commands=[docker_cmd("npm start")]),
        )

        self.assert_resolved(analysis, "node server.js", ["F001", "F002"], "dockerfile_cmd+package_script")

    def test_npm_run_named_script_resolves(self):
        analysis = analyze_runtime_commands(
            model(
                fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", "npm run start:prod"),
                fact("F002", "package_script", "package.json", "package.json", {"name": "start:prod", "command": "node prod.js"}),
            ),
            rules(commands=[docker_cmd("npm run start:prod")]),
        )

        self.assert_resolved(analysis, "node prod.js")

    def test_yarn_script_resolves(self):
        analysis = analyze_runtime_commands(
            model(
                fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", "yarn worker"),
                fact("F002", "package_script", "package.json", "package.json", {"name": "worker", "command": "node worker.js"}),
            ),
            rules(commands=[docker_cmd("yarn worker")]),
        )

        self.assert_resolved(analysis, "node worker.js")

    def test_pnpm_script_resolves(self):
        analysis = analyze_runtime_commands(
            model(
                fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", "pnpm run serve"),
                fact("F002", "package_script", "package.json", "package.json", {"name": "serve", "command": "vite --host 0.0.0.0"}),
            ),
            rules(commands=[docker_cmd("pnpm run serve")]),
        )

        self.assert_resolved(analysis, "vite --host 0.0.0.0")

    def test_package_script_two_step_chaining(self):
        analysis = analyze_runtime_commands(
            model(
                fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", "npm run start"),
                fact("F002", "package_script", "package.json", "package.json", {"name": "start", "command": "npm run start:prod"}),
                fact("F003", "package_script", "package.json", "package.json", {"name": "start:prod", "command": "node server.js"}),
            ),
            rules(commands=[docker_cmd("npm run start")]),
        )

        self.assert_resolved(analysis, "node server.js", ["F001", "F002", "F003"])

    def test_package_script_max_depth_limit_leaves_gap(self):
        analysis = analyze_runtime_commands(
            model(
                fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", "npm run s0"),
                fact("F002", "package_script", "package.json", "package.json", {"name": "s0", "command": "npm run s1"}),
                fact("F003", "package_script", "package.json", "package.json", {"name": "s1", "command": "npm run s2"}),
                fact("F004", "package_script", "package.json", "package.json", {"name": "s2", "command": "npm run s3"}),
                fact("F005", "package_script", "package.json", "package.json", {"name": "s3", "command": "npm run s4"}),
                fact("F006", "package_script", "package.json", "package.json", {"name": "s4", "command": "npm run s5"}),
                fact("F007", "package_script", "package.json", "package.json", {"name": "s5", "command": "node server.js"}),
            ),
            rules(commands=[docker_cmd("npm run s0")]),
        )

        self.assert_gap(
            analysis,
            RuntimeCommandResolutionStatus.REQUIRES_SOURCE_ANALYSIS,
            RuntimeCommandGapReason.UNRESOLVED_PACKAGE_SCRIPT,
        )

    def test_package_script_cycle_detected(self):
        analysis = analyze_runtime_commands(
            model(
                fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", "npm run start"),
                fact("F002", "package_script", "package.json", "package.json", {"name": "start", "command": "npm run loop"}),
                fact("F003", "package_script", "package.json", "package.json", {"name": "loop", "command": "npm run start"}),
            ),
            rules(commands=[docker_cmd("npm run start")]),
        )

        self.assert_gap(
            analysis,
            RuntimeCommandResolutionStatus.CYCLE_DETECTED,
            RuntimeCommandGapReason.PACKAGE_SCRIPT_CYCLE,
            ["F001", "F002", "F003"],
        )

    def test_missing_package_script_reference_is_invalid(self):
        analysis = analyze_runtime_commands(
            model(fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", "npm run production")),
            rules(commands=[docker_cmd("npm run production")]),
        )

        self.assert_gap(
            analysis,
            RuntimeCommandResolutionStatus.INVALID_REFERENCE,
            RuntimeCommandGapReason.UNRESOLVED_PACKAGE_SCRIPT,
        )

    def test_package_script_outside_component_root_is_not_used(self):
        components = [ComponentCandidate("api", "apps/api", "test", ["FC"])]
        analysis = analyze_runtime_commands(
            model(
                fact("F001", "dockerfile_cmd", "apps/api/Dockerfile", "dockerfile_cmd", "npm run start"),
                fact("F002", "package_script", "apps/worker/package.json", "package.json", {"name": "start", "command": "node worker.js"}),
            ),
            rules(components=components, commands=[docker_cmd("npm run start", artifact_ref="apps/api/Dockerfile")]),
        )

        self.assert_gap(
            analysis,
            RuntimeCommandResolutionStatus.INVALID_REFERENCE,
            RuntimeCommandGapReason.UNRESOLVED_PACKAGE_SCRIPT,
        )

    def test_single_start_script_without_dockerfile_resolves_medium(self):
        analysis = analyze_runtime_commands(
            model(fact("F001", "package_script", "package.json", "package.json", {"name": "start", "command": "node server.js"})),
            rules(),
        )

        self.assert_resolved(analysis, "node server.js", ["F001"], "package_script", "medium")

    def test_multiple_start_scripts_without_dockerfile_are_ambiguous(self):
        components = [ComponentCandidate("suite", "services", "test", ["FC"])]
        analysis = analyze_runtime_commands(
            model(
                fact("F001", "package_script", "services/api/package.json", "package.json", {"name": "start", "command": "node api.js"}),
                fact("F002", "package_script", "services/worker/package.json", "package.json", {"name": "start", "command": "node worker.js"}),
            ),
            rules(components=components),
        )

        gap = self.assert_gap(
            analysis,
            RuntimeCommandResolutionStatus.AMBIGUOUS,
            RuntimeCommandGapReason.CONFLICTING_EXPLICIT_COMMANDS,
        )
        self.assertEqual(sorted(gap.candidate_commands), ["node api.js", "node worker.js"])
        self.assertEqual(
            [alternative.model_dump() for alternative in gap.candidate_alternatives],
            [
                {
                    "command": "node api.js",
                    "source": "package_script",
                    "confidence": "medium",
                    "classification": "deterministic_runtime_command_analysis",
                    "evidence_refs": ["F001"],
                },
                {
                    "command": "node worker.js",
                    "source": "package_script",
                    "confidence": "medium",
                    "classification": "deterministic_runtime_command_analysis",
                    "evidence_refs": ["F002"],
                },
            ],
        )

    def test_independent_command_conflict_preserved(self):
        analysis = analyze_runtime_commands(
            model(
                fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", '["node", "server.js"]'),
                fact("F002", "runtime_command", "deploy.yaml", "existing_candidate", "python -m app.main"),
            ),
            rules(commands=[
                docker_cmd('["node", "server.js"]'),
                RuntimeCommandCandidate("api", "python -m app.main", "existing_candidate", "medium", ["F002"]),
            ]),
        )

        gap = self.assert_gap(
            analysis,
            RuntimeCommandResolutionStatus.AMBIGUOUS,
            RuntimeCommandGapReason.CONFLICTING_EXPLICIT_COMMANDS,
            ["F001", "F002"],
        )
        self.assertEqual(sorted(gap.candidate_commands), ["node server.js", "python -m app.main"])
        self.assertEqual(
            [alternative.model_dump() for alternative in gap.candidate_alternatives],
            [
                {
                    "command": "node server.js",
                    "source": "dockerfile_cmd",
                    "confidence": "high",
                    "classification": "deterministic_runtime_command_analysis",
                    "evidence_refs": ["F001"],
                },
                {
                    "command": "python -m app.main",
                    "source": "existing_candidate",
                    "confidence": "medium",
                    "classification": "deterministic_runtime_command_analysis",
                    "evidence_refs": ["F002"],
                },
            ],
        )

    def test_identical_commands_are_deduplicated(self):
        analysis = analyze_runtime_commands(
            model(
                fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", "node server.js"),
                fact("F002", "runtime_command", "deploy.yaml", "existing_candidate", "node server.js"),
            ),
            rules(commands=[
                docker_cmd("node server.js"),
                RuntimeCommandCandidate("api", "node server.js", "existing_candidate", "medium", ["F002"]),
            ]),
        )

        self.assert_resolved(analysis, "node server.js", ["F001", "F002"])

    def test_same_input_produces_same_output(self):
        evidence = model(fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", '["node", "server.js"]'))
        inference = rules(commands=[docker_cmd('["node", "server.js"]')])

        first = analyze_runtime_commands(evidence, inference)
        second = analyze_runtime_commands(evidence, inference)

        self.assertEqual(first.model_dump(), second.model_dump())

    def test_secret_like_environment_value_does_not_enter_result(self):
        analysis = analyze_runtime_commands(
            model(
                fact("F001", "dockerfile_cmd", "Dockerfile", "dockerfile_cmd", "node server.js"),
                fact("F002", "compose_environment", "docker-compose.yml", "compose_environment", {"service": "api", "name": "API_SECRET", "value_present": True}),
            ),
            rules(commands=[docker_cmd("node server.js")]),
        )

        dumped = str(analysis.model_dump())
        self.assertNotIn("super-secret", dumped)
        self.assertNotIn("API_SECRET", dumped)
        self.assert_resolved(analysis, "node server.js")


if __name__ == "__main__":
    unittest.main()
