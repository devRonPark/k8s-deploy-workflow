from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from migration_agent.adapters.models import LegacyAnalysisArtifacts
from migration_agent.domain.common import FieldState, TrackedValue, normalized_values
from migration_agent.domain.lifecycle import LifecycleModel, LifecycleVariant
from migration_agent.domain.repository import RepositoryIdentity
from migration_agent.domain.topology import ApplicationComponent, ApplicationTopology
from migration_agent.domain.understanding import (
    ArtifactCoverage,
    ConfirmedFact,
    ConflictFinding,
    CoverageStatus,
    EvidenceRef,
    UnderstandingCoverage,
    UnknownFinding,
)


SCHEMA_VERSION = "repository-understanding/v1-beta"


def project_repository(
    repository_path: Path,
    artifacts: LegacyAnalysisArtifacts,
) -> RepositoryIdentity:
    snapshot = artifacts.repository_snapshot
    return RepositoryIdentity(
        path=str(repository_path),
        commit_sha=snapshot.get("commit_sha"),
        workspace_hash=snapshot.get("workspace_hash"),
        analyzed_at=snapshot.get("analyzed_at"),
        analyzer_version=snapshot.get("analyzer_version"),
        rules_version=snapshot.get("rules_version"),
    )


def project_evidence(artifacts: LegacyAnalysisArtifacts) -> list[EvidenceRef]:
    evidence: list[EvidenceRef] = []
    fact_counts: dict[tuple[str, str], int] = {}
    compose_counts: dict[tuple[str, str, str], int] = {}
    for fact in artifacts.evidence_model.get("facts", []):
        key = (str(fact.get("artifact_ref", "")), str(fact.get("fact_type", "")))
        fact_index = fact_counts.get(key, 0)
        fact_counts[key] = fact_index + 1
        evidence.append(
            EvidenceRef(
                evidence_id=fact["evidence_id"],
                artifact_ref=fact["artifact_ref"],
                locator=_locator_for_fact(fact, fact_index, compose_counts),
                fact_type=fact["fact_type"],
                source=fact["source"],
                classification=fact["classification"],
            )
        )
    return evidence


def project_topology(artifacts: LegacyAnalysisArtifacts) -> ApplicationTopology:
    rules = artifacts.rule_inference
    roles_by_component: dict[str, list[dict[str, Any]]] = {}
    for candidate in rules.get("role_candidates", []):
        roles_by_component.setdefault(candidate["component_id"], []).append(candidate)
    dependencies_by_component: dict[str, list[str]] = {}
    for candidate in rules.get("dependency_edge_candidates", []):
        dependencies_by_component.setdefault(candidate["source_component"], []).append(candidate["target"])

    components = [
        ApplicationComponent(
            component_id=candidate["component_id"],
            root_path=candidate.get("root_path"),
            role=_tracked_from_candidates(
                candidates=roles_by_component.get(candidate["component_id"], []),
                value_key="role",
                missing_reason="No deployment role evidence was found.",
                conflict_reason="Multiple deployment role candidates were found.",
                missing_evidence_refs=list(candidate.get("evidence_refs", [])),
            ),
            evidence_refs=list(candidate.get("evidence_refs", [])),
            dependencies=dependencies_by_component.get(candidate["component_id"], []),
        )
        for candidate in rules.get("component_candidates", [])
    ]

    return ApplicationTopology(components=components)


def project_lifecycle(artifacts: LegacyAnalysisArtifacts) -> LifecycleModel:
    scopes = _lifecycle_scopes(artifacts)
    if not scopes:
        scopes = [(None, "common")]

    return LifecycleModel(
        variants=[
            _lifecycle_variant(artifacts=artifacts, component_id=component_id, variant_id=variant_id)
            for component_id, variant_id in scopes
        ]
    )


def _lifecycle_variant(
    artifacts: LegacyAnalysisArtifacts,
    component_id: str | None,
    variant_id: str,
) -> LifecycleVariant:
    runtime_command = _tracked_from_candidates(
        candidates=_candidates_for_scope(
            artifacts=artifacts,
            candidates=artifacts.rule_inference.get("runtime_command_candidates", []),
            component_id=component_id,
            variant_id=variant_id,
            aliases=_lifecycle_component_aliases(artifacts),
        ),
        value_key="command",
        missing_reason="No runtime command evidence was found.",
        conflict_reason="Multiple runtime command candidates were found.",
    )

    return LifecycleVariant(
        component_id=component_id,
        variant_id=variant_id,
        build_command=_build_command(artifacts, component_id=component_id, variant_id=variant_id),
        package_command=_unresolved("No package command evidence was found."),
        run_command=runtime_command,
        runtime_port=_runtime_port(artifacts, component_id=component_id, variant_id=variant_id),
        environment_variable_names=_environment_variable_names(artifacts, component_id=component_id),
        external_dependencies=_external_dependencies(artifacts, component_id=component_id),
        container_build_strategy=_container_build_strategy(
            artifacts,
            component_id=component_id,
            variant_id=variant_id,
        ),
        container_entrypoint=_container_entrypoint(artifacts, component_id=component_id, variant_id=variant_id),
    )


