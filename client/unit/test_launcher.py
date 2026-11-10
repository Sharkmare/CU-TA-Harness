import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from casualtieslink import launcher
from casualtieslink.launcher import GameAlreadyRunning, GameProcess

from .fake_link import FakeLink


START_TIMEOUT = 3.0


class FakeProcess:
    def __init__(self, exit_code=None, wait_times_out=False):
        self.pid = 4242
        self.exit_code = exit_code
        self.returncode = exit_code
        self.wait_times_out = wait_times_out
        self.killed = False

    def poll(self):
        return self.exit_code

    def wait(self, timeout=None):
        if self.wait_times_out and not self.killed:
            raise subprocess.TimeoutExpired("game", timeout)
        return self.exit_code

    def kill(self):
        self.killed = True


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.profile = os.path.join(self.directory.name, "profile")
        os.makedirs(self.profile)
        self.save_path = os.path.join(self.profile, "save.sv")
        self.popen = mock.patch.object(launcher.subprocess, "Popen", return_value=FakeProcess())
        self.pids = mock.patch.object(launcher, "running_game_pids", return_value=[])
        self.sleep = mock.patch.object(launcher.time, "sleep")
        self.spawn = self.popen.start()
        self.pids.start()
        self.sleep.start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(self.directory.cleanup)

    def link(self):
        return FakeLink({"status": {"persistentDataPath": self.profile}, "quit": {}})

    def write_save(self, text):
        with open(self.save_path, "w") as handle:
            handle.write(text)

    def read_save(self):
        with open(self.save_path) as handle:
            return handle.read()

    def test_it_refuses_to_start_while_a_game_runs_and_launches_nothing(self):
        launcher.running_game_pids.return_value = [123]
        with self.assertRaises(GameAlreadyRunning):
            GameProcess(7650, directory=self.directory.name).start(timeout=START_TIMEOUT)
        self.spawn.assert_not_called()

    def test_allow_existing_starts_anyway(self):
        with self.link() as link:
            GameProcess(link.port, directory=self.directory.name, manage_save=False).start(timeout=START_TIMEOUT, allow_existing=True)
        self.spawn.assert_called_once()

    def test_the_command_has_the_exe_window_arguments_extra_arguments_and_the_link_port_in_order(self):
        with self.link() as link:
            GameProcess(link.port, ["--mp-disable"], directory=self.directory.name, window_args=["-w"], manage_save=False).start(timeout=START_TIMEOUT)
        command = self.spawn.call_args[0][0]
        self.assertEqual(command, [os.path.join(self.directory.name, "CasualtiesUnknown.exe"), "-w", "--mp-disable", "--link-port", str(link.port)])
        self.assertEqual(self.spawn.call_args[1]["cwd"], self.directory.name)

    def test_without_the_link_there_is_no_port_argument_and_no_waiting(self):
        process = GameProcess(7650, ["--mp-disable"], directory=self.directory.name, link_enabled=False)
        self.assertIsNone(process.start(timeout=START_TIMEOUT))
        self.assertNotIn("--link-port", self.spawn.call_args[0][0])

    def test_a_game_that_exits_before_the_link_answers_is_reported_with_its_exit_code(self):
        self.spawn.return_value = FakeProcess(exit_code=3)
        process = GameProcess(7650, directory=self.directory.name, manage_save=False)
        process.game.transport.is_up = lambda: False
        with self.assertRaises(RuntimeError) as caught:
            process.start(timeout=START_TIMEOUT)
        self.assertIn("code 3", str(caught.exception))

    def test_a_link_that_never_answers_times_out(self):
        process = GameProcess(7650, directory=self.directory.name, manage_save=False)
        process.game.transport.is_up = lambda: False
        with self.assertRaises(TimeoutError):
            process.start(timeout=0.0)

    def test_an_existing_save_is_put_back_after_the_game_changed_it(self):
        self.write_save("original")
        with self.link() as link:
            process = GameProcess(link.port, directory=self.directory.name)
            process.start(timeout=START_TIMEOUT)
            self.assertTrue(os.path.exists(self.save_path + ".prerig"))
            self.write_save("changed by a test")
            process.close()
        self.assertEqual(self.read_save(), "original")
        self.assertFalse(os.path.exists(self.save_path + ".prerig"))

    def test_a_save_made_during_the_run_is_removed_when_there_was_none_before(self):
        with self.link() as link:
            process = GameProcess(link.port, directory=self.directory.name)
            process.start(timeout=START_TIMEOUT)
            self.write_save("made by a test")
            process.close()
        self.assertFalse(os.path.exists(self.save_path))

    def test_the_save_is_left_alone_when_save_management_is_off(self):
        self.write_save("original")
        with self.link() as link:
            process = GameProcess(link.port, directory=self.directory.name, manage_save=False)
            process.start(timeout=START_TIMEOUT)
            self.write_save("changed")
            process.close()
        self.assertEqual(self.read_save(), "changed")

    def test_close_asks_the_game_to_quit(self):
        with self.link() as link:
            process = GameProcess(link.port, directory=self.directory.name, manage_save=False)
            process.start(timeout=START_TIMEOUT)
            process.close()
        self.assertEqual(len(link.calls_to("quit")), 1)

    def test_close_kills_a_game_that_does_not_quit_in_time(self):
        fake = FakeProcess(wait_times_out=True)
        self.spawn.return_value = fake
        with self.link() as link:
            process = GameProcess(link.port, directory=self.directory.name, manage_save=False)
            process.start(timeout=START_TIMEOUT)
            process.close()
        self.assertTrue(fake.killed)

    def test_a_game_without_the_link_is_killed_on_close(self):
        fake = FakeProcess()
        self.spawn.return_value = fake
        process = GameProcess(7650, directory=self.directory.name, link_enabled=False)
        process.start(timeout=START_TIMEOUT)
        process.close()
        self.assertTrue(fake.killed)


class RunningGamePidTests(unittest.TestCase):
    def pids_from(self, output):
        completed = SimpleNamespace(stdout=output)
        with mock.patch.object(launcher.subprocess, "run", return_value=completed):
            return launcher.running_game_pids()

    def test_every_game_process_is_listed(self):
        output = '"CasualtiesUnknown.exe","1234","Console","1","700,000 K"\r\n"CasualtiesUnknown.exe","99","Console","1","10 K"\r\n'
        self.assertEqual(self.pids_from(output), [1234, 99])

    def test_other_processes_and_the_no_tasks_message_are_ignored(self):
        self.assertEqual(self.pids_from("INFO: No tasks are running which match the specified criteria.\r\n"), [])
        self.assertEqual(self.pids_from('"python.exe","5","Console","1","1 K"\r\n'), [])


class MpArgumentTests(unittest.TestCase):
    def test_value_flags_keep_their_value_in_order(self):
        self.assertEqual(launcher.mp_arguments({"setchar": 2, "debug": True, "mychar": 0}), ["--mp-setchar", "2", "--mp-debug", "--mp-mychar", "0"])

    def test_a_false_flag_is_left_out(self):
        self.assertEqual(launcher.mp_arguments({"starthost": False, "nosteam": True}), ["--mp-nosteam"])


if __name__ == "__main__":
    unittest.main()
