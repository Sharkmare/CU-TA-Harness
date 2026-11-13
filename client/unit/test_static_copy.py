import unittest
from unittest import mock

from tests import desync_scenarios as scenarios
from tests import spawned_crates as crates
from tests import static_copy as static


class Clock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        self.now += 0.05
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class PocketTests(unittest.TestCase):
    def blocks(self, solid_floor_rows, open_columns):
        def block_value(game, position):
            x, y = position["x"], position["y"]
            if x not in open_columns:
                return 1
            return 1 if y in solid_floor_rows else 0

        return block_value

    def test_the_first_open_column_far_enough_with_a_floor_is_chosen_and_lifted(self):
        origin = {"x": 10.0, "y": 100.0}
        with mock.patch.object(static.base, "block_value", self.blocks({99.0}, {55.0})):
            pocket = static.find_far_pocket(mock.Mock(), origin, 500)
        self.assertEqual(pocket, {"x": 55.0, "y": 100.0 + static.SPAWN_LIFT})

    def test_columns_beyond_the_world_edge_are_skipped(self):
        origin = {"x": 460.0, "y": 100.0}
        calls = []

        def block_value(game, position):
            calls.append(position["x"])
            return 1

        with mock.patch.object(static.base, "block_value", block_value):
            self.assertIsNone(static.find_far_pocket(mock.Mock(), origin, 500))
        self.assertTrue(all(abs(x) <= 500 - static.WORLD_EDGE_MARGIN for x in calls))

    def test_no_pocket_returns_none(self):
        with mock.patch.object(static.base, "block_value", lambda game, position: 1):
            self.assertIsNone(static.find_far_pocket(mock.Mock(), {"x": 0.0, "y": 0.0}, 500))

    def test_every_candidate_column_is_at_least_forty_tiles_away(self):
        self.assertGreaterEqual(min(abs(column) for column in static.FAR_COLUMNS), static.MIN_FAR_DISTANCE)


class PrepareHarness(unittest.TestCase):
    def setUp(self):
        static.reset_launch_state()
        crates.reset_launch_state()
        self.addCleanup(static.reset_launch_state)
        self.addCleanup(crates.reset_launch_state)
        self.host = mock.Mock()
        self.client = mock.Mock()
        self.host.get.return_value = 500
        self.target = {"handle": "id:5", "clientHandle": "id:-5", "position": {"x": 60.0, "y": 100.5}, "health": 1000.0}
        self.client_state = {"bodyType": "Static", "physicsActive": False}
        self.spawn_error = None
        self.spawn_args = None
        self.client_states = []
        self.farther_than_asked = []
        self.forced_position = None
        self.far_x = 60.0

        def spawn_object(host, client, object_id, min_health, spot=None):
            self.spawn_args = (object_id, min_health, spot)
            if self.spawn_error:
                raise self.spawn_error
            if self.forced_position is not None:
                return dict(self.target, position=self.forced_position)
            return dict(self.target, position={"x": spot["x"], "y": spot["y"]}) if spot else dict(self.target)

        def crate_physics(game, handle):
            if game is self.client:
                state = self.client_states.pop(0) if self.client_states else self.client_state
                return dict(state, handle=handle)
            return {"handle": handle, "bodyType": "Dynamic", "physicsActive": True}

        def find_far_pocket(host, origin, half, farther_than=0.0):
            self.farther_than_asked.append(farther_than)
            self.far_x = max(60.0, origin["x"] + farther_than + 5.0)
            return {"x": self.far_x, "y": 100.5}

        for patch in (mock.patch.object(static.crates, "spawn_object", spawn_object), mock.patch.object(static.crates, "crate_physics", crate_physics),
                      mock.patch.object(static.crates, "hold_client_at_anchor", lambda client: {"x": 10.0, "y": 100.0}),
                      mock.patch.object(static, "find_far_pocket", find_far_pocket),
                      mock.patch.object(static.base, "empty_the_hand", lambda client: None)):
            patch.start()
            self.addCleanup(patch.stop)


