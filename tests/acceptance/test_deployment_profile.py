from __future__ import annotations

import unittest

from k8s_agent.models.decision import Decision
from k8s_agent.models.intent import IntentCandidate, KubernetesIntent, PolicyDecision
from k8s_agent.profile.builder import DeploymentProfileBuilder, ProfileInputs


class DeploymentProfileAcceptanceTests(unittest.TestCase):
    def test_profile_merges_policy_and_user_decisions_with_stable_checksum(self):
        intent = KubernetesIntent(
            target="staging",
            candidates=[
                intent_candidate("replicas", "/components/api/replicas", 2, "auto_confirm", "target_replica_default"),
                intent_candidate("external_exposure", "/components/api/external_exposure", True, "requires_confirmation", "external_exposure_requires_confirmation"),
            ],
        )
        user = Decision(
            decision_id="D-user-exposure",
            question_id="Q-exposure",
            target_field="/components/api/external_exposure",
            value="private",
            raw_value="private",
            normalized_value="private",
            classification="user_answer",
            confidence="high",
            evidence_refs=["F200"],
            actor="user",
            alternatives=["private", "public"],
            approval="explicit",
            affected_resources=["Ingress", "Service"],
        )

        first = DeploymentProfileBuilder().build(ProfileInputs(intent=intent, decisions=[user]))
        second = DeploymentProfileBuilder().build(ProfileInputs(intent=intent, decisions=[user]))

        self.assertTrue(first.renderable)
        self.assertEqual(first.values["/components/api/replicas"].value, 2)
        self.assertEqual(first.values["/components/api/external_exposure"].actor, "user")
        self.assertEqual(first.checksum(), second.checksum())


def intent_candidate(kind: str, field: str, value, disposition: str, reason: str) -> IntentCandidate:
    return IntentCandidate(
        candidate_id=f"api/{kind}",
        component_id="api",
        kind=kind,
        field_path=field,
        value=value,
        source="test",
        confidence="high",
        classification="policy_default",
        evidence_refs=[],
        decision=PolicyDecision(disposition=disposition, reason_code=reason, policy_version="target-policy/v1"),
    )


if __name__ == "__main__":
    unittest.main()
