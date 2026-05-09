# Notification Center Report

Phase: 14

## Status

- Notification center: implemented.
- Storage: additive `notifications` table in `RuntimeStateStore`.
- Runtime data policy: no deletion/migration of existing runtime data; schema addition uses `CREATE TABLE IF NOT EXISTS`.

## Supported Types

- `reminder_due`
- `task_pending`
- `automation_failed`
- `clarification_required`
- `communication_failed`
- `setup_required`
- `agent_report`
- `system_alert`

## Commands Covered

- `What needs my attention?`
- `Show pending actions.`
- `What failed today?`
- `Show my reminders.`
- `Show failed actions.`
- `Clear completed notifications.`
- `Show setup blockers.`

## Safety

- Stale pending notifications are marked stale, not executed.
- Communication failures are reported with recovery context.
- Gmail not configured appears as a setup blocker.
- WhatsApp login/selector failures can be exposed through a status provider.
- Private-looking email addresses and phone numbers are redacted in notification text/metadata.
- Notification center does not replace or duplicate dangerous pending-confirmation execution.

## Files

- `app/services/notification_center_service.py`
- `app/state/runtime_state.py`
- `app/services/fast_intent_router_service.py`
- `app/core/orchestrator.py`
- `app/services/chat_service.py`
- `app/bootstrap/container.py`
- `tests/test_notification_center.py`

## Tests

Planned/added:

- `python -m pytest -q tests/test_notification_center.py`

## Blockers

- Agent reports are type-ready but actual self-created agents are deferred.
- WhatsApp setup blocker status is available through provider injection; live selector/login detection remains dependent on the WhatsApp connector/runtime path.