class StaticOfferTests(PrepareHarness):
    def rows(self):
        return [{"object": {"id": 11, "name": "SyncInfo(building, id: 11, res: wallpanel)"}, "position": {"x": 14.0, "y": 100.0}},
                {"object": {"id": 12, "name": "SyncInfo(building, id: 12, res: medcrate)"}, "position": {"x": 15.0, "y": 100.0}}]

    def client_rows(self):
        return [{"object": {"id": -11, "name": "x"}, "position": {"x": 14.0, "y": 100.0}}, {"object": {"id": -12, "name": "x"}, "position": {"x": 15.0, "y": 100.0}}]

    def described(self, host, row):
        return {"handle": "id:%d" % row["object"]["id"], "id": row["object"]["id"], "name": row["object"]["name"], "position": row["position"], "health": 500.0, "cantHit": False,
                "indestructible": False, "animal": False, "startHealth": 500.0}

    def patches(self, client_active):
        self.host.call.side_effect = lambda command, **arguments: self.rows()
        self.client.call.side_effect = lambda command, **arguments: self.client_rows()
        states = {"id:-11": client_active, "id:-12": True}
        return [mock.patch.object(static.world, "describe_candidate", self.described),
                mock.patch.object(static.crates, "crate_physics", lambda game, handle: {"handle": handle, "bodyType": "Static" if game is self.client and states.get(handle) is False else "Dynamic",
                                                                                   "physicsActive": states.get(handle, True) if game is self.client else True})]

    def run_offer(self, client_active):
        for patch in self.patches(client_active):
            patch.start()
            self.addCleanup(patch.stop)
        return static.world_offer(self.host, self.client, {"x": 10.0, "y": 100.0})

    def test_the_offer_lists_the_nearest_buildings_with_both_copies_states(self):
        offers = self.run_offer(False)
        self.assertEqual([offer["kind"] for offer in offers], ["wallpanel", "medcrate"])
        self.assertEqual(offers[0]["clientHandle"], "id:-11")
        self.assertEqual((offers[0]["host"]["physicsActive"], offers[0]["client"]["physicsActive"]), (True, False))
        self.assertEqual(offers[0]["distance"], 4.0)

    def test_only_a_building_whose_client_copy_is_static_and_that_can_be_hit_is_usable(self):
        offers = self.run_offer(False)
        self.assertTrue(static.static_offer_usable(offers[0]))
        self.assertFalse(static.static_offer_usable(offers[1]))
        offers = self.run_offer(True)
        self.assertFalse(static.static_offer_usable(offers[0]))
        indestructible = dict(offers[0], client={"physicsActive": False}, described=dict(offers[0]["described"], indestructible=True))
        self.assertFalse(static.static_offer_usable(indestructible))

    def test_without_a_far_pocket_a_usable_static_building_near_the_seat_is_adopted_and_its_state_recorded(self):
        for patch in self.patches(False):
            patch.start()
            self.addCleanup(patch.stop)
        with mock.patch.object(static, "find_far_pocket", lambda host, origin, half, farther_than=0.0: None):
            context = static.prepare(self.host, self.client)
        self.assertTrue(context["target"]["adopted"])
        self.assertEqual(context["hostHandle"], "id:11")
        self.assertEqual(context["target"]["clientFarState"]["physicsActive"], False)
        self.assertEqual(static.STATE["adopted"], 1)
        self.assertEqual(static.STATE["static_at_far"], 0)

    def test_an_adopted_building_is_never_destroyed_by_the_cleanup(self):
        context = {"host": self.host, "hostHandle": "id:11", "target": {"adopted": True}, "measurements": [], "anchor": None}
        with mock.patch.object(static, "wait_for_limbs", lambda *a: None), mock.patch.object(static, "approach", lambda *a: None), mock.patch.object(static.world, "act", lambda *a, **k: None), mock.patch.object(static, "return_to_anchor", lambda *a: None):
            static.act(self.client, context)
        self.host.set.assert_not_called()

    def test_with_no_usable_building_the_setup_failure_lists_what_the_world_offers(self):
        for patch in self.patches(True):
            patch.start()
            self.addCleanup(patch.stop)
        with mock.patch.object(static, "find_far_pocket", lambda host, origin, half, farther_than=0.0: None), self.assertRaises(crates.SetupFailure) as caught:
            static.prepare(self.host, self.client)
        self.assertEqual(caught.exception.category, "no-far-pocket")
        self.assertIn("wallpanel", str(caught.exception))


