import io
import json
import tempfile
import unittest
from unittest import mock

import run_tests
from tests import spawned_crates as crates

ANCHOR = {"x": 10.0, "y": 5.0}


def crate_row(identifier, x, y=5.0):
    return {"object": {"id": identifier, "name": "SyncInfo(building, id: %d, res: medcrate)" % identifier}, "position": {"x": x, "y": y}}


class Clock:
    def __init__(self, step=0.25):
        self.now = 0.0
        self.step = step

    def time(self):
        self.now += self.step
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def teleport_seat(client, target):
    client.set("player", crates.base.BODY_PATH, {"x": target["x"], "y": target["y"], "z": 0.0})


class SpawnTests(unittest.TestCase):
    def setUp(self):
        crates.reset_launch_state()
        self.addCleanup(crates.reset_launch_state)
        self.host = mock.Mock()
        self.client = mock.Mock()
        self.host_rows = []
        self.client_rows = [crate_row(7, 11.0)]
        self.spawn_arguments = None
        self.host.call.side_effect = self.host_call
        self.player = dict(ANCHOR)
        self.crate_at = {"x": 11.0, "y": 5.0}
        self.clock = Clock()
        self.described = {"handle": "id:7", "id": 7, "name": "SyncInfo(building, id: 7, res: medcrate)", "position": {"x": 11.0, "y": 5.0}, "health": 1000.0,
                          "cantHit": False, "indestructible": False, "animal": False, "rigidbodyType": "Dynamic", "layer": 8, "physicsActive": True}
        for patch in (mock.patch.object(crates.time, "sleep", self.clock.sleep), mock.patch.object(crates.time, "time", self.clock.time),
                      mock.patch.object(crates.base, "player_position", lambda game: dict(self.player)), mock.patch.object(crates, "seat_client", teleport_seat),
                      mock.patch.object(crates.base, "rows_near", self.rows_near),
                      mock.patch.object(crates.world, "host_position", lambda host, handle: dict(self.crate_at)),
                      mock.patch.object(crates.world, "describe_candidate", lambda host, row: dict(self.described, position=row["position"]))):
            patch.start()
            self.addCleanup(patch.stop)

    def host_call(self, command, **arguments):
        if command == "spawn":
            self.spawn_arguments = arguments
            self.host_rows = [crate_row(7, 11.0)]

    def rows_near(self, game, component, position, name=None, radius=3.0):
        rows = self.host_rows if game is self.host else self.client_rows
        return [row for row in rows if crates.base.distance(row["position"], position) <= radius]

    def test_the_crate_is_spawned_at_the_fixed_offset_from_the_client(self):
        target = crates.spawn_crate(self.host, self.client)
        arguments = self.spawn_arguments
        self.assertEqual((arguments["id"], arguments["x"], arguments["y"], arguments["pickup"]), ("medcrate", 11.0, 5.0, False))
        self.assertEqual((target["handle"], target["clientHandle"], target["startHealth"], target["spawnOffset"]), ("id:7", "id:7", 1000.0, 1.0))
        self.assertTrue(target["physicsActive"])

    def test_the_settle_trace_has_the_spawn_half_second_and_two_second_points_on_host_and_client(self):
        target = crates.spawn_crate(self.host, self.client)
        labels = [point["label"] for point in target["settleTrace"]]
        self.assertEqual(labels, ["spawn", "after 0.5 s", "after 2.0 s"])
        for point in target["settleTrace"]:
            self.assertEqual(point["host"], {"x": 11.0, "y": 5.0})
            self.assertEqual(point["client"], {"x": 11.0, "y": 5.0})

    def test_a_crate_that_slides_shows_its_positions_in_the_trace(self):
        positions = iter([{"x": 11.0, "y": 5.0}] * 3 + [{"x": 12.5, "y": 5.0}] * 60)
        with mock.patch.object(crates.world, "host_position", lambda host, handle: next(positions)):
            self.client_rows = [crate_row(7, 11.0), crate_row(8, 12.5)]
            target = crates.spawn_crate(self.host, self.client)
        self.assertEqual(target["settleTrace"][0]["host"]["x"], 11.0)
        self.assertEqual(target["settleTrace"][-1]["host"]["x"], 12.5)
        self.assertEqual(target["position"]["x"], 12.5)

    def test_a_crate_the_client_does_not_list_fails_the_setup_with_its_category(self):
        self.client_rows = []
        with self.assertRaises(crates.SetupFailure) as caught:
            crates.spawn_crate(self.host, self.client)
        self.assertEqual(caught.exception.category, "client-does-not-list-crate")

    def test_a_crate_that_was_already_there_is_not_taken_for_the_new_one(self):
        self.host_rows = [crate_row(3, 10.9)]

        def spawn(command, **arguments):
            if command == "spawn":
                self.host_rows = [crate_row(3, 10.9), crate_row(7, 11.0)]

        self.host.call.side_effect = spawn
        self.assertEqual(crates.spawn_crate(self.host, self.client)["id"], 7)

    def test_no_new_crate_on_the_host_fails_the_setup(self):
        self.host.call.side_effect = lambda command, **arguments: None
        with self.assertRaises(crates.SetupFailure) as caught:
            crates.spawn_crate(self.host, self.client)
        self.assertEqual(caught.exception.category, "no-new-crate")

    def test_the_client_is_put_back_at_the_first_anchor_before_the_second_spawn(self):
        crates.spawn_crate(self.host, self.client)
        self.player = {"x": 14.0, "y": 5.0}
        self.host_rows = []
        crates.spawn_crate(self.host, self.client)
        self.client.set.assert_called_with("player", crates.base.BODY_PATH, {"x": 10.0, "y": 5.0, "z": 0.0})

    def test_a_crate_below_the_health_floor_fails_the_setup(self):
        self.described["health"] = 20.0
        with self.assertRaises(crates.SetupFailure) as caught:
            crates.spawn_crate(self.host, self.client)
        self.assertEqual(caught.exception.category, "low-health")


