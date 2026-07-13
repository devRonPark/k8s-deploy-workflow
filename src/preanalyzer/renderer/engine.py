from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from preanalyzer.models.intent import KubernetesIntent
from preanalyzer.renderer.policy import annotations, labels


_TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True)
class DeferredResource:
    component_id: str
    resource: str
    reason: str


@dataclass(frozen=True)
class HeldResource:
    kind: str
    intended_path: str | None = None


@dataclass(frozen=True)
class HoldReason:
    code: str
    missing_field: str | None = None


@dataclass(frozen=True)
class GenerationHold:
    component_id: str
    resource: HeldResource
    reason: HoldReason
    status: str = "generation_held"
    display_status: str = "생성 보류"


@dataclass(frozen=True)
class RenderResult:
    files: dict[str, str] = field(default_factory=dict)
    deferred: list[DeferredResource] = field(default_factory=list)
    achieved_level_cap: int = 1
    generation_holds: list[GenerationHold] = field(default_factory=list)


class TemplateRenderer:
    def __init__(self, commit_sha: str | None, rules_version: str) -> None:
        self._commit_sha = commit_sha
        self._rules_version = rules_version
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, intent: KubernetesIntent, allow_placeholders: bool = False) -> RenderResult:
        files: dict[str, str] = {}
        deferred: list[DeferredResource] = []
        generation_holds: list[GenerationHold] = []
        namespace = intent.namespace.value if intent.namespace is not None else None
        common_annotations = annotations(self._commit_sha, self._rules_version)

        for component in sorted(intent.components, key=lambda c: c.component_id):
            if component.role != "application" or component.workload is None:
                deferred.append(
                    DeferredResource(component.component_id, "Workload", "role_dependency_no_workload")
                )
                continue

            workload = component.workload
            if workload.image_registry is None or workload.image_registry.value is None:
                deferred.append(
                    DeferredResource(
                        component.component_id,
                        "Deployment",
                        "unresolved_image_registry",
                    )
                )
                continue

            if workload.image_name is None or workload.image_name.value is None:
                deferred.append(
                    DeferredResource(component.component_id, "Deployment", "unresolved_image_name")
                )
                continue

            image_tag = workload.image_tag.value if workload.image_tag and workload.image_tag.value else "latest"
            image = f"{workload.image_registry.value}/{workload.image_name.value}:{image_tag}"
            base = {
                "name": component.component_id,
                "namespace": namespace,
                "labels": labels(component.component_id),
                "annotations": common_annotations,
            }
            port = workload.port.value if workload.port and workload.port.value is not None else None
            command = workload.command.value if workload.command and workload.command.value else None

            files[f"{component.component_id}/serviceaccount.yaml"] = self._render(
                "serviceaccount.yaml.j2", **base
            )
            files[f"{component.component_id}/deployment.yaml"] = self._render(
                "deployment.yaml.j2",
                **base,
                image=image,
                port=port,
                command=command,
                config_env=sorted(workload.config_env),
                secret_env=sorted(workload.secret_env),
            )
            if workload.config_env:
                files[f"{component.component_id}/configmap.yaml"] = self._render(
                    "configmap.yaml.j2", **base, keys=sorted(workload.config_env)
                )
            if workload.secret_env:
                files[f"{component.component_id}/secret.yaml"] = self._render(
                    "secret.placeholder.yaml.j2", **base, keys=sorted(workload.secret_env)
                )
            if component.service and component.service.port and component.service.port.value is not None:
                files[f"{component.component_id}/service.yaml"] = self._render(
                    "service.yaml.j2", **base, port=component.service.port.value
                )
            if component.ingress and component.ingress.host and component.ingress.host.value:
                service_port = (
                    component.service.port.value
                    if component.service and component.service.port and component.service.port.value is not None
                    else port
                )
                if service_port is None:
                    generation_holds.append(self._hold_ingress(component.component_id))
                    deferred.append(
                        DeferredResource(
                            component.component_id,
                            "Ingress",
                            "unresolved_service_port",
                        )
                    )
                    continue
                files[f"{component.component_id}/ingress.yaml"] = self._render(
                    "ingress.yaml.j2",
                    **base,
                    host=component.ingress.host.value,
                    service_port=service_port,
                )

        return RenderResult(
            files=dict(sorted(files.items())),
            deferred=deferred,
            generation_holds=generation_holds,
            achieved_level_cap=1,
        )

    def _render(self, template_name: str, **context) -> str:
        return self._env.get_template(template_name).render(**context).strip() + "\n"

    def _hold_ingress(self, component_id: str) -> GenerationHold:
        return GenerationHold(
            component_id=component_id,
            resource=HeldResource(kind="Ingress", intended_path=f"{component_id}/ingress.yaml"),
            reason=HoldReason(code="unresolved_service_port", missing_field="service.port"),
        )