def project_findings(
    lifecycle: LifecycleModel,
    topology: ApplicationTopology,
) -> tuple[list[ConfirmedFact], list[UnknownFinding], list[ConflictFinding]]:
    confirmed_facts: list[ConfirmedFact] = []
    unknowns: list[UnknownFinding] = []
    conflicts: list[ConflictFinding] = []

    tracked_fields = {}
    for index, variant in enumerate(lifecycle.variants):
        prefix = f"lifecycle.variants[{index}]"
        tracked_fields.update(
            {
                f"{prefix}.build_command": variant.build_command,
                f"{prefix}.package_command": variant.package_command,
                f"{prefix}.run_command": variant.run_command,
                f"{prefix}.runtime_port": variant.runtime_port,
                f"{prefix}.container_build_strategy": variant.container_build_strategy,
                f"{prefix}.container_entrypoint": variant.container_entrypoint,
            }
        )
    for index, component in enumerate(topology.components):
        tracked_fields[f"topology.components[{index}].role"] = component.role

    for field_path, tracked in tracked_fields.items():
        if tracked.state == FieldState.RESOLVED:
            confirmed_facts.append(
                ConfirmedFact(
                    fact_id=field_path.rsplit(".", 1)[-1],
                    field_path=field_path,
                    value=tracked.value,
                    source=tracked.source,
                    confidence=tracked.confidence,
                    classification=tracked.classification,
                    evidence_refs=tracked.evidence_refs,
                )
            )
        elif tracked.state == FieldState.UNRESOLVED:
            unknowns.append(
                UnknownFinding(
                    field_path=field_path,
                    reason=tracked.reason or "No repository evidence was found.",
                    reason_code=tracked.reason_code or "missing_evidence",
                    evidence_refs=tracked.evidence_refs,
                )
            )
        elif tracked.state == FieldState.CONFLICT:
            conflicts.append(
                ConflictFinding(
                    field_path=field_path,
                    candidates=tracked.candidates,
                    evidence_refs=tracked.evidence_refs,
                    reason=tracked.reason or "Conflicting repository evidence was found.",
                )
            )

    if not topology.components:
        unknowns.append(
            UnknownFinding(
                field_path="topology.components",
                reason="No component candidate evidence was found.",
            )
        )

    return confirmed_facts, unknowns, conflicts


def project_coverage(artifacts: LegacyAnalysisArtifacts) -> UnderstandingCoverage:
    inventory = artifacts.artifact_inventory
    facts_by_path = _facts_by_artifact_path(artifacts)
    warning_details = _warning_details_by_artifact_path(artifacts)
    items: list[ArtifactCoverage] = []

    for key in sorted(inventory):
        value = inventory[key]
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            if item.get("present") is False:
                continue
            path = str(item.get("path", key))
            artifact_type = str(item.get("type", key))
            path_facts = facts_by_path.get(path, [])
            evidence_refs = [str(fact.get("evidence_id")) for fact in path_facts if fact.get("evidence_id")]
            details = [*warning_details.get(path, []), *_unresolved_fact_details(path_facts)]

            if _is_ignored_inventory_item(key, artifact_type):
                items.append(
                    ArtifactCoverage(
                        artifact_ref=path,
                        artifact_type=artifact_type,
                        status=CoverageStatus.IGNORED,
                        reason_code=_ignored_reason_code(artifact_type),
                    )
                )
            elif _is_supported_inventory_item(key, artifact_type) or _has_supported_facts(path_facts):
                if details:
                    items.append(
                        ArtifactCoverage(
                            artifact_ref=path,
                            artifact_type=artifact_type,
                            status=CoverageStatus.PARTIAL,
                            reason_code=_coverage_reason_code(details),
                            details=_distinct_ordered(details),
                            evidence_refs=_distinct_ordered(evidence_refs),
                        )
                    )
                else:
                    items.append(
                        ArtifactCoverage(
                            artifact_ref=path,
                            artifact_type=artifact_type,
                            status=CoverageStatus.PARSED,
                            reason_code="parsed",
                            evidence_refs=_distinct_ordered(evidence_refs),
                        )
                    )
            else:
                items.append(
                    ArtifactCoverage(
                        artifact_ref=path,
                        artifact_type=artifact_type,
                        status=CoverageStatus.UNSUPPORTED,
                        reason_code="unsupported_artifact",
                    )
                )

    items = sorted(items, key=lambda item: (item.artifact_ref, item.artifact_type, item.status.value))
    analyzed = [item.artifact_ref for item in items if item.status in {CoverageStatus.PARSED, CoverageStatus.PARTIAL}]
    partial = [item.artifact_ref for item in items if item.status == CoverageStatus.PARTIAL]
    unsupported = [item.artifact_ref for item in items if item.status == CoverageStatus.UNSUPPORTED]
    ignored = [item.artifact_ref for item in items if item.status == CoverageStatus.IGNORED]

    return UnderstandingCoverage(
        analyzed_artifacts=len(_distinct_ordered(analyzed)),
        supported_artifacts=len(_distinct_ordered(analyzed)),
        unsupported_artifacts=_distinct_ordered(unsupported),
        partial_artifacts=_distinct_ordered(partial),
        ignored_artifacts=_distinct_ordered(ignored),
        items=items,
    )


