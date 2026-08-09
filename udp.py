
import os
import socket
import struct
import random

MAX_UDP_PAYLOAD_SIZE = 65507
PADDING_RANDOM = random.SystemRandom()

class UDPTun:
    def __init__(
        self,
        mode, addr,
        encrypter, decrypter, auth_msg,
        MTU,
        do_random_padding,
        logger
    ):
        self.mode = mode
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.encrypter = encrypter
        self.decrypter = decrypter
        self.auth_msg = auth_msg
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
                "dropping packet of {} bytes; configured MTU is {}".format(
                    len(data), self.MTU
                )
            )
            return

        if self.remote_addr is not None:
            padding_size = 0
            if self.do_random_padding and len(data) < self.MTU:
                padding_size = PADDING_RANDOM.randint(0, self.MTU - len(data))

            msg = bytearray(len(data) + padding_size + len(self.auth_msg) + 2)
            msg[0:len(self.auth_msg)] = self.auth_msg
            msg[len(self.auth_msg):len(self.auth_msg)+2] = struct.pack('<H', len(data))
            msg[len(self.auth_msg)+2:len(self.auth_msg)+2+len(data)] = data
            if padding_size > 0:
                msg[len(self.auth_msg)+2+len(data):] = os.urandom(padding_size)

            self.encrypter.reset()
            self.encrypter.encrypt_in_place(msg)

            self.socket.sendto(msg, self.remote_addr)

            self.logger.add_traffic('o', len(msg))

    def recv(self):
        msg, remote_addr = self.socket.recvfrom(MAX_UDP_PAYLOAD_SIZE)

        self.decrypter.reset()
        msg = self.decrypter.decrypt(msg)

        header_size = len(self.auth_msg) + 2
        if len(msg) < header_size:
            self.logger.log("invalid packet from " + str(remote_addr) + ": too short")
            return None
        elif msg[0:len(self.auth_msg)] != self.auth_msg:
            self.logger.log("authentication failure from " + str(remote_addr))
            return None

        data_size = struct.unpack('<H', msg[len(self.auth_msg):header_size])[0]
        padded_data_size = len(msg) - header_size
        if data_size > self.MTU:
            self.logger.log(
                "dropping packet from {} containing {} bytes; configured MTU is {}".format(
                    remote_addr, data_size, self.MTU
                )
            )
            return None
        elif padded_data_size > self.MTU:
            self.logger.log(
                "dropping packet from {} with {} padded bytes; configured MTU is {}".format(
                    remote_addr, padded_data_size, self.MTU
                )
            )
            return None
        elif data_size > padded_data_size:
            self.logger.log(
                "invalid packet from {}: declared {} bytes but received {}".format(
                    remote_addr, data_size, padded_data_size
                )
            )
            return None

        self.remote_addr = remote_addr
        self.logger.add_traffic('i', len(msg))
        return msg[header_size:header_size+data_size]
