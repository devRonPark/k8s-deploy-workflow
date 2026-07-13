from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from tests.cli.test_prepare_arguments import run_agent


class PrepareBlackBoxTests(unittest.TestCase):
    def test_prepare_reports_waiting_state_and_writes_orchestration_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_agent(
                "prepare",
                "--local-path",
                "tests/fixtures/repos/node-express-like",
                "--target",
                "development",
                extra_env={"K8S_AGENT_HOME": tmp},
            )

            text = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, text)
            self.assertIn("state=WAITING_FOR_USER", text)
            run_id = text.split("run_id=", 1)[1].split()[0]
            run_root = Path(tmp) / "runs" / run_id

            self.assertTrue((run_root / "analysis" / "04-application-topology.yaml").is_file())
            self.assertTrue((run_root / "analysis" / "05-kubernetes-intent.yaml").is_file())
            self.assertTrue((run_root / "agent" / "plan.yaml").is_file())
            self.assertTrue((run_root / "agent" / "questions.yaml").is_file())

            run_record = yaml.safe_load((run_root / "run.yaml").read_text(encoding="utf-8"))
            self.assertEqual(run_record["state"], "WAITING_FOR_USER")

    def test_prepare_policy_blocked_exits_with_code_four(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_agent(
                "prepare",
                "--local-path",
                "tests/fixtures/repos/fastapi-fullstack-like",
                "--target",
                "development",
                extra_env={"K8S_AGENT_HOME": tmp},
            )

            text = result.stdout + result.stderr
            self.assertEqual(result.returncode, 4, text)
            self.assertIn("state=BLOCKED", text)


if __name__ == "__main__":
    unittest.main()
