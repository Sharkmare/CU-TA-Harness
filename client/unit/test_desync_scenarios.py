import unittest

from casualtieslink import Game, desync
from tests import desync_scenarios as scenarios

from .fake_link import FakeFailure, FakeLink

PLAYER = {"x": 10.0, "y": 50.0}


def block_world(solid_below):
    state = {"blocks": {(PLAYER["x"], PLAYER["y"] - depth) for depth in solid_below}}

    def get(arguments):
        if arguments["target"] == "player":
            return dict(PLAYER)
        raise FakeFailure("unexpected get " + str(arguments))

    def invoke(arguments):
        position = arguments["args"][0]
        key = (position["x"], position["y"])
        if arguments["method"] == "GetBlock":
            return 3 if key in state["blocks"] else 0
        if arguments["method"] == "DamageBlock":
            state["blocks"].discard(key)
            return None
        raise FakeFailure("unexpected invoke " + str(arguments))

    return state, {"get": get, "invoke": invoke}


class BlockScenarioTests(unittest.TestCase):
    def test_the_first_solid_block_below_the_player_is_chosen(self):
        _, handlers = block_world([3, 5])
        with FakeLink(handlers) as link:
            context = scenarios.block_prepare(None, Game(link.port))
        self.assertEqual(context["position"], {"x": 10.0, "y": 47.0})

    def test_no_solid_block_is_a_clear_failure(self):
        _, handlers = block_world([])
        with FakeLink(handlers) as link:
            with self.assertRaises(AssertionError) as caught:
                scenarios.block_prepare(None, Game(link.port))
        self.assertIn("no solid block", str(caught.exception))

    def test_the_action_removes_the_block_and_the_read_sees_it(self):
        state, handlers = block_world([2])
        with FakeLink(handlers) as link:
            client = Game(link.port)
            context = scenarios.block_prepare(None, client)
            self.assertEqual(scenarios.block_read(client, context), 3)
            scenarios.block_act(client, context)
            self.assertEqual(scenarios.block_read(client, context), 0)
            damage = [call for call in link.calls if call[1].get("method") == "DamageBlock"][0][1]
        self.assertEqual(damage["types"], ["Vector2", "Single", "Boolean", "Boolean"])
        self.assertEqual(damage["target"], "world")

    def test_the_block_scenario_judges_removal_as_the_change(self):
        scenario = [item for item in scenarios.SCENARIOS if item.name == "block_removal_by_client"][0]
        self.assertTrue(scenario.changed(0, 3))
        self.assertFalse(scenario.changed(3, 3))
        self.assertFalse(scenario.changed(5, 3))


def item_world(items):
    def find(arguments):
        rows = [row for row in items if arguments["type"] == row["type"] and (not arguments.get("name") or arguments["name"] in row["name"])]
        return [{"object": {"id": row["id"], "name": row["name"]}, "position": row["position"]} for row in rows]

    def get(arguments):
        for row in items:
            if arguments["target"] == "id:%d" % row["id"]:
                if arguments["path"] == "transform.parent":
                    return row.get("parent")
                return row[arguments["path"]]
        raise FakeFailure("no such object " + arguments["target"])

    return {"find": find, "get": get}


class ItemHelperTests(unittest.TestCase):
    def test_rows_near_keeps_only_rows_within_the_radius(self):
        items = [
            {"id": 1, "type": "Item", "name": "bandage", "position": {"x": 10, "y": 50}},
            {"id": 2, "type": "Item", "name": "bandage", "position": {"x": 20, "y": 50}},
        ]
        with FakeLink(item_world(items)) as link:
            rows = scenarios.rows_near(Game(link.port), "Item", {"x": 10, "y": 50}, "bandage")
        self.assertEqual([row["object"]["id"] for row in rows], [1])

    def test_ground_count_ignores_held_items_that_have_a_parent(self):
        items = [
            {"id": 1, "type": "Item", "name": "bandage", "position": {"x": 10, "y": 50}},
            {"id": 2, "type": "Item", "name": "bandage", "position": {"x": 10.5, "y": 50}, "parent": {"$obj": "Transform"}},
        ]
        with FakeLink(item_world(items)) as link:
            count = scenarios.ground_count(Game(link.port), {"position": {"x": 10, "y": 50}, "name": "bandage"})
        self.assertEqual(count, 1)

    def test_waiting_for_rows_that_never_come_names_what_was_missing(self):
        with FakeLink(item_world([])) as link:
            with self.assertRaises(AssertionError) as caught:
                scenarios.wait_for_rows(Game(link.port), "Item", {"x": 1, "y": 2}, "bandage", timeout=0.2)
        self.assertIn("no Item named bandage", str(caught.exception))

    def test_corpse_health_reads_the_building_entity_and_none_when_it_is_gone(self):
        items = [{"id": 7, "type": "BuildingEntity", "name": "corpse(Clone)", "position": {"x": 1, "y": 1}, "health": 40.0}]
        context = {"position": {"x": 1, "y": 1}, "name": "corpse"}
        with FakeLink(item_world(items)) as link:
            self.assertEqual(scenarios.corpse_health(Game(link.port), context), 40.0)
        with FakeLink(item_world([])) as link:
            self.assertIsNone(scenarios.corpse_health(Game(link.port), context))

    def test_comparison_helpers_treat_missing_values_as_no_change(self):
        self.assertTrue(scenarios.fewer(0, 1))
        self.assertFalse(scenarios.fewer(None, 1))
        self.assertTrue(scenarios.more(2, 1))
        self.assertFalse(scenarios.more(1, None))


class ReadyUpTests(unittest.TestCase):
    def test_both_games_are_readied_through_the_lobby_gate(self):
        states = {"ready": False}

        def invoke(arguments):
            self.assertEqual((arguments["target"], arguments["method"], arguments["args"]), (scenarios.READY_TYPE, "SetLocalReady", [True]))
            states["ready"] = True

        def get(arguments):
            return states["ready"]

        with FakeLink({"invoke": invoke, "get": get}) as link:
            self.assertTrue(scenarios.ready_up([Game(link.port)], timeout=2.0, step=0.05))

    def test_a_build_without_the_gate_needs_no_ready_up(self):
        def invoke(arguments):
            raise FakeFailure("no type named 'Together.CharacterSelectWait'")

        with FakeLink({"invoke": invoke}) as link:
            self.assertTrue(scenarios.ready_up([Game(link.port)], timeout=2.0, step=0.05))

    def test_a_gate_that_never_confirms_times_out(self):
        with FakeLink({"invoke": lambda arguments: None, "get": lambda arguments: False}) as link:
            self.assertFalse(scenarios.ready_up([Game(link.port)], timeout=0.3, step=0.05))


class ScenarioListTests(unittest.TestCase):
    def test_every_scenario_is_complete_and_uniquely_named(self):
        names = [scenario.name for scenario in scenarios.SCENARIOS]
        self.assertEqual(len(names), len(set(names)))
        for scenario in scenarios.SCENARIOS:
            for member in (scenario.prepare, scenario.act, scenario.read, scenario.changed):
                self.assertTrue(callable(member), scenario.name)
            self.assertTrue(scenario.description, scenario.name)
            self.assertTrue(scenario.name.endswith("_by_client"), scenario.name)

    def test_the_audit_ranked_mutations_are_covered(self):
        names = {scenario.name for scenario in scenarios.SCENARIOS}
        for expected in ("block_removal_by_client", "corpse_damage_by_client", "door_open_by_client", "item_pickup_by_client", "item_drop_by_client", "container_load_by_client", "container_unload_by_client"):
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()
