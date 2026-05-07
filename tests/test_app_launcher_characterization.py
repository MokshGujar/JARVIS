import unittest
from unittest.mock import Mock, patch

from app.services import automation_service as automation_module
from app.services.automation_service import AutomationService
from app.services.command_risk_service import CommandRiskService


class AppLauncherCharacterizationTests(unittest.TestCase):
    def test_direct_app_commands_use_direct_fallbacks(self):
        service = AutomationService()
        cases = [
            ("open calculator", ["calc.exe"], "Done, I opened calculator."),
            ("open notepad", ["notepad.exe"], "Done, I opened notepad."),
        ]
        with patch("app.connectors.local_app_connector.subprocess.Popen") as popen:
            for command, expected_command, expected_message in cases:
                with self.subTest(command=command):
                    popen.reset_mock()
                    result = service.execute(command)
                    self.assertTrue(result["success"])
                    self.assertEqual(result["action"], "open")
                    self.assertEqual(result["message"], expected_message)
                    popen.assert_called_once_with(expected_command)

    def test_open_file_explorer_is_handled_by_settings_service(self):
        service = AutomationService()
        with patch("app.connectors.local_app_connector.subprocess.Popen") as popen:
            result = service.execute("open file explorer")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "open")
        self.assertEqual(result["message"], "Done, I opened file explorer.")
        popen.assert_called_once_with(["explorer.exe"])

    def test_open_settings_uses_direct_uri(self):
        service = AutomationService()
        with patch("app.connectors.local_app_connector.os.startfile", create=True) as startfile:
            result = service.execute("open settings")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "open")
        self.assertEqual(result["message"], "Done, I opened settings.")
        startfile.assert_called_once_with("ms-settings:")

    def test_open_youtube_uses_browser_control_url(self):
        service = AutomationService()
        with patch("app.connectors.local_app_connector.webbrowser.open") as web_open:
            result = service.execute("open youtube")

            self.assertTrue(result["success"])
            self.assertEqual(result["message"], "Done, I opened youtube.")
            web_open.assert_called_once_with("https://www.youtube.com")

    def test_open_whatsapp_stays_on_whatsapp_path(self):
        service = AutomationService()
        service._open_whatsapp_desktop_or_web = Mock(return_value={"success": True, "action": "open_whatsapp", "message": "Opening WhatsApp Desktop."})

        result = service.execute("open whatsapp")

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "open_whatsapp")
        service._open_whatsapp_desktop_or_web.assert_called_once()

    def test_open_chrome_is_currently_ambiguous_app_or_website(self):
        service = AutomationService()

        result = service.execute("open chrome")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "open")
        self.assertEqual(result["message"], "Do you want me to open chrome as the app or the website?")
        self.assertIsNotNone(service._pending_open_target)

    def test_alias_calc_opens_calculator(self):
        service = AutomationService()
        service._appopener_available = True
        with patch("app.connectors.local_app_connector.appopener_open") as app_open:
            result = service.execute("open calc")

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Done, I opened calc.")
        self.assertEqual(app_open.call_count, 1)
        self.assertEqual(app_open.call_args.args[0], "calc")

    def test_unknown_app_response_when_appopener_fails(self):
        service = AutomationService()
        service._appopener_available = True
        with patch("app.connectors.local_app_connector.appopener_open", side_effect=RuntimeError("missing")):
            result = service.execute("open made up app")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "open")
        self.assertEqual(result["message"], "I could not find an app matching made up.")

    def test_low_risk_app_open_does_not_require_step_up(self):
        risk = CommandRiskService().classify("open calculator", command_action="automation")

        self.assertFalse(risk.step_up_required)

    def test_call_someone_does_not_use_appopener(self):
        service = AutomationService()
        service._appopener_available = True

        with patch("app.connectors.local_app_connector.appopener_open") as mocked_open:
            result = service.execute("call someone")

        mocked_open.assert_not_called()
        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "whatsapp_contact_required")


if __name__ == "__main__":
    unittest.main()
