from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from k8s_agent.models.decision import Decision
from k8s_agent.models.intent import IntentCandidate, KubernetesIntent
from k8s_agent.models.profile import DeploymentProfile, ProfileConflict, ProfileHold, ProfileValue


class ProfileInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: KubernetesIntent | None = None
    decisions: list[Decision] = Field(default_factory=list)


class DeploymentProfileBuilder:
    def build(self, inputs: ProfileInputs, previous: DeploymentProfile | None = None) -> DeploymentProfile:
        decisions = [*self._intent_decisions(inputs.intent), *inputs.decisions]
        selected, conflicts = _merge_decisions(decisions)
        unresolved, blocked = _holds(inputs.intent, selected)
        revision = 1 if previous is None else previous.revision + 1
        return DeploymentProfile(
            revision=revision,
            values=selected,
            conflicts=conflicts,
            unresolved=unresolved,
            blocked=blocked,
            renderable=not unresolved and not blocked,
        )

    def _intent_decisions(self, intent: KubernetesIntent | None) -> list[Decision]:
        if intent is None:
            return []
        decisions: list[Decision] = []
        for candidate in intent.candidates:
            if candidate.decision is None or candidate.decision.disposition != "auto_confirm":
                continue
            decisions.append(_decision_from_candidate(candidate))
        return decisions


def _merge_decisions(decisions: list[Decision]) -> tuple[dict[str, ProfileValue], list[ProfileConflict]]:
    by_field: dict[str, list[Decision]] = {}
    for item in decisions:
        by_field.setdefault(item.target_field, []).append(item)

    selected: dict[str, ProfileValue] = {}
    conflicts: list[ProfileConflict] = []
    for field, items in sorted(by_field.items()):
        ordered = sorted(items, key=lambda item: (-_priority(item), item.decision_id))
        winner = ordered[0]
        selected[field] = ProfileValue(
            value=winner.value,
            decision_id=winner.decision_id,
            classification=winner.classification,
            confidence=winner.confidence,
            evidence_refs=sorted(winner.evidence_refs),
            actor=winner.actor,
            approval=winner.approval,
        )
        conflicting = [item for item in ordered[1:] if item.value != winner.value]
        if conflicting:
            refs = sorted({ref for item in [winner, *conflicting] for ref in item.evidence_refs})
            conflicts.append(
                ProfileConflict(
                    target_field=field,
                    selected_decision_id=winner.decision_id,
                    conflicting_decision_ids=[item.decision_id for item in conflicting],
                    evidence_refs=refs,
                )
            )
    return selected, conflicts


def _holds(intent: KubernetesIntent | None, selected: dict[str, ProfileValue]) -> tuple[list[ProfileHold], list[ProfileHold]]:
    if intent is None:
        return [], []
    unresolved: list[ProfileHold] = []
    blocked: list[ProfileHold] = []
    for candidate in sorted(intent.candidates, key=lambda item: (item.field_path, item.kind, item.candidate_id)):
        if candidate.decision is None:
            continue
        hold = ProfileHold(
            target_field=candidate.field_path,
            reason_code=candidate.decision.reason_code,
            evidence_refs=sorted(candidate.evidence_refs),
        )
        if candidate.decision.disposition == "requires_confirmation" and candidate.field_path not in selected:
            unresolved.append(hold)
        elif candidate.decision.disposition == "blocked":
            blocked.append(hold)
    return unresolved, blocked


def _decision_from_candidate(candidate: IntentCandidate) -> Decision:
    return Decision(
        decision_id=f"D-{candidate.candidate_id}",
        target_field=candidate.field_path,
        value=candidate.value,
        raw_value=candidate.value,
        normalized_value=candidate.value,
        classification=candidate.classification,
        confidence=candidate.confidence,
        evidence_refs=candidate.evidence_refs,
        actor="policy" if candidate.classification == "policy_default" else "agent",
        alternatives=[],
        approval="automatic",
        affected_resources=[],
    )


def _priority(decision: Decision) -> int:
    if decision.actor == "user" or decision.classification == "user_answer":
        return 100
    if decision.classification == "confirmed_fact":
        return 90
    if decision.classification == "llm_semantic_inference":
        return 70
    if decision.classification == "policy_default":
        return 60
    return 50