class LimbGateTests(unittest.TestCase):
    def run_gate(self, limb_distances):
        readings = iter(limb_distances)
        clock = [0.0]
        context = {"hostHandle": "id:1", "position": {"x": 0.0, "y": 0.0}, "target": {}}
        with mock.patch.object(static.time, "time", lambda: clock[0]), mock.patch.object(static.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)),                 mock.patch.object(static.world, "host_position", lambda host, handle: {"x": 0.0, "y": 0.0}),                 mock.patch.object(static.crates, "optional_read", lambda game, path: None if (value := next(readings, 99.0)) is None else {"x": value, "y": 0.0}):
            return static.wait_for_limbs(mock.Mock(), mock.Mock(), context), context["target"]["limbSettle"]

    def test_the_swings_wait_until_limb_one_is_near_the_crate_on_two_readings_in_a_row(self):
        ok, record = self.run_gate([9.8, 8.5, 3.4, 3.5])
        self.assertTrue(ok)
        self.assertEqual([row["limb1ToCrate"] for row in record["rows"]], [9.8, 8.5, 3.4, 3.5])

    def test_a_single_near_reading_between_far_ones_does_not_open_the_gate(self):
        ok, record = self.run_gate([9.8, 3.4, 9.0, 3.4, 9.0])
        self.assertTrue(record["ok"] is ok)
        self.assertFalse(ok)

    def test_a_limb_that_stays_away_is_recorded_as_not_settled_and_the_swings_still_run(self):
        ok, record = self.run_gate([9.0] * 100)
        self.assertFalse(ok)
        self.assertFalse(record["ok"])
        self.assertGreater(len(record["rows"]), 3)

    def test_an_unreadable_limb_is_never_taken_for_near(self):
        ok, record = self.run_gate([None] * 100)
        self.assertFalse(ok)
        self.assertEqual({row["limb1ToCrate"] for row in record["rows"]}, {None})

    def test_the_gate_runs_between_the_approach_and_the_swings(self):
        order = []
        context = {"host": mock.Mock(), "hostHandle": "id:1", "target": {}, "measurements": [], "anchor": None}
        with mock.patch.object(static, "approach", lambda *a: order.append("approach")), mock.patch.object(static, "wait_for_limbs", lambda *a: order.append("limbs")),                 mock.patch.object(static.world, "act", lambda *a, **k: order.append("swings")), mock.patch.object(static, "return_to_anchor", lambda *a: None),                 mock.patch.object(static, "crates_destroy", lambda *a: None):
            static.act(mock.Mock(), context)
        self.assertEqual(order, ["approach", "limbs", "swings"])


