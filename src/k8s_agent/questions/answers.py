from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from k8s_agent.errors import AgentError
from k8s_agent.questions.manager import Question, QuestionSet


class UserAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    question_id: str
    raw_value: Any
    normalized_value: Any
    question: Question


class AnswerSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[UserAnswer] = Field(default_factory=list)


class AnswerLoader:
    def load(self, path: Path, questions: QuestionSet) -> AnswerSet:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw_answers = payload.get("answers")
        if not isinstance(raw_answers, dict):
            raise _answer_error("invalid_answers_file", "answers file must contain a mapping at 'answers'.")
        question_by_id = {question.question_id: question for question in questions.questions}
        unknown = sorted(set(raw_answers) - set(question_by_id))
        if unknown:
            raise _answer_error("unknown_question", f"answers file contains unknown question IDs: {', '.join(unknown)}")
        missing = sorted(question.question_id for question in questions.questions if question.required and question.question_id not in raw_answers)
        if missing:
            raise _answer_error("missing_required_answer", f"required answers are missing: {', '.join(missing)}")

        answers: list[UserAnswer] = []
        for question_id, raw_value in sorted(raw_answers.items()):
            question = question_by_id[question_id]
            normalized = _normalize(raw_value)
            allowed = {option.value for option in question.options}
            if normalized not in allowed:
                raise _answer_error("invalid_option", f"answer for {question_id} must be one of: {', '.join(sorted(allowed))}")
            answers.append(UserAnswer(question_id=question_id, raw_value=raw_value, normalized_value=normalized, question=question))
        return AnswerSet(answers=answers)


def _normalize(value: Any) -> str:
    return str(value).strip()


def _answer_error(reason: str, message: str) -> AgentError:
    return AgentError(
        code="QST-201",
        exit_code=3,
        message=f"BLOCKED: {message}",
        resolution="Provide explicit answers for all required questions and retry.",
        context={"reason": reason},
    )
