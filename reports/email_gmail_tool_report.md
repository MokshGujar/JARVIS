# Email Gmail Tool Report

Last validation update: 2026-05-08.

## Status

Automated Gmail parser/tool validation is green. Runtime Gmail readiness is blocked because the default `GmailConnector` reports `not_configured`.

The behavior is intentionally fail-closed: Gmail live send, draft, unread count, search, read latest, and reply actions return a setup-needed response until OAuth/configuration is implemented. No Gmail success is faked.

## Runtime Behavior

- `EmailCommandParser` recognizes explicit send, draft/compose/write, unread count, search-from, read-latest, reply-latest, and subject/body commands.
- `GmailTool` resolves explicit email addresses directly.
- `GmailTool` can resolve named contacts through `ContactResolutionService` when an email channel is available.
- Missing body returns `gmail_body_required`.
- Ambiguous contacts return `gmail_contact_ambiguous`.
- Missing email channel returns `gmail_email_missing`.
- Unavailable connector returns `gmail_unavailable` with `status=not_configured`.
- Fresh explicit Gmail execution still goes through `ToolExecutor` and `PolicyEngine`.

## Manual Live Validation Commands

Run only after Gmail OAuth/configuration exists:

- `Send an email to forserver0101@gmail.com saying hello from Jarvis test`
- `Draft an email to forserver0101@gmail.com saying hello from Jarvis draft test`
- `Show my unread Gmail count`

Expected current result before OAuth/configuration:

- `success=False`
- `action=gmail_unavailable`
- `status=not_configured`
- message states that Gmail is not configured

## Automated Safety

The automated Gmail tests mock side effects. `tests/test_gmail_tool.py` uses `FakeGmailConnector`; send/draft/count/search calls are stored in `connector.calls` and no real Gmail API or SMTP send is used.

## Validation Output

```text
python -m pytest -q tests/test_unified_contact_resolution.py tests/test_whatsapp_characterization.py tests/test_email_command_parser.py tests/test_gmail_tool.py
31 passed, 1 warning in 0.88s
```

```text
python -m pytest -q tests -p no:cacheprovider
697 passed, 424 subtests passed in 58.48s
```

## Known Blockers

- Gmail OAuth/configuration is not implemented/configured in `GmailConnector`.
- Live Gmail actions must keep returning setup-needed/not-configured until the connector is real.