def _tracked_from_candidates(
    candidates: list[dict[str, Any]],
    value_key: str,
    missing_reason: str,
    conflict_reason: str,
    missing_evidence_refs: list[str] | None = None,
) -> TrackedValue:
    value_candidates: list[dict[str, Any]] = []
    missing_metadata: list[str] = []
    for candidate in candidates:
        projected, missing = _candidate_value(candidate, value_key)
        if missing:
            missing_metadata.extend(missing)
            continue
        value_candidates.append(projected)

    values = [candidate["value"] for candidate in value_candidates]
    evidence_refs = _merge_evidence_refs(candidates)
    distinct_values_only = _distinct_ordered(values)
    distinct_candidates = _distinct_candidates(value_candidates)

    if missing_metadata:
        fields = ", ".join(_distinct_ordered(missing_metadata))
        return _unresolved(
            f"Candidate for {value_key} has missing metadata: {fields}.",
            evidence_refs,
            reason_code="partial_parser_coverage",
        )
    if not distinct_values_only:
        return _unresolved(missing_reason, missing_evidence_refs or evidence_refs)
    if len(distinct_values_only) == 1:
        candidate = distinct_candidates[0]
        return TrackedValue(
            state=FieldState.RESOLVED,
            value=candidate["value"],
            source=candidate["source"],
            confidence=candidate["confidence"],
            classification=candidate["classification"],
            evidence_refs=evidence_refs,
        )
    return TrackedValue(
        state=FieldState.CONFLICT,
        candidates=distinct_candidates,
        evidence_refs=evidence_refs,
        reason=conflict_reason,
    )


def _container_build_strategy(
    artifacts: LegacyAnalysisArtifacts,
    component_id: str | None = None,
    variant_id: str = "common",
) -> TrackedValue:
    del variant_id
    dockerfiles = [
        item
        for item in artifacts.artifact_inventory.get("container_files", [])
        if item.get("type") == "dockerfile" and item.get("present", True)
        and _path_belongs_to_component(artifacts, str(item.get("path", "")), component_id)
    ]
    if not dockerfiles:
        return _unresolved("No Dockerfile evidence was found.")

    evidence_refs = [
        fact["evidence_id"]
        for fact in artifacts.evidence_model.get("facts", [])
        if fact.get("fact_type") == "artifact_presence"
        and fact.get("value", {}).get("type") == "dockerfile"
        and fact.get("value", {}).get("present", True)
        and _fact_belongs_to_component(artifacts, fact, component_id)
    ]
    return TrackedValue(
        state=FieldState.RESOLVED,
        value="existing_dockerfile",
        source="artifact_inventory",
        confidence="high",
        classification="observed_fact",
        evidence_refs=evidence_refs,
    )


def _build_command(
    artifacts: LegacyAnalysisArtifacts,
    component_id: str | None = None,
    variant_id: str = "common",
) -> TrackedValue:
    build_command = _package_script_command(
        artifacts=artifacts,
        component_id=component_id,
        variant_id=variant_id,
        script_name="build",
        missing_reason="No build command evidence was found.",
        conflict_reason="Multiple build command candidates were found.",
    )
    unsupported_refs = _unsupported_artifact_evidence_refs(artifacts, bucket="build_files", component_id=component_id)
    if build_command.state == FieldState.UNRESOLVED and unsupported_refs:
        return _unresolved(
            "Unsupported build artifacts were discovered, so build command evidence may be incomplete.",
            unsupported_refs,
            reason_code="unsupported_artifact",
        )
    return build_command


def _runtime_port(
    artifacts: LegacyAnalysisArtifacts,
    component_id: str | None = None,
    variant_id: str = "common",
) -> TrackedValue:
    candidates = _candidates_for_scope(
        artifacts=artifacts,
        candidates=artifacts.rule_inference.get("runtime_port_candidates", []),
        component_id=component_id,
        variant_id=variant_id,
        aliases=_lifecycle_component_aliases(artifacts),
    )
    unresolved_refs, unresolved_details = _unresolved_compose_port_refs_and_details(
        artifacts,
        component_id=component_id,
        variant_id=variant_id,
    )
    if unresolved_refs:
        return _unresolved(
            "Compose port evidence contains unresolved interpolation, so no runtime port was inferred.",
            unresolved_refs,
            reason_code=_coverage_reason_code(unresolved_details),
        )
    return _tracked_from_candidates(
        candidates=candidates,
        value_key="port",
        missing_reason="No runtime port evidence was found.",
        conflict_reason="Multiple runtime port candidates were found.",
    )


