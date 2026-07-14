from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from k8s_agent.errors import AgentError
from k8s_agent.questions.answers import AnswerLoader
from k8s_agent.questions.manager import QuestionManager


class AnswerLoaderTests(unittest.TestCase):
    def test_loads_valid_answers_without_auto_selecting_recommendations(self):
        questions = QuestionManager.bootstrap_questions()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "answers.yaml"
            path.write_text(f"answers:\n  {questions.questions[0].question_id}: acknowledge\n", encoding="utf-8")

            answers = AnswerLoader().load(path, questions)

        self.assertEqual(answers.answers[0].raw_value, "acknowledge")
        self.assertEqual(answers.answers[0].normalized_value, "acknowledge")

    def test_unknown_invalid_and_missing_required_answers_are_reported(self):
        questions = QuestionManager.bootstrap_questions()
        cases = [
            ("answers:\n  Q-UNKNOWN: acknowledge\n", "unknown_question"),
            (f"answers:\n  {questions.questions[0].question_id}: invalid\n", "invalid_option"),
            ("answers: {}\n", "missing_required_answer"),
        ]
        for content, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "answers.yaml"
                path.write_text(content, encoding="utf-8")

                with self.assertRaises(AgentError) as caught:
                    AnswerLoader().load(path, questions)

                self.assertEqual(caught.exception.exit_code, 3)
                self.assertIn(expected, caught.exception.context["reason"])


if __name__ == "__main__":
    unittest.main()
