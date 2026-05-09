import time
import shutil
from pathlib import Path

from app.services.notification_center_service import NotificationCenterService
from app.state.runtime_state import RuntimeStateStore


class FakeUnavailableGmail:
    def status(self):
        return {
            "available": False,
            "status": "not_configured",
            "message": "Gmail connector is not configured.",
        }


class FakeReminderService:
    def get_due_reminders(self):
        return [{"id": "r1", "message": "drink water"}]


ROOT = Path(__file__).resolve().parent / "_tmp" / "notification_center"


def make_service(name, **kwargs):
    root = ROOT / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    store = RuntimeStateStore(root / "runtime.sqlite3")
    return NotificationCenterService(store=store, gmail_connector=FakeUnavailableGmail(), **kwargs)


def test_add_list_and_clear_notification():
    service = make_service("add_list")

    service.add_notification("task_pending", title="Review", message="Check the build", status="completed")
    listed = service.list_notifications(statuses=("completed",))
    cleared = service.clear_completed()

    assert listed[0]["title"] == "Review"
    assert cleared == 1
    assert service.list_notifications(statuses=("completed",)) == []


def test_failed_action_appears_with_redaction():
    service = make_service("failed_redaction")

    service.add_failed_action(
        title="Email failed",
        message="Could not email forserver0101@gmail.com at +919999999999",
        source="gmail",
    )
    result = service.handle_request("show failed actions")

    assert "Email failed" in result["message"]
    assert "forserver0101@gmail.com" not in result["message"]
    assert "+919999999999" not in result["message"]


def test_stale_pending_communication_does_not_execute():
    service = make_service("stale")

    service.add_notification(
        "communication_failed",
        title="Pending send expired",
        message="A communication action expired before confirmation.",
        status="pending",
        expires_at=time.time() - 1,
    )
    items = service.list_notifications(statuses=("stale",), notification_types=("communication_failed",))

    assert len(items) == 1
    assert items[0]["status"] == "stale"


def test_setup_blockers_include_gmail_and_whatsapp():
    service = make_service(
        "setup_blockers",
        whatsapp_status_provider=lambda: {
            "available": False,
            "status": "login_required",
            "message": "WhatsApp login required.",
        },
    )

    result = service.handle_request("show setup blockers")

    assert "Gmail setup required" in result["message"]
    assert "WhatsApp setup required" in result["message"]


def test_due_reminders_are_exposed_if_service_supports_them():
    service = make_service("due_reminders", reminder_service=FakeReminderService())

    result = service.handle_request("show my reminders")

    assert "Reminder due" in result["message"]
    assert "drink water" in result["message"]