class PrepareTests(PrepareHarness):
    def test_a_far_crate_whose_client_copy_is_static_is_set_up_and_counted(self):
        context = static.prepare(self.host, self.client)
        self.assertEqual(self.spawn_args, ("medcrate", crates.MIN_HEALTH, {"x": 60.0, "y": 100.5}))
        self.assertEqual(context["target"]["clientFarState"]["physicsActive"], False)
        self.assertEqual(context["target"]["hostFarState"]["bodyType"], "Dynamic")
        self.assertEqual(context["target"]["farDistance"], 50.0)
        self.assertEqual(static.STATE["static_at_far"], 1)

    def test_a_client_copy_that_is_dynamic_at_the_far_spot_is_a_setup_failure_with_the_values_and_the_crate_is_destroyed(self):
        self.client_state = {"bodyType": "Dynamic", "physicsActive": True}
        with self.assertRaises(crates.SetupFailure) as caught:
            static.prepare(self.host, self.client)
        self.assertEqual(caught.exception.category, "client-copy-not-static-at-far")
        self.assertIn("Dynamic", str(caught.exception))
        self.assertEqual(self.host.set.call_count, static.FAR_ATTEMPTS)
        self.assertEqual(static.STATE["static_at_far"], 0)
        self.assertEqual(len(self.farther_than_asked), static.FAR_ATTEMPTS)
        self.assertEqual(self.farther_than_asked, sorted(self.farther_than_asked))
        self.assertIn("copy state per distance", str(caught.exception))

    def test_a_copy_that_is_dynamic_at_the_first_distance_but_static_farther_out_is_counted_with_every_state_recorded(self):
        self.client_states = [{"bodyType": "Dynamic", "physicsActive": True}, {"bodyType": "Static", "physicsActive": False}]
        context = static.prepare(self.host, self.client)
        attempts = context["target"]["farAttempts"]
        self.assertEqual([item["clientPhysicsActive"] for item in attempts], [True, False])
        self.assertGreater(attempts[1]["distance"], attempts[0]["distance"])
        self.assertEqual(static.STATE["static_at_far"], 1)
        self.assertEqual(context["target"]["clientFarState"]["physicsActive"], False)
        self.host.set.assert_called_once_with("id:5", "health", 0)

    def test_a_dynamic_copy_is_never_counted_as_a_static_copy_result(self):
        self.client_state = {"bodyType": "Dynamic", "physicsActive": True}
        with self.assertRaises(crates.SetupFailure):
            static.prepare(self.host, self.client)
        self.assertEqual((static.STATE["static_at_far"], static.STATE["valid"]), (0, 0))

    def test_an_unreadable_client_physics_state_is_not_taken_for_static(self):
        self.client_state = {"bodyType": None, "physicsActive": None}
        with self.assertRaises(crates.SetupFailure):
            static.prepare(self.host, self.client)

    def test_a_crate_that_ended_up_close_is_refused(self):
        self.forced_position = {"x": 20.0, "y": 100.5}
        with self.assertRaises(crates.SetupFailure) as caught:
            static.prepare(self.host, self.client)
        self.assertEqual(caught.exception.category, "crate-not-far")

    def test_no_pocket_is_a_setup_failure(self):
        self.host.call.side_effect = lambda command, **arguments: []
        self.client.call.side_effect = lambda command, **arguments: []
        with mock.patch.object(static, "find_far_pocket", lambda host, origin, half, farther_than=0.0: None), self.assertRaises(crates.SetupFailure) as caught:
            static.prepare(self.host, self.client)
        self.assertEqual(caught.exception.category, "no-far-pocket")

    def test_a_spawn_failure_keeps_its_category_with_a_far_prefix(self):
        self.spawn_error = crates.SetupFailure("client-does-not-list-crate", "the client does not list it")
        with self.assertRaises(crates.SetupFailure):
            static.prepare(self.host, self.client)
        self.assertEqual(dict(crates.STATE["reasons"]), {"far-client-does-not-list-crate": 1})

    def test_three_failed_setups_with_nothing_measured_stop_the_launch(self):
        self.client_state = {"bodyType": "Dynamic", "physicsActive": True}
        for _ in range(static.STOP_AFTER_SETUP_FAILURES):
            with self.assertRaises(crates.SetupFailure):
                static.prepare(self.host, self.client)
        with self.assertRaises(unittest.SkipTest) as caught:
            static.prepare(self.host, self.client)
        self.assertIn("client-copy-not-static-at-far", str(caught.exception))

    def test_six_measured_attempts_end_the_launch(self):
        static.STATE["valid"] = static.ATTEMPTS_WANTED
        with self.assertRaises(unittest.SkipTest):
            static.prepare(self.host, self.client)


class ApproachTests(unittest.TestCase):
    def setUp(self):
        static.reset_launch_state()
        self.addCleanup(static.reset_launch_state)
        self.clock = Clock()
        self.client = mock.Mock()
        self.player = {"x": 10.0, "y": 100.0}
        self.states = iter([{"bodyType": "Static", "physicsActive": False}] * 3 + [{"bodyType": "Dynamic", "physicsActive": True}] * 50)
        self.client.set.side_effect = self.teleport
        self.distance_after = [9.0, 4.0, 2.9]
        self.calls = 0
        for patch in (mock.patch.object(static.time, "sleep", self.clock.sleep), mock.patch.object(static.time, "time", self.clock.time),
                      mock.patch.object(static.world, "host_position", lambda host, handle: {"x": 60.0, "y": 100.5}),
                      mock.patch.object(static.base, "player_position", self.player_position),
                      mock.patch.object(static.crates, "crate_physics", lambda game, handle: next(self.states))):
            patch.start()
            self.addCleanup(patch.stop)

    def teleport(self, target, path, value):
        self.teleported_to = value

    def player_position(self, game):
        distance = self.distance_after[min(self.calls, len(self.distance_after) - 1)]
        self.calls += 1
        return {"x": 60.0 - distance, "y": 100.5}

    def test_the_client_is_moved_once_to_the_band_middle_and_the_state_is_polled_until_it_is_in_the_band(self):
        context = {"hostHandle": "id:5", "clientHandle": "id:-5", "position": {"x": 60.0, "y": 100.5}, "target": {}}
        timeline = static.approach(mock.Mock(), self.client, context)
        self.client.set.assert_called_once()
        self.assertEqual(self.teleported_to["x"], 60.0 - crates.BAND_TARGET)
        self.assertEqual([entry["distance"] for entry in timeline], [9.0, 4.0, 2.9])
        self.assertEqual([entry["clientPhysicsActive"] for entry in timeline], [False, False, False])
        self.assertIs(context["target"]["approach"], timeline)

    def test_the_timeline_shows_the_copy_turning_dynamic_when_it_does(self):
        self.distance_after = [9.0, 9.0, 9.0, 9.0, 2.9]
        context = {"hostHandle": "id:5", "clientHandle": "id:-5", "position": {"x": 60.0, "y": 100.5}, "target": {}}
        timeline = static.approach(mock.Mock(), self.client, context)
        self.assertEqual([entry["clientPhysicsActive"] for entry in timeline], [False, False, False, True, True])

    def test_a_client_that_never_gets_in_the_band_stops_at_the_timeout(self):
        self.distance_after = [9.0]
        context = {"hostHandle": "id:5", "clientHandle": "id:-5", "position": {"x": 60.0, "y": 100.5}, "target": {}}
        timeline = static.approach(mock.Mock(), self.client, context)
        self.assertLessEqual(len(timeline), int(static.APPROACH_TIMEOUT_SECONDS / static.APPROACH_POLL_SECONDS) + 2)
        self.assertTrue(all(entry["distance"] == 9.0 for entry in timeline))


