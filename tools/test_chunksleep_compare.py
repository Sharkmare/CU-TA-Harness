import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import chunksleep_compare as compare


def row(identifier, active, hot, name="medcrate"):
    return [identifier, name, 0.0, 0.0, 1, not active, active, True, hot]


def report(states_by_sample):
    samples = []
    for name, rows in states_by_sample.items():
        samples.append({"name": name, "machines": {"host": {"rows": rows, "unsettledTotal": 0}}})
    return {"build": "x", "samples": samples, "groups": {"g": {"ids": [1, 2, 3]}}}


class CompareTests(unittest.TestCase):

    def test_identical_reports_have_no_differences(self):
        a = report({"s": [row(1, True, True), row(2, False, False), row(3, False, False)]})
        b = report({"s": [row(1, True, True), row(2, False, False), row(3, False, False)]})
        self.assertEqual(compare.compare_reports(a, b), [])

    def test_a_wrongly_skipped_chunk_is_a_difference_and_names_the_first_object(self):
        a = report({"s": [row(1, True, True), row(2, True, True), row(3, False, False)]})
        b = report({"s": [row(1, True, True), row(2, False, True), row(3, False, False)]})
        differences = compare.compare_reports(a, b)
        self.assertEqual(len(differences), 1)
        self.assertEqual(differences[0]["firstDivergence"], {"index": 1, "baseline": True, "candidate": False})

    def test_a_hot_object_that_is_off_breaks_the_invariant(self):
        entry = {"rows": [row(1, True, True), row(2, False, True), row(3, False, False)]}
        self.assertEqual([found[0] for found in compare.invariant_violations(entry)], [2])

    def test_a_cold_object_that_is_off_does_not_break_the_invariant(self):
        self.assertEqual(compare.invariant_violations({"rows": [row(1, False, False)]}), [])

    def test_an_unwatched_label_is_counted_apart(self):
        entry = {"rows": [row(1, True, True)]}
        self.assertEqual(compare.summarize_group(compare.group_states(entry, [1, 99])), {"awake": 1, "asleep": 0, "unwatched": 1})

    def test_a_client_copy_is_matched_by_base_name_and_place(self):
        entry = {"rows": [[77, "SyncInfo(building, id: 62, res: medcrate)", 5.2, 3.1, 1, False, True, None, True]]}
        states = compare.group_states(entry, [1], [("medcrate(Clone)", 5.0, 3.0)])
        self.assertEqual(states, [True])

    def test_a_client_object_too_far_from_the_reference_is_unwatched(self):
        entry = {"rows": [[77, "SyncInfo(building, id: 62, res: medcrate)", 9.0, 3.0, 1, False, True, None, True]]}
        self.assertEqual(compare.group_states(entry, [1], [("medcrate(Clone)", 5.0, 3.0)]), [None])

    def test_an_object_one_machine_does_not_watch_is_not_a_divergence(self):
        self.assertIsNone(compare.first_divergence([True, None], [True, False]))

    def test_settle_time_is_the_last_poll_with_a_hot_object_off(self):
        trace = [{"t": 0.1, "host": {"hotOff": 5}}, {"t": 0.4, "host": {"hotOff": 2}}, {"t": 0.7, "host": {"hotOff": 0}}, {"t": 1.0, "host": {"hotOff": 0}}]
        self.assertEqual(compare.settle_time(trace, "host"), (0.4, 5))

    def test_a_trace_that_ends_with_hot_objects_off_never_settles(self):
        trace = [{"t": 0.1, "host": {"hotOff": 3}}, {"t": 0.9, "host": {"hotOff": 1}}]
        self.assertEqual(compare.settle_time(trace, "host"), (None, 3))


if __name__ == "__main__":
    unittest.main()
