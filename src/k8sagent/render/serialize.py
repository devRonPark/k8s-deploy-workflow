from __future__ import annotations

import yaml


def to_yaml(doc: dict) -> str:
    text = yaml.safe_dump(
        doc,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=False,
    )
    return text.rstrip("\n") + "\n"
