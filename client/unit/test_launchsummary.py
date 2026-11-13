import json
import os
import tempfile
import unittest

from casualtieslink.reports import launchsummary


def report(verdict, delay, jitter, repetition, rows=None, hits=4, answers=None, observed=None, launch="L1"):
    return {"launchId": launch, "verdict": verdict, "repetition": repetition, "hitTimes": [0.0] * hits,
            "network": {"delay_ms": delay, "jitter_ms": jitter, "loss": 0.0, "reorder": 0.0},
            "diagBlock": {"clientSends": len(rows), "rows": [{"outcome": outcome} for outcome in rows]} if rows is not None else None,
            "gamesAnswerAfterRun": answers or {"host": "in-world", "client": "in-world"},
            "proxyObserved": observed or {"toHost": {"packets": 3, "minMs": 100.0, "meanMs": 100.0, "maxMs": 100.0}, "toClient": {"packets": 0, "minMs": None, "meanMs": None, "maxMs": None}}}


class SummaryTests(unittest.TestCase):
    def test_runs_are_grouped_by_profile_and_counted(self):
        reports = [
            report("persisted", 0, 0, 1, ["decided:applied"] * 4),
            report("persisted", 100, 0, 1, ["decided:applied"] * 4),
            report("reappeared-after-break", 100, 0, 2, ["decided:applied"] * 3 + ["decided:out of reach"]),
            report("never-broke", 100, 60, 1, ["refused-cooldown", "decided:applied"]),
        ]
        profiles = launchsummary.summarise_launch(reports)
        self.assertEqual(sorted(profiles), ["d0-j0", "d100-j0", "d100-j60"])
        self.assertEqual(profiles["d100-j0"]["blocksMined"], 2)
        self.assertEqual(profiles["d100-j0"]["reappearedAfterBreak"], 1)
        self.assertEqual(profiles["d100-j0"]["reappearedRuns"], [2])
        self.assertEqual(profiles["d100-j60"]["blocksNeverBroke"], 1)
        self.assertEqual(profiles["d100-j60"]["blocksMined"], 0)

    def test_swings_sent_received_accepted_and_lost_reasons_add_up(self):
        reports = [report("reappeared-after-break", 100, 0, 1, ["decided:applied", "decided:out of reach", "refused-cooldown", "never-received"])]
        found = launchsummary.summarise_launch(reports)["d100-j0"]
        self.assertEqual((found["swingsSent"], found["swingsReceived"], found["swingsAccepted"]), (4, 3, 1))
        self.assertEqual(found["lossByReason"], {"out of reach": 1, "refused-cooldown": 1, "never-received": 1})

    def test_host_raycast_misses_are_a_loss_reason_and_not_accepted(self):
        rows = [{"outcome": "decided:non-block", "hostRaycastMiss": True}, {"outcome": "decided:non-block"}, {"outcome": "decided:applied"}]
        report_with_rows = report("persisted", 100, 0, 1, [])
        report_with_rows["diagBlock"] = {"clientSends": 3, "rows": rows}
        found = launchsummary.summarise_launch([report_with_rows])["d100-j0"]
        self.assertEqual((found["swingsAccepted"], found["lossByReason"]), (2, {"host raycast miss": 1}))

    def test_reports_without_diag_lines_still_count_blocks_and_harness_swings(self):
        found = launchsummary.summarise_launch([report("persisted", 0, 0, 1, None, hits=5)])["d0-j0"]
        self.assertEqual((found["blocksMined"], found["swingsHarness"], found["swingsSent"]), (1, 5, 0))

    def test_a_game_that_stopped_answering_is_counted(self):
        found = launchsummary.summarise_launch([report("persisted", 0, 0, 1, [], answers={"error": "gone"})])["d0-j0"]
        self.assertEqual(found["gamesDownAfterRun"], 1)

    def test_the_planned_proxy_delay_is_averaged_over_runs(self):
        observed_a = {"toHost": {"packets": 2, "minMs": 90.0, "meanMs": 90.0, "maxMs": 90.0}, "toClient": {"packets": 0, "minMs": None, "meanMs": None, "maxMs": None}}
        observed_b = {"toHost": {"packets": 2, "minMs": 110.0, "meanMs": 110.0, "maxMs": 130.0}, "toClient": {"packets": 0, "minMs": None, "meanMs": None, "maxMs": None}}
        found = launchsummary.summarise_launch([report("persisted", 100, 0, 1, [], observed=observed_a), report("persisted", 100, 0, 2, [], observed=observed_b)])["d100-j0"]
        self.assertEqual((found["proxyMeanDelayMs"], found["proxyMaxDelayMs"]), (100.0, 130.0))

    def test_only_reports_of_the_launch_are_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            for index, launch in enumerate(("L1", "L2", "L1")):
                with open(os.path.join(directory, "r%d.json" % index), "w") as handle:
                    json.dump(report("persisted", 0, 0, index, [], launch=launch), handle)
            self.assertEqual(len(launchsummary.load_reports(directory, "L1")), 2)

    def test_the_text_lists_profiles_in_numeric_order_with_the_reappeared_runs(self):
        reports = [report("persisted", 100, 60, 1, []), report("persisted", 100, 0, 1, []), report("reappeared-after-break", 0, 0, 3, [])]
        text = launchsummary.format_summary("L1", launchsummary.summarise_launch(reports))
        positions = [text.index(label) for label in ("d0-j0:", "d100-j0:", "d100-j60:")]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("reappeared after break 1 (runs [3])", text)


if __name__ == "__main__":
    unittest.main()
