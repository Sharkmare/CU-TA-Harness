import os
import tempfile
import unittest
from unittest import mock

import run_tests
from casualtieslink import recovery


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def make(self, stamp, with_registry=True):
        os.makedirs(os.path.join(self.directory.name, "profile-" + stamp))
        if with_registry:
            open(os.path.join(self.directory.name, "prefs-%s.reg" % stamp), "w").close()

    def test_the_latest_snapshot_with_a_prefs_export_is_chosen(self):
        self.make("20261112-081816")
        self.make("20261112-085749")
        self.make("20261112-090000", with_registry=False)
        self.assertEqual(recovery.latest_snapshot_stamp(self.directory.name), "20261112-085749")

    def test_no_snapshot_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            recovery.latest_snapshot_stamp(self.directory.name)

    def test_stray_games_are_killed_by_pid(self):
        calls = []
        found = recovery.stop_stray_games(run=lambda command, **kwargs: calls.append(command), pids=[11, 22])
        self.assertEqual(found, [11, 22])
        self.assertEqual([call[-1] for call in calls], ["11", "22"])

    def test_an_incomplete_snapshot_is_refused_before_anything_is_stopped(self):
        with mock.patch.object(recovery, "stop_stray_games") as stop:
            with self.assertRaises(FileNotFoundError):
                recovery.recover(self.directory.name, os.path.join(self.directory.name, "lock"), "20261112-000000")
        stop.assert_not_called()

    def test_recovery_restores_deletes_the_copies_and_the_lock(self):
        self.make("20261112-085749")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        copy = os.path.join(temp.name, "CU-scenario-host")
        os.makedirs(copy)
        open(os.path.join(copy, ".cu-test-copy"), "w").close()
        lock = os.path.join(self.directory.name, ".game.lock")
        open(lock, "w").close()
        with mock.patch.object(recovery.pair.ProfileGuard, "restore") as restore, mock.patch.object(recovery, "stop_stray_games", return_value=[5]):
            result = recovery.recover(self.directory.name, lock, temp_directory=temp.name)
        restore.assert_called_once()
        self.assertEqual(result, {"stamp": "20261112-085749", "killedGames": [5], "removedCopies": ["CU-scenario-host"], "lockRemoved": True})
        self.assertFalse(os.path.exists(copy))
        self.assertFalse(os.path.exists(lock))


class BudgetTests(unittest.TestCase):
    def test_mining_runs_get_the_long_budget(self):
        self.assertEqual(run_tests.scenario_budget(["v2check", "launch_log_checks"], 15), run_tests.LONG_SCENARIO_BUDGET_SECONDS_PER_RUN * 15 + run_tests.LAUNCH_STARTUP_SECONDS)

    def test_other_scenarios_keep_the_short_budget(self):
        self.assertEqual(run_tests.scenario_budget(["pvp_banded"], 8), run_tests.SCENARIO_BUDGET_SECONDS_PER_RUN * 8 + run_tests.LAUNCH_STARTUP_SECONDS)

    def test_the_long_budget_covers_a_run_that_never_breaks_the_block(self):
        self.assertGreaterEqual(run_tests.LONG_SCENARIO_BUDGET_SECONDS_PER_RUN, 130.0)


if __name__ == "__main__":
    unittest.main()
