import copy
import unittest
from unittest import mock

from casualtieslink import swinggate
from tests import world_building as world

SEAT = {"x": 0.0, "y": 0.0}
TARGET = {"x": 2.85, "y": 0.0}
REST = {"limb0": {"x": 0.0, "y": 1.0}, "limb1": {"x": 0.5, "y": -0.2}}


def good_state():
    pose = {"snapshot": {"linkRead": dict(SEAT), "holder": dict(SEAT), "paths": {"rb.position": dict(SEAT)}}, "body": dict(SEAT),
            "limb0": {"x": 0.0, "y": 1.0}, "limb1": {"x": 0.5, "y": -0.2}, "isRight": True, "cooldown": 0.0}
    target = {"present": True, "health": 1000.0, "position": dict(TARGET), "hostCopy": {"bodyType": "Dynamic", "physicsActive": True}, "clientCopy": {"bodyType": "Static", "physicsActive": False}}
    return {"pose": pose, "target": target, "parked": {"linkRead": {"x": -12.0, "y": 0.0}, "holder": {"x": -12.0, "y": 0.0}, "paths": {}}}


def good_spec(**changes):
    spec = {"seat": dict(SEAT), "band": (2.5, 3.2), "rest": copy.deepcopy(REST)}
    spec.update(changes)
    return spec


def failed_gates(state, spec=None):
    verdict = swinggate.judge(state, spec or good_spec())
    return sorted({item["gate"] for item in verdict["failures"]}), verdict


