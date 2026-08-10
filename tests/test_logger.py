import re
import socket
import unittest

import logger


class PacketEventTests(unittest.TestCase):
    def test_ipv4_event_contains_timestamp_role_event_and_addresses(self):
        packet = bytearray(20)
        packet[0] = 0x45
        packet[12:16] = socket.inet_pton(socket.AF_INET, "10.0.1.1")
        packet[16:20] = socket.inet_pton(socket.AF_INET, "203.0.113.10")

        event = logger.packet_event("client", "tun-to-udp", packet)

        self.assertRegex(
            event,
            re.compile(
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z "
                r"role=client event=tun-to-udp "
                r"source=10\.0\.1\.1 destination=203\.0\.113\.10$"
            )
        )

    def test_ipv6_event_contains_addresses(self):
        packet = bytearray(40)
        packet[0] = 0x60
        packet[8:24] = socket.inet_pton(socket.AF_INET6, "2001:db8::1")
        packet[24:40] = socket.inet_pton(socket.AF_INET6, "2001:db8::2")

        event = logger.packet_event("server", "udp-to-tun", packet)

        self.assertIn("role=server", event)
        self.assertIn("event=udp-to-tun", event)
        self.assertIn("source=2001:db8::1", event)
        self.assertIn("destination=2001:db8::2", event)

    def test_malformed_packet_uses_unknown_addresses(self):
        event = logger.packet_event("client", "tun-to-udp", b"not an IP packet")

        self.assertIn("source=unknown", event)
        self.assertIn("destination=unknown", event)


if __name__ == "__main__":
    unittest.main()
