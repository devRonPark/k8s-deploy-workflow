from __future__ import annotations

import yaml

from k8s_agent.analysis.phase1_adapter import Phase1Result
from k8s_agent.models.topology import (
    AnalysisCoverage,
    ApplicationComponent,
    ApplicationTopology,
    DependencyEdge,
    DeploymentVariant,
    EvidenceLinkedValue,
    RepositoryModule,
    RuntimeInfo,
    SecretUse,
    TopologyField,
    TopologyConflict,
)
from preanalyzer.models.evidence import EvidenceModel
from preanalyzer.models.rule_inference import RuleInferenceSet
from preanalyzer.reconciliation.engine import ReconciliationResult, reconcile
from preanalyzer.rules_version import RULES_VERSION


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
        return self.build_from_reconciliation(evidence, rules, reconcile(rules, evidence))

    def build_from_reconciliation(
        self,
        evidence: EvidenceModel,
        rules: RuleInferenceSet,
        reconciliation: ReconciliationResult,
    ) -> ApplicationTopology:
        component_ids = _component_ids(rules)
        component_ids.extend(
            entry.component_id for entry in reconciliation.component_model.components
        )
        component_ids = sorted(set(component_ids))
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

        for entry in reconciliation.component_model.components:
            component = components.setdefault(entry.component_id, ApplicationComponent(component_id=entry.component_id))
            if entry.role.value is None:
                continue
            components[entry.component_id] = component.model_copy(
                update={
                    "role": entry.role.value,
                    "evidence_refs": sorted(set(component.evidence_refs + entry.role.evidence_refs)),
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

        conflict_paths = {conflict.field_path for conflict in conflicts}
        for runtime in reconciliation.runtime_model.runtimes:
            command = runtime.command
            if command is None or command.value is None:
                continue
            if f"/components/{runtime.component_id}/runtime/command" in conflict_paths:
                continue
            component = components.setdefault(runtime.component_id, ApplicationComponent(component_id=runtime.component_id))
            if component.command is not None:
                continue
            components[runtime.component_id] = component.model_copy(
                update={
                    "command": EvidenceLinkedValue(
                        value=command.value,
                        source=command.source or "reconciliation",
                        confidence=_confidence_value(command.confidence),
                        classification=_classification_for_reconciled_source(command.source),
                        evidence_refs=sorted(command.evidence_refs),
                    )
                }
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

        sorted_conflicts = sorted(conflicts, key=lambda conflict: conflict.field_path)
        enriched_components = [
            _with_canonical_fields(components[key], sorted_conflicts, evidence)
            for key in sorted(components)
        ]
        repository_modules = _repository_modules(evidence)
        return ApplicationTopology(
            rules_version=RULES_VERSION,
            repository_modules=repository_modules,
            deployment_variants=[
                DeploymentVariant(
                    variant_id="common",
                    source="implicit_common",
                    evidence_refs=[],
                )
            ],
            analysis_coverage=_analysis_coverage(evidence, repository_modules, enriched_components),
            components=enriched_components,
            conflicts=sorted_conflicts,
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


def _confidence_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _classification_for_reconciled_source(source: str | None) -> str:
    if source == "llm_semantic_inference":
        return "llm_interpretation"
    return "rule_inference"


def _with_canonical_fields(
    component: ApplicationComponent,
    conflicts: list[TopologyConflict],
    evidence: EvidenceModel,
) -> ApplicationComponent:
    fields: list[TopologyField] = []
    component_refs = _component_refs(component)
    fields.append(
        _resolved_field(
            f"/components/{component.component_id}/present",
            "core",
            True,
            "component_candidate",
            "high",
            "rule_inference",
            component_refs,
        )
    )
    fields.append(
        _resolved_field(
            f"/components/{component.component_id}/deployment_role",
            "core",
            component.role,
            "component_role",
            "medium",
            "rule_inference",
            component_refs,
        )
    )
    fields.append(_runtime_command_field(component, conflicts))
    fields.append(_runtime_port_field(component))
    fields.append(_secret_classification_field(component))
    fields.append(_build_strategy_field(component))
    fields.extend(_package_dependency_fields(component, evidence))
    return component.model_copy(
        update={"fields": sorted(fields, key=lambda field: field.field_path)}
    )


def _runtime_command_field(
    component: ApplicationComponent,
    conflicts: list[TopologyConflict],
) -> TopologyField:
    path = f"/components/{component.component_id}/effective_runtime_command"
    conflict = next(
        (
            item
            for item in conflicts
            if item.field_path == f"/components/{component.component_id}/runtime/command"
        ),
        None,
    )
    if conflict is not None:
        return TopologyField(
            field_path=path,
            group="core",
            state="conflict",
            evidence_refs=sorted(conflict.evidence_refs),
            candidates=conflict.candidates,
            reason=conflict.reason,
        )
    if component.command is not None:
        return _resolved_from_value(path, "core", component.command)
    return TopologyField(
        field_path=path,
        group="core",
        state="unresolved",
        reason="runtime_command_not_detected",
        evidence_refs=_component_refs(component),
    )


def _runtime_port_field(component: ApplicationComponent) -> TopologyField:
    path = f"/components/{component.component_id}/runtime_port"
    if len(component.ports) > 1:
        return TopologyField(
            field_path=path,
            group="core",
            state="conflict",
            evidence_refs=sorted({ref for port in component.ports for ref in port.evidence_refs}),
            candidates=component.ports,
            reason="conflicting_runtime_ports",
        )
    if len(component.ports) == 1:
        return _resolved_from_value(path, "core", component.ports[0])
    return TopologyField(
        field_path=path,
        group="core",
        state="unresolved",
        reason="runtime_port_not_detected",
        evidence_refs=_component_refs(component),
    )


def _secret_classification_field(component: ApplicationComponent) -> TopologyField:
    path = f"/components/{component.component_id}/secret_classification"
    if component.secrets:
        refs = sorted({ref for secret in component.secrets for ref in secret.evidence_refs})
        candidates = [
            EvidenceLinkedValue(
                value=secret.name,
                source=secret.source,
                confidence="medium",
                classification=secret.classification,
                evidence_refs=sorted(secret.evidence_refs),
            )
            for secret in component.secrets
        ]
        return TopologyField(
            field_path=path,
            group="core",
            state="resolved",
            value="secret",
            source="secret_classification",
            confidence="high",
            classification="rule_inference",
            evidence_refs=refs,
            candidates=candidates,
        )
    return TopologyField(
        field_path=path,
        group="core",
        state="not_applicable",
        source="secret_absence",
        confidence="high",
        classification="rule_inference",
        evidence_refs=_component_refs(component),
        reason="no_secret_like_inputs_detected",
    )


def _build_strategy_field(component: ApplicationComponent) -> TopologyField:
    path = f"/components/{component.component_id}/build_strategy"
    if component.runtime is not None:
        return _resolved_field(
            path,
            "extended",
            component.runtime.build_strategy,
            component.runtime.source,
            component.runtime.confidence,
            component.runtime.classification,
            component.runtime.evidence_refs,
        )
    return TopologyField(
        field_path=path,
        group="extended",
        state="unresolved",
        reason="build_strategy_not_detected",
        evidence_refs=_component_refs(component),
    )


def _package_dependency_fields(
    component: ApplicationComponent, evidence: EvidenceModel
) -> list[TopologyField]:
    fields: list[TopologyField] = []
    for fact in evidence.facts_by_type("package_dependency"):
        if not _fact_belongs_to_component(fact.artifact_ref, component):
            continue
        if not isinstance(fact.value, dict) or "package" not in fact.value:
            continue
        package_name = str(fact.value["package"])
        module_id = _module_id_for_root(_artifact_root(fact.artifact_ref))
        fields.append(
            _resolved_field(
                f"/repository_modules/{module_id}/package_dependencies/{package_name}",
                "extended",
                True,
                fact.source,
                "high",
                fact.classification,
                [fact.evidence_id],
            )
        )
    return fields


def _resolved_from_value(
    field_path: str,
    group: str,
    tracked: EvidenceLinkedValue,
) -> TopologyField:
    return TopologyField(
        field_path=field_path,
        group=group,
        state="resolved",
        value=tracked.value,
        source=tracked.source,
        confidence=tracked.confidence,
        classification=tracked.classification,
        evidence_refs=sorted(tracked.evidence_refs),
        candidates=[tracked],
    )


def _resolved_field(
    field_path: str,
    group: str,
    value,
    source: str,
    confidence: str | None,
    classification: str,
    evidence_refs: list[str],
) -> TopologyField:
    refs = sorted(set(evidence_refs))
    candidate = EvidenceLinkedValue(
        value=value,
        source=source,
        confidence=confidence,
        classification=classification,
        evidence_refs=refs,
    )
    return TopologyField(
        field_path=field_path,
        group=group,
        state="resolved",
        value=value,
        source=source,
        confidence=confidence,
        classification=classification,
        evidence_refs=refs,
        candidates=[candidate],
    )


def _component_refs(component: ApplicationComponent) -> list[str]:
    refs = set(component.evidence_refs)
    if component.runtime is not None:
        refs.update(component.runtime.evidence_refs)
    if component.command is not None:
        refs.update(component.command.evidence_refs)
    for port in component.ports:
        refs.update(port.evidence_refs)
    for dependency in component.dependencies:
        refs.update(dependency.evidence_refs)
    for secret in component.secrets:
        refs.update(secret.evidence_refs)
    return sorted(refs)


def _repository_modules(evidence: EvidenceModel) -> list[RepositoryModule]:
    modules: dict[str, dict] = {}
    for fact in evidence.facts:
        if fact.fact_type not in {
            "maven_packaging",
            "package_dependency",
            "package_script",
            "python_requirement_include",
            "python_direct_reference",
        }:
            continue
        root = _artifact_root(fact.artifact_ref)
        module_id = _module_id_for_root(root)
        module = modules.setdefault(
            module_id,
            {
                "module_id": module_id,
                "root_path": root,
                "build_system": _build_system_for_artifact(fact.artifact_ref),
                "evidence_refs": set(),
                "package_dependencies": {},
            },
        )
        module["evidence_refs"].add(fact.evidence_id)
        if module["build_system"] is None:
            module["build_system"] = _build_system_for_artifact(fact.artifact_ref)
        if fact.fact_type == "package_dependency" and isinstance(fact.value, dict):
            package = str(fact.value.get("package", ""))
            if package:
                module["package_dependencies"][package] = EvidenceLinkedValue(
                    value=package,
                    source=fact.source,
                    confidence="high",
                    classification=fact.classification,
                    evidence_refs=[fact.evidence_id],
                )
    return [
        RepositoryModule(
            module_id=module["module_id"],
            root_path=module["root_path"],
            build_system=module["build_system"],
            evidence_refs=sorted(module["evidence_refs"]),
            package_dependencies=[
                module["package_dependencies"][name]
                for name in sorted(module["package_dependencies"])
            ],
        )
        for module in (modules[key] for key in sorted(modules))
    ]


SUPPORTED_COVERAGE_ARTIFACT_TYPES = {
    "compose",
    "dockerfile",
    "maven",
    "nodejs",
    "python_pyproject",
    "python_requirements",
}


def _analysis_coverage(
    evidence: EvidenceModel,
    modules: list[RepositoryModule],
    components: list[ApplicationComponent],
) -> list[AnalysisCoverage]:
    coverage: list[AnalysisCoverage] = []
    artifact_by_ref = {
        fact.evidence_id: fact.artifact_ref
        for fact in evidence.facts
    }
    for fact in evidence.facts_by_type("artifact_presence"):
        if not isinstance(fact.value, dict):
            continue
        artifact_type = str(fact.value.get("type", "unknown"))
        present = bool(fact.value.get("present", True))
        field_paths = _interpreted_field_paths_for_artifact(
            fact.artifact_ref,
            artifact_by_ref,
            modules,
            components,
        )
        if not present:
            status = "absent"
        elif field_paths:
            status = "analyzed"
        elif artifact_type in SUPPORTED_COVERAGE_ARTIFACT_TYPES:
            status = "coverage_gap"
        else:
            status = "coverage_gap"
        coverage.append(
            AnalysisCoverage(
                artifact_ref=fact.artifact_ref,
                artifact_type=artifact_type,
                status=status,
                evidence_refs=[fact.evidence_id],
                field_paths=field_paths,
                limitation=None if status != "coverage_gap" else "artifact_not_interpreted_by_topology_builder",
            )
        )
    return sorted(coverage, key=lambda item: (item.artifact_ref, item.artifact_type))


def _interpreted_field_paths_for_artifact(
    artifact_ref: str,
    artifact_by_ref: dict[str, str],
    modules: list[RepositoryModule],
    components: list[ApplicationComponent],
) -> list[str]:
    paths: set[str] = set()

    def refs_point_here(refs: list[str]) -> bool:
        return any(artifact_by_ref.get(ref) == artifact_ref for ref in refs)

    for module in modules:
        if refs_point_here(module.evidence_refs):
            paths.add(f"/repository_modules/{module.module_id}")
        for dependency in module.package_dependencies:
            if refs_point_here(dependency.evidence_refs):
                paths.add(
                    f"/repository_modules/{module.module_id}/package_dependencies/{dependency.value}"
                )

    for component in components:
        for field in component.fields:
            if refs_point_here(field.evidence_refs):
                paths.add(field.field_path)
            for candidate in field.candidates:
                if refs_point_here(candidate.evidence_refs):
                    paths.add(field.field_path)

    return sorted(paths)


def _fact_belongs_to_component(artifact_ref: str, component: ApplicationComponent) -> bool:
    root_path = component.root_path
    if root_path is None:
        return False
    if root_path == ".":
        return "/" not in artifact_ref
    return artifact_ref == root_path or artifact_ref.startswith(f"{root_path}/")


def _artifact_root(artifact_ref: str) -> str:
    parent = artifact_ref.rsplit("/", 1)[0] if "/" in artifact_ref else "."
    return parent or "."


def _module_id_for_root(root: str) -> str:
    if root in {"", "."}:
        return "root"
    return root


def _build_system_for_artifact(artifact_ref: str) -> str | None:
    if artifact_ref.endswith("package.json"):
        return "npm"
    if artifact_ref.endswith("pom.xml"):
        return "maven"
    if artifact_ref.endswith("pyproject.toml"):
        return "python"
    if artifact_ref.endswith("requirements.txt"):
        return "python"
    return None


def _load_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_topology_artifact(path, topology: ApplicationTopology) -> None:
    payload = {"application_topology": topology.model_dump(mode="json", exclude_none=True)}
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _write_topology(path, topology: ApplicationTopology) -> None:
    write_topology_artifact(path, topology)
