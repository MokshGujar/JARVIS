from __future__ import annotations

import asyncio
import platform
import shutil
import subprocess
import threading
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Dict

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    from playwright.async_api import async_playwright
    PLAYWRIGHT_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover
    async_playwright = None
    PlaywrightTimeout = TimeoutError
    PLAYWRIGHT_IMPORT_ERROR = exc


class _BrowserThread:
    def __init__(self) -> None:
        self.loop = None
        self.thread = None
        self.ready = threading.Event()
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.init_error = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run_loop, daemon=True, name="JarvisBrowserThread")
        self.thread.start()
        self.ready.wait(timeout=15)

    def _run_loop(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._init())
            self.ready.set()
            self.loop.run_forever()
        except Exception as exc:
            self.init_error = exc
            self.ready.set()

    async def _init(self) -> None:
        self.playwright = await async_playwright().start()

    def run(self, coro, timeout: int = 20):
        if not self.loop:
            raise RuntimeError("Browser thread is not running.")
        if self.init_error is not None:
            if hasattr(coro, "close"):
                coro.close()
            raise RuntimeError(f"Browser thread failed to initialize: {self.init_error}")
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=timeout)

    async def _page(self):
        if not self.browser or not self.browser.is_connected():
            launch_kwargs = {"headless": False, "args": ["--start-maximized"]}
            channel = self._browser_channel()
            if channel:
                launch_kwargs["channel"] = channel
            self.browser = await self.playwright.chromium.launch(**launch_kwargs)
            self.context = await self.browser.new_context(viewport=None)
            self.page = None
        if self.page is None or self.page.is_closed():
            self.page = await self.context.new_page()
        return self.page

    def _browser_channel(self) -> str | None:
        if platform.system() != "Windows":
            return "chrome" if shutil.which("google-chrome") or shutil.which("chrome") else None
        for candidate in ("chrome", "msedge"):
            if shutil.which(candidate):
                return "msedge" if candidate == "msedge" else "chrome"
        return None

    async def go_to(self, url: str) -> str:
        if not url.startswith("http"):
            url = "https://" + url
        page = await self._page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            return f"Opened: {page.url}"
        except PlaywrightTimeout:
            return f"Timeout loading: {url}"

    async def search(self, query: str, engine: str = "google") -> str:
        safe = (query or "").replace(" ", "+")
        engines = {
            "google": f"https://www.google.com/search?q={safe}",
            "bing": f"https://www.bing.com/search?q={safe}",
            "duckduckgo": f"https://duckduckgo.com/?q={safe}",
            "youtube": f"https://www.youtube.com/results?search_query={safe}",
        }
        return await self.go_to(engines.get((engine or "google").lower(), engines["google"]))

    async def click(self, selector: str | None = None, text: str | None = None) -> str:
        page = await self._page()
        if text:
            await page.get_by_text(text, exact=False).first.click(timeout=8000)
            return f"Clicked: {text}"
        if selector:
            await page.click(selector, timeout=8000)
            return f"Clicked: {selector}"
        return "No selector or text provided."

    async def type_text(self, text: str, selector: str | None = None, clear_first: bool = True) -> str:
        page = await self._page()
        element = page.locator(selector).first if selector else page.locator(":focus")
        if clear_first:
            await element.clear()
        await element.type(text or "", delay=45)
        return "Typed in the browser."

    async def scroll(self, direction: str = "down", amount: int = 500) -> str:
        page = await self._page()
        await page.mouse.wheel(0, abs(int(amount or 500)) if direction == "down" else -abs(int(amount or 500)))
        return f"Scrolled {direction}."

    async def get_text(self) -> str:
        page = await self._page()
        text = await page.inner_text("body")
        return text[:4000]

    async def current_url(self) -> str:
        page = await self._page()
        return page.url or "about:blank"

    async def whatsapp_logged_in(self) -> str:
        page = await self._page()
        if "web.whatsapp.com" not in (page.url or ""):
            await page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=15000)
        body = (await page.inner_text("body", timeout=8000))[:4000].lower()
        if "use whatsapp on your computer" in body or "link a device" in body or "qr code" in body:
            return "not_logged_in"
        if "search or start new chat" in body or "chats" in body:
            return "logged_in"
        return "unknown"

    async def close(self) -> str:
        if self.browser:
            await self.browser.close()
        self.browser = None
        self.context = None
        self.page = None
        return "Browser closed."

    async def incognito(self, url: str = "https://www.google.com") -> str:
        if not self.browser or not self.browser.is_connected():
            launch_kwargs = {"headless": False, "args": ["--start-maximized"]}
            channel = self._browser_channel()
            if channel:
                launch_kwargs["channel"] = channel
            self.browser = await self.playwright.chromium.launch(**launch_kwargs)
        self.context = await self.browser.new_context(viewport=None)
        self.page = await self.context.new_page()
        if url:
            if not url.startswith("http"):
                url = "https://" + url
            await self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
        return f"Opened an isolated browser window: {self.page.url}"


class BrowserControlService:
    def __init__(self) -> None:
        self._thread = _BrowserThread()
        self._started = False
        self._lock = threading.Lock()

    def available(self) -> bool:
        return async_playwright is not None

    def execute(self, action: str, **params) -> Dict[str, str | bool]:
        if not self.available():
            return {
                "success": False,
                "action": "browser_control",
                "message": (
                    f"Browser control is unavailable. Import error: {PLAYWRIGHT_IMPORT_ERROR}. "
                    "After installing dependencies run: python -m playwright install chromium"
                ),
            }
        try:
            self._ensure_started()
            action = (action or "").lower().strip()
            timeout = int(params.get("timeout", 20) or 20)
            if action == "go_to":
                message = self._thread.run(self._thread.go_to(params.get("url", "")), timeout=timeout)
            elif action == "search":
                message = self._thread.run(self._thread.search(params.get("query", ""), params.get("engine", "google")), timeout=timeout)
            elif action == "click":
                message = self._thread.run(self._thread.click(params.get("selector"), params.get("text")), timeout=timeout)
            elif action in {"type", "smart_type"}:
                message = self._thread.run(self._thread.type_text(params.get("text", ""), params.get("selector"), params.get("clear_first", True)), timeout=timeout)
            elif action == "scroll":
                message = self._thread.run(self._thread.scroll(params.get("direction", "down"), int(params.get("amount", 500))), timeout=timeout)
            elif action == "get_text":
                message = self._thread.run(self._thread.get_text(), timeout=timeout)
            elif action == "current_url":
                message = self._thread.run(self._thread.current_url(), timeout=timeout)
            elif action == "whatsapp_logged_in":
                message = self._thread.run(self._thread.whatsapp_logged_in(), timeout=timeout)
            elif action == "close":
                message = self._thread.run(self._thread.close(), timeout=timeout)
            elif action == "incognito":
                message = self._thread.run(self._thread.incognito(params.get("url", "https://www.google.com")), timeout=timeout)
            else:
                return {"success": False, "action": "browser_control", "message": f"Unsupported browser action: {action}"}
            return {"success": True, "action": "browser_control", "message": message, "current_url": message if action == "current_url" else ""}
        except FutureTimeout:
            return {"success": False, "action": "browser_control", "message": f"Browser control timed out while running {action}."}
        except Exception as exc:
            detail = str(exc)
            install_hint = " Run: python -m playwright install chromium" if "Executable doesn't exist" in detail or "playwright install" in detail.lower() else ""
            return {"success": False, "action": "browser_control", "message": f"Browser control failed: {detail}.{install_hint}"}

    def _ensure_started(self) -> None:
        with self._lock:
            if not self._started:
                self._thread.start()
                self._started = True
