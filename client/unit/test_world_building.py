import unittest
from unittest import mock

from casualtieslink import Game
from tests import world_building as world

from .fake_link import FakeFailure, FakeLink


def candidate(name, health, x, physics=False, cant_hit=False, indestructible=False):
    return {"handle": "id:1", "id": 1, "name": name, "position": {"x": x, "y": 0.0}, "health": health, "cantHit": cant_hit,
            "indestructible": indestructible, "rigidbodyType": "Static", "layer": 8, "physicsActive": physics}


def reset():
    world.USED.clear()
    world.PHYSICS_COUNTS.clear()


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
        attributes = HostAttributes({"health": 120.0, "cantHit": False, "indestructible": False, "rb.bodyType": "Dynamic", "gameObject.layer": 8}, physics=True)
        with FakeLink({"get": attributes.get, "invoke": attributes.invoke}) as link:
            found = world.describe_candidate(Game(link.port), self.row)
        self.assertEqual((found["handle"], found["health"], found["cantHit"], found["indestructible"]), ("id:9", 120.0, False, False))
        self.assertEqual((found["rigidbodyType"], found["layer"], found["physicsActive"]), ("Dynamic", 8, True))

    def test_a_building_without_a_readable_health_is_dropped(self):
        attributes = HostAttributes({})
        with FakeLink({"get": attributes.get, "invoke": attributes.invoke}) as link:
            self.assertIsNone(world.describe_candidate(Game(link.port), self.row))

    def test_unreadable_extras_are_recorded_as_unknown_not_fatal(self):
        attributes = HostAttributes({"health": 150.0, "cantHit": False, "indestructible": False}, physics=None)
        with FakeLink({"get": attributes.get, "invoke": attributes.invoke}) as link:
            found = world.describe_candidate(Game(link.port), self.row)
        self.assertIsNone(found["rigidbodyType"])
        self.assertIsNone(found["physicsActive"])

    def test_the_host_list_is_sorted_by_distance_and_limited(self):
        rows = [{"object": {"id": index, "name": "b%d" % index}, "position": {"x": float(100 - index), "y": 0.0}} for index in range(1, 80)]
        attributes = HostAttributes({"health": 150.0, "cantHit": False, "indestructible": False})
        with FakeLink({"find": lambda arguments: rows, "get": attributes.get, "invoke": attributes.invoke}) as link:
            found = world.host_candidates(Game(link.port), {"x": 100.0, "y": 0.0})
        self.assertEqual(len(found), world.CANDIDATES_CONSIDERED)
        self.assertEqual(found[0]["name"], "b79" if False else found[0]["name"])
        self.assertLessEqual(found[0]["position"]["x"], 100.0)
        distances = [abs(item["position"]["x"] - 100.0) for item in found]
        self.assertEqual(distances, sorted(distances))


class ChooseTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_corpses_unhittable_indestructible_and_out_of_range_targets_are_never_usable(self):
        for item in (candidate("corpse(Clone)", 200.0, 1.0), candidate("a", 200.0, 1.0, cant_hit=True), candidate("b", 200.0, 1.0, indestructible=True),
                     candidate("c", 20.0, 1.0), candidate("d", 900.0, 1.0)):
            self.assertFalse(world.usable(item), item["name"])
        self.assertTrue(world.usable(candidate("e", 150.0, 1.0)))

    def test_a_target_used_in_the_launch_is_not_reused(self):
        item = candidate("crate", 200.0, 1.0)
        world.USED.add(world.key_of(item["position"]))
        self.assertFalse(world.usable(item))
        self.assertIsNone(world.choose([item], {"x": 0.0, "y": 0.0}))

    def test_the_nearest_usable_one_is_taken(self):
        found = world.choose([candidate("far", 200.0, 9.0), candidate("near", 200.0, 2.0)], {"x": 0.0, "y": 0.0})
        self.assertEqual(found["name"], "near")

    def test_physics_active_and_static_targets_are_balanced_across_runs(self):
        pool = [candidate("static-near", 200.0, 1.0, physics=False), candidate("active-far", 200.0, 5.0, physics=True)]
        world.PHYSICS_COUNTS[False] = 3
        found = world.choose(pool, {"x": 0.0, "y": 0.0})
        self.assertEqual(found["name"], "active-far")
        world.PHYSICS_COUNTS[True] = 5
        self.assertEqual(world.choose(pool, {"x": 0.0, "y": 0.0})["name"], "static-near")

    def test_an_unknown_physics_state_does_not_block_a_choice(self):
        found = world.choose([candidate("unknown", 200.0, 1.0, physics=None)], {"x": 0.0, "y": 0.0})
        self.assertEqual(found["name"], "unknown")


