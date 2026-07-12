"""Reconciliation engine: RuleInferenceSet + EvidenceModel + accepted commands -> intent + questions."""

from __future__ import annotations
from dataclasses import dataclass, field

from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.fields import Tracked, Confidence
from preanalyzer.models.rule_inference import RuleInferenceSet, RoleCandidate
from preanalyzer.models.component import ComponentModel, ComponentEntry
from preanalyzer.models.runtime import RuntimeModel, RuntimeEntry
from preanalyzer.models.dependency import DependencyModel, DependencyEdge, EnvBinding
from preanalyzer.models.intent import (
    KubernetesIntent, ComponentIntent, Workload, ServiceIntent)
from preanalyzer.models.questions import UnresolvedQuestions, UnresolvedQuestion


@dataclass(frozen=True)
class AcceptedSemanticCommand:
    component_id: str
    command: str
    evidence_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReconciliationResult:
    component_model: ComponentModel
    runtime_model: RuntimeModel
    dependency_model: DependencyModel
    intent: KubernetesIntent
    questions: UnresolvedQuestions


def _conf(name: str) -> Confidence:
    return {"high": Confidence.HIGH, "medium": Confidence.MEDIUM, "low": Confidence.LOW}.get(name, Confidence.LOW)


def reconcile(rules: RuleInferenceSet, evidence: EvidenceModel,
              accepted_commands: list[AcceptedSemanticCommand] | None = None) -> ReconciliationResult:
    accepted = {c.component_id: c for c in (accepted_commands or [])}
    _conf_rank = {"high": 0, "medium": 1, "low": 2}
    roles: dict[str, "RoleCandidate"] = {}
    for rc in sorted(rules.role_candidates,
                      key=lambda c: (c.component_id, _conf_rank.get(c.confidence, 3), c.role)):
        roles.setdefault(rc.component_id, rc)  # best-confidence (then role name) wins deterministically

    components, runtimes, intents, questions = [], [], [], []
    comp_ids = sorted({c.component_id for c in rules.component_candidates})

    ports_by_comp: dict[str, list] = {}
    for pc in rules.runtime_port_candidates:
        ports_by_comp.setdefault(pc.component_id, []).append(pc)
    cmds_by_comp = {c.component_id: c for c in rules.runtime_command_candidates}

    for cid in comp_ids:
        rc = roles.get(cid)
        role = rc.role if rc is not None else "application"
        role_tracked = (
            Tracked(value=rc.role, source=rc.source, confidence=_conf(rc.confidence), evidence_refs=list(rc.evidence_refs))
            if rc is not None else
            Tracked(value="application", source="rule_inference_default", confidence=Confidence.LOW, evidence_refs=[]))
        components.append(ComponentEntry(component_id=cid, role=role_tracked))

        # port
        distinct_ports = sorted({p.port for p in ports_by_comp.get(cid, [])})
        port_tracked = None
        if len(distinct_ports) == 1:
            p = ports_by_comp[cid][0]
            port_tracked = Tracked(value=p.port, source=p.source, confidence=_conf(p.confidence), evidence_refs=list(p.evidence_refs))
        elif len(distinct_ports) > 1:
            questions.append(UnresolvedQuestion(
                id=f"Q-PORT-{cid}", field="runtime.port",
                question=f"Component {cid} exposes conflicting ports; which is the runtime port?",
                reason="conflicting_port_evidence", answer_type="port",
                candidates=[str(p) for p in distinct_ports],
                blocking_level="application_runnable", profile_field=None))

        # command: deterministic > accepted semantic
        cmd_tracked = None
        if cid in cmds_by_comp:
            c = cmds_by_comp[cid]
            cmd_tracked = Tracked(value=c.command, source=c.source, confidence=_conf(c.confidence), evidence_refs=list(c.evidence_refs))
        elif cid in accepted:
            a = accepted[cid]
            cmd_tracked = Tracked(value=a.command, source="llm_semantic_inference", confidence=Confidence.MEDIUM, evidence_refs=list(a.evidence_refs))

        runtimes.append(RuntimeEntry(
            component_id=cid,
            language=Tracked(value="unknown", source="rule_inference", confidence=Confidence.LOW, evidence_refs=[]),
            build_strategy="dockerfile", port=port_tracked, command=cmd_tracked))

        # intent
        if role == "application":
            workload = Workload(
                image_name=Tracked(value=cid, source="component_id", confidence=Confidence.MEDIUM, evidence_refs=[]),
                port=port_tracked, command=cmd_tracked,
                secret_env=sorted({s.name for s in rules.env_classification.secret_candidates if s.component_id == cid}))
            service = ServiceIntent(port=port_tracked) if port_tracked is not None else None
            intents.append(ComponentIntent(component_id=cid, role=role, workload=workload, service=service))
        else:
            intents.append(ComponentIntent(component_id=cid, role=role))

    # ops questions (merged once)
    questions.append(UnresolvedQuestion(id="Q-REG-001", field="image_registry",
        question="Which container registry hosts the built images?", reason="no_registry_evidence",
        answer_type="registry", blocking_level="application_runnable", profile_field="registry"))
    questions.append(UnresolvedQuestion(id="Q-NS-001", field="namespace",
        question="Which namespace should these resources deploy to?", reason="no_namespace_evidence",
        answer_type="namespace", blocking_level="application_runnable", profile_field="namespace"))
    if evidence.facts_by_type("compose_label"):
        questions.append(UnresolvedQuestion(id="Q-ING-001", field="ingress_host",
            question="Which host should the ingress route?", reason="traefik_label_detected",
            answer_type="ingress_host", blocking_level="feature_partial", profile_field="ingress_host"))

    edges = [DependencyEdge(source_component=e.source_component, target=e.target, dependency_type=e.dependency_type,
        confidence=Tracked(value=e.confidence, source=e.source, confidence=_conf(e.confidence), evidence_refs=list(e.evidence_refs)))
        for e in sorted(rules.dependency_edge_candidates, key=lambda e: (e.source_component, e.target))]
    env_bindings = [EnvBinding(component_id=s.component_id, name=s.name, kind="secret")
        for s in sorted(rules.env_classification.secret_candidates, key=lambda s: (s.component_id, s.name))]

    return ReconciliationResult(
        component_model=ComponentModel(components=components),
        runtime_model=RuntimeModel(runtimes=runtimes),
        dependency_model=DependencyModel(edges=edges, env_bindings=env_bindings),
        intent=KubernetesIntent(namespace=None, components=intents),
        questions=UnresolvedQuestions(questions=sorted(questions, key=lambda q: q.id)))
