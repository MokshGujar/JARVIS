# Capability Summary Report

Phase: 12

## Status

- Deterministic capability summary: implemented.
- LLM dependency: none.
- Runtime source of truth: `ToolRegistry`/tool inventory metadata, connector status, feature flags, and runtime service availability.

## Commands Covered

- `What can you do?`
- `What tools do you have?`
- `What is enabled?`
- `Can you access my laptop?`
- `Can you send email?`
- `Can you use WhatsApp?`
- `Can you run terminal commands?`

## Truthful Capability Behavior

- Local laptop file search/read is reported as available when the `file` tool is live-routed.
- App/browser/system capabilities are reported from live-routed tool metadata.
- Gmail is reported unavailable when `GmailConnector.status()` returns `not_configured`.
- WhatsApp is reported available only from live tool metadata, with policy protection noted.
- Terminal execution is reported as proposal-only unless Developer Mode is explicitly enabled.
- LangGraph agents are reported disabled unless `JARVIS_ENABLE_LANGGRAPH_AGENTS=1`.
- Developer Mode and Agent Mode default to disabled.

## Files

- `app/services/capability_summary_service.py`
- `app/services/fast_intent_router_service.py`
- `app/core/orchestrator.py`
- `app/services/chat_service.py`
- `app/bootstrap/container.py`
- `tests/test_capability_summary.py`

## Tests

Planned/added:

- `python -m pytest -q tests/test_capability_summary.py`

## Blockers

- None for deterministic summary.
- Gmail remains unavailable until OAuth/configuration is implemented.
- LangGraph, self-created agents, and Developer Mode remain disabled unless later gated phases are started.
