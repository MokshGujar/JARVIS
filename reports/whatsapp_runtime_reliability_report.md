# WhatsApp Runtime Reliability Report

Last validation update: 2026-05-08.

## Status

Automated WhatsApp validation is green. Runtime readiness is conditionally ready: fresh explicit WhatsApp chat/send/call requests route through `WhatsAppTool`, `ToolExecutor`, and `PolicyEngine`, but live execution still depends on local WhatsApp Desktop/Web availability, login state, contact sync, OS UI automation permissions, and selector verification.

No runtime WhatsApp contact, selector, or login failure log was found during this pass. No broad runtime path was patched without a concrete failure.

## Runtime Behavior

- Direct explicit send/call/open-chat requests resolve contacts first.
- Exact/high-confidence single-contact requests can execute directly in Trusted Mode.
- `Hetanshi India` remains resolvable when the contacts provider includes an exact contact with a phone number.
- STT/fuzzy variants such as `Hitanchi India` and `hitanshi india` require contact clarification first and do not send/call directly.
- `PolicyEngine` allows high-risk external communication only for fresh, explicit, single-recipient, confident, user-initiated commands with required body text.
- `ToolExecutor` remains the execution boundary and records policy/execution results.
- WhatsApp Desktop is tried first for send/chat/call paths.
- If Desktop is unavailable, WhatsApp Web fallback is used only where implemented.
- If Desktop/Web, login, contact phone number, chat verification, send selector, or call selector cannot be verified, the result is a clear failure. The code does not fake success.

## Manual Live Validation Commands

Run only from an active Jarvis runtime session and treat each as a real action:

- `Open WhatsApp chat with Hetanshi India`
- `Send WhatsApp message to Hetanshi India saying hello from Jarvis test`
- `Call Hetanshi India on WhatsApp`

## Automated Safety

The automated WhatsApp tests mock side effects. `tests/test_whatsapp_characterization.py` replaces WhatsApp Desktop/Web behavior with `Mock` instances for open, Web fallback, login-required, send, call, selector failure, missing phone, ambiguous contact, and contact-not-found cases.

## Validation Output

```text
python -m pytest -q tests/test_unified_contact_resolution.py tests/test_whatsapp_characterization.py tests/test_email_command_parser.py tests/test_gmail_tool.py
31 passed, 1 warning in 0.88s
```

```text
python -m pytest -q tests/test_unified_contact_resolution.py tests/test_whatsapp_characterization.py tests/test_automation_reliability.py -p no:cacheprovider
71 passed, 10 subtests passed in 1.70s
```

```text
python -m pytest -q tests -p no:cacheprovider
697 passed, 424 subtests passed in 58.48s
```

## Known Blockers

- Live WhatsApp send/call/open-chat still needs runtime validation on the user's local WhatsApp login/contact/selector state.
- If WhatsApp Web is not logged in, runtime should return `whatsapp_login_required`.
- If selectors cannot be verified, runtime should return an unverified failure and not click/send/call blindly.

