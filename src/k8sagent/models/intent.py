from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

from k8sagent.errors import ChangeSetError
from k8sagent.models.topology import ApplicationTopology
from preanalyzer.models.fields import Confidence, Tracked
from preanalyzer.models.intent import KubernetesIntent

_CID = r"[a-z0-9]([-a-z0-9]*[a-z0-9])?"
_ENV = r"[A-Za-z_][A-Za-z0-9_]*"

INTENT_PATHS = [
    re.compile(r"^namespace$"),
    re.compile(r"^create_namespace$"),
    re.compile(rf"^components\.({_CID})\.workload\.image\.registry$"),
    re.compile(rf"^components\.({_CID})\.workload\.image\.name$"),
    re.compile(rf"^components\.({_CID})\.workload\.image\.tag$"),
    re.compile(rf"^components\.({_CID})\.workload\.replicas$"),
    re.compile(rf"^components\.({_CID})\.workload\.container_port$"),
    re.compile(rf"^components\.({_CID})\.workload\.command$"),
    re.compile(rf"^components\.({_CID})\.service\.port$"),
    re.compile(rf"^components\.({_CID})\.ingress\.host$"),
    re.compile(rf"^components\.({_CID})\.ingress\.path$"),
    re.compile(rf"^components\.({_CID})\.configmap\.({_ENV})$"),
    re.compile(rf"^components\.({_CID})\.secret_refs\.({_ENV})\.secret_name$"),
    re.compile(rf"^components\.({_CID})\.secret_refs\.({_ENV})\.secret_key$"),
    re.compile(rf"^components\.({_CID})\.pvc\.size$"),
    re.compile(rf"^components\.({_CID})\.pvc\.storage_class$"),
    re.compile(rf"^components\.({_CID})\.pvc\.mount_path$"),
]

_RFC1123 = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
_HOST = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$")
_REGISTRY = re.compile(r"^[a-z0-9.-]+(:[0-9]{1,5})?(/[a-z0-9._/-]+)?$")
_TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")
_QTY = re.compile(r"^[1-9][0-9]*(Gi|Mi)$")
_SECRET_KEY = re.compile(r"^[-._a-zA-Z0-9]+$")


class ImageSpec(BaseModel):
    registry: Tracked[str] | None = None
    name: Tracked[str] | None = None
    tag: Tracked[str] | None = None


class WorkloadSpec(BaseModel):
    image: ImageSpec = Field(default_factory=ImageSpec)
    replicas: Tracked[int] | None = None
    container_port: Tracked[int] | None = None
    command: Tracked[str] | None = None


class ServiceSpec(BaseModel):
    port: Tracked[int] | None = None


class IngressSpec(BaseModel):
    host: Tracked[str] | None = None
    path: Tracked[str] | None = None


class SecretRefSpec(BaseModel):
    env_name: str
    secret_name: Tracked[str] | None = None
    secret_key: Tracked[str] | None = None

    @field_validator("env_name")
    @classmethod
    def _valid_env_name(cls, value: str) -> str:
        if not re.match(rf"^{_ENV}$", value):
            raise ValueError("invalid environment variable name")
        return value


class PVCSpec(BaseModel):
    size: Tracked[str] | None = None
    storage_class: Tracked[str] | None = None
    mount_path: Tracked[str] | None = None


class ComponentIntentSpec(BaseModel):
    component_id: str
    role: str
    workload: WorkloadSpec = Field(default_factory=WorkloadSpec)
    service: ServiceSpec | None = None
    configmap: dict[str, Tracked[str]] = Field(default_factory=dict)
    secret_refs: list[SecretRefSpec] = Field(default_factory=list)
    ingress: IngressSpec | None = None
    pvc: PVCSpec | None = None


class AgentKubernetesIntent(BaseModel):
    namespace: Tracked[str] | None = None
    create_namespace: bool = True
    components: list[ComponentIntentSpec] = Field(default_factory=list)


