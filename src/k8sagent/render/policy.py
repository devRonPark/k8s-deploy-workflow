from __future__ import annotations

from k8sagent import __version__


def labels(component_id: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/name": component_id,
        "app.kubernetes.io/part-of": component_id,
        "app.kubernetes.io/managed-by": "k8s-agent",
    }


def annotations(commit_sha: str | None) -> dict[str, str]:
    return {
        "k8s-agent/commit-sha": commit_sha or "unknown",
        "k8s-agent/version": __version__,
    }
