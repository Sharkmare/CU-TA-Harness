import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from casualtieslink import desync, launchplan


def sample(t, host, client):
    return {"t": t, "host": host, "client": client}


class JudgeSeriesTests(unittest.TestCase):
    def test_a_block_that_breaks_on_both_and_stays_gone_persists(self):
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(0.25, [8, 20.0], [8, 20.0]), sample(0.5, [0, 0.0], [0, 0.0]), sample(0.75, [0, 0.0], [0, 0.0])]
        verdict, findings = desync.judge_series(samples)
        self.assertEqual(verdict, desync.VERDICT_PERSISTED)
        self.assertEqual(findings["client"]["brokeAt"], 0.5)
        self.assertTrue(findings["host"]["resets"] == [] and not findings["client"]["presentAtEnd"])

    def test_a_counter_that_drops_without_a_break_is_a_crack_reset(self):
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(0.25, [8, 40.0], [8, 40.0]), sample(0.5, [8, 40.0], [8, 0.0]), sample(0.75, [8, 40.0], [8, 20.0]), sample(1.0, [0, 0.0], [0, 0.0])]
        verdict, findings = desync.judge_series(samples)
        self.assertEqual(verdict, desync.VERDICT_CRACK_RESET)
        self.assertEqual(findings["client"]["resets"], [{"t": 0.5, "from": 40.0, "to": 0.0}])
        self.assertEqual(findings["host"]["resets"], [])

    def test_a_block_present_again_after_it_was_gone_reappeared(self):
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(1.0, [0, 0.0], [0, 0.0]), sample(2.0, [0, 0.0], [8, 0.0]), sample(3.0, [0, 0.0], [8, 0.0])]
        verdict, findings = desync.judge_series(samples)
        self.assertEqual(verdict, desync.VERDICT_REAPPEARED)
        self.assertEqual(findings["client"]["reappeared"], [{"t": 2.0, "goneFor": 1.0}])
        self.assertTrue(findings["client"]["presentAtEnd"])
        self.assertFalse(findings["host"]["presentAtEnd"])

    def test_reappearance_outranks_a_crack_reset(self):
        samples = [sample(0.0, [8, 30.0], [8, 30.0]), sample(0.25, [8, 0.0], [8, 0.0]), sample(0.5, [0, 0.0], [0, 0.0]), sample(0.75, [8, 0.0], [8, 0.0])]
        self.assertEqual(desync.judge_series(samples)[0], desync.VERDICT_REAPPEARED)

    def test_nothing_breaking_is_never_broke(self):
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(0.25, [8, 20.0], [8, 20.0])]
        self.assertEqual(desync.judge_series(samples)[0], desync.VERDICT_NEVER_BROKE)

    def test_a_counter_cleared_a_moment_before_the_block_read_as_gone_is_not_a_reset(self):
        samples = [sample(0.0, [3, 58.0], [3, 58.0]), sample(0.25, [3, 0.0], [0, 0.0]), sample(0.5, [0, 0.0], [0, 0.0])]
        self.assertEqual(desync.judge_series(samples)[0], desync.VERDICT_PERSISTED)

    def test_a_counter_going_down_because_the_block_broke_is_not_a_reset(self):
        samples = [sample(0.0, [8, 80.0], [8, 80.0]), sample(0.25, [0, 0.0], [0, 0.0])]
        self.assertEqual(desync.judge_series(samples)[0], desync.VERDICT_PERSISTED)


class FakeBlock:
    def __init__(self, hits_to_break):
        self.hits = 0
        self.hits_to_break = hits_to_break
        self.lock = threading.Lock()

    def read(self, game, context):
        with self.lock:
            return [0, 0.0] if self.hits >= self.hits_to_break else [8, 20.0 * self.hits]

    def hit(self, client, context):
        with self.lock:
            self.hits += 1


