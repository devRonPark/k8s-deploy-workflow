from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from k8s_agent.application import AgentApplication
from k8s_agent.cli import PrepareRequest
from k8s_agent.errors import AgentError
from k8s_agent.models.profile import DeploymentProfile, ProfileValue
from k8s_agent.models.run import RunState


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "repos"
FIXED_TIME = datetime(2026, 7, 14, 4, 5, 6, tzinfo=timezone.utc)


class StageCommandTests(unittest.TestCase):
    def test_plan_before_analysis_is_precondition_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentApplication(state_home=Path(tmp), clock=lambda: FIXED_TIME)
            run = app.run_manager.create(_request(FIXTURES / "node-express-like"))

            with self.assertRaisesRegex(AgentError, "STAGE-101"):
                app.plan(run.run_id)

    def test_analyze_writes_phase1_and_topology_without_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentApplication(state_home=Path(tmp), clock=lambda: FIXED_TIME)

            outcome = app.analyze(_request(FIXTURES / "node-express-like"))

            self.assertEqual(outcome.state, RunState.WAITING_FOR_USER)
            self.assertEqual(outcome.exit_code, 0)
            self.assertTrue((outcome.run_root / "analysis" / "00-repository-snapshot.yaml").is_file())
            self.assertTrue((outcome.run_root / "analysis" / "04-application-topology.yaml").is_file())
            self.assertFalse((outcome.run_root / "analysis" / "05-kubernetes-intent.yaml").exists())

    def test_plan_after_analyze_writes_intent_questions_profile_and_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentApplication(state_home=Path(tmp), clock=lambda: FIXED_TIME)
            outcome = app.analyze(_request(FIXTURES / "node-express-like"))

            plan = app.plan(outcome.run_id)

            self.assertGreater(len(plan.tasks), 0)
            self.assertTrue((outcome.run_root / "analysis" / "05-kubernetes-intent.yaml").is_file())
            self.assertTrue((outcome.run_root / "agent" / "plan.yaml").is_file())
            self.assertTrue((outcome.run_root / "agent" / "questions.yaml").is_file())
            self.assertTrue((outcome.run_root / "profile" / "deployment-profile.yaml").is_file())
            self.assertIn("stage_plan_completed", (outcome.run_root / "events.jsonl").read_text(encoding="utf-8"))

    def test_generate_requires_renderable_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentApplication(state_home=Path(tmp), clock=lambda: FIXED_TIME)
            outcome = app.analyze(_request(FIXTURES / "node-express-like"))

            with self.assertRaisesRegex(AgentError, "STAGE-201"):
                app.generate(outcome.run_id)

    def test_generate_and_validate_use_existing_profile_and_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentApplication(state_home=Path(tmp), clock=lambda: FIXED_TIME)
            outcome = app.analyze(_request(FIXTURES / "node-express-like"))
            app.store.save_yaml(
                outcome.run_id,
                "profile/deployment-profile.yaml",
                {"deployment_profile": _renderable_profile().model_dump(mode="json")},
            )

            bundle = app.generate(outcome.run_id)
            report = app.validate(outcome.run_id)

            self.assertGreater(len(bundle.files), 0)
            self.assertTrue(report.manifest_ready)
            self.assertTrue((outcome.run_root / "generated" / "manifest-bundle.yaml").is_file())
            self.assertTrue((outcome.run_root / "validation" / "13-validation-report.yaml").is_file())

    def test_validate_requires_existing_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentApplication(state_home=Path(tmp), clock=lambda: FIXED_TIME)
            outcome = app.analyze(_request(FIXTURES / "node-express-like"))

            with self.assertRaisesRegex(AgentError, "STAGE-301"):
                app.validate(outcome.run_id)


def _request(path: Path) -> PrepareRequest:
    return PrepareRequest(
        repo_url=None,
        local_path=path,
        ref=None,
        target="development",
        non_interactive=False,
        answers_file=None,
    )


def _renderable_profile() -> DeploymentProfile:
    return DeploymentProfile(
        revision=1,
        values={
            "/components/api/image": _value("api:latest"),
            "/components/api/replicas": _value(1),
            "/components/api/service": _value({"port": 8000}),
            "/components/api/runtime_command": _value("node server.js"),
            "/components/api/external_exposure": _value("private"),
        },
    )


def _value(value) -> ProfileValue:
    return ProfileValue(
        value=value,
        decision_id=f"D-{value}",
        classification="policy_default",
        confidence="high",
        evidence_refs=[],
        actor="policy",
        approval="automatic",
    )


if __name__ == "__main__":
    unittest.main()
