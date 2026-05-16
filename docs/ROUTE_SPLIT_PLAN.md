# FastAPI Route Split Readiness Plan

## Purpose

This document maps `app/main.py` for a future mechanical route extraction. It is intentionally docs-only for this phase: no HTTP routes, payloads, globals, frontend contracts, Android bridge contracts, Face Gate behavior, step-up auth, TTS/STT behavior, or chat streaming behavior were changed.

## Current State

`app/main.py` owns application lifespan wiring, global service references, middleware, route handlers, streaming helpers, TTS/STT runtime helpers, launcher/static serving, and several small compatibility helpers. A broad route move would be risky because route handlers directly share globals and helper functions.

## Route Groups

### Health, Metrics, And Runtime Status

- Routes: `GET /api`, `GET /health`, `GET /system/metrics`, `GET /reminders/due`, `POST /control/sleep`, `GET /tasks/{task_id}`, `GET /tasks/{task_id}/image`, `GET /chat/history/{session_id}`.
- Current helpers: `_semantic_runtime_config`, `_face_runtime_config`, `_format_bytes`, `_primary_disk_path`, `_primary_disk_fstype`, `_temperature_metric`, `_battery_metric`, `_protection_metric`, `_connection_metric`, `collect_system_metrics`.
- Globals used: most service readiness globals, `task_manager`, `chat_service`, `reminder_service`, `automation_service`, `phone_command_service`, `face_identity_service`, `step_up_auth_service`, `launcher_bootstrap_service`.
- Future module candidate: `app/transports/http/status_routes.py`.
- Wiring needed: pass a container/service accessor plus metric helpers, or move metric helpers as a pure module first.
- Protective tests: `tests/test_system_metrics_and_hud_contract.py`, `tests/test_launcher_bootstrap_and_startup.py`.

### Face Gate And Auth

- Routes: `/face/enroll/start`, `/face/enroll/sample`, `/face/enroll/batch`, `/face/enroll/complete`, `/face/verify`, `/face/status`, `DELETE /face/profile`, `/auth/launcher/create-bootstrap`, `/auth/launcher/exchange-bootstrap`, `/auth/command-risk`, `/auth/step-up/start`, `/auth/step-up/verify`.
- Current helpers: `_face_runtime_config`.
- Globals used: `face_identity_service`, `face_enrollment_service`, `launcher_bootstrap_service`, `command_risk_service`, `step_up_auth_service`.
- Future module candidate: `app/transports/http/auth_routes.py`.
- Wiring needed: Face services, launcher bootstrap service, command risk service, and step-up auth service. Preserve launcher Face Gate and tool step-up distinction.
- Protective tests: `tests/test_api_auth.py`, auth and Face Gate tests in the full suite.

### Phone Bridge

- Routes: `POST /agent`, `POST /phone/incoming-call`, `POST /phone/contacts/sync`, `GET /phone/pending-actions`, `POST /phone/pending-actions/ack`, `POST /wake-on-lan/test`.
- Current helpers: `_require_phone_bridge_token`, `_basic_phone_payload`.
- Globals used: `phone_command_service`, `caller_lookup_service`, `wake_on_lan_service`, `PHONE_BRIDGE_TOKEN`.
- Future module candidate: `app/transports/http/phone_routes.py`.
- Wiring needed: phone command service, caller lookup service, Wake-on-LAN service, bridge token verifier, and fallback payload builder.
- Protective tests: `tests/test_phone_command_service.py`, `tests/test_phone_app_parity.py`, `tests/test_caller_lookup_service.py`, `tests/test_chat_service_routing.py`, plus Android parity checks.

### Chat And Streaming

- Routes: `POST /chat`, `POST /chat/stream`, `POST /chat/realtime`, `POST /chat/realtime/stream`, `POST /chat/jarvis/stream`, `POST /chat/interrupt`.
- Current helpers: `_stream_generator`, `_split_sentences`, `_merge_short`, `_should_hold_sentence_for_continuation`, `_safe_input_source`, `_metrics_event`, `_record_fast_response`, `_task_actions_from_response`, `_execute_fast_route`, `_normalize_confirmation_text`, `_get_pending_command_confirmation`, `_has_frontend_actions`, `_jarvis_realtime_pipeline`, `_mark_turn_voice_state`, `_register_thinking_ack`, `_thinking_skip_response`, `_warn_latency_budget`.
- Globals used: `assistant_orchestrator`, `chat_service`, `task_executor`, `fast_intent_router_service`, `acknowledgement_service`, `interrupt_manager`, `_pending_command_confirmations`, `_tts_pool`, `_stream_poll_pool`, voice turn state.
- Future module candidate: `app/transports/http/chat_routes.py`.
- Wiring needed: orchestrator, chat service, fast router, acknowledgement service, interrupt manager, latency tracker, streaming/TTS helper boundary.
- Protective tests: `tests/test_browser_streaming_ux.py`, `tests/test_chat_service_routing.py`, frontend/HUD contract tests, confirmation and interruption tests in the full suite.

