import unittest

from casualtieslink import launchplan
from casualtieslink.launchplan import NetworkProfile

COUNTS = {"default": {"plain": 10, "network": 0}, "hand-mining": {"plain": 0, "network": 2}, "mixed-characters": {"plain": 1, "network": 0}}


class ParseProfileTests(unittest.TestCase):
    def test_delay_jitter_loss_and_reorder_parse_in_order(self):
        profile = launchplan.parse_profile("250:100:0.1:0.2")
        self.assertEqual(profile.key(), (250.0, 100.0, 0.1, 0.2))

    def test_missing_parts_are_zero(self):
        self.assertEqual(launchplan.parse_profile("100").key(), (100.0, 0.0, 0.0, 0.0))
        self.assertEqual(launchplan.parse_profile("100::0.5").key(), (100.0, 0.0, 0.5, 0.0))

    def test_direct_and_empty_mean_zero_delay(self):
        self.assertEqual(launchplan.parse_profile("direct").key(), launchplan.DIRECT.key())
        self.assertEqual(launchplan.parse_profile(None).key(), launchplan.DIRECT.key())

    def test_bad_values_are_refused(self):
        for bad in ("-1:0", "fast", "100:0:2", "100:0:0:-1"):
            with self.assertRaises(ValueError, msg=bad):
                launchplan.parse_profile(bad)

    def test_profiles_keep_their_order_and_lose_duplicates(self):
        profiles = launchplan.parse_profiles(["100:0", "100:60", "100:0", "250:100"])
        self.assertEqual([p.label() for p in profiles], ["d100-j0", "d100-j60", "d250-j100"])

    def test_no_profile_given_means_one_direct_profile(self):
        self.assertEqual([p.label() for p in launchplan.parse_profiles(None)], ["d0-j0"])

    def test_spec_round_trips(self):
        profile = NetworkProfile(250, 100, 0.1, 0.2)
        self.assertEqual(launchplan.parse_profile(profile.spec()).key(), profile.key())

    def test_labels_name_loss_and_reorder_only_when_set(self):
        self.assertEqual(NetworkProfile(100, 60, 0.05, 0.1).label(), "d100-j60-l0.05-r0.1")
        self.assertEqual(NetworkProfile(100, 60).label(), "d100-j60")


