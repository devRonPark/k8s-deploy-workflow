from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

import yaml

from k8s_agent.application import AgentApplication
from k8s_agent.cli import PrepareRequest
from k8s_agent.models.run import RunState


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"


@dataclass(frozen=True)
class FixtureExpectation:
    name: str
    expected_ready: bool
    reason: str


MVP_FIXTURES = [
    FixtureExpectation("node-express-like", True, "single node service"),
    FixtureExpectation("python-fastapi-like", True, "single python service"),
    FixtureExpectation("java-spring-like", True, "single java service"),
    FixtureExpectation("frontend-backend-monorepo", True, "frontend/backend monorepo"),
    FixtureExpectation("compose-multi-service", True, "docker compose multi-service"),
    FixtureExpectation("secret-candidate-node", True, "secret candidate with explicit existing Secret answer"),
    FixtureExpectation("no-dockerfile-node", True, "dockerfile missing but package command is known"),
    FixtureExpectation("corrupt-package-node", True, "corrupt package manifest falls back to Dockerfile evidence"),
    FixtureExpectation("fastapi-fullstack-like", False, "stateful dependency requires design review"),
    FixtureExpectation("port-conflict-node", False, "conflicting runtime commands require explicit resolution"),
]


class MvpFixtureMatrixTests(unittest.TestCase):
    def test_ten_fixture_matrix_reaches_eighty_percent_manifest_ready(self):
        results: dict[str, RunState] = {}
        for fixture in MVP_FIXTURES:
            with self.subTest(fixture=fixture.name):
                with tempfile.TemporaryDirectory() as tmp:
                    state_home = Path(tmp) / "state"
                    probe = _prepare(state_home, fixture.name, non_interactive=False)
                    if fixture.expected_ready:
                        answers = Path(tmp) / "answers.yaml"
                        _write_recommended_answers(probe.run_root, answers)
                        outcome = _prepare(state_home, fixture.name, non_interactive=True, answers_file=answers)
                        self.assertEqual(outcome.state, RunState.READY, fixture.reason)
                        self.assertTrue((outcome.run_root / "generated" / "manifest-bundle.yaml").is_file())
                        self.assertTrue((outcome.run_root / "validation" / "13-validation-report.yaml").is_file())
                    else:
                        outcome = probe
                        self.assertIn(outcome.state, {RunState.WAITING_FOR_USER, RunState.BLOCKED}, fixture.reason)
                        _assert_blocked_or_questioned(outcome.run_root)
                    results[fixture.name] = outcome.state

        ready = sum(1 for state in results.values() if state == RunState.READY)
        self.assertEqual(len(results), 10)
        self.assertGreaterEqual(ready, 8, results)


def _prepare(state_home: Path, fixture_name: str, *, non_interactive: bool, answers_file: Path | None = None):
    return AgentApplication(state_home=state_home).prepare(
        PrepareRequest(
            repo_url=None,
            local_path=FIXTURES / fixture_name,
            ref=None,
            target="development",
            non_interactive=non_interactive,
            answers_file=answers_file,
        )
    )


def _write_recommended_answers(run_root: Path, path: Path) -> None:
    question_set = yaml.safe_load((run_root / "agent" / "questions.yaml").read_text(encoding="utf-8"))
    answers = {}
    for question in question_set["question_set"]["questions"]:
        options = [option["value"] for option in question["options"]]
        recommended = question.get("recommended_option")
        if recommended in options:
            answers[question["question_id"]] = recommended
        elif "confirm" in options:
            answers[question["question_id"]] = "confirm"
        else:
            answers[question["question_id"]] = options[0]
    path.write_text(yaml.safe_dump({"answers": answers}, sort_keys=True), encoding="utf-8")


def _assert_blocked_or_questioned(run_root: Path) -> None:
    questions = run_root / "agent" / "questions.yaml"
    profile = run_root / "profile" / "deployment-profile.yaml"
    has_questions = questions.is_file() and "questions:" in questions.read_text(encoding="utf-8")
    profile_payload = yaml.safe_load(profile.read_text(encoding="utf-8")) if profile.is_file() else {}
    deployment_profile = profile_payload.get("deployment_profile", {})
    has_blocker = bool(deployment_profile.get("blocked") or deployment_profile.get("unresolved"))
    if not (has_questions or has_blocker):
        raise AssertionError(f"expected questions or blockers under {run_root}")


if __name__ == "__main__":
    unittest.main()
