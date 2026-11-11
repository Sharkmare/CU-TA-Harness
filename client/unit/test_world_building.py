import unittest
from unittest import mock

from casualtieslink import Game
from tests import world_building as world

from .fake_link import FakeFailure, FakeLink


def candidate(identifier, name="res: crate)", health=150.0, x=0.0, physics=True, animal=False, body="Dynamic", cant_hit=False, indestructible=False):
    return {"handle": "id:%d" % identifier, "id": identifier, "name": "SyncInfo(building, id: %d, %s" % (identifier, name), "position": {"x": x, "y": 0.0},
            "health": health, "startHealth": health, "cantHit": cant_hit, "indestructible": indestructible, "animal": animal, "rigidbodyType": body, "layer": 8, "physicsActive": physics}


class HostAttributes:
    def __init__(self, values, physics=True):
        self.values = values
        self.physics = physics

    def get(self, arguments):
        if arguments["path"] in self.values:
            return self.values[arguments["path"]]
        raise FakeFailure("no member " + arguments["path"])

    def invoke(self, arguments):
        if arguments["method"] == "BuildingHasActivePhysics":
            if self.physics is None:
                raise FakeFailure("no type named 'ScavMPBuildingSynchronizer'")
            return self.physics
        raise FakeFailure("unexpected " + str(arguments))


class DescribeTests(unittest.TestCase):
    row = {"object": {"id": 9, "name": "SyncInfo(building, id: 9, res: leadbush)"}, "position": {"x": 3.0, "y": 1.0}}

    def test_every_attribute_of_the_target_is_read_from_the_host(self):
        attributes = HostAttributes({"health": 120.0, "cantHit": False, "indestructible": False, "animal": True, "rb.bodyType": "Dynamic", "gameObject.layer": 8})
        with FakeLink({"get": attributes.get, "invoke": attributes.invoke}) as link:
            found = world.describe_candidate(Game(link.port), self.row)
        self.assertEqual((found["handle"], found["health"], found["cantHit"], found["indestructible"], found["animal"]), ("id:9", 120.0, False, False, True))
        self.assertEqual((found["rigidbodyType"], found["layer"], found["physicsActive"]), ("Dynamic", 8, True))

    def test_a_building_without_a_readable_health_is_dropped(self):
        with FakeLink({"get": HostAttributes({}).get, "invoke": HostAttributes({}).invoke}) as link:
            self.assertIsNone(world.describe_candidate(Game(link.port), self.row))

    def test_unreadable_extras_are_recorded_as_unknown_not_fatal(self):
        attributes = HostAttributes({"health": 150.0}, physics=None)
        with FakeLink({"get": attributes.get, "invoke": attributes.invoke}) as link:
            found = world.describe_candidate(Game(link.port), self.row)
        self.assertIsNone(found["rigidbodyType"])
        self.assertIsNone(found["physicsActive"])


class HostListTests(unittest.TestCase):
    def test_only_physics_active_buildings_are_described_and_the_whole_list_is_counted(self):
        rows = [{"object": {"id": index, "name": "b%d" % index}, "position": {"x": float(index), "y": 0.0}} for index in range(1, 7)]
        attributes = HostAttributes({"health": 150.0})

        def invoke(arguments):
            return arguments["args"][0] in ("id:2", "id:4")

        with FakeLink({"find": lambda arguments: rows, "get": attributes.get, "invoke": invoke}) as link:
            found, total = world.host_physics_candidates(Game(link.port), {"x": 0.0, "y": 0.0})
        self.assertEqual((total, [item["id"] for item in found]), (6, [2, 4]))

    def test_kinds_are_counted_by_resource_health_animal_and_body(self):
        pool = [candidate(1, "res: crate)"), candidate(2, "res: crate)"), candidate(3, "res: shadecrawler)", animal=True)]
        rows = world.kinds_summary(pool)
        self.assertEqual(rows[0], ["crate", 150, False, "Dynamic", 2])
        self.assertEqual(rows[1], ["shadecrawler", 150, True, "Dynamic", 1])