class ObserveSeriesTests(unittest.TestCase):
    def scenario(self, block, max_hits=10):
        return desync.SeriesScenario("hand", "bare hands", lambda host, client: {}, block.hit, block.read,
                                     cadence_seconds=0.03, max_hits=max_hits, interval_seconds=0.01, tail_seconds=0.15)

    def test_hits_stop_at_the_break_and_the_series_keeps_sampling_for_the_tail(self):
        block = FakeBlock(hits_to_break=3)
        observation = desync.observe_series(self.scenario(block), "host", "client")
        self.assertEqual(block.hits, 3)
        self.assertEqual(len(observation.hit_times), 3)
        self.assertGreater(len(observation.samples), 8)
        self.assertEqual(observation.samples[-1]["client"], [0, 0.0])
        self.assertEqual(desync.judge_series(observation.samples)[0], desync.VERDICT_PERSISTED)

    def test_the_start_of_the_series_clock_is_kept_in_the_context_for_the_scenario(self):
        block = FakeBlock(hits_to_break=1)
        clock = iter([100.0] + [100.0 + step * 0.01 for step in range(1, 400)])
        observation = desync.observe_series(self.scenario(block), "host", "client", clock=lambda: next(clock))
        self.assertEqual(observation.context["seriesStarted"], 100.0)

    def test_the_hit_limit_ends_a_block_that_never_breaks(self):
        block = FakeBlock(hits_to_break=99)
        observation = desync.observe_series(self.scenario(block, max_hits=4), "host", "client")
        self.assertEqual(block.hits, 4)
        self.assertEqual(desync.judge_series(observation.samples)[0], desync.VERDICT_NEVER_BROKE)

    def test_skipping_the_action_makes_no_hits(self):
        block = FakeBlock(hits_to_break=1)
        observation = desync.observe_series(self.scenario(block), "host", "client", perform_action=False)
        self.assertEqual(block.hits, 0)
        self.assertFalse(observation.acted)
        self.assertEqual(desync.judge_series(observation.samples)[0], desync.VERDICT_NEVER_BROKE)


class SeriesReportTests(unittest.TestCase):
    def report(self, delay=100.0):
        block = FakeBlock(hits_to_break=2)
        scenario = desync.SeriesScenario("hand_mining_cracks", "bare hands", lambda host, client: {}, block.hit, block.read,
                                         cadence_seconds=0.02, max_hits=5, interval_seconds=0.01, tail_seconds=0.05)
        observation = desync.observe_series(scenario, "host", "client")
        return desync.describe_series(observation, "pr24-fixed", "cd" * 32, "1.0", delay, 20.0)

    def test_the_report_names_build_hash_delay_and_both_sides(self):
        text = desync.format_series_report(self.report())
        self.assertIn("[pr24-fixed] sha256 " + "cd" * 32, text)
        self.assertIn("100 ms one way (+ jitter up to 20 ms)", text)
        self.assertIn("game version 1.0, action performed by the client", text)
        self.assertIn("host: broke at", text)
        self.assertIn("client: broke at", text)
        self.assertIn("verdict: persisted", text)

    def test_without_a_proxy_the_report_says_so(self):
        self.assertIn("network: no proxy", desync.format_series_report(self.report(delay=None)))

    def test_the_saved_file_carries_the_delay_and_the_whole_series(self):
        report = self.report()
        with tempfile.TemporaryDirectory() as directory:
            path = desync.save_series_report(report, directory)
            self.assertRegex(os.path.basename(path), r"__pr24-fixed_cdcdcdcd__delay100_jitter20_r1__\d{6}\.json$")
            with open(path, encoding="utf-8") as handle:
                loaded = json.load(handle)
        self.assertEqual(loaded["delayMs"], 100.0)
        self.assertEqual(len(loaded["samples"]), len(report["samples"]))
        self.assertIn("hitTimes", loaded)


