import unittest
from unittest import mock

from tests import spawned_crates as crates

ANCHOR = {"x": 10.0, "y": 5.0}


def crate_row(identifier, x, y=5.0):
    return {"object": {"id": identifier, "name": "SyncInfo(building, id: %d, res: medcrate)" % identifier}, "position": {"x": x, "y": y}}


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
        clock = iter(x * 0.25 for x in range(1, 100000))
        self.described = {"handle": "id:7", "id": 7, "name": "SyncInfo(building, id: 7, res: medcrate)", "position": {"x": 11.0, "y": 5.0}, "health": 1000.0,
                          "cantHit": False, "indestructible": False, "animal": False, "rigidbodyType": "Dynamic", "layer": 8, "physicsActive": True}
        for patch in (mock.patch.object(crates.time, "sleep", lambda seconds: None), mock.patch.object(crates.time, "time", lambda: next(clock)),
                      mock.patch.object(crates.base, "player_position", lambda game: dict(self.player)),
                      mock.patch.object(crates.base, "rows_near", self.rows_near),
                      mock.patch.object(crates.world, "host_position", lambda host, handle: dict(self.crate_at)),
                      mock.patch.object(crates.world, "describe_candidate", lambda host, row: dict(self.described, position=row["position"]))):
            patch.start()
            self.addCleanup(patch.stop)

    def host_call(self, command, **arguments):
        if command == "spawn":
            self.spawn_arguments = arguments
            self.host_rows = [crate_row(7, 11.0)]
        return None

    def rows_near(self, game, component, position, name=None, radius=3.0):
        rows = self.host_rows if game is self.host else self.client_rows
        return [row for row in rows if crates.base.distance(row["position"], position) <= radius]

    def test_the_crate_is_spawned_at_the_fixed_offset_from_the_client(self):
        target = crates.spawn_crate(self.host, self.client)
        arguments = self.spawn_arguments
        self.assertEqual((arguments["id"], arguments["x"], arguments["y"], arguments["pickup"]), ("medcrate", 11.0, 5.0, False))
        self.assertEqual((target["handle"], target["clientHandle"], target["startHealth"], target["spawnOffset"]), ("id:7", "id:7", 1000.0, 1.0))
        self.assertTrue(target["physicsActive"])

    def test_a_crate_that_was_already_there_is_not_taken_for_the_new_one(self):
        self.host_rows = [crate_row(3, 11.7)]

        def spawn(command, **arguments):
            if command == "spawn":
                self.host_rows = [crate_row(3, 11.7), crate_row(7, 11.0)]

        self.host.call.side_effect = spawn
        self.assertEqual(crates.spawn_crate(self.host, self.client)["id"], 7)

    def test_no_new_crate_on_the_host_fails_the_setup(self):
        self.host.call.side_effect = lambda command, **arguments: None
        with self.assertRaises(AssertionError) as caught:
            crates.spawn_crate(self.host, self.client)
        self.assertIn("lists no new medcrate", str(caught.exception))

    def test_a_crate_the_client_does_not_list_at_the_same_position_fails_the_setup(self):
        self.client_rows = [crate_row(7, 13.0)]
        with self.assertRaises(AssertionError) as caught:
            crates.spawn_crate(self.host, self.client)
        self.assertIn("client does not list", str(caught.exception))

    def place_crate_away(self, distance):
        self.crate_at = {"x": ANCHOR["x"] + distance, "y": 5.0}
        self.client_rows = [crate_row(7, ANCHOR["x"] + distance)]
        self.host_rows = []

        def spawn(command, **arguments):
            if command == "spawn":
                self.spawn_arguments = arguments
                self.host_rows = [crate_row(7, ANCHOR["x"] + distance)]

        self.host.call.side_effect = spawn

    def teleport_follows_set(self):
        def set_position(target, path, value):
            self.player = {"x": value["x"], "y": value["y"]}

        self.client.set.side_effect = set_position

    def test_a_crate_inside_three_needs_no_reseat(self):
        self.place_crate_away(2.9)
        target = crates.spawn_crate(self.host, self.client)
        self.assertEqual((target["reseated"], target["reseatTries"], target["distanceBeforeReseat"]), (False, 0, 2.9))
        self.client.set.assert_not_called()

    def test_the_distances_seen_in_the_baseline_launch_are_re_seated_to_within_two(self):
        for distance in (3.01, 3.05, 3.11, 3.21, 3.31, 3.39, 3.52):
            with self.subTest(distance=distance):
                crates.reset_launch_state()
                self.player = dict(ANCHOR)
                self.place_crate_away(distance)
                self.teleport_follows_set()
                target = crates.spawn_crate(self.host, self.client)
                self.assertTrue(target["reseated"])
                self.assertEqual(target["reseatTries"], 1)
                self.assertEqual(target["distanceBeforeReseat"], round(distance, 2))
                self.assertLessEqual(target["distance"], crates.RESEAT_DISTANCE)

    def test_a_client_displaced_far_from_the_anchor_is_put_back_before_the_spawn(self):
        crates.spawn_crate(self.host, self.client)
        self.player = {"x": ANCHOR["x"] + 11.79, "y": 5.0}
        self.teleport_follows_set()
        self.host_rows = []
        target = crates.spawn_crate(self.host, self.client)
        self.assertFalse(target["reseated"])
        self.assertLessEqual(target["distance"], crates.world.MAX_START_DISTANCE)

    def test_a_client_that_cannot_be_moved_fails_after_the_set_number_of_re_seats_with_its_category(self):
        self.place_crate_away(3.52)
        with self.assertRaises(crates.SetupFailure) as caught:
            crates.spawn_crate(self.host, self.client)
        self.assertEqual(caught.exception.category, "client-too-far-after-reseat")
        self.assertEqual(self.client.set.call_count, crates.RESEAT_TRIES)
        self.assertIn("3.52", str(caught.exception))

    def test_the_client_is_put_back_at_the_first_anchor_before_the_second_spawn(self):
        crates.spawn_crate(self.host, self.client)
        self.player = {"x": 14.0, "y": 5.0}
        self.host_rows = []
        crates.spawn_crate(self.host, self.client)
        self.client.set.assert_called_with("player", crates.base.BODY_PATH, {"x": 10.0, "y": 5.0, "z": 0.0})
        self.assertEqual(self.spawn_arguments["x"], 11.0)

    def test_a_crate_below_the_health_floor_fails_the_setup(self):
        self.described["health"] = 20.0
        with self.assertRaises(AssertionError):
            crates.spawn_crate(self.host, self.client)


