import json
import os
import tempfile
import unittest

from casualtieslink import miningsummary


def report(verdict="persisted", repetition=1, swings=4, accepted=4, host_steps=3, client_steps=2, positions=None):
    positions = positions or [(1.0, 0.0), (2.0, 0.0)]
    listed = [{"aim": {"x": 0.0, "y": 0.0}, "clientPosition": {"x": x, "y": y}} for x, y in positions][:swings]
    return {"verdict": verdict, "repetition": repetition, "block": {"position": {"x": 0.0, "y": 0.0}}, "swings": {"list": listed, "acceptedCount": accepted},
            "crackSteps": {"host": [1.0] * host_steps, "client": [1.0] * client_steps}, "hostLog": {"applied": 0, "dropped": 0},
            "findings": {"host": {"brokeAt": 1.0 if host_steps else None, "presentAtEnd": not host_steps, "reappeared": []}, "client": {"brokeAt": None, "presentAtEnd": True, "reappeared": []}}}


class RowTests(unittest.TestCase):
    def test_a_broken_block_run_has_its_counts_and_no_cause(self):
        row = miningsummary.summarise_report(report())
        self.assertEqual((row["swingsFired"], row["swingsAcceptedByHost"], row["hostCrackSteps"], row["clientCrackSteps"]), (2, 4, 3, 2))
        self.assertIsNone(row["cause"])
        self.assertEqual((row["firstDistance"], row["distanceMax"]), (1.0, 2.0))

    def test_a_never_broke_run_with_no_crack_anywhere_names_that_as_the_cause(self):
        row = miningsummary.summarise_report(report("never-broke", host_steps=0, client_steps=0, accepted=0, positions=[(2.0, 0.0), (40.0, 0.0)]))
        self.assertIn("no crack step", row["cause"])
        self.assertIn("ended 40.0 from the block", row["cause"])

    def test_a_client_only_crack_is_reported_as_not_shown(self):
        row = miningsummary.summarise_report(report("never-broke", host_steps=0, client_steps=2))
        self.assertIn("not shown why", row["cause"])

    def test_counts_split_persisted_never_broke_and_other(self):
        rows = [miningsummary.summarise_report(report(v, i)) for i, v in enumerate(["persisted", "persisted", "never-broke", "reverted"], 1)]
        self.assertEqual(miningsummary.counts(rows), {"runs": 4, "invalid": 0, "persisted": 2, "neverBroke": 1, "other": ["reverted"], "reappeared": 0})

    def test_runs_whose_preflight_failed_are_invalid_and_left_out_of_the_other_counts(self):
        good = miningsummary.summarise_report(report("persisted", 1))
        bad = miningsummary.summarise_report(dict(report("never-broke", 2, host_steps=0, client_steps=0), positionControl={"ok": False, "issues": ["the bodies are 0.4 apart: they overlap"]}))
        unrecorded = miningsummary.summarise_report(report("persisted", 3))
        self.assertIsNone(unrecorded["preflightOk"])
        self.assertFalse(bad["preflightOk"])
        self.assertEqual(bad["preflightIssues"], ["the bodies are 0.4 apart: they overlap"])
        self.assertEqual(miningsummary.counts([good, bad, unrecorded]), {"runs": 2, "invalid": 1, "persisted": 2, "neverBroke": 0, "other": [], "reappeared": 0})

    def test_the_start_positions_of_a_run_are_carried_into_its_row(self):
        data = dict(report(), startPositions={"host": {"x": 1.0, "y": 2.0}, "client": {"x": 4.0, "y": 6.0}, "separation": 5.0})
        self.assertEqual(miningsummary.summarise_report(data)["startPositions"]["separation"], 5.0)

    def test_a_directory_is_read_in_repetition_order(self):
        with tempfile.TemporaryDirectory() as directory:
            for repetition in (3, 1, 2):
                with open(os.path.join(directory, "v2check_dig_cracks__x_r%d__1.json" % repetition), "w", encoding="utf-8") as handle:
                    json.dump(report(repetition=repetition), handle)
            rows = miningsummary.summarise_directory(directory)
        self.assertEqual([row["repetition"] for row in rows], [1, 2, 3])

    def test_the_end_time_comes_from_the_file_name_and_the_duration_from_the_last_sample(self):
        data = report()
        data["samples"] = [{"t": 0.0}, {"t": 12.5}]
        row = miningsummary.summarise_report(data, "x/v2check_dig_cracks__a__d100-j0_r3__083532.json")
        self.assertEqual((row["endLocalSeconds"], row["durationSeconds"]), (8 * 3600 + 35 * 60 + 32, 12.5))

    def test_a_path_without_a_time_stamp_gives_none(self):
        row = miningsummary.summarise_report(report(), "x/other.json")
        self.assertIsNone(row["endLocalSeconds"])

    def test_a_report_without_swings_does_not_crash(self):
        row = miningsummary.summarise_report({"verdict": "never-broke", "repetition": 1})
        self.assertEqual(row["swingsFired"], 0)
        self.assertIsNone(row["firstDistance"])


if __name__ == "__main__":
    unittest.main()