class JudgeTests(unittest.TestCase):
    def test_a_swing_with_every_condition_met_passes_and_records_every_value(self):
        gates, verdict = failed_gates(good_state())
        self.assertEqual(gates, [])
        self.assertTrue(verdict["passed"])
        values = verdict["values"]
        self.assertTrue(values["seat"]["ok"])
        self.assertEqual(values["limb"]["limb1ToTarget"], 2.358)
        self.assertEqual(values["facing"], {"isRight": True, "targetIsRight": True})
        self.assertEqual(values["cooldown"], 0.0)
        self.assertEqual(values["target"]["clientCopy"]["physicsActive"], False)
        self.assertEqual(values["target"]["hostCopy"]["physicsActive"], True)
        self.assertEqual(values["distance"], 2.85)
        self.assertEqual(values["box"]["smallest"], 12.0)

    def test_a_body_off_its_seat_by_rb_position_is_never_fired(self):
        state = good_state()
        state["pose"]["snapshot"]["paths"]["rb.position"] = {"x": 0.3, "y": 0.0}
        self.assertEqual(failed_gates(state)[0], ["seat"])

    def test_a_wandering_link_read_alone_does_not_fail_the_seat_but_is_recorded(self):
        state = good_state()
        state["pose"]["snapshot"]["linkRead"] = {"x": 0.4, "y": 0.0}
        gates, verdict = failed_gates(state)
        self.assertEqual(gates, [])
        self.assertTrue(verdict["values"]["seat"]["linkReadDisagrees"])

    def test_a_limb_out_of_its_rest_pose_tolerance_is_never_fired(self):
        state = good_state()
        state["pose"]["limb1"] = {"x": 0.5, "y": -9.2}
        gates, verdict = failed_gates(state)
        self.assertEqual(gates, ["limb"])
        self.assertTrue(any("limb1 is 9.00 from its rest pose" in item["detail"] for item in verdict["failures"]))

    def test_limb_zero_is_recorded_but_does_not_gate_by_default_because_it_is_not_the_swing_origin(self):
        state = good_state()
        state["pose"]["limb0"] = {"x": 3.0, "y": 1.0}
        gates, verdict = failed_gates(state)
        self.assertEqual(gates, [])
        self.assertEqual(verdict["values"]["limb"]["limb0Moved"], 3.0)

    def test_a_profile_that_gates_limb_zero_never_fires_a_swing_with_limb_zero_out_of_place(self):
        state = good_state()
        state["pose"]["limb0"] = {"x": 3.0, "y": 1.0}
        self.assertEqual(failed_gates(state, good_spec(gatedLimbs=("limb0", "limb1")))[0], ["limb"])

    def test_a_limb_beyond_reach_of_the_target_is_never_fired_even_in_its_rest_pose(self):
        state = good_state()
        state["target"]["position"] = {"x": 9.0, "y": 0.0}
        gates, verdict = failed_gates(state)
        self.assertIn("limb", gates)
        self.assertTrue(any("limb 1 is 8.50 from the target" in item["detail"] for item in verdict["failures"]))

    def test_a_resting_limb_four_units_behind_the_target_as_in_real_landed_swings_is_in_reach(self):
        state = good_state()
        state["pose"]["limb1"] = {"x": -1.08, "y": -1.06}
        rest = copy.deepcopy(REST)
        rest["limb1"] = {"x": -1.08, "y": -1.06}
        gates, verdict = failed_gates(state, good_spec(rest=rest))
        self.assertEqual(gates, [])
        self.assertEqual(verdict["values"]["limb"]["limb1ToTarget"], 4.07)

    def test_without_a_rest_pose_nothing_is_fired(self):
        gates, verdict = failed_gates(good_state(), good_spec(rest=None))
        self.assertEqual(gates, ["limb"])
        self.assertTrue(any("no rest pose" in item["detail"] for item in verdict["failures"]))

    def test_an_unreadable_limb_is_never_taken_for_in_place(self):
        state = good_state()
        state["pose"]["limb1"] = None
        self.assertEqual(failed_gates(state)[0], ["limb"])

    def test_facing_away_from_the_target_is_never_fired(self):
        state = good_state()
        state["pose"]["isRight"] = False
        self.assertEqual(failed_gates(state)[0], ["facing"])
        state["pose"]["isRight"] = None
        self.assertEqual(failed_gates(state)[0], ["facing"])

    def test_facing_follows_the_side_of_the_target(self):
        state = good_state()
        state["target"]["position"] = {"x": -2.85, "y": 0.0}
        state["pose"]["isRight"] = False
        state["pose"]["limb1"] = {"x": 0.5, "y": -0.2}
        gates, _ = failed_gates(state, good_spec(rest=copy.deepcopy(REST)))
        self.assertNotIn("facing", gates)

    def test_a_cooldown_that_is_not_ready_is_never_fired(self):
        state = good_state()
        state["pose"]["cooldown"] = 0.12
        self.assertEqual(failed_gates(state)[0], ["cooldown"])
        state["pose"]["cooldown"] = None
        self.assertEqual(failed_gates(state)[0], ["cooldown"])

    def test_a_missing_target_or_one_without_health_is_never_fired(self):
        state = good_state()
        state["target"]["present"] = False
        self.assertIn("target", failed_gates(state)[0])
        state = good_state()
        state["target"]["health"] = 0.0
        self.assertIn("target", failed_gates(state)[0])

    def test_a_distance_outside_the_band_is_never_fired(self):
        state = good_state()
        state["target"]["position"] = {"x": 3.6, "y": 0.0}
        state["pose"]["limb1"] = {"x": 0.5, "y": -0.2}
        self.assertIn("distance", failed_gates(state)[0])
        state["target"]["position"] = {"x": 2.0, "y": 0.0}
        self.assertIn("distance", failed_gates(state)[0])

    def test_a_parked_body_inside_the_swing_box_is_never_fired(self):
        state = good_state()
        state["parked"]["linkRead"] = {"x": 4.0, "y": 0.0}
        state["parked"]["holder"] = {"x": 4.0, "y": 0.0}
        gates, verdict = failed_gates(state)
        self.assertEqual(gates, ["box"])
        self.assertEqual(verdict["values"]["box"]["smallest"], 1.15)

    def test_every_failed_gate_is_listed_not_only_the_first(self):
        state = good_state()
        state["pose"]["isRight"] = False
        state["pose"]["cooldown"] = 1.0
        self.assertEqual(failed_gates(state)[0], ["cooldown", "facing"])

    def test_the_tolerances_are_named_constants_and_the_pose_spec_can_tighten_the_limb_tolerance(self):
        self.assertEqual((swinggate.LIMB_POSE_TOLERANCE, swinggate.LIMB_REACH, swinggate.COOLDOWN_READY, swinggate.PARKED_MIN_DISTANCE), (0.5, 4.5, 0.005, 6.0))
        state = good_state()
        state["pose"]["limb1"] = {"x": 0.7, "y": -0.2}
        self.assertEqual(failed_gates(state)[0], [])
        self.assertEqual(failed_gates(state, good_spec(limbPoseTolerance=0.1))[0], ["limb"])