class HintTests(unittest.TestCase):
    def hints(self, samples, hit_times, delay, counts=None):
        verdict, findings = desync.judge_series(samples)
        return desync.verdict_hints(samples, hit_times, delay, counts, findings)

    def test_a_constant_host_to_client_ratio_means_a_multiplier_mismatch(self):
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(0.25, [8, 10.0], [8, 20.0]), sample(0.5, [8, 20.0], [8, 40.0]), sample(0.6, [8, 30.0], [8, 60.0]), sample(0.75, [0, 0.0], [0, 0.0])]
        self.assertTrue(any("constant host/client crack ratio 0.50" in hint for hint in self.hints(samples, [0.0, 0.5], 0.0)))

    def test_equal_counters_do_not_claim_a_ratio(self):
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(0.25, [8, 20.0], [8, 20.0]), sample(0.5, [0, 0.0], [0, 0.0])]
        hints = self.hints(samples, [0.0], 0.0)
        self.assertFalse(any("ratio" in hint for hint in hints))
        self.assertIn("no divergence pattern in this run", hints)

    def test_fewer_host_steps_than_swings_with_delay_points_at_dropped_swings(self):
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(0.25, [8, 20.0], [8, 0.0]), sample(1.0, [8, 40.0], [8, 20.0]), sample(2.0, [0, 0.0], [0, 0.0])]
        counts = {"cooldownDrops": 3, "rangeDrops": 0, "applied": 2, "unresolved": 0, "dropped": 0}
        hints = self.hints(samples, [0.0, 0.7, 1.4, 2.1, 2.8, 3.5], 100.0, counts)
        self.assertTrue(any("dropped swings" in hint and "100 ms" in hint for hint in hints))
        self.assertIn("host dropped swings on the attacker cooldown", hints)
        self.assertIn("host log: cooldown drops 3, range drops 0, applied lines 2", hints)
        self.assertNotIn("host rejected swings for range", hints)

    def test_a_late_host_break_is_named_with_its_lag(self):
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(1.0, [8, 50.0], [0, 0.0]), sample(1.5, [0, 0.0], [0, 0.0])]
        self.assertTrue(any("host broke the block 0.50 s after the client" in hint for hint in self.hints(samples, [0.0], 250.0)))

    def test_host_log_lines_are_counted_by_marker(self):
        log = "[Info] [evidencebag] hit server cooldown client=2 cd=0.3\n[Info] [evidencebag] hit server cooldown client=2 cd=0.1\n[Info] [evidencebag] hit server range client=2\nother\n"
        counts = desync.host_log_counts(log)
        self.assertEqual((counts["cooldownDrops"], counts["rangeDrops"], counts["applied"]), (2, 1, 0))

    def test_counter_steps_ignore_the_clearing_at_the_break(self):
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(0.25, [8, 20.0], [8, 20.0]), sample(0.5, [0, 0.0], [0, 0.0])]
        self.assertEqual((desync.counter_increases(samples, "host"), desync.counter_increases(samples, "client")), (1, 1))


