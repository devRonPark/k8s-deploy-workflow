from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from k8sagent.models.intent import AgentKubernetesIntent


class UnresolvedField(BaseModel):
    path: str
    reason: str
    severity: Literal["blocking", "optional"]


def find_unresolved(intent: AgentKubernetesIntent) -> list[UnresolvedField]:
    gaps: list[UnresolvedField] = []
    if intent.namespace is None or intent.namespace.value is None:
        gaps.append(UnresolvedField(path="namespace", reason="missing_namespace", severity="blocking"))

    for component in sorted(intent.components, key=lambda item: item.component_id):
        if component.role != "application":
            continue
        prefix = f"components.{component.component_id}"
        image = component.workload.image
        if image.registry is None or image.registry.value is None:
            gaps.append(
                UnresolvedField(
                    path=f"{prefix}.workload.image.registry",
                    reason="missing_image_registry",
                    severity="blocking",
                )
            )
        if image.name is None or image.name.value is None:
            gaps.append(
                UnresolvedField(
                    path=f"{prefix}.workload.image.name",
                    reason="missing_image_name",
                    severity="blocking",
                )
            )
        if image.tag is None or image.tag.value is None:
            gaps.append(
                UnresolvedField(
                    path=f"{prefix}.workload.image.tag",
                    reason="missing_image_tag",
                    severity="optional",
                )
            )
        if component.service is not None:
            if component.service.port is None or component.service.port.value is None:
                gaps.append(
                    UnresolvedField(
                        path=f"{prefix}.service.port",
                        reason="missing_service_port",
                        severity="blocking",
                    )
                )
            if (
                component.workload.container_port is None
                or component.workload.container_port.value is None
            ):
                gaps.append(
                    UnresolvedField(
                        path=f"{prefix}.workload.container_port",
                        reason="missing_container_port",
                        severity="blocking",
                    )
                )
        for secret_ref in sorted(component.secret_refs, key=lambda item: item.env_name):
            if secret_ref.secret_name is None or secret_ref.secret_name.value is None:
                gaps.append(
                    UnresolvedField(
                        path=f"{prefix}.secret_refs.{secret_ref.env_name}.secret_name",
                        reason="missing_secret_name",
                        severity="blocking",
                    )
                )
            if secret_ref.secret_key is None or secret_ref.secret_key.value is None:
                gaps.append(
                    UnresolvedField(
                        path=f"{prefix}.secret_refs.{secret_ref.env_name}.secret_key",
                        reason="missing_secret_key",
                        severity="blocking",
                    )
                )
        if component.ingress is not None and (
            component.ingress.host is None or component.ingress.host.value is None
        ):
            gaps.append(
                UnresolvedField(
                    path=f"{prefix}.ingress.host",
                    reason="missing_ingress_host",
                    severity="blocking",
                )
            )
        if component.pvc is not None:
            if component.pvc.size is None or component.pvc.size.value is None:
                gaps.append(
                    UnresolvedField(
                        path=f"{prefix}.pvc.size",
                        reason="missing_pvc_size",
                        severity="blocking",
                    )
                )
            if component.pvc.mount_path is None or component.pvc.mount_path.value is None:
                gaps.append(
                    UnresolvedField(
                        path=f"{prefix}.pvc.mount_path",
                        reason="missing_pvc_mount_path",
                        severity="blocking",
                    )
                )
        for name, tracked in sorted(component.configmap.items()):
            if tracked.value is None:
                gaps.append(
                    UnresolvedField(
                        path=f"{prefix}.configmap.{name}",
                        reason="missing_config_value",
                        severity="optional",
                    )
                )
    return sorted(gaps, key=lambda gap: gap.path)
