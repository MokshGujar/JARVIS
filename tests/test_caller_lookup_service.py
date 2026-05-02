import unittest

from app.services.caller_lookup_service import CallerIdentityResult, CallerLookupService


class FakeRealtimeService:
    def search_tavily(self, query, num_results=5):
        raise AssertionError("High-confidence provider result should skip public web lookup")


class FakeProvider:
    source = "fake_provider"

    def lookup(self, normalized_number):
        return CallerIdentityResult(
            display_name="Test Caller",
            normalized_number=normalized_number,
            carrier="Example Carrier",
            line_type="mobile",
            country="IN",
            location="Delhi",
            spam_risk="low",
            confidence=0.9,
            source=self.source,
        )


class CallerLookupProviderTests(unittest.TestCase):
    def test_high_confidence_provider_result_shapes_incoming_payload(self):
        service = CallerLookupService(FakeRealtimeService())
        service._provider = FakeProvider()

        payload = service.build_incoming_call_payload("+91 98765 43210", speak_result=False)

        self.assertEqual(payload["source"], "fake_provider")
        self.assertEqual(payload["confidence"], 0.9)
        self.assertEqual(payload["display_name"], "Test Caller")
        self.assertEqual(payload["carrier"], "Example Carrier")
        self.assertEqual(payload["line_type"], "mobile")
        self.assertEqual(payload["country"], "IN")
        self.assertEqual(payload["location"], "Delhi")
        self.assertEqual(payload["spam_risk"], "low")
        self.assertIn("Test Caller", payload["summary"])
        self.assertEqual(payload["speak_text"], "")


if __name__ == "__main__":
    unittest.main()
