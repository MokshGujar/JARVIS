# JARVIS Core Architecture

This repository runs the local assistant through `run.py`, which starts
`app.main:app` on Windows. Runtime code lives under `app/`.

`config/app/` is a config/code shadow of `app/`. Current import search found no
runtime import from `app`, `tests`, `run.py`, or `config.py` into `config.app`;
treat it as non-runtime unless startup imports prove otherwise.

## Canonical Chain

All executable automation must flow through this chain:

Frontend / Client -> FastAPI Gateway -> Session / Turn Manager -> STT / Input
Normalization -> Intent / Semantic Layer -> Planner -> PolicyEngine ->
ToolExecutor -> ToolRegistry -> Tool Modules -> Providers / Adapters -> SQLite
State + Audit + Observability -> Response Formatter -> TTS / Frontend.

The control law is mandatory:

Planner suggests. Policy approves. Executor executes. Audit records. Response
formatter speaks.

No LLM, brain route, task classifier, semantic planner, FastAPI route,
compatibility service, or legacy helper may execute protected work directly.

## Live Runtime Responsibilities

`app/main.py` is the FastAPI gateway. It owns route wiring, request validation,
streaming, STT/TTS endpoints, launcher/face endpoints, and interrupt entrypoints.
Routes must not become automation executors.

Live route groups include health/API, chat and streaming chat, Jarvis unified
streaming, STT, TTS and thinking TTS, interrupt, launcher/enroll assets, launcher
auth, launcher-only face status/verify/enroll/delete, phone bridge, reminders,
Wake-on-LAN test, agent task status, and system metrics.

`app/core/orchestrator.py` is part of the live runtime path. It decides which
capability handles a turn and must preserve the canonical automation chain for
claimed automation.

`app/capabilities/automation.py` adapts runtime context into automation service
calls. It must stay thin and must not bypass policy or executor.

`app/services/automation_service.py` is a compatibility facade target. It may
normalize text, load/pass session and turn context, call semantic/planner layers,
call executor, and format responses. It must not directly open apps, open
browsers, manipulate files, run commands, own final policy decisions, or own
isolated confirmation persistence.

`app/orchestrator/smart_automation_planner.py`,
`app/orchestrator/semantic_planner_adapter.py`, `app/orchestrator/task_planner.py`,
the intent routers, LLM, and brain/task routes are planners/classifiers only.
They must not call tools, providers, AppOpener, pywinauto, `webbrowser`,
`os.startfile`, `subprocess`, file delete/write APIs, or message senders.

`app/policy/policy_engine.py` is mandatory for every executable action. Missing
policy decision means no execution.

`app/orchestrator/tool_executor.py` is the shared execution boundary. Tool calls
must happen there after registry metadata and policy evaluation.

`app/tools/tool_inventory.py` and `app/tools/registry.py` are authoritative for
tool readiness metadata.

## Tool Registry Contract

Every tool/action must have metadata:

- tool name
- category/domain
- status: `LIVE`, `PARTIAL`, `PLANNED`, `DISABLED`
- routing mode: `ACTIVE`, `HIDDEN`, `METADATA_ONLY`, `DISABLED`
- risk level: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`
- confirmation and step-up requirements
- dry-run support
- provider/adapter
- allowed actions

Rules:

- `LIVE` + `ACTIVE` may execute only for allowed actions.
- `PARTIAL` + `ACTIVE` may execute only for implemented safe partial actions.
- `PLANNED`, `METADATA_ONLY`, `HIDDEN`, `DISABLED`, unknown tools, missing
  metadata, and unknown actions never execute.

## Policy Contract

`PolicyEngine` returns only `ALLOW`, `CONFIRM`, `STEP_UP`, or `DENY`.

Default policy:

- Low risk app open/focus, browser search/open URL, system status read, and
  registered safe hotkeys may be `ALLOW`.
- Safe file create/write/append under safe roots with explicit name/content and
  no overwrite may be `ALLOW`; overwrite requires `CONFIRM`.
- UI typing/hotkey/address-bar actions are allowed only for explicit safe
  actions; otherwise require `CONFIRM`.
- Close window/app, send message/email/WhatsApp, browser form submit, and code
  edit apply require confirmation and remain disabled unless safely implemented.
- File/folder delete, bulk delete, terminal commands, power actions, and
  destructive system actions are denied or step-up gated as explicitly modeled.

## Runtime State, Confirmation, And Audit

`app/state/runtime_state.py` is the SQLite-backed runtime authority for sessions,
turns, pending confirmations, policy decisions, execution events, and audit
events. SQLite connections must enable `PRAGMA foreign_keys=ON`.

Schema changes must be additive. If a real runtime database is migrated, create
a timestamped backup first. Tests should use temp SQLite paths.

Pending confirmations must be replay-safe and resolved from canonical state
where available. Scattered in-memory state may be kept only as compatibility
cache, not as authority for protected execution.

Audit records are append-only where possible and must include session, turn,
intent/action, plan summary, policy decision, tool name, execution result, error,
and timestamp for policy blocks and tool executions.

## Voice Turn Correctness

`frontend/script.js` already owns `VoiceTurnManager` and `VoiceAudioQueue`; do
not redesign the HUD.

Empty transcripts must not call chat, thinking TTS, final TTS, interrupt, or
automation. Greetings, acknowledgements, and fast semantic app/file commands must
skip thinking audio. Thinking audio must cancel on `auth_required`,
`confirmation_required`, or interruption. Final TTS must play once for the
current valid turn only.

## Launcher-Only Face Gate

Face verification remains launcher-only:

- preserve launcher face gate, enrollment/profile storage, `/launcher/`,
  `/face/status`, and `/face/verify`
- do not reintroduce `/app` face polling, `face_session_id` in chat/tool
  payloads, or face step-up for normal tools

## Legacy Bypass Containment

Legacy AppOpener, browser helpers, system helpers, old AutomationService methods,
and BRAIN-TASK are fallback only. They must not steal commands claimed by
semantic automation.

Fallback may remain only when semantic planning does not claim the command, the
target is sanitized, the tool is registered live/active for that action, policy
approves, executor executes, and audit records.

Deletion candidates must be proven unused by import/usage search and covered by
replacement tests before removal. Uncertain items are documented as candidates,
not deleted.
