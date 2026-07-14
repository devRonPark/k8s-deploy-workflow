from __future__ import annotations

import unittest

from k8s_agent.models.decision import Decision
from k8s_agent.models.intent import IntentCandidate, KubernetesIntent, PolicyDecision
from k8s_agent.profile.builder import DeploymentProfileBuilder, ProfileInputs


def decision(field: str, value, *, classification="rule_inference", actor="agent", confidence="medium", evidence_refs=None) -> Decision:
    return Decision(
        decision_id=f"D-{classification}-{actor}-{field}-{value}",
        target_field=field,
        value=value,
        raw_value=value,
        normalized_value=value,
        classification=classification,
        confidence=confidence,
        evidence_refs=evidence_refs or ["F001"],
        actor=actor,
        alternatives=[],
        approval="explicit" if actor == "user" else "automatic",
        affected_resources=["Deployment"],
    )


class DeploymentProfileBuilderTests(unittest.TestCase):
    def test_user_value_wins_over_inference_without_mutating_inputs(self):
        inferred = decision("/components/api/replicas", 1, classification="policy_default", actor="policy")
        user = decision("/components/api/replicas", 3, classification="user_answer", actor="user")
        inputs = ProfileInputs(decisions=[inferred, user])

        profile = DeploymentProfileBuilder().build(inputs)

        self.assertEqual(profile.values["/components/api/replicas"].value, 3)
        self.assertEqual(profile.values["/components/api/replicas"].actor, "user")
        self.assertEqual(inputs.decisions[0].value, 1)

    def test_confirmed_and_inference_conflict_is_recorded(self):
        confirmed = decision("/components/api/image", "repo/api:v1", classification="confirmed_fact", actor="source", confidence="high", evidence_refs=["F010"])
        inferred = decision("/components/api/image", "repo/api:latest", classification="rule_inference", actor="agent", confidence="high", evidence_refs=["F011"])

        profile = DeploymentProfileBuilder().build(ProfileInputs(decisions=[inferred, confirmed]))

        self.assertEqual(profile.values["/components/api/image"].value, "repo/api:v1")
        self.assertEqual(profile.conflicts[0].target_field, "/components/api/image")
        self.assertEqual(sorted(profile.conflicts[0].evidence_refs), ["F010", "F011"])

    def test_required_unanswered_and_blocked_intent_prevent_rendering(self):
        intent = KubernetesIntent(
            target="production",
            candidates=[
                candidate("external_exposure", "requires_confirmation"),
                candidate("stateful_workload", "blocked"),
            ],
        )

        profile = DeploymentProfileBuilder().build(ProfileInputs(intent=intent))

        self.assertFalse(profile.renderable)
        self.assertEqual([item.reason_code for item in profile.unresolved], ["external_exposure_requires_confirmation"])
        self.assertEqual([item.reason_code for item in profile.blocked], ["stateful_requires_design_review"])

    def test_revision_increments_without_mutating_previous_profile(self):
        builder = DeploymentProfileBuilder()
        first = builder.build(ProfileInputs(decisions=[decision("/namespace", "dev")]))
        second = builder.build(ProfileInputs(decisions=[decision("/namespace", "prod")]), previous=first)

        self.assertEqual(first.revision, 1)
        self.assertEqual(first.values["/namespace"].value, "dev")
        self.assertEqual(second.revision, 2)
        self.assertEqual(second.values["/namespace"].value, "prod")

    def test_same_inputs_produce_same_checksum(self):
        inputs = ProfileInputs(decisions=[decision("/namespace", "dev")])

        first = DeploymentProfileBuilder().build(inputs)
        second = DeploymentProfileBuilder().build(inputs)

        self.assertEqual(first.checksum(), second.checksum())


def candidate(kind: str, disposition: str) -> IntentCandidate:
    reason = f"{kind}_requires_confirmation" if disposition == "requires_confirmation" else "stateful_requires_design_review"
    return IntentCandidate(
        candidate_id=f"api/{kind}",
        component_id="api",
        kind=kind,
        field_path=f"/components/api/{kind}",
        value=True,
        source="test",
        confidence="high",
        classification="rule_inference",
        evidence_refs=["F100"],
        decision=PolicyDecision(disposition=disposition, reason_code=reason, policy_version="target-policy/v1"),
    )


if __name__ == "__main__":
    unittest.main()