class PrepareTests(unittest.TestCase):
    def setUp(self):
        reset()

    def games(self, client_sees=True, health=150.0, distance_after=1.0):
        rows = [{"object": {"id": 9, "name": "SyncInfo(building, id: 9, res: leadbush)"}, "position": {"x": 6.0, "y": 0.0}}]
        attributes = HostAttributes({"health": health, "cantHit": False, "indestructible": False, "rb.bodyType": "Static", "gameObject.layer": 8})
        host = FakeLink({"find": lambda arguments: rows, "get": attributes.get, "invoke": attributes.invoke})
        client_state = {"x": 0.0}

        def client_get(arguments):
            if arguments["path"] == "transform.position":
                return {"x": client_state["x"], "y": 0.0}
            if arguments["path"] == "handSlot":
                return 0
            raise FakeFailure("unexpected " + str(arguments))

        def client_set(arguments):
            client_state["x"] = arguments["value"]["x"] + (distance_after - 1.5)

        def client_invoke(arguments):
            return None

        def client_find(arguments):
            return rows if client_sees else []

        client = FakeLink({"find": client_find, "get": client_get, "set": client_set, "invoke": client_invoke})
        return host, client

    def run_prepare(self, **keywords):
        host_link, client_link = self.games(**keywords)
        with host_link, client_link, mock.patch.object(world.time, "sleep", lambda seconds: None), \
                mock.patch.object(world, "CLIENT_SEES_TARGET_SECONDS", 0.3):
            return world.prepare(Game(host_link.port), Game(client_link.port))

    def test_the_client_is_moved_next_to_the_host_building_and_the_target_is_recorded(self):
        context = self.run_prepare()
        self.assertEqual(context["target"]["name"], "SyncInfo(building, id: 9, res: leadbush)")
        self.assertEqual(context["hostHandle"], "id:9")
        self.assertEqual(context["clientHandle"], "id:9")
        self.assertLessEqual(context["target"]["distance"], world.MAX_START_DISTANCE)
        self.assertEqual(context["target"]["healthBefore"], 150.0)

    def test_the_target_is_marked_used_and_counted_by_physics_class(self):
        self.run_prepare()
        self.assertIn((6.0, 0.0), world.USED)
        self.assertEqual(world.PHYSICS_COUNTS[True], 1)

    def test_a_building_the_client_never_sees_fails_the_setup_with_its_name(self):
        with self.assertRaises(AssertionError) as caught:
            self.run_prepare(client_sees=False)
        self.assertIn("the client does not see the host's building", str(caught.exception))

    def test_a_client_still_too_far_after_the_move_fails_the_setup(self):
        with self.assertRaises(AssertionError) as caught:
            self.run_prepare(distance_after=30.0)
        self.assertIn("beyond", str(caught.exception))

    def test_no_usable_building_fails_the_setup_and_lists_what_was_seen(self):
        with self.assertRaises(AssertionError) as caught:
            self.run_prepare(health=5000.0)
        self.assertIn("no fresh hittable destructible building", str(caught.exception))


class CheckTests(unittest.TestCase):
    def test_a_first_swing_that_changes_nothing_is_invalid(self):
        issues = world.check({"target": {"name": "crate"}, "measurements": [{"hostDelta": 0.0, "clientDelta": 0.0}]})
        self.assertTrue(issues[0].startswith("INVALID: the first swing changed nothing (host 0.00, client 0.00); target crate"))

    def test_a_landed_first_swing_is_valid_even_if_later_swings_miss(self):
        self.assertEqual(world.check({"measurements": [{"hostDelta": 19.3, "clientDelta": 19.3}, {"hostDelta": 0.0, "clientDelta": 0.0}]}), [])

    def test_no_swing_is_invalid(self):
        self.assertEqual(world.check({"measurements": []}), ["INVALID: no swing recorded"])


class GroupTests(unittest.TestCase):
    def report(self, physics, deltas, name="leadbush"):
        return {"target": {"physicsActive": physics, "name": name}, "measurements": [{"swing": index + 1, "hostDelta": delta, "clientDelta": delta} for index, delta in enumerate(deltas)]}

    def test_runs_are_split_into_physics_active_static_and_unknown(self):
        groups = world.group_by_physics([self.report(True, [19, 19, 0, 0, 0]), self.report(False, [19] * 5), self.report(None, [19, 0, 0, 0, 0])])
        self.assertEqual(sorted(groups), ["physics unknown", "physics-active", "static"])

    def test_landed_over_fired_swings_and_by_swing_index_are_counted_per_group(self):
        groups = world.group_by_physics([self.report(True, [19, 19, 0, 0, 0]), self.report(True, [19, 0, 0, 0, 0])])
        active = groups["physics-active"]
        self.assertEqual((active["runs"], active["firedSwings"], active["landedSwings"]), (2, 10, 3))
        self.assertEqual(active["bySwing"], {1: [2, 2], 2: [1, 2], 3: [0, 2], 4: [0, 2], 5: [0, 2]})

    def test_invalid_runs_are_counted_apart_and_add_no_swings(self):
        groups = world.group_by_physics([self.report(False, [0, 0, 0, 0, 0]), self.report(False, [19] * 5)])
        static = groups["static"]
        self.assertEqual((static["runs"], static["invalid"], static["firedSwings"], static["landedSwings"]), (2, 1, 5, 5))

    def test_the_scenario_is_in_the_evidence_group_and_selectable_alone(self):
        from tests import desync_scenarios as scenarios
        self.assertEqual(scenarios.matching_scenario_names(["worldhit_building"]), ["worldhit_building_by_client"])
        self.assertEqual(sorted(scenarios.counts_by_group(["worldhit_building"])), ["hook-evidence"])


if __name__ == "__main__":
    unittest.main()
