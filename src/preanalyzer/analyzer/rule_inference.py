from __future__ import annotations

from preanalyzer.analyzer.env_safety import is_secret_name
from preanalyzer.models.evidence import EvidenceFact, EvidenceModel
from preanalyzer.models.rule_inference import (
    ComponentCandidate,
    DependencyEdgeCandidate,
    EnvClassification,
    RoleCandidate,
    RuleInferenceSet,
    RuntimeCandidate,
    RuntimeCommandCandidate,
    RuntimePortCandidate,
    RuntimeVersionCandidate,
    SecretCandidate,
)


DEPENDENCY_IMAGES = ("postgres", "mysql", "mariadb", "redis")
INFRA_IMAGES = ("traefik", "nginx")


def infer(evidence: EvidenceModel) -> RuleInferenceSet:
    compose_components = _component_candidates_from_compose(evidence)
    package_components = _component_candidates_from_packages(evidence)
    component_candidates = _reconcile_components(compose_components, package_components)
    root_by_component = {candidate.component_id: candidate.root_path for candidate in component_candidates}

    return RuleInferenceSet(
        component_candidates=component_candidates,
        role_candidates=_role_candidates(evidence),
        runtime_candidates=_runtime_candidates(evidence, component_candidates, root_by_component),
        runtime_version_candidates=_runtime_version_candidates(evidence, component_candidates),
        runtime_port_candidates=_runtime_port_candidates(evidence, component_candidates),
        runtime_command_candidates=_runtime_command_candidates(evidence, component_candidates),
        dependency_edge_candidates=_dependency_edge_candidates(evidence),
        env_classification=EnvClassification(secret_candidates=_secret_candidates(evidence)),
    )


def _component_candidates_from_compose(evidence: EvidenceModel) -> list[ComponentCandidate]:
    build_context_by_service = {
        fact.value["service"]: _normalize_root(fact.value["context"])
        for fact in evidence.facts_by_type("compose_build_context")
    }
    candidates = []
    for fact in evidence.facts_by_type("compose_service"):
        service = fact.value["service"]
        candidates.append(
            ComponentCandidate(
                component_id=service,
                root_path=build_context_by_service.get(service),
                source="compose_service",
                evidence_refs=[fact.evidence_id],
            )
        )
    return candidates


_PACKAGE_MANIFEST_FACTS = {
    "maven_packaging",
    "package_dependency",
    "package_script",
    "python_requirement_include",
    "python_direct_reference",
}


def _component_candidates_from_packages(evidence: EvidenceModel) -> list[ComponentCandidate]:
    """One component per package-manifest root (monorepo-aware).

    Manifests are grouped by their containing directory so that each npm
    workspace / Maven module / Python package becomes its own component
    instead of collapsing to a single ``root``. The first manifest fact in a
    root supplies the representative source and evidence ref.
    """
    by_root: dict[str, EvidenceFact] = {}
    for fact in evidence.facts:
        if fact.fact_type not in _PACKAGE_MANIFEST_FACTS:
            continue
        root = _artifact_root(fact.artifact_ref)
        if root not in by_root:  # first fact in deterministic evidence order wins
            by_root[root] = fact

    candidates: list[ComponentCandidate] = []
    for root, fact in by_root.items():
        candidates.append(
            ComponentCandidate(
                component_id=_component_id_for_root(root),
                root_path=root,
                source=_source_for_package_fact(fact),
                evidence_refs=[fact.evidence_id],
            )
        )
    return candidates


def _reconcile_components(
    compose_components: list[ComponentCandidate],
    package_components: list[ComponentCandidate],
) -> list[ComponentCandidate]:
    """Union compose and package components, dropping duplicates.

    A package component whose root is already claimed by a compose service's
    ``build.context`` is subsumed by that service (the compose component wins).
    Image-only compose services (``root_path is None``) claim no source root,
    so package components are never merged into them. Remaining package
    components — monorepo packages with no matching service — are kept.
    """
    claimed_roots = {c.root_path for c in compose_components if c.root_path is not None}
    reconciled = list(compose_components)
    existing_ids = {c.component_id for c in compose_components}
    for candidate in package_components:
        if candidate.root_path in claimed_roots:
            continue
        if candidate.component_id in existing_ids:
            continue
        reconciled.append(candidate)
        existing_ids.add(candidate.component_id)
    return sorted(reconciled, key=lambda c: c.component_id)


