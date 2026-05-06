import unittest
from unittest.mock import Mock

from app.services.automation_service import AutomationService


class SemanticRoutingReliabilityTests(unittest.TestCase):
    def test_search_files_without_query_asks_clarification_not_google(self):
        service = AutomationService()
        service._open_url = Mock()

        result = service.execute("search files", session_id="sem", turn_id="sem-files")

        self.assertFalse(result["success"])
        self.assertEqual(result["selected_tool"], "file")
        self.assertEqual(result["action"], "search_files")
        self.assertIn("What file name or content", result["message"])
        service._open_url.assert_not_called()

    def test_search_files_for_resume_routes_to_file_tool(self):
        service = AutomationService()
        service._open_url = Mock()
        service._find_files = Mock(return_value={"success": True, "action": "search_files", "message": "Found files.", "query": "resume"})

        result = service.execute("search files for resume", session_id="sem", turn_id="sem-resume")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "file")
        service._find_files.assert_called_once()
        service._open_url.assert_not_called()

    def test_search_google_for_files_still_routes_to_browser_tool(self):
        service = AutomationService()
        service._open_url = Mock()

        result = service.execute("search google for files", session_id="sem", turn_id="sem-google")

        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "browser")
        service._open_url.assert_called_once()

    def test_subject_followup_search_uses_current_subject(self):
        service = AutomationService()
        service._open_url = Mock()

        subject = service.execute("change the subject to MS Dhoni", session_id="sem", turn_id="sem-subject")
        result = service.execute("search about him on Google", session_id="sem", turn_id="sem-followup")

        self.assertTrue(subject["success"])
        self.assertTrue(result["success"])
        self.assertEqual(result["selected_tool"], "browser")
        called_url = service._open_url.call_args[0][0]
        self.assertIn("ms+dhoni", called_url.lower())

    def test_browser_pronoun_without_context_asks_clarification(self):
        service = AutomationService()
        service._open_url = Mock()

        result = service.execute("search about him on Google", session_id="empty-sem", turn_id="sem-missing")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "clarification_required")
        service._open_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
