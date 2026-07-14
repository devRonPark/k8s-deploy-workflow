from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from k8s_agent.application import AgentApplication
from k8s_agent.cli import PrepareRequest
from k8s_agent.models.run import RunState


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"


class PrepareEndToEndTests(unittest.TestCase):
    def test_prepare_connects_source_analysis_topology_intent_plan_and_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            outcome = AgentApplication(state_home=Path(tmp)).prepare(
                PrepareRequest(
                    repo_url=None,
                    local_path=FIXTURES / "node-express-like",
                    ref=None,
                    target="development",
                    non_interactive=False,
                    answers_file=None,
                )
            )

            self.assertEqual(outcome.state, RunState.WAITING_FOR_USER)
            self.assertEqual(outcome.exit_code, 0)
            run_root = outcome.run_root
            artifacts = [
                "source.yaml",
                "analysis/00-repository-snapshot.yaml",
                "analysis/01-artifact-inventory.yaml",
                "analysis/02-evidence-model.yaml",
                "analysis/03-rule-inference.yaml",
                "analysis/04-application-topology.yaml",
                "analysis/05-kubernetes-intent.yaml",
                "agent/plan.yaml",
                "agent/questions.yaml",
                "profile/deployment-profile.yaml",
            ]
            for artifact in artifacts:
                self.assertTrue((run_root / artifact).is_file(), artifact)

            questions = yaml.safe_load((run_root / "agent" / "questions.yaml").read_text(encoding="utf-8"))
            self.assertGreater(len(questions["question_set"]["questions"]), 0)
            self.assertEqual(yaml.safe_load((run_root / "run.yaml").read_text(encoding="utf-8"))["state"], "WAITING_FOR_USER")

    def test_prepare_blocks_stateful_dependency_before_rendering(self):
        with tempfile.TemporaryDirectory() as tmp:
            outcome = AgentApplication(state_home=Path(tmp)).prepare(
                PrepareRequest(
                    repo_url=None,
                    local_path=FIXTURES / "fastapi-fullstack-like",
                    ref=None,
                    target="development",
                    non_interactive=False,
                    answers_file=None,
                )
            )

            self.assertEqual(outcome.state, RunState.BLOCKED)
            self.assertEqual(outcome.exit_code, 4)
            self.assertFalse((outcome.run_root / "generated").exists())


if __name__ == "__main__":
    unittest.main()
