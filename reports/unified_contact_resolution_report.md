# Unified Contact Resolution Report

Last validation update: 2026-05-08.

## Status

Unified contact resolution validation is green. The shared resolver preserves full display names, checks required channels, and prevents weak/STT matches from direct communication execution.

## Behavior Confirmed

- Exact contact matches return `status=matched`.
- Fuzzy but plausible contact matches return `status=weak_match` and require confirmation.
- Multiple plausible matches return `status=ambiguous`.
- Missing contacts return `status=not_found`.
- WhatsApp-required contacts without a phone number return `status=missing_channel`.
- Gmail-required contacts without an email address return `status=missing_channel`.
- `Hetanshi India` remains preserved as the selected contact.
- STT variants such as `Hitanchi India` suggest `Hetanshi India` but do not auto-send/call/email.
- Persisted aliases are saved only after explicit confirmation.
- Persisted aliases still remain confirmation-required and do not become direct auto-call/send matches.

## Side-Effect Safety

- Contact resolution tests use in-memory `ContactCandidate` providers.
- WhatsApp send/call/open paths are mocked in automated tests.
- Gmail tests use `FakeGmailConnector`.
- Pytest redirects runtime contact alias writes into ignored `tests/_tmp`, not `database/phone_bridge/contact_aliases.json`.

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

- Runtime WhatsApp readiness still depends on a live exact/high-confidence contact with a WhatsApp-capable phone number.
- Runtime Gmail named-contact sending still depends on contacts containing an email address and on Gmail connector configuration.

