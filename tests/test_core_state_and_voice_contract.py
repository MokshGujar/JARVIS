import sqlite3
import unittest
from uuid import uuid4
from pathlib import Path

from app.core.contracts import AssistantRequest
from app.core.context_builder import ContextBuilder
from app.models import ChatRequest
from app.state.runtime_state import RuntimeStateStore
from app.services.automation_service import AutomationService


def _tmp_sqlite(name: str) -> Path:
    db_path = Path("tests/_tmp") / f"{name}_{uuid4().hex}.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


class FakeConversation:
    def get_or_create_session(self, session_id):
        return session_id or "session-1"

    def format_history_for_llm(self, session_id, exclude_last=False):
        return []


class CoreStateAndVoiceContractTests(unittest.TestCase):
    def test_sqlite_foreign_keys_and_audit_insert(self):
        db_path = _tmp_sqlite("core_state")
        store = RuntimeStateStore(db_path)
        audit_id = store.record_audit_event(
            session_id="s1",
            turn_id="t1",
            event_type="tool_execution",
            intent_action="app.open",
            plan_summary="app.open",
            policy_decision="ALLOW",
            tool_name="app",
            execution_result="open",
        )

        with store.connect() as connection:
            foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
            row = connection.execute("SELECT tool_name FROM audit_events WHERE id=?", (audit_id,)).fetchone()
        self.assertEqual(foreign_keys, 1)
        self.assertEqual(row["tool_name"], "app")

    def test_sqlite_confirmation_state_persists(self):
        db_path = _tmp_sqlite("core_state_confirmations")
        store = RuntimeStateStore(db_path)

        confirmation_id = store.create_pending_confirmation(
            session_id="s1",
            turn_id="t1",
            tool_name="file",
            action="delete_file",
            metadata={"path": "notes.txt"},
        )
        pending = store.get_pending_confirmation(session_id="s1", turn_id="t1")
        store.resolve_confirmation(confirmation_id, status="cancelled")

        self.assertEqual(pending["confirmation_id"], confirmation_id)
        self.assertEqual(pending["metadata"]["path"], "notes.txt")
        self.assertIsNone(store.get_pending_confirmation(session_id="s1", turn_id="t1"))

    def test_sqlite_confirmation_accept_cancel_expire_helpers(self):
        db_path = _tmp_sqlite("core_state_confirmations")
        store = RuntimeStateStore(db_path)

        accepted = store.create_pending_confirmation(session_id="s1", turn_id="t1", tool_name="file", action="overwrite")
        cancelled = store.create_pending_confirmation(session_id="s1", turn_id="t2", tool_name="file", action="delete")
        expired = store.create_pending_confirmation(
            session_id="s1",
            turn_id="t3",
            tool_name="file",
            action="delete",
            metadata={"expires_at": 1},
        )

        store.accept_confirmation(accepted)
        store.cancel_confirmation(cancelled)
        self.assertGreaterEqual(store.expire_pending_confirmations(), 1)

        self.assertEqual(store.get_confirmation(accepted)["status"], "accepted")
        self.assertEqual(store.get_confirmation(cancelled)["status"], "cancelled")
        self.assertEqual(store.get_confirmation(expired)["status"], "expired")

    def test_turn_id_is_preserved_in_context(self):
        request = AssistantRequest(message="open notepad", session_id="s1", turn_id="turn-1", client_request_id="client-1")
        context = ContextBuilder(FakeConversation()).build(request)

        self.assertEqual(context.turn_id, "turn-1")
        self.assertEqual(context.client_request_id, "client-1")
        self.assertEqual(ChatRequest(message="hello", turn_id="turn-2").turn_id, "turn-2")

    def test_empty_transcript_is_ignored_by_automation(self):
        result = AutomationService().execute("   ", session_id="s1", turn_id="t1")

        self.assertEqual(result["action"], "empty_transcript")
        self.assertEqual(result["message"], "")


if __name__ == "__main__":
    unittest.main()
