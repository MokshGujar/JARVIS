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

## 2026-05-07 Legacy Delegate Caller Migration

- Before this phase: `app/services/automation_service.py` was 4,692 LOC with 181 directly defined methods.
- After removing the six private legacy delegate methods: 4,267 LOC with 175 directly defined methods.
- After mechanically extracting compatibility helper methods into `app/services/automation_compatibility_mixins.py`: `AutomationService` is 1,525 LOC with 56 directly defined methods.
- New module: `app/services/automation_compatibility_mixins.py`, a transitional mixin that preserves app/browser/file/system/WhatsApp helper behavior while the facade file shrinks.
- New module: `app/tools/compatibility_runners.py`, owned by tool boundaries, containing `AppCompatibilityRunner`, `BrowserCompatibilityRunner`, `FileCompatibilityRunner`, `SystemCompatibilityRunner`, and `WhatsAppCompatibilityRunner`.

### Delegates Migrated And Deleted

- Deleted from `AutomationService`: `_execute_app_launcher_command_legacy`, `_execute_system_command_legacy`, `_execute_file_command_legacy`, `_execute_whatsapp_command_legacy`, `_execute_browser_control_legacy`, `_execute_browser_command_legacy`.
- Tool callers migrated:
  - `AppTool` and `AppLauncherTool` now call `AppCompatibilityRunner`.
  - `BrowserTool` now calls `BrowserCompatibilityRunner`.
  - `FileTool` now calls `FileCompatibilityRunner`.
  - `SystemTool` now calls `SystemCompatibilityRunner`.
  - `WhatsAppTool` now calls `WhatsAppCompatibilityRunner` for compatibility parsing and retains planned-action calls to WhatsApp bridge methods.
- Tests migrated away from patching AutomationService private delegates and now patch compatibility runners or tool boundaries.
- `app/tools/tool_inventory.py` no longer lists the removed AutomationService delegate names for live-routed app/browser/file/system/WhatsApp records.

### Guards Added

- `tests/test_architecture_execution_boundaries.py` now asserts the six removed delegate methods are absent from `AutomationService`.
- The same guard searches `app/tools` and `tests` for references to the removed delegate names, excluding the guard test itself.

### Current Readiness

- `AutomationService` is under the phase target of 2,500 LOC.
- It is not yet the final sub-700 LOC clean facade: 56 directly defined methods remain, plus inherited transitional compatibility helpers.
- Remaining blocker: the mixin still preserves broad compatibility helper behavior for existing tools/tests. The next strangler step should move those helpers from the mixin into dedicated connectors/adapters or tool-native implementations.

### Focused Test Result

- `python -m pytest -q tests/test_core_automation_facade.py tests/test_tool_orchestrator_architecture.py tests/test_architecture_execution_boundaries.py tests/test_automation_reliability.py tests/test_app_launcher_tool_orchestrator.py tests/test_browser_tool_orchestrator.py tests/test_system_tool_orchestrator.py tests/test_whatsapp_characterization.py tests/test_file_characterization.py tests/test_semantic_claim_reliability.py`
- Result: `132 passed, 1 warning, 60 subtests passed in 2.68s`.
- `python -m pytest -q -p no:cacheprovider`
- Result: collection failed before tests because unreadable generated directories `pytest-cache-files-era_bh0x` and `pytest-cache-files-h11vr247` remain at the workspace root. The environment rejected the requested cache cleanup command.
- Nearest viable full-suite command: `python -m pytest -q tests -p no:cacheprovider`.
- Result: `666 passed, 407 subtests passed in 59.41s`.

## 2026-05-07 Domain Split Of AutomationCompatibilityMixin

- Original monolithic `automation_compatibility_mixins.py`: 2,784 LOC, 119 methods.
- Final monolithic file state: deleted.
- `AutomationService` no longer imports or inherits `AutomationCompatibilityMixin`.
- `AutomationService` current size: 1,528 LOC, 56 directly defined methods.

### Domain Helper Modules

- `app/tools/file_domain_helper.py`: 1,085 LOC, 41 methods.
- `app/tools/app_browser_domain_helper.py`: 861 LOC, 35 methods.
- `app/tools/system_domain_helper.py`: 250 LOC, 12 methods.
- `app/tools/whatsapp_domain_helper.py`: 826 LOC, 31 methods.

### Status

