import os
import unittest
from unittest import mock

from casualtieslink import desync, launchplan
from tests import corpse_banded as corpse
from tests import desync_scenarios as scenarios
from tests import spawned_crates as crates
from tests import test_desync


def flags(cant_hit, physics=False, body="Static"):
    return {"cantHit": cant_hit, "indestructible": False, "bodyType": body, "physicsActive": physics}


class SetupHarness(unittest.TestCase):
    def setUp(self):
        corpse.reset_launch_state()
        crates.reset_launch_state()
        self.addCleanup(corpse.reset_launch_state)
        self.addCleanup(crates.reset_launch_state)
        self.host = mock.Mock()
        self.client = mock.Mock()
        self.characters = {"client": 2, "host": 0, "clientBodyOnHost": 0}
        self.host_flags = flags(True)
        self.client_flags = flags(False)
        self.target = {"handle": "id:5", "clientHandle": "id:-5", "position": {"x": 3.0, "y": 0.0}, "health": 80.0}
        self.spawn_error = None
        self.spawned = []

        def spawn_object(host, client, object_id, min_health):
            self.spawned.append((object_id, min_health))
            if self.spawn_error:
                raise self.spawn_error
            return dict(self.target)

        def copy_flags(game, handle):
            return self.host_flags if game is self.host else self.client_flags

        for patch in (mock.patch.object(corpse.crates, "spawn_object", spawn_object), mock.patch.object(corpse, "copy_flags", copy_flags),
                      mock.patch.object(corpse, "characters_in_play", lambda host, client: dict(self.characters)),
                      mock.patch.object(corpse.base, "empty_the_hand", lambda client: None)):
            patch.start()
            self.addCleanup(patch.stop)


class PrepareTests(SetupHarness):
    def test_a_dune_client_and_an_experiment_host_with_the_premise_flags_are_set_up(self):
        context = corpse.prepare(self.host, self.client)
        self.assertEqual(self.spawned, [("corpse", corpse.MIN_CORPSE_HEALTH)])
        self.assertEqual((context["hostHandle"], context["clientHandle"]), ("id:5", "id:-5"))
        self.assertEqual(context["target"]["characters"], self.characters)
        self.assertEqual((context["target"]["hostFlags"]["cantHit"], context["target"]["clientFlags"]["cantHit"]), (True, False))

    def test_a_client_that_is_not_dune_is_a_setup_failure_with_its_category_and_the_values_seen(self):
        self.characters = {"client": 0, "host": 0, "clientBodyOnHost": 0}
        with self.assertRaises(crates.SetupFailure) as caught:
            corpse.prepare(self.host, self.client)
        self.assertEqual(caught.exception.category, "client-not-dune")
        self.assertIn("charType 0", str(caught.exception))
        self.assertEqual(self.spawned, [])
        self.assertEqual(dict(crates.STATE["reasons"]), {"client-not-dune": 1})

    def test_a_dune_host_is_a_setup_failure_because_the_mixed_case_is_not_set_up(self):
        self.characters = {"client": 2, "host": 2, "clientBodyOnHost": 2}
        with self.assertRaises(crates.SetupFailure) as caught:
            corpse.prepare(self.host, self.client)
        self.assertEqual(caught.exception.category, "host-is-dune")

    def test_an_unreadable_client_character_is_a_setup_failure_not_a_pass(self):
        self.characters = {"client": {"error": "no member charType"}, "host": 0, "clientBodyOnHost": None}
        with self.assertRaises(crates.SetupFailure):
            corpse.prepare(self.host, self.client)

    def test_a_corpse_whose_host_copy_is_hittable_is_a_premise_failure_and_the_corpse_is_destroyed(self):
        self.host_flags = flags(False)
        with self.assertRaises(crates.SetupFailure) as caught:
            corpse.prepare(self.host, self.client)
        self.assertEqual(caught.exception.category, "premise-not-met")
        self.host.set.assert_called_once_with("id:5", "health", 0)

    def test_a_corpse_whose_client_copy_is_still_unhittable_is_a_premise_failure(self):
        self.client_flags = flags(True)
        with self.assertRaises(crates.SetupFailure) as caught:
            corpse.prepare(self.host, self.client)
        self.assertEqual(caught.exception.category, "premise-not-met")

    def test_an_unreadable_cant_hit_flag_is_a_premise_failure(self):
        self.client_flags = flags(None)
        with self.assertRaises(crates.SetupFailure):
            corpse.prepare(self.host, self.client)

    def test_a_spawn_failure_is_counted_and_keeps_its_own_category(self):
        self.spawn_error = crates.SetupFailure("no-new-crate", "the host lists no new corpse")
        with self.assertRaises(crates.SetupFailure) as caught:
            corpse.prepare(self.host, self.client)
        self.assertEqual(caught.exception.category, "no-new-crate")
        self.assertEqual(corpse.STATE["setup_failed"], 1)

    def test_five_setup_failures_with_no_valid_run_stop_the_launch(self):
        self.characters = {"client": 0, "host": 0, "clientBodyOnHost": 0}
        for _ in range(corpse.STOP_AFTER_SETUP_FAILURES):
            with self.assertRaises(crates.SetupFailure):
                corpse.prepare(self.host, self.client)
        with self.assertRaises(unittest.SkipTest) as caught:
            corpse.prepare(self.host, self.client)
        self.assertIn("client-not-dune", str(caught.exception))

    def test_six_valid_runs_end_the_launch(self):
        corpse.STATE["valid"] = corpse.VALID_RUNS_WANTED
        with self.assertRaises(unittest.SkipTest):
            corpse.prepare(self.host, self.client)


