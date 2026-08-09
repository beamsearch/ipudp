import os
import shutil
import stat
import subprocess
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MOCK_COMMAND = r'''#!/usr/bin/env python3
import os
import sys

command = os.path.basename(sys.argv[0])
arguments = sys.argv[1:]
log_path = os.environ["IPUDP_TEST_LOG"]

with open(log_path, "a") as log:
    log.write(command + " " + " ".join(arguments) + "\n")

invocation = command + " " + " ".join(arguments)
failure = os.environ.get("IPUDP_TEST_FAIL")
failure_marker = log_path + ".failed"
if invocation == failure and not os.path.exists(failure_marker):
    with open(failure_marker, "w"):
        pass
    sys.exit(1)

if command == "ip":
    if arguments == ["-4", "route", "show", "table", "main", "default"]:
        print("default via 192.0.2.1 dev eth0 proto dhcp src 192.0.2.10 metric 100")
    elif arguments[:6] == ["-4", "route", "show", "table", "main", "exact"]:
        pass
    elif arguments[:3] == ["-4", "route", "get"]:
        route_mtu = os.environ.get("IPUDP_TEST_ROUTE_MTU")
        mtu_output = " mtu " + route_mtu if route_mtu else ""
        print(arguments[3] + " via 192.0.2.1 dev eth0 src 192.0.2.10" + mtu_output)
    elif arguments == ["-o", "link", "show", "dev", "eth0"]:
        print("2: eth0: <UP> mtu 1500 qdisc fq_codel state UP")
elif command == "nft":
    if arguments[:3] == ["list", "table", "ip"]:
        sys.exit(1)
    if arguments == ["-f", "-"]:
        with open(log_path, "a") as log:
            log.write(sys.stdin.read())
elif command == "sysctl":
    if arguments == ["-n", "net.ipv4.ip_forward"]:
        print("0")
'''


class NetworkScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.bin_dir = os.path.join(self.temp_dir, "bin")
        self.state_dir = os.path.join(self.temp_dir, "state")
        self.log_path = os.path.join(self.temp_dir, "commands.log")
        os.mkdir(self.bin_dir)

        mock_path = os.path.join(self.bin_dir, "mock-command")
        with open(mock_path, "w") as mock_file:
            mock_file.write(MOCK_COMMAND)
        os.chmod(mock_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        for command in ("ip", "nft", "sysctl"):
            os.symlink(mock_path, os.path.join(self.bin_dir, command))

        self.environment = os.environ.copy()
        self.environment.update({
            "IPUDP_STATE_DIR": self.state_dir,
            "IPUDP_TEST_LOG": self.log_path,
            "PATH": self.bin_dir + os.pathsep + self.environment["PATH"],
            "TUN_NAME": "tun0",
            "TUN_MTU": "1451",
            "AUTH_LENGTH": "19",
        })

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def run_script(self, name, extra_environment=None):
        environment = self.environment.copy()
        if extra_environment:
            environment.update(extra_environment)
        subprocess.check_call([os.path.join(ROOT, name)], env=environment)

    def call_script(self, name, extra_environment=None):
        environment = self.environment.copy()
        if extra_environment:
            environment.update(extra_environment)
        return subprocess.call([os.path.join(ROOT, name)], env=environment)

    def command_log(self):
        with open(self.log_path) as log_file:
            return log_file.read()

    def test_client_setup_and_cleanup(self):
        environment = {"REMOTE_IP": "203.0.113.10"}

        self.run_script("client.sh", environment)
        self.assertTrue(os.path.isdir(os.path.join(self.state_dir, "client-tun0")))

        setup_log = self.command_log()
        self.assertIn(
            "ip link set dev tun0 mtu 1451 up",
            setup_log,
        )
        self.assertIn(
            "ip -4 address replace 10.0.1.1 peer 10.0.1.2/32 dev tun0",
            setup_log,
        )
        self.assertIn(
            "ip -4 route replace 203.0.113.10/32 table main "
            "via 192.0.2.1 dev eth0 src 192.0.2.10",
            setup_log,
        )
        self.assertIn(
            "ip -4 route add default via 10.0.1.2 dev tun0",
            setup_log,
        )

        self.run_script("client-cleanup.sh", environment)
        self.assertFalse(os.path.exists(os.path.join(self.state_dir, "client-tun0")))

        cleanup_log = self.command_log()
        self.assertIn(
            "ip -4 route add default via 192.0.2.1 dev eth0 proto dhcp "
            "src 192.0.2.10 metric 100",
            cleanup_log,
        )
        self.assertIn("ip -4 address flush dev tun0", cleanup_log)
        self.assertIn("ip link set dev tun0 down", cleanup_log)

    def test_client_setup_failure_rolls_back(self):
        environment = {
            "REMOTE_IP": "203.0.113.10",
            "IPUDP_TEST_FAIL":
                "ip -4 route add default via 10.0.1.2 dev tun0",
        }

        self.assertNotEqual(self.call_script("client.sh", environment), 0)
        self.assertFalse(os.path.exists(os.path.join(self.state_dir, "client-tun0")))

        command_log = self.command_log()
        self.assertIn(
            "ip -4 route add default via 192.0.2.1 dev eth0 proto dhcp "
            "src 192.0.2.10 metric 100",
            command_log,
        )
        self.assertIn("ip -4 address flush dev tun0", command_log)

    def test_client_rejects_mtu_larger_than_underlay_allows(self):
        environment = {
            "REMOTE_IP": "203.0.113.10",
            "TUN_MTU": "1452",
        }

        self.assertNotEqual(self.call_script("client.sh", environment), 0)
        self.assertFalse(os.path.exists(os.path.join(self.state_dir, "client-tun0")))
        self.assertNotIn(
            "ip link set dev tun0 mtu 1452 up",
            self.command_log(),
        )

    def test_client_prefers_route_specific_mtu(self):
        environment = {
            "REMOTE_IP": "203.0.113.10",
            "TUN_MTU": "1352",
            "IPUDP_TEST_ROUTE_MTU": "lock 1400",
        }

        self.assertNotEqual(self.call_script("client.sh", environment), 0)
        self.assertFalse(os.path.exists(os.path.join(self.state_dir, "client-tun0")))
        self.assertNotIn(
            "ip -o link show dev eth0",
            self.command_log(),
        )

    def test_server_setup_and_cleanup(self):
        self.run_script("server.sh")
        self.assertTrue(os.path.isdir(os.path.join(self.state_dir, "server-tun0")))

        setup_log = self.command_log()
        self.assertIn(
            "ip link set dev tun0 mtu 1451 up",
            setup_log,
        )
        self.assertIn(
            "ip -4 address replace 10.0.1.2 peer 10.0.1.1/32 dev tun0",
            setup_log,
        )
        self.assertIn("sysctl -q -w net.ipv4.ip_forward=1", setup_log)
        self.assertIn("add table ip ipudp", setup_log)
        self.assertIn(
            "add rule ip ipudp postrouting ip saddr 10.0.1.1 masquerade",
            setup_log,
        )

        self.run_script("server-cleanup.sh")
        self.assertFalse(os.path.exists(os.path.join(self.state_dir, "server-tun0")))

        cleanup_log = self.command_log()
        self.assertIn("nft delete table ip ipudp", cleanup_log)
        self.assertIn("sysctl -q -w net.ipv4.ip_forward=0", cleanup_log)
        self.assertIn("ip -4 address flush dev tun0", cleanup_log)

    def test_server_setup_failure_rolls_back(self):
        environment = {"IPUDP_TEST_FAIL": "nft -f -"}

        self.assertNotEqual(self.call_script("server.sh", environment), 0)
        self.assertFalse(os.path.exists(os.path.join(self.state_dir, "server-tun0")))

        command_log = self.command_log()
        self.assertIn("sysctl -q -w net.ipv4.ip_forward=1", command_log)
        self.assertIn("sysctl -q -w net.ipv4.ip_forward=0", command_log)
        self.assertIn("ip -4 address flush dev tun0", command_log)


if __name__ == "__main__":
    unittest.main()
