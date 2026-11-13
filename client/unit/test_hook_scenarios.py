import os
import tempfile
import unittest
from unittest import mock

from casualtieslink import desync, instances
from scenarios import hook_scenarios as hooks

from .fake_link import FakeFailure, FakeLink
from casualtieslink import Game


def entry(swing, host_delta, client_delta):
    return {"swing": swing, "hostDelta": host_delta, "clientDelta": client_delta}


class DamageIssueTests(unittest.TestCase):
    def test_equal_damage_once_per_swing_has_no_issue(self):
        entries = [entry(index, 19.33, 19.33) for index in range(1, 6)]
        self.assertEqual(hooks.damage_issues(entries, 5), [])

    def test_a_swing_that_did_double_damage_is_flagged(self):
        entries = [entry(1, 19.33, 19.33), entry(2, 38.66, 38.66), entry(3, 19.33, 19.33), entry(4, 19.33, 19.33), entry(5, 19.33, 19.33)]
        issues = hooks.damage_issues(entries, 5)
        self.assertEqual(len(issues), 1)
        self.assertIn("swing 2 did 38.66 against a median of 19.33 (applied twice?)", issues[0])

    def test_a_swing_that_changed_nothing_is_missing_damage(self):
        entries = [entry(1, 19.33, 19.33), entry(2, 0.0, 0.0)]
        self.assertIn("swing 2 changed nothing on the host (damage missing)", hooks.damage_issues(entries, 2))

    def test_host_and_client_disagreeing_is_flagged(self):
        issues = hooks.damage_issues([entry(1, 19.33, 0.0)], 1)
        self.assertIn("swing 1: host lost 19.33 but the client sees 0.00", issues)

    def test_fewer_swings_than_requested_are_reported(self):
        self.assertIn("only 2 of 5 swings fired", hooks.damage_issues([entry(1, 1.0, 1.0), entry(2, 1.0, 1.0)], 5))

    def test_small_rounding_differences_are_not_disagreement(self):
        self.assertEqual(hooks.damage_issues([entry(1, 19.33, 18.9)], 1), [])


class PvpCheckTests(unittest.TestCase):
    def test_no_knockback_at_all_is_an_issue(self):
        context = {"measurements": [dict(entry(index, 5.0, 5.0), extra=[1.0, 1.0]) for index in range(1, 6)]}
        self.assertIn("the victim was never knocked back (host x did not change at any swing)", hooks.pvp_check(context))

    def test_some_knockback_is_enough(self):
        context = {"measurements": [dict(entry(index, 5.0, 5.0), extra=[1.0, 1.0 + (index == 2)]) for index in range(1, 6)]}
        self.assertEqual(hooks.pvp_check(context), [])


class ScatterCheckTests(unittest.TestCase):
    def context(self, far_radiation=0.0, chip=False, distance=300.0, eye=0.0):
        return {"measurements": [
            {"phase": "before", "t": 0.0, "distanceTiles": 3.0, "radiationSickness": 1.0, "eyePanicTime": 0.0, "chipPunishment": False},
            {"phase": "far", "t": 4.0, "distanceTiles": distance, "radiationSickness": 1.0 + far_radiation, "eyePanicTime": eye, "chipPunishment": chip},
            {"phase": "far", "t": 8.0, "distanceTiles": distance, "radiationSickness": 1.0 + far_radiation, "eyePanicTime": eye, "chipPunishment": chip},
        ]}

    def test_an_unchanged_state_far_from_the_host_passes(self):
        self.assertEqual(hooks.scatter_check(self.context()), [])

    def test_growing_radiation_is_an_issue(self):
        self.assertTrue(any("radiationSickness grew" in issue for issue in hooks.scatter_check(self.context(far_radiation=2.0))))

    def test_the_chip_flag_is_an_issue(self):
        self.assertIn("chip_punishment_protocol was true while far", hooks.scatter_check(self.context(chip=True)))

    def test_not_getting_far_enough_is_an_issue(self):
        self.assertTrue(any("never got beyond" in issue for issue in hooks.scatter_check(self.context(distance=100.0))))

    def test_eye_panic_is_an_issue(self):
        self.assertIn("eyePanicTime rose while far", hooks.scatter_check(self.context(eye=1.0)))

    def test_a_setup_error_is_reported_as_such(self):
        self.assertEqual(hooks.scatter_check({"measurements": [{"error": "no open pocket far enough from the host"}]}),
                         ["could not set up: no open pocket far enough from the host"])

    def test_the_distance_needed_is_eighty_metres_in_tiles(self):
        self.assertAlmostEqual(hooks.SCATTER_TILES, 266.67, places=1)
        self.assertTrue(all(abs(column) > hooks.SCATTER_TILES for column in hooks.SCATTER_COLUMNS))