class SwingTests(unittest.TestCase):
    def setUp(self):
        corpse.reset_launch_state()
        crates.reset_launch_state()
        self.addCleanup(corpse.reset_launch_state)
        self.addCleanup(crates.reset_launch_state)

    def test_every_swing_adds_the_flags_of_both_copies_to_the_crate_style_geometry(self):
        host, client = mock.Mock(), mock.Mock()
        context = {"host": host, "hostHandle": "id:5", "clientHandle": "id:-5"}
        seen = []

        def copy_flags(game, handle):
            seen.append(handle)
            return flags(game is host, physics=game is host)

        with mock.patch.object(corpse.crates, "before_swing", lambda game, context, index, aim: {"band": {"ok": True}, "geometry": {}, "physics": {}}), \
                mock.patch.object(corpse, "copy_flags", copy_flags):
            extra = corpse.before_swing(client, context, 1, {"x": 1.0, "y": 1.0})
        self.assertEqual((extra["flags"]["host"]["cantHit"], extra["flags"]["client"]["cantHit"]), (True, False))
        self.assertEqual(seen, ["id:5", "id:-5"])

    def test_a_band_failure_stops_the_swing(self):
        with mock.patch.object(corpse.crates, "before_swing", lambda game, context, index, aim: None):
            self.assertIsNone(corpse.before_swing(mock.Mock(), {"host": mock.Mock(), "hostHandle": "id:5", "clientHandle": "id:-5"}, 3, {"x": 1.0, "y": 1.0}))

    def test_the_corpse_is_destroyed_after_the_swings_even_when_they_raise(self):
        host = mock.Mock()

        def explode(client, context, before_swing=None):
            raise RuntimeError("link lost")

        with mock.patch.object(corpse.world, "act", explode), self.assertRaises(RuntimeError):
            corpse.act(mock.Mock(), {"host": host, "hostHandle": "id:5"})
        host.set.assert_called_once_with("id:5", "health", 0)

    def test_the_shared_swing_loop_gets_the_corpse_hook(self):
        seen = {}
        with mock.patch.object(corpse.world, "act", lambda client, context, before_swing=None: seen.update(hook=before_swing)):
            corpse.act(mock.Mock(), {"host": mock.Mock(), "hostHandle": "id:5"})
        self.assertIs(seen["hook"], corpse.before_swing)


