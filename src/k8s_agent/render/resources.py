from __future__ import annotations

import shlex

from k8s_agent.render.names import resource_name


def build_deployment(
    *,
    component_id: str,
    image: str,
    replicas: int,
    port: int | None,
    command: str | None,
    secret_names: list[str] | None = None,
) -> dict:
    name = resource_name(component_id, "deployment")
    labels = _labels(component_id)
    container = {"name": component_id, "image": image}
    if port is not None:
        container["ports"] = [{"containerPort": port}]
        container["readinessProbe"] = {"tcpSocket": {"port": port}}
        container["livenessProbe"] = {"tcpSocket": {"port": port}}
    if command:
        container["command"] = shlex.split(command)
    if secret_names:
        container["envFrom"] = [{"secretRef": {"name": name}} for name in sorted(secret_names)]
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "labels": labels},
        "spec": {
            "replicas": replicas,
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {"containers": [container]},
            },
        },
    }


def build_service(component_id: str, port: int) -> dict:
    labels = _labels(component_id)
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": resource_name(component_id, "svc"), "labels": labels},
        "spec": {"selector": labels, "ports": [{"port": port, "targetPort": port}]},
    }


def build_ingress(component_id: str, host: str, port: int) -> dict:
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {"name": resource_name(component_id, "ingress"), "labels": _labels(component_id)},
        "spec": {
            "rules": [
                {
                    "host": host,
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {
                                        "name": resource_name(component_id, "svc"),
                                        "port": {"number": port},
                                    }
                                },
                            }
                        ]
                    },
                }
            ]
        },
    }


def build_kustomization(resources: list[str]) -> dict:
    return {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": sorted(resources)}


def _labels(component_id: str) -> dict[str, str]:
    return {"app.kubernetes.io/name": resource_name(component_id, "app"), "app.kubernetes.io/component": component_id}
