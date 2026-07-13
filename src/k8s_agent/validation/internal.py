from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from k8s_agent.models.validation import ResourceRef, ValidationFinding


class InternalManifestValidator:
    def validate_paths(self, paths: list[Path]) -> list[ValidationFinding]:
        resources: list[tuple[Path, dict]] = []
        findings: list[ValidationFinding] = []
        for path in paths:
            try:
                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                findings.append(_finding("yaml-syntax", "error", None, "/", "yaml_syntax", str(exc)))
                continue
            if isinstance(payload, dict) and "kind" in payload and payload.get("kind") != "Kustomization":
                resources.append((path, payload))
        findings.extend(_duplicates(resources))
        findings.extend(_service_checks(resources))
        return sorted(findings, key=lambda item: item.finding_id)


def _duplicates(resources: list[tuple[Path, dict]]) -> list[ValidationFinding]:
    findings = []
    seen = {}
    for path, resource in resources:
        key = (resource.get("kind"), resource.get("metadata", {}).get("name"))
        if key in seen:
            findings.append(_finding("internal", "error", _ref(resource, path), "/metadata/name", "duplicate_resource", f"duplicate resource {key[0]}/{key[1]}"))
        seen.setdefault(key, path)
    return findings


def _service_checks(resources: list[tuple[Path, dict]]) -> list[ValidationFinding]:
    findings = []
    deployments = [resource for _, resource in resources if resource.get("kind") == "Deployment"]
    services = [(path, resource) for path, resource in resources if resource.get("kind") == "Service"]
    deployment_labels = [dep.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {}) for dep in deployments]
    container_ports = {
        port.get("containerPort")
        for dep in deployments
        for container in dep.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        for port in container.get("ports", [])
    }
    for path, service in services:
        selector = service.get("spec", {}).get("selector", {})
        if selector not in deployment_labels:
            findings.append(_finding("internal", "error", _ref(service, path), "/spec/selector", "service_selector_mismatch", "service selector does not match any pod labels", True))
        for index, port in enumerate(service.get("spec", {}).get("ports", [])):
            if port.get("targetPort") not in container_ports:
                findings.append(_finding("internal", "error", _ref(service, path), f"/spec/ports/{index}/targetPort", "service_target_port_mismatch", "service targetPort does not match a containerPort", True))
    return findings


def _ref(resource: dict, path: Path) -> ResourceRef:
    return ResourceRef(kind=resource.get("kind", "Unknown"), name=resource.get("metadata", {}).get("name", "unknown"), path=path.as_posix())


def _finding(validator: str, severity: str, resource_ref, field_path: str, code: str, message: str, repairable: bool = False) -> ValidationFinding:
    payload = f"{validator}:{severity}:{field_path}:{code}:{message}:{resource_ref.model_dump_json() if resource_ref else ''}"
    return ValidationFinding(
        finding_id=f"VF-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12].upper()}",
        validator=validator,
        severity=severity,
        resource_ref=resource_ref,
        field_path=field_path,
        code=code,
        message=message,
        repairable=repairable,
    )
