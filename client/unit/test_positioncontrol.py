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
            return [{"id": self.body_id, "position": dict(self.position), "heldWithinTolerance": self.hold_works_in_status and drift <= self.held["tolerance"], "lost": False, "maxDrift": drift, "exceededTicks": 0 if drift <= self.held["tolerance"] else 5}]
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


class SeatRetryTests(unittest.TestCase):
    def test_a_seat_that_fails_once_and_then_verifies_is_ok_and_keeps_the_first_issues(self):
        host, client = FakeBodyGame({"x": 0, "y": 0}), FakeBodyGame({"x": 5, "y": 6})
        real = host.call
        state = {"holds": 0}

        def flaky(command, **arguments):
            result = real(command, **arguments)
            if command == control.HOLD_COMMAND:
                state["holds"] += 1
                if state["holds"] == 1:
                    host.position = {"x": arguments["x"] + 0.7, "y": arguments["y"]}
            return result

        host.call = flaky
        check = control.seat_pair(host, client, {"x": 5, "y": 6}, "left", sleep=no_sleep)
        self.assertTrue(check["ok"], check["issues"])
        self.assertEqual(check["seatAttempts"], 2)
        self.assertEqual(len(check["earlierAttemptIssues"]), 1)
        self.assertTrue(any("host" in issue for issue in check["earlierAttemptIssues"][0]))

    def test_a_lock_that_keeps_leaking_fails_every_attempt(self):
        host, client = FakeBodyGame({"x": 0, "y": 0}), FakeBodyGame({"x": 5, "y": 6}, leaky=True)
        check = control.seat_pair(host, client, {"x": 5, "y": 6}, "left", sleep=no_sleep)
        self.assertFalse(check["ok"])
        self.assertEqual(check["seatAttempts"], control.SEAT_ATTEMPTS)
        self.assertEqual(len(check["earlierAttemptIssues"]), control.SEAT_ATTEMPTS - 1)

    def test_a_first_time_seat_reports_one_attempt(self):
        host, client = FakeBodyGame({"x": 0, "y": 0}), FakeBodyGame({"x": 5, "y": 6})
        check = control.seat_pair(host, client, {"x": 5, "y": 6}, "left", sleep=no_sleep)
        self.assertEqual((check["seatAttempts"], check["earlierAttemptIssues"]), (1, []))


class SilentPathsGame(FakeBodyGame):
    """Answers only the listed extra paths, the way a game with a different object layout would."""

    def __init__(self, position, answers=(), **kwargs):
        super().__init__(position, **kwargs)
        self.answers = tuple(answers)

    def get(self, target, path="", depth=1):
        if path in control.DIAGNOSTIC_PATHS and path not in self.answers:
            raise RuntimeError("no member named " + path)
        return super().get(target, path, depth)


