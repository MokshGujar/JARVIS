import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import main
from app.services.wake_on_lan_service import WakeOnLanService


class WakeOnLanServiceTests(unittest.TestCase):
    def test_magic_packet_is_102_bytes_and_contains_mac(self):
        service = WakeOnLanService(mac_address="AA:BB:CC:DD:EE:FF")

        packet = service._build_magic_packet("AA:BB:CC:DD:EE:FF")

        self.assertEqual(len(packet), 102)
        self.assertEqual(packet[:6], b"\xff" * 6)
        self.assertEqual(packet[6:12], bytes.fromhex("AABBCCDDEEFF"))
        self.assertEqual(packet[-6:], bytes.fromhex("AABBCCDDEEFF"))

    def test_invalid_mac_returns_clear_error(self):
        service = WakeOnLanService(mac_address="invalid")

        result = service.wake_laptop()

        self.assertFalse(result["success"])
        self.assertIn("12-hex-digit MAC", result["message"])

    def test_wake_phrases_are_detected(self):
        service = WakeOnLanService(mac_address="AA:BB:CC:DD:EE:FF")

        self.assertTrue(service.looks_like_wake_request("wake my laptop"))
        self.assertTrue(service.looks_like_wake_request("turn on my PC"))
        self.assertTrue(service.looks_like_wake_request("power on my computer"))
        self.assertFalse(service.looks_like_wake_request("wake me up tomorrow"))

    def test_wake_request_sends_packet_to_configured_broadcast(self):
        service = WakeOnLanService(
            mac_address="AA:BB:CC:DD:EE:FF",
            broadcast_ip="192.168.1.255",
            port=7,
        )
        fake_socket = MagicMock()

        with patch("socket.socket") as socket_factory:
            socket_factory.return_value.__enter__.return_value = fake_socket
            result = service.wake_laptop()

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Wake-on-LAN packet sent.")
        sent_packet, sent_address = fake_socket.sendto.call_args.args
        self.assertEqual(len(sent_packet), 102)
        self.assertEqual(sent_address, ("192.168.1.255", 7))

    def test_wake_on_lan_test_endpoint_reports_unconfigured(self):
        previous = main.wake_on_lan_service
        main.wake_on_lan_service = WakeOnLanService(mac_address="")
        try:
            with patch.object(main, "PHONE_BRIDGE_TOKEN", ""):
                response = TestClient(main.app).post("/wake-on-lan/test")
        finally:
            main.wake_on_lan_service = previous

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertFalse(result["configured"])
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