class BandTests(unittest.TestCase):
    def setUp(self):
        seat = mock.patch.object(crates, "seat_client", teleport_seat)
        seat.start()
        self.addCleanup(seat.stop)
        self.crate = {"x": 20.0, "y": 5.0}
        self.player = {"x": 17.0, "y": 5.0}
        self.client = mock.Mock()
        self.client.set.side_effect = self.teleport
        self.landing = None
        for patch in (mock.patch.object(crates.time, "sleep", lambda seconds: None), mock.patch.object(crates.world, "host_position", lambda host, handle: dict(self.crate)),
                      mock.patch.object(crates.base, "player_position", lambda game: dict(self.player))):
            patch.start()
            self.addCleanup(patch.stop)

    def teleport(self, target, path, value):
        if self.landing is not None:
            self.player = {"x": self.crate["x"] - self.landing, "y": 5.0}

    def band(self):
        return crates.ensure_band(None, self.client, "id:1", self.crate)

    def test_every_distance_inside_the_band_needs_no_re_seat(self):
        for distance in (2.5, 2.9, 3.0, 3.2):
            with self.subTest(distance=distance):
                self.player = {"x": self.crate["x"] - distance, "y": 5.0}
                result = self.band()
                self.assertEqual((result["ok"], result["reseats"], result["distances"]), (True, 0, [distance]))
        self.client.set.assert_not_called()

    def test_the_distances_seen_in_the_earlier_launches_outside_the_band_are_re_seated_to_the_band_middle(self):
        for distance in (3.28, 3.29, 3.3, 3.55, 3.63, 3.9, 4.66, 5.02, 11.79):
            with self.subTest(distance=distance):
                self.client.reset_mock()
                self.player = {"x": self.crate["x"] - distance, "y": 5.0}
                self.landing = 2.8
                result = self.band()
                self.assertEqual((result["ok"], result["reseats"]), (True, 1))
                self.client.set.assert_called_once_with("player", crates.base.BODY_PATH, {"x": 20.0 - crates.BAND_TARGET, "y": 5.0, "z": 0.0})

    def plant(self, first_point, second_point):
        (x0, y0), (x1, y1) = first_point, second_point
        slope = (y1 - y0) / (x1 - x0)

        def landed(target, path, value):
            offset = self.crate["x"] - value["x"]
            self.player = {"x": self.crate["x"] - (y0 + slope * (offset - x0)), "y": 5.0}

        self.client.set.side_effect = landed

    def test_the_sequence_that_oscillated_in_the_fixed_full_build_launch_now_converges(self):
        self.player = {"x": self.crate["x"] - 3.58, "y": 5.0}
        self.plant((2.0, 2.24), (2.85, 3.58))
        result = self.band()
        self.assertTrue(result["ok"], result)
        self.assertLessEqual(result["reseats"], crates.BAND_TRIES)
        self.assertEqual(len(result["distances"]), result["reseats"] + 1)
        self.assertLess(abs(result["distances"][-1] - crates.BAND_TARGET), abs(result["distances"][0] - crates.BAND_TARGET))
        self.assertGreaterEqual(result["distances"][-1], crates.BAND_LOW)
        self.assertLessEqual(result["distances"][-1], crates.BAND_HIGH)

    def test_the_first_move_goes_to_the_band_middle_and_the_next_one_moves_by_the_measured_error(self):
        self.player = {"x": self.crate["x"] - 3.58, "y": 5.0}
        self.plant((2.0, 2.24), (2.85, 3.58))
        result = self.band()
        self.assertEqual(result["offsets"][0], round(crates.BAND_TARGET, 3))
        expected = crates.BAND_TARGET + crates.BAND_GAIN * (crates.BAND_TARGET - 3.58)
        self.assertAlmostEqual(result["offsets"][1], expected, places=2)

    def test_the_old_two_point_zero_then_middle_rule_would_have_stayed_out_and_this_one_does_not_repeat_an_offset(self):
        self.player = {"x": self.crate["x"] - 3.58, "y": 5.0}
        self.plant((2.0, 2.24), (2.85, 3.58))
        result = self.band()
        self.assertEqual(len(set(result["offsets"])), len(result["offsets"]))

    def test_a_plant_that_overshoots_by_more_than_a_third_still_converges_within_the_tries(self):
        for slope in (0.5, 1.0, 1.576, 2.0):
            with self.subTest(slope=slope):
                self.client.reset_mock()
                self.player = {"x": self.crate["x"] - 4.2, "y": 5.0}
                self.plant((2.0, 2.0), (3.0, 2.0 + slope))
                self.assertTrue(self.band()["ok"])

    def test_a_correction_never_asks_for_an_offset_below_the_minimum(self):
        self.player = {"x": self.crate["x"] - 9.0, "y": 5.0}
        self.plant((0.0, 6.0), (1.0, 7.0))
        result = self.band()
        self.assertTrue(all(offset >= crates.MIN_RESEAT_OFFSET for offset in result["offsets"]))

    def test_a_client_too_close_is_moved_to_the_middle_of_the_band(self):
        self.player = {"x": self.crate["x"] - 1.2, "y": 5.0}
        self.landing = 2.85
        result = self.band()
        self.assertTrue(result["ok"])
        self.client.set.assert_called_once_with("player", crates.base.BODY_PATH, {"x": self.crate["x"] - 2.85, "y": 5.0, "z": 0.0})

    def test_a_client_that_drifts_back_out_is_re_seated_again_and_the_distances_are_recorded(self):
        self.player = {"x": self.crate["x"] - 3.6, "y": 5.0}
        landings = iter([3.4, 3.35, 2.9])
        self.client.set.side_effect = lambda target, path, value: self.__dict__.update(player={"x": self.crate["x"] - next(landings), "y": 5.0})
        result = self.band()
        self.assertEqual((result["ok"], result["reseats"], result["distances"]), (True, 3, [3.6, 3.4, 3.35, 2.9]))

    def test_a_client_that_cannot_be_brought_into_the_band_fails_after_the_set_number_of_tries(self):
        self.player = {"x": self.crate["x"] - 3.6, "y": 5.0}
        self.landing = 3.6
        result = self.band()
        self.assertEqual((result["ok"], result["reseats"], len(result["distances"])), (False, crates.BAND_TRIES, crates.BAND_TRIES + 1))
        self.assertEqual(self.client.set.call_count, crates.BAND_TRIES)


