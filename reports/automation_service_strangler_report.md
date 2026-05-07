# AutomationService Strangler Report

Date: 2026-05-07

## Baseline

- Original baseline from planning: about 4,766 lines and 181 methods.
- Current after seam extraction/fix pass: 4,692 lines and 181 methods.
- Clean small facade target is not complete yet. The default execute path is thinner, but compatibility delegates and legacy helper methods remain because tools/tests still call them directly.

## Extracted Modules

- `app/services/automation_context_builder.py`
  - Owns context lookup/building and safe request metadata.
  - Destination class: B, moved from AutomationService context setup.
- `app/services/automation_response_formatter.py`
  - Facade wrapper over existing `automation_response` normalization/formatting.
  - Destination class: C, preserves legacy import behavior while giving AutomationService a stable formatter seam.
- `app/services/pending_confirmation_service.py`
  - Owns session pending-state load/save, prompt IDs, pending IDs, and confirmation prompt dedupe.
  - Destination class: D, extracted without changing public response shape.

## Method Classification Summary

- A. Keep in AutomationService facade: `__init__`, `execute`, public pending probes, `looks_like_automation_request`, `looks_like_semantic_request`, registry/orchestrator wiring, public compatibility helpers (`create_file_with_content`, `describe_recent_target`, `diagnostics`).
- B. Move to AutomationContextBuilder: `_automation_context_for`; active context construction in `execute`.
- C. Move to AutomationResponseFormatter: response normalization call in `execute`; confirmation/user-message shaping remains compatible through the wrapper.
- D. Move to PendingConfirmationService: `_load_session_pending_state`, `_save_session_pending_state`, `_confirmation_scope_key`, `_pending_action_id`, `_active_pending_confirmation_id`, `_active_confirmation_prompt_keys`, `_clear_stale_confirmation_prompts`, `_dedupe_confirmation_prompt`, `_is_repeat_confirmation_prompt_result`, `_is_confirmation_prompt_result`.
- E. Move to Tool/Connector/Adapter later: app/browser/file/system/WhatsApp/YouTube/game execution helpers that are still bridged by tools.
- F. Legacy delegate still required by Tool: `_execute_app_launcher_command_legacy`, `_execute_system_command_legacy`, `_execute_file_command_legacy`, `_execute_whatsapp_command_legacy`, `_execute_browser_control_legacy`, `_execute_browser_command_legacy`.
- G. Dead code candidates: copied zip/config shadow/runtime artifacts, not AutomationService methods yet.
- H. Test-only compatibility: several methods are directly patched/asserted by characterization tests, especially legacy delegates.
- I. Unknown needs caller search: remaining low-level private helpers under app/file/WhatsApp/open-target groups before any method deletion.

## Caller Evidence

- Runtime imports: `app/main.py`, `app/bootstrap/container.py`, `app/services/agent_service.py`, `app/services/chat_service.py`, `app/services/jarvis_orchestrator_service.py`.
- Tool callers: AppTool/AppLauncherTool, BrowserTool, FileTool, SystemTool, WhatsAppTool call legacy delegate names.
- Test callers: automation reliability/characterization, core facade, tool orchestrator, semantic, system, file, browser, and WhatsApp tests instantiate or patch AutomationService.

## Deletion Readiness

- No AutomationService methods were deleted in this pass.
- Deletion is not safe until callers are migrated from direct private helper patching to tool/connector mocks.
- The full sub-700-line replacement remains blocked by compatibility callers and should be done as a dedicated follow-up after moving delegate logic into tools/connectors.

## Characterization And Guard Results

- App launcher, automation service, semantic orchestrator integration, and cleanup-map focused regressions: `49 passed, 108 subtests passed in 1.19s`.
- Required extraction guard suite: `94 passed, 1 warning, 17 subtests passed in 6.79s`.
- Final full suite with pytest cache disabled: `665 passed, 405 subtests passed in 52.85s`.