def build_intent(
    topology: ApplicationTopology,
    baseline: KubernetesIntent,
) -> AgentKubernetesIntent:
    baseline_components = {component.component_id: component for component in baseline.components}
    components: list[ComponentIntentSpec] = []
    for item in topology.components:
        base = baseline_components.get(item.component_id)
        workload = WorkloadSpec()
        service = None
        configmap: dict[str, Tracked[str]] = {}
        secret_refs: list[SecretRefSpec] = []

        if item.role == "application":
            if base is not None and base.workload is not None:
                workload.image.name = base.workload.image_name
                workload.container_port = base.workload.port
                workload.command = base.workload.command
                config_env = base.workload.config_env
                secret_env = base.workload.secret_env
            else:
                workload.container_port = item.port
                workload.command = item.command
                config_env = item.config_env
                secret_env = item.secret_env
            for name in sorted(config_env):
                configmap[name] = Tracked()
            secret_refs = [SecretRefSpec(env_name=name) for name in sorted(secret_env)]
            if base is not None and base.service is not None:
                service = ServiceSpec(port=base.service.port)

        components.append(
            ComponentIntentSpec(
                component_id=item.component_id,
                role=item.role,
                workload=workload,
                service=service,
                configmap=configmap,
                secret_refs=secret_refs,
            )
        )
    return AgentKubernetesIntent(namespace=baseline.namespace, components=components)


def intent_path_exists(intent: AgentKubernetesIntent, path: str) -> bool:
    try:
        _resolve_path(intent, path)
    except ChangeSetError:
        return False
    return True


def get_intent_path(intent: AgentKubernetesIntent, path: str) -> object | None:
    target = _resolve_path(intent, path)
    return _read_target(target)


def set_intent_path(
    intent: AgentKubernetesIntent,
    path: str,
    value: object | None,
    *,
    source: str,
) -> AgentKubernetesIntent:
    updated = intent.model_copy(deep=True)
    target = _resolve_path(updated, path, create=True)
    coerced = _validate_value(target["kind"], value)
    _write_target(target, coerced, source=source)
    _cleanup_optional_specs(target["component"])
    return updated


def _resolve_path(
    intent: AgentKubernetesIntent,
    path: str,
    *,
    create: bool = False,
) -> dict[str, Any]:
    if not any(pattern.match(path) for pattern in INTENT_PATHS):
        raise ChangeSetError(f"unsupported intent path: {path}")
    if path == "namespace":
        return {"kind": "k8s_name", "object": intent, "field": "namespace", "component": None}
    if path == "create_namespace":
        return {"kind": "bool", "object": intent, "field": "create_namespace", "component": None}

    parts = path.split(".")
    component_id = parts[1]
    component = _component(intent, component_id)
    tail = parts[2:]
    if tail[:2] == ["workload", "image"]:
        return {
            "kind": {"registry": "registry", "name": "k8s_name", "tag": "image_tag"}[tail[2]],
            "object": component.workload.image,
            "field": tail[2],
            "component": component,
        }
    if tail[:1] == ["workload"]:
        return {
            "kind": {
                "replicas": "replicas",
                "container_port": "port",
                "command": "string",
            }[tail[1]],
            "object": component.workload,
            "field": tail[1],
            "component": component,
        }
    if tail[:1] == ["service"]:
        if component.service is None:
            if not create:
                return {"kind": "port", "object": None, "field": "port", "component": component}
            component.service = ServiceSpec()
        return {"kind": "port", "object": component.service, "field": "port", "component": component}
    if tail[:1] == ["ingress"]:
        if component.ingress is None:
            if not create:
                return {"kind": "host" if tail[1] == "host" else "mount_path", "object": None, "field": tail[1], "component": component}
            component.ingress = IngressSpec()
        return {
            "kind": "host" if tail[1] == "host" else "mount_path",
            "object": component.ingress,
            "field": tail[1],
            "component": component,
        }
    if tail[:1] == ["configmap"]:
        return {"kind": "string", "object": component.configmap, "field": tail[1], "component": component}
    if tail[:1] == ["secret_refs"]:
        env_name = tail[1]
        ref = next((item for item in component.secret_refs if item.env_name == env_name), None)
        if ref is None:
            raise ChangeSetError(f"unknown secret env reference: {env_name}")
        return {
            "kind": "k8s_name" if tail[2] == "secret_name" else "secret_key",
            "object": ref,
            "field": tail[2],
            "component": component,
        }
    if tail[:1] == ["pvc"]:
        if component.pvc is None:
            if not create:
                return {"kind": _pvc_kind(tail[1]), "object": None, "field": tail[1], "component": component}
            component.pvc = PVCSpec()
        return {
            "kind": _pvc_kind(tail[1]),
            "object": component.pvc,
            "field": tail[1],
            "component": component,
        }
    raise ChangeSetError(f"unsupported intent path: {path}")


