import shutil
import unittest
from pathlib import Path

from app.services.chat_session_store import ChatSessionStore


class ChatSessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / "_tmp" / "chat_session_store"
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)
        self.store = ChatSessionStore(self.root, max_history_turns=2)

    def tearDown(self):
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_session_id_validation_rejects_path_traversal(self):
        self.assertTrue(self.store.validate_session_id("session-123"))
        self.assertFalse(self.store.validate_session_id("../secret"))
        self.assertFalse(self.store.validate_session_id("folder\\secret"))
        self.assertFalse(self.store.validate_session_id("user@example.com"))

    def test_save_load_and_format_history(self):
        session_id = self.store.get_or_create_session("abc123")
        self.store.add_message(session_id, "user", "first")
        self.store.add_message(session_id, "assistant", "one")
        self.store.add_message(session_id, "user", "second")
        self.store.add_message(session_id, "assistant", "two")
        self.store.add_message(session_id, "user", "third")
        self.store.add_message(session_id, "assistant", "three")

        self.store.save_chat_session(session_id, log_timing=False)

        reloaded = ChatSessionStore(self.root, max_history_turns=2)
        self.assertTrue(reloaded.load_session_from_disk(session_id))

        history = reloaded.format_history_for_llm(session_id)
        self.assertEqual(history, [("second", "two"), ("third", "three")])


if __name__ == "__main__":
    unittest.main()
