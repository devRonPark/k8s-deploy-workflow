from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from k8s_agent.errors import AgentError
from k8s_agent.models.run import RunRecord, RunSource, RunState
from k8s_agent.run.store import RunStore


def sample_record(run_id: str = "run-store") -> RunRecord:
    now = datetime(2026, 7, 13, 1, 2, 3, tzinfo=timezone.utc)
    return RunRecord(
        run_id=run_id,
        run_root=Path("/tmp/runs") / run_id,
        state=RunState.CREATED,
        target="development",
        source=RunSource(kind="local", value="/repo/app", ref=None),
        created_at=now,
        updated_at=now,
        last_successful_state=RunState.CREATED,
    )


class RunStoreTests(unittest.TestCase):
    def test_save_and_load_round_trip_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(Path(tmp))

            saved = store.save(sample_record())
            loaded = store.load("run-store")

            self.assertEqual(loaded, saved)
            self.assertIn("state: CREATED", (Path(tmp) / "run-store" / "run.yaml").read_text())

    def test_second_lock_holder_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(Path(tmp))
            store.save(sample_record("locked-run"))

            with store.acquire_lock("locked-run"):
                with self.assertRaisesRegex(AgentError, "RUN-202"):
                    with store.acquire_lock("locked-run"):
                        pass


if __name__ == "__main__":
    unittest.main()
