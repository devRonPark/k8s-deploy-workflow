from __future__ import annotations

import re


def dns_label(value: str) -> str:
    label = re.sub(r"[^a-z0-9-]+", "-", value.lower())
    label = re.sub(r"-+", "-", label).strip("-")
    if not label:
        label = "app"
    return label[:63].strip("-") or "app"


def resource_name(component_id: str, suffix: str) -> str:
    return dns_label(f"{component_id}-{suffix}")
