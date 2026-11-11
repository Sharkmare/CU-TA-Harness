import unittest

from casualtieslink import Game, desync, instances
from tests import regression_scenarios as regress
from unittest import mock
import os
import tempfile

from .fake_link import FakeFailure, FakeLink


def candidate(name, health, position, indestructible=False, cant_hit=False):
    return {"id": 1, "name": name, "position": position, "health": health, "indestructible": indestructible, "cantHit": cant_hit}


def entry(swing, host_delta, client_delta):
    return {"swing": swing, "hostDelta": host_delta, "clientDelta": client_delta}


class PickTargetTests(unittest.TestCase):
    anchor = {"x": 0.0, "y": 0.0}

    def test_the_nearest_destructible_building_in_the_health_range_is_chosen(self):
        found = regress.pick_target([
            candidate("wall", 5000.0, {"x": 1.0, "y": 0.0}),
            candidate("crate", 150.0, {"x": 8.0, "y": 0.0}),
            candidate("box", 300.0, {"x": 3.0, "y": 0.0}),
        ], self.anchor)
        self.assertEqual(found["name"], "box")

    def test_corpses_indestructible_and_unhittable_buildings_are_never_chosen(self):
        self.assertIsNone(regress.pick_target([
            candidate("corpse(Clone)", 250.0, {"x": 1.0, "y": 0.0}),
            candidate("steel", 200.0, {"x": 2.0, "y": 0.0}, indestructible=True),
            candidate("glass", 200.0, {"x": 3.0, "y": 0.0}, cant_hit=True),
        ], self.anchor))

    def test_health_outside_the_range_is_skipped(self):
        self.assertIsNone(regress.pick_target([candidate("weak", 20.0, {"x": 1.0, "y": 0.0}), candidate("huge", 900.0, {"x": 2.0, "y": 0.0})], self.anchor))

    def test_candidates_are_read_from_the_nearest_buildings_with_their_flags(self):
        rows = [{"object": {"id": 7, "name": "crate"}, "position": {"x": 2.0, "y": 0.0}}, {"object": {"id": 8, "name": "far"}, "position": {"x": 50.0, "y": 0.0}}]
        values = {"id:7": {"health": 150.0, "indestructible": False, "cantHit": False}, "id:8": {"health": 5000.0, "indestructible": True, "cantHit": False}}

        def get(arguments):
            return values[arguments["target"]][arguments["path"]]

        with FakeLink({"find": lambda arguments: rows, "get": get}) as link:
            found = regress.read_candidates(Game(link.port), self.anchor)
        self.assertEqual([item["name"] for item in found], ["crate", "far"])
        self.assertEqual(found[0]["health"], 150.0)
        self.assertTrue(found[1]["indestructible"])


class LandingTests(unittest.TestCase):
    def test_a_first_swing_that_changed_nothing_makes_the_run_invalid_not_a_pass(self):
        issues = regress.regression_check({"measurements": [entry(1, 0.0, 0.0)]})
        self.assertEqual(len(issues), 1)
        self.assertTrue(issues[0].startswith("INVALID: the first swing changed nothing (host 0.00, client 0.00)"))

    def test_a_first_swing_that_hurt_only_one_side_is_invalid(self):
        self.assertTrue(regress.regression_check({"measurements": [entry(1, 19.33, 0.0)]})[0].startswith("INVALID"))

    def test_no_swing_at_all_is_invalid(self):
        self.assertTrue(regress.regression_check({"measurements": []})[0].startswith("INVALID: no swing fired"))

    def test_equal_damage_every_swing_passes(self):
        self.assertEqual(regress.regression_check({"measurements": [entry(index, 19.33, 19.33) for index in range(1, 6)]}), [])

    def test_a_double_hit_is_flagged_against_the_first_swing(self):
        issues = regress.regression_check({"measurements": [entry(1, 19.33, 19.33), entry(2, 38.66, 38.66), entry(3, 19.33, 19.33)]})
        self.assertEqual(len(issues), 1)
        self.assertIn("swing 2 did 38.66 against 19.33 for the first swing (applied twice?)", issues[0])

    def test_a_missing_hit_after_a_landed_first_swing_is_flagged(self):
        issues = regress.regression_check({"measurements": [entry(1, 19.33, 19.33), entry(2, 0.0, 0.0)]})
        self.assertIn("swing 2 changed nothing on the host (damage missing)", issues)

    def test_a_partial_hit_is_flagged(self):
        issues = regress.regression_check({"measurements": [entry(1, 19.33, 19.33), entry(2, 5.0, 5.0)]})
        self.assertTrue(any("partly missing" in issue for issue in issues))

    def test_host_and_client_disagreeing_is_flagged(self):
        issues = regress.regression_check({"measurements": [entry(1, 19.33, 19.33), entry(2, 19.33, 3.0)]})
        self.assertIn("swing 2: host lost 19.33 but the client sees 3.00", issues)


