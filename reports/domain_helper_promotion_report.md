# Domain Helper Promotion Report

## Baseline

- `AutomationService` before this phase: 1,533 LOC, 56 directly defined methods, 0 base classes.
- The service-side compatibility files requested for deletion are already absent from `app/services/`:
  - `app/services/automation_file_compatibility.py`
  - `app/services/automation_app_browser_compatibility.py`
  - `app/services/automation_system_compatibility.py`
  - `app/services/automation_whatsapp_compatibility.py`
- Transitional domain helpers are currently tool-owned modules:
  - `app/tools/file_domain_helper.py`: 1,087 LOC, 41 methods.
  - `app/tools/app_browser_domain_helper.py`: 863 LOC, 35 methods.
  - `app/tools/system_domain_helper.py`: 252 LOC, 12 methods.
  - `app/tools/whatsapp_domain_helper.py`: 828 LOC, 31 methods.
  - `app/tools/automation_domain_helper.py`: service-backed composition proxy.

## Inventory

| Module | Class | Methods | Current direct callers | Test callers | Destination | Deletion readiness | Risk |
|---|---|---:|---|---|---|---|---|
| `app/tools/file_domain_helper.py` | `AutomationFileCompatibility` | 41 | `AutomationService.file_domain`, `FileTool`, `compatibility_runners.FileCompatibilityRunner` | File characterization, semantic routing, facade, reliability tests patch `service.file_domain` | Split later into `FileTool`, `local_files_connector`, file parser/repository | Not ready; behavior remains shared by tests and tool compatibility path | HIGH |
| `app/tools/app_browser_domain_helper.py` | `AutomationAppBrowserCompatibility` | 35 | `AutomationService.app_browser_domain`, `AppTool`, `AppLauncherTool`, `BrowserTool`, app/browser compatibility runners | Browser/app/facade/reliability tests patch `service.app_browser_domain` | Split later into `AppTool`, `BrowserTool`, `local_app_connector`, `browser_connector`, browser adapter/parser | Not ready; behavior remains shared by app/browser tools and tests | HIGH |
| `app/tools/system_domain_helper.py` | `AutomationSystemCompatibility` | 12 | `AutomationService.system_domain`, `SystemTool`, system compatibility runner | System characterization and orchestrator tests use `service.system_domain` | Split later into `SystemTool`, system adapters, safe command connector/parser | Not ready; policy-facing system routes still use helper surface | HIGH |
| `app/tools/whatsapp_domain_helper.py` | `AutomationWhatsAppCompatibility` | 31 | `AutomationService.whatsapp_domain`, `WhatsAppTool`, WhatsApp compatibility runner | WhatsApp, semantic confirmation, facade, reliability tests patch `service.whatsapp_domain` | Split later into `WhatsAppTool`, WhatsApp connectors/adapters, message/contact services/parser | Not ready; send/call confirmation replay still uses helper surface | HIGH |
| `app/tools/automation_domain_helper.py` | `ServiceBackedDomainHelper` | 3 | Four tool-owned compatibility helpers | Indirect through all domain tests | Delete after helpers no longer need service-backed mutable state | Not ready; helpers still delegate state to `AutomationService` | MEDIUM |

## Phase Decision

The requested `app/services/automation_*_compatibility.py` files are already gone, so this phase focuses on the remaining service reduction blocker: `AutomationService` still owns a large compatibility facade router. That router is being extracted from the service into a tool-owned router module while preserving public compatibility wrappers on `AutomationService`.

This is still transitional. The domain helper APIs are not deleted in this batch because runtime and tests still exercise them directly through `service.file_domain`, `service.app_browser_domain`, `service.system_domain`, and `service.whatsapp_domain`.

## Implementation

- Added `app/tools/automation_facade_router.py`.
- `AutomationService` now constructs `self._facade_router = AutomationFacadeRouter(self)`.
- The remaining facade routing body was moved out of `AutomationService`; service methods now delegate to the extracted router where public/test compatibility is still required.
- Updated `tests/test_tool_delegation_integration.py` to patch the new router module import boundary.
- Added an architecture guard that fails if service-side domain compatibility files return.

## Final State

- `AutomationService`: 704 LOC, 55 directly defined methods, zero base classes.
- `app/tools/automation_facade_router.py`: 930 LOC, 30 methods.
- `AutomationService` still composes domain helpers: yes.
- Tool registry still passes domain helpers: yes.
- Tools receive direct parser/connector/adapter dependencies only for already-migrated primitives; app/browser/file/system/WhatsApp compatibility grammar still flows through helper objects.

## Verification

- Focused command:
  `python -m pytest -q tests/test_core_automation_facade.py tests/test_tool_orchestrator_architecture.py tests/test_architecture_execution_boundaries.py tests/test_automation_reliability.py tests/test_app_launcher_tool_orchestrator.py tests/test_browser_tool_orchestrator.py tests/test_system_tool_orchestrator.py tests/test_whatsapp_characterization.py tests/test_file_characterization.py tests/test_semantic_claim_reliability.py`
- Result: `136 passed, 1 warning, 60 subtests passed in 2.21s`.
- Cache-disabled focused command:
  `python -m pytest -q tests/test_core_automation_facade.py tests/test_tool_orchestrator_architecture.py tests/test_architecture_execution_boundaries.py tests/test_automation_reliability.py tests/test_app_launcher_tool_orchestrator.py tests/test_browser_tool_orchestrator.py tests/test_system_tool_orchestrator.py tests/test_whatsapp_characterization.py tests/test_file_characterization.py tests/test_semantic_claim_reliability.py -p no:cacheprovider`
- Result: `136 passed, 60 subtests passed in 2.07s`.
- Guard/map command:
  `python -m pytest -q tests/test_service_cleanup_map.py tests/test_architecture_execution_boundaries.py -p no:cacheprovider`
- Result: `14 passed, 98 subtests passed in 0.17s`.
- Full command:
  `python -m pytest -q tests -p no:cacheprovider`
- Result: `670 passed, 405 subtests passed in 62.46s`.

## Remaining Blockers

- The extracted `AutomationFacadeRouter` is still transitional compatibility code and should shrink as tools absorb grammar directly.
- Domain helper modules remain large and must still be split by domain into parser-only modules, connector/adapter execution primitives, and tool-owned action behavior.
- Removing `file_domain`, `app_browser_domain`, `system_domain`, and `whatsapp_domain` composition is blocked by existing public compatibility tests and tool runner surfaces.
