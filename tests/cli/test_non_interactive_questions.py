from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from tests.cli.test_prepare_arguments import run_agent


class NonInteractiveQuestionTests(unittest.TestCase):
    def test_non_interactive_prepare_blocks_when_required_answer_is_missing(self):
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

        text = result.stdout + result.stderr
        self.assertEqual(result.returncode, 3, text)
        self.assertIn("QST-201", text)
        self.assertIn("BLOCKED", text)

    def test_non_interactive_prepare_accepts_explicit_required_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = run_agent(
                "prepare",
                "--local-path",
                "tests/fixtures/repos/node-express-like",
                "--target",
                "development",
                extra_env={"K8S_AGENT_HOME": tmp},
            )
            self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
            run_id = probe.stdout.split("run_id=", 1)[1].split()[0]
            questions_path = Path(tmp) / "runs" / run_id / "agent" / "questions.yaml"
            question_set = yaml.safe_load(questions_path.read_text(encoding="utf-8"))
            answers_payload = {
                question["question_id"]: question.get("recommended_option") or "confirm"
                for question in question_set["question_set"]["questions"]
            }
            answers = Path(tmp) / "answers.yaml"
            answers.write_text(yaml.safe_dump({"answers": answers_payload}, sort_keys=True), encoding="utf-8")
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

        text = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, text)
        self.assertIn("prepare created", text)


if __name__ == "__main__":
    unittest.main()