class ProfileRepeatTests(unittest.TestCase):
    def test_stall_fields_follow_the_four_network_fields_and_round_trip(self):
        profile = launchplan.parse_profile("100:75:0:0:800:300:400:100:10:1")
        self.assertTrue(profile.stall_active())
        self.assertEqual(profile.as_dict()["stall_interval_ms"], 800.0)
        self.assertEqual((profile.as_dict()["stall_gap_ms"], profile.as_dict()["stall_to_client"]), (10.0, 1.0))
        self.assertEqual(launchplan.parse_profile(profile.spec()).key(), profile.key())
        self.assertEqual(profile.label(), "d100-j75-s800x400g10c")

    def test_a_profile_without_a_stall_keeps_its_four_value_key_and_switches_the_stall_off(self):
        profile = launchplan.parse_profile("100:60")
        self.assertEqual(profile.key(), (100.0, 60.0, 0.0, 0.0))
        self.assertFalse(profile.stall_active())
        self.assertEqual(profile.as_dict()["stall_interval_ms"], 0.0)
        self.assertEqual(profile.label(), "d100-j60")

    def test_bad_stall_values_are_refused(self):
        for text in ("0:0:0:0:100:200:50:0", "0:0:0:0:100:0:50:60", "0:0:0:0:-1:0:50:0", "0:0:0:0:100:0:50:0:0:2"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    launchplan.parse_profile(text)

    def test_a_profile_repeat_is_read_and_round_trips(self):
        profile = launchplan.parse_profile("100:60@20")
        self.assertEqual((profile.key(), profile.repeat), ((100.0, 60.0, 0.0, 0.0), 20))
        self.assertEqual(launchplan.parse_profile(profile.spec()).repeat, 20)

    def test_a_profile_without_a_repeat_has_none(self):
        self.assertIsNone(launchplan.parse_profile("100:0").repeat)

    def test_a_zero_or_text_repeat_is_refused(self):
        for bad in ("100:0@0", "100:0@x"):
            with self.assertRaises(ValueError, msg=bad):
                launchplan.parse_profile(bad)

    def test_the_run_count_adds_each_profiles_own_repetitions(self):
        profiles = launchplan.parse_profiles(["0:0@10", "100:0@20", "100:60@10"])
        launch = launchplan.plan_launches(["pr24-control"], ["hand-mining"], profiles, 1)[0]
        self.assertEqual(launchplan.runs_in_launch(launch, {"hand-mining": {"plain": 0, "network": 1}}), 40)

    def test_the_child_arguments_keep_the_repeats(self):
        profiles = launchplan.parse_profiles(["0:0@10", "100:0@20"])
        launch = launchplan.plan_launches(["fork"], ["hand-mining"], profiles, 1)[0]
        self.assertIn("0:0:0:0@10", launch.arguments())
        self.assertIn("100:0:0:0@20", launch.arguments())


class PlanTests(unittest.TestCase):
    profiles = launchplan.parse_profiles(["100:0", "100:60", "250:100"])

    def test_network_settings_do_not_add_launches(self):
        few = launchplan.plan_launches(["pr24-fixed", "stock-5.5.0"], ["hand-mining"], launchplan.parse_profiles(["100:0"]), 3)
        many = launchplan.plan_launches(["pr24-fixed", "stock-5.5.0"], ["hand-mining"], self.profiles, 3)
        self.assertEqual((len(few), len(many)), (2, 2))

    def test_one_launch_per_build_and_startup_group(self):
        launches = launchplan.plan_launches(["fork", "stock-5.5.0"], ["default", "mixed-characters"], self.profiles)
        self.assertEqual(len(launches), 4)

    def test_identifiers_name_number_build_and_group(self):
        launches = launchplan.plan_launches(["stock-5.5.0"], ["hand-mining"], self.profiles)
        self.assertEqual(launches[0].identifier, "L1-stock-5.5.0-hand-mining")

    def test_the_same_build_twice_is_one_launch(self):
        self.assertEqual(len(launchplan.plan_launches(["fork", "fork"], ["default"], self.profiles)), 1)

    def test_zero_repetitions_are_refused(self):
        with self.assertRaises(ValueError):
            launchplan.plan_launches(["fork"], ["default"], self.profiles, repetitions=0)

    def test_the_child_arguments_carry_build_group_profiles_repeat_id_and_match(self):
        launch = launchplan.plan_launches(["stock-5.5.0"], ["hand-mining"], self.profiles, 3, ["hold_mining"])[0]
        self.assertEqual(launch.arguments(), ["--together", "stock-5.5.0", "--repeat", "3", "--launch-id", "L1-stock-5.5.0-hand-mining",
                                              "--group", "hand-mining", "--net", "100:0:0:0", "100:60:0:0", "250:100:0:0", "--match", "hold_mining"])


class CountTests(unittest.TestCase):
    def test_network_scenarios_run_once_per_profile_and_plain_ones_once(self):
        profiles = launchplan.parse_profiles(["100:0", "100:60", "250:100"])
        hand = launchplan.plan_launches(["fork"], ["hand-mining"], profiles, 3)[0]
        default = launchplan.plan_launches(["fork"], ["default"], profiles, 3)[0]
        self.assertEqual(launchplan.runs_in_launch(hand, COUNTS), 2 * 3 * 3)
        self.assertEqual(launchplan.runs_in_launch(default, COUNTS), 10 * 3)

    def test_the_listing_names_each_launch_with_its_networks_and_runs(self):
        profiles = launchplan.parse_profiles(["100:0", "100:60"])
        launches = launchplan.plan_launches(["fork"], ["hand-mining"], profiles, 2)
        lines = launchplan.describe_launches(launches, COUNTS)
        self.assertEqual(lines[0], "launches (1):")
        self.assertIn("L1-fork-hand-mining", lines[1])
        self.assertIn("8 scenario runs", lines[1])
        self.assertIn("d100-j0, d100-j60", lines[1])

    def test_without_grouping_every_run_would_be_its_own_launch(self):
        profiles = launchplan.parse_profiles(["100:0", "100:60", "250:100"])
        launches = launchplan.plan_launches(["pr24-fixed", "stock-5.5.0"], ["hand-mining"], profiles, 3)
        self.assertEqual(launchplan.launches_without_grouping(launches, COUNTS), 36)
        self.assertEqual(len(launches), 2)


if __name__ == "__main__":
    unittest.main()
