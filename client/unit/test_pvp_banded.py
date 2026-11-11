import unittest
from unittest import mock

from casualtieslink import desync, launchplan
from tests import desync_scenarios as scenarios
from tests import hook_scenarios, pvp_banded, regression_scenarios, spawned_crates as crates


class Clock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        self.now += 0.25
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ActHarness(unittest.TestCase):
    def setUp(self):
        crates.reset_launch_state()
        self.addCleanup(crates.reset_launch_state)
        self.host = mock.Mock()
        self.client = mock.Mock()
        self.victim = {"x": 20.0, "y": 5.0}
        self.player = {"x": 16.8, "y": 5.0}
        self.limbs = 100.0
        self.fired = []
        self.landing = None
        self.knockback = 1.0
        self.punch_damage = 18.0
        self.reach = 4.5
        self.clock = Clock()
        self.log_lines = {"host": [], "client": []}

    def fire(self, game, aim):
        self.fired.append(base_distance(self.player, self.victim))
        if base_distance(self.player, self.victim) <= self.reach:
            self.limbs -= self.punch_damage
            self.victim = {"x": self.victim["x"] + self.knockback, "y": 5.0}
        return True

    def teleport(self, target, path, value):
        if self.landing is not None:
            self.player = {"x": value["x"], "y": value["y"]}

    def host_get(self, handle, path, depth=0):
        if path == "transform.position":
            return dict(self.victim)
        if path == "conscious":
            return True
        raise KeyError(path)

    def run_act(self):
        self.client.set.side_effect = self.teleport
        self.client.get.side_effect = lambda handle, path, depth=0: dict(self.victim)
        self.host.get.side_effect = self.host_get
        context = {"host": self.host, "hostVictim": "id:9", "clientVictim": "id:-9", "measurements": []}
        patches = [mock.patch.object(pvp_banded.time, "sleep", self.clock.sleep), mock.patch.object(crates.time, "sleep", self.clock.sleep),
                   mock.patch.object(pvp_banded.hooks, "fire_one_swing", self.fire), mock.patch.object(pvp_banded.hooks, "limb_total", lambda game, handle: self.limbs),
                   mock.patch.object(pvp_banded.base, "player_position", lambda game: dict(self.player)), mock.patch.object(crates.base, "player_position", lambda game: dict(self.player)),
                   mock.patch.object(crates.world, "host_position", lambda game, handle: dict(self.victim)),
                   mock.patch.object(pvp_banded.evidence, "read_log", lambda which: "")]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        pvp_banded.act(self.client, context)
        return context


def base_distance(first, second):
    return ((first["x"] - second["x"]) ** 2 + (first["y"] - second["y"]) ** 2) ** 0.5


class ActTests(ActHarness):
    def test_the_client_is_re_approached_before_every_punch_so_a_knocked_back_victim_is_still_hit(self):
        self.landing = True
        context = self.run_act()
        self.assertEqual(len(context["measurements"]), pvp_banded.PUNCHES_PER_RUN)
        self.assertTrue(all(entry["hostDelta"] > pvp_banded.PUNCH_LANDED_MINIMUM for entry in context["measurements"]))
        for distance in self.fired:
            self.assertLessEqual(distance, 4.5)
        for entry in context["measurements"]:
            self.assertGreaterEqual(entry["geometry"]["distance"], pvp_banded.BAND_LOW)
            self.assertLessEqual(entry["geometry"]["distance"], pvp_banded.BAND_HIGH)

    def test_the_teleport_goes_to_the_clients_own_side_of_the_victim(self):
        self.landing = True
        self.player = {"x": 24.0, "y": 5.0}
        self.knockback = -1.0
        self.run_act()
        for call in self.client.set.call_args_list:
            self.assertGreater(call.args[2]["x"], 20.0 - 6)
        self.assertTrue(any(call.args[2]["x"] > self.victim["x"] for call in self.client.set.call_args_list))

    def test_every_punch_records_distance_positions_movement_drift_and_hook_lines(self):
        self.landing = True
        context = self.run_act()
        entry = context["measurements"][1]
        geometry = entry["geometry"]
        self.assertEqual(set(geometry), {"clientPosition", "victimHostPosition", "victimClientPosition", "distance", "distanceToClientCopy", "movedSincePreviousPunch",
                                         "idleDriftPerSecond", "victimConscious", "side"})
        self.assertEqual(context["measurements"][0]["geometry"]["movedSincePreviousPunch"], None)
        self.assertAlmostEqual(geometry["movedSincePreviousPunch"], 0.0, places=2)
        self.assertEqual(geometry["victimConscious"], True)
        self.assertEqual(geometry["idleDriftPerSecond"], 0.0)
        for key in ("hostHookCalls", "clientHookCalls", "band", "extra", "host", "client", "hostExceptions", "clientExceptions"):
            self.assertIn(key, entry)

    def test_the_victim_moving_between_punches_is_recorded(self):
        self.landing = True
        self.knockback = 1.0
        context = self.run_act()
        self.assertGreater(context["measurements"][0]["extra"][1] - context["measurements"][0]["extra"][0], 0.5)

    def test_a_client_that_cannot_be_brought_into_the_band_does_not_fire_and_marks_the_run(self):
        self.landing = None
        self.player = {"x": 14.0, "y": 5.0}
        context = self.run_act()
        self.assertEqual(self.fired, [])
        self.assertEqual(context["bandFailure"]["swing"], 1)
        self.assertEqual(context["measurements"], [])

    def test_a_band_failure_after_two_punches_keeps_those_punches_and_marks_the_run(self):
        self.landing = True
        original = self.fire
        calls = []

        def fire_then_break(game, aim):
            calls.append(1)
            result = original(game, aim)
            if len(calls) == 2:
                self.landing = None
                self.player = {"x": self.victim["x"] - 9.0, "y": 5.0}
            return result

        self.fire = fire_then_break
        context = self.run_act()
        self.assertEqual(len(context["measurements"]), 2)
        self.assertEqual(context["bandFailure"]["swing"], 3)

    def test_a_regen_of_half_a_point_per_second_is_not_read_as_a_landed_punch(self):
        self.landing = True
        self.punch_damage = -0.5
        context = self.run_act()
        self.assertTrue(all(entry["hostDelta"] <= pvp_banded.PUNCH_LANDED_MINIMUM for entry in context["measurements"]))
        issues = pvp_banded.check(context)
        self.assertTrue(issues)