class ActTests(unittest.TestCase):
    def setUp(self):
        static.reset_launch_state()
        self.addCleanup(static.reset_launch_state)

    def run_act(self, client_state, raises=False):
        host, client = mock.Mock(), mock.Mock()
        context = {"host": host, "hostHandle": "id:5", "clientHandle": "id:-5", "position": {"x": 60.0, "y": 100.5}, "target": {}, "measurements": [], "anchor": {"x": 10.0, "y": 100.0}}

        def world_act(game, ctx, before_swing=None):
            if raises:
                raise RuntimeError("link lost")
            ctx["measurements"] = [{"swing": 1, "hostDelta": 19.3, "clientDelta": 19.3, "physics": {"client": client_state}}]

        with mock.patch.object(static, "wait_for_limbs", lambda *a: None), mock.patch.object(static, "approach", lambda h, c, ctx: []), mock.patch.object(static.world, "act", world_act), mock.patch.object(static.time, "sleep", lambda seconds: None):
            if raises:
                with self.assertRaises(RuntimeError):
                    static.act(client, context)
            else:
                static.act(client, context)
        return host, client, context

    def test_a_first_swing_on_a_static_client_copy_is_counted_and_marked(self):
        host, client, context = self.run_act({"physicsActive": False, "bodyType": "Static"})
        self.assertTrue(context["target"]["clientStaticAtFirstSwing"])
        self.assertEqual(static.STATE["static_at_swing"], 1)

    def test_a_first_swing_on_a_dynamic_client_copy_is_not_counted(self):
        host, client, context = self.run_act({"physicsActive": True, "bodyType": "Dynamic"})
        self.assertFalse(context["target"]["clientStaticAtFirstSwing"])
        self.assertEqual(static.STATE["static_at_swing"], 0)

    def test_the_crate_is_destroyed_and_the_client_goes_back_to_the_anchor_even_when_the_swings_fail(self):
        host, client, context = self.run_act({}, raises=True)
        host.set.assert_called_once_with("id:5", "health", 0)
        client.set.assert_called_once_with("player", static.base.BODY_PATH, {"x": 10.0, "y": 100.0, "z": 0.0})

    def test_the_swing_hook_is_the_crate_band_hook(self):
        seen = {}
        with mock.patch.object(static, "wait_for_limbs", lambda *a: None), mock.patch.object(static, "approach", lambda h, c, ctx: []), mock.patch.object(static.world, "act", lambda client, ctx, before_swing=None: seen.update(hook=before_swing)), \
                mock.patch.object(static.time, "sleep", lambda seconds: None):
            static.act(mock.Mock(), {"host": mock.Mock(), "hostHandle": "id:5", "clientHandle": "id:-5", "position": {}, "target": {}, "measurements": [], "anchor": None})
        self.assertIs(seen["hook"], static.crates.before_swing)