class UsableTests(unittest.TestCase):
    def test_each_exclusion_alone_makes_a_target_unusable(self):
        for item in (candidate(1, physics=False), candidate(2, physics=None), candidate(3, animal=True), candidate(4, body="Kinematic"),
                     candidate(5, "res: corpse(Clone))"), candidate(6, cant_hit=True), candidate(7, indestructible=True),
                     candidate(8, health=20.0), candidate(9, health=3000.0)):
            self.assertFalse(world.usable(item, skipped=set()), item["id"])
        self.assertTrue(world.usable(candidate(10), skipped=set()))

    def test_a_skipped_target_is_not_usable(self):
        self.assertFalse(world.usable(candidate(11), skipped={11}))

    def test_a_crate_with_a_thousand_health_is_in_range(self):
        self.assertTrue(world.usable(candidate(12, health=1000.0), skipped=set()))
        self.assertTrue(world.usable(candidate(13, health=2000.0), skipped=set()))

    def test_the_nearest_usable_one_is_chosen(self):
        found = world.choose([candidate(1, x=9.0), candidate(2, x=2.0), candidate(3, x=1.0, animal=True)], {"x": 0.0, "y": 0.0}, skipped=set(), uses=world.collections.Counter())
        self.assertEqual(found["id"], 2)

    def test_the_least_used_target_is_chosen_before_a_nearer_one(self):
        uses = world.collections.Counter({1: 2, 2: 1})
        found = world.choose([candidate(1, x=1.0), candidate(2, x=5.0), candidate(3, x=9.0)], {"x": 0.0, "y": 0.0}, skipped=set(), uses=uses)
        self.assertEqual(found["id"], 3)

    def test_four_targets_chosen_round_robin_cover_twelve_runs_evenly(self):
        pool = [candidate(index, x=float(index)) for index in range(1, 5)]
        uses = world.collections.Counter()
        for _ in range(12):
            uses[world.choose(pool, {"x": 0.0, "y": 0.0}, skipped=set(), uses=uses)["id"]] += 1
        self.assertEqual(sorted(uses.values()), [3, 3, 3, 3])

    def test_nothing_usable_gives_none(self):
        self.assertIsNone(world.choose([candidate(1, animal=True)], {"x": 0.0, "y": 0.0}, skipped=set(), uses=world.collections.Counter()))


class GateTests(unittest.TestCase):
    def test_fewer_than_the_minimum_fails_naming_the_kinds_seen(self):
        pool = [candidate(index) for index in range(1, world.MIN_CANDIDATES)] + [candidate(50, "res: shadecrawler)", animal=True)]
        with self.assertRaises(AssertionError) as caught:
            world.enough_candidates(pool)
        message = str(caught.exception)
        self.assertIn("only %d usable" % (world.MIN_CANDIDATES - 1), message)
        self.assertIn("shadecrawler", message)

    def test_the_minimum_passes(self):
        pool = [candidate(index) for index in range(1, world.MIN_CANDIDATES + 1)]
        self.assertEqual(len(world.enough_candidates(pool)), world.MIN_CANDIDATES)


