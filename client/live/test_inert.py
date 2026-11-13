import os
import socket
import subprocess
import time
import unittest

from casualtieslink.launcher import GameProcess, game_dir, mp_arguments, running_game_pids

LOG_RELATIVE_PATH = os.path.join("BepInEx", "LogOutput.log")
CONFIG_FILE_RELATIVE_PATH = os.path.join("BepInEx", "config", "casualtieslink.cfg")
LOG_WAIT_SECONDS = 150.0
TEST_PORT = 7650
DISABLED_MARKER = "CasualtiesLink DISABLED"
ENABLED_MARKER = "CasualtiesLink ENABLED on port %d"


def log_text():
    try:
        with open(os.path.join(game_dir(), LOG_RELATIVE_PATH), encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def wait_for_log(marker, timeout=LOG_WAIT_SECONDS):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if marker in log_text():
            return True
        time.sleep(1.0)
    return False


def port_is_open(port):
    with socket.socket() as probe:
        probe.settimeout(2.0)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def listening_ports(pid):
    output = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    ports = set()
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[3] == "LISTENING" and fields[4] == str(pid):
            ports.add(int(fields[1].rsplit(":", 1)[1]))
    return ports


class DefaultOffTests(unittest.TestCase):
    def setUp(self):
        if running_game_pids():
            self.skipTest("a game is already running; this test must launch its own")
        config_file = os.path.join(game_dir(), CONFIG_FILE_RELATIVE_PATH)
        if os.path.exists(config_file):
            os.remove(config_file)

    def test_no_switch_means_no_socket_and_no_extra_files(self):
        game = GameProcess(TEST_PORT, mp_arguments({"disable": True}), link_enabled=False)
        game.start()
        try:
            self.assertTrue(wait_for_log(DISABLED_MARKER), "disabled startup line never appeared in LogOutput.log")
            time.sleep(5.0)
            self.assertFalse(port_is_open(TEST_PORT), "port %d is open although no switch was given" % TEST_PORT)
            self.assertNotIn(TEST_PORT, listening_ports(game.pid))
            self.assertNotIn(ENABLED_MARKER % TEST_PORT, log_text())
            self.assertFalse(os.path.exists(os.path.join(game_dir(), CONFIG_FILE_RELATIVE_PATH)), "plugin wrote a config file")
        finally:
            game.terminate()

    def test_switch_opens_the_link_and_logs_the_port(self):
        game = GameProcess(TEST_PORT, mp_arguments({"disable": True}), link_enabled=True)
        try:
            status = game.start()
            self.assertEqual(status["port"], TEST_PORT)
            self.assertTrue(wait_for_log(ENABLED_MARKER % TEST_PORT, 30.0), "enabled startup line missing from LogOutput.log")
            self.assertTrue(port_is_open(TEST_PORT))
            self.assertIn(TEST_PORT, listening_ports(game.pid))
            self.assertFalse(os.path.exists(os.path.join(game_dir(), CONFIG_FILE_RELATIVE_PATH)), "plugin wrote a config file")
        finally:
            game.close()


if __name__ == "__main__":
    unittest.main()