class SwingClassificationTests(unittest.TestCase):
    def test_a_swing_is_accepted_when_a_host_step_follows_its_arrival(self):
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(0.4, [8, 19.0], [8, 19.0]), sample(1.5, [8, 38.0], [8, 38.0]), sample(2.2, [8, 38.0], [8, 38.0])]
        accepted = desync.classify_swings([0.0, 0.7, 1.4], samples, 100.0)
        self.assertEqual(accepted, [True, False, True])

    def test_the_break_counts_as_a_host_step(self):
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(0.3, [8, 19.0], [8, 19.0]), sample(1.0, [0, 0.0], [0, 0.0])]
        self.assertEqual(desync.classify_swings([0.0, 0.7], samples, 0.0), [True, True])

    def test_a_counter_cleared_before_the_block_reads_gone_still_counts_the_breaking_swing(self):
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(0.4, [8, 58.0], [8, 0.0]), sample(1.5, [8, 0.0], [8, 58.0]), sample(1.9, [0, 0.0], [0, 58.0])]
        self.assertEqual(desync.host_step_times(samples), [0.4, 1.5])
        self.assertEqual(desync.classify_swings([0.0, 1.2], samples, 100.0), [True, True])

    def test_the_gap_summary_splits_accepted_from_dropped(self):
        log = [{"gap": 0.1}, {"gap": 0.9}, {"gap": 0.3}]
        summary = desync.gap_summary(log, [True, False, True])
        self.assertEqual(summary["accepted"], {"count": 2, "meanGap": 0.2, "maxGap": 0.3})
        self.assertEqual(summary["dropped"], {"count": 1, "meanGap": 0.9, "maxGap": 0.9})

    def test_an_empty_group_has_no_mean(self):
        self.assertEqual(desync.gap_summary([{"gap": 0.5}], [True])["dropped"], {"count": 0, "meanGap": None, "maxGap": None})

    def test_the_report_lists_each_swing_with_its_gap_and_acceptance(self):
        class Scenario:
            name = "x"
            description = "d"
        observation = desync.SeriesObservation(Scenario(), {"host": [8, 0.0], "client": [8, 0.0]},
                                               [sample(0.0, [8, 0.0], [8, 0.0]), sample(0.4, [8, 19.0], [8, 19.0]), sample(2.0, [0, 0.0], [0, 0.0])],
                                               [0.0, 0.7], True,
                                               {"swingLog": [{"clientPosition": {"x": 1, "y": 2}, "hostCopyPosition": {"x": 1, "y": 2.5}, "gap": 0.5}, {"clientPosition": {"x": 1, "y": 2}, "hostCopyPosition": {"x": 1, "y": 2}, "gap": 0.0}]})
        report = desync.describe_series(observation, "b", "00" * 32, "1.0", 100.0)
        self.assertEqual([item["acceptedByHost"] for item in report["swings"]["list"]], [True, True])
        self.assertEqual(report["swings"]["list"][0]["gap"], 0.5)
        self.assertIn("accepted by the host (approximate, by crack steps): 2", desync.format_series_report(report))


class HeldClickTests(unittest.TestCase):
    def test_calls_the_game_refuses_are_not_counted_as_swings(self):
        calls = {"n": 0}
        block = FakeBlock(hits_to_break=2)

        def hold(client, context):
            calls["n"] += 1
            if calls["n"] % 3:
                return False
            block.hit(client, context)
            return True

        scenario = desync.SeriesScenario("hold", "held", lambda host, client: {}, hold, block.read,
                                         cadence_seconds=0.005, max_hits=100, interval_seconds=0.01, tail_seconds=0.05)
        observation = desync.observe_series(scenario, "host", "client")
        self.assertGreaterEqual(len(observation.hit_times), 2)
        self.assertEqual(len(observation.hit_times), calls["n"] // 3)

    def test_swings_sent_after_the_host_broke_the_block_are_not_drops(self):
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(0.4, [8, 19.0], [8, 19.0]), sample(1.0, [0, 0.0], [8, 58.0]), sample(1.6, [0, 0.0], [0, 0.0])]
        accepted = desync.classify_swings([0.0, 0.7, 1.4], samples, 100.0)
        self.assertEqual(accepted, [True, True, None])

    def test_intervals_and_the_cooldown_hint_use_the_jitter_range(self):
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(2.0, [0, 0.0], [0, 0.0])]
        verdict, findings = desync.judge_series(samples)
        hits = [0.0, 0.2, 0.4, 0.62]
        hints = desync.verdict_hints(samples, hits, 100.0, None, findings, 100.0)
        self.assertEqual(desync.swing_intervals(hits), [0.2, 0.2, 0.22])
        self.assertIn("client swing intervals: shortest 0.200 s, mean 0.207 s; 3 of 3 could reach the host under the 0.124 s cooldown after jitter of up to 100 ms", hints)
        quiet = desync.verdict_hints(samples, hits, 100.0, None, findings, 50.0)
        self.assertIn("client swing intervals: shortest 0.200 s, mean 0.207 s; 0 of 3 could reach the host under the 0.124 s cooldown after jitter of up to 50 ms", quiet)