def _role_candidates(evidence: EvidenceModel) -> list[RoleCandidate]:
    candidates: list[RoleCandidate] = []
    for fact in evidence.facts_by_type("compose_build_context"):
        candidates.append(
            RoleCandidate(
                component_id=fact.value["service"],
                role="application",
                source="compose_build",
                confidence="medium",
                evidence_refs=[fact.evidence_id],
            )
        )
    for fact in evidence.facts_by_type("compose_image"):
        image = fact.value["image"].lower()
        service = fact.value["service"]
        if image.startswith(DEPENDENCY_IMAGES):
            candidates.append(
                RoleCandidate(service, "dependency", "infra_image_pattern", "high", [fact.evidence_id])
            )
        elif image.startswith(INFRA_IMAGES):
            candidates.append(
                RoleCandidate(service, "infrastructure", "infra_image_pattern", "high", [fact.evidence_id])
            )
    return sorted(candidates, key=lambda candidate: (candidate.component_id, candidate.role))


def _runtime_candidates(
    evidence: EvidenceModel,
    component_candidates: list[ComponentCandidate],
    root_by_component: dict[str, str | None],
) -> list[RuntimeCandidate]:
    candidates: list[RuntimeCandidate] = []
    package_dependencies = evidence.facts_by_type("package_dependency")
    maven_packaging = evidence.facts_by_type("maven_packaging")

    for fact in maven_packaging:
        component_id = _owning_component(fact.artifact_ref, component_candidates)
        if component_id is None:
            continue
        candidates.append(
            RuntimeCandidate(
                component_id=component_id,
                language="java",
                framework=None,
                build_tool="maven",
                build_strategy=_build_strategy_for(component_id, root_by_component, evidence),
                source="pom.xml",
                confidence="high",
                evidence_refs=[fact.evidence_id],
            )
        )

    for component in component_candidates:
        component_deps = [
            fact
            for fact in package_dependencies
            if _owning_component(fact.artifact_ref, component_candidates) == component.component_id
        ]
        if not component_deps:
            continue
        dep_names = {fact.value["package"].lower() for fact in component_deps}
        if "fastapi" in dep_names:
            candidates.append(
                RuntimeCandidate(
                    component.component_id,
                    "python",
                    "fastapi",
                    "pyproject",
                    _build_strategy_for(component.component_id, root_by_component, evidence),
                    "pyproject.toml",
                    "high",
                    [_fact_for_package(component_deps, "fastapi").evidence_id],
                )
            )
        elif "express" in dep_names:
            candidates.append(
                RuntimeCandidate(
                    component.component_id,
                    "nodejs",
                    "express",
                    "npm",
                    _build_strategy_for(component.component_id, root_by_component, evidence),
                    "package.json",
                    "high",
                    [_fact_for_package(component_deps, "express").evidence_id],
                )
            )
        elif {"react", "vite"} & dep_names:
            first = _fact_for_package(component_deps, "react") or _fact_for_package(component_deps, "vite")
            candidates.append(
                RuntimeCandidate(
                    component.component_id,
                    "nodejs",
                    "react" if "react" in dep_names else "vite",
                    "npm",
                    _build_strategy_for(component.component_id, root_by_component, evidence),
                    "package.json",
                    "high",
                    [first.evidence_id],
                )
            )
    return sorted(candidates, key=lambda candidate: candidate.component_id)


def _secret_candidates(evidence: EvidenceModel) -> list[SecretCandidate]:
    candidates = []
    for fact in evidence.facts_by_type("compose_environment"):
        name = fact.value["name"]
        present = fact.value.get("value_present") is True
        has_credentials = fact.value.get("contains_credentials") is True
        if (present and is_secret_name(name)) or has_credentials:
            candidates.append(SecretCandidate(fact.value["service"], name, fact.source, [fact.evidence_id]))
    return sorted(candidates, key=lambda candidate: (candidate.component_id, candidate.name))


def _runtime_version_candidates(
    evidence: EvidenceModel,
    component_candidates: list[ComponentCandidate],
) -> list[RuntimeVersionCandidate]:
    candidates: list[RuntimeVersionCandidate] = []
    for fact in evidence.facts_by_type("dockerfile_base_image"):
        component_id = _component_for_artifact(fact.artifact_ref, component_candidates)
        parsed = _runtime_from_image(str(fact.value))
        if component_id is not None and parsed is not None:
            language, version = parsed
            candidates.append(
                RuntimeVersionCandidate(component_id, language, version, fact.source, "high", [fact.evidence_id])
            )
    return sorted(candidates, key=lambda candidate: (candidate.component_id, candidate.language))


def _runtime_port_candidates(
    evidence: EvidenceModel,
    component_candidates: list[ComponentCandidate],
) -> list[RuntimePortCandidate]:
    candidates: list[RuntimePortCandidate] = []
    for fact in evidence.facts_by_type("dockerfile_expose"):
        component_id = _component_for_artifact(fact.artifact_ref, component_candidates)
        if component_id is not None:
            candidates.append(RuntimePortCandidate(component_id, int(fact.value), fact.source, "high", [fact.evidence_id]))
    return sorted(candidates, key=lambda candidate: (candidate.component_id, candidate.port))


