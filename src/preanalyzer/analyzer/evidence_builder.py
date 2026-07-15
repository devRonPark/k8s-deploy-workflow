from __future__ import annotations

from typing import Any

from preanalyzer.analyzer.env_safety import build_env_fact
from preanalyzer.analyzer.parsers.compose import ParsedCompose
from preanalyzer.analyzer.parsers.dockerfile import ParsedDockerfile
from preanalyzer.analyzer.parsers.helm import ParsedHelmChart
from preanalyzer.analyzer.parsers.kubernetes import ParsedKubernetesManifest
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
        elif isinstance(parsed, ParsedKubernetesManifest):
            _append_kubernetes_facts(append, artifact_ref, parsed)
        elif isinstance(parsed, ParsedHelmChart):
            _append_helm_facts(append, artifact_ref, parsed)
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
            source = _python_source(artifact_ref)
            for dependency in parsed.dependencies:
                append("package_dependency", artifact_ref, source, {"package": dependency})
            for include in parsed.includes:
                append(
                    "python_requirement_include",
                    artifact_ref,
                    source,
                    {"kind": include.kind, "path": include.path},
                )
            for reference in parsed.direct_references:
                if reference.name is not None:
                    append(
                        "python_direct_reference",
                        artifact_ref,
                        source,
                        {"package": reference.name, "kind": reference.kind},
                    )

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
            append("compose_port", artifact_ref, "compose_ports", {"service": service.name, **port.model_dump()})
        for name, value in sorted(service.environment.items()):
            append("compose_environment", artifact_ref, "compose_environment", build_env_fact(service.name, name, value))
        for volume in service.volumes:
            append("compose_volume", artifact_ref, "compose_volumes", {"service": service.name, "volume": volume})
    for warning in parsed.warnings:
        append("parse_warning", artifact_ref, "compose_parser", warning)


def _append_kubernetes_facts(append, artifact_ref: str, parsed: ParsedKubernetesManifest) -> None:
    for resource in parsed.resources:
        append(
            "kubernetes_resource",
            artifact_ref,
            "kubernetes_manifest",
            {"kind": resource.kind, "name": resource.name, "labels": resource.labels},
        )
        for service_port in resource.service_ports:
            append(
                "kubernetes_service_port",
                artifact_ref,
                "kubernetes_manifest",
                {
                    "name": service_port.service,
                    "port": service_port.port,
                    "target_port": service_port.target_port,
                    "protocol": service_port.protocol,
                },
            )
        for container in resource.containers:
            if container.image is not None:
                append(
                    "kubernetes_container_image",
                    artifact_ref,
                    "kubernetes_manifest",
                    {
                        "workload": container.workload,
                        "container": container.name,
                        "image": container.image,
                    },
                )
            for port in container.ports:
                append(
                    "kubernetes_container_port",
                    artifact_ref,
                    "kubernetes_manifest",
                    {
                        "workload": container.workload,
                        "container": container.name,
                        "name": port.name,
                        "container_port": port.port,
                    },
                )


def _append_helm_facts(append, artifact_ref: str, parsed: ParsedHelmChart) -> None:
    append(
        "helm_chart_metadata",
        artifact_ref,
        "helm_chart",
        {
            "name": parsed.name,
            "version": parsed.version,
            "app_version": parsed.app_version,
            "chart_type": parsed.chart_type,
        },
    )


def _python_source(artifact_ref: str) -> str:
    if artifact_ref.endswith("requirements.txt"):
        return "requirements.txt"
    return "pyproject.toml"
