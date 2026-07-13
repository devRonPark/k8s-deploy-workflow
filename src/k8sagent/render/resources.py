from __future__ import annotations

import shlex

from k8sagent.models.intent import AgentKubernetesIntent, ComponentIntentSpec
from k8sagent.render.policy import annotations, labels


def render_namespace(intent: AgentKubernetesIntent) -> dict | None:
    if not intent.create_namespace or intent.namespace is None or intent.namespace.value is None:
        return None
    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {
            "name": intent.namespace.value,
            "labels": {
                "app.kubernetes.io/managed-by": "k8s-agent",
            },
        },
    }


def render_deployment(
    component: ComponentIntentSpec,
    namespace: str | None,
    commit_sha: str | None,
) -> dict:
    cid = component.component_id
    workload = component.workload
    container: dict = {"name": cid, "image": _image_ref(component)}
    if workload.command is not None and workload.command.value:
        container["command"] = shlex.split(workload.command.value)
    if workload.container_port is not None and workload.container_port.value is not None:
        container["ports"] = [{"containerPort": workload.container_port.value}]
    env = [
        {
            "name": ref.env_name,
            "valueFrom": {
                "secretKeyRef": {
                    "name": ref.secret_name.value,
                    "key": ref.secret_key.value,
                }
            },
        }
        for ref in sorted(component.secret_refs, key=lambda item: item.env_name)
        if ref.secret_name is not None
        and ref.secret_name.value
        and ref.secret_key is not None
        and ref.secret_key.value
    ]
    if env:
        container["env"] = env
    if _configmap_data(component):
        container["envFrom"] = [{"configMapRef": {"name": f"{cid}-config"}}]
    if component.pvc is not None and component.pvc.mount_path and component.pvc.mount_path.value:
        container["volumeMounts"] = [
            {"name": f"{cid}-data", "mountPath": component.pvc.mount_path.value}
        ]

    pod_spec: dict = {"containers": [container]}
    if "volumeMounts" in container:
        pod_spec["volumes"] = [
            {"name": f"{cid}-data", "persistentVolumeClaim": {"claimName": f"{cid}-data"}}
        ]
    spec: dict = {
        "selector": {"matchLabels": {"app.kubernetes.io/name": cid}},
        "template": {"metadata": {"labels": labels(cid)}, "spec": pod_spec},
    }
    if workload.replicas is not None and workload.replicas.value is not None:
        spec = {"replicas": workload.replicas.value, **spec}
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": _metadata(cid, namespace, cid, commit_sha),
        "spec": spec,
    }


def render_service(
    component: ComponentIntentSpec,
    namespace: str | None,
    commit_sha: str | None,
) -> dict | None:
    if component.service is None or component.service.port is None or component.service.port.value is None:
        return None
    cid = component.component_id
    port = component.service.port.value
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": _metadata(f"{cid}-service", namespace, cid, commit_sha),
        "spec": {
            "type": "ClusterIP",
            "selector": {"app.kubernetes.io/name": cid},
            "ports": [{"port": port, "targetPort": port}],
        },
    }


def render_configmap(
    component: ComponentIntentSpec,
    namespace: str | None,
    commit_sha: str | None,
) -> dict | None:
    data = _configmap_data(component)
    if not data:
        return None
    cid = component.component_id
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": _metadata(f"{cid}-config", namespace, cid, commit_sha),
        "data": data,
    }


def render_ingress(
    component: ComponentIntentSpec,
    namespace: str | None,
    commit_sha: str | None,
) -> dict | None:
    if component.ingress is None or component.ingress.host is None or component.ingress.host.value is None:
        return None
    cid = component.component_id
    service_port = component.service.port.value if component.service and component.service.port else None
    if service_port is None:
        return None
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": _metadata(f"{cid}-ingress", namespace, cid, commit_sha),
        "spec": {
            "rules": [
                {
                    "host": component.ingress.host.value,
                    "http": {
                        "paths": [
                            {
                                "path": (
                                    component.ingress.path.value
                                    if component.ingress.path is not None
                                    and component.ingress.path.value
                                    else "/"
                                ),
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {
                                        "name": f"{cid}-service",
                                        "port": {"number": service_port},
                                    }
                                },
                            }
                        ]
                    },
                }
            ]
        },
    }


def render_pvc(
    component: ComponentIntentSpec,
    namespace: str | None,
    commit_sha: str | None,
) -> dict | None:
    if component.pvc is None or component.pvc.size is None or component.pvc.mount_path is None:
        return None
    if component.pvc.size.value is None or component.pvc.mount_path.value is None:
        return None
    cid = component.component_id
    spec = {
        "accessModes": ["ReadWriteOnce"],
        "resources": {"requests": {"storage": component.pvc.size.value}},
    }
    if component.pvc.storage_class is not None and component.pvc.storage_class.value:
        spec["storageClassName"] = component.pvc.storage_class.value
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": _metadata(f"{cid}-data", namespace, cid, commit_sha),
        "spec": spec,
    }


def _metadata(
    name: str,
    namespace: str | None,
    component_id: str,
    commit_sha: str | None,
) -> dict:
    metadata = {
        "name": name,
    }
    if namespace is not None:
        metadata["namespace"] = namespace
    metadata["labels"] = labels(component_id)
    metadata["annotations"] = annotations(commit_sha)
    return metadata


def _configmap_data(component: ComponentIntentSpec) -> dict[str, str]:
    return {
        key: tracked.value
        for key, tracked in sorted(component.configmap.items())
        if tracked.value is not None
    }


def _image_ref(component: ComponentIntentSpec) -> str:
    image = component.workload.image
    registry = image.registry.value
    name = image.name.value
    tag = image.tag.value if image.tag is not None and image.tag.value else "latest"
    return f"{registry}/{name}:{tag}"
