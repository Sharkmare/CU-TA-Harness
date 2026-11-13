import os
import tempfile
import unittest
from unittest import mock

from casualtieslink import desync, instances, launchplan
from tests import desync_scenarios as scenarios
from tests import hook_scenarios, regression_scenarios, spawned_crates, test_desync, v2_suite


class SuiteTests(unittest.TestCase):
    def test_the_mining_check_runs_in_the_same_startup_group_as_the_crate_scenario(self):
        self.assertEqual(v2_suite.MINING.group, spawned_crates.GROUP)
        self.assertEqual(sorted(scenarios.counts_by_group(["spawned_crate", "v2check"])), ["hook-evidence"])

    def test_the_originals_keep_their_own_groups_and_names(self):
        self.assertEqual(hook_scenarios.HOOK_MINING.group, "hook-check")
        self.assertEqual(hook_scenarios.HOOK_MINING.name, "hookcheck_dig_cracks")

    def test_the_copies_share_the_original_steps(self):
        self.assertIs(v2_suite.MINING.prepare, hook_scenarios.HOOK_MINING.prepare)
        self.assertIs(v2_suite.MINING.hit, hook_scenarios.HOOK_MINING.hit)

    def test_the_selection_fragments_pick_the_crate_and_the_mining_scenario(self):
        self.assertEqual(sorted(scenarios.matching_scenario_names(["spawned_crate", "v2check"])), ["spawned_crate_hit_by_client", "v2check_dig_cracks"])

    def test_the_crate_keeps_all_attempts_and_the_mining_follows_the_profile_repeat(self):
        profiles = launchplan.parse_profiles(["100:0@5"])
        crate = desync.expand_runs([scenario for scenario in scenarios.SCENARIOS if scenario.name == "spawned_crate_hit_by_client"], profiles, 8)
        mining = desync.expand_runs([v2_suite.MINING], profiles, 8)
        self.assertEqual(len(crate), 8)
        self.assertEqual((len(mining), {run.profile.delay_ms for run in mining}), (5, {100.0}))

    def test_a_scenario_without_a_cap_is_not_limited(self):
        plain = scenarios.SCENARIOS[0]
        self.assertIsNone(getattr(plain, "max_repeat", None))
        self.assertEqual(len(desync.expand_runs([plain], [launchplan.DIRECT], 7)), 7)

    def test_the_evidence_group_turns_the_pvp_rule_on_for_both_games(self):
        for arguments in (test_desync.GROUP_HOST_ARGUMENTS, test_desync.GROUP_CLIENT_ARGUMENTS):
            self.assertIn("--mp-setrule PVP 1", " ".join(arguments["hook-evidence"]))
            self.assertIn("--mp-verbose", arguments["hook-evidence"])

    def test_the_launch_plan_for_the_v2_command_is_one_launch(self):
        counts = scenarios.counts_by_group(["pvp_banded", "spawned_crate", "v2check", "launch_log_checks"])
        launches = launchplan.plan_launches(["pr24-3d060fe-plain"], sorted(counts), launchplan.parse_profiles(["100:0@5"]), 8, ["pvp_banded", "spawned_crate", "v2check", "launch_log_checks"])
        self.assertEqual(len(launches), 1)
        self.assertEqual(launches[0].startup_group, "hook-evidence")



class RawHitTests(unittest.TestCase):
    def test_the_raw_first_hit_is_stored_so_its_keys_can_be_read_later(self):
        client = mock.Mock()
        client.call.return_value = {"count": 2, "items": [{"point": {"x": 1.0}, "fraction": 0.2, "colliderId": 77}, {"colliderId": 78}]}
        cast = spawned_crates.mimic_cast(client, {"x": 0.0, "y": 0.0}, {"x": 3.0, "y": 0.0})
        self.assertEqual(cast["method"], "RaycastAll")
        self.assertIn("colliderId", cast["rawFirstHit"])
        self.assertIn("fraction", cast["rawFirstHit"])

    def test_the_raw_hit_is_cut_to_a_fixed_width(self):
        client = mock.Mock()
        client.call.return_value = [{"blob": "x" * 5000}]
        cast = spawned_crates.mimic_cast(client, {"x": 0.0, "y": 0.0}, {"x": 3.0, "y": 0.0})
        self.assertEqual(len(cast["rawFirstHit"]), spawned_crates.RAW_HIT_WIDTH)

    def test_an_empty_cast_has_no_raw_hit_and_a_failed_cast_none(self):
        client = mock.Mock()
        client.call.return_value = []
        self.assertIsNone(spawned_crates.mimic_cast(client, {"x": 0.0, "y": 0.0}, {"x": 3.0, "y": 0.0})["rawFirstHit"])
        client.call.side_effect = RuntimeError("down")
        self.assertIsNone(spawned_crates.mimic_cast(client, {"x": 0.0, "y": 0.0}, {"x": 3.0, "y": 0.0})["rawFirstHit"])


if __name__ == "__main__":
    unittest.main()
