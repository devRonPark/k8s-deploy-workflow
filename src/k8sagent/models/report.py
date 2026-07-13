from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class CheckResult(BaseModel):
    name: Literal["yaml_syntax", "intent_invariants", "kubeconform", "kubectl_dry_run"]
    status: Literal["pass", "fail", "skipped"]
    detail: str | None = None
    skipped_reason: Literal["tool_not_found", "prior_check_failed"] | None = None


class AgentValidationReport(BaseModel):
    aggregate: Literal["PASS", "FAIL", "PARTIAL"]
    k8s_version: str
    checks: list[CheckResult]