class ParkedHostTests(unittest.TestCase):
    def wander(self, body, offset):
        real = body.call

        def moved(command, **arguments):
            result = real(command, **arguments)
            if command == control.HOLD_COMMAND:
                body.position = {"x": arguments["x"] + offset, "y": arguments["y"]}
            return result

        body.call = moved

    def test_the_tolerances_are_named_constants(self):
        self.assertEqual((control.HOLD_TOLERANCE, control.PARKED_TOLERANCE), (0.05, 0.5))

    def test_the_default_policy_holds_and_checks_the_parked_host_as_strictly_as_the_client(self):
        host, client = FakeBodyGame({"x": 0, "y": 0}), FakeBodyGame({"x": 5, "y": 6})
        self.wander(host, 0.3)
        check = control.seat_pair(host, client, {"x": 5, "y": 6}, "left", sleep=no_sleep)
        self.assertFalse(check["ok"])
        self.assertTrue(any("the host body is" in issue and "tolerance 0.050" in issue for issue in check["issues"]), check["issues"])
        self.assertEqual(check["parkedHost"]["policy"], control.PARKED_STRICT)
        self.assertEqual(check["parkedHost"]["tolerance"], control.HOLD_TOLERANCE)

    def test_the_recorded_policy_never_fails_the_seat_on_the_parked_host_drift_but_records_it(self):
        host, client = FakeBodyGame({"x": 0, "y": 0}), FakeBodyGame({"x": 5, "y": 6})
        self.wander(host, 0.7)
        check = control.seat_pair(host, client, {"x": 5, "y": 6}, "left", sleep=no_sleep, parked_policy=control.PARKED_RECORDED)
        self.assertTrue(check["ok"], check["issues"])
        self.assertEqual(check["seatAttempts"], 1)
        parked = check["parkedHost"]
        self.assertEqual(parked["policy"], control.PARKED_RECORDED)
        self.assertEqual(parked["tolerance"], control.PARKED_TOLERANCE)
        self.assertEqual(parked["rawDriftReads"], [0.7] * control.VERIFY_POLLS)
        self.assertEqual((parked["largestRead"], parked["driftNow"]), (0.7, 0.7))
        self.assertEqual(parked["target"], {"x": 5.0 - control.PARK_DISTANCE, "y": 6.0})
        self.assertEqual(host.held["tolerance"], control.PARKED_TOLERANCE)

    def test_the_client_is_held_to_the_strict_tolerance_under_both_policies(self):
        for policy in (control.PARKED_STRICT, control.PARKED_RECORDED):
            host, client = FakeBodyGame({"x": 0, "y": 0}), FakeBodyGame({"x": 5, "y": 6})
            self.wander(client, 0.3)
            check = control.seat_pair(host, client, {"x": 5, "y": 6}, "left", sleep=no_sleep, parked_policy=policy)
            self.assertFalse(check["ok"], policy)
            self.assertEqual(check["tolerance"], control.HOLD_TOLERANCE)
            client_holds = [arguments["tolerance"] for command, arguments in client.calls if command == control.HOLD_COMMAND]
            self.assertEqual(client_holds, [control.HOLD_TOLERANCE] * control.SEAT_ATTEMPTS, policy)
            self.assertTrue(any("the client body is" in issue and "tolerance 0.050" in issue for issue in check["issues"]), check["issues"])

    def test_the_recorded_policy_keeps_a_snapshot_of_the_parked_host_at_every_verification_poll(self):
        host, client = FakeBodyGame({"x": 0, "y": 0}), FakeBodyGame({"x": 5, "y": 6})
        check = control.seat_pair(host, client, {"x": 5, "y": 6}, "left", sleep=no_sleep, parked_policy=control.PARKED_RECORDED)
        observations = check["parkedHost"]["observations"]
        self.assertEqual(len(observations), control.VERIFY_POLLS)
        for snapshot in observations:
            self.assertEqual(snapshot["linkRead"], {"x": 5.0 - control.PARK_DISTANCE, "y": 6.0})
            self.assertEqual(snapshot["holder"], {"x": 5.0 - control.PARK_DISTANCE, "y": 6.0})
            self.assertEqual(sorted(snapshot["paths"]), sorted(check["parkedHost"]["paths"]))
        self.assertIsNotNone(check["parkedHost"]["afterPreflight"])

    def test_an_unknown_policy_is_refused(self):
        host, client = FakeBodyGame({"x": 0, "y": 0}), FakeBodyGame({"x": 5, "y": 6})
        with self.assertRaises(control.PositionControlError):
            control.seat_pair(host, client, {"x": 5, "y": 6}, "left", sleep=no_sleep, parked_policy="loose")

    def test_only_the_paths_the_game_answers_are_discovered_and_read(self):
        game = SilentPathsGame({"x": 1, "y": 2}, answers=("rb.position", "rb.velocity"))
        paths = control.discover_diagnostic_paths(game)
        self.assertEqual(paths, ["rb.position", "rb.velocity"])
        snapshot = control.parked_snapshot(game, paths)
        self.assertEqual(sorted(snapshot["paths"]), ["rb.position", "rb.velocity"])
        self.assertEqual(snapshot["linkRead"], {"x": 1.0, "y": 2.0})
        self.assertIsNone(snapshot["holder"])

    def test_the_holder_position_comes_from_the_status_row(self):
        game = FakeBodyGame({"x": 1, "y": 2})
        game.call(control.HOLD_COMMAND, x=1, y=2, tolerance=0.5, local=True)
        game.call = lambda command, **arguments: [{"position": {"x": 3.0, "y": 4.0}}]
        self.assertEqual(control.holder_position(game), {"x": 3.0, "y": 4.0})
        game.call = lambda command, **arguments: []
        self.assertIsNone(control.holder_position(game))

    def test_the_closest_approach_uses_the_nearest_readable_position_and_names_the_read(self):
        snapshot = {"linkRead": {"x": 0.0, "y": 0.0}, "holder": {"x": 10.0, "y": 0.0}, "paths": {"rb.position": {"x": 4.0, "y": 0.0}, "rb.velocity": {"x": 100.0, "y": 0.0}}}
        self.assertEqual(control.closest_approach(snapshot, [{"x": 20.0, "y": 0.0}]), {"distance": 10.0, "source": "holder"})
        self.assertEqual(control.closest_approach(snapshot, [{"x": -3.0, "y": 0.0}]), {"distance": 3.0, "source": "linkRead"})
        self.assertEqual(control.closest_approach(snapshot, [{"x": 4.5, "y": 0.0}, {"x": 99.0, "y": 0.0}]), {"distance": 0.5, "source": "rb.position"})
        self.assertIsNone(control.closest_approach({"linkRead": None, "holder": None, "paths": {}}, [{"x": 0.0, "y": 0.0}]))


