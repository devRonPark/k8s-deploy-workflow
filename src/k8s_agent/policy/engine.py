from __future__ import annotations

from k8s_agent.models.intent import IntentCandidate, PolicyDecision
from k8s_agent.policy.target_policy import POLICY_VERSION, PolicyDisposition, Target


_CONFIRMATION_KINDS = {
    "external_exposure",
    "hostname",
    "secret_ref",
    "pvc_size",
    "resource_requests",
    "readiness_probe",
    "liveness_probe",
    "runtime_command",
}
_BLOCKED_KINDS = {"stateful_workload"}


class PolicyEngine:
    def evaluate(self, candidate: IntentCandidate, target: Target | str) -> PolicyDecision:
        resolved_target = Target(target)
        if candidate.kind == "cluster_validation" and resolved_target == Target.PRODUCTION:
            return _decision(PolicyDisposition.BLOCKED, "production_cluster_validation_forbidden")
        if candidate.kind in _BLOCKED_KINDS:
            return _decision(PolicyDisposition.BLOCKED, "stateful_requires_design_review")
        if candidate.kind in _CONFIRMATION_KINDS:
            return _decision(PolicyDisposition.REQUIRES_CONFIRMATION, f"{candidate.kind}_requires_confirmation")
        if candidate.confidence != "high":
            return _decision(PolicyDisposition.REQUIRES_CONFIRMATION, "confidence_below_auto_threshold")
        return _decision(PolicyDisposition.AUTO_CONFIRM, "low_risk_high_confidence")

    def replica_default(self, target: Target | str) -> IntentCandidate:
        resolved_target = Target(target)
        values = {
            Target.DEVELOPMENT: 1,
            Target.STAGING: 2,
            Target.PRODUCTION: 3,
        }
        candidate = IntentCandidate(
            candidate_id=f"policy/replicas/{resolved_target.value}",
            component_id="__target__",
            kind="replicas",
            field_path="/replicas",
            value=values[resolved_target],
            source="target_policy",
            confidence="high",
            classification="policy_default",
            evidence_refs=[],
            policy_version=POLICY_VERSION,
        )
        reason = "target_replica_default"
        disposition = PolicyDisposition.AUTO_CONFIRM
        if resolved_target == Target.PRODUCTION:
            reason = "production_replicas_require_confirmation"
            disposition = PolicyDisposition.REQUIRES_CONFIRMATION
        return candidate.model_copy(update={"decision": _decision(disposition, reason)})


def _decision(disposition: PolicyDisposition, reason_code: str) -> PolicyDecision:
    return PolicyDecision(disposition=disposition, reason_code=reason_code, policy_version=POLICY_VERSION)
