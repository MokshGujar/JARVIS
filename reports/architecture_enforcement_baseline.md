# JARVIS Architecture Enforcement Baseline

Date: 2026-05-06

## Summary

The canonical automation path exists and service-level direct execution has been contained. `AutomationService.execute()` enters a facade path that routes known executable commands through `MainOrchestrator -> PolicyEngine -> ToolExecutor -> ToolRegistry -> Tool`. Legacy method names remain for tool compatibility, but low-level app/browser/process/keyboard/file-move primitives have moved behind connectors/adapters.

## Current Runtime Path Confirmation

- Open calculator/open chrome: `AutomationService.execute()` enters `_execute_facade()`, calls `MainOrchestrator`, policy is evaluated in `ToolExecutor`, metadata is resolved through `ToolRegistry`, and `AppTool` delegates temporarily to the marked app-launch legacy delegate.
- Search Google: `AutomationService.execute()` enters `_execute_facade()`, calls `MainOrchestrator`, policy is evaluated in `ToolExecutor`, metadata is resolved through `ToolRegistry`, and `BrowserTool` delegates temporarily to the marked browser legacy delegate.
- Search files: deterministic routing now selects `FileTool.search_files`. Missing query returns clarification instead of opening Google.
- WhatsApp confirmation replay: pending confirmation uses `ToolExecutor` and `WhatsAppTool`; send/call delegates remain transitional and tool-owned.
- Delete/critical action confirmation: `PolicyEngine` returns confirmation/step-up before tool execution. Tests patch destructive delegates to prove no direct delete occurs.
- Thinking acknowledgement: streaming now registers one canonical thinking acknowledgement per turn, and `/tts/thinking` speaks only that turn/hash payload.

## Direct Execution Findings

Allowed inside tool/connector/adapter boundaries:

- `app/tools/file_tool.py`: file create/write/append through `FileTool`.
- `app/connectors/local_files_connector.py`: local file connector writes.
- `app/connectors/whatsapp_desktop_connector.py` and `app/connectors/whatsapp_web_connector.py`: WhatsApp connector wrappers.
- `app/adapters/ui/pywinauto_adapter.py`: `pywinauto` UI adapter boundary.
- `app/adapters/providers/nemo_parakeet_provider.py`: temporary audio file cleanup.

Contained service execution:

- `app/services/automation_service.py`: no longer imports/calls `subprocess`, `AppOpener`, `webbrowser.open`, `os.startfile`, `keyboard`, or `shutil.move` directly. Transitional delegate methods remain, but they call connectors/adapters or tool-owned helpers.
- `app/services/computer_control_service.py`, `computer_settings_service.py`, `browser_control_service.py`, `whatsapp_desktop_automation.py`, `message_action_service.py`, `game_service.py`, `youtube_tools_service.py`, and `safe_command_info_service.py` now act as compatibility facades over connector/adapter boundaries.
- Current grep finds direct execution APIs in tools/connectors/adapters only, plus read-only `winreg` discovery in service path alias/game metadata helpers.

Must stay guarded behind tool/policy:

- App open/close/focus.
- Browser open/search/navigation.
- File create/write/move/rename/delete.
- System settings/window/power actions.
- WhatsApp message/call send execution.

## Duplicate Paths

- `app/orchestrator/main_orchestrator.py` is the canonical automation command entrypoint.
- `app/orchestrator/tool_executor.py` is the canonical execution boundary.
- `app/execution/tool_executor.py` is a compatibility wrapper.
- `app/orchestrator/tool_registry.py` wraps the base registry from `app/tools/registry.py`.
- `app/core/orchestrator.py` is still used by `app/bootstrap/container.py` for assistant-level routing and is not deleted in this phase.

## Shadow Tree And Runtime Pollution

- `config/app` was an ignored untracked copied app tree. Import/path checks found no runtime or test imports, so it was deleted from disk rather than archived.
- Runtime/user data under `database/agent_tasks`, `database/chats_data`, `database/camera_captures`, `database/vector_store`, `database/voice_identity`, `database/face_identity`, and `database/memory` was removed from git tracking with `git rm --cached`; local files were preserved.
- `.gitignore` includes runtime folders for future pollution prevention. No local user/runtime data was destroyed.
