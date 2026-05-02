"""
RUN SCRIPT - Start J.A.R.V.I.S through the startup face gate.

The wake-word supervisor has been removed. Normal startup launches the FastAPI
backend as a managed subprocess, waits for /health, then opens the browser-
based face-gate launcher served from the local FastAPI app.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn


HOST = "0.0.0.0"
PORT = 8000
LOCAL_BASE_URL = "http://127.0.0.1:8000"
HEALTH_URL = f"{LOCAL_BASE_URL}/health"
LAUNCHER_URL = "http://localhost:8000/launcher/"
DEFAULT_STARTUP_TIMEOUT_SECONDS = 120


def run_server(*, reload: bool = False) -> None:
    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=reload,
        access_log=False,
    )


def wait_for_health(
    url: str = HEALTH_URL,
    *,
    timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
    interval_seconds: float = 0.35,
    process: subprocess.Popen | None = None,
) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if process is not None and process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if 200 <= response.status < 300:
                    return True
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(max(0.0, interval_seconds))
    return False


class ManagedBackend:
    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        if self.process is not None:
            return
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                HOST,
                "--port",
                str(PORT),
                "--log-level",
                "info",
                "--no-access-log",
            ],
            cwd=str(Path(__file__).resolve().parent),
            stdin=subprocess.DEVNULL,
        )

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def wait(self) -> int:
        if self.process is None:
            return 0
        return self.process.wait()


def show_fatal_error(message: str) -> None:
    print(f"[ERROR] {message}")


def should_stop_backend_after_launcher(*, browser_opened: bool, keep_backend: bool) -> bool:
    return False


def _preferred_browser_launchers(url: str) -> list[list[str]]:
    if sys.platform != "win32":
        return []

    candidates = [
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    commands: list[list[str]] = []
    for executable in candidates:
        if executable.exists():
            commands.append([str(executable), "--new-window", url])
    return commands


def open_browser_launcher(url: str = LAUNCHER_URL) -> bool:
    for command in _preferred_browser_launchers(url):
        try:
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            continue
    try:
        return bool(webbrowser.open(url, new=1))
    except Exception:
        return False


def run_browser_launcher(*, keep_backend: bool, startup_timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS) -> int:
    backend = ManagedBackend()

    using_existing_backend = wait_for_health(timeout_seconds=1.0, interval_seconds=0.1)
    if not using_existing_backend:
        try:
            backend.start()
        except OSError as exc:
            show_fatal_error(f"Backend failed to start: {exc}")
            return 1

    print(f"[JARVIS] Waiting for backend readiness for up to {int(startup_timeout_seconds)} seconds...")
    if not wait_for_health(
        process=None if using_existing_backend else backend.process,
        timeout_seconds=startup_timeout_seconds,
    ):
        show_fatal_error(f"Backend did not become ready within {int(startup_timeout_seconds)} seconds.")
        if not using_existing_backend:
            backend.stop()
        return 1

    browser_opened = open_browser_launcher(LAUNCHER_URL)
    if not browser_opened:
        print(f"[WARN] Browser did not open automatically. Open {LAUNCHER_URL} manually.")

    if browser_opened and not using_existing_backend:
        print("[JARVIS] Browser opened. Backend is running. Press Ctrl+C to stop.")
        try:
            return backend.wait()
        except KeyboardInterrupt:
            backend.stop()
            return 0

    if not using_existing_backend:
        print(f"[JARVIS] Backend is running at {LAUNCHER_URL}")
        if not browser_opened:
            print("[JARVIS] Browser did not open automatically. Open the launcher URL manually.")
    return 0


def run_launcher(*, keep_backend: bool, startup_timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS) -> int:
    return run_browser_launcher(
        keep_backend=keep_backend,
        startup_timeout_seconds=startup_timeout_seconds,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Accepted for compatibility; launcher mode always disables reload.",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Development only: start the backend without browser auto-open.",
    )
    parser.add_argument(
        "--keep-backend",
        action="store_true",
        help="Development only: keep backend alive if the launcher exits before verification.",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=DEFAULT_STARTUP_TIMEOUT_SECONDS,
        help="Seconds to wait for FastAPI /health before showing the launcher.",
    )
    args = parser.parse_args()

    if args.no_gui:
        try:
            run_server(reload=False)
        except OSError as exc:
            if "address already in use" in str(exc).lower() or "10048" in str(exc):
                print("[ERROR] Port 8000 is already in use. Stop the other process and retry.")
            else:
                print(f"[ERROR] Server failed to start: {exc}")
            sys.exit(1)
        return

    sys.exit(run_browser_launcher(keep_backend=args.keep_backend, startup_timeout_seconds=args.startup_timeout))


if __name__ == "__main__":
    main()
