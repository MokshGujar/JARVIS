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

    def test_semantic_confirmation_responses_are_natural(self):
        required = normalize_automation_response(
            {
                "success": False,
                "action": "semantic_confirmation_required",
                "message": "I need confirmation before deleting meeting note.txt. Should I delete it?",
                "confirmation_id": "confirm-secret",
            }
        )
        blocked = normalize_automation_response(
            {
                "success": False,
                "action": "semantic_confirmation_accepted_disabled",
                "message": "I have confirmation, but deleting files is not enabled in this phase.",
            }
        )
        cancelled = normalize_automation_response(
            {"success": False, "action": "semantic_confirmation_cancelled", "message": "Cancelled. I did not send it."}
        )

        self.assertEqual(required["message"], "I need confirmation before deleting meeting note.txt. Should I delete it?")
        self.assertEqual(blocked["message"], "I have confirmation, but deleting files is not enabled in this phase.")
        self.assertEqual(cancelled["message"], "Cancelled. I did not send it.")
        self.assertNotIn("confirm-secret", required["message"])

    def test_response_formatter_hides_internal_repr_and_enums(self):
        raw = normalize_automation_response({"success": False, "action": "semantic_action_blocked", "message": "SEND_MESSAGE_AFTER_CONFIRMATION"})
        tool_result = normalize_automation_response({"success": False, "action": "write_file", "message": "ToolResult(success=False)"})

        self.assertNotIn("SEND_MESSAGE_AFTER_CONFIRMATION", raw["message"])
        self.assertNotIn("ToolResult", tool_result["message"])

    def test_response_formatter_hides_user_facing_leak_blacklist(self):
        blocked_terms = (
            "automation supports opening and closing apps",
            "supported automation commands: open, close",
            "ToolResult(success=False)",
            "SEND_MESSAGE_AFTER_CONFIRMATION",
            "Traceback (most recent call last)",
            '{"success": false}',
            "semantic failed",
            "internal policy decision denied",
        )

        for message in blocked_terms:
            with self.subTest(message=message):
                result = normalize_automation_response({"success": False, "action": "unsupported", "message": message})

                lowered = result["message"].lower()
                self.assertNotIn("automation supports", lowered)
                self.assertNotIn("supported automation commands", lowered)
                self.assertNotIn("toolresult", lowered)
                self.assertNotIn("send_message_after_confirmation", lowered)
                self.assertNotIn("traceback", lowered)
                self.assertFalse(result["message"].lstrip().startswith("{"))
                self.assertNotIn("semantic failed", lowered)
                self.assertNotIn("policy decision", lowered)

    def test_tool_unavailable_and_dependency_failure_are_natural(self):
        missing = normalize_automation_response({"success": False, "action": "tool_not_found", "message": "No tool is registered for planned step step1: terminal."})
        dependency = normalize_automation_response({"success": False, "action": "dependency_failed", "message": "Step step3 could not run because step2 failed."})

        self.assertEqual(missing["message"], "That tool is not available right now.")
        self.assertEqual(dependency["message"], "I started that, but a required step did not finish.")

    def test_uncertain_semantic_clarification_is_natural(self):
        result = normalize_automation_response(
            {
                "success": False,
                "action": "semantic_clarification_required",
                "message": "Did you mean put world in it?",
            }
        )

        self.assertEqual(result["message"], "Did you mean put world in it?")
        self.assertEqual(result["spoken_text"], "Did you mean put world in it?")


if __name__ == "__main__":
    unittest.main()
