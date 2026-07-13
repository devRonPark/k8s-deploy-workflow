from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from k8sagent.models.intent import AgentKubernetesIntent
from k8sagent.models.report import AgentValidationReport, CheckResult
from k8sagent.procutil import run_command
from preanalyzer.validator.kubeconform_tool import resolve_kubeconform


def aggregate_checks(checks: list[CheckResult]) -> str:
    if any(check.status == "fail" for check in checks):
        return "FAIL"
    if any(check.skipped_reason == "tool_not_found" for check in checks):
        return "PARTIAL"
    return "PASS"


def run_validation(
    manifest_dir: Path,
    intent: AgentKubernetesIntent,
    *,
    k8s_version: str,
    kubeconform_path: Path | None,
    runner=run_command,
    project_root: Path | None = None,
) -> AgentValidationReport:
    del intent
    checks: list[CheckResult] = []
    docs, syntax = _load_yaml_documents(manifest_dir)
    checks.append(syntax)
    if syntax.status == "fail":
        checks.extend(_skipped_after_prior())
        return AgentValidationReport(
            aggregate=aggregate_checks(checks),
            k8s_version=k8s_version,
            checks=checks,
        )

    invariant = _check_invariants(docs)
    checks.append(invariant)
    if invariant.status == "fail":
        checks.extend(_skipped_after_prior()[1:])
        return AgentValidationReport(
            aggregate=aggregate_checks(checks),
            k8s_version=k8s_version,
            checks=checks,
        )

    checks.append(
        _run_kubeconform(
            manifest_dir,
            k8s_version=k8s_version,
            kubeconform_path=kubeconform_path,
            runner=runner,
            project_root=project_root,
        )
    )
    checks.append(_run_kubectl(manifest_dir, runner=runner))
    return AgentValidationReport(
        aggregate=aggregate_checks(checks),
        k8s_version=k8s_version,
        checks=checks,
    )


def write_report(report: AgentValidationReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "report.yaml"
    path.write_text(
        yaml.safe_dump({"validation_report": report.model_dump()}, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _load_yaml_documents(manifest_dir: Path) -> tuple[list[dict], CheckResult]:
    docs: list[dict] = []
    for path in sorted(manifest_dir.rglob("*.yaml")):
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            return [], CheckResult(name="yaml_syntax", status="fail", detail=f"{path.name}: {exc}")
        if isinstance(loaded, dict):
            docs.append(loaded)
    return docs, CheckResult(name="yaml_syntax", status="pass")


def _skipped_after_prior() -> list[CheckResult]:
    return [
        CheckResult(name="intent_invariants", status="skipped", skipped_reason="prior_check_failed"),
        CheckResult(name="kubeconform", status="skipped", skipped_reason="prior_check_failed"),
        CheckResult(name="kubectl_dry_run", status="skipped", skipped_reason="prior_check_failed"),
    ]


def _check_invariants(docs: list[dict]) -> CheckResult:
    violations: list[str] = []
    deployments = {doc["metadata"]["name"]: doc for doc in docs if doc.get("kind") == "Deployment"}
    services = {doc["metadata"]["name"]: doc for doc in docs if doc.get("kind") == "Service"}
    namespaces = {
        doc.get("metadata", {}).get("namespace")
        for doc in docs
        if doc.get("kind") != "Namespace" and doc.get("metadata", {}).get("namespace") is not None
    }
    if len(namespaces) > 1:
        violations.append("metadata.namespace differs between rendered resources")

    for service_name, service in services.items():
        selector = service.get("spec", {}).get("selector", {})
        deployment = _deployment_for_selector(deployments.values(), selector)
        if deployment is None:
            violations.append(f"Service {service_name} selector does not match a Deployment")
            continue
        labels = deployment.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {})
        if any(labels.get(key) != value for key, value in selector.items()):
            violations.append(f"Service {service_name} selector is not contained in pod labels")
        container_ports = {
            port.get("containerPort")
            for container in deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
            for port in container.get("ports", [])
        }
        for port in service.get("spec", {}).get("ports", []):
            if port.get("targetPort") not in container_ports:
                violations.append(f"Service {service_name} targetPort does not match Deployment containerPort")

    for ingress in [doc for doc in docs if doc.get("kind") == "Ingress"]:
        for rule in ingress.get("spec", {}).get("rules", []):
            for path in rule.get("http", {}).get("paths", []):
                service = path.get("backend", {}).get("service", {})
                name = service.get("name")
                number = service.get("port", {}).get("number")
                if name not in services:
                    violations.append(f"Ingress backend service missing: {name}")
                elif number not in {p.get("port") for p in services[name].get("spec", {}).get("ports", [])}:
                    violations.append(f"Ingress backend service port mismatch: {name}")

    for doc in docs:
        for container in doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", []):
            for env in container.get("env", []):
                ref = env.get("valueFrom", {}).get("secretKeyRef")
                if ref is not None and (not ref.get("name") or not ref.get("key")):
                    violations.append("secretKeyRef name/key must be non-empty")

    if violations:
        return CheckResult(name="intent_invariants", status="fail", detail="; ".join(violations))
    return CheckResult(name="intent_invariants", status="pass")


def _deployment_for_selector(deployments, selector: dict):
    for deployment in deployments:
        labels = deployment.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {})
        if all(labels.get(key) == value for key, value in selector.items()):
            return deployment
    return None


def _run_kubeconform(
    manifest_dir: Path,
    *,
    k8s_version: str,
    kubeconform_path: Path | None,
    runner,
    project_root: Path | None,
) -> CheckResult:
    executable = str(kubeconform_path) if kubeconform_path is not None else resolve_kubeconform(project_root or Path.cwd(), None)
    if executable is None:
        return CheckResult(name="kubeconform", status="skipped", skipped_reason="tool_not_found")
    result = runner(
        [
            executable,
            "-strict",
            "-summary",
            "-kubernetes-version",
            _normalize_kubernetes_version(k8s_version),
            str(manifest_dir),
        ]
    )
    if result.returncode != 0:
        return CheckResult(name="kubeconform", status="fail", detail=(result.stderr or result.stdout).strip())
    return CheckResult(name="kubeconform", status="pass", detail=result.stdout.strip() or None)


def _run_kubectl(manifest_dir: Path, *, runner) -> CheckResult:
    executable = shutil.which("kubectl")
    if executable is None:
        return CheckResult(name="kubectl_dry_run", status="skipped", skipped_reason="tool_not_found")
    result = runner([executable, "apply", "--dry-run=client", "-f", str(manifest_dir), "-R"])
    if result.returncode != 0:
        return CheckResult(name="kubectl_dry_run", status="fail", detail=(result.stderr or result.stdout).strip())
    return CheckResult(name="kubectl_dry_run", status="pass", detail=result.stdout.strip() or None)


# Same normalization rule as preanalyzer.validator.pipeline._normalize_kubernetes_version.
def _normalize_kubernetes_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) == 2:
        return f"{version}.0"
    return version