def _container_entrypoint(
    artifacts: LegacyAnalysisArtifacts,
    component_id: str | None = None,
    variant_id: str = "common",
) -> TrackedValue:
    candidates = [
        {
            "entrypoint": fact["value"],
            "source": fact["source"],
            "confidence": "high",
            "classification": fact["classification"],
            "evidence_refs": [fact["evidence_id"]],
        }
        for fact in _facts_for_scope(
            artifacts,
            [
                fact
                for fact in artifacts.evidence_model.get("facts", [])
                if fact.get("fact_type") == "dockerfile_entrypoint"
            ],
            component_id=component_id,
            variant_id=variant_id,
        )
    ]
    return _tracked_from_candidates(
        candidates=candidates,
        value_key="entrypoint",
        missing_reason="No Dockerfile ENTRYPOINT evidence was found.",
        conflict_reason="Multiple Dockerfile ENTRYPOINT candidates were found.",
    )


def _package_script_command(
    artifacts: LegacyAnalysisArtifacts,
    component_id: str | None,
    variant_id: str,
    script_name: str,
    missing_reason: str,
    conflict_reason: str,
) -> TrackedValue:
    candidates = [
        {
            "command": fact["value"]["command"],
            "source": fact["source"],
            "confidence": "high",
            "classification": fact["classification"],
            "evidence_refs": [fact["evidence_id"]],
        }
        for fact in _facts_for_scope(
            artifacts,
            [
                fact
                for fact in artifacts.evidence_model.get("facts", [])
                if fact.get("fact_type") == "package_script"
                and isinstance(fact.get("value"), dict)
                and fact["value"].get("name") == script_name
                and fact["value"].get("command")
            ],
            component_id=component_id,
            variant_id=variant_id,
        )
    ]
    return _tracked_from_candidates(
        candidates=candidates,
        value_key="command",
        missing_reason=missing_reason,
        conflict_reason=conflict_reason,
    )


def _environment_variable_names(
    artifacts: LegacyAnalysisArtifacts,
    component_id: str | None = None,
) -> list[str]:
    names: list[str] = []
    for fact in artifacts.evidence_model.get("facts", []):
        if fact.get("fact_type") != "compose_environment" or not isinstance(fact.get("value"), dict):
            continue
        if not _compose_fact_belongs_to_component(artifacts, fact, component_id):
            continue
        name = fact["value"].get("name")
        if name:
            names.append(name)
    for fact in artifacts.evidence_model.get("facts", []):
        if fact.get("fact_type") != "dotnet_launch_environment" or not isinstance(fact.get("value"), dict):
            continue
        if not _fact_belongs_to_component(artifacts, fact, component_id):
            continue
        name = fact["value"].get("name")
        if name:
            names.append(name)

    env_classification = artifacts.rule_inference.get("env_classification", {})
    for candidates in env_classification.values():
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not _candidate_belongs_to_component(
                candidate,
                component_id,
                aliases=_lifecycle_component_aliases(artifacts),
            ):
                continue
            if isinstance(candidate, dict) and candidate.get("name"):
                names.append(candidate["name"])
    return _distinct_ordered(names)


def _external_dependencies(
    artifacts: LegacyAnalysisArtifacts,
    component_id: str | None = None,
) -> list[str]:
    return _distinct_ordered(
        [
            candidate["target"]
            for candidate in artifacts.rule_inference.get("dependency_edge_candidates", [])
            if candidate.get("target")
            and _candidate_belongs_to_component(
                candidate,
                component_id,
                aliases=_lifecycle_component_aliases(artifacts),
            )
        ]
    )


