import unittest

from app.orchestrator.stt_automation_normalization import normalize_automation_command


class STTAutomationNormalizationTests(unittest.TestCase):
    def test_safe_it_corrects_only_with_automation_context(self):
        unchanged = normalize_automation_command("safe it")
        corrected = normalize_automation_command("safe it", context={"domain": "file"})

        self.assertEqual(unchanged.corrected_text, "safe it")
        self.assertEqual(corrected.corrected_text, "save it")
        self.assertIn("safe_it_to_save_it", corrected.corrections_applied)

    def test_past_it_corrects_only_with_ui_or_clipboard_context(self):
        unchanged = normalize_automation_command("past it", context={"domain": "file"})
        corrected = normalize_automation_command("past it", context={"domain": "clipboard"})

        self.assertEqual(unchanged.corrected_text, "past it")
        self.assertEqual(corrected.corrected_text, "paste it")

    def test_right_hello_corrects_only_with_note_or_file_context(self):
        unchanged = normalize_automation_command("right hello", context={"domain": "browser"})
        corrected = normalize_automation_command("right hello", context={"domain": "note"})

        self.assertEqual(unchanged.corrected_text, "right hello")
        self.assertEqual(corrected.corrected_text, "write hello")

    def test_open_crumb_corrects_chrome_only_with_high_confidence_app_context(self):
        suggested = normalize_automation_command("open crumb")
        corrected = normalize_automation_command("open crumb", context={"domain": "app_control"})

        self.assertEqual(suggested.corrected_text, "open crumb")
        self.assertEqual(suggested.suggested_correction, "open Chrome")
        self.assertLess(suggested.confidence, 0.8)
        self.assertEqual(corrected.corrected_text, "open Chrome")
        self.assertGreaterEqual(corrected.confidence, 0.9)

    def test_normal_conversation_is_unchanged(self):
        result = normalize_automation_command("that is not bad at all")

        self.assertEqual(result.corrected_text, "that is not bad at all")
        self.assertEqual(result.corrections_applied, [])
        self.assertEqual(result.reason, "unchanged")


if __name__ == "__main__":
    unittest.main()
