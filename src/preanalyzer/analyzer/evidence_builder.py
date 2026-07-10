from __future__ import annotations

from typing import Any

from preanalyzer.analyzer.parsers.compose import ParsedCompose
from preanalyzer.analyzer.parsers.dockerfile import ParsedDockerfile
from preanalyzer.analyzer.parsers.maven import ParsedMaven
from preanalyzer.analyzer.parsers.nodejs import ParsedNodePackage
from preanalyzer.analyzer.parsers.python_pkg import ParsedPythonPackage
from preanalyzer.models.evidence import EvidenceFact, EvidenceModel
from preanalyzer.models.inventory import ArtifactInventory, ArtifactItem


def build(inventory: ArtifactInventory, parsed_artifacts: dict[str, object]) -> EvidenceModel:
    facts: list[EvidenceFact] = []

    def append(fact_type: str, artifact_ref: str, source: str, value: Any) -> None:
        facts.append(
            EvidenceFact(
                evidence_id=f"F{len(facts) + 1:04d}",
                fact_type=fact_type,
                artifact_ref=artifact_ref,
                source=source,
                classification="observed_fact",
                value=value,
            )
        )

    for item in _inventory_items(inventory):
        present = bool(item.get("present", True))
        append(
            "artifact_presence",
            str(item["path"]),
            "artifact_inventory",
            {"path": item["path"], "type": item.get("type", "unknown"), "present": present},
        )

    for artifact_ref, parsed in sorted(parsed_artifacts.items()):
        if isinstance(parsed, ParsedDockerfile):
            _append_dockerfile_facts(append, artifact_ref, parsed)
        elif isinstance(parsed, ParsedCompose):
            _append_compose_facts(append, artifact_ref, parsed)
        elif isinstance(parsed, ParsedMaven):
            append("maven_packaging", artifact_ref, "pom.xml", parsed.packaging.value)
            for module in parsed.modules:
                append("maven_module", artifact_ref, "pom.xml", module)
        elif isinstance(parsed, ParsedNodePackage):
            for dependency in parsed.dependencies:
                append("package_dependency", artifact_ref, "package.json", {"package": dependency})
            for name, command in sorted(parsed.scripts.items()):
                append("package_script", artifact_ref, "package.json", {"name": name, "command": command})
        elif isinstance(parsed, ParsedPythonPackage):
            for dependency in parsed.dependencies:
                append("package_dependency", artifact_ref, _python_source(artifact_ref), {"package": dependency})

    return EvidenceModel(facts=facts)


def _inventory_items(inventory: ArtifactInventory) -> list[ArtifactItem]:
    items: list[ArtifactItem] = []
    items.extend(inventory.build_files)
    items.extend(inventory.container_files)
    items.extend(inventory.compose_files)
    items.extend(inventory.kubernetes_manifests)
    items.extend(inventory.helm_charts)
    items.extend(inventory.kustomize_dirs)
    items.extend(inventory.ci_cd)
    items.extend(inventory.app_configs)
    items.extend(inventory.docs)
    return sorted(items, key=lambda item: str(item["path"]))


def _append_dockerfile_facts(append, artifact_ref: str, parsed: ParsedDockerfile) -> None:
    if parsed.base_image is not None:
        append("dockerfile_base_image", artifact_ref, parsed.base_image.source, parsed.base_image.value)
    for port in parsed.expose_ports:
        append("dockerfile_expose", artifact_ref, port.source, port.value)
    if parsed.cmd is not None:
        append("dockerfile_cmd", artifact_ref, parsed.cmd.source, parsed.cmd.value)
    if parsed.entrypoint is not None:
        append("dockerfile_entrypoint", artifact_ref, parsed.entrypoint.source, parsed.entrypoint.value)
    if parsed.user is not None:
        append("dockerfile_user", artifact_ref, parsed.user.source, parsed.user.value)


def _append_compose_facts(append, artifact_ref: str, parsed: ParsedCompose) -> None:
    for service in parsed.services:
        append("compose_service", artifact_ref, "compose_service", {"service": service.name})
        if service.image is not None:
            append("compose_image", artifact_ref, "compose_image", {"service": service.name, "image": service.image})
        if service.build_context is not None:
            append(
                "compose_build_context",
                artifact_ref,
                "compose_build",
                {"service": service.name, "context": service.build_context},
            )
        for depends_on in service.depends_on:
            append(
                "compose_depends_on",
                artifact_ref,
                "compose_depends_on",
                {"service": service.name, "depends_on": depends_on},
            )
        for port in service.ports:
            append("compose_port", artifact_ref, port.source, {"service": service.name, **port.model_dump()})
        for name, value in sorted(service.environment.items()):
            append("compose_environment", artifact_ref, "compose_environment", _safe_env_fact(service.name, name, value))
        for volume in service.volumes:
            append("compose_volume", artifact_ref, "compose_volumes", {"service": service.name, "volume": volume})
    for warning in parsed.warnings:
        append("parse_warning", artifact_ref, "compose_parser", warning)


def _safe_env_fact(service_name: str, name: str, value: str) -> dict[str, str | bool]:
    if _is_secret_name(name):
        return {"service": service_name, "name": name, "value_present": bool(value)}
    return {"service": service_name, "name": name, "value": value}


def _is_secret_name(name: str) -> bool:
    upper = name.upper()
    return any(token in upper for token in ["PASSWORD", "SECRET", "TOKEN", "KEY", "CREDENTIAL", "PRIVATE"])


def _python_source(artifact_ref: str) -> str:
    if artifact_ref.endswith("requirements.txt"):
        return "requirements.txt"
    return "pyproject.toml"