class CheckTests(unittest.TestCase):
    def setUp(self):
        static.reset_launch_state()
        crates.reset_launch_state()
        self.addCleanup(static.reset_launch_state)
        self.addCleanup(crates.reset_launch_state)

    def entry(self, index, host, client, physics=False):
        return {"swing": index, "hostDelta": host, "clientDelta": client, "physics": {"client": {"physicsActive": physics}}}

    def context(self, entries, gate_ok=True):
        return {"measurements": entries, "target": {"limbSettle": {"ok": gate_ok, "rows": [{"limb1ToCrate": 9.0}, {"limb1ToCrate": 3.4}, {"limb1ToCrate": 3.5}]}}}

    def test_swings_that_damage_both_sides_pass_and_the_run_is_measured(self):
        self.assertEqual(static.check(self.context([self.entry(index, 19.3, 19.3) for index in range(1, 6)])), [])
        self.assertEqual(static.STATE["valid"], 1)

    def test_swings_fired_before_the_limb_gate_passed_are_not_counted_even_when_they_landed(self):
        issues = static.check(self.context([self.entry(index, 19.3, 19.3) for index in range(1, 6)], gate_ok=False))
        self.assertTrue(issues[0].startswith("NOT COUNTED"), issues)
        self.assertIn("5 of 5 swings landed anyway", issues[0])
        self.assertEqual((static.STATE["valid"], static.STATE["not_counted"]), (0, 1))
        self.assertEqual(dict(crates.STATE["reasons"]), {"limb-gate-not-passed": 1})

    def test_a_run_without_any_limb_gate_record_is_not_counted(self):
        issues = static.check({"measurements": [self.entry(1, 19.3, 19.3)]})
        self.assertTrue(issues[0].startswith("NOT COUNTED"))
        self.assertEqual(static.STATE["valid"], 0)

    def test_a_missed_swing_names_the_limb_distance(self):
        entry = dict(self.entry(1, 0.0, 0.0), geometry={"limb1Distance": 9.4})
        issues = static.check(self.context([entry]))
        self.assertIn("limb 1 9.4 from the crate", issues[0])

    def test_a_swing_with_no_damage_on_a_static_copy_is_reported_with_the_copy_state_and_still_counts_as_measured(self):
        issues = static.check(self.context([self.entry(1, 0.0, 0.0, physics=False), self.entry(2, 19.3, 19.3, physics=True)]))
        self.assertEqual(len(issues), 1)
        self.assertIn("swing 1", issues[0])
        self.assertIn("physicsActive False", issues[0])
        self.assertEqual(static.STATE["valid"], 1)

    def test_a_band_failure_is_invalid_and_not_measured(self):
        issues = static.check({"bandFailure": {"swing": 1, "distances": [9.0]}, "measurements": []})
        self.assertTrue(issues[0].startswith("INVALID: the client could not be brought into the 2.5 to 3.2 band before swing 1"))
        self.assertEqual((static.STATE["valid"], static.STATE["setup_failed"]), (0, 1))


class WiringTests(unittest.TestCase):
    def test_the_scenario_is_in_the_evidence_group_and_between_the_crate_and_the_mining_scenarios_in_test_order(self):
        self.assertIn("staticcrate_hit_by_client", scenarios.matching_scenario_names(["staticcrate"]))
        names = sorted(["test_spawned_crate_hit_by_client_r1", "test_staticcrate_hit_by_client_r1", "test_v2check_dig_cracks_d100-j0_r1", "test_pvp_banded_by_client_r1"])
        self.assertEqual(names, ["test_pvp_banded_by_client_r1", "test_spawned_crate_hit_by_client_r1", "test_staticcrate_hit_by_client_r1", "test_v2check_dig_cracks_d100-j0_r1"])

    def test_the_fragment_for_the_crate_scenario_does_not_select_the_static_one(self):
        self.assertEqual(scenarios.matching_scenario_names(["spawned_crate"]), ["spawned_crate_hit_by_client"])

    def test_the_preflight_passes_for_eight_attempts_and_refuses_too_few(self):
        self.assertEqual(static.preflight(["staticcrate"], 8), [])
        self.assertTrue(static.preflight(["staticcrate"], 4))
        self.assertEqual(static.preflight(["spawned_crate"], 1), [])


if __name__ == "__main__":
    unittest.main()
