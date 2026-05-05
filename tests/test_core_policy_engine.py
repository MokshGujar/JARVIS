import unittest

from app.policy.models import PolicyDecisionType, RoutingMode, ToolMetadata, ToolRiskLevel, ToolStatus
from app.policy.policy_engine import PolicyEngine


class CorePolicyEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = PolicyEngine()

    def test_app_open_and_browser_search_are_allowed(self):
        self.assertEqual(self.engine.evaluate("app", "open", {"app": "notepad"}).decision, PolicyDecisionType.ALLOW)
        self.assertEqual(self.engine.evaluate("browser", "search", {"query": "python docs"}).decision, PolicyDecisionType.ALLOW)

    def test_file_delete_and_folder_delete_are_protected(self):
        file_delete = self.engine.evaluate("file", "delete_file", {"path": "notes.txt"})
        folder_delete = self.engine.evaluate("file", "delete_folder", {"path": "Downloads/demo"})

        self.assertEqual(file_delete.decision, PolicyDecisionType.STEP_UP)
        self.assertTrue(file_delete.requires_confirmation)
        self.assertTrue(file_delete.requires_step_up)
        self.assertEqual(folder_delete.decision, PolicyDecisionType.STEP_UP)
        self.assertTrue(folder_delete.requires_confirmation)
        self.assertTrue(folder_delete.requires_step_up)

    def test_terminal_and_non_live_metadata_are_denied(self):
        self.assertEqual(self.engine.evaluate("terminal", "run_command", {"command": "dir"}).decision, PolicyDecisionType.DENY)

        planned = ToolMetadata("future", "developer", ToolStatus.PLANNED, RoutingMode.METADATA_ONLY, ToolRiskLevel.HIGH)
        metadata_only = ToolMetadata("meta", "developer", ToolStatus.LIVE, RoutingMode.METADATA_ONLY, ToolRiskLevel.LOW)
        disabled = ToolMetadata("off", "system", ToolStatus.DISABLED, RoutingMode.DISABLED, ToolRiskLevel.CRITICAL)

        self.assertEqual(self.engine.evaluate("future", "run", {}, metadata=planned).decision, PolicyDecisionType.DENY)
        self.assertEqual(self.engine.evaluate("meta", "read", {}, metadata=metadata_only).decision, PolicyDecisionType.DENY)
        self.assertEqual(self.engine.evaluate("off", "run", {}, metadata=disabled).decision, PolicyDecisionType.DENY)


if __name__ == "__main__":
    unittest.main()
