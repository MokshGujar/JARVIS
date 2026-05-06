# Runtime Observability Report

Date: 2026-05-06

## Implemented

- Added structured boundary logs for the canonical automation chain:
  - `[ORCHESTRATOR]`
  - `[POLICY]`
  - `[TOOL_REGISTRY]`
  - `[TOOL_EXECUTOR]`
  - `[TOOL]`
- Added thinking acknowledgement/TTS logs:
  - `[ACK] turn_id=<id> type=thinking text_hash=<hash> should_speak=<bool>`
  - `[TTS_THINKING] turn_id=<id> text_hash=<hash> status=<status> reason=<reason>`
- Logs redact sensitive values such as tokens, secrets, message body content, and TTS text.

## Verified

- `tests/test_canonical_chain_observability.py` verifies app open, browser search, and blocked delete emit canonical boundary logs.
- `tests/test_thinking_ack_contract.py` verifies thinking display/TTS use the same acknowledgement hash and stale/duplicate/final-started requests are skipped.

## Remaining

- Some low-level `[AUTOMATION]` logs still appear inside transitional legacy delegates. They are allowed only because those delegates are called from tool classes during this migration phase.
