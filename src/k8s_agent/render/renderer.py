from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from k8s_agent.errors import AgentError
from k8s_agent.models.profile import DeploymentProfile
from k8s_agent.render.names import resource_name
from k8s_agent.render.resources import build_deployment, build_ingress, build_kustomization, build_service
from k8s_agent.render.serializer import dump_yaml


class ResourceRef(BaseModel):
    kind: str
    name: str
    path: str


class GeneratedFile(BaseModel):
    path: str
    checksum: str


class ManifestBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_refs: list[ResourceRef] = Field(default_factory=list)
    files: list[GeneratedFile] = Field(default_factory=list)
    checksum: str


class ManifestRenderer:
    def render(self, profile: DeploymentProfile, destination: Path) -> ManifestBundle:
        if not profile.renderable:
            raise AgentError(
                code="RENDER-101",
                exit_code=3,
                message="profile is not renderable.",
                resolution="Resolve blocked and unresolved profile holds before rendering.",
                context={"blocked": str(len(profile.blocked)), "unresolved": str(len(profile.unresolved))},
            )
        destination.mkdir(parents=True, exist_ok=True)
        base = destination / "base"
        overlay = destination / "overlays" / "default"
        base.mkdir(parents=True, exist_ok=True)
        overlay.mkdir(parents=True, exist_ok=True)

        resource_refs: list[ResourceRef] = []
        base_resources: list[str] = []
        for component_id in _components(profile):
            resources = _resources_for_component(profile, component_id)
            for filename, resource in resources:
                path = base / filename
                path.write_text(dump_yaml(resource), encoding="utf-8")
                base_resources.append(filename)
                if resource.get("kind") != "Kustomization":
                    resource_refs.append(ResourceRef(kind=resource["kind"], name=resource["metadata"]["name"], path=path.relative_to(destination).as_posix()))
        (base / "kustomization.yaml").write_text(dump_yaml(build_kustomization(base_resources)), encoding="utf-8")
        (overlay / "kustomization.yaml").write_text(dump_yaml(build_kustomization(["../../base"])), encoding="utf-8")
        files = _generated_files(destination)
        return ManifestBundle(
            resource_refs=sorted(resource_refs, key=lambda ref: (ref.kind, ref.name, ref.path)),
            files=files,
            checksum=_bundle_checksum(destination, files),
        )


def _components(profile: DeploymentProfile) -> list[str]:
    components = set()
    for field in profile.values:
        parts = field.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "components":
            components.add(parts[1])
    return sorted(components)


def _resources_for_component(profile: DeploymentProfile, component_id: str) -> list[tuple[str, dict]]:
    image = _value(profile, component_id, "image") or f"{component_id}:latest"
    replicas = int(_value(profile, component_id, "replicas") or 1)
    service = _value(profile, component_id, "service") or {}
    port = service.get("port") if isinstance(service, dict) else None
    command = _value(profile, component_id, "runtime_command")
    secret_ref = _value(profile, component_id, "secret_ref")
    secret_names = [secret_ref["name"]] if isinstance(secret_ref, dict) and "name" in secret_ref else []

    resources = [
        (
            f"{component_id}-deployment.yaml",
            build_deployment(
                component_id=component_id,
                image=str(image),
                replicas=replicas,
                port=int(port) if port is not None else None,
                command=str(command) if command else None,
                secret_names=secret_names,
            ),
        )
    ]
    if port is not None:
        resources.append((f"{component_id}-service.yaml", build_service(component_id, int(port))))
    if _value(profile, component_id, "external_exposure") == "public" and port is not None:
        host = _value(profile, component_id, "hostname") or f"{resource_name(component_id, 'app')}.example.local"
        resources.append((f"{component_id}-ingress.yaml", build_ingress(component_id, str(host), int(port))))
    return resources


def _value(profile: DeploymentProfile, component_id: str, field: str):
    for path in _field_paths(component_id, field):
        item = profile.values.get(path)
        if item is not None:
            return item.value
    if field == "secret_ref":
        prefix = f"/components/{component_id}/secrets/"
        for path, item in sorted(profile.values.items()):
            if path.startswith(prefix):
                return item.value
    return None


def _field_paths(component_id: str, field: str) -> list[str]:
    aliases = {
        "replicas": "workload/replicas",
        "service": "service/port",
        "runtime_command": "workload/command",
        "external_exposure": "network/external_exposure",
    }
    paths = [f"/components/{component_id}/{field}"]
    if field in aliases:
        paths.append(f"/components/{component_id}/{aliases[field]}")
    return paths


def _generated_files(destination: Path) -> list[GeneratedFile]:
    files = []
    for path in sorted(candidate for candidate in destination.rglob("*") if candidate.is_file()):
        rel = path.relative_to(destination).as_posix()
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append(GeneratedFile(path=rel, checksum=f"sha256:{checksum}"))
    return files


def _bundle_checksum(destination: Path, files: list[GeneratedFile]) -> str:
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update((destination / file.path).read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"
