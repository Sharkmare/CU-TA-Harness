import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hookbench_stats as stats


def report(frame_mean, cpu=0.5, hook_ms=0.1, hooks=()):
    return {"frames": {"meanMs": frame_mean, "p95Ms": frame_mean * 1.5, "p99Ms": frame_mean * 2}, "processCpuShareOfOneCore": cpu,
            "hookSecondsPerFrame": {"meanMs": hook_ms}, "hooks": list(hooks)}


def noisy(centre, relative_noise, count, seed):
    generator = random.Random(seed)
    return [centre * (1 + generator.gauss(0, relative_noise)) for _ in range(count)]


class CompareTests(unittest.TestCase):

    def test_identical_builds_show_no_difference(self):
        first = noisy(10.0, 0.02, 8, 1)
        second = noisy(10.0, 0.02, 8, 2)
        self.assertEqual(stats.compare(first, second)["verdict"], "no difference")

    def test_a_ten_percent_cost_is_detected(self):
        first = noisy(10.0, 0.02, 8, 1)
        second = noisy(11.0, 0.02, 8, 2)
        self.assertEqual(stats.compare(first, second)["verdict"], "candidate slower")

    def test_a_gap_inside_the_noise_is_not_reported(self):
        first = noisy(10.0, 0.10, 6, 3)
        second = noisy(10.3, 0.10, 6, 4)
        self.assertEqual(stats.compare(first, second)["verdict"], "no difference")

    def test_a_gap_under_the_relative_minimum_is_not_reported_even_when_noise_is_tiny(self):
        self.assertEqual(stats.compare([10.0, 10.0, 10.0, 10.0], [10.1, 10.1, 10.1, 10.1])["verdict"], "no difference")

    def test_faster_candidate_is_named_faster(self):
        self.assertEqual(stats.compare(noisy(10.0, 0.01, 6, 5), noisy(8.0, 0.01, 6, 6))["verdict"], "candidate faster")

    def test_too_few_runs_is_refused(self):
        self.assertEqual(stats.compare([10.0, 10.0], [12.0, 12.0])["verdict"], "too few runs")

    def test_reports_are_compared_on_every_metric(self):
        base = [report(10.0 + 0.01 * index) for index in range(5)]
        slower = [report(12.0 + 0.01 * index, cpu=0.6, hook_ms=0.4) for index in range(5)]
        result = stats.compare_reports(base, slower)
        self.assertEqual({name: item["verdict"] for name, item in result.items()}, {name: "candidate slower" for name, _ in stats.METRICS})


class HookTableTests(unittest.TestCase):

    def row(self, name, total, calls=100):
        return {"name": name, "kinds": ["prefix"], "targets": ["T.M"], "calls": calls, "totalMs": total, "meanUs": total * 10, "netMeanUs": total * 9, "p95Us": 2.0, "p99Us": 4.0,
                "maxUs": 8.0, "callsPerFrame": 1.0, "callsPerFixedTick": 2.0}

    def test_sorted_by_total_and_averaged_over_runs(self):
        reports = [report(10, hooks=[self.row("a", 1.0), self.row("b", 5.0)]), report(10, hooks=[self.row("a", 3.0), self.row("b", 7.0)])]
        table = stats.hook_table(reports)
        self.assertEqual([row["name"] for row in table], ["b", "a"])
        self.assertAlmostEqual(table[0]["meanTotalMs"], 6.0)
        self.assertAlmostEqual(table[1]["meanTotalMs"], 2.0)
        self.assertEqual(table[0]["runsSeen"], 2)


if __name__ == "__main__":
    unittest.main()
