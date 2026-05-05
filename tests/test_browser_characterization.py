import asyncio
import unittest
from unittest.mock import Mock, patch

from app.services import browser_control_service as browser_module
from app.services.automation_service import AutomationService
from app.services.browser_control_service import BrowserControlService, FutureTimeout


class FakeBrowserThread:
    def __init__(self):
        self.started = False

    def start(self):
        self.started = True

    def run(self, coro, timeout=20):
        return asyncio.run(coro)

    async def go_to(self, url):
        return f"Opened: {url if str(url).startswith('http') else 'https://' + url}"

    async def search(self, query, engine="google"):
        return f"Searched {engine}: {query}"

    async def click(self, selector=None, text=None):
        return f"Clicked: {text or selector}"

    async def type_text(self, text, selector=None, clear_first=True):
        return f"Typed: {text} clear={clear_first}"

    async def scroll(self, direction="down", amount=500):
        return f"Scrolled {direction} {amount}"

    async def get_text(self):
        return "body text"

    async def current_url(self):
        return "https://example.com"

    async def whatsapp_logged_in(self):
        return "logged_in"

    async def close(self):
        return "Browser closed."

    async def incognito(self, url="https://www.google.com"):
        return f"Opened an isolated browser window: {url}"


class BrowserCharacterizationTests(unittest.TestCase):
    def make_service(self):
        service = BrowserControlService()
        service._thread = FakeBrowserThread()
        return service

    def test_browser_control_success_actions_keep_response_shape(self):
        with patch.object(browser_module, "async_playwright", object()):
            service = self.make_service()

            cases = [
                ("go_to", {"url": "example.com"}, "Opened: https://example.com"),
                ("search", {"query": "Jarvis", "engine": "google"}, "Searched google: Jarvis"),
                ("click", {"text": "Accept"}, "Clicked: Accept"),
                ("click", {"selector": "#ok"}, "Clicked: #ok"),
                ("type", {"text": "hello"}, "Typed: hello clear=True"),
                ("scroll", {"direction": "up", "amount": 300}, "Scrolled up 300"),
                ("get_text", {}, "body text"),
                ("current_url", {}, "https://example.com"),
                ("whatsapp_logged_in", {}, "logged_in"),
                ("close", {}, "Browser closed."),
                ("incognito", {"url": "https://example.com"}, "Opened an isolated browser window: https://example.com"),
            ]
            for action, params, message in cases:
                with self.subTest(action=action):
                    result = service.execute(action, **params)
                    self.assertTrue(result["success"])
                    self.assertEqual(result["action"], "browser_control")
                    self.assertEqual(result["message"], message)

    def test_current_url_sets_current_url_field(self):
        with patch.object(browser_module, "async_playwright", object()):
            result = self.make_service().execute("current_url")

        self.assertEqual(result["current_url"], "https://example.com")

    def test_unavailable_playwright_fails_with_install_hint(self):
        with patch.object(browser_module, "async_playwright", None), patch.object(browser_module, "PLAYWRIGHT_IMPORT_ERROR", "missing"):
            result = self.make_service().execute("go_to", url="example.com")

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "browser_control")
        self.assertIn("Browser control is unavailable", result["message"])

    def test_timeout_fails_closed(self):
        class TimeoutThread(FakeBrowserThread):
            def run(self, coro, timeout=20):
                coro.close()
                raise FutureTimeout()

        with patch.object(browser_module, "async_playwright", object()):
            service = BrowserControlService()
            service._thread = TimeoutThread()
            result = service.execute("get_text")

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Browser control timed out while running get_text.")

    def test_unsupported_action_fails_closed(self):
        with patch.object(browser_module, "async_playwright", object()):
            result = self.make_service().execute("unsupported")

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Unsupported browser action: unsupported")

    def test_automation_browser_command_parsing_delegates_exact_actions(self):
        service = AutomationService()
        service.browser_control_service = Mock()
        service.browser_control_service.execute.return_value = {"success": True, "action": "browser_control", "message": "ok"}

        cases = [
            ("browser search ai news", ("search",), {"query": "ai news", "engine": "google"}),
            ("go to example.com", ("go_to",), {"url": "example.com"}),
            ("browser get text", ("get_text",), {}),
            ("close browser", ("close",), {}),
            ("browser scroll up 300", ("scroll",), {"direction": "up", "amount": 300}),
            ("incognito example.com", ("incognito",), {"url": "example.com"}),
        ]

        for command, args, kwargs in cases:
            with self.subTest(command=command):
                service.browser_control_service.execute.reset_mock()
                service.execute(command)
                service.browser_control_service.execute.assert_called_once_with(*args, **kwargs)

        for command in ("browser click Accept", "browser type hello"):
            with self.subTest(command=command):
                service.browser_control_service.execute.reset_mock()
                result = service.execute(command)
                self.assertFalse(result["success"])
                self.assertEqual(result["action"], "confirmation_required")
                service.browser_control_service.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
