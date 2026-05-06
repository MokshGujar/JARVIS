# Service Direct API Containment Report

Date: 2026-05-06

## Current Containment

- Canonical app/browser/file/system/WhatsApp command paths are exercised through:
  `AutomationService -> MainOrchestrator -> PolicyEngine -> ToolExecutor -> ToolRegistry -> Tool`.
- `AutomationService` remains facade-first.
- Legacy app/browser/file/system/WhatsApp delegates remain marked as transitional tool-only delegates.
- Confirmed WhatsApp actions replay through `ToolExecutor`.
- Delete and system-power actions are policy-blocked/step-up gated before execution in tests.

## Direct APIs Still Present

- `app/services/automation_service.py`: `subprocess`, `AppOpener`, `webbrowser.open`, `os.startfile`, `shutil.move`.
- `app/services/computer_control_service.py`: `subprocess`, `pyautogui`.
- `app/services/computer_settings_service.py`: `subprocess`.
- `app/services/browser_control_service.py`: `subprocess`.
- `app/services/game_service.py`: `subprocess`, `webbrowser.open`.
- `app/services/message_action_service.py`: `pyautogui`, `webbrowser.open`.
- `app/services/safe_command_info_service.py`: `subprocess`.
- `app/services/whatsapp_desktop_automation.py`: `os.startfile`, `pyautogui`, `pywinauto`.
- `app/services/youtube_tools_service.py`: `webbrowser.open`.

## Allowed Boundaries

- `app/tools/*`, `app/connectors/*`, and `app/adapters/*` are allowed to contain execution APIs.
- `app/services/automation_service.py` is allowed to retain explicitly marked transitional delegates only while tool classes call them.

## Deferred Work

- Move `computer_control_service.py` and `computer_settings_service.py` behind `SystemTool`/adapters.
- Move browser/YouTube direct opening behind `BrowserTool`/connector.
- Move WhatsApp desktop automation behind WhatsApp connectors.
- Move game/window direct execution behind `AppTool`/adapter.