def _merge_evidence_refs(candidates: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for candidate in candidates:
        refs.extend(candidate.get("evidence_refs", []))
    return _distinct_ordered(refs)


def _candidate_value(candidate: dict[str, Any], value_key: str) -> tuple[dict[str, Any], list[str]]:
    missing: list[str] = []
    if value_key not in candidate or candidate[value_key] is None:
        missing.append(value_key)
    for key in ("source", "confidence", "classification"):
        if not candidate.get(key):
            missing.append(key)
    if not candidate.get("evidence_refs"):
        missing.append("evidence_refs")
    if missing:
        return {}, missing

    return (
        {
            "value": candidate[value_key],
            "source": candidate["source"],
            "confidence": candidate["confidence"],
            "classification": candidate["classification"],
            "evidence_refs": list(candidate["evidence_refs"]),
        },
        [],
    )


def _distinct_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for candidate in candidates:
        normalized = normalized_values([candidate])[0]
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(candidate)
    return result


def _distinct_ordered(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value, normalized in zip(values, normalized_values(values), strict=False):
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def _component_candidates(artifacts: LegacyAnalysisArtifacts) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for candidate in artifacts.rule_inference.get("component_candidates", []):
        if isinstance(candidate, dict) and isinstance(candidate.get("component_id"), str):
            candidates.append(candidate)
    return candidates


def _lifecycle_component_ids(artifacts: LegacyAnalysisArtifacts) -> list[str]:
    aliases = _lifecycle_component_aliases(artifacts)
    return [
        candidate["component_id"]
        for candidate in _component_candidates(artifacts)
        if candidate["component_id"] not in aliases
    ]


def _lifecycle_scopes(artifacts: LegacyAnalysisArtifacts) -> list[tuple[str | None, str]]:
    scopes: list[tuple[str | None, str]] = []
    aliases = _lifecycle_component_aliases(artifacts)
    candidates_with_variants = [
        *artifacts.rule_inference.get("runtime_command_candidates", []),
        *artifacts.rule_inference.get("runtime_port_candidates", []),
    ]
    for component_id in _lifecycle_component_ids(artifacts):
        variant_ids = {"common"}
        for candidate in candidates_with_variants:
            if _candidate_belongs_to_component(candidate, component_id, aliases=aliases):
                variant_ids.update(_candidate_variant_ids(artifacts, candidate))
        for variant_id in _sort_variant_ids(variant_ids):
            scopes.append((component_id, variant_id))
    return scopes


def _lifecycle_component_aliases(artifacts: LegacyAnalysisArtifacts) -> dict[str, str]:
    """Map image-only Compose app services to the sole source component.

    Older single-app fixtures often have a package root plus a Compose service
    with only ``image``/``ports``. Treat that service as deployment evidence for
    the package component, while dependency/infrastructure images stay separate.
    """
    candidates = _component_candidates(artifacts)
    rooted = [candidate for candidate in candidates if candidate.get("root_path") is not None]
    if len(rooted) != 1:
        return {}

    target_component_id = rooted[0]["component_id"]
    infrastructure_components = {
        candidate.get("component_id")
        for candidate in artifacts.rule_inference.get("role_candidates", [])
        if isinstance(candidate, dict) and candidate.get("role") in {"dependency", "infrastructure"}
    }
    aliases: dict[str, str] = {}
    for candidate in candidates:
        component_id = candidate["component_id"]
        if candidate.get("root_path") is not None:
            continue
        if candidate.get("source") != "compose_service":
            continue
        if component_id in infrastructure_components:
            continue
        aliases[component_id] = target_component_id
    return aliases


def _candidates_for_component(
    candidates: list[dict[str, Any]],
    component_id: str | None,
    aliases: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    return [
        candidate
        for candidate in candidates
        if _candidate_belongs_to_component(candidate, component_id, aliases=aliases)
    ]


def _candidates_for_scope(
    artifacts: LegacyAnalysisArtifacts,
    candidates: list[dict[str, Any]],
    component_id: str | None,
    variant_id: str,
    aliases: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    component_candidates = _candidates_for_component(candidates, component_id, aliases=aliases)
    if variant_id == "common":
        return [
            candidate
            for candidate in component_candidates
            if _candidate_variant_ids(artifacts, candidate) == ["common"]
        ]

    variant_candidates = [
        candidate
        for candidate in component_candidates
        if variant_id in _candidate_variant_ids(artifacts, candidate)
    ]
    if variant_candidates:
        return variant_candidates
    return [
        candidate
        for candidate in component_candidates
        if _candidate_variant_ids(artifacts, candidate) == ["common"]
    ]


def _candidate_belongs_to_component(
    candidate: dict[str, Any],
    component_id: str | None,
    aliases: dict[str, str] | None = None,
) -> bool:
    if component_id is None:
        return True
    aliases = aliases or {}
    for key in ("component_id", "source_component"):
        candidate_component = candidate.get(key)
        if candidate_component == component_id or aliases.get(str(candidate_component)) == component_id:
            return True
    return False


def _facts_for_scope(
    artifacts: LegacyAnalysisArtifacts,
    facts: list[dict[str, Any]],
    component_id: str | None,
    variant_id: str,
) -> list[dict[str, Any]]:
    component_facts = [
        fact
        for fact in facts
        if _fact_belongs_to_component(artifacts, fact, component_id)
    ]
    if variant_id == "common":
        return [fact for fact in component_facts if _fact_variant_id(fact) == "common"]

    variant_facts = [fact for fact in component_facts if _fact_variant_id(fact) == variant_id]
    if variant_facts:
        return variant_facts
    return [fact for fact in component_facts if _fact_variant_id(fact) == "common"]


def _fact_belongs_to_component(
    artifacts: LegacyAnalysisArtifacts,
    fact: dict[str, Any],
    component_id: str | None,
) -> bool:
    if component_id is None:
        return True
    artifact_ref = fact.get("artifact_ref")
    if not isinstance(artifact_ref, str):
        return False
    return _owning_component(artifacts, artifact_ref) == component_id


def _candidate_variant_ids(artifacts: LegacyAnalysisArtifacts, candidate: dict[str, Any]) -> list[str]:
    facts_by_id = _facts_by_evidence_id(artifacts)
    variant_ids: list[str] = []
    for evidence_ref in candidate.get("evidence_refs", []):
        fact = facts_by_id.get(str(evidence_ref))
        if fact is not None:
            variant_ids.append(_fact_variant_id(fact))
    return _distinct_ordered(variant_ids) or ["common"]


def _facts_by_evidence_id(artifacts: LegacyAnalysisArtifacts) -> dict[str, dict[str, Any]]:
    return {
        str(fact["evidence_id"]): fact
        for fact in artifacts.evidence_model.get("facts", [])
        if fact.get("evidence_id")
    }


def _fact_variant_id(fact: dict[str, Any]) -> str:
    artifact_ref = fact.get("artifact_ref")
    if not isinstance(artifact_ref, str):
        return "common"
    return _artifact_variant_id(artifact_ref)


def _artifact_variant_id(artifact_ref: str) -> str:
    name = Path(artifact_ref).name.lower()
    for suffix in (".properties", ".yaml", ".yml"):
        if name == f"application{suffix}":
            return "common"
        prefix = "application-"
        if name.startswith(prefix) and name.endswith(suffix):
            variant = name.removeprefix(prefix).removesuffix(suffix)
            return variant or "common"
    for prefix in ("docker-compose.", "compose."):
        if not name.startswith(prefix):
            continue
        suffix = name.removeprefix(prefix)
        if suffix.endswith(".yaml"):
            variant = suffix.removesuffix(".yaml")
        elif suffix.endswith(".yml"):
            variant = suffix.removesuffix(".yml")
        else:
            return "common"
        if variant and variant != "override":
            return variant
    return "common"


def _sort_variant_ids(variant_ids: set[str]) -> list[str]:
    return sorted(variant_ids, key=lambda value: (value != "common", value))


def _path_belongs_to_component(
    artifacts: LegacyAnalysisArtifacts,
    artifact_ref: str,
    component_id: str | None,
) -> bool:
    if component_id is None:
        return True
    return _owning_component(artifacts, artifact_ref) == component_id


def _compose_fact_belongs_to_component(
    artifacts: LegacyAnalysisArtifacts,
    fact: dict[str, Any],
    component_id: str | None,
) -> bool:
    if component_id is None:
        return True
    value = fact.get("value")
    if not isinstance(value, dict):
        return False
    service = value.get("service")
    aliases = _lifecycle_component_aliases(artifacts)
    if service == component_id or aliases.get(str(service)) == component_id:
        return True
    return _fact_belongs_to_component(artifacts, fact, component_id)


def _owning_component(artifacts: LegacyAnalysisArtifacts, artifact_ref: str) -> str | None:
    best_id: str | None = None
    best_specificity = -1
    for candidate in _component_candidates(artifacts):
        root_path = candidate.get("root_path")
        component_id = candidate.get("component_id")
        if not isinstance(component_id, str) or root_path is None:
            continue
        root = str(root_path)
        if root == ".":
            if "/" in artifact_ref:
                continue
            specificity = 0
        elif artifact_ref == root or artifact_ref.startswith(f"{root}/"):
            specificity = len(root)
        else:
            continue
        if specificity > best_specificity:
            best_id = component_id
            best_specificity = specificity
    return best_id


def _unresolved(
    reason: str,
    evidence_refs: list[str] | None = None,
    reason_code: str = "missing_evidence",
) -> TrackedValue:
    return TrackedValue(
        state=FieldState.UNRESOLVED,
        reason=reason,
        reason_code=reason_code,
        evidence_refs=evidence_refs or [],
    )


def _supported_fact_types() -> set[str]:
    return {
        "dockerfile_base_image",
        "dockerfile_expose",
        "dockerfile_cmd",
        "dockerfile_entrypoint",
        "dockerfile_user",
        "maven_packaging",
        "maven_module",
        "package_dependency",
        "package_script",
        "python_requirement_include",
        "python_direct_reference",
        "compose_service",
        "compose_image",
        "compose_build_context",
        "compose_depends_on",
        "compose_port",
        "compose_environment",
        "compose_volume",
        "dotnet_project_metadata",
        "dotnet_target_framework",
        "dotnet_package_reference",
        "dotnet_solution_project",
        "dotnet_build_property",
        "dotnet_launch_profile",
        "dotnet_launch_port",
        "dotnet_launch_environment",
        "dotnet_configuration_key",
        "dotnet_connection_string_name",
        "spring_configuration_key",
        "spring_application_name",
        "spring_server_port",
        "spring_dependency_hint",
        "kubernetes_resource",
        "kubernetes_service_port",
        "kubernetes_container_image",
        "kubernetes_container_port",
        "helm_chart_metadata",
        "parse_warning",
    }


def _facts_by_artifact_path(artifacts: LegacyAnalysisArtifacts) -> dict[str, list[dict[str, Any]]]:
    paths: dict[str, list[dict[str, Any]]] = {}
    for fact in artifacts.evidence_model.get("facts", []):
        paths.setdefault(str(fact.get("artifact_ref")), []).append(fact)
    return paths


def _has_supported_facts(facts: list[dict[str, Any]]) -> bool:
    supported_fact_types = _supported_fact_types()
    return any(fact.get("fact_type") in supported_fact_types for fact in facts)


def _warning_details_by_artifact_path(artifacts: LegacyAnalysisArtifacts) -> dict[str, list[str]]:
    details: dict[str, list[str]] = {}
    for fact in artifacts.evidence_model.get("facts", []):
        if fact.get("fact_type") == "parse_warning":
            path = str(fact.get("artifact_ref"))
            value = fact.get("value")
            if value is not None:
                details.setdefault(path, []).append(str(value))

    for warning in artifacts.evidence_model.get("warnings", []):
        parsed = _parse_warning_payload(warning)
        path = parsed.get("path")
        message = parsed.get("message")
        if path and message:
            details.setdefault(str(path), []).append(str(message))
    return details


def _parse_warning_payload(warning: Any) -> dict[str, Any]:
    if isinstance(warning, dict):
        return warning
    if not isinstance(warning, str):
        return {}
    try:
        parsed = json.loads(warning)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _unresolved_fact_details(facts: list[dict[str, Any]]) -> list[str]:
    return [warning for _, warning in _unresolved_facts(facts)]


def _unresolved_compose_port_refs_and_details(
    artifacts: LegacyAnalysisArtifacts,
    component_id: str | None = None,
    variant_id: str = "common",
) -> tuple[list[str], list[str]]:
    refs: list[str] = []
    details: list[str] = []
    component_facts = [
        fact
        for fact in artifacts.evidence_model.get("facts", [])
        if fact.get("fact_type") == "compose_port"
        and _compose_fact_belongs_to_component(artifacts, fact, component_id)
    ]
    if variant_id == "common":
        compose_port_facts = [fact for fact in component_facts if _fact_variant_id(fact) == "common"]
    else:
        variant_facts = [fact for fact in component_facts if _fact_variant_id(fact) == variant_id]
        compose_port_facts = variant_facts or [
            fact for fact in component_facts if _fact_variant_id(fact) == "common"
        ]
    for evidence_id, warning in _unresolved_facts(compose_port_facts):
        refs.append(evidence_id)
        details.append(warning)
    return _distinct_ordered(refs), _distinct_ordered(details)


def _unresolved_facts(facts: list[dict[str, Any]]) -> list[tuple[str, str]]:
    unresolved: list[tuple[str, str]] = []
    for fact in facts:
        value = fact.get("value")
        if not isinstance(value, dict):
            continue
        warning = value.get("warning")
        evidence_id = fact.get("evidence_id")
        if value.get("resolved") is False and warning and evidence_id:
            unresolved.append((str(evidence_id), str(warning)))
    return unresolved


def _coverage_reason_code(details: list[str]) -> str:
    text = " ".join(details).lower()
    if "unresolved interpolation" in text:
        return "unresolved_interpolation"
    if details:
        return "partial_parser_coverage"
    return "parsed"


def _is_supported_inventory_item(bucket: str, artifact_type: str) -> bool:
    return (bucket, artifact_type) in {
        ("build_files", "maven"),
        ("build_files", "nodejs"),
        ("build_files", "python_requirements"),
        ("build_files", "python_pyproject"),
        ("compose_files", "compose"),
        ("container_files", "dockerfile"),
        ("app_configs", "dotnet_appsettings"),
        ("app_configs", "dotnet_launch_settings"),
        ("app_configs", "application_yaml"),
        ("app_configs", "java_properties"),
        ("build_files", "dotnet_build_metadata"),
        ("build_files", "dotnet_project"),
        ("build_files", "dotnet_solution"),
        ("helm_charts", "helm_chart"),
        ("kubernetes_manifests", "kubernetes_manifest"),
    }


def _unsupported_artifact_evidence_refs(
    artifacts: LegacyAnalysisArtifacts,
    bucket: str,
    component_id: str | None = None,
) -> list[str]:
    paths = {
        str(item.get("path"))
        for item in artifacts.artifact_inventory.get(bucket, [])
        if isinstance(item, dict)
        and item.get("present", True)
        and not _is_supported_inventory_item(bucket, str(item.get("type", bucket)))
        and not _is_ignored_inventory_item(bucket, str(item.get("type", bucket)))
        and _path_belongs_to_component(artifacts, str(item.get("path", "")), component_id)
    }
    refs: list[str] = []
    for fact in artifacts.evidence_model.get("facts", []):
        if fact.get("fact_type") != "artifact_presence":
            continue
        value = fact.get("value")
        if not isinstance(value, dict) or str(value.get("path")) not in paths:
            continue
        if fact.get("evidence_id"):
            refs.append(str(fact["evidence_id"]))
    return _distinct_ordered(refs)


def _is_ignored_inventory_item(bucket: str, artifact_type: str) -> bool:
    return bucket == "docs" or artifact_type == "env"


def _ignored_reason_code(artifact_type: str) -> str:
    if artifact_type == "env":
        return "secret_safety"
    return "intentionally_ignored"


def _locator_for_fact(fact: dict[str, Any], index: int, compose_counts: dict[tuple[str, str, str], int]) -> str:
    value = fact.get("value")
    fact_type = fact.get("fact_type")
    if fact_type == "artifact_presence":
        if isinstance(value, dict) and value.get("present") is False:
            return "inventory:absent"
        return "inventory:present"
    if fact_type == "dockerfile_base_image":
        return "dockerfile:FROM"
    if fact_type == "dockerfile_expose":
        return f"dockerfile:EXPOSE[{index}]"
    if fact_type == "dockerfile_cmd":
        return "dockerfile:CMD"
    if fact_type == "dockerfile_entrypoint":
        return "dockerfile:ENTRYPOINT"
    if fact_type == "dockerfile_user":
        return "dockerfile:USER"
    if fact_type == "maven_packaging":
        return "xpath:/project/packaging"
    if fact_type == "maven_module":
        return f"xpath:/project/modules/module[{index}]"
    if fact_type == "package_dependency" and isinstance(value, dict):
        package = str(value.get("package", ""))
        if str(fact.get("artifact_ref", "")).endswith("package.json"):
            return f"jsonpath:$.dependencies.{package}"
        if str(fact.get("artifact_ref", "")).endswith("requirements.txt"):
            return f"requirement:{package}"
        return f"package:{package}"
    if fact_type == "package_script" and isinstance(value, dict):
        return f"jsonpath:$.scripts.{value.get('name', '')}"
    if fact_type == "python_requirement_include" and isinstance(value, dict):
        return f"requirement-include:{value.get('kind', '')}:{value.get('path', '')}"
    if fact_type == "python_direct_reference" and isinstance(value, dict):
        return f"direct-reference:{value.get('kind', '')}:{value.get('package', '')}"
    if fact_type == "dotnet_project_metadata" and isinstance(value, dict):
        return "xmlpath:/Project"
    if fact_type == "dotnet_target_framework" and isinstance(value, dict):
        return "xmlpath:/Project/PropertyGroup/TargetFramework"
    if fact_type == "dotnet_package_reference" and isinstance(value, dict):
        return f"xmlpath:/Project/ItemGroup/PackageReference[@Include='{value.get('package', '')}']"
    if fact_type == "dotnet_solution_project" and isinstance(value, dict):
        return f"sln:Project[{value.get('name', '')}]"
    if fact_type == "dotnet_build_property" and isinstance(value, dict):
        return f"xmlpath:/Project/PropertyGroup/{value.get('name', '')}"
    if fact_type == "dotnet_launch_profile" and isinstance(value, dict):
        return f"jsonpath:$.profiles.{value.get('profile', '')}"
    if fact_type == "dotnet_launch_port" and isinstance(value, dict):
        return f"jsonpath:$.profiles.{value.get('profile', '')}.applicationUrl"
    if fact_type == "dotnet_launch_environment" and isinstance(value, dict):
        return f"jsonpath:$.profiles.{value.get('profile', '')}.environmentVariables.{value.get('name', '')}"
    if fact_type == "dotnet_configuration_key" and isinstance(value, dict):
        return f"jsonpath:$.{str(value.get('key', '')).replace(':', '.')}"
    if fact_type == "dotnet_connection_string_name" and isinstance(value, dict):
        return f"jsonpath:$.ConnectionStrings.{value.get('name', '')}"
    if fact_type == "spring_configuration_key" and isinstance(value, dict):
        return f"config:{value.get('key', '')}"
    if fact_type == "spring_application_name":
        return "config:spring.application.name"
    if fact_type == "spring_server_port":
        return "config:server.port"
    if fact_type == "spring_dependency_hint" and isinstance(value, dict):
        return f"config:{value.get('key', '')}"
    if fact_type == "kubernetes_resource" and isinstance(value, dict):
        return f"yamlpath:{value.get('kind', 'Resource')}.{value.get('name', '')}.metadata"
    if fact_type == "kubernetes_service_port" and isinstance(value, dict):
        return f"yamlpath:Service.{value.get('name', '')}.spec.ports[{index}]"
    if fact_type == "kubernetes_container_image" and isinstance(value, dict):
        return (
            f"yamlpath:{value.get('workload', 'workload')}"
            f".containers.{value.get('container', '')}.image"
        )
    if fact_type == "kubernetes_container_port" and isinstance(value, dict):
        return (
            f"yamlpath:{value.get('workload', 'workload')}"
            f".containers.{value.get('container', '')}.ports[{index}]"
        )
    if fact_type == "helm_chart_metadata":
        return "yamlpath:$.name"
    if fact_type == "parse_warning":
        return f"parser-warning:{fact.get('source', 'parser')}[{index}]"
    if isinstance(fact_type, str) and fact_type.startswith("compose_") and isinstance(value, dict):
        return _compose_locator(str(fact.get("artifact_ref", "")), fact_type, value, compose_counts)
    return f"fact:{fact_type or 'unknown'}[{index}]"


def _compose_locator(
    artifact_ref: str,
    fact_type: str,
    value: dict[str, Any],
    compose_counts: dict[tuple[str, str, str], int],
) -> str:
    service = str(value.get("service", ""))
    if fact_type == "compose_service":
        return f"yamlpath:$.services.{service}"
    compose_key = {
        "compose_image": "image",
        "compose_build_context": "build",
        "compose_depends_on": "depends_on",
        "compose_port": "ports",
        "compose_environment": "environment",
        "compose_volume": "volumes",
    }.get(fact_type)
    if compose_key is None:
        return fact_type
    if compose_key in {"image", "build"}:
        return f"yamlpath:$.services.{service}.{compose_key}"
    key = (artifact_ref, service, compose_key)
    index = compose_counts.get(key, 0)
    compose_counts[key] = index + 1
    return f"yamlpath:$.services.{service}.{compose_key}[{index}]"
