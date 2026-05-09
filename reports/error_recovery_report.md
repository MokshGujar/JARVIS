# Error Recovery Report

Phase: 19

## Status

- Error recovery service: implemented.
- Structured recovery messages include what failed, why, next step, and retry status.

## Implemented Cases

- Contact not found.
- Gmail not configured.
- WhatsApp selector/message-box missing.
- File query missing.
- Ambiguous file/contact.
- Protected destructive action.
- Unsupported document type.

## Safety

- Recovery messages redact email addresses and phone numbers.
- No tracebacks are returned to the user.
- Destructive actions remain protected.

## Files

- `app/services/error_recovery_service.py`
- `tests/test_error_recovery.py`
