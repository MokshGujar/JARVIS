import unittest
from unittest.mock import Mock, patch

from app.services import automation_service as automation_module
from app.services.automation_service import AutomationService
from app.services.command_risk_service import CommandRiskService


class SystemCharacterizationTests(unittest.TestCase):
    def test_keyboard_system_hotkeys(self):
        service = AutomationService()
        fake_keyboard = Mock()
        cases = [
            ("volume up", "volume up"),
            ("volume down", "volume down"),
            ("mute", "volume mute"),
            ("show desktop", "windows+d"),
            ("switch window", "alt+tab"),
            ("minimize window", "windows+down"),
            ("fullscreen", "f11"),
        ]
        with patch.object(automation_module, "keyboard", fake_keyboard):
            for command, hotkey in cases:
                with self.subTest(command=command):
                    fake_keyboard.press_and_release.reset_mock()
                    result = service.execute(command)
                    self.assertTrue(result["success"])
                    self.assertEqual(result["action"], "system")
                    self.assertEqual(result["message"], f"Done {service._match_system_command(command) or command}.")
                    fake_keyboard.press_and_release.assert_called_once_with(hotkey)

    def test_keyboard_unavailable_fails_closed(self):
        service = AutomationService()
        with patch.object(automation_module, "keyboard", None), patch.object(automation_module, "KEYBOARD_IMPORT_ERROR", "missing"):
            result = service.execute("volume up")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "system")
        self.assertIn("Keyboard control is not available", result["message"])

    def test_computer_control_actions_delegate_to_service(self):
        service = AutomationService()
        service.computer_control_service = Mock()
        service.computer_control_service.screenshot.return_value = {"success": True, "action": "computer_control", "message": "Screenshot saved"}
        service.computer_control_service.hotkey.return_value = {"success": True, "action": "computer_control", "message": "Pressed ctrl+s."}
        service.computer_control_service.press.return_value = {"success": True, "action": "computer_control", "message": "Pressed enter."}

        screenshot = service.execute("take screenshot")
        hotkey = service.execute("hotkey ctrl+s")
        press = service.execute("press enter")

        self.assertEqual(screenshot["message"], "Screenshot saved")
        self.assertEqual(hotkey["message"], "Pressed ctrl+s.")
        self.assertEqual(press["message"], "Pressed enter.")
        service.computer_control_service.screenshot.assert_called_once()
        service.computer_control_service.hotkey.assert_called_once_with(["ctrl", "s"])
        service.computer_control_service.press.assert_called_once_with("enter")

    def test_extended_settings_delegate_to_settings_service(self):
        service = AutomationService()
        service.computer_settings_service = Mock()
        service.computer_settings_service.can_handle.return_value = True
        service.computer_settings_service.execute.return_value = {"success": True, "action": "computer_settings", "message": "Locked the screen."}

        result = service.execute("lock screen")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "confirmation_required")
        self.assertTrue(result["requires_voice_permission"])
        self.assertFalse(result["requires_face_step_up"])
        service.computer_settings_service.execute.assert_not_called()

    def test_shutdown_restart_and_unsafe_shell_commands_are_blocked_before_execution(self):
        service = AutomationService()
        service.computer_settings_service = Mock()
        service.computer_control_service = Mock()
        commands = ["shutdown the computer", "restart the computer", "run command rm -rf C:\\"]

        for command in commands:
            with self.subTest(command=command):
                result = service.execute(command)
                self.assertFalse(result["success"])
                self.assertEqual(result["action"], "blocked")
                self.assertIn("blocked", result["message"].lower())
        service.computer_settings_service.execute.assert_not_called()
        service.computer_control_service.hotkey.assert_not_called()

    def test_risk_classification_for_power_and_terminal_does_not_request_fresh_step_up(self):
        risk_service = CommandRiskService()

        shutdown = risk_service.classify("shutdown the computer", command_action="automation")
        terminal = risk_service.classify("run command powershell remove item", command_action="automation")
        volume = risk_service.classify("volume up", command_action="automation")

        self.assertFalse(shutdown.step_up_required)
        self.assertFalse(terminal.step_up_required)
        self.assertFalse(volume.step_up_required)


if __name__ == "__main__":
    unittest.main()