### TTS And STT

- Routes: `POST /tts`, `POST /tts/thinking`, `POST /stt/transcribe`, `POST /stt/warmup`.
- Current helpers: `_tts_runtime_config`, `_thinking_audio_runtime_config`, `_normalize_edge_tts_text`, `_edge_tts_bytes`, `_generate_tts_sync`, `_select_thinking_phrase`, `_register_thinking_ack`, `_stt_provider_cache_enabled`, `_stt_preload_enabled`, `_stt_warmup_on_startup_enabled`, `_stt_fail_fast_on_warmup_error_enabled`, `_get_stt_tool`, `_stt_cached_provider`, `_stt_model_loaded`, `_warmup_stt_tool`, `_run_startup_stt_warmup`, `_stt_capture_runtime_config`, `_stt_runtime_bool`, `_audio_suffix_from_name`, `_ffmpeg_available`, `_maybe_convert_audio_to_wav`.
- Globals used: `app.state.stt_tool`, `app.state.stt_provider`, `app.state.stt_warmup_result`, `_tts_pool`, `_tts_request_lock`, `_tts_request_generation`, `_thinking_tts_cache`, voice turn state, many TTS/STT config constants.
- Future module candidate: split pure runtime helpers first into `app/transports/http/audio_runtime.py`, then routes into `app/transports/http/audio_routes.py`.
- Wiring needed: app state access, TTS executor pool, voice turn state, runtime config readers.
- Protective tests: `tests/test_stt_transcribe_endpoint.py`, `tests/test_edge_tts_config.py`, `tests/test_thinking_ack_contract.py`.

### Launcher And Static Assets

- Routes: `GET /launcher`, `GET /launcher/`, `GET /launcher/launcher.css`, `GET /launcher/launcher.js`, `GET /enroll`, `GET /enroll/`, `GET /enroll/enroll.css`, `GET /enroll/enroll.js`, `GET /favicon.ico`, `GET /`.
- Current helpers: `_launcher_asset_response`.
- Globals used: static file paths and FastAPI static mount behavior.
- Future module candidate: `app/transports/http/static_routes.py`.
- Wiring needed: path constants only. Keep cache headers/media types and redirects unchanged.
- Protective tests: `tests/test_launcher_bootstrap_and_startup.py`, frontend/HUD contract tests.

## Suggested Extraction Sequence

1. Move pure system metric helpers into a helper module with no route changes.
2. Move launcher/static routes because they have the smallest service dependency surface.
3. Move phone bridge routes after wrapping `_require_phone_bridge_token` and `_basic_phone_payload`.
4. Move Face/Auth routes only after preserving launcher Face Gate and step-up auth tests.
5. Move TTS/STT runtime helpers before moving audio routes.
6. Move chat streaming last because it has the broadest dependency surface and frontend/HUD contract risk.

## Must Not Change During Route Extraction

- HTTP paths, methods, status codes, response fields, SSE event shapes, and media types.
- Launcher bootstrap token and Face Gate semantics.
- Step-up auth outcomes and tool policy outcomes.
- Phone bridge token enforcement and Android payload contracts.
- TTS no-overlap/interruption behavior, thinking TTS state, and STT empty transcript handling.
- Frontend/HUD action payloads and streaming timing assumptions.

## Risks And Assumptions

- `app/main.py` globals are the main extraction risk; route modules should receive dependencies explicitly or through a small read-only accessor.
- Chat streaming and TTS share turn-level voice state. Moving one without the other can break cancellation or duplicate audio suppression.
- Phone bridge endpoints are Android-facing; extraction must be covered by parity tests before Android changes are considered.
- Face Gate and step-up auth are separate security boundaries and must not be collapsed during route cleanup.
