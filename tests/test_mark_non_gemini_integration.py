import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.services import automation_service as automation_module
from app.services import computer_control_service as computer_control_module
from app.services import message_action_service as message_action_module
from app.services.automation_service import AutomationService
from app.services.computer_control_service import ComputerControlService
from app.services.message_action_service import MessageActionService
from app.services.safe_command_info_service import SafeCommandInfoService
from app.services.youtube_tools_service import YouTubeToolsService


class MarkNonGeminiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / "_tmp" / "mark_non_gemini"
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)
        self.desktop = self.root / "Desktop"
        self.desktop.mkdir()
        self.patcher_base = patch.object(automation_module, "BASE_DIR", self.root)
        self.patcher_aliases = patch.object(
            AutomationService,
            "USER_PATH_ALIASES",
            {
                "desktop": self.desktop,
                "documents": self.root / "Documents",
                "downloads": self.root / "Downloads",
                "home": self.root,
                "music": self.root / "Music",
                "pictures": self.root / "Pictures",
                "videos": self.root / "Videos",
            },
        )
        self.patcher_base.start()
        self.patcher_aliases.start()
        self.service = AutomationService()

    def tearDown(self):
        self.patcher_aliases.stop()
        self.patcher_base.stop()
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_optional_computer_control_dependency_unavailable(self):
        with patch.object(computer_control_module, "pyautogui", None), patch.object(
            computer_control_module, "PYAUTOGUI_IMPORT_ERROR", RuntimeError("missing")
        ):
            result = ComputerControlService().press("enter")

        self.assertFalse(result["success"])
        self.assertIn("Computer control is not available", result["message"])

    def test_computer_typing_hotkey_clipboard_routing(self):
        fake_control = Mock()
        fake_control.type_text.return_value = {"success": True, "action": "computer_control", "message": "typed"}
        fake_control.hotkey.return_value = {"success": True, "action": "computer_control", "message": "hotkey"}
        fake_control.clipboard_copy.return_value = {"success": True, "action": "computer_control", "message": "clip"}
        self.service.computer_control_service = fake_control

        typed = self.service.execute("smart type hello world")
        hotkeyed = self.service.execute("hotkey ctrl+shift+t")
        clip = self.service.execute("read clipboard")

        self.assertTrue(typed["success"])
        fake_control.type_text.assert_called_once_with("hello world", clear_first=True)
        self.assertTrue(hotkeyed["success"])
        fake_control.hotkey.assert_called_once_with(["ctrl", "shift", "t"])
        self.assertTrue(clip["success"])
        fake_control.clipboard_copy.assert_called_once_with()

    def test_browser_control_dispatch_without_launching_real_browser(self):
        fake_browser = Mock()
        fake_browser.execute.return_value = {"success": True, "action": "browser_control", "message": "searched"}
        self.service.browser_control_service = fake_browser

        result = self.service.execute("browser search python docs")

        self.assertTrue(result["success"])
        fake_browser.execute.assert_called_once_with("search", query="python docs", engine="google")

    def test_send_message_pending_confirm_cancel_flow(self):
        fake_sender = Mock()
        fake_sender.prepare.return_value = {
            "success": False,
            "action": "send_message_pending",
            "message": "Ready. Say yes.",
            "pending": {"platform": "whatsapp", "receiver": "Alex", "message": "hello"},
        }
        fake_sender.send.return_value = {"success": True, "action": "send_message_sent", "message": "sent"}
        self.service.message_action_service = fake_sender

        pending = self.service.execute("send whatsapp message to Alex saying hello")
        sent = self.service.execute("yes")

        self.assertFalse(pending["success"])
        self.assertEqual(pending["action"], "send_message_pending")
        self.assertTrue(sent["success"])
        fake_sender.send.assert_called_once_with({"platform": "whatsapp", "receiver": "Alex", "message": "hello"})

        self.service.message_action_service.prepare.return_value = {
            "success": False,
            "action": "send_message_pending",
            "message": "Ready. Say yes.",
            "pending": {"platform": "telegram", "receiver": "Alex", "message": "hello"},
        }
        self.service.execute("send telegram message to Alex saying hello")
        cancelled = self.service.execute("no")

        self.assertTrue(cancelled["success"])
        self.assertEqual(cancelled["action"], "confirmation_cancelled")
        self.assertEqual(fake_sender.send.call_count, 1)

    def test_whatsapp_web_numeric_send_uses_phone_url_after_confirmation(self):
        fake_pyautogui = Mock()

        with patch.object(message_action_module, "pyautogui", fake_pyautogui), patch.object(
            message_action_module, "webbrowser"
        ) as fake_webbrowser, patch.object(message_action_module.time, "sleep"):
            result = MessageActionService().send(
                {"platform": "whatsapp", "receiver": "+91 98765 43210", "message": "hello world"}
            )

        self.assertTrue(result["success"])
        opened_url = fake_webbrowser.open.call_args.args[0]
        self.assertIn("https://web.whatsapp.com/send?", opened_url)
        self.assertIn("phone=919876543210", opened_url)
        self.assertIn("text=hello%20world", opened_url)
        fake_pyautogui.press.assert_called_once_with("enter")

    def test_whatsapp_web_named_recipient_does_not_auto_send(self):
        fake_pyautogui = Mock()

        with patch.object(message_action_module, "pyautogui", fake_pyautogui), patch.object(
            message_action_module, "webbrowser"
        ) as fake_webbrowser:
            result = MessageActionService().send(
                {"platform": "whatsapp", "receiver": "Alex", "message": "hello"}
            )

        self.assertFalse(result["success"])
        self.assertIn("Android phone companion", result["message"])
        fake_webbrowser.open.assert_not_called()
        fake_pyautogui.press.assert_not_called()

    def test_game_install_schedule_confirmation_flow(self):
        fake_game = Mock()
        fake_game.prepare_sensitive.return_value = {
            "success": False,
            "action": "game_confirmation",
            "message": "Open store. Say yes.",
            "pending": {"action": "install", "target": "Portal"},
        }
        fake_game.confirm.return_value = {"success": True, "action": "game", "message": "opened"}
        self.service.game_service = fake_game

        pending = self.service.execute("install Portal on steam")
        confirmed = self.service.execute("confirm")

        self.assertFalse(pending["success"])
        self.assertEqual(pending["action"], "game_confirmation")
        self.assertTrue(confirmed["success"])
        fake_game.confirm.assert_called_once_with({"action": "install", "target": "Portal"})

    def test_game_routing_ignores_generic_chat_phrases(self):
        self.assertFalse(self.service.looks_like_automation_request("tell me an epic story"))
        self.assertFalse(self.service.looks_like_automation_request("tell me a game fact"))

    def test_game_routing_still_handles_clear_game_commands(self):
        self.assertTrue(self.service.looks_like_automation_request("open steam"))
        self.assertTrue(self.service.looks_like_automation_request("steam download status"))
        pending = self.service.execute("install Portal on steam")
        self.assertFalse(pending["success"])
        self.assertEqual(pending["action"], "game_confirmation")

    def test_safe_command_info_map_and_unsupported_commands(self):
        service = SafeCommandInfoService()
        with patch("app.services.safe_command_info_service.platform.system", return_value="Windows"), patch(
            "app.services.safe_command_info_service.subprocess.run"
        ) as fake_run:
            fake_run.return_value = Mock(stdout="Caption=C:\n", stderr="")
            result = service.execute("show disk space")

        self.assertTrue(result["success"])
        self.assertIn("Caption=C:", result["message"])

        unsupported = service.execute("run command echo hello")
        self.assertFalse(unsupported["success"])
        self.assertIn("hardcoded safe", unsupported["message"])

    def test_youtube_transcript_summary_uses_mocked_groq(self):
        fake_groq = Mock()
        fake_groq.get_response.return_value = "Short summary"
        service = YouTubeToolsService(groq_service=fake_groq)

        with patch.object(service, "_get_transcript", return_value="transcript text"):
            result = service.summarize("https://www.youtube.com/watch?v=abcdefghijk")

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Short summary")
        fake_groq.get_response.assert_called_once()

    def test_file_delete_moves_to_recycle_bin_only_after_confirmation(self):
        target = self.desktop / "old.txt"
        target.write_text("old", encoding="utf-8")
        fake_trash = Mock()

        first = self.service.execute(f"delete file {target}")
        with patch.object(automation_module, "send2trash", fake_trash):
            confirmed = self.service.execute("yes")

        self.assertFalse(first["success"])
        self.assertTrue(confirmed["success"])
        fake_trash.assert_called_once_with(str(target))


if __name__ == "__main__":
    unittest.main()
