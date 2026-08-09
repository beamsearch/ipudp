import struct
import unittest
from unittest import mock

import udp


class IdentityCipher:
    def reset(self):
        pass

    def encrypt_in_place(self, data):
        pass

    def decrypt(self, data):
        return bytearray(data)


class LoggerStub:
    def __init__(self):
        self.messages = []
        self.traffic = []

    def log(self, message):
        self.messages.append(message)

    def add_traffic(self, mode, size):
        self.traffic.append((mode, size))


class SocketStub:
    def __init__(self, incoming=None):
        self.incoming = incoming
        self.recv_size = None
        self.sent = None

    def recvfrom(self, size):
        self.recv_size = size
        return self.incoming

    def sendto(self, data, address):
        self.sent = (bytes(data), address)


class RandomStub:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def randint(self, lower, upper):
        self.calls.append((lower, upper))
        return self.result


def make_tunnel(mtu=10, do_random_padding=False):
    tunnel = object.__new__(udp.UDPTun)
    tunnel.remote_addr = ("server", 9000)
    tunnel.auth_msg = b"auth"
    tunnel.MTU = mtu
    tunnel.do_random_padding = do_random_padding
    tunnel.encrypter = IdentityCipher()
    tunnel.decrypter = IdentityCipher()
    tunnel.logger = LoggerStub()
    tunnel.socket = SocketStub()
    return tunnel


class UDPTunTests(unittest.TestCase):
    def test_random_padding_uses_uniform_bounded_length_and_random_bytes(self):
        tunnel = make_tunnel(do_random_padding=True)
        random_source = RandomStub(3)

        with mock.patch("udp.PADDING_RANDOM", random_source), \
                mock.patch("udp.os.urandom", return_value=b"\xaa" * 3) as urandom:
            tunnel.send(b"data")

        wire_data, address = tunnel.socket.sent
        self.assertEqual(address, ("server", 9000))
        self.assertEqual(random_source.calls, [(0, 6)])
        urandom.assert_called_once_with(3)
        self.assertEqual(wire_data[:4], b"auth")
        self.assertEqual(struct.unpack("<H", wire_data[4:6])[0], 4)
        self.assertEqual(wire_data[6:10], b"data")
        self.assertEqual(wire_data[10:], b"\xaa" * 3)
        self.assertLessEqual(len(wire_data) - 6, tunnel.MTU)

    def test_mtu_sized_packet_is_not_padded(self):
        tunnel = make_tunnel(do_random_padding=True)
        random_source = RandomStub(1)

        with mock.patch("udp.PADDING_RANDOM", random_source):
            tunnel.send(b"x" * tunnel.MTU)

        self.assertEqual(random_source.calls, [])
        self.assertEqual(len(tunnel.socket.sent[0]), 6 + tunnel.MTU)

    def test_oversized_outbound_packet_is_logged_and_dropped(self):
        tunnel = make_tunnel()

        tunnel.send(b"x" * (tunnel.MTU + 1))

        self.assertIsNone(tunnel.socket.sent)
        self.assertIn("11 bytes", tunnel.logger.messages[0])
        self.assertIn("MTU is 10", tunnel.logger.messages[0])

    def test_receive_reads_and_validates_complete_padded_datagram(self):
        tunnel = make_tunnel()
        sender = ("authenticated", 3000)
        tunnel.remote_addr = ("previous", 2000)
        tunnel.socket = SocketStub((b"auth\x04\x00dataxyz", sender))

        self.assertEqual(tunnel.recv(), b"data")
        self.assertEqual(tunnel.socket.recv_size, udp.MAX_UDP_PAYLOAD_SIZE)
        self.assertEqual(tunnel.remote_addr, sender)
        self.assertEqual(tunnel.logger.traffic, [("i", 13)])

    def test_oversized_received_packet_does_not_update_remote_address(self):
        tunnel = make_tunnel()
        tunnel.remote_addr = ("previous", 2000)
        message = b"auth" + struct.pack("<H", 11) + b"x" * 11
        tunnel.socket = SocketStub((message, ("attacker", 3000)))

        self.assertIsNone(tunnel.recv())
        self.assertEqual(tunnel.remote_addr, ("previous", 2000))
        self.assertIn("11 bytes", tunnel.logger.messages[0])

    def test_padding_larger_than_mtu_is_rejected(self):
        tunnel = make_tunnel()
        message = b"auth" + struct.pack("<H", 3) + b"abc" + b"x" * 8
        tunnel.socket = SocketStub((message, ("sender", 3000)))

        self.assertIsNone(tunnel.recv())
        self.assertIn("11 padded bytes", tunnel.logger.messages[0])

    def test_declared_length_larger_than_datagram_is_rejected(self):
        tunnel = make_tunnel()
        tunnel.socket = SocketStub((b"auth\x05\x00abc", ("sender", 3000)))

        self.assertIsNone(tunnel.recv())
        self.assertIn("declared 5 bytes but received 3", tunnel.logger.messages[0])


if __name__ == "__main__":
    unittest.main()
