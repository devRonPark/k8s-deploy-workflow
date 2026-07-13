"""Deployment profile validation + merge into KubernetesIntent (Task 6)."""

from __future__ import annotations
from dataclasses import dataclass

from preanalyzer.models.fields import Tracked, Confidence
from preanalyzer.models.intent import KubernetesIntent, IngressIntent
from preanalyzer.models.profile import DeploymentProfile
from preanalyzer.models.questions import UnresolvedQuestions
from preanalyzer.reconciliation.engine import ReconciliationResult


@dataclass(frozen=True)
class MergeResult:
    intent: KubernetesIntent
    questions: UnresolvedQuestions
    ready_for_level2: bool


def _pf(value: str) -> Tracked[str]:
    return Tracked(value=value, source="deployment_profile", confidence=Confidence.HIGH, evidence_refs=[])


def merge(result: ReconciliationResult, profile: DeploymentProfile) -> MergeResult:
    intent = result.intent.model_copy(deep=True)
    if profile.namespace:
        intent.namespace = _pf(profile.namespace)
    for ci in intent.components:
        if ci.workload is None:
            continue
        if profile.registry:
            ci.workload.image_registry = _pf(profile.registry)
        ci.workload.image_tag = _pf(profile.image_tag)
    if profile.ingress_host:
        app = next((c for c in intent.components if c.role == "application"), None)
        if app is not None:
            app.ingress = IngressIntent(host=_pf(profile.ingress_host))

    satisfied = set()
    if profile.registry:
        satisfied.add("registry")
    if profile.namespace:
        satisfied.add("namespace")
    if profile.ingress_host:
        satisfied.add("ingress_host")
    remaining = [q for q in result.questions.questions if q.profile_field not in satisfied]
    ready = not any(q.blocking_level == "application_runnable" for q in remaining)
    return MergeResult(intent=intent, questions=UnresolvedQuestions(questions=remaining), ready_for_level2=ready)