class HitListTests(unittest.TestCase):
    def test_a_plain_list_is_used_as_it_is(self):
        self.assertEqual(crates.hit_list([{"a": 1}]), [{"a": 1}])

    def test_a_dict_with_a_known_list_key_gives_that_list(self):
        for key in ("items", "hits", "results", "values", "elements", "array", "data", "value"):
            with self.subTest(key=key):
                self.assertEqual(crates.hit_list({"count": 1, key: [{"a": 1}]}), [{"a": 1}])

    def test_a_dict_with_one_list_under_another_key_gives_that_list(self):
        self.assertEqual(crates.hit_list({"type": "RaycastHit2D[]", "hitsInOrder": [{"a": 1}, {"a": 2}]}), [{"a": 1}, {"a": 2}])

    def test_a_dict_with_numbered_entries_is_ordered_numerically(self):
        self.assertEqual(crates.hit_list({"10": "c", "2": "b", "1": "a", "length": 3}), ["a", "b", "c"])

    def test_an_empty_counted_dict_is_no_hits(self):
        self.assertEqual(crates.hit_list({"count": 0}), [])

    def test_an_unknown_dict_names_its_keys_in_the_error(self):
        with self.assertRaises(ValueError) as caught:
            crates.hit_list({"zeta": 1, "alpha": 2})
        self.assertIn("['alpha', 'zeta']", str(caught.exception))

    def test_a_scalar_is_an_error(self):
        with self.assertRaises(ValueError):
            crates.hit_list("nothing")

    def test_a_dict_result_from_the_link_is_cast_without_falling_back(self):
        client = mock.Mock()
        client.call.return_value = {"count": 2, "items": [{"collider": {"name": "Body_ClientD", "tag": "Player"}}, {"collider": {"name": "SyncInfo(building, id: 1, res: medcrate)"}}]}
        cast = crates.mimic_cast(client, {"x": 0.0, "y": 0.0}, {"x": 3.0, "y": 0.0})
        self.assertEqual((cast["method"], cast["error"], cast["crateIndex"]), ("RaycastAll", None, 1))
        self.assertEqual(cast["hitsBeforeCrate"][0]["tag"], "Player")


class CastTests(unittest.TestCase):
    def setUp(self):
        self.client = mock.Mock()

    def test_a_raycast_all_list_is_read_in_order_with_names_and_tags(self):
        self.client.call.return_value = [{"collider": {"name": "Ground", "tag": "BlockGround"}, "distance": 1.0}, {"collider": {"name": "SyncInfo(building, id: 1, res: medcrate)"}, "distance": 2.0}]
        cast = crates.mimic_cast(self.client, {"x": 0.0, "y": 0.0}, {"x": 3.0, "y": 0.0})
        self.assertEqual((cast["method"], cast["error"], cast["crateIndex"]), ("RaycastAll", None, 1))
        self.assertEqual(cast["hitsBeforeCrate"][0]["tag"], "BlockGround")
        arguments = self.client.call.call_args.kwargs
        self.assertEqual((arguments["method"], arguments["args"][1], arguments["args"][2]), ("RaycastAll", {"x": 1.0, "y": 0.0}, 4.5))

    def test_a_crate_that_is_not_in_the_cast_has_no_index(self):
        self.client.call.return_value = [{"collider": {"name": "Ground"}}]
        cast = crates.mimic_cast(self.client, {"x": 0.0, "y": 0.0}, {"x": 3.0, "y": 0.0})
        self.assertIsNone(cast["crateIndex"])

    def test_a_raycast_that_cannot_run_falls_back_to_point_samples_and_says_so(self):
        def call(command, **arguments):
            if arguments["method"] == "RaycastAll":
                raise RuntimeError("no such overload")
            point = arguments["args"][0]
            return {"name": "Ground"} if point["x"] < 1.0 else ({"name": "SyncInfo(building, id: 1, res: medcrate)"} if point["x"] >= 2.5 else None)

        self.client.call.side_effect = call
        cast = crates.mimic_cast(self.client, {"x": 0.0, "y": 0.0}, {"x": 3.0, "y": 0.0})
        self.assertEqual(cast["method"], "OverlapPoint samples")
        self.assertIn("RaycastAll failed: no such overload", cast["error"])
        self.assertEqual([hit["name"] for hit in cast["hits"]], ["Ground", "SyncInfo(building, id: 1, res: medcrate)"])
        self.assertEqual(cast["crateIndex"], 1)

    def test_neither_method_working_is_recorded_as_an_error_with_no_hits(self):
        self.client.call.side_effect = RuntimeError("link refused")
        cast = crates.mimic_cast(self.client, {"x": 0.0, "y": 0.0}, {"x": 3.0, "y": 0.0})
        self.assertEqual(cast["hits"], [])
        self.assertIn("samples failed", cast["error"])

    def test_an_unreadable_limb_position_is_recorded_not_fatal(self):
        cast = crates.mimic_cast(self.client, None, {"x": 3.0, "y": 0.0})
        self.assertEqual((cast["method"], cast["hits"]), (None, []))
        self.assertIn("limb1", cast["error"])