class CheckTests(unittest.TestCase):
    def setUp(self):
        crates.reset_launch_state()
        self.addCleanup(crates.reset_launch_state)

    def entry(self, index, damage, moved=1.0):
        return {"swing": index, "hostDelta": damage, "clientDelta": damage, "extra": [0.0, moved]}

    def test_five_landed_punches_with_knockback_pass(self):
        self.assertEqual(pvp_banded.check({"measurements": [self.entry(index, 18.0) for index in range(1, 6)], "pvpRule": True}), [])

    def test_a_band_failure_is_an_invalid_run_with_its_own_category(self):
        issues = pvp_banded.check({"bandFailure": {"swing": 2, "distances": [3.9, 3.8]}, "measurements": [self.entry(1, 18.0)]})
        self.assertTrue(issues[0].startswith("INVALID: the client could not be brought into the 2.5 to 3.2 band before punch 2"))
        self.assertEqual(dict(crates.STATE["reasons"]), {"pvp-distance-band-unreachable": 1})

    def test_a_punch_with_no_damage_inside_the_band_is_a_failure_not_an_invalid_run(self):
        entries = [self.entry(1, 18.0), self.entry(2, 0.0), self.entry(3, 18.0)]
        issues = pvp_banded.check({"measurements": entries, "pvpRule": True})
        self.assertTrue(any("swing 2 changed nothing" in issue for issue in issues))

    def test_a_double_damage_punch_is_flagged(self):
        issues = pvp_banded.check({"measurements": [self.entry(1, 18.0), self.entry(2, 40.0)], "pvpRule": True})
        self.assertTrue(any("applied twice" in issue for issue in issues))


class PlanTests(unittest.TestCase):
    def test_the_scenario_runs_three_times_in_the_evidence_group_and_sorts_before_the_other_checks(self):
        scenario = next(item for item in scenarios.SCENARIOS if item.name == "pvp_banded_by_client")
        self.assertEqual((scenario.group, scenario.max_repeat), ("hook-evidence", 3))
        self.assertEqual(len(desync.expand_runs([scenario], [launchplan.DIRECT], 8)), 3)
        self.assertEqual(3 * hook_scenarios.REGRESSION_SWINGS, 15)
        names = sorted(["test_00_launch_log_checks", "test_spawned_crate_hit_by_client_r1", "test_v2check_dig_cracks_d100-j0_r1", "test_pvp_banded_by_client_r1"])
        self.assertEqual(names[:2], ["test_00_launch_log_checks", "test_pvp_banded_by_client_r1"])

    def test_the_selection_fragments_pick_exactly_the_three_checks(self):
        self.assertEqual(sorted(scenarios.matching_scenario_names(["pvp_banded", "spawned_crate", "v2check"])),
                         ["pvp_banded_by_client", "spawned_crate_hit_by_client", "v2check_dig_cracks"])

    def test_the_pvp_band_is_the_crate_band_and_inside_the_attack_reach(self):
        self.assertEqual((pvp_banded.BAND_LOW, pvp_banded.BAND_HIGH), (crates.BAND_LOW, crates.BAND_HIGH))
        self.assertLess(pvp_banded.BAND_HIGH + 1.0, crates.ATTACK_DISTANCE)

    def test_the_old_unbanded_pvp_copy_is_gone_and_the_original_is_untouched(self):
        self.assertNotIn("v2check_pvp_melee_by_client", scenarios.matching_scenario_names(["v2check"]))
        self.assertIn("regress_pvp_melee_by_client", [item.name for item in regression_scenarios.REGRESSION_SCENARIOS])


class EnsureBandSideTests(unittest.TestCase):
    def test_the_side_argument_puts_the_teleport_on_the_requested_side(self):
        client = mock.Mock()
        position = {"x": 10.0, "y": 5.0}
        with mock.patch.object(crates.time, "sleep", lambda seconds: None), mock.patch.object(crates.world, "host_position", lambda host, handle: dict(position)), \
                mock.patch.object(crates.base, "player_position", lambda game: {"x": 20.0, "y": 5.0}):
            crates.ensure_band(None, client, "id:1", position, side=1)
        self.assertEqual(client.set.call_args_list[0].args[2], {"x": 12.0, "y": 5.0, "z": 0.0})

    def test_the_default_side_is_unchanged_for_crates(self):
        client = mock.Mock()
        position = {"x": 10.0, "y": 5.0}
        with mock.patch.object(crates.time, "sleep", lambda seconds: None), mock.patch.object(crates.world, "host_position", lambda host, handle: dict(position)), \
                mock.patch.object(crates.base, "player_position", lambda game: {"x": 0.0, "y": 5.0}):
            crates.ensure_band(None, client, "id:1", position)
        self.assertEqual(client.set.call_args_list[0].args[2], {"x": 8.0, "y": 5.0, "z": 0.0})


if __name__ == "__main__":
    unittest.main()
