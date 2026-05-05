# JARVIS Core Architecture

This repository runs the local assistant through `run.py`, which starts the
FastAPI app at `app.main:app`. Runtime code lives under `app/`. The untracked
`config/app/` tree mirrors `app/` and is treated as a generated/config shadow
unless startup imports prove otherwise.

## Canonical Control Flow

All executable automation must flow through this chain:

Frontend / Client
-> FastAPI Gateway
-> Session / Turn Manager
-> Intent / Semantic Layer
-> Planner
-> Policy Engine
-> Executor
-> Tool Registry
-> Tool Modules
-> Providers / Adapters
-> SQLite State + Audit + Observability

The rule is strict:

Planner suggests. Policy approves. Executor executes. Audit records.

No LLM, semantic planner, route handler, compatibility service, or tool may
bypass the policy/executor boundary for protected actions.

## Runtime Responsibilities

`app/main.py` is the FastAPI gateway. It owns request validation, route wiring,
streaming, STT/TTS endpoints, and interrupt entrypoints. Route handlers should
not perform automation directly.

`app/services/interrupt_manager.py` is the current session turn cancellation
primitive. Voice and streaming flows must preserve `session_id`,
`client_request_id`, and `turn_id` semantics so stale work cannot emit final
text or audio.

`app/services/automation_service.py` is a compatibility facade. It may
normalize legacy requests, create or pass session/turn context, call
intent/planner, call policy, call executor, and format responses. It must not
be the authority that directly approves or performs protected work.

`app/orchestrator/task_planner.py`,
`app/orchestrator/smart_automation_planner.py`, and
`app/orchestrator/semantic_planner_adapter.py` are planning layers. They may
produce structured plans and metadata only. They must not call file operations,
browser operations, app launchers, subprocesses, OS automation, or
send-message actions.

`app/policy/policy_engine.py` is the centralized policy authority. It returns
only `ALLOW`, `CONFIRM`, `STEP_UP`, or `DENY` decisions and records why the
decision was made.

`app/orchestrator/tool_executor.py` is the execution boundary used by the
existing orchestrator path. `app/execution/tool_executor.py` may expose the
same executor contract for new imports, but execution still has one shared
policy-enforced boundary.

`app/tools/tool_inventory.py` is the authoritative tool inventory. Runtime
tools must carry metadata for status, routing mode, risk, confirmation,
step-up, dry-run support, adapter/provider, and allowed actions.

## Tool Execution Rules

Only `LIVE` + `ACTIVE` tools may execute freely after policy approval.
`PARTIAL` + `ACTIVE` tools may execute only for explicitly allowed implemented
actions. `PLANNED`, `METADATA_ONLY`, and `DISABLED` tools must never execute.

The executor must resolve registry metadata before execution. Missing metadata
is a failure. Hidden, metadata-only, planned, or disabled tools are blocked
before their `execute()` method is called.

The policy matrix starts with these defaults:

- App open: `ALLOW`
- Browser search/navigation: `ALLOW`
- File read/list/search: `ALLOW` or `CONFIRM` when sensitive
- File create/write/rename/move: `CONFIRM`
- File delete: `CONFIRM`
- Folder delete or bulk delete: `STEP_UP`
- Send message/email/WhatsApp: `CONFIRM`
- Terminal/system command: `DENY` by default
- Planned, metadata-only, or disabled tool: `DENY`

`STEP_UP` implies the action is blocked until step-up has been verified. If a
flow also needs user confirmation, confirmation must be satisfied before the
executor runs the tool.

## Runtime State

SQLite is the runtime state authority for sessions, turns, confirmations,
policy decisions, execution events, and audit events. Every SQLite connection
must enable `PRAGMA foreign_keys=ON`.

YAML and JSON are for static config, manifests, and provider config. Files are
for logs, generated artifacts, screenshots, temporary audio, and TTS/STT
artifacts. Existing JSON state should not be expanded for new runtime control
state.

If an existing SQLite database requires migration, create a timestamped backup
before applying schema changes. Migrations must be additive unless a rollback
plan is documented.

## Voice Turn Correctness

Voice requests must preserve `turn_id` and `session_id`. Empty transcripts must
not create runnable automation commands.

Interrupts must cancel old turns. Stale turns must not emit final text or
final audio. Thinking TTS must be delayed/cancellable and must stop before
final TTS. Final TTS is generated once at the end of the latest valid response.

## Audit And Observability

Every protected action must append an audit event with:

- `session_id`
- `turn_id`
- intent/action
- plan summary
- policy decision
- tool name
- execution result
- error, if any
- timestamp

Audit records are append-only where possible. Execution failures and policy
blocks are audit events too.
