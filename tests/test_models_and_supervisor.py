import unittest

from app.models import ChatRequest, JarvisActions, TTSRequest
import run


class ModelAndStartupTests(unittest.TestCase):
    def test_chat_and_tts_validation_accept_expected_payloads(self):
        chat = ChatRequest(message="hello", session_id=None, tts=True)
        tts = TTSRequest(text="Yes, Sir?")

        self.assertEqual(chat.message, "hello")
        self.assertTrue(chat.tts)
        self.assertEqual(tts.text, "Yes, Sir?")

    def test_jarvis_actions_lists_are_not_shared(self):
        first = JarvisActions()
        second = JarvisActions()

        first.wopens.append("notepad")

        self.assertEqual(second.wopens, [])

    def test_wake_word_supervisor_is_removed(self):
        self.assertFalse(hasattr(run, "BackendSupervisor"))
        self.assertFalse(hasattr(run, "WAKE_PHRASES"))
        self.assertTrue(hasattr(run, "run_launcher"))


if __name__ == "__main__":
    unittest.main()