class TileHitTests(unittest.TestCase):
    def test_increases_are_counted_per_tile_and_side(self):
        samples = [
            {"t": 0.0, "host": [8, 0.0, {}], "client": [8, 0.0, {}]},
            {"t": 0.25, "host": [8, 19.0, {"0,0": 19.0}], "client": [8, 19.0, {"0,0": 19.0}]},
            {"t": 0.5, "host": [8, 19.0, {"0,0": 19.0, "1,0": 19.0}], "client": [8, 38.0, {"0,0": 38.0}]},
            {"t": 0.75, "host": [8, 38.0, {"0,0": 38.0, "1,0": 19.0}], "client": [0, 0.0, {}]},
        ]
        self.assertEqual(desync.tile_hits(samples, "host"), {"0,0": 2, "1,0": 1})
        self.assertEqual(desync.tile_hits(samples, "client"), {"0,0": 2})

    def test_two_element_states_are_still_judged_and_have_no_tile_hits(self):
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(0.25, [8, 19.0], [8, 19.0]), sample(0.5, [0, 0.0], [0, 0.0])]
        self.assertEqual(desync.judge_series(samples)[0], desync.VERDICT_PERSISTED)
        self.assertEqual(desync.tile_hits(samples, "host"), {})

    def test_three_element_states_are_judged_by_block_and_counter_only(self):
        samples = [{"t": 0.0, "host": [8, 0.0, {}], "client": [8, 0.0, {}]}, {"t": 0.25, "host": [8, 20.0, {"0,0": 20.0}], "client": [0, 0.0, {}]},
                   {"t": 0.5, "host": [8, 20.0, {"0,0": 20.0}], "client": [8, 0.0, {}]}]
        self.assertEqual(desync.judge_series(samples)[0], desync.VERDICT_REAPPEARED)

    def test_the_report_names_hits_on_other_tiles(self):
        block = FakeBlock(hits_to_break=2)
        scenario = desync.SeriesScenario("hold", "d", lambda host, client: {"aimPattern": "circle"}, block.hit, block.read, cadence_seconds=0.01, max_hits=5, interval_seconds=0.01, tail_seconds=0.05)
        report = desync.describe_series(desync.observe_series(scenario, "host", "client"), "fork", "ab" * 32)
        report["tileHits"] = {"client": {"0,0": 3}, "host": {"0,0": 2, "1,0": 1}}
        text = desync.format_series_report(report)
        self.assertIn("increases on tiles other than the target: client 0, host 1", text)
        self.assertIn("aim pattern circle", text)


class CleanupTests(unittest.TestCase):
    def test_cleanup_runs_after_the_series_even_when_hits_fail(self):
        calls = []

        def broken_hit(client, context):
            raise RuntimeError("link gone")

        scenario = desync.SeriesScenario("hold", "d", lambda host, client: {}, broken_hit, lambda game, context: [8, 0.0], cadence_seconds=0.0, max_hits=3,
                                         interval_seconds=0.01, tail_seconds=0.0, cleanup=lambda host, client, context: calls.append("cleaned"))
        with self.assertRaises(RuntimeError):
            desync.observe_series(scenario, "host", "client")
        self.assertEqual(calls, ["cleaned"])

    def test_a_cleanup_error_is_recorded_not_raised(self):
        def failing_cleanup(host, client, context):
            raise RuntimeError("no host")

        block = FakeBlock(hits_to_break=1)
        scenario = desync.SeriesScenario("hold", "d", lambda host, client: {}, block.hit, block.read, cadence_seconds=0.01, max_hits=3,
                                         interval_seconds=0.01, tail_seconds=0.02, cleanup=failing_cleanup)
        observation = desync.observe_series(scenario, "host", "client")
        self.assertEqual(observation.context["cleanupError"], "no host")
        self.assertEqual(desync.describe_series(observation, "fork", "ab" * 32)["cleanupError"], "no host")