class PocketTests(unittest.TestCase):
    def test_a_pocket_needs_floor_and_three_free_cells(self):
        blocks = {(300, 49): 6}

        def invoke(arguments):
            position = arguments["args"][0]
            return blocks.get((int(position["x"]), int(position["y"])), 0)

        with FakeLink({"invoke": invoke}) as link:
            pocket = hooks.find_far_pocket(Game(link.port), {"x": 15.0, "y": 50.0}, 1000.0)
        self.assertEqual(pocket, {"x": 300.0, "y": 50.2})

    def test_no_floor_anywhere_means_no_pocket(self):
        with FakeLink({"invoke": lambda arguments: 0}) as link:
            self.assertIsNone(hooks.find_far_pocket(Game(link.port), {"x": 15.0, "y": 50.0}, 1000.0))

    def test_columns_outside_the_world_are_skipped(self):
        with FakeLink({"invoke": lambda arguments: 6}) as link:
            self.assertIsNone(hooks.find_far_pocket(Game(link.port), {"x": 15.0, "y": 50.0}, 100.0))


class LaunchLogCheckTests(unittest.TestCase):
    GOOD = "[Info   :  Together] TRANSPILER: Body.Attack TRANSPILER SUCCESS :) \n"
    BAD = "[Warning:  Together] Body.Attack TRANSPILER: hit-loop markers not found, leaving stock IL\n"
    SCATTER = "[Info   :NoScatterPunish] NoScatterPunish: the 'too far from everyone' punishment is off (2 of 2 Together checks replaced)\n"

    def test_success_on_both_and_the_scatter_line_has_no_issues(self):
        checks = desync.launch_log_checks(self.GOOD + self.SCATTER, self.GOOD)
        self.assertEqual(checks["issues"], [])
        self.assertEqual((checks["hostTranspilerSuccess"], checks["clientTranspilerSuccess"]), (1, 1))

    def test_a_missing_success_line_or_a_markers_warning_is_an_issue_per_machine(self):
        checks = desync.launch_log_checks(self.GOOD + self.SCATTER, self.BAD)
        self.assertIn("no 'Body.Attack TRANSPILER SUCCESS' line in the client log", checks["issues"])
        self.assertIn("'loop markers not found' in the client log", checks["issues"])

    def test_a_failed_attack_patch_fails_the_check_even_after_a_success_line(self):
        failed = self.GOOD + "[Error  :  Together] Failed to patch: Body_Attack_MultiplayerPatch: IL Compile Error (unknown location)\n"
        checks = desync.launch_log_checks(failed + self.SCATTER, self.GOOD)
        self.assertEqual(len(checks["hostFailedAttackPatch"]), 1)
        self.assertEqual(checks["clientFailedAttackPatch"], [])
        self.assertTrue(any("Failed to patch: Body_Attack_MultiplayerPatch' in the host log" in issue for issue in checks["issues"]))

    def test_other_failed_patches_do_not_count_as_the_attack_patch(self):
        other = self.GOOD + "[Error  :  Together] Failed to patch: DamagingCrate_OnCollisionEnter2D_MultiplayerPatch: IL Compile Error\n"
        self.assertEqual(desync.launch_log_checks(other + self.SCATTER, self.GOOD)["issues"], [])

    def test_one_of_two_checks_replaced_is_an_issue(self):
        partial = self.SCATTER.replace("2 of 2", "1 of 2")
        self.assertTrue(desync.launch_log_checks(self.GOOD + partial, self.GOOD)["issues"])

    def test_the_scatter_line_can_be_left_out_of_the_expectation(self):
        self.assertEqual(desync.launch_log_checks(self.GOOD, self.GOOD, expect_no_scatter=False)["issues"], [])

    def test_only_new_exception_lines_count(self):
        before = "[Error  :  Together] old NullReferenceException\nfine\n"
        after = before + "[Error  :  Together] new thing\nSystem.Exception: boom\nfine again\n"
        self.assertEqual(desync.new_exception_lines(before, after), ["[Error  :  Together] new thing", "System.Exception: boom"])

    def test_the_checks_are_saved_as_json_named_by_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = desync.save_launch_checks({"issues": []}, directory, "L1-pr24-3d060fe-plain-hook-check")
            self.assertTrue(os.path.basename(path).startswith("launch_checks__L1-pr24-3d060fe-plain-hook-check"))
            self.assertTrue(os.path.exists(path))