def _component(intent: AgentKubernetesIntent, component_id: str) -> ComponentIntentSpec:
    for component in intent.components:
        if component.component_id == component_id:
            return component
    raise ChangeSetError(f"unknown component: {component_id}")


def _pvc_kind(field: str) -> str:
    return {"size": "quantity", "storage_class": "string", "mount_path": "mount_path"}[field]


def _read_target(target: dict[str, Any]) -> object | None:
    obj = target["object"]
    if obj is None:
        return None
    if isinstance(obj, dict):
        tracked = obj.get(target["field"])
    else:
        tracked = getattr(obj, target["field"])
    if isinstance(tracked, Tracked):
        return tracked.value
    return tracked


def _write_target(target: dict[str, Any], value: object | None, *, source: str) -> None:
    obj = target["object"]
    field = target["field"]
    if target["kind"] == "bool":
        setattr(obj, field, bool(value))
        return
    tracked = None if value is None else _tracked(value, source)
    if isinstance(obj, dict):
        if tracked is None:
            obj.pop(field, None)
        else:
            obj[field] = tracked
    else:
        setattr(obj, field, tracked)


def _tracked(value: object, source: str) -> Tracked:
    confidence = Confidence.HIGH if source == "user_decision" else Confidence.MEDIUM
    return Tracked(value=value, source=source, confidence=confidence, evidence_refs=[])


def _validate_value(kind: str, value: object | None) -> object | None:
    if value is None:
        return None
    if kind == "bool":
        if not isinstance(value, bool):
            raise ChangeSetError("expected boolean value")
        return value
    if kind in {"port", "replicas"}:
        if not isinstance(value, int):
            raise ChangeSetError("expected integer value")
        maximum = 65535 if kind == "port" else 50
        if value < 1 or value > maximum:
            raise ChangeSetError(f"{kind} out of range")
        return value
    if not isinstance(value, str) or "\n" in value or "\x00" in value or not value:
        raise ChangeSetError("expected non-empty single-line string value")
    if kind == "k8s_name" and not _RFC1123.match(value):
        raise ChangeSetError("invalid Kubernetes name")
    if kind == "host" and not _HOST.match(value):
        raise ChangeSetError("invalid host")
    if kind == "registry" and not _REGISTRY.match(value):
        raise ChangeSetError("invalid image registry")
    if kind == "image_tag" and not _TAG.match(value):
        raise ChangeSetError("invalid image tag")
    if kind == "quantity" and not _QTY.match(value):
        raise ChangeSetError("invalid storage quantity")
    if kind == "mount_path" and not value.startswith("/"):
        raise ChangeSetError("mount path must be absolute")
    if kind == "secret_key" and not _SECRET_KEY.match(value):
        raise ChangeSetError("invalid secret key")
    return value


def _cleanup_optional_specs(component: ComponentIntentSpec | None) -> None:
    if component is None:
        return
    if component.ingress is not None and component.ingress.host is None and component.ingress.path is None:
        component.ingress = None
    if (
        component.pvc is not None
        and component.pvc.size is None
        and component.pvc.storage_class is None
        and component.pvc.mount_path is None
    ):
        component.pvc = None