class TranspilerLineTests(unittest.TestCase):
    def test_lines_naming_the_transpiler_are_collected(self):
        log = "[Info] fine\n[Warning:  Together] Body.Attack TRANSPILER: hit-loop markers not found, leaving stock IL\n[Info] TRANSPILER: Body.Attack TRANSPILER SUCCESS :) \n"
        found = desync.transpiler_lines(log)
        self.assertEqual(len(found), 2)
        self.assertTrue(found[0].startswith("[Warning:  Together] Body.Attack TRANSPILER: hit-loop markers not found"))

    def test_a_log_without_them_gives_none(self):
        self.assertEqual(desync.transpiler_lines("nothing"), [])

    def test_the_report_shows_the_lines_per_machine(self):
        block = FakeBlock(hits_to_break=1)
        scenario = desync.SeriesScenario("hold", "d", lambda host, client: {}, block.hit, block.read, cadence_seconds=0.01, max_hits=3, interval_seconds=0.01, tail_seconds=0.02)
        report = desync.describe_series(desync.observe_series(scenario, "host", "client"), "fork", "ab" * 32)
        report["transpilerLines"] = {"host": ["TRANSPILER: hit-loop markers not found"], "client": []}
        text = desync.format_series_report(report)
        self.assertIn("host Body.Attack transpiler lines: ['TRANSPILER: hit-loop markers not found']", text)
        self.assertIn("client Body.Attack transpiler lines: none", text)


class CrackStepTests(unittest.TestCase):
    def test_each_rise_of_the_counter_is_one_step_per_side(self):
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(0.25, [8, 19.33], [8, 24.7]), sample(0.5, [8, 38.66], [8, 49.4]), sample(0.75, [8, 58.0], [0, 0.0]), sample(1.0, [0, 0.0], [0, 0.0])]
        self.assertEqual(desync.crack_steps(samples, "host"), [19.33, 19.33, 19.34])
        self.assertEqual(desync.crack_steps(samples, "client"), [24.7, 24.7])

    def test_a_report_carries_the_steps_of_both_sides(self):
        block = FakeBlock(hits_to_break=2)
        scenario = desync.SeriesScenario("hold", "d", lambda host, client: {}, block.hit, block.read, cadence_seconds=0.01, max_hits=5, interval_seconds=0.01, tail_seconds=0.05)
        report = desync.describe_series(desync.observe_series(scenario, "host", "client"), "fork", "ab" * 32)
        self.assertEqual(set(report["crackSteps"]), {"client", "host"})
        self.assertIn("crack steps per sample, client", desync.format_series_report(report))


class RunExpansionTests(unittest.TestCase):
    def scenarios(self):
        plain = desync.Scenario("block", "d", None, None, None, None)
        series = desync.SeriesScenario("hold", "d", None, None, None, 0.0, 1)
        return plain, series

    def test_network_scenarios_run_once_per_profile_and_plain_ones_once(self):
        profiles = launchplan.parse_profiles(["100:0", "100:60", "250:100"])
        runs = desync.expand_runs(list(self.scenarios()), profiles, 1)
        self.assertEqual([run.name for run in runs], ["test_block", "test_hold_d100-j0", "test_hold_d100-j60", "test_hold_d250-j100"])
        self.assertTrue(runs[0].profile is launchplan.DIRECT)

    def test_repetitions_repeat_the_whole_set_with_a_suffix(self):
        profiles = launchplan.parse_profiles(["100:0"])
        runs = desync.expand_runs(list(self.scenarios()), profiles, 2)
        self.assertEqual([run.name for run in runs], ["test_block_r01", "test_block_r02", "test_hold_d100-j0_r01", "test_hold_d100-j0_r02"])
        self.assertEqual([run.repetition for run in runs], [1, 2, 1, 2])

    def test_a_profile_can_carry_its_own_repetition_count(self):
        profiles = launchplan.parse_profiles(["0:0@2", "100:0@3", "100:60"])
        runs = desync.expand_runs([self.scenarios()[1]], profiles, 1)
        self.assertEqual([run.name for run in runs], [
            "test_hold_d0-j0_r01", "test_hold_d0-j0_r02",
            "test_hold_d100-j0_r01", "test_hold_d100-j0_r02", "test_hold_d100-j0_r03",
            "test_hold_d100-j60"])

    def test_plain_scenarios_ignore_a_profile_repeat(self):
        profiles = launchplan.parse_profiles(["100:0@5"])
        self.assertEqual([run.name for run in desync.expand_runs([self.scenarios()[0]], profiles, 1)], ["test_block"])

    def test_the_names_are_unique_across_profiles_and_repetitions(self):
        profiles = launchplan.parse_profiles(["100:0", "100:60", "250:100"])
        names = [run.name for run in desync.expand_runs(list(self.scenarios()), profiles, 3)]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 3 * (1 + 3))

    def test_the_series_scenario_is_network_sensitive_and_the_plain_one_is_not(self):
        plain, series = self.scenarios()
        self.assertFalse(plain.network_sensitive)
        self.assertTrue(series.network_sensitive)


