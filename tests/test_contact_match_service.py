import unittest
from pathlib import Path

from app.services.contact_match_service import ContactCandidate, ContactMatchService


class ContactMatchServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = ContactMatchService()

    def test_extracts_normal_whatsapp_and_hinglish_call_names(self):
        cases = {
            "Jarvis call Shakti please": ("shakti", ""),
            "whatsapp call shakt": ("shakt", "whatsapp"),
            "Shakti ko call karo": ("shakti", ""),
            "call Chakti on WhatsApp": ("chakti", "whatsapp"),
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                parsed = self.service.parse_call_intent(command)
                self.assertIsNotNone(parsed)
                self.assertEqual((parsed.contact_name, parsed.call_method), expected)

    def test_ranks_exact_prefix_fuzzy_and_phonetic_candidates(self):
        contacts = [
            ContactCandidate(display_name="Shakti"),
            ContactCandidate(display_name="Rohit"),
            ContactCandidate(display_name="Shakuntala"),
        ]

        exact = self.service.rank_contacts("shakti", contacts)
        self.assertEqual(exact[0].display_name, "Shakti")
        self.assertEqual(exact[0].score, 1.0)

        prefix = self.service.rank_contacts("shakt", contacts)
        self.assertEqual(prefix[0].display_name, "Shakti")
        self.assertGreaterEqual(prefix[0].score, 0.88)

        phonetic = self.service.rank_contacts("chakti", contacts)
        self.assertEqual(phonetic[0].display_name, "Shakti")
        self.assertGreaterEqual(phonetic[0].score, 0.65)

    def test_short_query_and_close_matches_require_clarification(self):
        contacts = [
            ContactCandidate(display_name="Shakti", score=0.94),
            ContactCandidate(display_name="Shakuntala", score=0.91),
        ]

        short_decision = self.service.decide("sha", contacts)
        self.assertEqual(short_decision.status, "clarify")

        close_decision = self.service.decide("shakti", contacts)
        self.assertEqual(close_decision.status, "clarify")

    def test_clarification_resolves_ordinals_and_repeated_name(self):
        key = "pixel-test"
        candidates = [
            ContactCandidate(display_name="Shakti", score=0.8),
            ContactCandidate(display_name="Shakuntala", score=0.78),
        ]
        self.service.save_clarification(key, candidates)
        self.assertEqual(self.service.resolve_clarification(key, "first one").display_name, "Shakti")

        self.service.save_clarification(key, candidates)
        self.assertEqual(self.service.resolve_clarification(key, "Shakuntala").display_name, "Shakuntala")

    def test_external_alias_config_boosts_contact_name(self):
        tmp = Path(__file__).resolve().parent / "_tmp" / "contact_aliases"
        tmp.mkdir(parents=True, exist_ok=True)
        alias_file = tmp / "contact_aliases.json"
        alias_file.write_text('{"shakti": ["iron man"]}', encoding="utf-8")
        try:
            service = ContactMatchService()
            service._aliases_path = alias_file

            ranked = service.rank_contacts("iron man", [ContactCandidate(display_name="Shakti")])

            self.assertEqual(ranked[0].display_name, "Shakti")
            self.assertGreaterEqual(ranked[0].score, 0.9)
        finally:
            if alias_file.exists():
                alias_file.unlink()

    def test_exact_hetanshi_india_auto_resolves(self):
        contacts = [ContactCandidate(display_name="Hetanshi India", phone_number="+919999999999")]

        ranked = self.service.rank_contacts("hetanshi india", contacts)
        decision = self.service.decide("hetanshi india", ranked)

        self.assertEqual(ranked[0].display_name, "Hetanshi India")
        self.assertEqual(ranked[0].reason, "exact")
        self.assertEqual(decision.status, "auto_call")

    def test_typo_hitanshi_india_requires_fuzzy_confirmation(self):
        contacts = [ContactCandidate(display_name="Hetanshi India", phone_number="+919999999999")]

        ranked = self.service.rank_contacts("hitanshi india", contacts)
        decision = self.service.decide("hitanshi india", ranked)

        self.assertEqual(ranked[0].display_name, "Hetanshi India")
        self.assertGreaterEqual(ranked[0].score, 0.88)
        self.assertEqual(decision.status, "confirm_contact")

    def test_partial_hetanshi_returns_unique_candidate_for_confirmation(self):
        contacts = [ContactCandidate(display_name="Hetanshi India", phone_number="+919999999999")]

        ranked = self.service.rank_contacts("hetanshi", contacts)
        decision = self.service.decide("hetanshi", ranked)

        self.assertEqual(ranked[0].display_name, "Hetanshi India")
        self.assertIn(decision.status, {"confirm_contact", "clarify"})

    def test_no_match_stays_not_found(self):
        contacts = [ContactCandidate(display_name="Hetanshi India", phone_number="+919999999999")]

        ranked = self.service.rank_contacts("zzzz nobody", contacts)
        decision = self.service.decide("zzzz nobody", ranked)

        self.assertEqual(decision.status, "not_found")

    def test_multiple_close_contacts_asks_clarification(self):
        contacts = [
            ContactCandidate(display_name="Hetanshi India", phone_number="+919999999999"),
            ContactCandidate(display_name="Hetanshi Office", phone_number="+918888888888"),
        ]

        ranked = self.service.rank_contacts("hetanshi", contacts)
        decision = self.service.decide("hetanshi", ranked)

        self.assertEqual(decision.status, "clarify")

    def test_phone_backed_contact_wins_close_tie(self):
        contacts = [
            ContactCandidate(display_name="Hetanshi India"),
            ContactCandidate(display_name="Hetanshi Inda", phone_number="+919999999999"),
        ]

        ranked = self.service.rank_contacts("hitanshi inda", contacts)

        self.assertEqual(ranked[0].display_name, "Hetanshi Inda")
        self.assertTrue(ranked[0].phone_number)


if __name__ == "__main__":
    unittest.main()
