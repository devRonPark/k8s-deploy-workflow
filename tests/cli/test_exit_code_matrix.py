from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from k8s_agent.models.run import RunState
from k8s_agent.run.manager import RunManager
from k8s_agent.run.store import RunStore
from tests.acceptance.test_mvp_fixture_matrix import _prepare, _write_recommended_answers
from tests.cli.test_prepare_arguments import run_agent


class ExitCodeMatrixTests(unittest.TestCase):
    def test_prepare_success_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = _prepare(Path(tmp) / "state", "node-express-like", non_interactive=False)
            answers = Path(tmp) / "answers.yaml"
            _write_recommended_answers(probe.run_root, answers)
            result = run_agent(
                "prepare",
                "--local-path",
                "tests/fixtures/repos/node-express-like",
                "--target",
                "development",
                "--non-interactive",
                "--answers-file",
                str(answers),
                extra_env={"K8S_AGENT_HOME": str(Path(tmp) / "cli-state")},
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("state=READY", result.stdout)

    def test_usage_error_returns_two(self):
        result = run_agent("prepare", "--target", "development")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("CLI-101", result.stdout + result.stderr)

    def test_missing_required_answers_returns_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            answers = Path(tmp) / "answers.yaml"
            answers.write_text("answers: {}\n", encoding="utf-8")
            result = run_agent(
                "prepare",
                "--local-path",
                "tests/fixtures/repos/node-express-like",
                "--target",
                "development",
                "--non-interactive",
                "--answers-file",
                str(answers),
                extra_env={"K8S_AGENT_HOME": tmp},
            )

        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("QST-201", result.stdout + result.stderr)

    def test_policy_block_returns_four(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_agent(
                "prepare",
                "--local-path",
                "tests/fixtures/repos/fastapi-fullstack-like",
                "--target",
                "development",
                extra_env={"K8S_AGENT_HOME": tmp},
            )

        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertIn("state=BLOCKED", result.stdout)

    def test_terminal_failed_resume_returns_eight(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(Path(tmp) / "runs")
            manager = RunManager(store, run_id_factory=lambda: "run-failed")
            record = manager.create(
                _request("tests/fixtures/repos/node-express-like")
            )
            manager.transition(record.run_id, RunState.ACQUIRING_SOURCE, "source acquisition started")
            manager.transition(record.run_id, RunState.FAILED, "source acquisition failed")

            result = run_agent("resume", "run-failed", extra_env={"K8S_AGENT_HOME": tmp})

        self.assertEqual(result.returncode, 8, result.stdout + result.stderr)
        self.assertIn("not resumable", result.stdout)


def _request(path: str):
    from k8s_agent.cli import PrepareRequest

    return PrepareRequest(
        repo_url=None,
        local_path=Path(path),
        ref=None,
        target="development",
        non_interactive=False,
        answers_file=None,
    )


if __name__ == "__main__":
    unittest.main()
