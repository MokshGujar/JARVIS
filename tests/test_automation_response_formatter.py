import unittest

from app.services.automation_response import normalize_automation_response


class AutomationResponseFormatterTests(unittest.TestCase):
    def test_file_create_write_multistep_response_is_natural(self):
        result = normalize_automation_response(
            {
                "success": True,
                "action": "multi_step",
                "message": "{'step_id': 'step4'}",
                "is_multistep": True,
                "step_results": [
                    {"success": True, "planned_action": "create_file", "path": r"C:\Users\Moksh\Desktop\test_jarvis.txt"},
                    {"success": True, "planned_action": "write_file", "path": r"C:\Users\Moksh\Desktop\test_jarvis.txt", "content": "hello"},
                    {"success": True, "planned_action": "verify_exists", "path": r"C:\Users\Moksh\Desktop\test_jarvis.txt"},
                ],
            }
        )

        self.assertEqual(result["message"], "Done, I created test jarvis on your Desktop and wrote hello.")
        self.assertNotIn("step_id", result["message"])
        self.assertLessEqual(len(result["spoken_text"]), 180)

    def test_partial_write_failure_response_is_natural(self):
        result = normalize_automation_response(
            {
                "success": False,
                "action": "write_file",
                "message": "write_file failed",
                "is_multistep": True,
                "partial_success": True,
                "step_results": [
                    {"success": True, "planned_action": "create_file", "path": r"C:\Users\Moksh\Desktop\test_jarvis.txt"},
                    {"success": False, "planned_action": "write_file", "message": "Permission denied"},
                ],
            }
        )

        self.assertEqual(result["message"], "I created the file, but I couldn't write the text into it.")
        self.assertNotIn("Permission", result["message"])

    def test_browser_search_response_is_natural(self):
        result = normalize_automation_response(
            {
                "success": True,
                "action": "google_search",
                "message": "Searching Google for Python docs in Chrome.",
            }
        )

        self.assertEqual(result["message"], "Done, searching for Python docs in Chrome.")

    def test_app_open_response_is_natural(self):
        result = normalize_automation_response(
            {
                "success": True,
                "action": "app_open",
                "message": "Opening Chrome.",
            }
        )

        self.assertEqual(result["message"], "Done, I opened Chrome.")

    def test_confirmation_and_voice_permission_responses_are_short(self):
        confirmation = normalize_automation_response({"success": False, "action": "confirmation_required", "message": "internal policy"})
        auth = normalize_automation_response({"success": False, "action": "auth_required", "message": "internal policy"})

        self.assertEqual(confirmation["message"], "Please confirm before I continue.")
        self.assertEqual(auth["message"], "I need voice permission before I can do that.")


if __name__ == "__main__":
    unittest.main()
