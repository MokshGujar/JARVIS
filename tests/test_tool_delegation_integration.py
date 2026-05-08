import unittest
from unittest.mock import Mock, patch

from app.services.automation_service import AutomationService


class ToolDelegationIntegrationTests(unittest.TestCase):
    def test_file_command_delegates_to_file_tool_after_system_and_mark_paths(self):
        service = AutomationService()
        fake_file = Mock()
        fake_file.execute.return_value = {"success": True, "action": "file_tool", "message": "file ran"}

        with patch("app.tools.automation_facade_router.FileTool", return_value=fake_file) as file_cls:
            result = service.execute("list files in downloads")

        self.assertEqual(result["action"], "file_tool")
        file_cls.assert_called_once_with(service.file_domain)
        fake_file.execute.assert_called_once()

    def test_app_command_delegates_to_app_tool_after_router_declines_file(self):
        service = AutomationService()
        fake_file = Mock()
        fake_file.name = "file"
        fake_file.can_handle.return_value = True
        fake_file.execute.return_value = None
        fake_app = Mock()
        fake_app.name = "app"
        fake_app.can_handle.return_value = True
        fake_app.execute.return_value = {"success": True, "action": "app_tool", "message": "app ran"}

        with (
            patch("app.tools.automation_facade_router.FileTool", return_value=fake_file) as file_cls,
            patch("app.tools.automation_facade_router.AppTool", return_value=fake_app) as app_cls,
        ):
            result = service.execute("open calculator")

        self.assertEqual(result["action"], "app_tool")
        file_cls.assert_called_once_with(service.file_domain)
        fake_file.execute.assert_not_called()
        app_cls.assert_called_once_with(service.app_browser_domain)
        fake_app.execute.assert_called_once()

    def test_system_command_delegates_to_system_tool_before_file_or_app_tools(self):
        service = AutomationService()
        with patch(
            "app.tools.compatibility_runners.SystemCompatibilityRunner.execute",
            return_value={"success": True, "action": "system_tool", "message": "system ran"},
        ) as system_runner:
            result = service.execute("volume up")

        self.assertEqual(result["action"], "system_tool")
        self.assertEqual(result["selected_tool"], "system")
        system_runner.assert_called_once()
        self.assertEqual(system_runner.call_args.args[0], "volume up")


if __name__ == "__main__":
    unittest.main()