class SettleTests(unittest.TestCase):
    def run_settle(self, limb_positions, target=TARGET, timeout=swinggate.SETTLE_TIMEOUT_SECONDS):
        clock = [0.0]
        positions = iter(limb_positions)

        def read_pose(client, paths):
            limb = next(positions, None)
            return {"body": dict(SEAT), "limb0": {"x": 0.0, "y": 1.0}, "limb1": limb}

        with mock.patch.object(swinggate, "read_pose", read_pose):
            return swinggate.settle_limbs(mock.Mock(), [], lambda: target, sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds), now=lambda: clock[0], timeout=timeout)

    def test_limbs_that_hold_still_on_two_consecutive_reads_and_in_reach_give_the_rest_pose(self):
        record = self.run_settle([{"x": 0.5, "y": -0.2}, {"x": 0.52, "y": -0.2}])
        self.assertTrue(record["ok"])
        self.assertEqual(record["rest"]["limb1"], {"x": 0.52, "y": -0.2})
        self.assertEqual(len(record["rows"]), 2)

    def test_limbs_still_moving_after_a_teleport_are_waited_for_until_they_stop(self):
        moving = [{"x": 0.5, "y": -9.0}, {"x": 0.5, "y": -6.0}, {"x": 0.5, "y": -3.0}, {"x": 0.5, "y": -0.2}, {"x": 0.5, "y": -0.2}]
        record = self.run_settle(moving)
        self.assertTrue(record["ok"])
        self.assertEqual(len(record["rows"]), 5)

    def test_limbs_that_are_steady_but_out_of_reach_never_settle_and_the_run_is_invalid(self):
        record = self.run_settle([{"x": 0.5, "y": -9.0}] * 80)
        self.assertFalse(record["ok"])
        self.assertIsNone(record["rest"])

    def test_limbs_that_never_hold_still_time_out_without_a_rest_pose(self):
        record = self.run_settle([{"x": 0.5, "y": -0.2 - step * 0.4} for step in range(80)])
        self.assertFalse(record["ok"])
        self.assertIsNone(record["rest"])

    def test_unreadable_limbs_never_settle(self):
        record = self.run_settle([None] * 80)
        self.assertFalse(record["ok"])

    def test_the_wait_is_bounded_by_the_timeout(self):
        record = self.run_settle([{"x": 0.5, "y": -9.0}] * 200, timeout=1.0)
        self.assertFalse(record["ok"])
        self.assertLessEqual(len(record["rows"]), 8)


class GateTests(unittest.TestCase):
    def make(self, state):
        reads = {"pose": 0, "target": 0}

        def read_pose(client, paths):
            reads["pose"] += 1
            return state["pose"]

        def read_target():
            reads["target"] += 1
            return state["target"]

        gate = swinggate.Gate(good_spec(), read_target, parked_game=mock.Mock())
        patches = [mock.patch.object(swinggate, "read_pose", read_pose), mock.patch.object(swinggate.positioncontrol, "parked_snapshot", lambda game, paths: state["parked"])]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return gate, reads

    def test_every_check_reads_the_body_and_the_target_fresh(self):
        gate, reads = self.make(good_state())
        gate.check(mock.Mock())
        first = dict(reads)
        gate.check(mock.Mock())
        self.assertEqual(first["pose"], 1)
        self.assertEqual(reads["pose"], 2)
        self.assertGreater(reads["target"], first["target"])

    def test_every_check_puts_the_injected_mouse_on_the_target_and_settling_waits_for_the_body_to_turn(self):
        gate, _ = self.make(good_state())
        client = mock.Mock()
        gate.check(client)
        client.call.assert_called_with("mouse", wx=2.85, wy=0.0)
        slept = []
        client = mock.Mock()
        with mock.patch.object(swinggate, "settle_limbs", lambda *a, **k: {"ok": True, "rest": copy.deepcopy(REST), "rows": []}):
            gate.settle(client, sleep=slept.append)
        client.call.assert_called_with("mouse", wx=2.85, wy=0.0)
        self.assertEqual(slept, [swinggate.AIM_SETTLE_SECONDS])

    def test_release_clears_the_mouse_and_never_raises(self):
        gate, _ = self.make(good_state())
        client = mock.Mock()
        gate.release(client)
        client.call.assert_called_once_with("mouse", clear=True)
        client.call.side_effect = RuntimeError("link lost")
        gate.release(client)

    def test_a_target_with_no_position_is_not_aimed_at(self):
        state = good_state()
        state["target"]["position"] = None
        gate, _ = self.make(state)
        client = mock.Mock()
        self.assertFalse(gate.aim(client))
        client.call.assert_not_called()

    def test_a_limb_that_drifts_between_two_swings_fails_the_second_check_only(self):
        state = good_state()
        gate, _ = self.make(state)
        self.assertTrue(gate.check(mock.Mock())["passed"])
        state["pose"]["limb1"] = {"x": 0.5, "y": -9.2}
        self.assertFalse(gate.check(mock.Mock())["passed"])

    def test_settling_stores_the_rest_pose_in_the_spec_the_checks_use(self):
        gate, _ = self.make(good_state())
        gate.spec["rest"] = None
        with mock.patch.object(swinggate, "settle_limbs", lambda *a, **k: {"ok": True, "rest": copy.deepcopy(REST), "rows": []}):
            record = gate.settle(mock.Mock())
        self.assertTrue(record["ok"])
        self.assertEqual(gate.spec["rest"], REST)
        self.assertTrue(gate.check(mock.Mock())["passed"])


