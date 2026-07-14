from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from k8s_agent.application import AgentApplication, DriftPolicy
from k8s_agent.cli import PrepareRequest
from k8s_agent.models.run import RunState
from k8s_agent.models.source import GitMetadata, RepositorySource, SourceFingerprint
from k8s_agent.run.manager import RunManager
from k8s_agent.run.store import RunStore


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "repos"
FIXED_TIME = datetime(2026, 7, 14, 1, 2, 3, tzinfo=timezone.utc)


class ResumeTests(unittest.TestCase):
    def test_resume_waiting_run_reuses_existing_phase1_when_source_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentApplication(state_home=Path(tmp), clock=lambda: FIXED_TIME)
            prepared = app.prepare(_local_request(FIXTURES / "node-express-like"))
            snapshot = prepared.run_root / "analysis" / "00-repository-snapshot.yaml"
            os.utime(snapshot, (1, 1))

            resumed = app.resume(prepared.run_id)

            self.assertEqual(resumed.state, RunState.WAITING_FOR_USER)
            self.assertEqual(resumed.exit_code, 0)
            self.assertEqual(snapshot.stat().st_mtime, 1)
            events = (prepared.run_root / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn("resume source unchanged", events)

    def test_resume_changed_local_source_requires_drift_choice_before_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            shutil.copytree(FIXTURES / "node-express-like", repo)
            app = AgentApplication(state_home=Path(tmp) / "state", clock=lambda: FIXED_TIME)
            prepared = app.prepare(_local_request(repo))
            snapshot = prepared.run_root / "analysis" / "00-repository-snapshot.yaml"
            os.utime(snapshot, (1, 1))
            (repo / "README.md").write_text("changed source\n", encoding="utf-8")

            resumed = app.resume(prepared.run_id)

            self.assertEqual(resumed.state, RunState.WAITING_FOR_USER)
            self.assertEqual(resumed.exit_code, 3)
            self.assertIn("source drift", resumed.message)
            self.assertEqual(snapshot.stat().st_mtime, 1)
            self.assertTrue((prepared.run_root / "resume" / "source-drift.yaml").is_file())

    def test_resume_changed_local_source_with_replan_updates_source_and_reruns_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            shutil.copytree(FIXTURES / "node-express-like", repo)
            app = AgentApplication(state_home=Path(tmp) / "state", clock=lambda: FIXED_TIME)
            prepared = app.prepare(_local_request(repo))
            original = yaml.safe_load((prepared.run_root / "source.yaml").read_text(encoding="utf-8"))
            snapshot = prepared.run_root / "analysis" / "00-repository-snapshot.yaml"
            os.utime(snapshot, (1, 1))
            (repo / "README.md").write_text("changed source\n", encoding="utf-8")

            resumed = app.resume(prepared.run_id, DriftPolicy.REPLAN)

            self.assertEqual(resumed.run_id, prepared.run_id)
            self.assertEqual(resumed.state, RunState.WAITING_FOR_USER)
            self.assertEqual(resumed.exit_code, 0)
            self.assertGreater(snapshot.stat().st_mtime, 1)
            updated = yaml.safe_load((prepared.run_root / "source.yaml").read_text(encoding="utf-8"))
            self.assertNotEqual(updated["fingerprint"]["value"], original["fingerprint"]["value"])

    def test_resume_changed_local_source_with_new_run_starts_from_current_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            shutil.copytree(FIXTURES / "node-express-like", repo)
            app = AgentApplication(state_home=Path(tmp) / "state", clock=lambda: FIXED_TIME)
            prepared = app.prepare(_local_request(repo))
            (repo / "README.md").write_text("changed source\n", encoding="utf-8")

            resumed = app.resume(prepared.run_id, DriftPolicy.NEW_RUN)

            self.assertNotEqual(resumed.run_id, prepared.run_id)
            self.assertEqual(resumed.state, RunState.WAITING_FOR_USER)
            updated = yaml.safe_load((resumed.run_root / "source.yaml").read_text(encoding="utf-8"))
            original = yaml.safe_load((prepared.run_root / "source.yaml").read_text(encoding="utf-8"))
            self.assertNotEqual(updated["fingerprint"]["value"], original["fingerprint"]["value"])

    def test_resume_github_source_uses_pinned_workspace_without_network_refetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunManager(
                RunStore(Path(tmp) / "runs"),
                clock=lambda: FIXED_TIME,
                run_id_factory=lambda: "run-github",
            )
            manager.create(
                PrepareRequest(
                    repo_url="https://github.com/example/app.git",
                    local_path=None,
                    ref="main",
                    target="development",
                    non_interactive=False,
                    answers_file=None,
                )
            )
            manager.transition("run-github", RunState.ACQUIRING_SOURCE, "source acquisition started")
            manager.store.save_yaml("run-github", "source.yaml", _github_source(FIXTURES / "node-express-like"))
            manager.transition("run-github", RunState.ANALYZING, "agent orchestration started")
            manager.transition("run-github", RunState.WAITING_FOR_USER, "waiting")

            resumed = AgentApplication(state_home=Path(tmp), run_manager=manager, clock=lambda: FIXED_TIME).resume("run-github")

            self.assertEqual(resumed.state, RunState.WAITING_FOR_USER)
            self.assertEqual(resumed.exit_code, 0)

    def test_resume_stale_tool_metadata_invalidates_completed_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentApplication(state_home=Path(tmp), clock=lambda: FIXED_TIME)
            prepared = app.prepare(_local_request(FIXTURES / "node-express-like"))
            snapshot = prepared.run_root / "analysis" / "00-repository-snapshot.yaml"
            os.utime(snapshot, (1, 1))
            app.store.save_yaml(prepared.run_id, "agent/runtime-metadata.yaml", {"tool_versions": {"phase1": "old"}})

            resumed = app.resume(prepared.run_id)

            self.assertEqual(resumed.state, RunState.WAITING_FOR_USER)
            self.assertEqual(resumed.exit_code, 0)
            self.assertGreater(snapshot.stat().st_mtime, 1)
            metadata = yaml.safe_load((prepared.run_root / "agent" / "runtime-metadata.yaml").read_text(encoding="utf-8"))
            self.assertNotEqual(metadata["tool_versions"]["phase1"], "old")

    def test_resume_terminal_failed_run_reports_non_resumable_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunManager(
                RunStore(Path(tmp) / "runs"),
                clock=lambda: FIXED_TIME,
                run_id_factory=lambda: "run-failed",
            )
            manager.create(_local_request(FIXTURES / "node-express-like"))
            manager.transition("run-failed", RunState.ACQUIRING_SOURCE, "source acquisition started")
            manager.transition("run-failed", RunState.ANALYZING, "agent orchestration started")
            manager.transition("run-failed", RunState.FAILED, "validation failed")

            resumed = AgentApplication(state_home=Path(tmp), run_manager=manager, clock=lambda: FIXED_TIME).resume("run-failed")

            self.assertEqual(resumed.state, RunState.FAILED)
            self.assertEqual(resumed.exit_code, 8)
            self.assertIn("not resumable", resumed.message)


def _local_request(path: Path) -> PrepareRequest:
    return PrepareRequest(
        repo_url=None,
        local_path=path,
        ref=None,
        target="development",
        non_interactive=False,
        answers_file=None,
    )


def _github_source(path: Path) -> dict:
    return RepositorySource(
        kind="github",
        path=path,
        acquired_at=FIXED_TIME,
        git=GitMetadata(is_repository=True, head="abcdef1234567890"),
        fingerprint=SourceFingerprint(value="sha256:pinned", file_count=1),
    ).model_dump(mode="json")


if __name__ == "__main__":
    unittest.main()