def view(holder, rb, link=None, target=None):
    return {"holder": holder, "linkRead": link if link is not None else holder, "paths": {"rb.position": rb}}


TARGET = {"x": 5.0, "y": 6.0}


class OffsetGame(FakeBodyGame):
    """A held body whose link read, rb.position or holder view can each be moved off the target."""

    def __init__(self, position, link_offset=0.0, rb_offset=0.0, holder_offset=0.0):
        super().__init__(position)
        self.link_offset, self.rb_offset, self.holder_offset = link_offset, rb_offset, holder_offset

    def get(self, target, path="", depth=1):
        point = super().get(target, path, depth)
        offset = self.rb_offset if path == "rb.position" else self.link_offset
        return {"x": point["x"] + offset, "y": point["y"]}

    def call(self, command, **arguments):
        result = super().call(command, **arguments)
        if command == control.STATUS_COMMAND and result:
            result[0]["position"] = {"x": result[0]["position"]["x"] + self.holder_offset, "y": result[0]["position"]["y"]}
        return result


class JudgeSeatTests(unittest.TestCase):
    def test_a_seat_where_the_holder_and_rb_agree_with_the_target_is_ok_even_when_the_link_read_wandered(self):
        judgment = control.judge_seat(view({"x": 5.0, "y": 6.0}, {"x": 5.01, "y": 6.0}, link={"x": 5.4, "y": 6.0}), TARGET)
        self.assertTrue(judgment["ok"], judgment["issues"])
        self.assertTrue(judgment["linkReadDisagrees"])
        self.assertEqual(judgment["linkDrift"], 0.4)

    def test_a_seat_is_refused_when_rb_position_is_off_even_if_the_link_read_and_holder_look_fine(self):
        judgment = control.judge_seat(view({"x": 5.0, "y": 6.0}, {"x": 5.3, "y": 6.0}, link={"x": 5.0, "y": 6.0}), TARGET)
        self.assertFalse(judgment["ok"])
        self.assertTrue(any("rb.position is 0.300" in issue for issue in judgment["issues"]), judgment["issues"])
        self.assertFalse(judgment["linkReadDisagrees"])

    def test_a_seat_is_refused_when_the_holder_view_is_off(self):
        judgment = control.judge_seat(view({"x": 5.2, "y": 6.0}, {"x": 5.0, "y": 6.0}), TARGET)
        self.assertFalse(judgment["ok"])
        self.assertTrue(any("holder's view is 0.200" in issue for issue in judgment["issues"]), judgment["issues"])

    def test_a_seat_is_refused_when_the_holder_and_rb_disagree_with_each_other_but_both_are_near_the_target(self):
        judgment = control.judge_seat(view({"x": 4.97, "y": 6.0}, {"x": 5.04, "y": 6.0}), TARGET, tolerance=0.05)
        self.assertFalse(judgment["ok"])
        self.assertTrue(any("apart" in issue for issue in judgment["issues"]), judgment["issues"])

    def test_a_seat_is_refused_when_the_holder_view_or_rb_position_cannot_be_read(self):
        self.assertFalse(control.judge_seat({"holder": None, "linkRead": TARGET, "paths": {"rb.position": TARGET}}, TARGET)["ok"])
        self.assertFalse(control.judge_seat({"holder": TARGET, "linkRead": TARGET, "paths": {}}, TARGET)["ok"])

    def test_the_tolerance_is_the_strict_default(self):
        self.assertEqual(control.judge_seat.__defaults__[0], control.HOLD_TOLERANCE)
        self.assertEqual(control.verify_swinging_body.__defaults__[0], control.HOLD_TOLERANCE)


