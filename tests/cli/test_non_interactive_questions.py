from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from k8s_agent.questions.manager import QuestionManager
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
        question = QuestionManager.bootstrap_questions().questions[0]
        with tempfile.TemporaryDirectory() as tmp:
            answers = Path(tmp) / "answers.yaml"
            answers.write_text(f"answers:\n  {question.question_id}: acknowledge\n", encoding="utf-8")
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
