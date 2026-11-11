import math
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


class MixedHandMiningTests(unittest.TestCase):
    def test_the_dune_client_group_has_its_own_held_click_scenario(self):
        found = [item for item in scenarios.SERIES_SCENARIOS if item.group == scenarios.MIXED_HAND_MINING_GROUP]
        self.assertEqual(sorted(item.name for item in found), ["dune_client_aim_circle_mining", "dune_client_hold_mining"])
        self.assertTrue(found[0].network_sensitive)

    def test_the_group_starts_a_dune_client_with_verbose_logging_and_the_probe_config(self):
        from tests import test_desync
        self.assertEqual(test_desync.GROUP_CLIENT_ARGUMENTS["mixed-hand-mining"], ["--mp-setchar", "2", "--mp-verbose"])
        self.assertEqual(test_desync.GROUP_HOST_ARGUMENTS["mixed-hand-mining"], ["--mp-verbose"])
        self.assertIn("mixed-hand-mining", test_desync.PROBE_GROUPS)

    def test_the_plain_hold_match_would_plan_both_hand_mining_groups(self):
        counts = scenarios.counts_by_group(["hold_mining"])
        self.assertEqual(sorted(counts), ["hand-mining", "mixed-hand-mining"])
        self.assertEqual(sorted(scenarios.counts_by_group(["dune_client"])), ["mixed-hand-mining"])

    def test_each_match_fragment_selects_exactly_one_mining_scenario(self):
        for fragment, expected in (("hold_mining_cracks", "hold_mining_cracks"), ("aim_circle_mining_cracks", "aim_circle_mining_cracks"),
                                   ("dune_client_hold_mining", "dune_client_hold_mining"), ("dune_client_aim_circle", "dune_client_aim_circle_mining")):
            self.assertEqual(scenarios.matching_scenario_names([fragment]), [expected], fragment)


class FakeWorld:
    def __init__(self, blocks, replicate_to=None, never_replicate=False):
        self.blocks = dict(blocks)
        self.replicate_to = replicate_to or []
        self.never_replicate = never_replicate
        self.damage = {}
        self.player = {"x": 10.2, "y": 50.7}
        self.sets = []

    def get(self, arguments):
        if arguments["target"] == "world":
            return {"halfWidth": 100, "halfHeight": 20}[arguments["path"]]
        if arguments["target"] == "player" and arguments["path"] == scenarios.BODY_PATH:
            return dict(self.player)
        raise FakeFailure("unexpected get " + str(arguments))

    def invoke(self, arguments):
        method = arguments["method"]
        if method == "GetBlock":
            position = arguments["args"][0]
            return self.blocks.get((int(position["x"] + 100), int(position["y"] + 20)), 0)
        if method == "SetBlock":
            x, y, block = arguments["args"]
            self.sets.append((x, y, block))
            self.blocks[(x, y)] = block
            if not self.never_replicate:
                for other in self.replicate_to:
                    other.blocks[(x, y)] = block
            return None
        if method == "GetBlockDamage":
            cell = arguments["args"][0]
            counter = self.damage.get((cell["x"], cell["y"]))
            return {"$type": "BlockDamage", "damage": counter} if counter is not None else None
        if method == "GetBlockInfo":
            return {"health": {8: 60.0, 9: 150.0, 6: 5000.0}.get(arguments["args"][0], 1.0)}
        raise FakeFailure("unexpected invoke " + str(arguments))

    def handlers(self):
        return {"get": self.get, "invoke": self.invoke}


