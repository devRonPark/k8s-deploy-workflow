from __future__ import annotations

import re
from pathlib import Path

from k8sagent.changeset import Change, ChangeSet, apply_changeset, render_diff_text, validate_changeset
from k8sagent.llm import LLMProtocol
from k8sagent.models.intent import AgentKubernetesIntent
from k8sagent.models.report import AgentValidationReport
from k8sagent.render import render_all, write_manifests
from k8sagent.validate import run_validation


def explain_failure(report: AgentValidationReport, llm: LLMProtocol | None) -> str:
    if llm is not None:
        explained = llm.explain_validation_failure(report)
        if explained:
            return explained
    return "\n".join(
        f"{check.name}: {check.detail}"
        for check in report.checks
        if check.status == "fail" and check.detail
    )


def propose_correction(
    report: AgentValidationReport,
    intent: AgentKubernetesIntent,
    llm: LLMProtocol | None,
) -> tuple[ChangeSet | None, str]:
    detail = _failure_detail(report)
    by_rule = _rule_table(detail, intent)
    if by_rule is not None:
        return by_rule, "rule_table"
    if llm is not None:
        proposed = llm.propose_correction(report.model_dump(mode="json"), intent, _allowed_paths(intent))
        if proposed is not None:
            try:
                validate_changeset(proposed, intent)
            except Exception:
                return None, "none"
            return proposed.model_copy(update={"origin": "correction"}), "llm"
    return None, "none"


def run_correction_cycle(
    session,
    intent: AgentKubernetesIntent,
    manifest_dir: Path,
    *,
    report: AgentValidationReport,
    llm: LLMProtocol | None,
    approve,
    k8s_version: str,
    kubeconform_path: Path | None,
    output_dir: Path,
    commit_sha: str | None,
) -> tuple[AgentKubernetesIntent, AgentValidationReport, bool]:
    del session
    proposed, _source = propose_correction(report, intent, llm)
    if proposed is None:
        return intent, report, False
    diff_text = render_diff_text(_safe_diff(proposed, intent))
    if not approve(diff_text):
        return intent, report, False
    updated = apply_changeset(proposed, intent, source="correction")
    rendered = render_all(updated, commit_sha)
    write_manifests(rendered, manifest_dir)
    new_report = run_validation(
        manifest_dir,
        updated,
        k8s_version=k8s_version,
        kubeconform_path=kubeconform_path,
        project_root=output_dir,
    )
    return updated, new_report, True


def _safe_diff(cs: ChangeSet, intent: AgentKubernetesIntent):
    from k8sagent.changeset import diff_changeset

    return diff_changeset(cs, intent)


def _failure_detail(report: AgentValidationReport) -> str:
    return "\n".join(check.detail or "" for check in report.checks if check.status == "fail")


def _rule_table(detail: str, intent: AgentKubernetesIntent) -> ChangeSet | None:
    lowered = detail.lower()
    if ("rfc 1123" in lowered or "lowercase rfc" in lowered) and "namespace" in lowered:
        match = re.search(r"namespace\s+([A-Za-z0-9_.-]+)", detail)
        raw_value = match.group(1) if match is not None else (
            str(intent.namespace.value) if intent.namespace is not None and intent.namespace.value else ""
        )
        if raw_value:
            normalized = _normalize_k8s_name(raw_value)
            return ChangeSet(
                origin="correction",
                changes=[Change(op="set", path="namespace", value=normalized)],
                summary="normalize namespace",
            )
    if "quantity" in lowered or "storage" in lowered and "invalid" in lowered:
        for component in intent.components:
            if component.pvc is not None and component.pvc.size is not None:
                return ChangeSet(
                    origin="correction",
                    changes=[Change(op="unset", path=f"components.{component.component_id}.pvc.size")],
                    summary="unset invalid pvc size",
                )
    if "port" in lowered and ("invalid" in lowered or "out of range" in lowered):
        for component in intent.components:
            if component.service is not None and component.service.port is not None:
                return ChangeSet(
                    origin="correction",
                    changes=[Change(op="unset", path=f"components.{component.component_id}.service.port")],
                    summary="unset invalid service port",
                )
    return None


def _normalize_k8s_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    normalized = re.sub(r"-+", "-", normalized)
    return normalized[:63] or "default"


def _allowed_paths(intent: AgentKubernetesIntent) -> list[str]:
    paths = ["namespace", "create_namespace"]
    for component in intent.components:
        cid = component.component_id
        paths.extend(
            [
                f"components.{cid}.workload.image.registry",
                f"components.{cid}.workload.image.name",
                f"components.{cid}.workload.image.tag",
                f"components.{cid}.workload.replicas",
                f"components.{cid}.workload.container_port",
                f"components.{cid}.workload.command",
                f"components.{cid}.service.port",
                f"components.{cid}.ingress.host",
                f"components.{cid}.ingress.path",
                f"components.{cid}.pvc.size",
                f"components.{cid}.pvc.storage_class",
                f"components.{cid}.pvc.mount_path",
            ]
        )
        paths.extend(f"components.{cid}.configmap.{key}" for key in component.configmap)
        for ref in component.secret_refs:
            paths.append(f"components.{cid}.secret_refs.{ref.env_name}.secret_name")
            paths.append(f"components.{cid}.secret_refs.{ref.env_name}.secret_key")
    return paths
