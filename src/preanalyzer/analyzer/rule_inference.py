from __future__ import annotations

from preanalyzer.models.evidence import EvidenceFact, EvidenceModel
from preanalyzer.models.rule_inference import (
    ComponentCandidate,
    EnvClassification,
    RoleCandidate,
    RuleInferenceSet,
    RuntimeCandidate,
    SecretCandidate,
)


DEPENDENCY_IMAGES = ("postgres", "mysql", "mariadb", "redis")
INFRA_IMAGES = ("traefik", "nginx")


def infer(evidence: EvidenceModel) -> RuleInferenceSet:
    compose_components = _component_candidates_from_compose(evidence)
    component_candidates = compose_components or _component_candidates_from_packages(evidence)
    root_by_component = {candidate.component_id: candidate.root_path for candidate in component_candidates}

    return RuleInferenceSet(
        component_candidates=component_candidates,
        role_candidates=_role_candidates(evidence),
        runtime_candidates=_runtime_candidates(evidence, component_candidates, root_by_component),
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


def _component_candidates_from_packages(evidence: EvidenceModel) -> list[ComponentCandidate]:
    package_facts = [
        fact
        for fact in evidence.facts
        if fact.fact_type in {"maven_packaging", "package_dependency", "package_script"}
    ]
    if not package_facts:
        return []
    first = package_facts[0]
    return [
        ComponentCandidate(
            component_id="root",
            root_path=".",
            source=_source_for_package_fact(first),
            evidence_refs=[first.evidence_id],
        )
    ]


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

    if maven_packaging:
        candidates.append(
            RuntimeCandidate(
                component_id="root",
                language="java",
                framework=None,
                build_tool="maven",
                build_strategy=_build_strategy_for("root", root_by_component, evidence),
                source="pom.xml",
                confidence="high",
                evidence_refs=[maven_packaging[0].evidence_id],
            )
        )

    for component in component_candidates:
        component_deps = [
            fact
            for fact in package_dependencies
            if _artifact_belongs_to_component(fact.artifact_ref, component.root_path)
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
        if fact.value.get("value_present") is True and _is_secret_name(name):
            candidates.append(SecretCandidate(fact.value["service"], name, fact.source, [fact.evidence_id]))
    return sorted(candidates, key=lambda candidate: (candidate.component_id, candidate.name))


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


def _artifact_belongs_to_component(artifact_ref: str, root_path: str | None) -> bool:
    if root_path in {None, "."}:
        return "/" not in artifact_ref
    return artifact_ref.startswith(f"{root_path}/")


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


def _is_secret_name(name: str) -> bool:
    upper = name.upper()
    return any(token in upper for token in ["PASSWORD", "SECRET", "TOKEN", "KEY", "CREDENTIAL", "PRIVATE"])
