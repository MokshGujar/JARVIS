# Service Direct API Containment Report

Date: 2026-05-06

## Current Containment

- Canonical executable automation remains:
  `AutomationService -> MainOrchestrator -> PolicyEngine -> ToolExecutor -> ToolRegistry -> Tool -> Connector/Adapter`.
- `AutomationService.execute()` remains facade-first and does not call legacy execution before `MainOrchestrator` for known executable commands.
- `AutomationService.execute()` now uses extracted seams for context building, response formatting, and pending confirmation state/prompt handling.
- High-level service files listed in the containment phase no longer import or call direct execution APIs such as `subprocess`, `webbrowser.open`, `os.startfile`, `pyautogui`, or `pywinauto`.
- `AutomationService` retains legacy delegate method names for tool compatibility, but the low-level app/browser/process/keyboard/file-move primitives now live behind connectors/adapters.

## Services Converted To Facades

- `app/services/computer_control_service.py` delegates to `app/adapters/ui/pyautogui_adapter.py`.
- `app/services/computer_settings_service.py` delegates to `app/adapters/system/local_system_adapter.py`.
- `app/services/browser_control_service.py` delegates to `app/adapters/browser/browser_runtime_adapter.py`.
- `app/services/message_action_service.py` delegates to `app/connectors/message_action_connector.py`.
- `app/services/whatsapp_desktop_automation.py` delegates to `app/adapters/whatsapp/desktop_adapter.py`.
- `app/services/safe_command_info_service.py` delegates to `app/connectors/safe_command_info_connector.py`.
- `app/services/automation_context_builder.py` builds safe automation request context.
- `app/services/automation_response_formatter.py` provides the facade response formatting seam over existing response normalization.
- `app/services/pending_confirmation_service.py` owns pending confirmation/session prompt glue during the strangler transition.
- `app/services/game_service.py` delegates launch/open operations to `app/connectors/game_launcher_connector.py`.
- `app/services/youtube_tools_service.py` delegates play/search open operations to `app/connectors/youtube_connector.py`; summary/info/trending remain read-only service logic.

## Connectors And Adapters Added

- `app/adapters/ui/pyautogui_adapter.py`: keyboard, mouse, clipboard, screenshot, window focus primitives.
- `app/adapters/system/local_system_adapter.py`: local system setting/power primitives.
- `app/adapters/browser/browser_runtime_adapter.py`: Playwright browser runtime primitives.
- `app/adapters/whatsapp/desktop_adapter.py`: WhatsApp Desktop URI/UI automation primitives.
- `app/connectors/local_app_connector.py`: app open/close, URL launch, process fallback, AppOpener boundary.
- `app/connectors/local_files_connector.py`: file move added beside existing file operations.
- `app/connectors/message_action_connector.py`: legacy UI-driven messaging send primitives.
- `app/connectors/safe_command_info_connector.py`: allowlisted read-only shell info commands.
- `app/connectors/game_launcher_connector.py`: Steam/Epic launch/store open primitives.
- `app/connectors/youtube_connector.py`: YouTube open/search through BrowserTool-owned connector path.

## Tool Ownership

- `AppTool`: app open/close/focus and app/window launch families.
- `BrowserTool`: browser search/open/navigation and YouTube web routes.
- `FileTool`: file create/read/list/search/write/append/move/rename/delete.
- `SystemTool`: volume, brightness, screenshot, safe system info, window/system controls, power-action policy routing.
- `WhatsAppTool`: WhatsApp open/send/call/end-call/contact flows.

## Remaining Direct APIs

- Direct execution APIs remain in `app/tools/`, `app/connectors/`, and `app/adapters/`, which are approved execution boundaries.
- `app/services/game_service.py` still reads Steam install paths via `winreg`; this is read-only discovery, not execution. Game launch execution is connector-owned.
- `app/services/automation_path_aliases.py` still reads Windows known-folder paths via `winreg`; this is read-only path discovery, not execution.

## Known Non-Automation Legacy Tool Calls

- `app/main.py` still invokes `STTTool.execute(...)` directly for STT warmup/transcription endpoint handling. This is provider/STT plumbing, not OS/browser/file/system automation.
- `app/services/secure_execution_service.py` and `app/agents/*` still contain pre-canonical direct tool execution helpers. Current grep indicates they are not on the canonical `AutomationService -> MainOrchestrator -> ToolExecutor` automation path. They should be wrapped or retired in a dedicated legacy-agent cleanup phase.

## Guards

- `tests/test_architecture_execution_boundaries.py` now verifies high-level service facades do not contain dangerous direct execution imports/calls.
- The same guard verifies `AutomationService.execute()` enters `_execute_facade()` and high-level routing methods do not construct connectors/adapters directly.
- Connector/adapter construction remains allowed in compatibility facade constructors and tool wiring, but executable calls are still policy-gated through tools.

## 2026-05-07 Delegate Migration Update

- The six private AutomationService delegate methods for app/system/file/WhatsApp/browser command compatibility were removed from `AutomationService`.
- Live-routed tools no longer call or patch `AutomationService._execute_*_legacy` methods.
- Transitional command parsing now lives behind tool-owned compatibility runners in `app/tools/compatibility_runners.py`.
- Broad compatibility helper methods were mechanically extracted to `app/services/automation_compatibility_mixins.py`; this is still a transitional service-side helper module, but the default executable route remains `AutomationService -> MainOrchestrator -> PolicyEngine -> ToolExecutor -> ToolRegistry -> Tool`.
- Guard coverage now fails if app tools or tests reintroduce references to the removed private AutomationService delegate names.

## 2026-05-07 Domain Helper Split Update

- `app/services/automation_compatibility_mixins.py` was deleted after the helper methods were split by domain.
- Transitional service-side helper modules now isolate file, app/browser, system, and WhatsApp/message behavior separately.
- Direct API containment is unchanged: high-level routing still enters `AutomationService -> MainOrchestrator -> PolicyEngine -> ToolExecutor -> ToolRegistry -> Tool`; executable primitives remain behind tools/connectors/adapters or transitional compatibility helpers.
- Remaining containment cleanup: move the new domain helper modules into their owning tools/connectors/adapters so `AutomationService` can stop inheriting compatibility helpers.
- Verification after split: focused suite `133 passed, 1 warning, 60 subtests passed`; full `tests/` suite with cache disabled `667 passed, 413 subtests passed`.
