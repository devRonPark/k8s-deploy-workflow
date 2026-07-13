from __future__ import annotations


def labels(component_id: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/name": component_id,
        "app.kubernetes.io/part-of": component_id,
        "app.kubernetes.io/managed-by": "preanalyzer",
    }


def annotations(commit_sha: str | None, rules_version: str) -> dict[str, str]:
    return {
        "preanalyzer/commit-sha": commit_sha or "unknown",
        "preanalyzer/rules-version": rules_version,
    }
