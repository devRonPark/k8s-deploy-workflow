from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from preanalyzer.analyzer.parsers.result import (
    CODE_INVALID_ENCODING,
    CODE_INVALID_YAML,
    CODE_READ_ERROR,
    ParseWarning,
)


@dataclass(frozen=True)
class KubernetesContainerPort:
    name: str | None
    port: int


@dataclass(frozen=True)
class KubernetesContainer:
    workload: str
    name: str
    image: str | None
    ports: list[KubernetesContainerPort] = field(default_factory=list)


@dataclass(frozen=True)
class KubernetesServicePort:
    service: str
    port: int | None
    target_port: int | str | None
    protocol: str | None


@dataclass(frozen=True)
class KubernetesResource:
    kind: str
    name: str
    labels: dict[str, str] = field(default_factory=dict)
    pod_labels: dict[str, str] = field(default_factory=dict)
    selector: dict[str, str] = field(default_factory=dict)
    containers: list[KubernetesContainer] = field(default_factory=list)
    service_ports: list[KubernetesServicePort] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedKubernetesManifest:
    path: str
    resources: list[KubernetesResource]


def parse(path: Path) -> ParsedKubernetesManifest:
    documents = yaml.safe_load_all(path.read_text(encoding="utf-8"))
    resources = [
        resource
        for document in documents
        if isinstance(document, dict)
        for resource in [_parse_resource(document)]
        if resource is not None
    ]
    return ParsedKubernetesManifest(path=path.as_posix(), resources=resources)


def try_parse(path: Path) -> ParsedKubernetesManifest | ParseWarning:
    try:
        return parse(path)
    except yaml.YAMLError as exc:
        message = getattr(exc, "problem", None) or "YAML parsing failed"
        return ParseWarning(path=str(path), parser="kubernetes", message=str(message), code=CODE_INVALID_YAML)
    except UnicodeDecodeError:
        return ParseWarning(path=str(path), parser="kubernetes", message="invalid text encoding", code=CODE_INVALID_ENCODING)
    except OSError as exc:
        return ParseWarning(path=str(path), parser="kubernetes", message=exc.strerror or "read error", code=CODE_READ_ERROR)


def _parse_resource(document: dict[str, Any]) -> KubernetesResource | None:
    kind = document.get("kind")
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    name = metadata.get("name")
    if not isinstance(kind, str) or not isinstance(name, str) or not name:
        return None

    return KubernetesResource(
        kind=kind,
        name=name,
        labels=_string_map(metadata.get("labels")),
        pod_labels=_pod_labels(document, kind, metadata),
        selector=_service_selector(document, kind),
        containers=_containers(document, kind, name),
        service_ports=_service_ports(document, kind, name),
    )


def _containers(document: dict[str, Any], kind: str, workload: str) -> list[KubernetesContainer]:
    workload_kinds = {
        "CronJob",
        "DaemonSet",
        "Deployment",
        "Job",
        "Pod",
        "ReplicaSet",
        "ReplicationController",
        "StatefulSet",
    }
    if kind not in workload_kinds:
        return []
    pod_spec = _pod_spec(document, kind)
    raw_containers = pod_spec.get("containers") if isinstance(pod_spec, dict) else []
    containers: list[KubernetesContainer] = []
    for raw in raw_containers if isinstance(raw_containers, list) else []:
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
            continue
        containers.append(
            KubernetesContainer(
                workload=workload,
                name=raw["name"],
                image=raw.get("image") if isinstance(raw.get("image"), str) else None,
                ports=_container_ports(raw),
            )
        )
    return containers


def _pod_spec(document: dict[str, Any], kind: str) -> dict[str, Any]:
    spec = document.get("spec") if isinstance(document.get("spec"), dict) else {}
    if kind == "Pod":
        return spec
    if kind == "CronJob":
        job_template = spec.get("jobTemplate")
        job_spec = job_template.get("spec") if isinstance(job_template, dict) else {}
        template = job_spec.get("template") if isinstance(job_spec, dict) else {}
    else:
        template = spec.get("template", {})
    if not isinstance(template, dict):
        return {}
    pod_spec = template.get("spec")
    return pod_spec if isinstance(pod_spec, dict) else {}


def _pod_labels(document: dict[str, Any], kind: str, metadata: dict[str, Any]) -> dict[str, str]:
    if kind == "Pod":
        return _string_map(metadata.get("labels"))
    spec = document.get("spec") if isinstance(document.get("spec"), dict) else {}
    if kind == "CronJob":
        job_template = spec.get("jobTemplate")
        job_spec = job_template.get("spec") if isinstance(job_template, dict) else {}
        template = job_spec.get("template") if isinstance(job_spec, dict) else {}
    else:
        template = spec.get("template", {})
    if not isinstance(template, dict):
        return {}
    template_metadata = template.get("metadata")
    if not isinstance(template_metadata, dict):
        return {}
    return _string_map(template_metadata.get("labels"))


def _service_selector(document: dict[str, Any], kind: str) -> dict[str, str]:
    if kind != "Service":
        return {}
    spec = document.get("spec") if isinstance(document.get("spec"), dict) else {}
    return _string_map(spec.get("selector"))


def _container_ports(raw_container: dict[str, Any]) -> list[KubernetesContainerPort]:
    ports: list[KubernetesContainerPort] = []
    for raw in raw_container.get("ports") or []:
        if isinstance(raw, dict) and isinstance(raw.get("containerPort"), int):
            name = raw.get("name")
            ports.append(
                KubernetesContainerPort(
                    name=name if isinstance(name, str) and name else None,
                    port=raw["containerPort"],
                )
            )
    return ports


def _service_ports(document: dict[str, Any], kind: str, service: str) -> list[KubernetesServicePort]:
    if kind != "Service":
        return []
    spec = document.get("spec") if isinstance(document.get("spec"), dict) else {}
    ports: list[KubernetesServicePort] = []
    for raw in spec.get("ports") or []:
        if not isinstance(raw, dict):
            continue
        port = raw.get("port")
        target_port = raw.get("targetPort")
        ports.append(
            KubernetesServicePort(
                service=service,
                port=port if isinstance(port, int) else None,
                target_port=target_port if isinstance(target_port, (int, str)) else None,
                protocol=raw.get("protocol") if isinstance(raw.get("protocol"), str) else None,
            )
        )
    return ports


def _string_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if value is not None}