class SetupTests(unittest.TestCase):
    def setUp(self):
        world.reset_launch_state()
        self.addCleanup(world.reset_launch_state)

    def patches(self, host_positions, client_positions, sees=True, health=150.0):
        host_iter = iter(host_positions)
        client_iter = iter(client_positions)
        last = {"host": host_positions[-1], "client": client_positions[-1]}

        def host_position(host, handle):
            return next(host_iter, last["host"])

        def player_position(client):
            return next(client_iter, last["client"])

        clock = iter(x * 0.25 for x in range(1, 100000))
        return [mock.patch.object(world.time, "sleep", lambda seconds: None), mock.patch.object(world.time, "time", lambda: next(clock)), mock.patch.object(world, "host_position", host_position),
                mock.patch.object(world.base, "player_position", player_position),
                mock.patch.object(world.base, "rows_near", lambda *args, **kwargs: [{"object": {"id": 5}}] if sees else []),
                mock.patch.object(world, "optional_get", lambda game, handle, path, nonpublic=False: health if path == "health" else None)]

    def run_setup(self, host_positions, client_positions, **keywords):
        patches = self.patches(host_positions, client_positions, **keywords)
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return world.try_setup(None, mock.Mock(), candidate(5))

    def test_a_client_that_arrives_beside_a_still_target_is_set_up(self):
        target, reason = self.run_setup([{"x": 0.0, "y": 0.0}], [{"x": -1.5, "y": 0.0}])
        self.assertIsNone(reason)
        self.assertEqual((target["clientHandle"], target["teleports"]), ("id:5", 1))
        self.assertLessEqual(target["distance"], world.MAX_START_DISTANCE)

    def test_a_client_that_never_gets_close_fails_with_both_positions(self):
        target, reason = self.run_setup([{"x": 0.0, "y": 0.0}], [{"x": -25.0, "y": 0.0}])
        self.assertIsNone(target)
        self.assertIn("never reached", reason)
        self.assertIn("-25.0", reason)

    def test_a_target_the_client_cannot_see_fails_the_setup(self):
        target, reason = self.run_setup([{"x": 0.0, "y": 0.0}], [{"x": -1.5, "y": 0.0}], sees=False)
        self.assertIsNone(target)
        self.assertIn("never reached", reason)

    def test_a_target_that_moves_more_than_half_a_unit_is_rejected_without_a_swing(self):
        positions = [{"x": 0.0, "y": 0.0}] * 3 + [{"x": 4.0, "y": 0.0}]
        target, reason = self.run_setup(positions, [{"x": -1.5, "y": 0.0}])
        self.assertIsNone(target)
        self.assertIn("moved", reason)

    def test_a_target_that_moves_less_than_half_a_unit_is_kept(self):
        positions = [{"x": 0.0, "y": 0.0}] * 3 + [{"x": 0.3, "y": 0.0}]
        target, reason = self.run_setup(positions, [{"x": -1.2, "y": 0.0}])
        self.assertIsNone(reason)
        self.assertEqual(target["position"], {"x": 0.3, "y": 0.0})


class ReuseTests(unittest.TestCase):
    def setUp(self):
        world.reset_launch_state()
        self.addCleanup(world.reset_launch_state)
        self.state = {"host": 150.0, "client": 150.0}
        self.host_game = mock.Mock()
        self.client_game = mock.Mock()
        self.host_game.set.side_effect = lambda handle, path, value: self.state.__setitem__("host", value)
        self.client_game.set.side_effect = lambda handle, path, value: self.state.__setitem__("client", value) if path == "health" else None
        clock = iter(x * 0.25 for x in range(1, 100000))

        def optional_get(game, handle, path, nonpublic=False):
            if path == "health":
                return self.state["host" if game is self.host_game else "client"]
            return None

        for patch in (mock.patch.object(world.time, "sleep", lambda seconds: None), mock.patch.object(world.time, "time", lambda: next(clock)),
                      mock.patch.object(world, "host_position", lambda host, handle: self.position),
                      mock.patch.object(world.base, "player_position", lambda client: {"x": self.position["x"] - 1.5, "y": 0.0}),
                      mock.patch.object(world.base, "rows_near", lambda *args, **kwargs: [{"object": {"id": 5}}]),
                      mock.patch.object(world, "optional_get", optional_get)):
            patch.start()
            self.addCleanup(patch.stop)
        self.position = {"x": 0.0, "y": 0.0}

    def setup_target(self):
        return world.try_setup(self.host_game, self.client_game, candidate(5, health=150.0))

    def test_a_depleted_target_is_reset_to_its_start_health_through_the_host(self):
        self.state["host"] = 40.0
        target, reason = self.setup_target()
        self.assertIsNone(reason)
        self.host_game.set.assert_called_once_with("id:5", "health", 150.0)
        self.assertEqual((target["hostHealthReset"], target["hostHealthBeforeReset"], target["startHealth"]), (True, 40.0, 150.0))

    def test_a_full_health_target_is_not_written_to(self):
        target, reason = self.setup_target()
        self.host_game.set.assert_not_called()
        self.assertFalse(target["hostHealthReset"])

    def test_a_host_that_refuses_the_reset_fails_the_setup(self):
        self.state["host"] = 40.0
        self.host_game.set.side_effect = lambda handle, path, value: None
        target, reason = self.setup_target()
        self.assertIsNone(target)
        self.assertIn("stayed at 40.0", reason)

    def test_a_client_whose_copy_is_still_depleted_is_aligned_and_it_is_recorded(self):
        self.state["client"] = 40.0
        target, reason = self.setup_target()
        self.client_game.set.assert_any_call("id:5", "health", 150.0)
        self.assertEqual((target["clientHealthReset"], target["clientHealthBeforeReset"]), (True, 40.0))

    def test_a_target_shoved_over_half_a_unit_from_its_first_position_is_skipped_for_the_launch(self):
        self.assertIsNone(self.setup_target()[1])
        self.position = {"x": 0.9, "y": 0.0}
        target, reason = self.setup_target()
        self.assertIsNone(target)
        self.assertIn("shoved", reason)
        self.assertIn(5, world.SKIPPED)

    def test_a_target_shoved_less_than_half_a_unit_is_reused(self):
        self.assertIsNone(self.setup_target()[1])
        self.position = {"x": 0.3, "y": 0.0}
        self.assertIsNone(self.setup_target()[1])
        self.assertNotIn(5, world.SKIPPED)


