from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from k8s_agent.agent.planner import AgentPlan
from k8s_agent.models.decision import Decision
from k8s_agent.models.intent import IntentCandidate, KubernetesIntent


class QuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    label: str
    description: str


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    reason_code: str
    prompt: str
    target_field: str
    component_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    options: list[QuestionOption] = Field(default_factory=list)
    recommended_option: str | None = None
    impact: str
    skip_impact: str
    required: bool = True
    affected_resources: list[str] = Field(default_factory=list)


class QuestionSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[Question] = Field(default_factory=list)


class QuestionManager:
    def build(self, intent: KubernetesIntent, plan: AgentPlan) -> QuestionSet:
        questions: list[Question] = []
        for candidate in intent.candidates:
            if candidate.decision is None:
                continue
            if candidate.decision.disposition not in {"requires_confirmation", "blocked"}:
                continue
            questions.append(_question_from_candidate(candidate))
        for task in plan.tasks:
            if task.action == "semantic_action" and task.reason_code == "conflicting_runtime_commands":
                questions.append(
                    _question(
                        reason_code="conflicting_runtime_commands",
                        target_field=f"/components/{task.component_id}/runtime/command",
                        component_id=task.component_id,
                        evidence_refs=task.evidence_refs,
                        options=[
                            ("use_first", "Use first candidate", "Use the first grounded command candidate."),
                            ("use_second", "Use second candidate", "Use the second grounded command candidate."),
                            ("defer", "Defer", "Leave runtime command unresolved for now."),
                        ],
                        recommended_option="defer",
                        prompt="Select the runtime command to use.",
                        impact="Controls the container command in generated manifests.",
                        skip_impact="Manifest generation remains blocked for this component.",
                        affected_resources=["Deployment"],
                    )
                )
        return QuestionSet(questions=_dedupe_sorted(questions))

    @staticmethod
    def bootstrap_questions() -> QuestionSet:
        return QuestionSet(
            questions=[
                _question(
                    reason_code="non_interactive_acknowledgement",
                    target_field="/run/non_interactive_acknowledgement",
                    component_id=None,
                    evidence_refs=[],
                    options=[("acknowledge", "Acknowledge", "Proceed with explicit non-interactive answers.")],
                    recommended_option=None,
                    prompt="Acknowledge non-interactive deployment decisions.",
                    impact="Allows the run to proceed without interactive prompts.",
                    skip_impact="The run is BLOCKED until required answers are supplied.",
                    affected_resources=[],
                )
            ]
        )

    def to_decisions(self, answers) -> list[Decision]:
        decisions: list[Decision] = []
        for answer in answers.answers:
            question = answer.question
            decisions.append(
                Decision(
                    decision_id=_stable_id("D", {"question_id": question.question_id, "value": answer.normalized_value}),
                    question_id=question.question_id,
                    target_field=question.target_field,
                    value=answer.normalized_value,
                    raw_value=answer.raw_value,
                    normalized_value=answer.normalized_value,
                    classification="user_answer",
                    confidence="high",
                    evidence_refs=question.evidence_refs,
                    actor="user",
                    alternatives=[option.value for option in question.options],
                    approval="explicit",
                    affected_resources=question.affected_resources,
                )
            )
        return decisions


def _question_from_candidate(candidate: IntentCandidate) -> Question:
    reason = candidate.decision.reason_code if candidate.decision is not None else candidate.kind
    options = _options_for(candidate.kind, reason)
    return _question(
        reason_code=reason,
        target_field=candidate.field_path,
        component_id=None if candidate.component_id == "__run__" else candidate.component_id,
        evidence_refs=candidate.evidence_refs,
        options=options,
        recommended_option=_recommended_for(candidate.kind),
        prompt=_prompt_for(candidate.kind, reason),
        impact=_impact_for(candidate.kind),
        skip_impact=_skip_impact_for(candidate.kind),
        affected_resources=_resources_for(candidate.kind),
    )


def _question(
    *,
    reason_code: str,
    target_field: str,
    component_id: str | None,
    evidence_refs: list[str],
    options: list[tuple[str, str, str]],
    recommended_option: str | None,
    prompt: str,
    impact: str,
    skip_impact: str,
    affected_resources: list[str],
) -> Question:
    option_models = [QuestionOption(value=value, label=label, description=description) for value, label, description in options]
    payload = {
        "reason_code": reason_code,
        "target_field": target_field,
        "component_id": component_id,
        "evidence_refs": sorted(evidence_refs),
        "options": [option.value for option in option_models],
    }
    return Question(
        question_id=_stable_id("Q", payload),
        reason_code=reason_code,
        prompt=prompt,
        target_field=target_field,
        component_id=component_id,
        evidence_refs=sorted(evidence_refs),
        options=option_models,
        recommended_option=recommended_option,
        impact=impact,
        skip_impact=skip_impact,
        affected_resources=affected_resources,
    )


def _options_for(kind: str, reason: str) -> list[tuple[str, str, str]]:
    if kind == "external_exposure":
        return [("private", "Private", "Keep service internal."), ("public", "Public", "Expose through ingress later.")]
    if kind == "hostname":
        return [("provide_hostname", "Provide hostname", "Use an explicit hostname."), ("skip", "Skip", "Do not create hostname-specific resources.")]
    if kind == "secret_ref":
        return [("existing_secret", "Existing Secret", "Reference an existing Kubernetes Secret."), ("block", "Block", "Stop until Secret supply is clarified.")]
    if kind == "pvc_size":
        return [("1Gi", "1Gi", "Use a small persistent volume."), ("custom", "Custom", "Provide a custom PVC size later.")]
    if kind == "stateful_workload" or reason == "stateful_requires_design_review":
        return [("stop", "Stop", "Do not generate stateful workload automatically."), ("deployment_pvc", "Deployment + PVC", "Proceed only if this is explicitly acceptable.")]
    return [("confirm", "Confirm", "Confirm this deployment decision."), ("skip", "Skip", "Leave this decision unresolved.")]


def _recommended_for(kind: str) -> str | None:
    return {
        "external_exposure": "private",
        "hostname": "skip",
        "secret_ref": "existing_secret",
        "pvc_size": "1Gi",
        "stateful_workload": "stop",
    }.get(kind)


def _prompt_for(kind: str, reason: str) -> str:
    prompts = {
        "external_exposure": "Should this service be exposed outside the cluster?",
        "hostname": "Which hostname should be used?",
        "secret_ref": "How should this Secret be supplied?",
        "pvc_size": "What PVC size should be used?",
        "stateful_workload": "How should the stateful workload requirement be handled?",
    }
    return prompts.get(kind, f"Confirm deployment decision for {reason}.")


def _impact_for(kind: str) -> str:
    return f"Answer affects {', '.join(_resources_for(kind)) or 'the deployment plan'}."


def _skip_impact_for(kind: str) -> str:
    return "Skipping leaves the related decision unresolved and may block manifest generation."


def _resources_for(kind: str) -> list[str]:
    return {
        "external_exposure": ["Ingress", "Service"],
        "hostname": ["Ingress"],
        "secret_ref": ["Deployment", "Secret"],
        "pvc_size": ["PersistentVolumeClaim", "Deployment"],
        "stateful_workload": ["Deployment", "PersistentVolumeClaim"],
    }.get(kind, [])


def _dedupe_sorted(questions: list[Question]) -> list[Question]:
    by_id = {question.question_id: question for question in questions}
    return [by_id[key] for key in sorted(by_id, key=lambda question_id: by_id[question_id].reason_code)]


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest.upper()}"
