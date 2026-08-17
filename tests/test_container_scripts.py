import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MOCK_DOCKER = r'''#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["IPUDP_TEST_DOCKER_LOG"], "w") as log:
    json.dump(sys.argv[1:], log)
'''


class ContainerScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.bin_dir = os.path.join(self.temp_dir, "bin")
        self.log_path = os.path.join(self.temp_dir, "docker.json")
        os.mkdir(self.bin_dir)

        docker_path = os.path.join(self.bin_dir, "docker")
        with open(docker_path, "w") as docker_file:
            docker_file.write(MOCK_DOCKER)
        os.chmod(docker_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

        self.environment = os.environ.copy()
        self.environment.update({
            "IPUDP_TEST_DOCKER_LOG": self.log_path,
            "PATH": self.bin_dir + os.pathsep + self.environment["PATH"],
        })

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def run_script(self, name, arguments):
        result = subprocess.run(
            [os.path.join(ROOT, name)] + arguments,
            cwd=self.temp_dir,
            env=self.environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(self.log_path) as log_file:
            return result, json.load(log_file)

    def assert_relayed(self, docker_arguments, image, main_arguments):
        image_index = docker_arguments.index(image)
        self.assertEqual(docker_arguments[image_index + 1:], main_arguments)

    def test_development_relays_client_arguments_and_mounts_source(self):
        main_arguments = [
            "-key", "0123abcd",
            "-client", "198.51.100.20:48625",
            "-tunnel", "udp",
            "-auth", "message with spaces",
            "-unknown-option",
        ]

        result, docker_arguments = self.run_script(
            "run-development-container.sh",
            main_arguments,
        )

        self.assertEqual(result.stdout + result.stderr, "")
        self.assert_relayed(
            docker_arguments,
            "ipudp-development",
            main_arguments,
        )
        self.assertIn(
            "type=bind,src=" + ROOT + ",dst=/work,readonly",
            docker_arguments,
        )
        self.assertNotIn("-p", docker_arguments)
        self.assertNotIn("--sysctl", docker_arguments)

    def test_development_publishes_server_port_and_relays_arguments(self):
        main_arguments = [
            "-debug",
            "-server", "43210",
            "-key", "0123abcd",
            "-tunnel", "udp",
        ]

        _, docker_arguments = self.run_script(
            "run-development-container.sh",
            main_arguments,
        )

        port_index = docker_arguments.index("-p")
        self.assertEqual(docker_arguments[port_index + 1], "43210:43210/udp")
        sysctl_index = docker_arguments.index("--sysctl")
        self.assertEqual(
            docker_arguments[sysctl_index + 1],
            "net.ipv4.ip_forward=1",
        )
        self.assert_relayed(
            docker_arguments,
            "ipudp-development",
            main_arguments,
        )

    def test_deployment_publishes_server_port_without_mount(self):
        main_arguments = [
            "-key", "0123abcd",
            "-server", "48625",
            "-tunnel", "udp",
            "-do-random-padding",
        ]

        _, docker_arguments = self.run_script(
            "run-deployment-container.sh",
            main_arguments,
        )

        port_index = docker_arguments.index("-p")
        self.assertEqual(docker_arguments[port_index + 1], "48625:48625/udp")
        sysctl_index = docker_arguments.index("--sysctl")
        self.assertEqual(
            docker_arguments[sysctl_index + 1],
            "net.ipv4.ip_forward=1",
        )
        self.assertNotIn("--mount", docker_arguments)
        self.assert_relayed(
            docker_arguments,
            "ipudp-deployment",
            main_arguments,
        )

    def test_deployment_adds_no_main_arguments(self):
        _, docker_arguments = self.run_script(
            "run-deployment-container.sh",
            [],
        )

        self.assert_relayed(docker_arguments, "ipudp-deployment", [])
        self.assertNotIn("-p", docker_arguments)
        self.assertNotIn("--sysctl", docker_arguments)


if __name__ == "__main__":
    unittest.main()
