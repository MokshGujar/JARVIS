from __future__ import annotations

import logging
import os
import subprocess
import webbrowser
from pathlib import Path
from typing import Any

try:
    from AppOpener import close as appopener_close
    from AppOpener import open as appopener_open
    APP_OPENER_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - depends on optional package
    appopener_open = None
    appopener_close = None
    APP_OPENER_IMPORT_ERROR = exc

try:
    import winreg
except Exception:  # pragma: no cover - non-Windows hosts
    winreg = None

logger = logging.getLogger("J.A.R.V.I.S")


class LocalAppConnector:
    """Connector boundary for local app, URL, and process launch primitives."""

    def __init__(self, browser_control_service: Any | None = None) -> None:
        self.browser_control_service = browser_control_service

    @property
    def appopener_available(self) -> bool:
        return appopener_open is not None and appopener_close is not None

    @property
    def appopener_error(self) -> object | None:
        return APP_OPENER_IMPORT_ERROR

    def appopener_unavailable(self, action: str) -> dict[str, str | bool]:
        message = "AppOpener is not available on this machine."
        if APP_OPENER_IMPORT_ERROR is not None:
            message = f"{message} Import error: {APP_OPENER_IMPORT_ERROR}"
        return {"success": False, "action": action, "message": message}

    def open_web_target(self, url: str) -> None:
        webbrowser.open(url)
        logger.info("[AUTOMATION] Opened web target: %s", url)

    def open_path(self, path: str | Path) -> None:
        os.startfile(str(path))  # type: ignore[attr-defined]
        logger.info("[AUTOMATION] Opened path: %s", path)

    def open_app_candidate(self, candidate: str) -> None:
        if appopener_open is None:
            raise RuntimeError(self.appopener_unavailable("open")["message"])
        appopener_open(candidate, match_closest=True, output=False, throw_error=True)
        logger.info("[AUTOMATION] Opened app via AppOpener: %s", candidate)

    def close_app_candidate(self, candidate: str) -> None:
        if appopener_close is None:
            raise RuntimeError(self.appopener_unavailable("close")["message"])
        appopener_close(candidate, match_closest=True, output=False, throw_error=True)
        logger.info("[AUTOMATION] Closed app via AppOpener: %s", candidate)

    def open_url(self, url: str, *, browser: str | None = None) -> None:
        normalized_browser = (browser or "").strip().lower()
        if normalized_browser:
            executable = self.resolve_browser_executable(normalized_browser)
            if executable:
                try:
                    subprocess.Popen([executable, url])
                    logger.info("[AUTOMATION] Opened URL in native browser %s: %s", normalized_browser, url)
                    return
                except Exception as exc:
                    logger.warning("[AUTOMATION] Native browser launch failed for %s: %s", normalized_browser, exc)
        else:
            try:
                if webbrowser.open(url):
                    logger.info("[AUTOMATION] Opened URL with system browser: %s", url)
                    return
            except Exception as exc:
                logger.warning("[AUTOMATION] System browser open failed: %s", exc)

        if self.browser_control_service is None:
            raise RuntimeError("Browser control failed.")
        result = self.browser_control_service.execute("go_to", url=url)
        if not bool(result.get("success")):
            raise RuntimeError(str(result.get("message") or "Browser control failed."))
        logger.info("[AUTOMATION] BrowserControlService opened URL: %s", url)

    def resolve_browser_process_name(self, browser: str) -> str | None:
        mapping = {
            "chrome": "chrome.exe",
            "google chrome": "chrome.exe",
            "edge": "msedge.exe",
            "microsoft edge": "msedge.exe",
        }
        return mapping.get(browser)

    def is_process_running(self, executable_name: str) -> bool:
        if not executable_name:
            return False
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {executable_name}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            return False
        output = f"{result.stdout}\n{result.stderr}".lower()
        return executable_name.lower() in output

    def resolve_browser_executable(self, browser: str) -> str | None:
        mapping = {
            "chrome": "chrome.exe",
            "google chrome": "chrome.exe",
            "edge": "msedge.exe",
            "microsoft edge": "msedge.exe",
        }
        executable_name = mapping.get(browser)
        if not executable_name:
            return None

        for root in filter(None, [getattr(winreg, "HKEY_CURRENT_USER", None), getattr(winreg, "HKEY_LOCAL_MACHINE", None)]):
            try:
                with winreg.OpenKey(root, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}") as key:
                    value, _ = winreg.QueryValueEx(key, None)
                    if value and Path(str(value)).exists():
                        return str(value)
            except Exception:
                continue
        return executable_name

    def direct_open_fallback(
        self,
        target: str,
        *,
        direct_open_uris: dict[str, str],
        direct_open_commands: dict[str, list[str]],
    ) -> dict[str, str | bool] | None:
        normalized = " ".join((target or "").strip().lower().split())
        browser_executable = self.resolve_browser_executable(normalized)
        if browser_executable:
            try:
                subprocess.Popen([browser_executable])
                logger.info("[AUTOMATION] Opened browser executable directly: %s", browser_executable)
                return {"success": True, "action": "open", "message": f"Opening {target}."}
            except Exception as exc:
                return {"success": False, "action": "open", "message": f"I could not open {target}: {exc}"}

        uri = direct_open_uris.get(normalized)
        if uri:
            try:
                os.startfile(uri)  # type: ignore[attr-defined]
                logger.info("[AUTOMATION] Opened direct URI target: %s", uri)
                return {"success": True, "action": "open", "message": f"Opening {target}."}
            except Exception as exc:
                return {"success": False, "action": "open", "message": f"I could not open {target}: {exc}"}

        command = direct_open_commands.get(normalized)
        if not command:
            return None
        try:
            subprocess.Popen(command)
            logger.info("[AUTOMATION] Opened direct command target: %s", command)
            return {"success": True, "action": "open", "message": f"Opening {target}."}
        except Exception as exc:
            return {"success": False, "action": "open", "message": f"I could not open {target}: {exc}"}

    def direct_close_fallback(self, target: str, *, direct_close_executables: dict[str, str]) -> dict[str, str | bool] | None:
        normalized = " ".join((target or "").strip().lower().split())
        executable = direct_close_executables.get(normalized)
        if not executable:
            return None
        try:
            result = subprocess.run(["taskkill", "/IM", executable, "/F"], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                details = (result.stderr or result.stdout or "").strip() or "process not found"
                return {"success": False, "action": "close", "message": f"I could not find an open app matching {target}: {details}"}
            logger.info("[AUTOMATION] Closed direct executable target: %s", executable)
            return {"success": True, "action": "close", "message": f"Closing {target}."}
        except Exception as exc:
            return {"success": False, "action": "close", "message": f"I could not close {target}: {exc}"}
