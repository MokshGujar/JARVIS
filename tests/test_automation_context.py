import time
import unittest

from app.orchestrator.automation_context import AutomationContext, AutomationContextStore
from app.orchestrator.semantic_automation import (
    AutomationDomain,
    AutomationMode,
    SemanticAutomationAction,
    SemanticAutomationIntent,
)


class AutomationContextTests(unittest.TestCase):
    def test_context_stores_last_app_file_text_query_and_window(self):
        context = AutomationContext(session_id="s1", active_window_title="Chrome")
        context.update_from_semantic_action(
            SemanticAutomationAction(
                intent=SemanticAutomationIntent.SEARCH_WEB,
                domain=AutomationDomain.BROWSER,
                mode=AutomationMode.DIRECT_TOOL,
                app="chrome",
                query="Python docs",
                content="safe note",
            )
        )
        context.update_from_tool_result(
            {
                "success": True,
                "action": "create_file",
                "tool_name": "file",
                "data": {"path": r"C:\Users\Moksh\Desktop\note.txt", "content": "hello"},
            }
        )

        self.assertEqual(context.active_app, "chrome")
        self.assertEqual(context.last_browser_query, "Python docs")
        self.assertEqual(context.last_created_file_path, r"C:\Users\Moksh\Desktop\note.txt")
        self.assertEqual(context.last_content, "hello")
        self.assertEqual(context.last_tool_used, "file")

    def test_reference_resolution(self):
        context = AutomationContext(
            session_id="s1",
            active_app="notepad",
            active_window_title="Untitled - Notepad",
            last_focused_app="notepad",
            last_created_file_path=r"C:\tmp\todo.txt",
            last_browser_query="AI news",
        )

        self.assertEqual(context.resolve_reference("it"), r"C:\tmp\todo.txt")
        self.assertEqual(context.resolve_reference("that file"), r"C:\tmp\todo.txt")
        self.assertEqual(context.resolve_reference("that search"), "AI news")
        self.assertEqual(context.resolve_reference("same app"), "notepad")
        self.assertEqual(context.resolve_reference("same window"), "Untitled - Notepad")

    def test_send_and_save_reference_resolution(self):
        context = AutomationContext(session_id="s1")
        context.current_message_draft = {"recipient": "Rahul", "content": "hello"}
        context.last_content = "note content"

        self.assertEqual(context.resolve_reference("send it"), {"recipient": "Rahul", "content": "hello"})
        self.assertEqual(context.resolve_reference("save it"), "note content")

    def test_context_expires_stale_state_and_store_recreates(self):
        context = AutomationContext(session_id="s1", expires_at=time.time() - 1)
        self.assertTrue(context.is_expired())

        store = AutomationContextStore()
        first = store.get("s1")
        first.expires_at = time.time() - 1
        second = store.get("s1")
        self.assertIsNot(first, second)
        self.assertEqual(second.session_id, "s1")

    def test_sensitive_content_is_redacted_and_sensitive_fields_clear(self):
        context = AutomationContext(session_id="s1")
        context.last_typed_text = "api key sk-abcdefghijklmnopqrstuvwxyz"

        redacted = context.redact_sensitive_text("password: hunter2")
        context.clear_sensitive_fields()

        self.assertIn("[REDACTED]", redacted)
        self.assertIn("[REDACTED]", context.last_typed_text)

    def test_failed_action_is_stored(self):
        context = AutomationContext(session_id="s1")

        context.update_from_tool_result({"success": False, "action": "type_text", "message": "focus failed", "tool_name": "app_interaction"})

        self.assertEqual(context.last_failed_action["action"], "type_text")
        self.assertEqual(context.last_tool_used, "app_interaction")

    def test_pending_action_clear_works(self):
        context = AutomationContext(session_id="s1")

        context.set_pending_action("demo", {"target": "file"})
        context.clear_pending_action()

        self.assertIsNone(context.pending_action_type)
        self.assertIsNone(context.current_pending_action)

    def test_confirmation_yes_resolves_only_active_confirmation(self):
        context = AutomationContext(session_id="s1")
        confirmation = context.set_pending_confirmation(
            semantic_action="DELETE_FILE",
            action="delete_file",
            target="note.txt",
            safety_level="CRITICAL",
        )

        unrelated = context.resolve_confirmation_response("yes", expected_action="send_message")
        accepted = context.resolve_confirmation_response("yes", expected_action="delete_file")
        repeated = context.resolve_confirmation_response("yes", expected_action="delete_file")

        self.assertEqual(unrelated.status, "unrelated")
        self.assertEqual(accepted.status, "confirmed")
        self.assertIs(accepted.confirmation, confirmation)
        self.assertEqual(repeated.status, "none")

    def test_confirmation_no_cancels_active_confirmation(self):
        context = AutomationContext(session_id="s1")
        context.set_pending_confirmation(semantic_action="SEND_MESSAGE", action="send_message", recipient="Rahul")

        result = context.resolve_confirmation_response("no")

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.confirmation.status, "cancelled")
        self.assertIsNone(context.last_confirmation_request)

    def test_expired_confirmation_does_not_resolve(self):
        context = AutomationContext(session_id="s1")
        confirmation = context.set_pending_confirmation(semantic_action="DELETE_FILE", action="delete_file", target="note.txt", ttl_seconds=-1)

        result = context.resolve_confirmation_response("yes")

        self.assertEqual(result.status, "expired")
        self.assertEqual(confirmation.status, "expired")

    def test_update_pending_confirmation_recipient_and_content_without_execution(self):
        context = AutomationContext(session_id="s1")
        confirmation = context.set_pending_confirmation(
            semantic_action="SEND_MESSAGE",
            action="send_message",
            target="Rahul",
            recipient="Rahul",
            content="I am late",
        )

        changed_recipient = context.update_pending_confirmation_from_text("change Rahul to Amit")
        changed_message = context.update_pending_confirmation_from_text("change the message to I'll be there soon")

        self.assertTrue(changed_recipient)
        self.assertTrue(changed_message)
        self.assertEqual(confirmation.recipient, "Amit")
        self.assertEqual(confirmation.content, "I'll be there soon")
        self.assertEqual(confirmation.status, "pending")

    def test_duplicate_fingerprints_detect_recent_mutating_duplicates(self):
        context = AutomationContext(session_id="s1")
        first = context.create_fingerprint(
            original_user_text="add milk",
            semantic_action="APPEND_FILE",
            target="todo.txt",
            content="milk",
            timestamp=100.0,
        )
        second = context.create_fingerprint(
            original_user_text="add milk",
            semantic_action="APPEND_FILE",
            target="todo.txt",
            content="milk",
            timestamp=102.0,
        )
        context.record_fingerprint(first)

        self.assertTrue(context.is_duplicate(second, now=102.0, window_seconds=5))
        self.assertFalse(context.is_duplicate(second, now=110.0, window_seconds=5))

    def test_duplicate_fingerprint_different_target_and_read_status(self):
        context = AutomationContext(session_id="s1")
        first = context.create_fingerprint(original_user_text="add milk", semantic_action="APPEND_FILE", target="todo.txt", content="milk", timestamp=100)
        other_target = context.create_fingerprint(original_user_text="add milk", semantic_action="APPEND_FILE", target="other.txt", content="milk", timestamp=101)
        read_action = context.create_fingerprint(original_user_text="what window am I on", semantic_action="READ_ACTIVE_WINDOW", target="active", timestamp=101)
        context.record_fingerprint(first)

        self.assertFalse(context.is_duplicate(other_target, now=101, window_seconds=5))
        self.assertFalse(context.is_duplicate(read_action, now=101, window_seconds=5))
        self.assertIsNotNone(first.content_hash)
        self.assertNotEqual(first.content_hash, "milk")


if __name__ == "__main__":
    unittest.main()