- The 2,000+ LOC transitional blob has been removed.
- Helper behavior is now split by domain, but these are still compatibility helpers inherited by `AutomationService`.
- Remaining blocker for a pure facade: migrate each domain helper module into tool/connector/adapter ownership and remove inherited private compatibility methods.
- Verification after split:
  - Focused command: `133 passed, 1 warning, 60 subtests passed in 2.26s`.
  - Full `tests/` command with cache disabled: `667 passed, 413 subtests passed in 59.77s`.

## 2026-05-07 Domain Helper Inheritance Removal

- `AutomationService` no longer inherits `AutomationFileCompatibility`, `AutomationAppBrowserCompatibility`, `AutomationSystemCompatibility`, or `AutomationWhatsAppCompatibility`.
- `AutomationService` now composes explicit helpers: `file_domain`, `app_browser_domain`, `system_domain`, and `whatsapp_domain`.
- Tool registry wiring now passes domain helpers to `FileTool`, `AppTool`, `AppLauncherTool`, `BrowserTool`, `SystemTool`, and `WhatsAppTool`.
- Direct tool constructors normalize an `AutomationService` argument to the correct domain helper, preserving compatibility for existing tests/runtime code.
- New helper: `app/tools/automation_domain_helper.py`, which keeps mutable runtime state on `AutomationService` while allowing helper methods to be composed instead of inherited.
- AutomationService final for this phase: 1,532 LOC, 56 directly defined methods, zero base classes.
- Remaining blocker for under-900 LOC at that checkpoint: `_execute_facade` still contained legacy compatibility routing and the domain helpers were still transitional composition dependencies.
- Verification:
  - Focused command: `135 passed, 1 warning, 60 subtests passed in 2.23s`.
  - Full `tests/` command with cache disabled: `669 passed, 415 subtests passed in 40.75s`.

## 2026-05-07 Domain Helper Promotion And Router Extraction

- `AutomationService` before this phase: 1,533 LOC, 56 directly defined methods, zero base classes.
- `AutomationService` after this phase: 704 LOC, 55 directly defined methods, zero base classes.
- New module: `app/tools/automation_facade_router.py`, which owns the remaining compatibility facade routing glue and preserves the policy-gated orchestrator/tool path.
- Service-side domain helper files are removed from `app/services/`; the active transitional helpers are tool-owned:
  - `app/tools/file_domain_helper.py`: 1,087 LOC, 41 methods.
  - `app/tools/app_browser_domain_helper.py`: 863 LOC, 35 methods.
  - `app/tools/system_domain_helper.py`: 252 LOC, 12 methods.
  - `app/tools/whatsapp_domain_helper.py`: 828 LOC, 31 methods.
  - `app/tools/automation_domain_helper.py`: shared service-backed state proxy.
- Tests updated:
  - `tests/test_tool_delegation_integration.py` now patches `app.tools.automation_facade_router.FileTool` and `AppTool`, matching the extracted tool registry construction boundary.
  - `tests/test_architecture_execution_boundaries.py` now guards that service-side domain compatibility files do not return.
- Public API preserved:
  - `AutomationService.execute()` still calls `_execute_facade()`.
  - Compatibility wrappers remain for `_execute_file_tool`, `_execute_app_tool`, `_execute_browser_tool`, and `_execute_system_tool` because focused tests still exercise them directly.
- Remaining blockers:
  - `AutomationService` still composes `file_domain`, `app_browser_domain`, `system_domain`, and `whatsapp_domain`.
  - Tool registry still receives transitional domain helper objects.
  - The tool-owned domain helpers still need to be split into smaller parser/connector/adapter/tool-native code in a later batch.
- Focused promotion suite:
  - `python -m pytest -q tests/test_core_automation_facade.py tests/test_tool_orchestrator_architecture.py tests/test_architecture_execution_boundaries.py tests/test_automation_reliability.py tests/test_app_launcher_tool_orchestrator.py tests/test_browser_tool_orchestrator.py tests/test_system_tool_orchestrator.py tests/test_whatsapp_characterization.py tests/test_file_characterization.py tests/test_semantic_claim_reliability.py`
  - Result: `136 passed, 1 warning, 60 subtests passed in 2.21s`.
- Full promotion suite:
  - `python -m pytest -q tests -p no:cacheprovider`
  - Result: `670 passed, 405 subtests passed in 62.46s`.