class BeforeSwingTests(unittest.TestCase):
    def setUp(self):
        self.context = {"host": mock.Mock(), "hostHandle": "id:1", "clientHandle": "id:1", "position": {"x": 20.0, "y": 5.0}}

    def test_a_swing_in_the_band_returns_the_band_and_every_geometry_field(self):
        values = {"standing": True, "isRight": False, "limbs[1].transform.position": {"x": 17.2, "y": 5.4}, "targetLookPos": {"x": 20.0, "y": 5.0, "z": 0.0}}
        client = mock.Mock()
        client.get.side_effect = lambda target, path, depth=0: values[path]
        with mock.patch.object(crates, "ensure_band", lambda host, game, handle, fallback: {"ok": True, "reseats": 0, "distances": [3.0]}), \
                mock.patch.object(crates.world, "host_position", lambda host, handle: {"x": 20.0, "y": 5.0}), \
                mock.patch.object(crates.base, "player_position", lambda game: {"x": 17.0, "y": 5.0}), \
                mock.patch.object(crates, "client_crate_position", lambda game, near: {"x": 19.9, "y": 5.0}), \
                mock.patch.object(crates, "mimic_cast", lambda game, origin, aim: {"method": "RaycastAll", "hits": []}):
            extra = crates.before_swing(client, self.context, 1, {"x": 20.0, "y": 5.0})
        geometry = extra["geometry"]
        self.assertEqual(extra["band"]["reseats"], 0)
        self.assertEqual((geometry["standing"], geometry["isRight"], geometry["distance"]), (True, False, 3.0))
        self.assertEqual((geometry["clientPosition"], geometry["crateHostPosition"], geometry["crateClientPosition"]), ({"x": 17.0, "y": 5.0}, {"x": 20.0, "y": 5.0}, {"x": 19.9, "y": 5.0}))
        self.assertEqual((geometry["limb1Position"], geometry["targetLookPos"], geometry["intendedAim"]), ({"x": 17.2, "y": 5.4}, {"x": 20.0, "y": 5.0}, {"x": 20.0, "y": 5.0}))
        self.assertEqual(geometry["cast"]["method"], "RaycastAll")

    def test_the_body_type_and_physics_state_of_the_host_and_client_copy_are_recorded_every_swing(self):
        self.context["clientHandle"] = "id:-44"
        seen = {}

        def optional_get(game, handle, path, nonpublic=False):
            seen[(handle, path, nonpublic)] = True
            return "Kinematic" if handle == "id:-44" else "Dynamic"

        def physics_active(game, handle):
            return handle == "id:1"

        client = mock.Mock()
        client.get.return_value = True
        with mock.patch.object(crates, "ensure_band", lambda host, game, handle, fallback: {"ok": True, "reseats": 0, "distances": [3.0]}),                 mock.patch.object(crates.world, "host_position", lambda host, handle: {"x": 20.0, "y": 5.0}),                 mock.patch.object(crates.base, "player_position", lambda game: {"x": 17.0, "y": 5.0}),                 mock.patch.object(crates, "client_crate_position", lambda game, near: None),                 mock.patch.object(crates, "mimic_cast", lambda game, origin, aim: {"method": None, "hits": []}),                 mock.patch.object(crates.world, "optional_get", optional_get), mock.patch.object(crates.world, "physics_active", physics_active):
            extra = crates.before_swing(client, self.context, 1, {"x": 20.0, "y": 5.0})
        self.assertEqual(extra["physics"]["host"], {"handle": "id:1", "bodyType": "Dynamic", "physicsActive": True})
        self.assertEqual(extra["physics"]["client"], {"handle": "id:-44", "bodyType": "Kinematic", "physicsActive": False})
        self.assertIn(("id:-44", "rb.bodyType", True), seen)

    def test_unreadable_fields_are_recorded_with_their_error_not_fatal(self):
        client = mock.Mock()
        client.get.side_effect = RuntimeError("no member")
        with mock.patch.object(crates, "ensure_band", lambda host, game, handle, fallback: {"ok": True, "reseats": 0, "distances": [3.0]}), \
                mock.patch.object(crates.world, "host_position", lambda host, handle: {"x": 20.0, "y": 5.0}), \
                mock.patch.object(crates.base, "player_position", lambda game: {"x": 17.0, "y": 5.0}), \
                mock.patch.object(crates, "client_crate_position", lambda game, near: None):
            extra = crates.before_swing(client, self.context, 1, {"x": 20.0, "y": 5.0})
        self.assertIn("error", extra["geometry"]["standing"])
        self.assertIsNone(extra["geometry"]["limb1Position"])

    def test_a_swing_that_cannot_be_brought_into_the_band_is_not_fired_and_the_run_is_marked(self):
        with mock.patch.object(crates, "ensure_band", lambda host, game, handle, fallback: {"ok": False, "reseats": 4, "distances": [3.6, 3.5, 3.5, 3.6, 3.7]}):
            self.assertIsNone(crates.before_swing(mock.Mock(), self.context, 3, {"x": 20.0, "y": 5.0}))
        self.assertEqual(self.context["bandFailure"], {"swing": 3, "distances": [3.6, 3.5, 3.5, 3.6, 3.7]})


