import struct
import unittest
from unittest import mock

from crypto import Encrypter, Decrypter
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


class FailingSocketStub(SocketStub):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def sendto(self, data, address):
        raise self.error


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
                mock.patch("udp.os.urandom", side_effect=[b"n" * 8, b"p" * 3]) as urandom:
            tunnel.send(b"data")

        wire_data, address = tunnel.socket.sent
        self.assertEqual(address, ("server", 9000))
        self.assertEqual(random_source.calls, [(0, 6)])
        self.assertEqual(urandom.call_args_list, [mock.call(8), mock.call(3)])
        self.assertEqual(wire_data, b"n" * 8 + b"data" + b"ppp" + b"data-end")

    def test_mtu_sized_packet_is_not_padded(self):
        tunnel = make_tunnel(do_random_padding=True)
        random_source = RandomStub(1)

        with mock.patch("udp.PADDING_RANDOM", random_source):
            tunnel.send(b"x" * tunnel.MTU)

        self.assertEqual(random_source.calls, [])
        self.assertEqual(len(tunnel.socket.sent[0]), 16 + tunnel.MTU)

    def test_oversized_outbound_packet_is_logged_and_dropped(self):
        tunnel = make_tunnel()

        tunnel.send(b"x" * (tunnel.MTU + 1))

        self.assertIsNone(tunnel.socket.sent)
        self.assertIn("11 bytes", tunnel.logger.messages[0])
        self.assertIn("MTU is 10", tunnel.logger.messages[0])

    def test_socket_error_is_logged_and_not_counted_as_traffic(self):
        tunnel = make_tunnel()
        tunnel.socket = FailingSocketStub(OSError("network unavailable"))

        tunnel.send(b"data")

        self.assertIn("network unavailable", tunnel.logger.messages[0])
        self.assertEqual(tunnel.logger.traffic, [])

    def test_unexpected_send_error_propagates(self):
        tunnel = make_tunnel()
        tunnel.socket = FailingSocketStub(RuntimeError("unexpected"))

        with self.assertRaisesRegex(RuntimeError, "unexpected"):
            tunnel.send(b"data")

    def receive(self, message, mtu=100):
        tunnel = make_tunnel(mtu=mtu)
        tunnel.socket = SocketStub((message, ("sender", 3000)))
        result = tunnel.recv()
        if result is None:
            self.assertEqual(tunnel.remote_addr, ("server", 9000))
            self.assertEqual(tunnel.logger.traffic, [])
        return tunnel, result

    def test_receive_ipv4_and_ipv6_with_padding(self):
        for packet in (ipv4(), ipv4(ihl=6), ipv6(), ipv6(b"")):
            for padding in (b"", b"random-data-end"):
                message = frame(packet, padding)
                tunnel, result = self.receive(message)
                self.assertEqual(result, packet)
                self.assertEqual(tunnel.socket.recv_size, udp.MAX_UDP_PAYLOAD_SIZE)
                self.assertEqual(tunnel.remote_addr, ("sender", 3000))
                self.assertEqual(tunnel.logger.traffic, [("i", len(message))])

    def test_oversized_packet_and_padding_are_rejected(self):
        for packet, padding in ((ipv4(b"x" * 81), b""), (ipv4(), b"x" * 80)):
            tunnel, result = self.receive(frame(packet, padding))
            self.assertIsNone(result)
            self.assertIn("padded bytes", tunnel.logger.messages[0])

    def test_invalid_ip_headers_and_lengths_are_rejected(self):
        bad_ihl = bytearray(ipv4())
        bad_ihl[0] = 0x44
        bad_length = bytearray(ipv4(ihl=6))
        bad_length[2:4] = struct.pack('!H', 20)
        for packet in (b"", b"x" * 40, ipv4()[:19], ipv6()[:39],
                       ipv4()[:-1], ipv6()[:-1], bad_ihl, bad_length):
            tunnel, result = self.receive(frame(packet))
            self.assertIsNone(result)
            self.assertTrue(tunnel.logger.messages)

    def test_missing_or_nonfinal_marker_is_decryption_failure(self):
        for message in (b"", frame(ipv4())[:-1], frame(ipv4()) + b"x",
                        frame(ipv4())[:-8] + b"bad-mark"):
            tunnel, result = self.receive(message)
            self.assertIsNone(result)
            self.assertIn("could not decrypt", tunnel.logger.messages[0])

    def test_marker_without_nonce_and_ip_is_rejected(self):
        for message in (b"data-end", b"n" * 8 + b"data-end"):
            self.assertIsNone(self.receive(message)[1])

    def test_encrypted_round_trips_reset_state_and_randomize_nonce(self):
        tunnel = make_tunnel(mtu=100, do_random_padding=True)
        tunnel.encrypter = Encrypter(123)
        tunnel.decrypter = Decrypter(123)
        wires = []
        with mock.patch("udp.PADDING_RANDOM", RandomStub(3)):
            for packet in (ipv4(), ipv6(), ipv4()):
                tunnel.send(packet)
                wire = tunnel.socket.sent[0]
                wires.append(wire)
                tunnel.socket.incoming = (wire, ("sender", 3000))
                self.assertEqual(tunnel.recv(), packet)
        self.assertNotEqual(wires[0], wires[2])
        tunnel.decrypter = Decrypter(456)
        self.assertIsNone(tunnel.recv())
        self.assertIn("could not decrypt", tunnel.logger.messages[-1])


def ipv4(payload=b"data", ihl=5):
    header = bytearray(ihl * 4)
    header[0] = 0x40 | ihl
    header[2:4] = struct.pack('!H', len(header) + len(payload))
    return bytes(header) + payload


def ipv6(payload=b"data"):
    header = bytearray(40)
    header[0] = 0x60
    header[4:6] = struct.pack('!H', len(payload))
    return bytes(header) + payload


def frame(packet, padding=b""):
    return b"n" * 8 + packet + padding + b"data-end"


if __name__ == "__main__":
    unittest.main()
