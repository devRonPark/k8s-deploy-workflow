from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from k8s_agent.models.intent import IntentCandidate, KubernetesIntent
from k8s_agent.models.topology import ApplicationComponent, ApplicationTopology, EvidenceLinkedValue
from k8s_agent.policy.engine import PolicyEngine
from k8s_agent.policy.target_policy import POLICY_VERSION, Target


INTENT_ARTIFACT = "05-kubernetes-intent.yaml"


class IntentBuilder:
    def __init__(self, *, output_dir: Path | None = None, policy: PolicyEngine | None = None) -> None:
        self.output_dir = output_dir
        self.policy = policy or PolicyEngine()

    def build(self, topology: ApplicationTopology, target: Target | str) -> KubernetesIntent:
        resolved_target = Target(target)
        candidates: list[IntentCandidate] = []
        for component in sorted(topology.components, key=lambda item: item.component_id):
            candidates.extend(self._component_candidates(component, resolved_target))
        if resolved_target != Target.PRODUCTION:
            candidates.append(self._candidate("__run__", "cluster_validation", "/cluster_validation", True, "target_policy", "high", [], "policy_default", resolved_target))
        candidates = [self._with_decision(candidate, resolved_target) for candidate in candidates]
        intent = KubernetesIntent(
            target=resolved_target.value,
            candidates=sorted(candidates, key=lambda item: (item.component_id, item.kind, item.field_path, item.candidate_id)),
        )
        if self.output_dir is not None:
            _write_intent(self.output_dir / INTENT_ARTIFACT, intent)
        return intent

    def _component_candidates(self, component: ApplicationComponent, target: Target) -> list[IntentCandidate]:
        candidates: list[IntentCandidate] = []
        if component.role == "application":
            refs = _refs(component.evidence_refs, component.runtime.evidence_refs if component.runtime else [])
            candidates.append(self._candidate(component.component_id, "deployment", "/workload/deployment", {"enabled": True}, "application_topology", "high", refs, "rule_inference", target))
            replica_default = self.policy.replica_default(target)
            replica = replica_default.model_copy(
                update={
                    "candidate_id": _candidate_id(target, component.component_id, "replicas", "/workload/replicas", replica_default.value),
                    "component_id": component.component_id,
                    "field_path": f"/components/{component.component_id}/workload/replicas",
                }
            )
            candidates.append(replica)
            if component.command is not None:
                candidates.append(self._from_value(component, "runtime_command", "/workload/command", component.command, target))
            first_port = component.ports[0] if component.ports else None
            if first_port is not None:
                candidates.append(self._from_value(component, "service", "/service/port", first_port, target, value={"port": first_port.value}))
                candidates.append(self._candidate(component.component_id, "external_exposure", "/network/external_exposure", {"service_port": first_port.value}, "target_policy", "high", list(first_port.evidence_refs), "policy_default", target))
                candidates.append(self._candidate(component.component_id, "readiness_probe", "/probes/readiness", {"port": first_port.value}, "target_policy", "high", [], "policy_default", target))
                candidates.append(self._candidate(component.component_id, "liveness_probe", "/probes/liveness", {"port": first_port.value}, "target_policy", "high", [], "policy_default", target))
            candidates.append(self._candidate(component.component_id, "resource_requests", "/resources/requests", {"cpu": "100m", "memory": "128Mi"}, "target_policy", "high", [], "policy_default", target))
        if component.role == "dependency":
            candidates.append(self._candidate(component.component_id, "stateful_workload", "/workload/stateful", {"required": True}, "application_topology", "medium", list(component.evidence_refs), "rule_inference", target))
            candidates.append(self._candidate(component.component_id, "pvc_size", "/storage/pvc_size", {"size": None}, "target_policy", "high", [], "policy_default", target))
        for secret in component.secrets:
            candidates.append(
                self._candidate(
                    component.component_id,
                    "secret_ref",
                    f"/components/{component.component_id}/secrets/{secret.name}",
                    {"name": secret.name},
                    secret.source,
                    "medium",
                    list(secret.evidence_refs),
                    secret.classification,
                    target,
                )
            )
        return candidates

    def _from_value(
        self,
        component: ApplicationComponent,
        kind: str,
        field_path: str,
        tracked: EvidenceLinkedValue,
        target: Target,
        *,
        value: Any | None = None,
    ) -> IntentCandidate:
        return self._candidate(
            component.component_id,
            kind,
            field_path,
            tracked.value if value is None else value,
            tracked.source,
            tracked.confidence or "medium",
            list(tracked.evidence_refs),
            tracked.classification,
            target,
        )

    def _candidate(
        self,
        component_id: str,
        kind: str,
        field_path: str,
        value: Any,
        source: str,
        confidence: str,
        evidence_refs: list[str],
        classification: str,
        target: Target,
    ) -> IntentCandidate:
        full_path = field_path if field_path.startswith("/components/") or component_id == "__run__" else f"/components/{component_id}{field_path}"
        return IntentCandidate(
            candidate_id=_candidate_id(target, component_id, kind, full_path, value),
            component_id=component_id,
            kind=kind,
            field_path=full_path,
            value=value,
            source=source,
            confidence=confidence,
            classification=classification,
            evidence_refs=sorted(evidence_refs),
            policy_version=POLICY_VERSION,
        )

    def _with_decision(self, candidate: IntentCandidate, target: Target) -> IntentCandidate:
        if candidate.decision is not None:
            return candidate
        return candidate.model_copy(update={"decision": self.policy.evaluate(candidate, target)})


def _candidate_id(target: Target, component_id: str, kind: str, field_path: str, value: Any) -> str:
    payload = {
        "target": target.value,
        "component_id": component_id,
        "kind": kind,
        "field_path": field_path,
        "value": value,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]
    return f"KI-{digest.upper()}"


def _refs(*groups: list[str]) -> list[str]:
    return sorted({ref for group in groups for ref in group})


def _write_intent(path: Path, intent: KubernetesIntent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"kubernetes_intent": intent.model_dump(mode="json", exclude_none=True)}
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