class ActTests(unittest.TestCase):
    def test_every_swing_records_the_displacement_of_the_target_and_the_probe(self):
        positions = iter([{"x": 0.0, "y": 0.0}, {"x": 0.2, "y": 0.0}, {"x": 0.2, "y": 0.0}, {"x": 0.2, "y": 0.0}] + [{"x": 0.2, "y": 0.0}] * 20)
        healths = {"host": 100.0, "client": 100.0}

        def optional_get(game, handle, path, nonpublic=False):
            return healths["host" if game is host else "client"]

        host, client = mock.Mock(), mock.Mock()
        client.get.return_value = 0.0

        def swing(game, aim):
            healths["host"] -= 19.0
            healths["client"] -= 19.0
            return True

        context = {"host": host, "hostHandle": "id:5", "clientHandle": "id:5", "position": {"x": 0.0, "y": 0.0}, "measurements": []}
        with mock.patch.object(world, "host_position", lambda game, handle: next(positions)), mock.patch.object(world, "optional_get", optional_get),                 mock.patch.object(world.hooks, "fire_one_swing", swing), mock.patch.object(world.time, "sleep", lambda seconds: None),                 mock.patch.object(world.evidence, "read_log", lambda which: ""), mock.patch.object(world, "collider_at", lambda game, point: {"name": "crate"}),                 mock.patch.object(world.base, "player_position", lambda game: {"x": -1.5, "y": 0.0}):
            world.act(client, context)
        first = context["measurements"][0]
        self.assertEqual((first["hostDelta"], first["clientDelta"], first["displacement"], first["colliderAtAim"]), (19.0, 19.0, 0.2, {"name": "crate"}))
        self.assertEqual(len(context["measurements"]), world.SWINGS)
        self.assertTrue(context["valid"])


