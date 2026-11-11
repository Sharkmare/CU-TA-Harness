import json
import os
import tempfile
import threading
import unittest

from casualtieslink import desync


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
        samples = [sample(0.0, [8, 0.0], [8, 0.0]), sample(0.25, [8, 40.0], [8, 40.0]), sample(0.5, [8, 40.0], [8, 0.0]), sample(0.75, [0, 0.0], [0, 0.0])]
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
        return desync.describe_series(observation, "upstream-fixes", "cd" * 32, "1.0", delay, 20.0)

    def test_the_report_names_build_hash_delay_and_both_sides(self):
        text = desync.format_series_report(self.report())
        self.assertIn("[upstream-fixes] sha256 " + "cd" * 32, text)
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
            self.assertTrue(os.path.basename(path).endswith("__upstream-fixes_cdcdcdcd__delay100.json"), path)
            with open(path, encoding="utf-8") as handle:
                loaded = json.load(handle)
        self.assertEqual(loaded["delayMs"], 100.0)
        self.assertEqual(len(loaded["samples"]), len(report["samples"]))
        self.assertIn("hitTimes", loaded)


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
