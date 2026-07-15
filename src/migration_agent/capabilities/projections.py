from __future__ import annotations

from pathlib import Path
from typing import Any

from migration_agent.adapters.models import LegacyAnalysisArtifacts
from migration_agent.domain.common import FieldState, TrackedValue, distinct_values
from migration_agent.domain.lifecycle import LifecycleModel, LifecycleVariant
from migration_agent.domain.repository import RepositoryIdentity
from migration_agent.domain.topology import ApplicationComponent, ApplicationTopology
from migration_agent.domain.understanding import (
    ConfirmedFact,
    ConflictFinding,
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
    return [
        EvidenceRef(
            evidence_id=fact["evidence_id"],
            artifact_ref=fact["artifact_ref"],
            fact_type=fact["fact_type"],
            source=fact["source"],
            classification=fact["classification"],
        )
        for fact in artifacts.evidence_model.get("facts", [])
    ]


def project_topology(artifacts: LegacyAnalysisArtifacts) -> ApplicationTopology:
    rules = artifacts.rule_inference
    roles_by_component = {
        candidate["component_id"]: candidate["role"]
        for candidate in rules.get("role_candidates", [])
    }
    dependencies_by_component: dict[str, list[str]] = {}
    for candidate in rules.get("dependency_edge_candidates", []):
        dependencies_by_component.setdefault(candidate["source_component"], []).append(candidate["target"])

    components = [
        ApplicationComponent(
            component_id=candidate["component_id"],
            root_path=candidate.get("root_path"),
            role=roles_by_component.get(candidate["component_id"], "application"),
            evidence_refs=list(candidate.get("evidence_refs", [])),
            dependencies=dependencies_by_component.get(candidate["component_id"], []),
        )
        for candidate in rules.get("component_candidates", [])
    ]

    return ApplicationTopology(components=components)


def project_lifecycle(artifacts: LegacyAnalysisArtifacts) -> LifecycleModel:
    build_command = _package_script_command(
        artifacts=artifacts,
        script_name="build",
        missing_reason="No build command evidence was found.",
        conflict_reason="Multiple build command candidates were found.",
    )
    runtime_command = _tracked_from_candidates(
        candidates=artifacts.rule_inference.get("runtime_command_candidates", []),
        value_key="command",
        missing_reason="No runtime command evidence was found.",
        conflict_reason="Multiple runtime command candidates were found.",
    )
    runtime_port = _tracked_from_candidates(
        candidates=artifacts.rule_inference.get("runtime_port_candidates", []),
        value_key="port",
        missing_reason="No runtime port evidence was found.",
        conflict_reason="Multiple runtime port candidates were found.",
    )
    container_strategy = _container_build_strategy(artifacts)

    return LifecycleModel(
        variants=[
            LifecycleVariant(
                build_command=build_command,
                package_command=_unresolved("No package command evidence was found."),
                run_command=runtime_command,
                runtime_port=runtime_port,
                environment_variable_names=_environment_variable_names(artifacts),
                external_dependencies=_external_dependencies(artifacts),
                container_build_strategy=container_strategy,
                container_entrypoint=_container_entrypoint(artifacts),
            )
        ]
    )


def project_findings(
    lifecycle: LifecycleModel,
    topology: ApplicationTopology,
) -> tuple[list[ConfirmedFact], list[UnknownFinding], list[ConflictFinding]]:
    confirmed_facts: list[ConfirmedFact] = []
    unknowns: list[UnknownFinding] = []
    conflicts: list[ConflictFinding] = []

    variant = lifecycle.variants[0]
    tracked_fields = {
        "lifecycle.variants[0].build_command": variant.build_command,
        "lifecycle.variants[0].package_command": variant.package_command,
        "lifecycle.variants[0].run_command": variant.run_command,
        "lifecycle.variants[0].runtime_port": variant.runtime_port,
        "lifecycle.variants[0].container_build_strategy": variant.container_build_strategy,
        "lifecycle.variants[0].container_entrypoint": variant.container_entrypoint,
    }

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
    supported_keys = {"build_files", "container_files", "compose_files"}
    analyzed_artifacts = 0
    supported_artifacts = 0
    unsupported_artifacts: list[str] = []

    for key, value in inventory.items():
        if not isinstance(value, list):
            continue
        analyzed_artifacts += len(value)
        if key in supported_keys:
            supported_artifacts += len(value)
        elif value:
            unsupported_artifacts.extend(item.get("path", key) for item in value if isinstance(item, dict))

    return UnderstandingCoverage(
        analyzed_artifacts=analyzed_artifacts,
        supported_artifacts=supported_artifacts,
        unsupported_artifacts=unsupported_artifacts,
    )


def _tracked_from_candidates(
    candidates: list[dict[str, Any]],
    value_key: str,
    missing_reason: str,
    conflict_reason: str,
) -> TrackedValue:
    value_candidates = [_candidate_value(candidate, value_key) for candidate in candidates if value_key in candidate]
    values = [candidate["value"] for candidate in value_candidates]
    evidence_refs = _merge_evidence_refs(candidates)
    distinct_values_only = _distinct_ordered(values)
    distinct_candidates = _distinct_candidates(value_candidates)

    if not distinct_values_only:
        return _unresolved(missing_reason)
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


def _container_build_strategy(artifacts: LegacyAnalysisArtifacts) -> TrackedValue:
    dockerfiles = [
        item
        for item in artifacts.artifact_inventory.get("container_files", [])
        if item.get("type") == "dockerfile" and item.get("present", True)
    ]
    if not dockerfiles:
        return _unresolved("No Dockerfile evidence was found.")

    evidence_refs = [
        fact["evidence_id"]
        for fact in artifacts.evidence_model.get("facts", [])
        if fact.get("fact_type") == "artifact_presence"
        and fact.get("value", {}).get("type") == "dockerfile"
        and fact.get("value", {}).get("present", True)
    ]
    return TrackedValue(
        state=FieldState.RESOLVED,
        value="existing_dockerfile",
        source="artifact_inventory",
        confidence="high",
        classification="observed_fact",
        evidence_refs=evidence_refs,
    )


def _container_entrypoint(artifacts: LegacyAnalysisArtifacts) -> TrackedValue:
    candidates = [
        {
            "entrypoint": fact["value"],
            "source": fact["source"],
            "confidence": "high",
            "classification": fact["classification"],
            "evidence_refs": [fact["evidence_id"]],
        }
        for fact in artifacts.evidence_model.get("facts", [])
        if fact.get("fact_type") == "dockerfile_entrypoint"
    ]
    return _tracked_from_candidates(
        candidates=candidates,
        value_key="entrypoint",
        missing_reason="No Dockerfile ENTRYPOINT evidence was found.",
        conflict_reason="Multiple Dockerfile ENTRYPOINT candidates were found.",
    )


def _package_script_command(
    artifacts: LegacyAnalysisArtifacts,
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
        for fact in artifacts.evidence_model.get("facts", [])
        if fact.get("fact_type") == "package_script"
        and isinstance(fact.get("value"), dict)
        and fact["value"].get("name") == script_name
        and fact["value"].get("command")
    ]
    return _tracked_from_candidates(
        candidates=candidates,
        value_key="command",
        missing_reason=missing_reason,
        conflict_reason=conflict_reason,
    )


def _environment_variable_names(artifacts: LegacyAnalysisArtifacts) -> list[str]:
    names: list[str] = []
    env_classification = artifacts.rule_inference.get("env_classification", {})
    for candidates in env_classification.values():
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("name"):
                names.append(candidate["name"])
    return _distinct_ordered(names)


def _external_dependencies(artifacts: LegacyAnalysisArtifacts) -> list[str]:
    return _distinct_ordered(
        [
            candidate["target"]
            for candidate in artifacts.rule_inference.get("dependency_edge_candidates", [])
            if candidate.get("target")
        ]
    )


def _merge_evidence_refs(candidates: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for candidate in candidates:
        refs.extend(candidate.get("evidence_refs", []))
    return _distinct_ordered(refs)


def _candidate_value(candidate: dict[str, Any], value_key: str) -> dict[str, Any]:
    return {
        "value": candidate[value_key],
        "source": candidate.get("source", "unknown"),
        "confidence": candidate.get("confidence", "high"),
        "classification": candidate.get("classification", "observed_fact"),
        "evidence_refs": list(candidate.get("evidence_refs", [])),
    }


def _distinct_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for candidate in candidates:
        normalized = distinct_values([candidate["value"]])[0]
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(candidate)
    return result


def _distinct_ordered(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value, normalized in zip(values, distinct_values(values), strict=False):
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def _unresolved(reason: str) -> TrackedValue:
    return TrackedValue(state=FieldState.UNRESOLVED, reason=reason)
