from __future__ import annotations

import unittest

from k8s_agent.agent.planner import AgentPlanner, PlanningContext
from k8s_agent.models.decision import Decision
from k8s_agent.models.intent import IntentCandidate, KubernetesIntent, PolicyDecision
from k8s_agent.models.topology import ApplicationComponent, ApplicationTopology, TopologyConflict
from k8s_agent.questions.answers import AnswerSet, UserAnswer
from k8s_agent.questions.manager import QuestionManager


class QuestionManagerTests(unittest.TestCase):
    def test_builds_required_questions_for_deployment_affecting_uncertainties(self):
        intent = KubernetesIntent(
            target="staging",
            candidates=[
                candidate("api", "external_exposure", "external_exposure_requires_confirmation", ["F001"]),
                candidate("api", "hostname", "hostname_requires_confirmation", ["F002"]),
                candidate("api", "secret_ref", "secret_ref_requires_confirmation", ["F003"]),
                candidate("db", "pvc_size", "pvc_size_requires_confirmation", ["F004"]),
                candidate("db", "stateful_workload", "stateful_requires_design_review", ["F005"], disposition="blocked"),
            ],
        )
        conflict = TopologyConflict(field_path="/components/api/runtime/command", reason="conflicting_runtime_commands", evidence_refs=["F006", "F007"])
        topology = ApplicationTopology(components=[ApplicationComponent(component_id="api", role="application")], conflicts=[conflict])
        plan = AgentPlanner().plan(PlanningContext(topology=topology, intent=intent))

        questions = QuestionManager().build(intent, plan)

        reasons = [question.reason_code for question in questions.questions]
        self.assertEqual(reasons, sorted(reasons))
        for expected in [
            "external_exposure_requires_confirmation",
            "hostname_requires_confirmation",
            "secret_ref_requires_confirmation",
            "pvc_size_requires_confirmation",
            "stateful_requires_design_review",
            "conflicting_runtime_commands",
        ]:
            self.assertIn(expected, reasons)
        first = questions.questions[0]
        self.assertTrue(first.question_id.startswith("Q-"))
        self.assertTrue(first.options)
        self.assertIsNotNone(first.recommended_option)
        self.assertTrue(first.impact)
        self.assertTrue(first.skip_impact)
        self.assertTrue(first.required)

    def test_to_decisions_preserves_raw_and_normalized_user_answers(self):
        question_set = QuestionManager.bootstrap_questions()
        question = question_set.questions[0]
        answers = AnswerSet(
            answers=[
                UserAnswer(
                    question_id=question.question_id,
                    raw_value="acknowledge",
                    normalized_value="acknowledge",
                    question=question,
                )
            ]
        )

        decisions = QuestionManager().to_decisions(answers)

        self.assertEqual(len(decisions), 1)
        self.assertIsInstance(decisions[0], Decision)
        self.assertEqual(decisions[0].actor, "user")
        self.assertEqual(decisions[0].raw_value, "acknowledge")
        self.assertEqual(decisions[0].value, "acknowledge")
        self.assertEqual(decisions[0].approval, "explicit")

    def test_question_ids_are_stable(self):
        first = QuestionManager.bootstrap_questions()
        second = QuestionManager.bootstrap_questions()

        self.assertEqual([q.question_id for q in first.questions], [q.question_id for q in second.questions])


def candidate(component_id: str, kind: str, reason: str, refs: list[str], *, disposition: str = "requires_confirmation") -> IntentCandidate:
    return IntentCandidate(
        candidate_id=f"{component_id}/{kind}",
        component_id=component_id,
        kind=kind,
        field_path=f"/components/{component_id}/{kind}",
        value={"kind": kind},
        source="test",
        confidence="high",
        classification="rule_inference",
        evidence_refs=refs,
        decision=PolicyDecision(disposition=disposition, reason_code=reason, policy_version="target-policy/v1"),
    )


if __name__ == "__main__":
    unittest.main()
