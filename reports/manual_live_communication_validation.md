# Manual Live Communication Validation

Last validation update: 2026-05-08.

Automated tests for Gmail and WhatsApp must use mocked connectors only. Do not run live sends or calls from pytest, startup, background tasks, reminders, recovered pending state, LangGraph agents, or self-created agents.

## How To Run Safely

Run live validation only from an active Jarvis runtime session after you intentionally type or speak one of the commands below. Treat each command as a real action.

## Gmail Setup Status

Current code includes a canonical `GmailTool` shell and `GmailConnector`. The default connector reports `not_configured`, so live Gmail commands will return a setup-needed message until OAuth/configuration is implemented.

## WhatsApp Setup Status

WhatsApp live validation requires synced phone contacts, a confident exact match for `Hetanshi India`, and WhatsApp Desktop or Web availability. If the chat, message box, or call button cannot be verified, Jarvis must report failure and not fake success.

## Commands To Test

- `Open WhatsApp chat with Hetanshi India`
- `Send WhatsApp message to Hetanshi India saying hello from Jarvis test`
- `Call Hetanshi India on WhatsApp`
- `Send an email to forserver0101@gmail.com saying hello from Jarvis test`
- `Draft an email to forserver0101@gmail.com saying hello from Jarvis draft test`
- `Show my unread Gmail count`
- `Search Gmail for emails from forserver0101@gmail.com`
- `Make a WhatsApp video call to Hetanshi India`

## Expected Results

- Gmail configured: send/draft/count/search may execute through `GmailTool`, `PolicyEngine`, and `ToolExecutor`.
- Gmail unavailable: Jarvis says Gmail is not configured.
- WhatsApp exact contact and verified UI: chat/send/call may execute through `WhatsAppTool`, `PolicyEngine`, and `ToolExecutor`.
- WhatsApp missing contact, ambiguous contact, missing phone, unavailable Desktop/Web, or missing selector: Jarvis asks clarification or returns a clear failure.

## Logs To Check

- `[MANUAL_LIVE_VALIDATION] mode=enabled action=<gmail|whatsapp> status=<ready|blocked|executed|failed> reason=<safe_reason>`
- `[POLICY] tool=<gmail|whatsapp> action=<action> risk=HIGH decision=ALLOW reason=explicit_user_command_confident_<contact|recipient>`
- `[TOOL_EXECUTOR] tool=<gmail|whatsapp> action=<action> status=<started|success|failed>`
- `[GMAIL_EXEC]` and `[WHATSAPP_EXEC]` without full message bodies or raw recipient details.

## Automated Test Safety

Confirmed on 2026-05-08:

- `tests/test_gmail_tool.py` uses `FakeGmailConnector`; Gmail send/draft/count/search calls are recorded in memory.
- `tests/test_whatsapp_characterization.py` replaces WhatsApp Desktop/Web surfaces with `Mock` objects for open, send, call, selector failure, login-required, and fallback cases.
- The focused communication tests passed without real WhatsApp sends, real WhatsApp calls, or real Gmail sends.

Manual live commands were not executed during pytest validation. They remain real runtime commands and should only be run intentionally in an active Jarvis runtime session.

## Automated Validation

Full suite:

```text
python -m pytest -q tests -p no:cacheprovider
697 passed, 424 subtests passed in 58.48s
```

Focused file/browser/chat suite:

```text
python -m pytest -q tests/test_file_characterization.py tests/test_browser_tool_orchestrator.py tests/test_chat_service_routing.py
32 passed, 1 warning, 21 subtests passed in 6.26s
```

Focused communication suite:

```text
python -m pytest -q tests/test_unified_contact_resolution.py tests/test_whatsapp_characterization.py tests/test_email_command_parser.py tests/test_gmail_tool.py
31 passed, 1 warning in 0.88s
```

Focused face/thinking/STT suite:

```text
python -m pytest -q tests/test_launcher_bootstrap_and_startup.py tests/test_face_gate_launcher_only.py tests/test_thinking_ack_contract.py tests/test_browser_streaming_ux.py tests/test_stt_transcribe_endpoint.py
69 passed, 1 warning in 8.15s
```

The focused commands emitted `PytestCacheWarning` access-denied warnings while trying to create pytest cache paths. The requested full-suite command used `-p no:cacheprovider` and did not emit that warning.

## Current Blockers

- Gmail live send/draft/search/count is blocked until Gmail OAuth/configuration is implemented.
- WhatsApp live execution depends on local WhatsApp login, contact sync, OS permissions, and UI selector verification.
- No runtime WhatsApp contact, selector, or login failure logs were found in this validation pass, so no runtime path patch was made.
