from __future__ import annotations

import yaml


def dump_yaml(resource: dict) -> str:
    return yaml.safe_dump(resource, sort_keys=False, allow_unicode=True)
