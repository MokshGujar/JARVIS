# Security Modes Report

Phase: 20

## Status

- Security modes: implemented as policy-bound helpers.
- Current default preference: Trusted Mode via `JARVIS_SECURITY_MODE=trusted`.
- Unknown mode defaults safe.

## Modes

- Safe Mode: communication requires confirmation; terminal disabled/proposal-only.
- Trusted Mode: exact, fresh, single-recipient communication can be allowed by policy; destructive actions remain protected.
- Developer Mode: terminal still requires explicit permission and destructive shell is blocked.
- Agent Mode: tool allowlists are enforced; hidden communications are not allowed.

## Files

- `app/policy/security_modes.py`
- `app/policy/policy_engine.py`
- `tests/test_security_modes.py`

## Deferred

- User-facing mode switch UI.
- Persistence of per-user mode outside environment/config.