def _runtime_command_candidates(
    evidence: EvidenceModel,
    component_candidates: list[ComponentCandidate],
) -> list[RuntimeCommandCandidate]:
    candidates: list[RuntimeCommandCandidate] = []
    for fact in evidence.facts_by_type("dockerfile_cmd"):
        component_id = _component_for_artifact(fact.artifact_ref, component_candidates)
        if component_id is not None:
            candidates.append(RuntimeCommandCandidate(component_id, str(fact.value), fact.source, "high", [fact.evidence_id]))
    return sorted(candidates, key=lambda candidate: candidate.component_id)


def _component_for_artifact(artifact_ref: str, component_candidates: list[ComponentCandidate]) -> str | None:
    return _owning_component(artifact_ref, component_candidates)


def _owning_component(artifact_ref: str, component_candidates: list[ComponentCandidate]) -> str | None:
    """Return the component that owns ``artifact_ref`` by longest-prefix root.

    Image-only components (``root_path is None``) own nothing. A ``"."`` root
    owns only top-level files; a nested root owns files beneath it. When roots
    are nested, the longest matching root wins so an artifact is attributed to
    the most specific component.
    """
    best_id: str | None = None
    best_specificity = -1
    for candidate in component_candidates:
        root_path = candidate.root_path
        if root_path is None:
            continue
        if root_path == ".":
            specificity = 0
            if "/" in artifact_ref:
                continue
        elif artifact_ref == root_path or artifact_ref.startswith(f"{root_path}/"):
            specificity = len(root_path)
        else:
            continue
        if specificity > best_specificity:
            best_id = candidate.component_id
            best_specificity = specificity
    return best_id


def _artifact_root(artifact_ref: str) -> str:
    parent = artifact_ref.rsplit("/", 1)[0] if "/" in artifact_ref else "."
    return parent or "."


def _component_id_for_root(root: str) -> str:
    if root in {".", ""}:
        return "root"
    return root


def _runtime_from_image(image: str) -> tuple[str, str] | None:
    repository, _, tag = image.partition(":")
    if not tag:
        return None
    language = {
        "python": "python",
        "node": "nodejs",
        "eclipse-temurin": "java",
        "openjdk": "java",
    }.get(repository.split("/")[-1])
    if language is None:
        return None
    version = tag.split("-", 1)[0]
    if version:
        return language, version
    return None


def _build_strategy_for(component_id: str, root_by_component: dict[str, str | None], evidence: EvidenceModel) -> str:
    root_path = root_by_component.get(component_id)
    for fact in evidence.facts_by_type("artifact_presence"):
        if fact.value["type"] != "dockerfile" or not fact.value["present"]:
            continue
        if root_path in {None, "."} and fact.artifact_ref == "Dockerfile":
            return "dockerfile"
        if root_path and fact.artifact_ref == f"{root_path}/Dockerfile":
            return "dockerfile"
    return "dockerfile_needed"


def _fact_for_package(facts: list[EvidenceFact], package_name: str) -> EvidenceFact | None:
    for fact in facts:
        if fact.value["package"].lower() == package_name:
            return fact
    return None


def _normalize_root(value: str) -> str:
    return value.removeprefix("./").rstrip("/") or "."


def _source_for_package_fact(fact: EvidenceFact) -> str:
    if fact.fact_type == "maven_packaging":
        return "pom.xml"
    return fact.source


def _dependency_edge_candidates(evidence: EvidenceModel) -> list[DependencyEdgeCandidate]:
    candidates: list[DependencyEdgeCandidate] = []
    compose_services = {fact.value["service"] for fact in evidence.facts_by_type("compose_service")}
    for fact in evidence.facts_by_type("compose_depends_on"):
        candidates.append(
            DependencyEdgeCandidate(
                source_component=fact.value["service"],
                target=fact.value["depends_on"],
                dependency_type="internal",
                source=fact.source,
                confidence="high",
                evidence_refs=[fact.evidence_id],
            )
        )
    for fact in evidence.facts_by_type("compose_environment"):
        name = fact.value["name"]
        if name.upper().endswith("DATABASE_URL"):
            target = _database_target(fact.value.get("sanitized"), compose_services)
            if target is not None:
                candidates.append(
                    DependencyEdgeCandidate(
                        source_component=fact.value["service"],
                        target=target,
                        dependency_type="database",
                        source=fact.source,
                        confidence="medium",
                        evidence_refs=[fact.evidence_id],
                    )
                )
    return sorted(candidates, key=lambda c: (c.source_component, c.target, c.dependency_type))


def _database_target(sanitized: object, compose_services: set[str]) -> str | None:
    if not isinstance(sanitized, dict):
        return None
    host = sanitized.get("host")
    if isinstance(host, str) and host in compose_services:
        return host
    return None