class CheckTests(unittest.TestCase):
    def setUp(self):
        corpse.reset_launch_state()
        crates.reset_launch_state()
        self.addCleanup(corpse.reset_launch_state)
        self.addCleanup(crates.reset_launch_state)

    def entry(self, index, host, client):
        return {"swing": index, "hostDelta": host, "clientDelta": client}

    def test_each_outcome_is_named_from_the_two_deltas(self):
        self.assertEqual([corpse.outcome_of(self.entry(1, 19.3, 19.3)), corpse.outcome_of(self.entry(1, 0.0, 19.3)), corpse.outcome_of(self.entry(1, 19.3, 0.0)),
                          corpse.outcome_of(self.entry(1, 0.0, 0.0))], ["both", "client-only", "host-only", "neither"])

    def test_five_swings_that_damage_both_sides_once_pass_and_count_as_a_valid_run(self):
        self.assertEqual(corpse.check({"measurements": [self.entry(index, 19.33, 19.33) for index in range(1, 6)]}), [])
        self.assertEqual(corpse.STATE["valid"], 1)

    def test_client_only_damage_is_reported_as_an_issue_naming_the_outcomes_and_still_counts_as_a_valid_run(self):
        issues = corpse.check({"measurements": [self.entry(index, 0.0, 19.33) for index in range(1, 6)]})
        self.assertTrue(issues[0].startswith("corpse damage per swing: ['client-only'"))
        self.assertTrue(any("changed nothing on the host" in issue for issue in issues))
        self.assertEqual(corpse.STATE["valid"], 1)

    def test_a_band_failure_is_invalid_and_not_a_valid_run(self):
        issues = corpse.check({"bandFailure": {"swing": 2, "distances": [3.9, 3.8]}, "measurements": [self.entry(1, 19.33, 19.33)]})
        self.assertTrue(issues[0].startswith("INVALID: the client could not be brought into the 2.5 to 3.2 band before swing 2"))
        self.assertEqual((corpse.STATE["valid"], corpse.STATE["setup_failed"]), (0, 1))

    def test_no_swing_is_invalid(self):
        self.assertEqual(corpse.check({"measurements": []}), ["INVALID: no swing recorded"])
        self.assertEqual(corpse.STATE["valid"], 0)


class CharacterTests(unittest.TestCase):
    def test_the_characters_are_read_from_the_client_the_host_and_the_clients_body_on_the_host(self):
        host, client = mock.Mock(), mock.Mock()
        host.get.side_effect = lambda handle, path, depth=0: {"player": 0, "id:7": 0}[handle]
        client.get.side_effect = lambda handle, path, depth=0: 2
        with mock.patch.object(corpse.base, "body_handle_by_name", lambda game, name: "id:7"):
            self.assertEqual(corpse.characters_in_play(host, client), {"client": 2, "host": 0, "clientBodyOnHost": 0})

    def test_a_missing_client_body_on_the_host_is_none_not_fatal(self):
        host, client = mock.Mock(), mock.Mock()
        host.get.return_value = 0
        client.get.return_value = 2
        with mock.patch.object(corpse.base, "body_handle_by_name", mock.Mock(side_effect=AssertionError("no body"))):
            self.assertIsNone(corpse.characters_in_play(host, client)["clientBodyOnHost"])

    def test_an_unreadable_character_is_recorded_with_its_error(self):
        game = mock.Mock()
        game.get.side_effect = RuntimeError("no member charType")
        self.assertIn("no member charType", corpse.read_character(game, "player")["error"])


