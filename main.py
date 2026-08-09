
import sys
import signal
import os
import subprocess
import selectors

import importlib
logger = importlib.import_module("logger")
tun = importlib.import_module("tun")
crypto = importlib.import_module("crypto")
udp = importlib.import_module("udp")

tun_name = ""

mode = None
addr = None

key = None
auth_msg = b"Infinite Socks Auth"

tunnel_type = None
MTU = 1000
do_random_padding = False

MAX_IP_PACKET_SIZE = 65535
OUTER_IPV4_HEADER_SIZE = 20
UDP_HEADER_SIZE = 8
PAYLOAD_LENGTH_FIELD_SIZE = 2

i = 1
while i < len(sys.argv):
    if sys.argv[i] == '-tun':
        i = i + 1
        tun_name = sys.argv[i]
    elif sys.argv[i] == '-client':
        mode = 'c'
        i = i + 1
        ip_and_port = sys.argv[i].split(sep=':', maxsplit=2)
        addr = (ip_and_port[0], int(ip_and_port[1], 10))
    elif sys.argv[i] == '-server':
        mode = 's'
        i = i + 1
        addr = ("", int(sys.argv[i], 10))
    elif sys.argv[i] == '-key':
        i = i + 1
        key = int(sys.argv[i], 16)
    elif sys.argv[i] == '-auth':
        i = i + 1
        auth_msg = sys.argv[i].encode('utf-8')
    elif sys.argv[i] == '-tunnel':
        i = i + 1
        tunnel_type = sys.argv[i]
    elif sys.argv[i] == '-mtu':
        i = i + 1
        MTU = int(sys.argv[i], 10)
    elif sys.argv[i] == '-do-random-padding':
        do_random_padding = True
    else:
        raise Exception("unknown option " + sys.argv[i])
    i = i + 1

if mode is None:
    print("no mode specified")
    exit(1)
elif key is None:
    print("so key specified")
    exit(1)
elif tunnel_type is None:
    print("no tunnel type specified")
    exit(1)
elif MTU < 68:
    print("MTU must be at least 68")
    exit(1)
elif MTU + len(auth_msg) + PAYLOAD_LENGTH_FIELD_SIZE > udp.MAX_UDP_PAYLOAD_SIZE:
    print("MTU and authentication message exceed the IPv4 UDP payload limit")
    exit(1)
elif tunnel_type == 'udp':
    traffic_logger = logger.Logger(5)
    tunnel = udp.UDPTun(
        mode, addr,
        crypto.Encrypter(key), crypto.Decrypter(key), auth_msg,
        MTU,
        do_random_padding,
        traffic_logger
    )
else:
    print("unknown tunnel type", tunnel_type)
    exit(1)

tun = tun.Tun(tun_name)
os.putenv("TUN_NAME", tun.name)
os.putenv("TUN_MTU", str(MTU))
minimum_required_underlay_mtu = (
    MTU + OUTER_IPV4_HEADER_SIZE + UDP_HEADER_SIZE
    + PAYLOAD_LENGTH_FIELD_SIZE + len(auth_msg)
)
os.putenv(
    "MINIMUM_REQUIRED_UNDERLAY_MTU",
    str(minimum_required_underlay_mtu)
)
script_dir = os.path.dirname(os.path.abspath(__file__))
if mode == 'c':
    os.putenv("REMOTE_IP", addr[0])
    os.putenv("REMOTE_PORT", str(addr[1]))
    setup_script = os.path.join(script_dir, "client.sh")
    cleanup_script = os.path.join(script_dir, "client-cleanup.sh")
else:
    os.putenv("LISTEN_PORT", str(addr[1]))
    setup_script = os.path.join(script_dir, "server.sh")
    cleanup_script = os.path.join(script_dir, "server-cleanup.sh")

def exit_on_signal(signal, frame):
    raise SystemExit(0)

for sig in [ signal.SIGHUP, signal.SIGINT, signal.SIGQUIT, signal.SIGTERM ]:
    signal.signal(sig, exit_on_signal)

setup_complete = False
try:
    subprocess.run([setup_script], check=True)
    setup_complete = True

    sel = selectors.DefaultSelector()
    sel.register(tun.fd, selectors.EVENT_READ, 0)
    sel.register(tunnel.socket, selectors.EVENT_READ, 1)

    while True:
        for (skey, mask) in sel.select():
            if skey.data == 0:
                data = os.read(tun.fd, MAX_IP_PACKET_SIZE)
                if len(data) == 0:
                    raise RuntimeError("TUN device closed")
                elif len(data) > MTU:
                    traffic_logger.log(
                        "dropping TUN packet of {} bytes; configured MTU is {}".format(
                            len(data), MTU
                        )
                    )
                else:
                    tunnel.send(data)
            elif skey.data == 1:
                data = tunnel.recv()
                if data is not None:
                    if len(data) > MTU:
                        traffic_logger.log(
                            "dropping UDP packet containing {} bytes; configured MTU is {}".format(
                                len(data), MTU
                            )
                        )
                    else:
                        written = os.write(tun.fd, data)
                        if written != len(data):
                            raise RuntimeError("incomplete TUN packet write")
finally:
    if setup_complete:
        subprocess.run([cleanup_script], check=True)
