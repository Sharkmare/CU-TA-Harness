import math
import unittest

from casualtieslink import positioncontrol as control


class FakeBodyGame:
    """A link game whose local body can be held; a leaky one keeps drifting after the hold, the way a broken lock would."""

    def __init__(self, position, leaky=False, drift_per_poll=0.4, hold_works_in_status=True):
        self.position = dict(position)
        self.leaky = leaky
        self.drift_per_poll = drift_per_poll
        self.hold_works_in_status = hold_works_in_status
        self.held = None
        self.calls = []
        self.body_id = 99

    def get(self, target, path="", depth=1):
        if self.held is not None and self.leaky:
            self.position["y"] -= self.drift_per_poll
        elif self.held is None:
            self.position["y"] -= 0.0
        return dict(self.position)

    def call(self, command, **arguments):
        self.calls.append((command, arguments))
        if command == control.HOLD_COMMAND:
            self.held = {"x": arguments["x"], "y": arguments["y"], "tolerance": arguments["tolerance"]}
            if not self.leaky:
                self.position = {"x": arguments["x"], "y": arguments["y"]}
            return {"id": self.body_id, "heldWithinTolerance": False, "drift": 0.0}
        if command == control.RELEASE_COMMAND:
            released = 1 if self.held is not None else 0
            self.held = None
            return {"released": released}
        if command == control.STATUS_COMMAND:
            if self.held is None:
                return []
            drift = math.hypot(self.position["x"] - self.held["x"], self.position["y"] - self.held["y"])
            return [{"id": self.body_id, "heldWithinTolerance": self.hold_works_in_status and drift <= self.held["tolerance"], "lost": False, "maxDrift": drift, "exceededTicks": 0 if drift <= self.held["tolerance"] else 5}]
        raise AssertionError(command)

    def set(self, target, path, value):
        self.position = {"x": value["x"], "y": value["y"]}


def no_sleep(seconds):
    return None


class ValidationTests(unittest.TestCase):
    def test_points_must_be_finite_numbers(self):
        for bad in ({"x": float("nan"), "y": 0}, {"x": 0, "y": float("inf")}, {"x": "a", "y": 1}, {"y": 1}, None):
            with self.subTest(bad=bad), self.assertRaises(control.PositionControlError):
                control.validate_point(bad)

    def test_the_tolerance_must_be_inside_the_range_the_plugin_accepts(self):
        for bad in (0, -1, control.MIN_TOLERANCE / 2, control.MAX_TOLERANCE * 2, float("nan"), True, "0.1"):
            with self.subTest(bad=bad), self.assertRaises(control.PositionControlError):
                control.validate_tolerance(bad)
        self.assertEqual(control.validate_tolerance(0.05), 0.05)

    def test_a_named_or_vector_direction_becomes_a_unit_vector_and_zero_is_refused(self):
        self.assertEqual(control.direction_vector("left"), (-1.0, 0.0))
        self.assertAlmostEqual(math.hypot(*control.direction_vector((3, 4))), 1.0)
        for bad in ("sideways", (0, 0), (float("nan"), 1), [1], None):
            with self.subTest(bad=bad), self.assertRaises(control.PositionControlError):
                control.direction_vector(bad)

    def test_a_point_at_a_distance_along_a_direction(self):
        self.assertEqual(control.point_at({"x": 1, "y": 2}, "right", 3), {"x": 4.0, "y": 2.0})
        self.assertEqual(control.point_at({"x": 1, "y": 2}, "down", 5), {"x": 1.0, "y": -3.0})
        for bad in (0, -1, float("inf"), True):
            with self.subTest(bad=bad), self.assertRaises(control.PositionControlError):
                control.point_at({"x": 0, "y": 0}, "up", bad)

    def test_the_hold_sends_the_validated_target_to_the_plugin_command(self):
        game = FakeBodyGame({"x": 0, "y": 0})
        control.hold_at(game, {"x": 3, "y": 4}, 0.1)
        self.assertEqual(game.calls[0], (control.HOLD_COMMAND, {"local": True, "x": 3.0, "y": 4.0, "tolerance": 0.1}))
        with self.assertRaises(control.PositionControlError):
            control.hold_at(game, {"x": float("nan"), "y": 0})
        self.assertEqual(len(game.calls), 1)