class VerifySwingingBodyTests(unittest.TestCase):
    def test_a_held_body_whose_link_read_wanders_is_verified_and_the_disagreement_is_recorded(self):
        game = OffsetGame({"x": 0, "y": 0}, link_offset=0.4)
        result = control.seat_swinging_body(game, TARGET, paths=["rb.position"], sleep=no_sleep)
        self.assertTrue(result["ok"], result["issues"])
        self.assertTrue(result["linkReadDisagrees"])
        self.assertEqual(result["linkDrifts"], [0.4] * control.VERIFY_POLLS)
        self.assertEqual(result["drifts"], result["linkDrifts"])

    def test_a_held_body_whose_rb_position_is_off_is_not_verified(self):
        game = OffsetGame({"x": 0, "y": 0}, rb_offset=0.3)
        result = control.seat_swinging_body(game, TARGET, paths=["rb.position"], sleep=no_sleep)
        self.assertFalse(result["ok"])
        self.assertTrue(any("rb.position" in issue for issue in result["issues"]))

    def test_one_bad_reading_among_good_ones_fails_the_seat(self):
        game = OffsetGame({"x": 0, "y": 0})
        control.hold_at(game, TARGET)
        readings = iter([0.0, 0.0, 0.4, 0.0])
        real = game.get

        def get(target, path="", depth=1):
            point = real(target, path, depth)
            return {"x": point["x"] + (next(readings) if path == "rb.position" else 0.0), "y": point["y"]}

        game.get = get
        result = control.verify_swinging_body(game, TARGET, paths=["rb.position"], sleep=no_sleep)
        self.assertFalse(result["ok"])


