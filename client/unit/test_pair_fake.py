import os
import tempfile
import unittest
from unittest import mock

from casualtieslink.games import pair
from casualtieslink.games.pair import GamePair, ProfileGuard


class ProfileGuardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.profile = os.path.join(self.directory.name, "profile")
        self.backups = os.path.join(self.directory.name, "backups")
        os.makedirs(self.profile)
        self.run = mock.patch.object(pair.subprocess, "run")
        self.run_mock = self.run.start()
        self.addCleanup(self.run.stop)
        self.addCleanup(self.directory.cleanup)

    def write(self, name, text):
        path = os.path.join(self.profile, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)

    def read(self, name):
        with open(os.path.join(self.profile, name)) as handle:
            return handle.read()

    def test_files_changed_or_added_during_the_run_are_put_back_exactly(self):
        self.write("settings.json", "original")
        self.write("mp_save/one.json", "keep")
        guard = ProfileGuard(self.backups, self.profile)
        guard.snapshot()
        self.write("settings.json", "changed")
        self.write("save.sv", "new")
        self.write("mp_save/two.json", "new")
        guard.restore()
        self.assertEqual(self.read("settings.json"), "original")
        self.assertEqual(self.read("mp_save/one.json"), "keep")
        self.assertFalse(os.path.exists(os.path.join(self.profile, "save.sv")))
        self.assertFalse(os.path.exists(os.path.join(self.profile, "mp_save", "two.json")))

    def test_player_logs_are_not_touched_either_way(self):
        self.write("Player.log", "before")
        guard = ProfileGuard(self.backups, self.profile)
        guard.snapshot()
        self.write("Player.log", "written by the game")
        self.write("Player-prev.log", "also written")
        guard.restore()
        self.assertEqual(self.read("Player.log"), "written by the game")
        self.assertTrue(os.path.exists(os.path.join(self.profile, "Player-prev.log")))

    def test_the_registry_key_is_exported_before_and_imported_after(self):
        guard = ProfileGuard(self.backups, self.profile)
        guard.snapshot()
        export = self.run_mock.call_args_list[0][0][0]
        self.assertEqual(export[:3], ["reg", "export", pair.PREFS_REGISTRY_KEY])
        open(guard.registry_backup, "w").close()
        guard.restore()
        imported = self.run_mock.call_args_list[1][0][0]
        self.assertEqual(imported, ["reg", "import", guard.registry_backup])

    def test_restore_without_a_snapshot_does_nothing_and_a_second_restore_is_harmless(self):
        guard = ProfileGuard(self.backups, self.profile)
        guard.restore()
        self.run_mock.assert_not_called()
        guard.snapshot()
        guard.restore()
        calls = self.run_mock.call_count
        guard.restore()
        self.assertEqual(self.run_mock.call_count, calls)


class FakeGameProcess:
    instances = []
    fail_client = False

    def __init__(self, port, extra_args=(), directory=None, link_enabled=True, manage_save=True, window_args=None):
        self.port = port
        self.extra_args = list(extra_args)
        self.directory = directory
        self.game = "game-on-%d" % port
        self.started = False
        self.closed = False
        FakeGameProcess.instances.append(self)
        self.log = FakeGameProcess.log

    def start(self, timeout=None, allow_existing=False):
        self.log.append(("start", self.port, allow_existing))
        if self.directory is not None and FakeGameProcess.fail_client:
            raise RuntimeError("client did not start")
        self.started = True

    def close(self):
        self.log.append(("close", self.port))
        self.closed = True


class FakeGuard:
    def __init__(self, backup_root):
        self.backup_root = backup_root
        FakeGameProcess.log.append(("guard created",))

    def snapshot(self):
        FakeGameProcess.log.append(("snapshot",))

    def restore(self):
        FakeGameProcess.log.append(("restore",))


