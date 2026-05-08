import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

import app.services.contact_match_service as contact_match_module
from app.services.contact_match_service import ContactCandidate, ContactMatchService
from app.services.contact_resolution_service import ContactResolutionService


class UnifiedContactResolutionTests(unittest.TestCase):
    def test_hetanshi_india_is_preserved_and_exact_match_resolves(self):
        service = ContactResolutionService(
            contacts_provider=lambda: [ContactCandidate(display_name="Hetanshi India", phone_number="+919999999999", email_address="hetanshi@example.com")]
        )

        result = service.resolve("Hetanshi India", source="gmail", required_channel="email")

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["selected_contact"]["display_name"], "Hetanshi India")
        self.assertEqual(result["selected_contact"]["email_address"], "hetanshi@example.com")

    def test_fuzzy_match_is_weak_and_does_not_auto_execute(self):
        service = ContactResolutionService(
            contacts_provider=lambda: [ContactCandidate(display_name="Hetanshi India", phone_number="+919999999999")]
        )

        result = service.resolve("hitanshi india", source="whatsapp", required_channel="whatsapp")

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "weak_match")

    def test_multiple_candidates_are_ambiguous(self):
        service = ContactResolutionService(
            contacts_provider=lambda: [
                ContactCandidate(display_name="Hetanshi India", phone_number="+919999999999"),
                ContactCandidate(display_name="Hetanshi Office", phone_number="+918888888888"),
            ]
        )

        result = service.resolve("Hetanshi", source="whatsapp", required_channel="whatsapp")

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "ambiguous")

    def test_missing_email_channel_blocks_email(self):
        service = ContactResolutionService(
            contacts_provider=lambda: [ContactCandidate(display_name="Hetanshi India", phone_number="+919999999999")]
        )

        result = service.resolve("Hetanshi India", source="gmail", required_channel="email")

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "missing_channel")
        self.assertEqual(result["missing_channels"], ["email"])

    def test_stt_alias_is_not_persisted_until_explicit_confirmation(self):
        root = Path(__file__).resolve().parent / "_tmp" / "contact_aliases"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        try:
            with patch.object(contact_match_module, "PHONE_BRIDGE_DIR", root):
                service = ContactMatchService()
                contacts = [ContactCandidate(display_name="Hetanshi India", phone_number="+919999999999")]

                ranked = service.rank_contacts("Hitanchi India", contacts)
                decision = service.decide("Hitanchi India", ranked)

                self.assertIn(decision.status, {"confirm_contact", "clarify"})
                self.assertFalse((root / "contact_aliases.json").exists())
                self.assertTrue(service.save_confirmed_alias("Hetanshi India", "Hitanchi India"))

                aliases = json.loads((root / "contact_aliases.json").read_text(encoding="utf-8"))
                self.assertEqual(aliases["hetanshi india"], ["hitanchi india"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_persisted_stt_alias_still_requires_confirmation_not_direct_execution(self):
        root = Path(__file__).resolve().parent / "_tmp" / "contact_aliases"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        try:
            with patch.object(contact_match_module, "PHONE_BRIDGE_DIR", root):
                service = ContactMatchService()
                service.save_confirmed_alias("Hetanshi India", "Hitanchi India")

                ranked = service.rank_contacts(
                    "Hitanchi India",
                    [ContactCandidate(display_name="Hetanshi India", phone_number="+919999999999")],
                )
                decision = service.decide("Hitanchi India", ranked)

                self.assertEqual(decision.status, "confirm_contact")
                self.assertEqual(ranked[0].reason, "alias+phone")
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
