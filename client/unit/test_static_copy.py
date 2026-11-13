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
        self.host.call.return_value = []
        self.client.call.return_value = []
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
        return [{"object": {"id": 11, "name": "SyncInfo(building, id: 11, res: wallpanel)"}, "position": {"x": 12.8, "y": 100.0}},
                {"object": {"id": 12, "name": "SyncInfo(building, id: 12, res: medcrate)"}, "position": {"x": 15.0, "y": 100.0}}]

    def client_rows(self):
        return [{"object": {"id": -11, "name": "x"}, "position": {"x": 12.8, "y": 100.0}}, {"object": {"id": -12, "name": "x"}, "position": {"x": 15.0, "y": 100.0}}]

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
        self.assertEqual(offers[0]["distance"], 2.8)

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

    def start_patches(self, client_active):
        for patch in self.patches(client_active):
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_building_the_band_cannot_reach_is_never_adopted(self):
        offers = self.run_offer(False)
        far = dict(offers[0], distance=4.4)
        self.assertFalse(static.static_offer_usable(far))
        near = dict(offers[0], distance=3.6)
        self.assertTrue(static.static_offer_usable(near))

    def test_a_standing_building_with_thousands_of_health_is_usable_as_a_static_target(self):
        offers = self.run_offer(False)
        big = dict(offers[0], described=dict(offers[0]["described"], health=5000.0))
        self.assertTrue(static.static_offer_usable(big))
        tiny = dict(offers[0], described=dict(offers[0]["described"], health=10.0))
        self.assertFalse(static.static_offer_usable(tiny))

    def test_a_far_copy_that_is_never_static_falls_back_to_a_static_building_near_the_seat(self):
        self.start_patches(False)
        self.client_state = {"bodyType": "Dynamic", "physicsActive": True}
        self.client_states = []
        with mock.patch.object(static.crates, "crate_physics", lambda game, handle: {"handle": handle, "bodyType": "Dynamic", "physicsActive": True} if handle != "id:-11" else {"handle": handle, "bodyType": "Static", "physicsActive": False}):
            context = static.prepare(self.host, self.client)
        self.assertTrue(context["target"]["adopted"])
        self.assertEqual(context["hostHandle"], "id:11")
        self.assertEqual(static.STATE["adopted"], 1)

    def test_a_far_crate_that_ended_up_close_falls_back_to_a_static_building_near_the_seat(self):
        self.start_patches(False)
        self.forced_position = {"x": 20.0, "y": 100.5}
        context = static.prepare(self.host, self.client)
        self.assertTrue(context["target"]["adopted"])
        self.host.set.assert_called_once_with("id:5", "health", 0)

    def test_an_adopted_building_is_never_destroyed_by_the_cleanup(self):
        context = {"host": self.host, "hostHandle": "id:11", "target": {"adopted": True}, "measurements": [], "anchor": None}
        with mock.patch.object(static, "seat_and_gate", lambda *a: True), mock.patch.object(static, "approach", lambda *a: None), mock.patch.object(static.world, "act", lambda *a, **k: None), mock.patch.object(static, "return_to_anchor", lambda *a: None):
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