class SwingHookTests(unittest.TestCase):
    def run_act(self, before_swing, reader=None):
        healths = {"host": 100.0, "client": 100.0}
        host, client = mock.Mock(), mock.Mock()
        client.get.return_value = 0.0

        def optional_get(game, handle, path, nonpublic=False):
            return healths["host" if game is host else "client"]

        def swing(game, aim):
            healths["host"] -= 19.0
            healths["client"] -= 19.0
            return True

        context = {"host": host, "hostHandle": "id:5", "clientHandle": "id:5", "position": {"x": 0.0, "y": 0.0}, "measurements": []}
        with mock.patch.object(world, "host_position", lambda game, handle: {"x": 0.0, "y": 0.0}), mock.patch.object(world, "optional_get", optional_get),                 mock.patch.object(world.hooks, "fire_one_swing", swing), mock.patch.object(world.time, "sleep", lambda seconds: None),                 mock.patch.object(world.evidence, "read_log", reader or (lambda which: "")), mock.patch.object(world, "collider_at", lambda game, point: {"name": "crate"}),                 mock.patch.object(world.base, "player_position", lambda game: {"x": -3.0, "y": 0.0}):
            world.act(client, context, before_swing=before_swing)
        return context

    def test_without_a_hook_every_swing_is_fired(self):
        self.assertEqual(len(self.run_act(None)["measurements"]), world.SWINGS)

    def test_the_hook_result_is_merged_into_each_swing_entry(self):
        context = self.run_act(lambda client, context, index, aim: {"band": {"reseats": index}})
        self.assertEqual([entry["band"]["reseats"] for entry in context["measurements"]], [1, 2, 3, 4, 5])

    def test_a_hook_that_returns_none_stops_before_that_swing_is_fired(self):
        context = self.run_act(lambda client, context, index, aim: None if index == 3 else {})
        self.assertEqual([entry["swing"] for entry in context["measurements"]], [1, 2])

    def test_hook_call_lines_of_the_swing_window_are_kept_apart_from_the_evidence_lines(self):
        hook = "[Info   :  Together] [KrokV5Opt] evidencebag hook call side=client collider=medcrate tag=Untagged dist=3.1 building=True cantHit=False phys=True local=True"
        calls = {"count": 0}

        def read_log(which):
            calls["count"] += 1
            return "" if calls["count"] <= 2 else "\n".join(["start", hook, ""])

        context = self.run_act(None, reader=read_log)
        first = context["measurements"][0]
        self.assertEqual(len(first["clientHookCalls"]), 1)
        self.assertIn("hook call side=client collider=medcrate", first["clientHookCalls"][0])
        self.assertEqual(len(first["hostHookCalls"]), 1)


class PrepareTests(unittest.TestCase):
    def setUp(self):
        world.reset_launch_state()
        self.addCleanup(world.reset_launch_state)

    def prepared(self, results, candidates=None):
        pool = candidates or [candidate(index, x=float(index)) for index in range(1, world.MIN_CANDIDATES + 3)]
        outcomes = iter(results)
        with mock.patch.object(world, "survey", lambda host, anchor: pool), mock.patch.object(world.base, "empty_the_hand", lambda client: None), \
                mock.patch.object(world.base, "player_position", lambda client: {"x": 0.0, "y": 0.0}), \
                mock.patch.object(world, "try_setup", lambda host, client, chosen: next(outcomes)):
            return world.prepare("host", "client")

    def good(self):
        return (dict(candidate(1), distance=1.5, clientHandle="id:1", teleports=1, healthBefore=150.0), None)

    def test_a_failed_pick_is_recorded_and_the_next_one_is_tried(self):
        context = self.prepared([(None, "first one moved"), self.good()])
        self.assertEqual(context["target"]["skippedPicks"], ["first one moved"])
        self.assertEqual(sum(world.USES.values()), 2)

    def test_every_pick_failing_raises_with_all_reasons(self):
        with self.assertRaises(AssertionError) as caught:
            self.prepared([(None, "reason %d" % index) for index in range(world.MAX_PICKS)])
        self.assertIn("reason 0", str(caught.exception))
        self.assertIn("reason %d" % (world.MAX_PICKS - 1), str(caught.exception))

    def test_a_launch_that_has_its_valid_runs_skips_the_rest(self):
        world.VALID_RUNS[0] = world.VALID_RUNS_WANTED
        with self.assertRaises(unittest.SkipTest):
            self.prepared([self.good()])

    def test_too_few_candidates_fail_before_any_setup(self):
        with self.assertRaises(AssertionError) as caught:
            self.prepared([], candidates=[candidate(1)])
        self.assertIn("SURVEY", str(caught.exception))


