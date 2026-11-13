import unittest

from casualtieslink import Game
from scenarios import evidence_scenarios as evidence

from .fake_link import FakeFailure, FakeLink


def swing(index, host_delta, client_delta, client_lines=(), host_lines=(), fired=True):
    return {"swing": index, "fired": fired, "hostDelta": host_delta, "clientDelta": client_delta,
            "clientLines": list(client_lines), "hostLines": list(host_lines)}


class StageTests(unittest.TestCase):
    def test_a_swing_that_hurt_both_sides_is_landed(self):
        self.assertEqual(evidence.stage_of_miss(swing(1, 19.3, 19.3)), "landed")

    def test_no_client_damage_line_points_at_the_client_hit_loop(self):
        self.assertTrue(evidence.stage_of_miss(swing(2, 0.0, 0.0)).startswith("client: no DamageBuilding line"))

    def test_a_client_damage_line_without_a_host_decision_points_at_the_host(self):
        entry = swing(2, 0.0, 0.0, client_lines=["[evidencebag] damage client before=120 minus=19 local=True leadbush"])
        self.assertEqual(evidence.stage_of_miss(entry), "host: no 'hit server' decision line")

    def test_both_lines_present_but_no_damage_is_its_own_class(self):
        entry = swing(2, 0.0, 0.0, client_lines=["[evidencebag] damage client local=True"], host_lines=["[evidencebag] hit server range client=2"])
        self.assertEqual(evidence.stage_of_miss(entry), "host decided but no damage on either side")

    def test_a_swing_that_never_fired_is_named_as_such(self):
        self.assertEqual(evidence.stage_of_miss(swing(3, 0.0, 0.0, fired=False)), "no swing fired (cooldown never cleared)")

    def test_swings_are_grouped_by_stage_in_order_of_first_appearance(self):
        groups = evidence.summarise([swing(1, 19.0, 19.0), swing(2, 0.0, 0.0), swing(3, 19.0, 19.0), swing(4, 0.0, 0.0)])
        self.assertEqual(list(groups), ["landed", "client: no DamageBuilding line (hit loop or hook did not reach the building)"])
        self.assertEqual(list(groups.values()), [[1, 3], [2, 4]])


class LineTests(unittest.TestCase):
    def test_only_evidence_like_lines_are_kept_and_trimmed(self):
        lines = ["[Info] noise", "[Info] [evidencebag] hit send victim=1", "[Info] damage client before=1", "x" * 10, "[Info] hit server cooldown client=2"]
        self.assertEqual(evidence.evidence_lines(lines), ["[Info] [evidencebag] hit send victim=1", "[Info] damage client before=1", "[Info] hit server cooldown client=2"])

    def test_the_number_and_width_of_kept_lines_is_limited(self):
        lines = ["[evidencebag] " + "y" * 500] * 20
        kept = evidence.evidence_lines(lines)
        self.assertEqual(len(kept), evidence.LINE_LIMIT)
        self.assertTrue(all(len(line) <= evidence.LINE_WIDTH for line in kept))

    def test_exceptions_are_picked_out(self):
        self.assertEqual(evidence.exception_lines(["fine", "[Error  :  Together] boom", "System.NullReferenceException: x"]),
                         ["[Error  :  Together] boom", "System.NullReferenceException: x"])

    def test_new_lines_start_after_the_mark(self):
        self.assertEqual(evidence.new_lines(2, "a\nb\nc\nd\n"), ["c", "d"])

    def test_without_a_log_reader_the_log_is_empty(self):
        original = evidence.LOG_READER
        evidence.LOG_READER = None
        try:
            self.assertEqual(evidence.read_log("host"), "")
        finally:
            evidence.LOG_READER = original


