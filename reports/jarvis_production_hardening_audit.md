# JARVIS Production Hardening Audit

## Phase A Inventory

Start commit: `57972c8`

Branch target: `chore/jarvis-prod-hardening`

Pre-existing dirty/untracked files:

- Archive: deleted `Jarvis_main.zip`
- Runtime artifact: modified `database/face_identity/verification_history.jsonl`
- Test runtime scratch: modified `tests/_tmp/face_profile_required_samples/profile.json`
- Config shadow: untracked `config/app/`
- Runtime artifact: untracked `database/chats_data/chat_9b854481-81c6-4791-917d-3911ad524f73.json`
- Test runtime scratch: untracked `tests/_tmp/config_loader_06566b352f0c46c5967a9c20e34c6465/`
- Test runtime scratch: untracked temp SQLite files under `tests/_tmp/`

These items are not part of hardening changes and must not be staged.

## Live Route Inventory

Runtime entrypoint is `run.py -> app.main:app`.

FastAPI route groups in `app/main.py`:

- health/API: `/api`, `/health`, `/system/metrics`
- chat: `/chat`, `/chat/stream`, `/chat/realtime`, `/chat/realtime/stream`,
  `/chat/jarvis/stream`, `/chat/history/{session_id}`, `/chat/interrupt`
- STT/TTS: `/stt/transcribe`, `/stt/warmup`, `/tts/thinking`, `/tts`
- launcher/enroll/assets: `/launcher`, `/launcher/`, `/launcher/launcher.css`,
  `/launcher/launcher.js`, `/enroll`, `/enroll/`, `/enroll/enroll.css`,
  `/enroll/enroll.js`, `/favicon.ico`, `/`
- face/launcher auth: `/face/enroll/start`, `/face/enroll/sample`,
  `/face/enroll/batch`, `/face/enroll/complete`, `/face/verify`,
  `/face/status`, `/face/profile`, `/auth/launcher/create-bootstrap`,
  `/auth/launcher/exchange-bootstrap`
- protected auth/risk: `/auth/command-risk`, `/auth/step-up/start`,
  `/auth/step-up/verify`
- domain endpoints: `/reminders/due`, `/wake-on-lan/test`, `/agent`,
  `/phone/incoming-call`, `/phone/contacts/sync`, `/phone/pending-actions`,
  `/phone/pending-actions/ack`, `/tasks/{task_id}`, `/tasks/{task_id}/image`,
  `/control/sleep`

## Live Critical Files

- `app/core/orchestrator.py`
- `app/capabilities/automation.py`
- `app/services/automation_service.py`
- `app/orchestrator/tool_executor.py`
- `app/tools/registry.py`
- `app/tools/tool_inventory.py`
- `app/policy/policy_engine.py`
- `app/state/runtime_state.py`
- `frontend/script.js`

## Bypass Risks Found

- `AutomationService` is 4,711 lines before reduction and still contains direct
  `os.startfile`, `subprocess`, `webbrowser`, AppOpener, pywinauto-adjacent, and
  delete-confirmation paths.
- `AutomationService` keeps session pending state in memory, including delete
  confirmation targets.
- Legacy open/app fallback can receive unsanitized trailing wake words if
  semantic claim fails.
- Some route/task paths can still invoke task executor or legacy automation for
  action-like commands; claimed semantic commands must be kept out of BRAIN-TASK.
- `config/app/` shadows `app/` but is not active by current import search.

## Deletion Candidates

These require proof before deletion:

- Direct AppOpener fallback branches once app open/focus is fully executor-gated.
- Direct browser open/search helpers once browser tool path is fully canonical.
- Direct file delete confirmation logic once SQLite confirmation lifecycle is
  authoritative.
- Duplicate wake-word/semantic normalization helpers after one path is canonical.
- Old frontend thinking-audio globals if `VoiceAudioQueue` fully replaces them.

## Phase Results

Phase A: green. Updated `.gitignore`, `docs/JARVIS_CORE_ARCHITECTURE.md`, and this audit report. No files staged.

Phase B: green. Hardened wake-word stripping and semantic app-open claims. Added tests for trailing wake words and `open calculator Jarvis`.

Phase C: green. Tightened policy defaults for unknown tools/actions and metadata action allowlists.

Phase D: green. Confirmed current runtime SQLite schema/user_version 1. Added runtime-state confirmation helpers and executor confirmation-id checks without schema migration.

Phase E: green. Single-step semantic app opens still execute through `ToolExecutor` but report the concrete selected tool, preserving compatibility.

Phase F: green. Extracted Windows path alias helper to `app/services/automation_path_aliases.py`. `AutomationService` line count changed from 4,711 to 4,680.

Phase G: green. Existing voice/startup contracts passed without code changes in this phase.

Phase H: green. Tightened response leak detection and added explicit user-facing leak blacklist tests.

Phase I: green. Removed unused duplicate `MainOrchestrator._policy_block`; executor remains the policy boundary. Added the new helper to `reports/service_cleanup_map.md`.

Phase J: green. Full suite passed: `627 passed, 391 subtests passed`.