class GamePairTests(unittest.TestCase):
    def setUp(self):
        FakeGameProcess.instances = []
        FakeGameProcess.log = []
        FakeGameProcess.fail_client = False
        self.directory = tempfile.TemporaryDirectory()
        self.copy = os.path.join(self.directory.name, "copy")
        os.makedirs(os.path.join(self.copy, "BepInEx", "plugins", "Together"))
        self.patches = [
            mock.patch.object(pair, "GameProcess", FakeGameProcess),
            mock.patch.object(pair, "ProfileGuard", FakeGuard),
            mock.patch.object(pair, "running_game_pids", return_value=[]),
            mock.patch.object(pair.time, "sleep"),
            mock.patch.object(pair.testcopy, "make_copy", side_effect=self.make_copy),
            mock.patch.object(pair.testcopy, "remove_copy", side_effect=lambda path: FakeGameProcess.log.append(("remove copy", path))),
        ]
        for patch in self.patches:
            patch.start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(self.directory.cleanup)

    def make_copy(self):
        FakeGameProcess.log.append(("make copy",))
        return self.copy

    def test_the_host_starts_before_the_copy_is_made_and_the_client_runs_from_the_copy(self):
        pair_of_games = GamePair(self.directory.name)
        pair_of_games.start()
        self.assertEqual(FakeGameProcess.log, [("guard created",), ("snapshot",), ("start", 7650, False), ("make copy",), ("start", 7651, True)])
        host, client = FakeGameProcess.instances
        self.assertEqual((host.port, client.port, client.directory), (7650, 7651, self.copy))

    def test_both_games_get_the_no_steam_flag_and_their_own_arguments(self):
        GamePair(self.directory.name, host_extra_args=["--a"], client_extra_args=["--b"]).start()
        host, client = FakeGameProcess.instances
        self.assertEqual(host.extra_args, ["--mp-nosteam", "--a"])
        self.assertEqual(client.extra_args, ["--mp-nosteam", "--b"])

    def test_it_refuses_to_start_while_a_game_runs_and_snapshots_nothing(self):
        pair.running_game_pids.return_value = [5]
        with self.assertRaises(RuntimeError):
            GamePair(self.directory.name).start()
        self.assertNotIn(("snapshot",), FakeGameProcess.log)
        self.assertEqual(FakeGameProcess.instances[0].started, False)

    def test_a_client_that_fails_to_start_still_closes_everything_and_restores_the_profile(self):
        FakeGameProcess.fail_client = True
        with self.assertRaises(RuntimeError):
            GamePair(self.directory.name).start()
        self.assertIn(("close", 7650), FakeGameProcess.log)
        self.assertIn(("remove copy", self.copy), FakeGameProcess.log)
        self.assertEqual(FakeGameProcess.log[-1], ("restore",))

    def test_close_closes_the_client_first_then_the_host_removes_the_copy_and_restores(self):
        running = GamePair(self.directory.name).start()
        FakeGameProcess.log.clear()
        running.close()
        self.assertEqual(FakeGameProcess.log, [("close", 7651), ("close", 7650), ("remove copy", self.copy), ("restore",)])

    def test_the_links_run_after_their_game_is_up(self):
        calls = []
        running = GamePair(self.directory.name, after_host_link=lambda game: calls.append(("host", game)),
                           after_client_link=lambda game: calls.append(("client", game)))
        running.start()
        self.assertEqual(calls, [("host", "game-on-7650"), ("client", "game-on-7651")])

    def test_a_replacement_mod_dll_is_copied_into_the_client_copy_only(self):
        replacement = os.path.join(self.directory.name, "stock.dll")
        with open(replacement, "w") as handle:
            handle.write("stock")
        GamePair(self.directory.name, client_plugin_dll=replacement).start()
        with open(os.path.join(self.copy, pair.TOGETHER_DLL_RELATIVE)) as handle:
            self.assertEqual(handle.read(), "stock")


class FlagTests(unittest.TestCase):
    def test_host_and_client_differ_in_name_and_role_and_share_the_address(self):
        host, client = pair.host_flags(), pair.client_flags()
        self.assertTrue(host["starthost"] and host["immidiate-start"] and "startclient" not in host)
        self.assertTrue(client["startclient"] and "starthost" not in client)
        self.assertEqual(host["ip-port"], client["ip-port"])
        self.assertNotEqual(host["setname"], client["setname"])

    def test_debug_can_be_left_out_and_extra_flags_override(self):
        self.assertNotIn("debug", pair.host_flags(debug=False))
        self.assertEqual(pair.client_flags(extra={"setname": "Zed"})["setname"], "Zed")


if __name__ == "__main__":
    unittest.main()
