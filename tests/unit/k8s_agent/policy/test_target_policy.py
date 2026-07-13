from __future__ import annotations

import unittest

from k8s_agent.models.intent import IntentCandidate
from k8s_agent.policy.engine import PolicyEngine
from k8s_agent.policy.target_policy import PolicyDisposition, Target


def candidate(kind: str, *, confidence: str = "high", evidence_refs: list[str] | None = None) -> IntentCandidate:
    return IntentCandidate(
        candidate_id=f"test/{kind}",
        component_id="api",
        kind=kind,
        field_path=f"/components/api/{kind}",
        value={"enabled": True},
        source="test",
        confidence=confidence,
        classification="rule_inference",
        evidence_refs=evidence_refs or ["F001"],
    )


class TargetPolicyTests(unittest.TestCase):
    def test_low_risk_high_confidence_candidate_auto_confirms(self):
        decision = PolicyEngine().evaluate(candidate("service"), Target.DEVELOPMENT)

        self.assertEqual(decision.disposition, PolicyDisposition.AUTO_CONFIRM)
        self.assertEqual(decision.policy_version, "target-policy/v1")
        self.assertEqual(decision.reason_code, "low_risk_high_confidence")

    def test_external_exposure_hostname_secret_and_pvc_are_not_auto_confirmed(self):
        engine = PolicyEngine()

        for kind in ["external_exposure", "hostname", "secret_ref", "pvc_size"]:
            with self.subTest(kind=kind):
                decision = engine.evaluate(candidate(kind), Target.STAGING)
                self.assertEqual(decision.disposition, PolicyDisposition.REQUIRES_CONFIRMATION)

    def test_stateful_requirement_is_blocked(self):
        decision = PolicyEngine().evaluate(candidate("stateful_workload"), Target.PRODUCTION)

        self.assertEqual(decision.disposition, PolicyDisposition.BLOCKED)
        self.assertEqual(decision.reason_code, "stateful_requires_design_review")

    def test_production_cluster_validation_is_blocked_by_policy(self):
        decision = PolicyEngine().evaluate(candidate("cluster_validation"), Target.PRODUCTION)

        self.assertEqual(decision.disposition, PolicyDisposition.BLOCKED)
        self.assertEqual(decision.reason_code, "production_cluster_validation_forbidden")

    def test_low_confidence_candidate_requires_confirmation(self):
        decision = PolicyEngine().evaluate(candidate("service", confidence="medium"), Target.DEVELOPMENT)

        self.assertEqual(decision.disposition, PolicyDisposition.REQUIRES_CONFIRMATION)
        self.assertEqual(decision.reason_code, "confidence_below_auto_threshold")

    def test_target_replica_defaults(self):
        engine = PolicyEngine()

        self.assertEqual(engine.replica_default(Target.DEVELOPMENT).value, 1)
        self.assertEqual(engine.replica_default(Target.STAGING).value, 2)
        production = engine.replica_default(Target.PRODUCTION)
        self.assertEqual(production.value, 3)
        self.assertEqual(production.decision.disposition, PolicyDisposition.REQUIRES_CONFIRMATION)


if __name__ == "__main__":
    unittest.main()
