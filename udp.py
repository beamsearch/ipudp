import os
import socket
import struct
import random

MAX_UDP_PAYLOAD_SIZE = 65507
NONCE_SIZE = 8
DATA_END = b"data-end"
FRAMING_OVERHEAD = NONCE_SIZE + len(DATA_END)
PADDING_RANDOM = random.SystemRandom()

class UDPTun:
    def __init__(
        self,
        mode, addr,
        encrypter, decrypter,
        MTU,
        do_random_padding,
        logger
    ):
        self.mode = mode
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.encrypter = encrypter
        self.decrypter = decrypter
        self.MTU = MTU
        self.do_random_padding = do_random_padding
        self.logger = logger

        if mode == 'c':
            self.remote_addr = addr
        elif mode == 's':
            self.remote_addr = None
            self.socket.bind(addr)
        else:
            raise Exception("unknown mode" + mode)

    def send(self, data):
        if len(data) > self.MTU:
            self.logger.log(
                    "UDPTun.send: dropping packet of {} bytes; configured MTU is {}".format(
                    len(data), self.MTU
                )
            )
            return

        if self.remote_addr is not None:
            padding_size = 0
            if self.do_random_padding and len(data) < self.MTU:
                padding_size = PADDING_RANDOM.randint(0, self.MTU - len(data))

            msg = bytearray(os.urandom(NONCE_SIZE))
            msg.extend(data)
            if padding_size > 0:
                msg.extend(os.urandom(padding_size))
            msg.extend(DATA_END)

            self.encrypter.reset()
            self.encrypter.encrypt_in_place(msg)

            try:
                self.socket.sendto(msg, self.remote_addr)
            except OSError as ex:
                self.logger.log(f'UDPTun.send: socket.sendto reported this error: {ex}')
            else:
                self.logger.add_traffic('o', len(msg))

    def recv(self):
        msg, remote_addr = self.socket.recvfrom(MAX_UDP_PAYLOAD_SIZE)

        self.decrypter.reset()
        msg = self.decrypter.decrypt(msg)

        if not msg.endswith(DATA_END):
            self.logger.log("could not decrypt packet from peer " + str(remote_addr))
            return None
        if len(msg) < FRAMING_OVERHEAD + 1:
            self.logger.log("invalid packet from " + str(remote_addr) + ": too short")
            return None

        data = msg[NONCE_SIZE:-len(DATA_END)]
        padded_data_size = len(data)
        if padded_data_size > self.MTU:
            self.logger.log(
                "dropping packet from {} with {} padded bytes; configured MTU is {}".format(
                    remote_addr, padded_data_size, self.MTU
                )
            )
            return None

        version = data[0] >> 4
        if version == 4 and len(data) >= 20:
            header_size = (data[0] & 15) * 4
            data_size = struct.unpack('!H', data[2:4])[0]
            if header_size < 20 or data_size < header_size:
                self.logger.log("invalid IPv4 length from " + str(remote_addr))
                return None
        elif version == 6 and len(data) >= 40:
            data_size = 40 + struct.unpack('!H', data[4:6])[0]
        else:
            self.logger.log("invalid or truncated IP header from " + str(remote_addr))
            return None

        if data_size > padded_data_size:
            self.logger.log(
                "invalid packet from {}: declared {} bytes but received {}".format(
                    remote_addr, data_size, padded_data_size
                )
            )
            return None

        self.remote_addr = remote_addr
        self.logger.add_traffic('i', len(msg))
        return data[:data_size]