class RunControlTests(unittest.TestCase):
    def setUp(self):
        crates.reset_launch_state()
        self.addCleanup(crates.reset_launch_state)

    def landed(self):
        return {"measurements": [{"hostDelta": 19.3, "clientDelta": 19.3}]}

    def missed(self):
        return {"measurements": [{"hostDelta": 0.0, "clientDelta": 0.0}], "target": {"name": "medcrate"}}

    def prepare_with(self, outcome):
        with mock.patch.object(crates.base, "empty_the_hand", lambda client: None), mock.patch.object(crates, "spawn_crate", outcome):
            return crates.prepare("host", "client")

    def test_three_runs_without_a_landed_first_swing_stop_the_launch(self):
        for _ in range(3):
            self.assertTrue(crates.check(self.missed()))
        with self.assertRaises(unittest.SkipTest) as caught:
            self.prepare_with(lambda host, client: self.fail("must not spawn"))
        self.assertIn("looks unhittable", str(caught.exception))

    def test_two_failed_runs_do_not_stop_it(self):
        crates.check(self.missed())
        crates.check(self.missed())
        target = dict(handle="id:7", clientHandle="id:7", position={"x": 1.0, "y": 1.0})
        self.assertEqual(self.prepare_with(lambda host, client: target)["hostHandle"], "id:7")

    def test_setup_failures_count_toward_the_stop(self):
        def fail(host, client):
            raise crates.SetupFailure("no-new-crate", "no new crate")

        for _ in range(crates.STOP_AFTER_SETUP_FAILURES):
            with self.assertRaises(crates.SetupFailure):
                self.prepare_with(fail)
        with self.assertRaises(unittest.SkipTest) as caught:
            self.prepare_with(fail)
        self.assertIn("first 5 attempts all failed setup", str(caught.exception))
        self.assertIn("no-new-crate", str(caught.exception))

    def test_four_setup_failures_do_not_stop_it(self):
        def fail(host, client):
            raise crates.SetupFailure("no-new-crate", "no new crate")

        for _ in range(crates.STOP_AFTER_SETUP_FAILURES - 1):
            with self.assertRaises(crates.SetupFailure):
                self.prepare_with(fail)
        target = dict(handle="id:7", clientHandle="id:7", position={"x": 1.0, "y": 1.0})
        self.assertIsNotNone(self.prepare_with(lambda host, client: target))

    def test_failure_reasons_are_grouped_and_written_to_the_failure_file(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(crates, "FAILURE_DIRECTORY", directory):
            crates.record_failure("no-new-crate", "first")
            crates.record_failure("no-new-crate", "second")
            crates.record_failure("client-too-far-after-reseat", "third")
            with open(directory + "/" + crates.FAILURE_FILE, encoding="utf-8") as handle:
                written = json.load(handle)
        self.assertEqual(written["reasons"], {"no-new-crate": 2, "client-too-far-after-reseat": 1})
        self.assertEqual([item["message"] for item in written["attempts"]], ["first", "second", "third"])

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

    def test_the_spawned_crate_is_destroyed_through_the_host_after_the_swings(self):
        host = mock.Mock()
        with mock.patch.object(crates.world, "act", lambda client, context: None):
            crates.act("client", {"host": host, "hostHandle": "id:7"})
        host.set.assert_called_once_with("id:7", "health", 0)

    def test_the_crate_is_destroyed_even_when_the_swings_raise(self):
        host = mock.Mock()

        def explode(client, context):
            raise RuntimeError("link lost")

        with mock.patch.object(crates.world, "act", explode):
            with self.assertRaises(RuntimeError):
                crates.act("client", {"host": host, "hostHandle": "id:7"})
        host.set.assert_called_once()

    def test_the_scenario_is_selectable_alone_in_the_evidence_group(self):
        from tests import desync_scenarios as scenarios
        self.assertEqual(scenarios.matching_scenario_names(["spawned_crate"]), ["spawned_crate_hit_by_client"])
        self.assertEqual(sorted(scenarios.counts_by_group(["spawned_crate"])), ["hook-evidence"])


if __name__ == "__main__":
    unittest.main()