class SpawnTests(unittest.TestCase):
    def world(self, health=120.0, host_has=True, client_has=True):
        rows = [{"object": {"id": 5, "name": "SyncInfo(building, id: 5, res: leadbush)"}, "position": {"x": 2.0, "y": 0.0}}]
        host = FakeLink({"find": lambda arguments: rows if host_has else [], "spawn": lambda arguments: {"ok": True},
                         "get": lambda arguments: health})
        client = FakeLink({"find": lambda arguments: rows if client_has else [], "get": lambda arguments: {"x": 0.0, "y": 0.0}})
        return host, client

    def test_the_host_spawns_the_building_and_both_games_must_show_it(self):
        host_link, client_link = self.world()
        original = evidence.base.APPEAR_TIMEOUT_SECONDS
        with host_link, client_link:
            host, client = Game(host_link.port), Game(client_link.port)
            host_row, client_row, handle, health = evidence.spawn_building(host, client, "leadbush")
            spawn_calls = [call for call in host_link.calls if call[0] == "spawn"]
        self.assertEqual((handle, health), ("id:5", 120.0))
        self.assertEqual(spawn_calls[0][1]["id"], "leadbush")
        self.assertEqual(spawn_calls[0][1]["pickup"], False)

    def test_a_spawned_building_with_the_wrong_health_is_a_setup_failure(self):
        host_link, client_link = self.world(health=5000.0)
        with host_link, client_link:
            with self.assertRaises(AssertionError) as caught:
                evidence.spawn_building(Game(host_link.port), Game(client_link.port), "leadbush")
        self.assertIn("outside", str(caught.exception))

    def test_the_resources_cycle_so_every_kind_gets_runs(self):
        seen = [next(evidence.RESOURCE_CYCLE) for _ in range(len(evidence.BUILDING_RESOURCES) * 2)]
        self.assertEqual(set(seen), set(evidence.BUILDING_RESOURCES))


class GateTests(unittest.TestCase):
    def test_the_probe_state_is_read_from_the_config_entry_value(self):
        seen = []

        def get(arguments):
            seen.append(arguments)
            return True

        with FakeLink({"get": get}) as link:
            self.assertTrue(evidence.find_the_bug_enabled(Game(link.port)))
        self.assertEqual((seen[0]["target"], seen[0]["path"], seen[0]["nonpublic"]), ("static:KrokV5Optimization.FindTheBug", "Enabled.Value", True))

    def test_an_unreadable_probe_is_unknown_not_off(self):
        def broken(arguments):
            raise FakeFailure("no type named 'KrokV5Optimization.FindTheBug'")

        with FakeLink({"get": broken}) as link:
            self.assertIsNone(evidence.find_the_bug_enabled(Game(link.port)))

    def test_the_evidence_group_is_verbose_probe_configured_and_gated(self):
        from live import test_desync
        self.assertIn("--mp-verbose", test_desync.GROUP_HOST_ARGUMENTS["hook-evidence"])
        self.assertIn("--mp-verbose", test_desync.GROUP_CLIENT_ARGUMENTS["hook-evidence"])
        self.assertIn("hook-evidence", test_desync.PROBE_GROUPS)
        self.assertIn("hook-evidence", test_desync.EVIDENCE_GROUPS)

    def test_the_gate_refuses_when_the_probe_is_off_and_lists_the_config(self):
        from live import test_desync
        class Games:
            host_copy = client_copy = "nowhere"
        original = test_desync.GAMES
        test_desync.GAMES = Games()
        try:
            with FakeLink({"get": lambda arguments: False}) as link:
                with self.assertRaises(AssertionError) as caught:
                    test_desync.require_find_the_bug(Game(link.port), Game(link.port))
        finally:
            test_desync.GAMES = original
        self.assertIn("FindTheBug is not on at startup", str(caught.exception))
        self.assertIn("no config folder", str(caught.exception))


class CheckTests(unittest.TestCase):
    def test_a_run_without_swings_is_invalid_and_one_with_swings_is_not(self):
        self.assertEqual(evidence.evidence_check({"measurements": []}), ["INVALID: no swing recorded"])
        self.assertEqual(evidence.evidence_check({"measurements": [swing(1, 0.0, 0.0)]}), [])

    def test_the_scenario_is_selectable_by_one_fragment(self):
        from scenarios import desync_scenarios as scenarios
        self.assertEqual(scenarios.matching_scenario_names(["evidence_building"]), ["evidence_building_hit_by_client"])
        self.assertEqual(sorted(scenarios.counts_by_group(["evidence_building"])), ["hook-evidence"])


if __name__ == "__main__":
    unittest.main()