REAL_WAIT_CRATE_STILL = crates.wait_crate_still


class SettledSetupTests(unittest.TestCase):
    def setUp(self):
        crates.reset_launch_state()
        self.addCleanup(crates.reset_launch_state)
        self.host = mock.Mock()
        self.client = mock.Mock()
        self.anchor = {"x": 10.0, "y": 50.0}
        self.seat_results = []
        self.spawned = []

        def spawn_object(host, client, object_id, min_health, spot=None):
            self.spawned.append(spot)
            return {"handle": "id:%d" % len(self.spawned), "position": dict(spot), "clientHandle": "id:-1"}

        def seat(game, target, tolerance=0.05, paths=(), sleep=None):
            result = self.seat_results.pop(0) if self.seat_results else self.good_seat()
            self.seated_at = target
            return result

        for patch in (mock.patch.object(crates, "hold_client_at_anchor", lambda client: self.anchor), mock.patch.object(crates, "spawn_object", spawn_object),
                      mock.patch.object(crates.positioncontrol, "seat_swinging_body", seat), mock.patch.object(crates.positioncontrol, "discover_diagnostic_paths", lambda game: ["rb.position"]),
                      mock.patch.object(crates, "wait_crate_still", lambda host, handle, fallback: {"still": True, "seconds": 0.6, "lastSpeed": 0.0})):
            patch.start()
            self.addCleanup(patch.stop)

    def good_seat(self):
        return {"ok": True, "issues": [], "linkReadDisagrees": False, "holderDrifts": [0.0], "rbDrifts": [0.0], "linkDrifts": [0.0]}

    def bad_seat(self):
        return {"ok": False, "issues": ["rb.position is 0.300 from the target (tolerance 0.050)"], "linkReadDisagrees": True, "holderDrifts": [0.1], "rbDrifts": [0.3], "linkDrifts": [0.2]}

    def test_the_crate_is_spawned_at_the_band_distance_and_the_client_is_seated_at_the_anchor_after_it_is_still(self):
        target, attempts, seat = crates.spawn_settled(self.host, self.client)
        self.assertEqual(self.spawned, [{"x": 10.0 + crates.BAND_TARGET, "y": 50.0}])
        self.assertEqual(seat, self.anchor)
        self.assertEqual(self.seated_at, self.anchor)
        self.assertEqual(len(attempts), 1)
        self.assertTrue(crates.BAND_LOW <= crates.SETTLED_OFFSETS[0] <= crates.BAND_HIGH)

    def test_the_client_is_seated_only_after_the_crate_is_still(self):
        order = []
        with mock.patch.object(crates, "wait_crate_still", lambda host, handle, fallback: order.append("still") or {"still": True}), \
                mock.patch.object(crates.positioncontrol, "seat_swinging_body", lambda *a, **k: order.append("seat") or self.good_seat()):
            crates.spawn_settled(self.host, self.client)
        self.assertEqual(order, ["still", "seat"])

    def test_a_seat_that_does_not_verify_is_retried_at_a_larger_offset_still_inside_the_band_and_the_first_crate_is_removed(self):
        self.seat_results = [self.bad_seat(), self.good_seat()]
        target, attempts, seat = crates.spawn_settled(self.host, self.client)
        for spawned, offset in zip(self.spawned, crates.SETTLED_OFFSETS):
            self.assertAlmostEqual(spawned["x"] - 10.0, offset)
        self.assertGreater(crates.SETTLED_OFFSETS[1], crates.SETTLED_OFFSETS[0])
        self.assertLessEqual(crates.SETTLED_OFFSETS[1], crates.BAND_HIGH)
        self.assertEqual([item["seat"]["ok"] for item in attempts], [False, True])
        self.host.set.assert_called_once_with("id:1", "health", 0)

    def test_when_no_offset_verifies_the_run_is_a_setup_failure_naming_every_attempt(self):
        self.seat_results = [self.bad_seat(), self.bad_seat()]
        with self.assertRaises(crates.SetupFailure) as caught:
            crates.spawn_settled(self.host, self.client)
        self.assertEqual(caught.exception.category, "client-seat-not-verified-after-settle")
        self.assertIn("rb.position is 0.300", str(caught.exception))

    def test_the_seat_rule_for_the_client_is_not_relaxed(self):
        called = []
        with mock.patch.object(crates.positioncontrol, "seat_swinging_body", lambda game, target, tolerance=0.05, paths=(), sleep=None: called.append(tolerance) or self.good_seat()):
            crates.spawn_settled(self.host, self.client)
        self.assertEqual(called, [crates.positioncontrol.HOLD_TOLERANCE])

    def test_the_first_run_is_the_diagnostic_one_with_the_old_setup_and_later_runs_use_the_settled_setup(self):
        old, new = mock.Mock(return_value={"position": {"x": 1.0, "y": 2.0}, "handle": "id:1", "clientHandle": "id:-1"}), mock.Mock(return_value=({"position": {"x": 1.0, "y": 2.0}, "handle": "id:2", "clientHandle": "id:-2"}, [{"offset": 2.85}], self.anchor))
        with mock.patch.object(crates, "spawn_crate", old), mock.patch.object(crates, "spawn_settled", new), mock.patch.object(crates, "position_setup", lambda host, client, context: context.update({"startPositions": {}})), \
                mock.patch.object(crates.base, "empty_the_hand", lambda client: None):
            first = crates.prepare(self.host, self.client)
            second = crates.prepare(self.host, self.client)
        self.assertTrue(first["diagnostic"])
        self.assertFalse(second["diagnostic"])
        self.assertEqual(second["settledSeat"], self.anchor)
        self.assertEqual(second["target"]["settledAttempts"], [{"offset": 2.85}])
        old.assert_called_once()
        new.assert_called_once()

    def test_the_verified_seat_is_the_target_of_the_preflight_when_the_band_needs_no_reseat(self):
        context = {"host": self.host, "hostHandle": "id:7", "position": {"x": 12.85, "y": 50.0}, "settledSeat": self.anchor, "hostPark": {"x": -2.0, "y": 50.0}, "diagnostic": False, "clientHandle": "id:-7"}
        seen = {}
        with mock.patch.object(crates, "ensure_band", lambda *a, **k: {"ok": True, "distances": [2.85], "seat": None}), \
                mock.patch.object(crates, "run_preflight", lambda host, client, ctx, band: seen.setdefault("seat", band["seat"]) and {"ok": True}), \
                mock.patch.object(crates, "read_geometry", lambda *a: {}), mock.patch.object(crates, "record_parked_host", lambda *a: None), mock.patch.object(crates, "crate_physics", lambda g, h: {}):
            crates.before_swing(self.client, context, 1, {"x": 12.85, "y": 50.0})
        self.assertEqual(seen["seat"], self.anchor)

    def test_the_diagnostic_run_records_a_trace_from_the_seat_to_the_first_swing(self):
        context = {"host": self.host, "hostHandle": "id:7", "position": {"x": 12.85, "y": 50.0}, "hostPark": {"x": -2.0, "y": 50.0}, "diagnostic": True, "target": {}, "clientPaths": ["rb.position"], "clientHandle": "id:-7"}
        with mock.patch.object(crates, "ensure_band", lambda *a, **k: {"ok": True, "distances": [2.85], "seat": {"x": 10.0, "y": 50.0}}), \
                mock.patch.object(crates, "trace_client_and_crate", mock.Mock(return_value=[{"t": 0.0}])) as trace, \
                mock.patch.object(crates, "run_preflight", lambda *a: {"ok": True}), mock.patch.object(crates, "read_geometry", lambda *a: {}), \
                mock.patch.object(crates, "record_parked_host", lambda *a: None), mock.patch.object(crates, "crate_physics", lambda g, h: {}):
            crates.before_swing(self.client, context, 1, {"x": 12.85, "y": 50.0})
        trace.assert_called_once()
        self.assertEqual(context["target"]["diagnostic"]["rows"], [{"t": 0.0}])

    def test_the_trace_rows_carry_the_client_three_ways_the_crate_and_the_host(self):
        context = {"host": self.host, "hostHandle": "id:7", "clientPaths": ["rb.position", "limbs[1].transform.position", "rb.velocity"]}
        snapshot = {"linkRead": {"x": 10.1, "y": 50.0}, "holder": {"x": 10.0, "y": 50.0}, "paths": {"rb.position": {"x": 10.2, "y": 50.0}, "limbs[1].transform.position": {"x": 10.0, "y": 51.0}, "rb.velocity": {"x": 0.5, "y": 0.0}}}
        clock = [0.0]
        with mock.patch.object(crates.positioncontrol, "parked_snapshot", lambda game, paths: snapshot), mock.patch.object(crates.world, "host_position", lambda host, handle: {"x": 12.85, "y": 50.0}), \
                mock.patch.object(crates, "read_at", lambda game, handle, path: {"x": 0.0, "y": -0.1}), mock.patch.object(crates, "client_crate_position", lambda client, near: {"x": 12.8, "y": 50.0}), \
                mock.patch.object(crates.base, "player_position", lambda game: {"x": -2.0, "y": 50.0}), mock.patch.object(crates.time, "time", lambda: clock[0]), \
                mock.patch.object(crates.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
            rows = crates.trace_client_and_crate(self.host, self.client, context, seconds=0.3, interval=0.1)
        self.assertEqual(len(rows), 3)
        row = rows[0]
        self.assertEqual((row["holder"], row["linkRead"], row["rb"]), ({"x": 10.0, "y": 50.0}, {"x": 10.1, "y": 50.0}, {"x": 10.2, "y": 50.0}))
        self.assertEqual((row["clientVelocity"], row["crate"], row["crateVelocity"], row["hostBody"]), ({"x": 0.5, "y": 0.0}, {"x": 12.85, "y": 50.0}, {"x": 0.0, "y": -0.1}, {"x": -2.0, "y": 50.0}))
        self.assertEqual(row["clientToCrate"], 2.75)

    def test_a_crate_that_stays_still_is_reported_still_and_one_that_keeps_moving_is_not(self):
        clock = [0.0]
        speeds = iter([0.5, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01])
        with mock.patch.object(crates.time, "time", lambda: clock[0]), mock.patch.object(crates.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)), \
                mock.patch.object(crates.world, "host_position", lambda host, handle: {"x": 1.0, "y": 2.0}), mock.patch.object(crates, "read_at", lambda game, handle, path: {"x": next(speeds), "y": 0.0}):
            still = REAL_WAIT_CRATE_STILL(self.host, "id:1", {"x": 1.0, "y": 2.0})
        self.assertTrue(still["still"])
        clock[0] = 0.0
        with mock.patch.object(crates.time, "time", lambda: clock[0]), mock.patch.object(crates.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)), \
                mock.patch.object(crates.world, "host_position", lambda host, handle: {"x": 1.0, "y": 2.0}), mock.patch.object(crates, "read_at", lambda game, handle, path: {"x": 0.5, "y": 0.0}):
            moving = REAL_WAIT_CRATE_STILL(self.host, "id:1", {"x": 1.0, "y": 2.0})
        self.assertFalse(moving["still"])


