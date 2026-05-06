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

- Some low-level `[AUTOMATION]` logs still appear inside connectors/adapters and transitional delegate call paths. They are now downstream of tool execution and should be read together with the boundary logs.

## Representative Expected Logs

- `open calculator`:
  `[ORCHESTRATOR] ... tool=app action=open status=executing`
  `[POLICY] tool=app action=open risk=low decision=allow`
  `[TOOL_REGISTRY] tool=app action=open status=resolved`
  `[TOOL_EXECUTOR] tool=app action=open status=started policy_decision=allow`
  `[TOOL] name=AppTool action=open delegate=legacy_delegate status=success target="open calculator"`
- `search Google for cats`:
  `[ORCHESTRATOR] ... tool=browser action=search status=executing`
  `[POLICY] tool=browser action=search risk=low decision=allow`
  `[TOOL_REGISTRY] tool=browser action=search status=resolved`
  `[TOOL_EXECUTOR] tool=browser action=search status=success policy_decision=allow`
  `[TOOL] name=BrowserTool action=search delegate=legacy_delegate status=success target="cats"`
- `search files`:
  `[ORCHESTRATOR] ... tool=file action=search_files status=blocked`
  response asks which file name or content to search for; no BrowserTool log is expected.
- `send WhatsApp message ...`:
  `[POLICY] tool=whatsapp action=send_message risk=high decision=confirm`
  message body is redacted from logs.
- `shutdown computer`:
  `[POLICY] tool=system action=shutdown risk=critical decision=confirm|step_up|deny`
  no power primitive is executed in tests.
