import unittest
from unittest.mock import Mock, patch

from app.services.automation_service import AutomationService


class CanonicalChainObservabilityTests(unittest.TestCase):
    def test_open_app_emits_canonical_boundary_logs(self):
        service = AutomationService()
        with (
            patch("app.tools.compatibility_runners.AppCompatibilityRunner.execute", return_value={"success": True, "action": "open", "message": "Opening calculator."}),
            self.assertLogs(level="INFO") as captured,
        ):
            result = service.execute("open calculator", session_id="obs", turn_id="obs-open")

        self.assertTrue(result["success"])
        logs = "\n".join(captured.output)
        self.assertIn("[ORCHESTRATOR]", logs)
        self.assertIn("[POLICY]", logs)
        self.assertIn("[TOOL_REGISTRY]", logs)
        self.assertIn("[TOOL_EXECUTOR]", logs)
        self.assertIn("[TOOL]", logs)
        self.assertIn("AppTool", logs)

    def test_browser_search_emits_canonical_boundary_logs(self):
        service = AutomationService()
        service.app_browser_domain._open_url = Mock()
        with self.assertLogs(level="INFO") as captured:
            result = service.execute("search google for cats", session_id="obs", turn_id="obs-search")

        self.assertTrue(result["success"])
        logs = "\n".join(captured.output)
        self.assertIn("[ORCHESTRATOR]", logs)
        self.assertIn("[POLICY]", logs)
        self.assertIn("[TOOL_REGISTRY]", logs)
        self.assertIn("[TOOL_EXECUTOR]", logs)
        self.assertIn("[TOOL]", logs)
        self.assertIn("BrowserTool", logs)

    def test_delete_file_policy_log_blocks_execution(self):
        service = AutomationService()
        with (
            patch.object(service.file_domain, "_delete_file", side_effect=AssertionError("delete bypass")),
            self.assertLogs(level="INFO") as captured,
        ):
            result = service.execute("delete file notes.txt", session_id="obs", turn_id="obs-delete")

        self.assertEqual(result["action"], "confirmation_required")
        logs = "\n".join(captured.output)
        self.assertIn("[POLICY]", logs)
        self.assertIn('decision="STEP_UP"', logs)
        self.assertIn("[TOOL_EXECUTOR]", logs)
        self.assertIn('status="blocked"', logs)


if __name__ == "__main__":
    unittest.main()

