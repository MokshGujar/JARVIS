# Runtime Observability Report

Date: 2026-05-07

## Canonical Logs

- File-search clarification uses `status=clarification_required` at FileTool/ToolExecutor/Orchestrator boundaries.
- System status commands route through canonical orchestration, policy, registry, executor, and SystemTool.
- Browser search remains routed through BrowserTool for explicit web queries.

## Thinking TTS

- Fast responses do not force thinking audio.
- Fast-response skip is observable through `[TTS_THINKING] status=skipped reason=fast_response`.
- Existing duplicate/final/stale thinking TTS skip headers remain unchanged.

## Test Mapping

- `tests/test_runtime_observability.py` is absent.
- Nearest active coverage: `tests/test_canonical_chain_observability.py`, `tests/test_thinking_ack_contract.py`, and browser streaming UX tests.
