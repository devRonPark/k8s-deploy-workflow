from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from k8sagent.models.intent import AgentKubernetesIntent, ComponentIntentSpec
from k8sagent.render.resources import (
    render_configmap,
    render_deployment,
    render_ingress,
    render_namespace,
    render_pvc,
    render_service,
)
from k8sagent.render.serialize import to_yaml


@dataclass(frozen=True)
class RenderedManifests:
    files: dict[str, str] = field(default_factory=dict)
    deferred: list[str] = field(default_factory=list)


def render_all(intent: AgentKubernetesIntent, commit_sha: str | None) -> RenderedManifests:
    namespace = intent.namespace.value if intent.namespace is not None else None
    files: dict[str, str] = {}
    deferred: list[str] = []

    namespace_doc = render_namespace(intent)
    if namespace_doc is not None:
        files["namespace.yaml"] = to_yaml(namespace_doc)

    for component in sorted(intent.components, key=lambda item: item.component_id):
        if component.role != "application":
            continue
        reason = _defer_reason(component)
        if reason is not None:
            deferred.append(reason)
            continue
        prefix = component.component_id
        docs = [
            ("deployment.yaml", render_deployment(component, namespace, commit_sha)),
            ("service.yaml", render_service(component, namespace, commit_sha)),
            ("configmap.yaml", render_configmap(component, namespace, commit_sha)),
            ("ingress.yaml", render_ingress(component, namespace, commit_sha)),
            ("pvc.yaml", render_pvc(component, namespace, commit_sha)),
        ]
        for filename, doc in docs:
            if doc is not None:
                files[f"{prefix}/{filename}"] = to_yaml(doc)
    return RenderedManifests(files=dict(sorted(files.items())), deferred=deferred)


def write_manifests(rendered: RenderedManifests, output_dir: Path) -> list[Path]:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for rel, text in rendered.files.items():
        target = output_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        paths.append(target)
    return paths


def _defer_reason(component: ComponentIntentSpec) -> str | None:
    image = component.workload.image
    if (
        image.registry is None
        or image.registry.value is None
        or image.name is None
        or image.name.value is None
    ):
        return f"{component.component_id}: image registry or name unresolved"
    return None