class WaitReadyTests(unittest.TestCase):
    def gate_with(self, verdicts):
        gate = swinggate.Gate(good_spec(), lambda: {})
        queue = list(verdicts)
        gate.check = lambda client: dict(queue.pop(0) if len(queue) > 1 else queue[0])
        return gate

    def passed(self):
        return {"passed": True, "failures": [], "values": {}}

    def failed(self, gate="limb"):
        return {"passed": False, "failures": [{"gate": gate, "detail": "limb1 is 3.98 from its rest pose (tolerance 0.50)"}], "values": {}}

    def run_wait(self, gate, timeout=3.0):
        clock = [0.0]
        return gate.wait_ready(mock.Mock(), sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds), now=lambda: clock[0], timeout=timeout)

    def test_a_gate_that_passes_on_the_first_read_returns_at_once_without_waiting(self):
        verdict = self.run_wait(self.gate_with([self.passed()]))
        self.assertTrue(verdict["passed"])
        self.assertEqual(verdict["waitedReads"], 0)

    def test_a_limb_still_in_recoil_is_waited_for_and_the_returned_verdict_is_the_fresh_passing_read(self):
        verdict = self.run_wait(self.gate_with([self.failed(), self.failed("seat"), self.passed()]))
        self.assertTrue(verdict["passed"])
        self.assertEqual(verdict["waitedReads"], 2)

    def test_a_gate_that_never_passes_times_out_failed_and_nothing_is_fired(self):
        verdict = self.run_wait(self.gate_with([self.failed()]), timeout=1.0)
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["failures"][0]["gate"], "limb")
        self.assertGreater(verdict["waitedReads"], 5)
        self.assertLess(verdict["waitedReads"], 20)

    def test_the_wait_is_bounded_by_the_named_timeout(self):
        self.assertEqual((swinggate.READY_TIMEOUT_SECONDS, swinggate.READY_POLL_SECONDS), (3.0, 0.1))


class RunVerdictTests(unittest.TestCase):
    def entries(self, landed=(True, True, True)):
        return [{"swing": index, "fired": True, "hostDelta": 19.3 if hit else 0.0, "clientDelta": 19.3 if hit else 0.0} for index, hit in enumerate(landed, 1)]

    def test_a_run_where_every_swing_landed_is_valid(self):
        self.assertEqual(swinggate.run_verdict(self.entries()), ("valid", ""))

    def test_a_swing_that_missed_with_every_gate_passed_is_a_fail_with_the_swing_named(self):
        verdict, reason = swinggate.run_verdict(self.entries((True, False, True)))
        self.assertEqual(verdict, "fail")
        self.assertIn("swing 2 did not land with every gate passed", reason)

    def test_a_swing_that_failed_its_gate_makes_the_run_invalid_never_a_fail(self):
        failure = {"swing": 3, "failures": [{"gate": "facing", "detail": "isRight False, target on the right"}], "values": {}}
        verdict, reason = swinggate.run_verdict(self.entries((True, True)), failure)
        self.assertEqual(verdict, "invalid")
        self.assertEqual(reason, "swing 3 not fired, gate facing failed: isRight False, target on the right")

    def test_a_gate_failure_outranks_a_miss_in_the_same_run(self):
        failure = {"swing": 3, "failures": [{"gate": "limb", "detail": "x"}], "values": {}}
        self.assertEqual(swinggate.run_verdict(self.entries((False, True)), failure)[0], "invalid")

    def test_no_swing_and_a_swing_that_did_not_fire_are_invalid(self):
        self.assertEqual(swinggate.run_verdict([])[0], "invalid")
        unfired = self.entries()
        unfired[1]["fired"] = False
        verdict, reason = swinggate.run_verdict(unfired)
        self.assertEqual((verdict, reason), ("invalid", "swing 2 did not fire"))

    def test_a_run_is_all_or_nothing_one_miss_in_many_fails_the_whole_run(self):
        verdict, _ = swinggate.run_verdict(self.entries((True,) * 19 + (False,)))
        self.assertEqual(verdict, "fail")

    def test_the_reason_names_the_gates_that_failed(self):
        failure = {"failures": [{"gate": "limb", "detail": "a"}, {"gate": "facing", "detail": "b"}, {"gate": "limb", "detail": "c"}]}
        self.assertEqual(swinggate.gate_reason(failure), "gate facing, limb failed")