class PvpTests(unittest.TestCase):
    def test_knockback_missing_after_a_landed_punch_is_flagged_with_the_rule_value(self):
        context = {"pvpRule": True, "measurements": [dict(entry(index, 5.0, 5.0), extra=[1.0, 1.0]) for index in range(1, 4)]}
        issues = regress.pvp_check(context)
        self.assertTrue(any("never knocked back" in issue and "PVP rule reads True" in issue for issue in issues))

    def test_knockback_is_not_asked_of_a_run_that_never_landed(self):
        context = {"pvpRule": False, "measurements": [dict(entry(1, 0.0, 0.0), extra=[1.0, 1.0])]}
        issues = regress.pvp_check(context)
        self.assertEqual(len(issues), 1)
        self.assertTrue(issues[0].startswith("INVALID"))

    def test_some_knockback_and_equal_damage_pass(self):
        context = {"pvpRule": True, "measurements": [dict(entry(1, 5.0, 5.0), extra=[1.0, 1.4]), dict(entry(2, 5.0, 5.0), extra=[1.4, 1.4])]}
        self.assertEqual(regress.pvp_check(context), [])

    def test_the_rule_is_read_and_an_unreadable_rule_is_reported_not_raised(self):
        from tests import hook_scenarios as hooks
        with mock.patch.object(hooks, "pvp_prepare", return_value={"host": None}):
            def broken(arguments):
                raise FakeFailure("no type named 'Together.Multiplayer'")
            with FakeLink({"get": broken}) as link:
                context = regress.pvp_prepare(Game(link.port), None)
        self.assertTrue(str(context["pvpRule"]).startswith("unreadable"))


class MeasureTests(unittest.TestCase):
    def test_a_first_swing_that_does_nothing_stops_the_run_after_one_swing(self):
        from tests import hook_scenarios as hooks
        calls = []

        def fake_measure(host, client, read_host, read_client, target_of, count=5, extra=None):
            calls.append(count)
            return [entry(1, 0.0, 0.0)]

        with mock.patch.object(hooks, "measure_swings", fake_measure):
            result = regress.measure_until_invalid(None, lambda: 0, lambda: 0, lambda: {})
        self.assertEqual(calls, [1])
        self.assertEqual(len(result), 1)

    def test_a_first_swing_that_lands_continues_with_the_rest_numbered_on(self):
        from tests import hook_scenarios as hooks
        calls = []

        def fake_measure(host, client, read_host, read_client, target_of, count=5, extra=None):
            calls.append(count)
            return [entry(1, 19.33, 19.33)] if count == 1 else [entry(index, 19.33, 19.33) for index in range(1, count + 1)]

        with mock.patch.object(hooks, "measure_swings", fake_measure):
            result = regress.measure_until_invalid(None, lambda: 0, lambda: 0, lambda: {})
        self.assertEqual(calls, [1, 4])
        self.assertEqual([item["swing"] for item in result], [1, 2, 3, 4, 5])


class BuildAndGroupTests(unittest.TestCase):
    def test_the_fixed_and_baseline_builds_have_their_own_stage_folders(self):
        self.assertEqual(desync.together_choice("upstream-fixed"), "fullgame-stage")
        self.assertEqual(desync.together_choice("upstream-baseline"), "baseline-stage")
        for build, variable, choice in (("fixed", instances.FULLGAME_STAGE_ENVIRONMENT_VARIABLE, "fullgame-stage"), ("baseline", instances.BASELINE_STAGE_ENVIRONMENT_VARIABLE, "baseline-stage")):
            with tempfile.TemporaryDirectory() as stage:
                os.makedirs(os.path.join(stage, "plugins", "Together"))
                with open(os.path.join(stage, "plugins", "Together", "CasualtiesMP.dll"), "w") as handle:
                    handle.write(build)
                with tempfile.TemporaryDirectory() as copy, mock.patch.dict(os.environ, {variable: stage}):
                    instances.configure_instance(copy, [], together=choice)
                    with open(os.path.join(copy, "BepInEx", "plugins", "Together", "CasualtiesMP.dll")) as handle:
                        self.assertEqual(handle.read(), build)

    def test_the_regression_group_turns_the_pvp_rule_on_for_both_games(self):
        from tests import test_desync
        for arguments in (test_desync.GROUP_HOST_ARGUMENTS, test_desync.GROUP_CLIENT_ARGUMENTS):
            joined = " ".join(arguments["hook-regression"])
            self.assertIn("--mp-setrule PVP 1", joined)

    def test_the_baseline_control_expects_no_success_line_and_the_fixed_build_expects_one(self):
        good = "Body.Attack TRANSPILER SUCCESS :)\n"
        self.assertEqual(desync.launch_log_checks(good, good, expect_no_scatter=False, expect_success=True)["issues"], [])
        control = desync.launch_log_checks("nothing", "nothing", expect_no_scatter=False, expect_success=False)
        self.assertEqual(control["issues"], [])
        wrong = desync.launch_log_checks(good, "nothing", expect_no_scatter=False, expect_success=False)
        self.assertTrue(any("should not have the repaired hook" in issue for issue in wrong["issues"]))

    def test_the_scenarios_are_selectable_with_one_fragment(self):
        from tests import desync_scenarios as scenarios
        self.assertEqual(scenarios.matching_scenario_names(["regress_"]), ["regress_building_hit_by_client", "regress_pvp_melee_by_client"])
        self.assertEqual(sorted(scenarios.counts_by_group(["regress_"])), ["hook-regression"])


if __name__ == "__main__":
    unittest.main()