class FreshBlockTests(unittest.TestCase):
    def games(self, host_world, client_world):
        return FakeLink(host_world.handlers()), FakeLink(client_world.handlers())

    def test_the_host_places_a_block_next_to_the_client_and_both_games_see_it(self):
        client_world = FakeWorld({})
        host_world = FakeWorld({}, replicate_to=[client_world])
        host_link, client_link = self.games(host_world, client_world)
        with host_link, client_link:
            host, client = Game(host_link.port), Game(client_link.port)
            cell, centre, block, health, placed = scenarios.place_fresh_block(host, client)
        self.assertEqual((cell, block, health, placed), ({"x": 112, "y": 70}, 8, 60.0, True))
        self.assertEqual(centre, {"x": 12.5, "y": 50.5})
        self.assertEqual(host_world.sets, [(112, 70, 8)])
        self.assertEqual(client_world.blocks[(112, 70)], 8)

    def test_an_occupied_column_is_skipped_for_the_next_one(self):
        client_world = FakeWorld({})
        host_world = FakeWorld({(112, 70): 6}, replicate_to=[client_world])
        host_link, client_link = self.games(host_world, client_world)
        with host_link, client_link:
            cell = scenarios.place_fresh_block(Game(host_link.port), Game(client_link.port))[0]
        self.assertEqual(cell, {"x": 108, "y": 70})

    def test_when_every_column_is_taken_the_failure_names_them(self):
        taken = {(110 + column, 70): 6 for column in scenarios.FRESH_BLOCK_COLUMNS}
        client_world = FakeWorld({})
        host_world = FakeWorld(taken, replicate_to=[client_world])
        host_link, client_link = self.games(host_world, client_world)
        with host_link, client_link:
            with self.assertRaises(AssertionError) as caught:
                scenarios.place_fresh_block(Game(host_link.port), Game(client_link.port))
        self.assertIn("no free cell", str(caught.exception))

    def test_a_block_that_never_reaches_the_client_fails_the_setup(self):
        client_world = FakeWorld({})
        host_world = FakeWorld({}, replicate_to=[client_world], never_replicate=True)
        host_link, client_link = self.games(host_world, client_world)
        original = scenarios.FRESH_BLOCK_VERIFY_SECONDS
        try:
            with host_link, client_link:
                with self.assertRaises(AssertionError) as caught:
                    scenarios.wait_for_block_on_both(Game(host_link.port), Game(client_link.port), {"x": 12.5, "y": 50.5}, 8, timeout=0.5)
        finally:
            scenarios.FRESH_BLOCK_VERIFY_SECONDS = original
        self.assertIn("is not on both games", str(caught.exception))

    def test_cleanup_removes_a_block_the_host_placed_and_leaves_air_alone(self):
        world = FakeWorld({(112, 70): 8})
        with FakeLink(world.handlers()) as link:
            host = Game(link.port)
            context = {"position": {"x": 12.5, "y": 50.5}, "cell": {"x": 112, "y": 70}, "placedByHost": True}
            scenarios.remove_fresh_block(host, None, context)
            self.assertEqual(world.blocks[(112, 70)], 0)
            world.sets.clear()
            scenarios.remove_fresh_block(host, None, context)
        self.assertEqual(world.sets, [])

    def test_a_block_not_placed_by_the_harness_is_never_removed(self):
        world = FakeWorld({(112, 70): 8})
        with FakeLink(world.handlers()) as link:
            scenarios.remove_fresh_block(Game(link.port), None, {"position": {"x": 12.5, "y": 50.5}, "cell": {"x": 112, "y": 70}, "placedByHost": False})
        self.assertEqual(world.blocks[(112, 70)], 8)

    def test_the_cell_centre_follows_the_world_half_size(self):
        world = FakeWorld({})
        with FakeLink(world.handlers()) as link:
            self.assertEqual(scenarios.world_centre_of_cell(Game(link.port), {"x": 112, "y": 70}), {"x": 12.5, "y": 50.5})


class AimTests(unittest.TestCase):
    centre = {"x": 5.0, "y": 7.0}

    def test_a_fixed_aim_stays_on_the_centre(self):
        self.assertEqual(scenarios.aim_point("fixed", self.centre, 1.7), self.centre)

    def test_the_circle_stays_at_its_radius_and_comes_back_after_a_period(self):
        for elapsed in (0.0, 0.4, 1.1, 2.9):
            point = scenarios.aim_point("circle", self.centre, elapsed)
            self.assertAlmostEqual(math.hypot(point["x"] - 5.0, point["y"] - 7.0), scenarios.AIM_CIRCLE_RADIUS, places=6)
        start = scenarios.aim_point("circle", self.centre, 0.0)
        again = scenarios.aim_point("circle", self.centre, scenarios.AIM_CIRCLE_PERIOD_SECONDS)
        self.assertAlmostEqual(start["x"], again["x"], places=6)
        self.assertNotEqual(scenarios.aim_point("circle", self.centre, 0.0), scenarios.aim_point("circle", self.centre, 0.75))

    def test_the_drift_moves_one_block_sideways_and_back_without_leaving_the_row(self):
        xs = [scenarios.aim_point("drift", self.centre, step * 0.1)["x"] for step in range(0, 41)]
        self.assertAlmostEqual(max(xs) - min(xs), scenarios.AIM_DRIFT_BLOCKS, places=6)
        self.assertTrue(all(scenarios.aim_point("drift", self.centre, step * 0.3)["y"] == 7.0 for step in range(20)))

    def test_the_near_x_aim_stays_within_the_sway_of_the_characters_x_at_the_blocks_height(self):
        for step in range(0, 60):
            point = scenarios.aim_point("near_x", self.centre, step * 0.13, anchor_x=12.34)
            self.assertLessEqual(abs(point["x"] - 12.34), scenarios.AIM_NEAR_X_SWAY + 1e-9)
            self.assertEqual(point["y"], 7.0)
        xs = [scenarios.aim_point("near_x", self.centre, step * 0.1, anchor_x=0.0)["x"] for step in range(21)]
        self.assertGreater(max(xs) - min(xs), 0.5)

    def test_the_near_x_aim_follows_a_walking_character(self):
        first = scenarios.aim_point("near_x", self.centre, 0.0, anchor_x=1.0)
        later = scenarios.aim_point("near_x", self.centre, 0.0, anchor_x=3.0)
        self.assertEqual(later["x"] - first["x"], 2.0)

    def test_the_near_x_aim_needs_the_characters_x(self):
        with self.assertRaises(ValueError):
            scenarios.aim_point("near_x", self.centre, 0.0)

    def test_an_unknown_pattern_is_refused(self):
        with self.assertRaises(ValueError):
            scenarios.aim_point("spiral", self.centre, 0.0)


