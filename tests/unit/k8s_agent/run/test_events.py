from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from k8s_agent.models.run import RunEvent
from k8s_agent.run.events import EventLog


class EventLogTests(unittest.TestCase):
    def test_append_writes_jsonl_without_rewriting_existing_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            log = EventLog(path)
            first = RunEvent(
                event_id="event-001",
                run_id="run-001",
                event_type="run_created",
                created_at=datetime(2026, 7, 13, 1, 2, 3, tzinfo=timezone.utc),
                summary="created",
                details={"state": "CREATED"},
            )
            second = first.model_copy(update={"event_id": "event-002", "event_type": "state_transition"})

            log.append(first)
            before = path.read_text()
            log.append(second)

            lines = path.read_text().splitlines()
            self.assertEqual(before, lines[0] + "\n")
            self.assertEqual([json.loads(line)["event_id"] for line in lines], ["event-001", "event-002"])


if __name__ == "__main__":
    unittest.main()
