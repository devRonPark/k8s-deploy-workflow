from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from k8s_agent.cli import PrepareRequest
from k8s_agent.errors import AgentError
from k8s_agent.models.run import RunState
from k8s_agent.run.manager import RunManager
from k8s_agent.run.store import RunStore


class RunManagerTests(unittest.TestCase):
    def test_create_persists_run_and_initial_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunManager(
                store=RunStore(Path(tmp)),
                clock=lambda: datetime(2026, 7, 13, 1, 2, 3, tzinfo=timezone.utc),
                run_id_factory=lambda: "run-001",
            )

            record = manager.create(
                PrepareRequest(
                    repo_url=None,
                    local_path=Path("/repo/app"),
                    ref=None,
                    target="development",
                    non_interactive=False,
                    answers_file=None,
                )
            )

            self.assertEqual(record.run_id, "run-001")
            self.assertEqual(record.state, RunState.CREATED)
            self.assertEqual(record.last_successful_state, RunState.CREATED)
            self.assertTrue((Path(tmp) / "run-001" / "run.yaml").is_file())
            self.assertTrue((Path(tmp) / "run-001" / "events.jsonl").is_file())
            self.assertIn("run_created", (Path(tmp) / "run-001" / "events.jsonl").read_text())

    def test_transition_allows_only_declared_edges_and_updates_last_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunManager(
                store=RunStore(Path(tmp)),
                clock=lambda: datetime(2026, 7, 13, 1, 2, 3, tzinfo=timezone.utc),
                run_id_factory=lambda: "run-002",
            )
            manager.create(
                PrepareRequest(
                    repo_url="https://github.com/example/app.git",
                    local_path=None,
                    ref="main",
                    target="staging",
                    non_interactive=True,
                    answers_file=Path("answers.yaml"),
                )
            )

            acquiring = manager.transition("run-002", RunState.ACQUIRING_SOURCE, "source acquisition started")

            self.assertEqual(acquiring.state, RunState.ACQUIRING_SOURCE)
            self.assertEqual(acquiring.last_successful_state, RunState.ACQUIRING_SOURCE)
            loaded = manager.store.load("run-002")
            self.assertEqual(loaded.state, RunState.ACQUIRING_SOURCE)

            with self.assertRaisesRegex(AgentError, "RUN-201"):
                manager.transition("run-002", RunState.READY, "skip required states")

    def test_terminal_state_rejects_further_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunManager(
                store=RunStore(Path(tmp)),
                clock=lambda: datetime(2026, 7, 13, 1, 2, 3, tzinfo=timezone.utc),
                run_id_factory=lambda: "run-003",
            )
            manager.create(
                PrepareRequest(
                    repo_url=None,
                    local_path=Path("/repo/app"),
                    ref=None,
                    target="production",
                    non_interactive=False,
                    answers_file=None,
                )
            )
            manager.transition("run-003", RunState.FAILED, "failed for test")

            with self.assertRaisesRegex(AgentError, "RUN-201"):
                manager.transition("run-003", RunState.ACQUIRING_SOURCE, "retry from terminal")


if __name__ == "__main__":
    unittest.main()
