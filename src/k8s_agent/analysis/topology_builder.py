from __future__ import annotations

import yaml

from k8s_agent.analysis.phase1_adapter import Phase1Result
from k8s_agent.models.topology import (
    ApplicationComponent,
    ApplicationTopology,
    DependencyEdge,
    EvidenceLinkedValue,
    RuntimeInfo,
    SecretUse,
    TopologyConflict,
)
from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.rule_inference import RuleInferenceSet


TOPOLOGY_ARTIFACT = "04-application-topology.yaml"


class TopologyBuilder:
    def build(self, phase1: Phase1Result) -> ApplicationTopology:
        evidence_payload = _load_yaml(phase1.analysis_dir / "02-evidence-model.yaml")["evidence_model"]
        rules_payload = _load_yaml(phase1.analysis_dir / "03-rule-inference.yaml")["rule_inference"]
        topology = self.build_from_models(
            EvidenceModel.model_validate(evidence_payload),
            RuleInferenceSet.model_validate(rules_payload),
        )
        _write_topology(phase1.analysis_dir / TOPOLOGY_ARTIFACT, topology)
        return topology

    def build_from_models(self, evidence: EvidenceModel, rules: RuleInferenceSet) -> ApplicationTopology:
        del evidence
        component_ids = _component_ids(rules)
        components = {
            component_id: ApplicationComponent(component_id=component_id)
            for component_id in component_ids
        }

        for candidate in rules.component_candidates:
            component = components[candidate.component_id]
            components[candidate.component_id] = component.model_copy(
                update={
                    "root_path": candidate.root_path,
                    "evidence_refs": sorted(set(component.evidence_refs + candidate.evidence_refs)),
                }
            )

        for candidate in rules.role_candidates:
            component = components.setdefault(candidate.component_id, ApplicationComponent(component_id=candidate.component_id))
            components[candidate.component_id] = component.model_copy(
                update={
                    "role": candidate.role,
                    "evidence_refs": sorted(set(component.evidence_refs + candidate.evidence_refs)),
                }
            )

        for candidate in rules.runtime_candidates:
            component = components.setdefault(candidate.component_id, ApplicationComponent(component_id=candidate.component_id))
            if component.runtime is None or _confidence_rank(candidate.confidence) > _confidence_rank(component.runtime.confidence):
                components[candidate.component_id] = component.model_copy(
                    update={
                        "runtime": RuntimeInfo(
                            language=candidate.language,
                            framework=candidate.framework,
                            build_tool=candidate.build_tool,
                            build_strategy=candidate.build_strategy,
                            source=candidate.source,
                            confidence=candidate.confidence,
                            classification=candidate.classification,
                            evidence_refs=sorted(candidate.evidence_refs),
                        )
                    }
                )

        for candidate in rules.runtime_port_candidates:
            component = components.setdefault(candidate.component_id, ApplicationComponent(component_id=candidate.component_id))
            ports = list(component.ports)
            if candidate.port not in {port.value for port in ports}:
                ports.append(
                    EvidenceLinkedValue(
                        value=candidate.port,
                        source=candidate.source,
                        confidence=candidate.confidence,
                        classification=candidate.classification,
                        evidence_refs=sorted(candidate.evidence_refs),
                    )
                )
            components[candidate.component_id] = component.model_copy(update={"ports": sorted(ports, key=lambda p: p.value)})

        conflicts: list[TopologyConflict] = []
        commands_by_component: dict[str, list] = {}
        for candidate in rules.runtime_command_candidates:
            commands_by_component.setdefault(candidate.component_id, []).append(candidate)
        for component_id, candidates in commands_by_component.items():
            component = components.setdefault(component_id, ApplicationComponent(component_id=component_id))
            unique_commands = {candidate.command for candidate in candidates}
            if len(unique_commands) == 1:
                candidate = sorted(candidates, key=lambda item: (-_confidence_rank(item.confidence), item.command))[0]
                components[component_id] = component.model_copy(
                    update={
                        "command": EvidenceLinkedValue(
                            value=candidate.command,
                            source=candidate.source,
                            confidence=candidate.confidence,
                            classification=candidate.classification,
                            evidence_refs=sorted(candidate.evidence_refs),
                        )
                    }
                )
            else:
                conflict_candidates = [
                    EvidenceLinkedValue(
                        value=candidate.command,
                        source=candidate.source,
                        confidence=candidate.confidence,
                        classification=candidate.classification,
                        evidence_refs=sorted(candidate.evidence_refs),
                    )
                    for candidate in sorted(candidates, key=lambda item: item.command)
                ]
                refs = sorted({ref for candidate in conflict_candidates for ref in candidate.evidence_refs})
                conflicts.append(
                    TopologyConflict(
                        field_path=f"/components/{component_id}/runtime/command",
                        reason="conflicting_runtime_commands",
                        candidates=conflict_candidates,
                        evidence_refs=refs,
                    )
                )

        for candidate in rules.dependency_edge_candidates:
            component = components.setdefault(candidate.source_component, ApplicationComponent(component_id=candidate.source_component))
            dependencies = list(component.dependencies)
            dependencies.append(
                DependencyEdge(
                    target=candidate.target,
                    dependency_type=candidate.dependency_type,
                    source=candidate.source,
                    confidence=candidate.confidence,
                    classification=candidate.classification,
                    evidence_refs=sorted(candidate.evidence_refs),
                )
            )
            components[candidate.source_component] = component.model_copy(
                update={"dependencies": sorted(dependencies, key=lambda edge: (edge.target, edge.dependency_type, edge.source))}
            )

        for candidate in rules.env_classification.secret_candidates:
            component = components.setdefault(candidate.component_id, ApplicationComponent(component_id=candidate.component_id))
            secrets = list(component.secrets)
            if candidate.name not in {secret.name for secret in secrets}:
                secrets.append(
                    SecretUse(
                        name=candidate.name,
                        source=candidate.source,
                        classification=candidate.classification,
                        evidence_refs=sorted(candidate.evidence_refs),
                    )
                )
            components[candidate.component_id] = component.model_copy(update={"secrets": sorted(secrets, key=lambda secret: secret.name)})

        return ApplicationTopology(
            components=[components[key] for key in sorted(components)],
            conflicts=sorted(conflicts, key=lambda conflict: conflict.field_path),
        )


def _component_ids(rules: RuleInferenceSet) -> list[str]:
    ids = {candidate.component_id for candidate in rules.component_candidates}
    ids.update(candidate.component_id for candidate in rules.role_candidates)
    ids.update(candidate.component_id for candidate in rules.runtime_candidates)
    ids.update(candidate.component_id for candidate in rules.runtime_port_candidates)
    ids.update(candidate.component_id for candidate in rules.runtime_command_candidates)
    ids.update(candidate.source_component for candidate in rules.dependency_edge_candidates)
    ids.update(candidate.component_id for candidate in rules.env_classification.secret_candidates)
    return sorted(ids)


def _confidence_rank(value: str | None) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(value or "", 0)


def _load_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_topology(path, topology: ApplicationTopology) -> None:
    payload = {"application_topology": topology.model_dump(mode="json", exclude_none=True)}
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