class SeatAndGateTests(unittest.TestCase):
    def setUp(self):
        self.host = mock.Mock()
        self.client = mock.Mock()
        self.context = {"host": self.host, "hostHandle": "id:5", "clientHandle": "id:-5", "position": {"x": 60.0, "y": 100.5}, "target": {}}
        self.seat = {"x": 57.1, "y": 100.5}

    def patches(self, seat_ok=True, settle_ok=True):
        gate = mock.Mock()
        gate.settle.return_value = {"ok": settle_ok, "rest": {}, "rows": []}
        self.gate = gate
        return [mock.patch.object(static.base, "player_position", lambda game: self.seat), mock.patch.object(static.positioncontrol, "discover_diagnostic_paths", lambda game: ["rb.position"]),
                mock.patch.object(static.positioncontrol, "seat_swinging_body", lambda game, target, tolerance=0.05, paths=(), sleep=None: {"ok": seat_ok, "issues": [] if seat_ok else ["rb.position is 0.300 from the target"], "linkReadDisagrees": False}),
                mock.patch.object(static.crates, "make_gate", lambda *a: gate)]

    def run_seat(self, **options):
        for patch in self.patches(**options):
            patch.start()
            self.addCleanup(patch.stop)
        return static.seat_and_gate(self.client, self.context)

    def test_after_the_move_the_client_is_seated_verified_and_the_gate_is_installed_after_the_limbs_settled(self):
        self.assertTrue(self.run_seat())
        self.assertIs(self.context["gate"], self.gate)
        self.assertEqual(self.context["settledSeat"], self.seat)
        self.assertTrue(self.context["target"]["limbSettle"]["ok"])
        self.gate.settle.assert_called_once()

    def test_a_seat_that_does_not_verify_gives_no_gate_and_an_invalid_position_failure(self):
        self.assertFalse(self.run_seat(seat_ok=False))
        self.assertNotIn("gate", self.context)
        self.assertIn("the client seat did not verify after the move", self.context["positionFailure"]["issues"][0])
        self.gate.settle.assert_not_called()

    def test_limbs_that_do_not_settle_give_no_gate_and_the_run_is_invalid_before_any_swing(self):
        self.assertFalse(self.run_seat(settle_ok=False))
        self.assertNotIn("gate", self.context)
        self.assertIn("limbs did not settle", self.context["positionFailure"]["issues"][0])

    def test_the_swings_do_not_start_when_the_seat_or_the_limbs_failed(self):
        context = {"host": self.host, "hostHandle": "id:5", "clientHandle": "id:-5", "position": {}, "target": {}, "measurements": [], "anchor": None}
        with mock.patch.object(static, "approach", lambda *a: []), mock.patch.object(static, "seat_and_gate", lambda *a: False), mock.patch.object(static.world, "act") as swings, \
                mock.patch.object(static, "return_to_anchor", lambda *a: None), mock.patch.object(static, "crates_destroy", lambda *a: None):
            static.act(self.client, context)
        swings.assert_not_called()


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

        with mock.patch.object(static, "seat_and_gate", lambda *a: True), mock.patch.object(static, "approach", lambda h, c, ctx: []), mock.patch.object(static.world, "act", world_act), mock.patch.object(static.time, "sleep", lambda seconds: None):
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
        with mock.patch.object(static, "seat_and_gate", lambda *a: True), mock.patch.object(static, "approach", lambda h, c, ctx: []), mock.patch.object(static.world, "act", lambda client, ctx, before_swing=None: seen.update(hook=before_swing)), \
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

    def context(self, entries, gate_failure=None):
        return {"measurements": entries, "target": {}, "gateFailure": gate_failure}

    def test_a_run_where_every_swing_landed_is_valid_and_counted(self):
        self.assertEqual(static.check(self.context([self.entry(index, 19.3, 19.3) for index in range(1, 6)])), [])
        self.assertEqual(static.STATE["valid"], 1)

    def test_one_missed_swing_with_every_gate_passed_fails_the_whole_run_and_is_not_counted_valid(self):
        issues = static.check(self.context([self.entry(1, 19.3, 19.3), self.entry(2, 0.0, 0.0), self.entry(3, 19.3, 19.3)]))
        self.assertTrue(issues[0].startswith("FAIL: swing 2 did not land with every gate passed"), issues)
        self.assertEqual((static.STATE["valid"], static.STATE["not_counted"]), (0, 1))
        self.assertEqual(dict(crates.STATE["reasons"]), {"static-copy-swing-missed": 1})

    def test_a_swing_that_failed_its_gate_makes_the_run_invalid_and_not_a_fail(self):
        failure = {"swing": 3, "failures": [{"gate": "limb", "detail": "limb1 is 9.00 from its rest pose (tolerance 0.50)"}], "values": {}}
        issues = static.check(self.context([self.entry(1, 19.3, 19.3), self.entry(2, 19.3, 19.3)], gate_failure=failure))
        self.assertTrue(issues[0].startswith("INVALID: swing 3 not fired, gate limb failed"), issues)
        self.assertEqual((static.STATE["valid"], static.STATE["setup_failed"], static.STATE["not_counted"]), (0, 1, 0))

    def test_a_run_with_no_swing_is_invalid(self):
        self.assertEqual(static.check({"measurements": []}), ["INVALID: no swing recorded"])

    def test_a_position_failure_before_the_swings_is_invalid(self):
        issues = static.check({"positionFailure": {"ok": False, "issues": ["the limbs did not settle within 6 s after the move"]}, "measurements": []})
        self.assertIn("limbs did not settle", issues[0])
        self.assertTrue(issues[0].startswith("INVALID"))

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
