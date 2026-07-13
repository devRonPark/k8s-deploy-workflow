from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from k8s_agent.agent.orchestrator import AgentOrchestrator, OrchestrationResult
from k8s_agent.cli import PrepareRequest
from k8s_agent.errors import AgentError
from k8s_agent.models.run import RunState
from k8s_agent.run.manager import RunManager
from k8s_agent.run.store import RunStore


FIXED_TIME = datetime(2026, 7, 13, 5, 6, 7, tzinfo=timezone.utc)


def request() -> PrepareRequest:
    return PrepareRequest(
        repo_url=None,
        local_path=Path("tests/fixtures/repos/node-express-like"),
        ref=None,
        target="development",
        non_interactive=False,
        answers_file=None,
    )


class AgentOrchestratorTests(unittest.TestCase):
    def test_ready_result_transitions_run_and_persists_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = _manager(tmp, "run-ready")
            manager.create(request())
            manager.transition("run-ready", RunState.ACQUIRING_SOURCE, "source acquisition started")

            orchestrator = AgentOrchestrator(
                run_manager=manager,
                pipeline=lambda run_id: OrchestrationResult(
                    state=RunState.READY,
                    exit_code=0,
                    message=f"{run_id} ready",
                    artifacts={"agent/summary.yaml": {"status": "ready"}},
                ),
            )
            outcome = orchestrator.run("run-ready")

            self.assertEqual(outcome.state, RunState.READY)
            self.assertEqual(outcome.exit_code, 0)
            self.assertEqual(manager.store.load("run-ready").state, RunState.READY)
            self.assertTrue((Path(tmp) / "run-ready" / "agent" / "summary.yaml").is_file())

    def test_blocked_result_uses_policy_blocked_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = _manager(tmp, "run-blocked")
            manager.create(request())
            manager.transition("run-blocked", RunState.ACQUIRING_SOURCE, "source acquisition started")

            orchestrator = AgentOrchestrator(
                run_manager=manager,
                pipeline=lambda _run_id: OrchestrationResult(
                    state=RunState.BLOCKED,
                    exit_code=4,
                    message="stateful workload requires design review",
                ),
            )
            outcome = orchestrator.run("run-blocked")

            self.assertEqual(outcome.state, RunState.BLOCKED)
            self.assertEqual(outcome.exit_code, 4)
            self.assertEqual(manager.store.load("run-blocked").state, RunState.BLOCKED)

    def test_waiting_result_is_non_error_and_records_waiting_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = _manager(tmp, "run-waiting")
            manager.create(request())
            manager.transition("run-waiting", RunState.ACQUIRING_SOURCE, "source acquisition started")

            orchestrator = AgentOrchestrator(
                run_manager=manager,
                pipeline=lambda _run_id: OrchestrationResult(
                    state=RunState.WAITING_FOR_USER,
                    exit_code=0,
                    message="deployment decisions are waiting for user input",
                ),
            )
            outcome = orchestrator.run("run-waiting")

            self.assertEqual(outcome.state, RunState.WAITING_FOR_USER)
            self.assertEqual(outcome.exit_code, 0)
            self.assertEqual(manager.store.load("run-waiting").state, RunState.WAITING_FOR_USER)

    def test_repair_success_result_is_ready_and_persists_repair_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = _manager(tmp, "run-repaired")
            manager.create(request())
            manager.transition("run-repaired", RunState.ACQUIRING_SOURCE, "source acquisition started")

            orchestrator = AgentOrchestrator(
                run_manager=manager,
                pipeline=lambda _run_id: OrchestrationResult(
                    state=RunState.READY,
                    exit_code=0,
                    message="manifests are ready after repair",
                    artifacts={"repair/14-repair-report.yaml": {"repaired": True}},
                ),
            )
            outcome = orchestrator.run("run-repaired")

            self.assertEqual(outcome.state, RunState.READY)
            self.assertEqual(outcome.exit_code, 0)
            self.assertTrue((Path(tmp) / "run-repaired" / "repair" / "14-repair-report.yaml").is_file())

    def test_validation_failure_result_uses_failed_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = _manager(tmp, "run-failed")
            manager.create(request())
            manager.transition("run-failed", RunState.ACQUIRING_SOURCE, "source acquisition started")

            orchestrator = AgentOrchestrator(
                run_manager=manager,
                pipeline=lambda _run_id: OrchestrationResult(
                    state=RunState.FAILED,
                    exit_code=5,
                    message="validation failed",
                ),
            )
            outcome = orchestrator.run("run-failed")

            self.assertEqual(outcome.state, RunState.FAILED)
            self.assertEqual(outcome.exit_code, 5)
            self.assertEqual(manager.store.load("run-failed").state, RunState.FAILED)

    def test_keyboard_interrupt_cancels_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = _manager(tmp, "run-cancelled")
            manager.create(request())
            manager.transition("run-cancelled", RunState.ACQUIRING_SOURCE, "source acquisition started")

            def interrupted(_run_id: str) -> OrchestrationResult:
                raise KeyboardInterrupt

            outcome = AgentOrchestrator(run_manager=manager, pipeline=interrupted).run("run-cancelled")

            self.assertEqual(outcome.state, RunState.CANCELLED)
            self.assertEqual(outcome.exit_code, 130)
            self.assertEqual(manager.store.load("run-cancelled").state, RunState.CANCELLED)
            self.assertIn("cancelled", (Path(tmp) / "run-cancelled" / "events.jsonl").read_text(encoding="utf-8"))

    def test_terminal_run_does_not_execute_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = _manager(tmp, "run-terminal")
            manager.create(request())
            manager.transition("run-terminal", RunState.ACQUIRING_SOURCE, "source acquisition started")
            manager.transition("run-terminal", RunState.ANALYZING, "agent orchestration started")
            manager.transition("run-terminal", RunState.READY, "ready")

            def fail_if_called(_run_id: str) -> OrchestrationResult:
                raise AssertionError("terminal run should not execute pipeline")

            outcome = AgentOrchestrator(run_manager=manager, pipeline=fail_if_called).run("run-terminal")

            self.assertEqual(outcome.state, RunState.READY)
            self.assertEqual(outcome.exit_code, 0)

    def test_agent_errors_transition_to_failed_with_agent_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = _manager(tmp, "run-agent-error")
            manager.create(request())
            manager.transition("run-agent-error", RunState.ACQUIRING_SOURCE, "source acquisition started")

            def raises_agent_error(_run_id: str) -> OrchestrationResult:
                raise AgentError(
                    code="TEST-101",
                    exit_code=5,
                    message="validation failed",
                    resolution="fix generated manifests",
                    context={},
                )

            outcome = AgentOrchestrator(run_manager=manager, pipeline=raises_agent_error).run("run-agent-error")

            self.assertEqual(outcome.state, RunState.FAILED)
            self.assertEqual(outcome.exit_code, 5)
            self.assertEqual(manager.store.load("run-agent-error").state, RunState.FAILED)


def _manager(tmp: str, run_id: str) -> RunManager:
    return RunManager(
        store=RunStore(Path(tmp)),
        clock=lambda: FIXED_TIME,
        run_id_factory=lambda: run_id,
    )


if __name__ == "__main__":
    unittest.main()
