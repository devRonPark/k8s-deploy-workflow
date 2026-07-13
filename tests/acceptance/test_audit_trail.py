from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from k8s_agent.application import AgentApplication
from k8s_agent.cli import PrepareRequest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "repos"


class AuditTrailAcceptanceTests(unittest.TestCase):
    def test_prepare_audit_trail_records_tools_without_leaking_secret_canary(self):
        canary = "TASK19_RUN_DIR_SECRET_CANARY"
        with tempfile.TemporaryDirectory() as tmp:
            state_home = Path(tmp) / "state"
            repo = Path(tmp) / "repo"
            shutil.copytree(FIXTURES / "node-express-like", repo)
            (repo / ".env").write_text(f"TOKEN={canary}\n", encoding="utf-8")

            app = AgentApplication(
                state_home=state_home,
                clock=lambda: datetime(2026, 7, 14, tzinfo=timezone.utc),
            )
            outcome = app.prepare(
                PrepareRequest(
                    repo_url=None,
                    local_path=repo,
                    ref=None,
                    target="development",
                    non_interactive=False,
                    answers_file=None,
                )
            )

            run_root = outcome.run_root
            events = [
                json.loads(line)
                for line in (run_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            run_text = "\n".join(
                path.read_text(encoding="utf-8", errors="ignore")
                for path in run_root.rglob("*")
                if path.is_file()
            )

        tool_events = [event for event in events if event["event_type"] == "tool_execution"]
        self.assertTrue(tool_events)
        self.assertTrue(any(event["details"].get("tool") == "git" for event in tool_events))
        self.assertNotIn(canary, run_text)
        self.assertNotIn(canary, repr(events))


if __name__ == "__main__":
    unittest.main()