class PreflightViewsTests(unittest.TestCase):
    def test_a_swinging_victim_is_never_judged_by_distance_only(self):
        host, client = OffsetGame({"x": 0, "y": 0}, rb_offset=0.4), OffsetGame({"x": 5, "y": 6})
        control.hold_at(host, {"x": -7.0, "y": 6.0})
        control.hold_at(client, TARGET)
        check = control.preflight_views(host, client, {"x": -7.0, "y": 6.0}, TARGET, control.ROLE_SWINGING, ["rb.position"], ["rb.position"], sleep=no_sleep)
        self.assertFalse(check["ok"])
        self.assertTrue(any(issue.startswith("the victim seat did not verify") for issue in check["issues"]), check["issues"])
        self.assertGreater(check["separation"], 6.0)

    def test_the_client_that_swings_is_verified_by_the_holder_and_rb_not_by_distance(self):
        host, client = OffsetGame({"x": 0, "y": 0}), OffsetGame({"x": 5, "y": 6}, rb_offset=0.3)
        control.hold_at(host, {"x": -7.0, "y": 6.0})
        control.hold_at(client, TARGET)
        check = control.preflight_views(host, client, {"x": -7.0, "y": 6.0}, TARGET, control.ROLE_PARKED, ["rb.position"], ["rb.position"], sleep=no_sleep)
        self.assertFalse(check["ok"])
        self.assertTrue(any(issue.startswith("the client seat did not verify") for issue in check["issues"]), check["issues"])

    def test_a_parked_host_with_wandering_reads_never_fails_the_preflight_and_its_reads_are_recorded(self):
        host, client = OffsetGame({"x": 0, "y": 0}, link_offset=0.9, rb_offset=0.9, holder_offset=0.9), OffsetGame({"x": 5, "y": 6})
        control.hold_at(host, {"x": -7.0, "y": 6.0})
        control.hold_at(client, TARGET)
        check = control.preflight_views(host, client, {"x": -7.0, "y": 6.0}, TARGET, control.ROLE_PARKED, ["rb.position"], ["rb.position"], sleep=no_sleep)
        self.assertTrue(check["ok"], check["issues"])
        self.assertEqual(len(check["parkedHost"]["reads"]), control.VERIFY_POLLS)
        self.assertNotIn("hostSeat", check)
        self.assertTrue(check["clientSeat"]["ok"])

    def test_a_client_whose_link_read_wanders_but_whose_holder_and_rb_agree_passes_with_the_disagreement_recorded(self):
        host, client = OffsetGame({"x": 0, "y": 0}), OffsetGame({"x": 5, "y": 6}, link_offset=0.25)
        control.hold_at(host, {"x": -7.0, "y": 6.0})
        control.hold_at(client, TARGET)
        check = control.preflight_views(host, client, {"x": -7.0, "y": 6.0}, TARGET, control.ROLE_PARKED, ["rb.position"], ["rb.position"], sleep=no_sleep)
        self.assertTrue(check["ok"], check["issues"])
        self.assertTrue(check["clientSeat"]["linkReadDisagrees"])
        self.assertEqual(check["clientDrift"], 0.25)

    def test_an_unknown_host_role_is_refused(self):
        with self.assertRaises(control.PositionControlError):
            control.preflight_views(FakeBodyGame({"x": 0, "y": 0}), FakeBodyGame({"x": 5, "y": 6}), TARGET, TARGET, "idle")


class ParkedDistanceTests(unittest.TestCase):
    def snapshot(self, x):
        return {"linkRead": {"x": x, "y": 0.0}, "holder": {"x": x, "y": 0.0}, "paths": {"rb.position": {"x": x, "y": 0.0}}}

    def test_a_parked_body_that_stays_far_has_no_problem_and_the_smallest_distance_is_reported(self):
        problems, smallest = control.parked_distance_problems([("a", self.snapshot(-10.0)), ("b", self.snapshot(-8.0))], [{"x": 0.0, "y": 0.0}], 6.0)
        self.assertEqual((problems, smallest), ([], 8.0))

    def test_a_close_reading_or_an_unreadable_one_is_a_problem(self):
        problems, smallest = control.parked_distance_problems([("a", self.snapshot(-10.0)), ("b", self.snapshot(-5.0)), ("c", None)], [{"x": 0.0, "y": 0.0}], 6.0)
        self.assertEqual(smallest, 5.0)
        self.assertEqual(len(problems), 2)
        self.assertIn("at b", problems[0])


class StartPositionTests(unittest.TestCase):
    def test_the_start_positions_are_recorded_even_when_nothing_is_held(self):
        record = control.start_positions(FakeBodyGame({"x": 1, "y": 2}), FakeBodyGame({"x": 4, "y": 6}), copy_state={"victimOnClient": "Dynamic"})
        self.assertEqual(record, {"host": {"x": 1.0, "y": 2.0}, "client": {"x": 4.0, "y": 6.0}, "separation": 5.0, "copyState": {"victimOnClient": "Dynamic"}})


if __name__ == "__main__":
    unittest.main()
