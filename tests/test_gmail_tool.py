import unittest

from app.services.contact_match_service import ContactCandidate
from app.services.contact_resolution_service import ContactResolutionService
from app.tools.base import ToolContext
from app.tools.gmail_tool import GmailTool


class FakeGmailConnector:
    def __init__(self, available=True):
        self.calls = []
        self._available = available

    def status(self):
        return {"available": self._available, "status": "ready" if self._available else "not_configured", "message": "Gmail connector is not configured."}

    def send_email(self, *, to, subject, body):
        self.calls.append(("send_email", to, subject, body))
        return {"success": True, "action": "send_email", "message": f"Sent email to {to}."}

    def create_draft(self, *, to, subject, body):
        self.calls.append(("draft_email", to, subject, body))
        return {"success": True, "action": "draft_email", "message": f"Drafted email to {to}."}

    def get_unread_count(self):
        self.calls.append(("get_unread_count",))
        return {"success": True, "action": "get_unread_count", "message": "You have 2 unread Gmail messages.", "count": 2}

    def search_emails(self, *, query):
        self.calls.append(("search_emails", query))
        return {"success": True, "action": "search_emails", "message": "Found 1 email.", "results": [{"id": "m1"}]}


class GmailToolTests(unittest.TestCase):
    def test_explicit_email_send_uses_connector_without_real_side_effects(self):
        connector = FakeGmailConnector()
        tool = GmailTool(connector)

        result = tool.execute(ToolContext(command="Send an email to forserver0101@gmail.com saying hello from Jarvis test", intent="gmail", source="user"))

        self.assertTrue(result["success"])
        self.assertEqual(connector.calls[0], ("send_email", "forserver0101@gmail.com", "Message from Jarvis", "hello from Jarvis test"))

    def test_draft_creates_draft_not_send(self):
        connector = FakeGmailConnector()
        tool = GmailTool(connector)

        result = tool.execute(ToolContext(command="Draft an email to forserver0101@gmail.com saying hello from Jarvis draft test", intent="gmail", source="user"))

        self.assertTrue(result["success"])
        self.assertEqual(connector.calls[0][0], "draft_email")

    def test_unavailable_connector_fails_clearly(self):
        tool = GmailTool(FakeGmailConnector(available=False))

        result = tool.execute(ToolContext(command="Show my unread Gmail count", intent="gmail", source="user"))

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "gmail_unavailable")
        self.assertIn("not configured", result["message"].lower())

    def test_contact_resolution_uses_email_channel(self):
        connector = FakeGmailConnector()
        contacts = ContactResolutionService(
            contacts_provider=lambda: [ContactCandidate(display_name="Hetanshi India", email_address="hetanshi@example.com")]
        )
        tool = GmailTool(connector, contact_resolution_service=contacts)

        result = tool.execute(ToolContext(command="Send an email to Hetanshi India saying hello", intent="gmail", source="user"))

        self.assertTrue(result["success"])
        self.assertEqual(connector.calls[0][1], "hetanshi@example.com")

    def test_missing_body_asks_clarification(self):
        tool = GmailTool(FakeGmailConnector())

        result = tool.execute(ToolContext(command="Send an email to forserver0101@gmail.com", intent="gmail", source="user"))

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "gmail_body_required")

    def test_ambiguous_contact_asks_clarification(self):
        contacts = ContactResolutionService(
            contacts_provider=lambda: [
                ContactCandidate(display_name="Hetanshi India", email_address="hetanshi@example.com"),
                ContactCandidate(display_name="Hetanshi Office", email_address="office@example.com"),
            ]
        )
        tool = GmailTool(FakeGmailConnector(), contact_resolution_service=contacts)

        result = tool.execute(ToolContext(command="Send an email to Hetanshi saying hello", intent="gmail", source="user"))

        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "gmail_contact_ambiguous")


if __name__ == "__main__":
    unittest.main()