class PlaceAndHoldTests(unittest.TestCase):
    def test_a_working_hold_verifies_with_zero_drift(self):
        game = FakeBodyGame({"x": 50, "y": 50})
        result = control.place_and_hold(game, {"x": 3, "y": 4}, sleep=no_sleep)
        self.assertTrue(result["ok"])
        self.assertEqual(result["drifts"], [0.0] * control.VERIFY_POLLS)
        self.assertTrue(result["heldWithinTolerance"])

    def test_a_lock_that_does_not_hold_fails_the_verification(self):
        game = FakeBodyGame({"x": 3, "y": 4}, leaky=True)
        result = control.place_and_hold(game, {"x": 3, "y": 4}, sleep=no_sleep)
        self.assertFalse(result["ok"])
        self.assertGreater(max(result["drifts"]), control.HOLD_TOLERANCE)

    def test_a_holder_that_reports_not_held_fails_even_when_the_polls_look_fine(self):
        game = FakeBodyGame({"x": 3, "y": 4}, hold_works_in_status=False)
        result = control.place_and_hold(game, {"x": 3, "y": 4}, sleep=no_sleep)
        self.assertFalse(result["ok"])
        self.assertFalse(result["heldWithinTolerance"])

    def test_the_verification_polls_the_position_the_stated_number_of_times(self):
        game = FakeBodyGame({"x": 0, "y": 0})
        slept = []
        control.place_and_hold(game, {"x": 0, "y": 0}, sleep=slept.append)
        self.assertEqual(slept, [control.VERIFY_INTERVAL_SECONDS] * control.VERIFY_POLLS)

    def test_release_all_sends_the_all_flag_and_a_failing_release_is_swallowed_only_when_quiet(self):
        game = FakeBodyGame({"x": 0, "y": 0})
        control.hold_at(game, {"x": 0, "y": 0})
        self.assertEqual(control.release(game), {"released": 1})
        self.assertEqual(game.calls[-1], (control.RELEASE_COMMAND, {"all": True, "local": False}))

        class Broken:
            def call(self, command, **arguments):
                raise RuntimeError("no such command")

        self.assertEqual(control.release_quietly(Broken()), {"released": None, "error": "RuntimeError"})
        with self.assertRaises(RuntimeError):
            control.release(Broken())


class PreflightTests(unittest.TestCase):
    def pair(self, host_position, client_position):
        return FakeBodyGame(host_position), FakeBodyGame(client_position)

    def test_bodies_on_target_and_apart_pass_and_the_positions_are_recorded(self):
        host, client = self.pair({"x": 20, "y": 0}, {"x": 5, "y": 0})
        check = control.preflight_pair(host, client, {"x": 20, "y": 0}, {"x": 5, "y": 0}, copy_state={"clientCopy": "Dynamic"})
        self.assertTrue(check["ok"])
        self.assertEqual((check["separation"], check["hostDrift"], check["clientDrift"], check["copyState"]), (15.0, 0.0, 0.0, {"clientCopy": "Dynamic"}))

    def test_overlapping_bodies_fail_the_check(self):
        host, client = self.pair({"x": 5.5, "y": 0}, {"x": 5, "y": 0})
        check = control.preflight_pair(host, client, {"x": 5.5, "y": 0}, {"x": 5, "y": 0})
        self.assertFalse(check["ok"])
        self.assertTrue(any("overlap" in issue for issue in check["issues"]), check["issues"])

    def test_a_body_off_its_target_fails_and_names_which_one(self):
        host, client = self.pair({"x": 20, "y": 0}, {"x": 5, "y": -35})
        check = control.preflight_pair(host, client, {"x": 20, "y": 0}, {"x": 5, "y": 0})
        self.assertFalse(check["ok"])
        self.assertTrue(any("client body is 35.000" in issue for issue in check["issues"]), check["issues"])
        self.assertFalse(any("host body" in issue for issue in check["issues"]))

    def test_a_drift_exactly_at_the_tolerance_passes_and_just_above_fails(self):
        host, client = self.pair({"x": 20, "y": 0}, {"x": 5 + control.HOLD_TOLERANCE, "y": 0})
        self.assertTrue(control.preflight_pair(host, client, {"x": 20, "y": 0}, {"x": 5, "y": 0})["ok"])
        host, client = self.pair({"x": 20, "y": 0}, {"x": 5 + control.HOLD_TOLERANCE * 1.5, "y": 0})
        self.assertFalse(control.preflight_pair(host, client, {"x": 20, "y": 0}, {"x": 5, "y": 0})["ok"])

    def test_bad_thresholds_are_refused_before_anything_is_read(self):
        host, client = self.pair({"x": 0, "y": 0}, {"x": 9, "y": 0})
        for bad in (0, -2, float("nan"), True):
            with self.subTest(bad=bad), self.assertRaises(control.PositionControlError):
                control.preflight_pair(host, client, {"x": 0, "y": 0}, {"x": 9, "y": 0}, min_separation=bad)
        self.assertEqual((host.calls, client.calls), ([], []))


