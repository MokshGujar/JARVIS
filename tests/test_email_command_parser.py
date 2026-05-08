import unittest

from app.tools.email_command_parser import EmailCommandParser


class EmailCommandParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = EmailCommandParser()

    def test_send_email_extracts_explicit_recipient_and_body(self):
        parsed = self.parser.parse("Send an email to forserver0101@gmail.com saying hello from Jarvis test")

        self.assertEqual(parsed.action, "send_email")
        self.assertEqual(parsed.recipient, "forserver0101@gmail.com")
        self.assertEqual(parsed.body, "hello from Jarvis test")

    def test_draft_email_extracts_body(self):
        parsed = self.parser.parse("Draft an email to forserver0101@gmail.com saying hello from Jarvis draft test")

        self.assertEqual(parsed.action, "draft_email")
        self.assertEqual(parsed.body, "hello from Jarvis draft test")

    def test_subject_and_body_are_extracted(self):
        parsed = self.parser.parse("Send email to Hetanshi India with subject Meeting and body I'll join in 10 minutes")

        self.assertEqual(parsed.action, "send_email")
        self.assertEqual(parsed.recipient, "Hetanshi India")
        self.assertEqual(parsed.subject, "Meeting")
        self.assertEqual(parsed.body, "I'll join in 10 minutes")

    def test_gmail_count_and_search(self):
        self.assertEqual(self.parser.parse("Show my unread Gmail count").action, "get_unread_count")
        search = self.parser.parse("Search Gmail for emails from forserver0101@gmail.com")
        self.assertEqual(search.action, "search_emails")
        self.assertEqual(search.recipient, "forserver0101@gmail.com")


if __name__ == "__main__":
    unittest.main()
