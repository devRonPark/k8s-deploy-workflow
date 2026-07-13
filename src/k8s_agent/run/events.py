from __future__ import annotations

import json
from pathlib import Path

from k8s_agent.models.run import RunEvent


class EventLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, event: RunEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = event.model_dump(mode="json")
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