class TileReadTests(unittest.TestCase):
    def test_the_read_lists_the_counter_of_the_block_and_each_cracked_neighbour(self):
        world = FakeWorld({(112, 70): 8})
        world.damage = {(112, 70): 19.33, (113, 70): 5.0, (111, 71): 2.0}
        with FakeLink(world.handlers()) as link:
            state = scenarios.tile_read(Game(link.port), {"position": {"x": 12.5, "y": 50.5}, "cell": {"x": 112, "y": 70}})
        self.assertEqual(state[0], 8)
        self.assertEqual(state[1], 19.33)
        self.assertEqual(state[2], {"0,0": 19.33, "1,0": 5.0, "-1,1": 2.0})


class AimedHoldTests(unittest.TestCase):
    def test_each_call_sends_the_current_aim_and_a_swing_counts_only_when_the_cooldown_rose(self):
        state = {"cooldown": 0.0, "sets": []}

        def get(arguments):
            if arguments["path"] == "attackCooldown":
                return state["cooldown"]
            if arguments["path"] == "isRight":
                return True
            if arguments["path"] == scenarios.BODY_PATH:
                return {"x": 1.0, "y": 2.0}
            raise FakeFailure("unexpected " + str(arguments))

        def invoke(arguments):
            state["sets"].append(arguments["sets"][0]["value"])
            if state["fire"]:
                state["cooldown"] = 0.2

        host_world = FakeWorld({})
        with FakeLink({"get": get, "invoke": invoke}) as client_link, FakeLink(host_world.handlers()) as host_link:
            host_world.get = lambda arguments: {"x": 1.1, "y": 2.0}
            host_link.handlers["get"] = host_world.get
            client = Game(client_link.port)
            context = {"aimPattern": "circle", "position": {"x": 5.0, "y": 7.0}, "firstCall": None, "swingLog": [],
                       "hostGame": Game(host_link.port), "hostBodyHandle": "id:1"}
            state["fire"] = False
            self.assertFalse(scenarios.aimed_hold_hit(client, context))
            state["fire"] = True
            self.assertTrue(scenarios.aimed_hold_hit(client, context))
        self.assertEqual(len(context["swingLog"]), 1)
        self.assertEqual(context["swingLog"][0]["gap"], 0.1)
        self.assertEqual(len(state["sets"]), 2)
        self.assertNotEqual(state["sets"][0], {"x": 5.0, "y": 7.0, "z": 0.0})


class LayoutAndWalkTests(unittest.TestCase):
    def games(self, blocks):
        client_world = FakeWorld({})
        host_world = FakeWorld(blocks, replicate_to=[client_world])
        return host_world, client_world

    def place(self, layout, blocks=None):
        host_world, client_world = self.games(blocks or {})
        with FakeLink(host_world.handlers()) as host_link, FakeLink(client_world.handlers()) as client_link:
            cell = scenarios.place_fresh_block(Game(host_link.port), Game(client_link.port), layout)[0]
        return cell

    def test_the_layouts_put_the_block_above_below_beside_and_next_to_the_client(self):
        self.assertEqual(self.place("above"), {"x": 110, "y": 73})
        self.assertEqual(self.place("below"), {"x": 110, "y": 68})
        self.assertEqual(self.place("adjacent"), {"x": 111, "y": 70})
        self.assertEqual(self.place("side"), {"x": 112, "y": 70})

    def test_an_occupied_below_cell_falls_back_to_the_next_one(self):
        self.assertEqual(self.place("below", {(110, 68): 6}), {"x": 110, "y": 67})

    def test_every_layout_has_cells_and_none_is_the_players_own_cell(self):
        for layout, cells in scenarios.FRESH_BLOCK_LAYOUTS.items():
            self.assertTrue(cells, layout)
            self.assertNotIn((0, 0), cells, layout)

    def test_walking_taps_alternate_keys_and_respect_the_period(self):
        taps = []

        def record(arguments):
            taps.append((arguments["key"], arguments["frames"]))

        with FakeLink({"input": record}) as link:
            client = Game(link.port)
            context = {"lastWalk": 0.0, "walkIndex": 0}
            scenarios.walk_a_little(client, context)
            scenarios.walk_a_little(client, context)
            context["lastWalk"] -= scenarios.WALK_PERIOD_SECONDS
            scenarios.walk_a_little(client, context)
        self.assertEqual(taps, [("A", scenarios.WALK_TAP_FRAMES), ("D", scenarios.WALK_TAP_FRAMES)])

    def test_the_new_aim_scenarios_are_selectable_one_at_a_time(self):
        for fragment in ("aim_vertical_up_mining_cracks", "aim_vertical_down_mining_cracks", "aim_cross_mining_cracks", "aim_walk_mining_cracks", "aim_circle_mining_cracks"):
            self.assertEqual(scenarios.matching_scenario_names([fragment]), [fragment], fragment)


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