class CheckTests(unittest.TestCase):
    def setUp(self):
        world.reset_launch_state()
        self.addCleanup(world.reset_launch_state)

    def test_a_first_swing_that_changes_nothing_is_invalid_and_not_counted(self):
        issues = world.check({"target": {"name": "crate"}, "measurements": [{"hostDelta": 0.0, "clientDelta": 0.0}]})
        self.assertTrue(issues[0].startswith("INVALID: the first swing changed nothing (host 0.00, client 0.00); target crate"))
        self.assertEqual(world.VALID_RUNS[0], 0)

    def test_a_landed_first_swing_is_valid_and_counted_even_if_later_swings_miss(self):
        self.assertEqual(world.check({"measurements": [{"hostDelta": 19.3, "clientDelta": 19.3}, {"hostDelta": 0.0, "clientDelta": 0.0}]}), [])
        self.assertEqual(world.VALID_RUNS[0], 1)

    def test_no_swing_is_invalid(self):
        self.assertEqual(world.check({"measurements": []}), ["INVALID: no swing recorded"])


class ProbeTests(unittest.TestCase):
    def test_a_collider_name_is_recorded(self):
        with FakeLink({"invoke": lambda arguments: {"name": "crate"}}) as link:
            self.assertEqual(world.collider_at(Game(link.port), {"x": 1.0, "y": 2.0}), {"name": "crate"})

    def test_nothing_under_the_point_is_recorded_as_none(self):
        with FakeLink({"invoke": lambda arguments: None}) as link:
            self.assertEqual(world.collider_at(Game(link.port), {"x": 1.0, "y": 2.0}), {"name": None})

    def test_a_probe_that_cannot_run_is_recorded_not_fatal(self):
        def refuse(arguments):
            raise FakeFailure("no such overload")

        with FakeLink({"invoke": refuse}) as link:
            self.assertIn("no such overload", world.collider_at(Game(link.port), {"x": 1.0, "y": 2.0})["error"])


class GroupTests(unittest.TestCase):
    def report(self, physics, deltas, name="leadbush"):
        return {"target": {"physicsActive": physics, "name": name}, "measurements": [{"swing": index + 1, "hostDelta": delta, "clientDelta": delta} for index, delta in enumerate(deltas)]}

    def test_runs_are_split_into_physics_active_static_and_unknown(self):
        groups = world.group_by_physics([self.report(True, [19, 19, 0, 0, 0]), self.report(False, [19] * 5), self.report(None, [19, 0, 0, 0, 0])])
        self.assertEqual(sorted(groups), ["physics unknown", "physics-active", "static"])

    def test_landed_over_fired_swings_and_by_swing_index_are_counted_per_group(self):
        active = world.group_by_physics([self.report(True, [19, 19, 0, 0, 0]), self.report(True, [19, 0, 0, 0, 0])])["physics-active"]
        self.assertEqual((active["runs"], active["firedSwings"], active["landedSwings"]), (2, 10, 3))
        self.assertEqual(active["bySwing"], {1: [2, 2], 2: [1, 2], 3: [0, 2], 4: [0, 2], 5: [0, 2]})

    def test_invalid_runs_are_counted_apart_and_add_no_swings(self):
        static = world.group_by_physics([self.report(False, [0, 0, 0, 0, 0]), self.report(False, [19] * 5)])["static"]
        self.assertEqual((static["runs"], static["invalid"], static["firedSwings"], static["landedSwings"]), (2, 1, 5, 5))

    def test_the_scenario_is_in_the_evidence_group_and_selectable_alone(self):
        from tests import desync_scenarios as scenarios
        self.assertEqual(scenarios.matching_scenario_names(["worldhit_building"]), ["worldhit_building_by_client"])
        self.assertEqual(sorted(scenarios.counts_by_group(["worldhit_building"])), ["hook-evidence"])


if __name__ == "__main__":
    unittest.main()