class RunControlTests(unittest.TestCase):
    def setUp(self):
        crates.reset_launch_state()
        self.addCleanup(crates.reset_launch_state)

    def landed(self):
        return {"measurements": [{"hostDelta": 19.3, "clientDelta": 19.3}]}

    def missed(self):
        return {"measurements": [{"hostDelta": 0.0, "clientDelta": 0.0}], "target": {"name": "medcrate"}}

    def prepare_with(self, outcome):
        with mock.patch.object(crates.base, "empty_the_hand", lambda client: None), mock.patch.object(crates, "spawn_crate", outcome), mock.patch.object(crates, "spawn_settled", lambda host, client: (outcome(host, client), [], None)), mock.patch.object(crates, "position_setup", lambda host, client, context: context.update({"startPositions": {}})):
            return crates.prepare("host", "client")

    def test_a_band_failure_is_an_invalid_setup_failure_and_not_a_missed_swing(self):
        issues = crates.check({"bandFailure": {"swing": 1, "distances": [3.6, 3.7]}, "measurements": []})
        self.assertTrue(issues[0].startswith("INVALID: the client could not be brought into the 2.5 to 3.2 band before swing 1"))
        self.assertEqual((crates.STATE["setup_failed"], crates.STATE["swing_failed"], crates.STATE["valid"]), (1, 0, 0))
        self.assertEqual(dict(crates.STATE["reasons"]), {"distance-band-unreachable": 1})

    def test_a_band_failure_after_a_landed_first_swing_still_marks_the_run_invalid(self):
        issues = crates.check({"bandFailure": {"swing": 4, "distances": [3.6]}, "measurements": [{"hostDelta": 19.3, "clientDelta": 19.3}]})
        self.assertTrue(issues)
        self.assertEqual(crates.STATE["valid"], 0)

    def test_three_runs_without_a_landed_first_swing_stop_the_launch(self):
        for _ in range(3):
            self.assertTrue(crates.check(self.missed()))
        with self.assertRaises(unittest.SkipTest) as caught:
            self.prepare_with(lambda host, client: self.fail("must not spawn"))
        self.assertIn("looks unhittable", str(caught.exception))

    def test_five_setup_failures_with_no_valid_run_stop_the_launch(self):
        def fail(host, client):
            raise crates.SetupFailure("no-new-crate", "no new crate")

        for _ in range(crates.STOP_AFTER_SETUP_FAILURES):
            with self.assertRaises(crates.SetupFailure):
                self.prepare_with(fail)
        with self.assertRaises(unittest.SkipTest) as caught:
            self.prepare_with(fail)
        self.assertIn("first 5 attempts all failed setup", str(caught.exception))

    def test_four_setup_failures_do_not_stop_it(self):
        def fail(host, client):
            raise crates.SetupFailure("no-new-crate", "no new crate")

        for _ in range(crates.STOP_AFTER_SETUP_FAILURES - 1):
            with self.assertRaises(crates.SetupFailure):
                self.prepare_with(fail)
        target = dict(handle="id:7", clientHandle="id:7", position={"x": 1.0, "y": 1.0})
        self.assertIsNotNone(self.prepare_with(lambda host, client: target))

    def test_later_failures_do_not_stop_a_launch_that_already_has_a_valid_run(self):
        self.assertEqual(crates.check(self.landed()), [])
        for _ in range(5):
            crates.check(self.missed())
        target = dict(handle="id:7", clientHandle="id:7", position={"x": 1.0, "y": 1.0})
        self.assertIsNotNone(self.prepare_with(lambda host, client: target))

    def test_ten_valid_runs_end_the_launch(self):
        for _ in range(crates.VALID_RUNS_WANTED):
            crates.check(self.landed())
        with self.assertRaises(unittest.SkipTest):
            self.prepare_with(lambda host, client: self.fail("must not spawn"))

    def test_failure_reasons_are_grouped_and_written_to_the_failure_file(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(crates, "FAILURE_DIRECTORY", directory):
            crates.record_failure("no-new-crate", "first")
            crates.record_failure("no-new-crate", "second")
            crates.record_failure("distance-band-unreachable", "third")
            with open(directory + "/" + crates.FAILURE_FILE, encoding="utf-8") as handle:
                written = json.load(handle)
        self.assertEqual(written["reasons"], {"no-new-crate": 2, "distance-band-unreachable": 1})
        self.assertEqual([item["message"] for item in written["attempts"]], ["first", "second", "third"])

    def test_the_spawned_crate_is_destroyed_through_the_host_after_the_swings(self):
        host = mock.Mock()
        with mock.patch.object(crates.world, "act", lambda client, context, before_swing=None: None):
            crates.act("client", {"host": host, "hostHandle": "id:7"})
        host.set.assert_called_once_with("id:7", "health", 0)

    def test_the_crate_is_destroyed_even_when_the_swings_raise(self):
        host = mock.Mock()

        def explode(client, context, before_swing=None):
            raise RuntimeError("link lost")

        with mock.patch.object(crates.world, "act", explode):
            with self.assertRaises(RuntimeError):
                crates.act("client", {"host": host, "hostHandle": "id:7"})
        host.set.assert_called_once()

    def test_the_swing_hook_is_handed_to_the_shared_swing_loop(self):
        seen = {}
        with mock.patch.object(crates.world, "act", lambda client, context, before_swing=None: seen.update(hook=before_swing)):
            crates.act("client", {"host": mock.Mock(), "hostHandle": "id:7"})
        self.assertIs(seen["hook"], crates.before_swing)

    def test_the_scenario_is_selectable_alone_in_the_evidence_group(self):
        from tests import desync_scenarios as scenarios
        self.assertEqual(scenarios.matching_scenario_names(["spawned_crate"]), ["spawned_crate_hit_by_client"])
        self.assertEqual(sorted(scenarios.counts_by_group(["spawned_crate"])), ["hook-evidence"])


class PreflightTests(unittest.TestCase):
    def test_the_planned_gates_and_counts_are_consistent_for_twelve_attempts(self):
        self.assertEqual(crates.preflight(["spawned_crate"], 12), [])

    def test_a_launch_that_does_not_select_the_scenario_is_not_checked(self):
        self.assertEqual(crates.preflight(["worldhit_building"], 1), [])

    def test_a_band_that_is_empty_or_beyond_the_attack_distance_is_refused(self):
        with mock.patch.object(crates, "BAND_LOW", 3.5):
            self.assertTrue(any("is empty" in problem for problem in crates.preflight(["spawned_crate"], 12)))
        with mock.patch.object(crates, "BAND_HIGH", 5.0):
            self.assertTrue(any("attack distance" in problem for problem in crates.preflight(["spawned_crate"], 12)))

    def test_a_re_seat_target_outside_the_band_or_a_gain_outside_zero_to_one_is_refused(self):
        with mock.patch.object(crates, "BAND_TARGET", 4.0):
            self.assertTrue(any("re-seat target" in problem for problem in crates.preflight(["spawned_crate"], 12)))
        with mock.patch.object(crates, "BAND_GAIN", 1.5):
            self.assertTrue(any("re-seat gain" in problem for problem in crates.preflight(["spawned_crate"], 12)))

    def test_too_few_attempts_for_the_valid_runs_and_the_early_stop_are_refused(self):
        self.assertEqual(len(crates.preflight(["spawned_crate"], 4)), 2)

    def test_checkpoints_that_do_not_fit_the_minimum_settle_time_are_refused(self):
        with mock.patch.object(crates, "CHECKPOINT_SECONDS", (0.5, 3.0)):
            self.assertTrue(any("checkpoints" in problem for problem in crates.preflight(["spawned_crate"], 12)))

    def test_the_launch_runner_refuses_before_any_game_starts(self):
        arguments = run_tests.parse_args(["--pair", "--only", "desync", "--builds", "pr24-control", "--repeat", "4", "--match", "spawned_crate"])
        with mock.patch("sys.stdout", new_callable=io.StringIO) as output, mock.patch.object(run_tests.subprocess, "run", side_effect=AssertionError("a game was started")):
            code = run_tests.run_launch_plan(arguments)
        self.assertEqual(code, 2)
        self.assertIn("PREFLIGHT: the setup early stop 5 is not below the 4 planned attempts", output.getvalue())

    def test_the_launch_runner_reports_ok_for_the_planned_command(self):
        arguments = run_tests.parse_args(["--list", "--only", "desync", "--builds", "pr24-control", "pr24-fixed", "--repeat", "12", "--match", "spawned_crate", "launch_log_checks"])
        with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            code = run_tests.run_launch_plan(arguments)
        self.assertEqual(code, 0)
        self.assertIn("preflight: ok", output.getvalue())


if __name__ == "__main__":
    unittest.main()
