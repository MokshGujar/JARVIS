import unittest
from unittest.mock import Mock

from app.services.automation_service import AutomationService


class SemanticRoutingReliabilityTests(unittest.TestCase):
    def test_search_files_without_query_asks_clarification_not_google(self):
        service = AutomationService()
        service.app_browser_domain._open_url = Mock()

        result = service.execute("search files", session_id="sem", turn_id="sem-files")

        self.assertFalse(result["success"])
        self.assertEqual(result["selected_tool"], "file")
        self.assertEqual(result["action"], "search_files")
        self.assertEqual(result["status"], "clarification_required")
        self.assertTrue(result["requires_followup"])
        self.assertIn("What file name or content", result["message"])
        service.app_browser_domain._open_url.assert_not_called()

    def test_search_files_for_resume_routes_to_file_tool(self):
        service = AutomationService()
        service.app_browser_domain._open_url = Mock()
        service.file_domain._find_files = Mock(return_value={"success": True, "action": "search_files", "message": "Found files.", "query": "resume"})

        result = service.execute("search files for resume", session_id="sem", turn_id="sem-resume")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "file")
        service.file_domain._find_files.assert_called_once()
        service.app_browser_domain._open_url.assert_not_called()

    def test_search_google_for_files_still_routes_to_browser_tool(self):
        service = AutomationService()
        service.app_browser_domain._open_url = Mock()

        result = service.execute("search google for files", session_id="sem", turn_id="sem-google")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "browser")
        service.app_browser_domain._open_url.assert_called_once()

    def test_search_web_for_files_still_routes_to_browser_tool(self):
        service = AutomationService()
        service.app_browser_domain._open_url = Mock()

        result = service.execute("search web for files", session_id="sem", turn_id="sem-web")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "browser")
        service.app_browser_domain._open_url.assert_called_once()

    def test_subject_followup_search_uses_current_subject(self):
        service = AutomationService()
        service.app_browser_domain._open_url = Mock()

        subject = service.execute("change the subject to MS Dhoni", session_id="sem", turn_id="sem-subject")
        result = service.execute("search about him on Google", session_id="sem", turn_id="sem-followup")

        self.assertTrue(subject["success"])
        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "browser")
        called_url = service.app_browser_domain._open_url.call_args[0][0]
        self.assertIn("ms+dhoni", called_url.lower())

    def test_subject_command_accepts_misspelled_entity_without_browser_or_brain(self):
        service = AutomationService()
        service.app_browser_domain._open_url = Mock()
        result = service.execute("Change the subject to MS Zoni.", session_id="sem", turn_id="sem-zoni")

        context = service._automation_context_for("sem")
        self.assertTrue(result["success"])
        self.assertEqual(context.current_subject, "MS Zoni")
        self.assertEqual(context.last_explicit_entity, "MS Zoni")
        service.app_browser_domain._open_url.assert_not_called()

    def test_browser_pronoun_prefers_current_subject_over_last_browser_query(self):
        service = AutomationService()
        service.app_browser_domain._open_url = Mock()

        service.execute("search google for cats", session_id="sem", turn_id="sem-cats")
        service.execute("change the subject to MS Zoni", session_id="sem", turn_id="sem-zoni")
        result = service.execute("search about him", session_id="sem", turn_id="sem-him")

        self.assertTrue(result["success"])
        called_url = service.app_browser_domain._open_url.call_args[0][0]
        self.assertIn("ms+zoni", called_url.lower())
        self.assertNotIn("cats", called_url.lower())

    def test_neutral_pronoun_can_use_last_browser_query(self):
        service = AutomationService()
        service.app_browser_domain._open_url = Mock()

        service.execute("search google for cats", session_id="sem", turn_id="sem-cats")
        result = service.execute("search about it again", session_id="sem", turn_id="sem-it")

        self.assertTrue(result["success"])
        called_url = service.app_browser_domain._open_url.call_args[0][0]
        self.assertIn("cats", called_url.lower())

    def test_person_pronoun_does_not_fall_back_to_last_browser_query(self):
        service = AutomationService()
        service.app_browser_domain._open_url = Mock()

        service.execute("search google for cats", session_id="sem", turn_id="sem-cats")
        result = service.execute("search about him", session_id="sem", turn_id="sem-him")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "clarification_required")
        self.assertIn("Who should I search for", result["message"])
        self.assertEqual(service.app_browser_domain._open_url.call_count, 1)

    def test_browser_pronoun_without_context_asks_clarification(self):
        service = AutomationService()
        service.app_browser_domain._open_url = Mock()

        result = service.execute("search about him on Google", session_id="empty-sem", turn_id="sem-missing")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "clarification_required")
        service.app_browser_domain._open_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()


