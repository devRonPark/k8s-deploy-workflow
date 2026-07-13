import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from k8sagent.errors import SessionError
from k8sagent.session import AgentSession, SessionState, SessionStore, advance

FIXED = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)


def make_store(tmp: str) -> SessionStore:
    return SessionStore(Path(tmp), clock=lambda: FIXED, id_factory=lambda: "s-test01")


class SessionTests(unittest.TestCase):
    def test_create_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            session = store.create(k8s_version="1.29", llm_enabled=False)
            self.assertEqual(session.session_id, "s-test01")
            self.assertEqual(session.state, SessionState.CREATED)
            store.save(session)
            loaded = store.load("s-test01")
            self.assertEqual(loaded, session)

    def test_valid_transition_chain(self):
        session = AgentSession(
            session_id="s",
            created_at="t",
            updated_at="t",
            state=SessionState.CREATED,
            k8s_version="1.29",
            llm_enabled=True,
        )
        for state in [
            SessionState.REPO_READY,
            SessionState.ANALYZED,
            SessionState.COMPONENTS_SELECTED,
            SessionState.INTENT_DRAFTED,
            SessionState.INTENT_RESOLVED,
            SessionState.PLAN_APPROVED,
            SessionState.GENERATED,
            SessionState.VALIDATED,
            SessionState.COMPLETED,
        ]:
            session = advance(session, state, clock=lambda: FIXED)
        self.assertEqual(session.state, SessionState.COMPLETED)

    def test_backward_loops_allowed(self):
        base = dict(
            session_id="s",
            created_at="t",
            updated_at="t",
            k8s_version="1.29",
            llm_enabled=True,
        )
        s1 = AgentSession(state=SessionState.PLAN_APPROVED, **base)
        self.assertEqual(
            advance(s1, SessionState.INTENT_RESOLVED, clock=lambda: FIXED).state,
            SessionState.INTENT_RESOLVED,
        )
        s2 = AgentSession(state=SessionState.VALIDATED, **base)
        self.assertEqual(
            advance(s2, SessionState.GENERATED, clock=lambda: FIXED).state,
            SessionState.GENERATED,
        )

    def test_invalid_transition_rejected(self):
        session = AgentSession(
            session_id="s",
            created_at="t",
            updated_at="t",
            state=SessionState.CREATED,
            k8s_version="1.29",
            llm_enabled=True,
        )
        with self.assertRaises(SessionError):
            advance(session, SessionState.GENERATED, clock=lambda: FIXED)

    def test_any_state_can_fail(self):
        session = AgentSession(
            session_id="s",
            created_at="t",
            updated_at="t",
            state=SessionState.ANALYZED,
            k8s_version="1.29",
            llm_enabled=True,
        )
        self.assertEqual(
            advance(session, SessionState.FAILED, clock=lambda: FIXED).state,
            SessionState.FAILED,
        )

    def test_load_missing_session_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SessionError):
                make_store(tmp).load("nope")

    def test_session_file_never_contains_token_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            session = store.create(k8s_version="1.29", llm_enabled=True)
            store.save(session)
            raw = (Path(tmp) / "sessions" / "s-test01" / "session.json").read_text(
                encoding="utf-8"
            )
            payload = json.loads(raw)
            self.assertNotIn("token", raw.lower())
            self.assertNotIn("api_key", set(payload))

    def test_list_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            store.save(store.create(k8s_version="1.29", llm_enabled=True))
            self.assertEqual([s.session_id for s in store.list_sessions()], ["s-test01"])


if __name__ == "__main__":
    unittest.main()
