from __future__ import annotations

import json
from typing import Any

from .assessment import KUBERNETES_LIMITATION_MESSAGE, RepositoryAssessmentView


def render_json(view: RepositoryAssessmentView) -> str:
    return json.dumps(_payload(view), indent=2, sort_keys=True) + "\n"


def _payload(view: RepositoryAssessmentView) -> dict[str, Any]:
    payload = view.model_dump(mode="json")
    payload["components_count"] = view.components_count
    payload["kubernetes_manifest_limitation"] = KUBERNETES_LIMITATION_MESSAGE
    return payload