class SaveGameLogsTests(unittest.TestCase):
    class Games:
        def log_text(self, which):
            return {"host": "host log line\n", "client": ""}[which]

    def test_both_logs_that_have_text_are_saved_under_the_launch_and_class_name(self):
        with tempfile.TemporaryDirectory() as directory:
            saved = desync.save_game_logs(self.Games(), directory, "L1-pr24-3d060fe-plain-hook-regression", "Desync_x")
            self.assertEqual([os.path.basename(path) for path in saved], ["host-LogOutput.log"])
            with open(saved[0], encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "host log line\n")
            self.assertIn("L1-pr24-3d060fe-plain-hook-regression__Desync_x", saved[0])


class NoScatterInstallTests(unittest.TestCase):
    def test_the_plugin_dll_is_copied_into_its_own_plugin_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "no-scatter-punish", "bin")
            os.makedirs(source)
            with open(os.path.join(source, "NoScatterPunish.dll"), "w") as handle:
                handle.write("plugin")
            copy = os.path.join(directory, "copy")
            os.makedirs(copy)
            with mock.patch.dict(os.environ, {instances.MODS_ROOT_ENVIRONMENT_VARIABLE: directory}):
                instances.install_noscatter(copy)
            installed = os.path.join(copy, "BepInEx", "plugins", "NoScatterPunish", "NoScatterPunish.dll")
            self.assertTrue(os.path.isfile(installed))

    def test_it_is_a_known_plugin_set_and_is_cleared_with_the_others(self):
        self.assertIn("noscatter", instances.PLUGIN_INSTALLERS)
        self.assertIn(instances.NO_SCATTER_FOLDER, instances.MANAGED_FOLDERS)

    def test_a_missing_dll_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {instances.MODS_ROOT_ENVIRONMENT_VARIABLE: directory}):
                with self.assertRaises(FileNotFoundError):
                    instances.install_noscatter(directory)


class GroupTests(unittest.TestCase):
    def test_the_hook_group_loads_the_scatter_plugin_on_the_host_only_and_runs_verbose(self):
        from live import test_desync
        self.assertEqual(test_desync.GROUP_HOST_PLUGINS["hook-check"], ["noscatter"])
        self.assertIn("hook-check", test_desync.PROBE_GROUPS)
        self.assertIn("--mp-verbose", test_desync.GROUP_HOST_ARGUMENTS["hook-check"])

    def test_the_mining_scenario_is_in_the_group_and_takes_every_profile(self):
        self.assertEqual(hooks.HOOK_MINING.group, hooks.HOOK_GROUP)
        self.assertTrue(hooks.HOOK_MINING.network_sensitive)

    def test_the_regression_scenarios_have_a_check_and_never_pass_on_the_verdict_alone(self):
        for scenario in hooks.HOOK_SCENARIOS:
            self.assertTrue(callable(scenario.check), scenario.name)
            self.assertEqual(scenario.group, hooks.HOOK_GROUP)


if __name__ == "__main__":
    unittest.main()