class SeatPairTests(unittest.TestCase):
    def test_the_client_is_held_at_its_seat_and_the_host_is_parked_away_and_held(self):
        host, client = FakeBodyGame({"x": 0, "y": 0}), FakeBodyGame({"x": 100, "y": 100})
        check = control.seat_pair(host, client, {"x": 5, "y": 6}, "left", sleep=no_sleep)
        self.assertTrue(check["ok"], check["issues"])
        self.assertEqual(client.held["x"], 5.0)
        self.assertEqual((host.held["x"], host.held["y"]), (5.0 - control.PARK_DISTANCE, 6.0))
        self.assertEqual(check["separation"], control.PARK_DISTANCE)

    def test_a_parking_distance_below_the_minimum_separation_is_an_overlap_failure(self):
        host, client = FakeBodyGame({"x": 0, "y": 0}), FakeBodyGame({"x": 0, "y": 0})
        check = control.seat_pair(host, client, {"x": 5, "y": 6}, "left", park_distance=1.0, sleep=no_sleep)
        self.assertFalse(check["ok"])
        self.assertTrue(any("overlap" in issue for issue in check["issues"]))

    def test_a_client_lock_that_leaks_makes_the_whole_seat_invalid(self):
        host, client = FakeBodyGame({"x": 0, "y": 0}), FakeBodyGame({"x": 5, "y": 6}, leaky=True)
        check = control.seat_pair(host, client, {"x": 5, "y": 6}, "left", sleep=no_sleep)
        self.assertFalse(check["ok"])
        self.assertTrue(any("client hold did not verify" in issue for issue in check["issues"]), check["issues"])


    def test_a_holder_that_reports_not_held_invalidates_the_seat_even_when_the_positions_look_right(self):
        host, client = FakeBodyGame({"x": 0, "y": 0}), FakeBodyGame({"x": 5, "y": 6}, hold_works_in_status=False)
        check = control.seat_pair(host, client, {"x": 5, "y": 6}, "left", sleep=no_sleep)
        self.assertEqual(check["hostDrift"], 0.0)
        self.assertEqual(check["clientDrift"], 0.0)
        self.assertFalse(check["ok"])
        self.assertTrue(any("client hold did not verify" in issue for issue in check["issues"]), check["issues"])


class StartPositionTests(unittest.TestCase):
    def test_the_start_positions_are_recorded_even_when_nothing_is_held(self):
        record = control.start_positions(FakeBodyGame({"x": 1, "y": 2}), FakeBodyGame({"x": 4, "y": 6}), copy_state={"victimOnClient": "Dynamic"})
        self.assertEqual(record, {"host": {"x": 1.0, "y": 2.0}, "client": {"x": 4.0, "y": 6.0}, "separation": 5.0, "copyState": {"victimOnClient": "Dynamic"}})


if __name__ == "__main__":
    unittest.main()
