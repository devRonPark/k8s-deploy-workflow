from __future__ import annotations

from pathlib import Path

import yaml

from k8s_agent.models.validation import ValidationFinding


REPAIRABLE_CODES = {
    "service_selector_mismatch": "sync_service_to_deployment",
    "service_target_port_mismatch": "sync_service_to_deployment",
}


def strategy_for(finding: ValidationFinding) -> str | None:
    if not finding.repairable:
        return None
    return REPAIRABLE_CODES.get(finding.code)


def apply_strategy(strategy: str, service_path: Path, deployment_path: Path) -> list[Path]:
    if strategy != "sync_service_to_deployment":
        return []
    service = yaml.safe_load(service_path.read_text(encoding="utf-8"))
    deployment = yaml.safe_load(deployment_path.read_text(encoding="utf-8"))
    labels = deployment["spec"]["template"]["metadata"]["labels"]
    ports = [
        port["containerPort"]
        for container in deployment["spec"]["template"]["spec"]["containers"]
        for port in container.get("ports", [])
    ]
    service["spec"]["selector"] = labels
    if ports:
        service["spec"]["ports"][0]["targetPort"] = ports[0]
    service_path.write_text(yaml.safe_dump(service, sort_keys=False), encoding="utf-8")
    return [service_path]