class EnvironmentTests(unittest.TestCase):
    def test_profiles_come_from_the_nets_variable(self):
        with mock.patch.dict(os.environ, {desync.NETS_ENVIRONMENT_VARIABLE: "100:0,250:100:0.1"}):
            profiles = desync.profiles_from_environment()
        self.assertEqual([p.key() for p in profiles], [(100.0, 0.0, 0.0, 0.0), (250.0, 100.0, 0.1, 0.0)])

    def test_the_old_delay_variables_still_make_one_profile(self):
        with mock.patch.dict(os.environ, {desync.DELAY_ENVIRONMENT_VARIABLE: "100", desync.JITTER_ENVIRONMENT_VARIABLE: "60"}, clear=False):
            os.environ.pop(desync.NETS_ENVIRONMENT_VARIABLE, None)
            profiles = desync.profiles_from_environment()
        self.assertEqual([p.key() for p in profiles], [(100.0, 60.0, 0.0, 0.0)])

    def test_nothing_set_means_the_direct_profile(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for name in (desync.NETS_ENVIRONMENT_VARIABLE, desync.DELAY_ENVIRONMENT_VARIABLE):
                os.environ.pop(name, None)
            self.assertEqual([p.key() for p in desync.profiles_from_environment()], [launchplan.DIRECT.key()])

    def test_repeat_defaults_to_one_and_refuses_zero(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(desync.REPEAT_ENVIRONMENT_VARIABLE, None)
            self.assertEqual(desync.repeat_from_environment(), 1)
        with mock.patch.dict(os.environ, {desync.REPEAT_ENVIRONMENT_VARIABLE: "0"}):
            with self.assertRaises(ValueError):
                desync.repeat_from_environment()

    def test_the_series_report_names_launch_network_and_seed(self):
        block = FakeBlock(hits_to_break=2)
        scenario = desync.SeriesScenario("hold", "d", lambda host, client: {}, block.hit, block.read, cadence_seconds=0.01, max_hits=5, interval_seconds=0.01, tail_seconds=0.05)
        observation = desync.observe_series(scenario, "host", "client")
        report = desync.describe_series(observation, "fork", "ab" * 32, "1.0", 100.0, 60.0, None, "L2-fork-hand-mining", 3,
                                        {"delay_ms": 100.0, "jitter_ms": 60.0, "loss": 0.0, "reorder": 0.0}, 4242)
        text = desync.format_series_report(report)
        self.assertIn("launch L2-fork-hand-mining, repetition 3", text)
        self.assertIn("100 ms one way, jitter up to 60 ms, loss 0, reorder 0, seed 4242", text)
        with tempfile.TemporaryDirectory() as directory:
            path = desync.save_series_report(report, directory)
        self.assertRegex(os.path.basename(path), r"__d100-j60_r3__\d{6}\.json$")


class DelayParsingTests(unittest.TestCase):
    def test_numbers_parse_and_empty_means_no_proxy(self):
        self.assertEqual(desync.parse_delay("250"), 250.0)
        self.assertEqual(desync.parse_delay("0"), 0.0)
        self.assertIsNone(desync.parse_delay(None))
        self.assertIsNone(desync.parse_delay(""))

    def test_a_negative_or_non_numeric_delay_is_refused(self):
        with self.assertRaises(ValueError):
            desync.parse_delay("-5")
        with self.assertRaises(ValueError):
            desync.parse_delay("fast")


if __name__ == "__main__":
    unittest.main()