class WorldActGateTests(unittest.TestCase):
    def run_act(self, verdicts, fire_result=True):
        gate = mock.Mock()
        gate.wait_ready.side_effect = verdicts
        context = {"host": mock.Mock(), "hostHandle": "id:7", "clientHandle": "id:-7", "position": {"x": 3.0, "y": 0.0}, "target": {}, "gate": gate}
        fired = []
        client = mock.Mock()
        client.get.return_value = 0.0

        def fire(game, aim, **kwargs):
            fired.append(aim)
            return fire_result

        patches = [mock.patch.object(world.hooks, "fire_one_swing", fire), mock.patch.object(world, "health_by_handle", lambda game, handle: 1000.0), mock.patch.object(world, "current_position", lambda host, ctx: {"x": 3.0, "y": 0.0}),
                   mock.patch.object(world, "collider_at", lambda game, point: None), mock.patch.object(world.evidence, "read_log", lambda which: ""), mock.patch.object(world.base, "player_position", lambda game: {"x": 0.0, "y": 0.0}),
                   mock.patch.object(world.time, "sleep", lambda seconds: None)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        world.act(client, context)
        return context, fired

    def passed(self, **values):
        return {"passed": True, "failures": [], "values": values}

    def failed(self):
        return {"passed": False, "failures": [{"gate": "limb", "detail": "limb1 is 9.00 from its rest pose (tolerance 0.50)"}], "values": {"limb": {"limb1Moved": 9.0}}}

    def test_a_swing_that_fails_the_gate_is_not_fired_and_no_later_swing_is_tried(self):
        context, fired = self.run_act([self.passed(), self.passed(), self.failed()])
        self.assertEqual(len(fired), 2)
        self.assertEqual(len(context["measurements"]), 2)
        self.assertEqual(context["gateFailure"]["swing"], 3)
        self.assertEqual(context["gateFailure"]["values"], {"limb": {"limb1Moved": 9.0}})

    def test_the_gate_values_at_fire_time_are_kept_in_every_swing_record(self):
        context, fired = self.run_act([self.passed(seat=1), self.passed(seat=2), self.passed(seat=3), self.passed(seat=4), self.passed(seat=5)])
        self.assertEqual([entry["gate"]["values"] for entry in context["measurements"]], [{"seat": 1}, {"seat": 2}, {"seat": 3}, {"seat": 4}, {"seat": 5}])
        self.assertNotIn("gateFailure", context)

    def test_a_gate_failure_on_the_first_swing_fires_nothing_and_leaves_no_measurement(self):
        context, fired = self.run_act([self.failed()])
        self.assertEqual(fired, [])
        self.assertEqual(context["measurements"], [])
        self.assertEqual(swinggate.run_verdict(context["measurements"], context["gateFailure"])[0], "invalid")

    def test_a_swing_fired_with_every_gate_passed_that_did_not_land_is_classified_a_fail(self):
        context, fired = self.run_act([self.passed()] * 5)
        self.assertEqual(len(context["measurements"]), 5)
        verdict, reason = swinggate.run_verdict(context["measurements"], context.get("gateFailure"))
        self.assertEqual(verdict, "fail")
        self.assertIn("swing 1 did not land with every gate passed", reason)


if __name__ == "__main__":
    unittest.main()
