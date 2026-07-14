from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tests.cli.test_prepare_arguments import run_agent


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"


class ResumeBlackBoxTests(unittest.TestCase):
    def test_resume_waiting_prepare_reports_state_and_run_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared = run_agent(
                "prepare",
                "--local-path",
                "tests/fixtures/repos/node-express-like",
                "--target",
                "development",
                extra_env={"K8S_AGENT_HOME": tmp},
            )
            run_id = prepared.stdout.split("run_id=", 1)[1].split()[0]

            resumed = run_agent("resume", run_id, extra_env={"K8S_AGENT_HOME": tmp})

            text = resumed.stdout + resumed.stderr
            self.assertEqual(resumed.returncode, 0, text)
            self.assertIn(f"resume run_id={run_id}", text)
            self.assertIn("state=WAITING_FOR_USER", text)
            self.assertIn("run_root=", text)

    def test_resume_local_source_drift_exits_with_question_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            shutil.copytree(FIXTURES / "node-express-like", repo)
            state_home = Path(tmp) / "state"
            prepared = run_agent(
                "prepare",
                "--local-path",
                str(repo),
                "--target",
                "development",
                extra_env={"K8S_AGENT_HOME": str(state_home)},
            )
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            run_id = prepared.stdout.split("run_id=", 1)[1].split()[0]
            (repo / "README.md").write_text("drift\n", encoding="utf-8")

            resumed = run_agent("resume", run_id, extra_env={"K8S_AGENT_HOME": str(state_home)})

            text = resumed.stdout + resumed.stderr
            self.assertEqual(resumed.returncode, 3, text)
            self.assertIn("source drift", text)
            self.assertIn("state=WAITING_FOR_USER", text)

    def test_resume_local_source_drift_can_replan_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            shutil.copytree(FIXTURES / "node-express-like", repo)
            state_home = Path(tmp) / "state"
            prepared = run_agent(
                "prepare",
                "--local-path",
                str(repo),
                "--target",
                "development",
                extra_env={"K8S_AGENT_HOME": str(state_home)},
            )
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            run_id = prepared.stdout.split("run_id=", 1)[1].split()[0]
            (repo / "README.md").write_text("drift\n", encoding="utf-8")

            resumed = run_agent(
                "resume",
                run_id,
                "--drift-policy",
                "replan",
                extra_env={"K8S_AGENT_HOME": str(state_home)},
            )

            text = resumed.stdout + resumed.stderr
            self.assertEqual(resumed.returncode, 0, text)
            self.assertIn(f"resume run_id={run_id}", text)
            self.assertIn("state=WAITING_FOR_USER", text)


if __name__ == "__main__":
    unittest.main()
