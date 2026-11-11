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


class RealPathHelperTests(unittest.TestCase):
    def test_the_crack_counter_comes_from_get_block_damage_at_the_block_cell(self):
        seen = []

        def invoke(arguments):
            seen.append(arguments)
            return {"$type": "BlockDamage", "damage": 42.456} if arguments["args"][0] == {"x": 110, "y": 3} else None

        world = {"halfWidth": 100, "halfHeight": 50}
        with FakeLink({"invoke": invoke, "get": lambda arguments: world[arguments["path"]]}) as link:
            game = Game(link.port)
            self.assertEqual(scenarios.crack_counter(game, {"position": {"x": 10.5, "y": -47.0}}), 42.46)
            self.assertEqual(scenarios.crack_counter(game, {"position": {"x": 0.0, "y": 0.0}}), 0.0)
            self.assertEqual(scenarios.crack_counter(game, {"position": {"x": 0.0, "y": 0.0}, "cell": {"x": 110, "y": 3}}), 42.46)
        self.assertEqual(seen[0]["method"], "GetBlockDamage")
        self.assertEqual(seen[0]["types"], ["Vector2Int"])

    def test_every_scenario_group_has_launch_arguments(self):
        from tests import test_desync
        for scenario in scenarios.SCENARIOS:
            self.assertIn(scenario.group, test_desync.GROUP_CLIENT_ARGUMENTS)

    def test_the_corpse_group_makes_the_client_a_dune(self):
        from tests import test_desync
        self.assertEqual(test_desync.GROUP_CLIENT_ARGUMENTS["mixed-characters"], ["--mp-setchar", "2"])

    def test_scenarios_with_a_fuse_sample_after_it_burns(self):
        scenario = [item for item in scenarios.SCENARIOS if item.name == "S14_grenade_crater_by_client"][0]
        self.assertGreaterEqual(min(scenario.offsets), 5.0)

    def test_the_comparison_helpers(self):
        self.assertTrue(scenarios.gone_or_lower(None, 10))
        self.assertTrue(scenarios.gone_or_lower(3, 10))
        self.assertFalse(scenarios.gone_or_lower(10, 10))
        self.assertTrue(scenarios.lower_sum(5, 6))


class DigLoopTests(unittest.TestCase):
    def test_the_client_swings_until_the_block_is_gone_aiming_at_it(self):
        state = {"swings": 0, "look": []}

        def invoke(arguments):
            if arguments["method"] == "GetBlock":
                return 0 if state["swings"] >= 2 else 8
            if arguments["method"] == "UseItemInHand":
                state["swings"] += 1
                state["look"].append((arguments["sets"][0]["path"], arguments["sets"][0]["value"]))
            return None

        def set_value(arguments):
            state["look"].append((arguments["path"], arguments["value"]))

        original = scenarios.SWING_PAUSE_SECONDS
        scenarios.SWING_PAUSE_SECONDS = 0.0
        try:
            with FakeLink({"invoke": invoke, "set": set_value}) as link:
                scenarios.dig_act(Game(link.port), {"position": {"x": 3.0, "y": 4.0}})
        finally:
            scenarios.SWING_PAUSE_SECONDS = original
        self.assertEqual(state["swings"], 2)
        self.assertEqual(state["look"][0], ("targetLookPos", {"x": 3.0, "y": 4.0, "z": 0.0}))

    def test_the_client_gives_up_after_the_swing_limit(self):
        state = {"swings": 0}

        def invoke(arguments):
            if arguments["method"] == "GetBlock":
                return 8
            state["swings"] += 1

        original = scenarios.SWING_PAUSE_SECONDS
        scenarios.SWING_PAUSE_SECONDS = 0.0
        try:
            with FakeLink({"invoke": invoke, "set": lambda arguments: None}) as link:
                scenarios.dig_act(Game(link.port), {"position": {"x": 0.0, "y": 0.0}})
        finally:
            scenarios.SWING_PAUSE_SECONDS = original
        self.assertEqual(state["swings"], scenarios.MAX_SWINGS)


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
        for expected in ("S1_block_dig_by_client", "S2_block_crack_by_client", "S3_corpse_punch_by_client", "S5_building_break_by_client", "S6_door_open_by_client", "S7_item_pickup_by_client", "S7_item_drop_by_client", "S7_item_throw_by_client", "S9_eat_by_client", "S14_grenade_crater_by_client", "container_load_by_client", "container_unload_by_client", "block_removal_by_client"):
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()