class WiringTests(unittest.TestCase):
    def test_both_scenarios_are_in_the_dune_group_and_run_pvp_first(self):
        self.assertEqual(sorted(scenarios.counts_by_group(["dune1_", "dune2_"])), ["hook-dune"])
        self.assertEqual(sorted(scenarios.matching_scenario_names(["dune1_", "dune2_"])), ["dune1_pvp_banded_by_client", "dune2_corpse_hit_by_client"])
        names = sorted(["test_00_launch_log_checks", "test_dune2_corpse_hit_by_client_r1", "test_dune1_pvp_banded_by_client_r1"])
        self.assertEqual(names[1], "test_dune1_pvp_banded_by_client_r1")

    def test_the_dune_group_starts_the_client_as_dune_with_the_pvp_rule_and_the_probe(self):
        self.assertEqual(test_desync.GROUP_CLIENT_CHARACTER, {"hook-dune": 2})
        for arguments in (test_desync.GROUP_HOST_ARGUMENTS, test_desync.GROUP_CLIENT_ARGUMENTS):
            self.assertIn("--mp-setrule PVP 1", " ".join(arguments["hook-dune"]))
            self.assertIn("--mp-verbose", arguments["hook-dune"])
        self.assertIn("hook-dune", test_desync.PROBE_GROUPS)
        self.assertIn("hook-dune", test_desync.EVIDENCE_GROUPS)

    def test_the_generated_dune_class_carries_the_character_and_the_other_classes_do_not(self):
        classes = {name: item for name, item in vars(test_desync).items() if name.startswith("Desync_") and isinstance(item, type)}
        dune = [item for name, item in classes.items() if name.endswith("hook_dune")]
        self.assertEqual([item.client_character for item in dune], [2])
        self.assertTrue(all(item.client_character is None for name, item in classes.items() if not name.endswith("hook_dune")))

    def test_the_character_is_set_through_the_client_link_before_the_world(self):
        game = mock.Mock()
        test_desync.choose_character(2)(game)
        game.set.assert_called_once_with("static:PreRunScript", "characterSelected", 2)
        self.assertIsNone(test_desync.choose_character(None))

    def test_the_pvp_run_count_follows_the_environment_and_defaults_to_three(self):
        with mock.patch.dict(os.environ, {corpse.PVP_RUNS_VARIABLE: "1"}):
            self.assertEqual(corpse.pvp_runs(), 1)
            self.assertEqual(corpse.pvp_clone().max_repeat, 1)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(corpse.PVP_RUNS_VARIABLE, None)
            self.assertEqual(corpse.pvp_runs(), 3)

    def test_the_pvp_copy_shares_the_banded_steps_and_the_original_stays_in_the_evidence_group(self):
        original = next(item for item in scenarios.SCENARIOS if item.name == "pvp_banded_by_client")
        clone = next(item for item in scenarios.SCENARIOS if item.name == "dune1_pvp_banded_by_client")
        self.assertEqual((original.group, clone.group), ("hook-evidence", "hook-dune"))
        self.assertIs(clone.act, original.act)
        self.assertIs(clone.prepare, original.prepare)
        self.assertIs(clone.check, original.check)

    def test_the_pvp_runs_three_times_by_default_and_the_corpse_uses_every_attempt(self):
        profiles = [launchplan.DIRECT]
        runs = {item.name: len(desync.expand_runs([item], profiles, 8)) for item in scenarios.SCENARIOS if item.name.startswith("dune")}
        self.assertEqual(runs["dune2_corpse_hit_by_client"], 8)
        self.assertEqual(runs["dune1_pvp_banded_by_client"], 3)


class PreflightTests(unittest.TestCase):
    def test_the_planned_command_passes(self):
        self.assertEqual(corpse.preflight(["dune1_", "dune2_"], 8), [])

    def test_too_few_attempts_for_the_corpse_are_refused(self):
        problems = corpse.preflight(["dune2_"], 4)
        self.assertEqual(len(problems), 2)

    def test_a_launch_without_the_dune_scenarios_is_not_checked(self):
        self.assertEqual(corpse.preflight(["spawned_crate"], 1), [])

    def test_the_stage_builds_for_both_launches_exist_in_the_stage_table(self):
        from casualtieslink import instances
        for build in ("upstream-baseline", "upstream-fixed-final"):
            self.assertIn(build, instances.stage_directory_by_build())
            self.assertIn(build, desync.KNOWN_BUILDS)


if __name__ == "__main__":
    unittest.main()
