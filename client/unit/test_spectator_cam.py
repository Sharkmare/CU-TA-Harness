import os
import tempfile
import unittest
from unittest import mock

from casualtieslink import desync, instances
from scenarios import desync_scenarios as scenarios
from scenarios import spectator_cam as cam
from live import test_desync

DEAD_BODY = {"x": 0.0, "y": 0.0}


def sample(t, camera, target, frame=1, dead=DEAD_BODY):
    def gap(first, second):
        return round(((first["x"] - second["x"]) ** 2 + (first["y"] - second["y"]) ** 2) ** 0.5, 2)

    return {"t": t, "camera": camera, "target": target, "deadBody": dead, "cameraToTarget": gap(camera, target), "cameraToDeadBody": gap(camera, dead),
            "targetToDeadBody": gap(target, dead), "spectatorModeActive": True, "targetNonNull": True, "customLookPos": None, "frame": frame, "focused": True}


def phase(camera_x_by_step, target, start_frame=1):
    return [sample(0.25 * index, {"x": x, "y": 0.0}, target, frame=start_frame + index) for index, x in enumerate(camera_x_by_step)]


class VerdictTests(unittest.TestCase):
    def test_a_camera_that_goes_to_the_target_and_follows_the_jump_is_follows(self):
        first = phase([0.0, 6.0, 11.0, 14.0, 15.0], {"x": 15.0, "y": 0.0})
        second = phase([15.0, 25.0, 35.0, 42.0, 44.0], {"x": 45.0, "y": 0.0}, 10)
        result = cam.verdict_from(first, second)
        self.assertEqual(result["verdict"], cam.FOLLOWS, result)
        self.assertTrue(result["cameraMovedFirstPhase"] and result["cameraMovedAfterJump"] and result["framesAdvanced"])

    def test_a_camera_that_had_already_caught_up_before_the_first_sample_after_the_jump_is_still_follows_because_it_relocated(self):
        first = phase([14.0, 15.0, 15.0, 15.0], {"x": 15.0, "y": 0.0})
        second = phase([44.3, 44.3, 44.3, 44.3], {"x": 45.0, "y": 0.0}, 10)
        result = cam.verdict_from(first, second)
        self.assertEqual(result["verdict"], cam.FOLLOWS, result)
        self.assertTrue(result["cameraRelocatedAcrossTheJump"])

    def test_a_camera_that_never_left_the_first_target_is_not_follows_after_a_far_jump(self):
        first = phase([15.0, 15.0, 15.0], {"x": 15.0, "y": 0.0})
        far_target = phase([15.0, 15.0, 15.0], {"x": 45.0, "y": 0.0}, 10)
        self.assertNotEqual(cam.verdict_from(first, far_target)["verdict"], cam.FOLLOWS)

    def test_the_jump_is_sampled_from_the_instant_it_happens(self):
        host, client = mock.Mock(), mock.Mock()
        calls = []
        with mock.patch.object(cam, "move_host", lambda h, pocket, settle=True: calls.append(settle)):
            cam.move_host(host, {"x": 1.0, "y": 1.0}, settle=False)
        self.assertEqual(calls, [False])

    def test_a_camera_that_stays_at_the_dead_body_while_the_target_is_far_is_the_bug(self):
        first = phase([0.0, 0.0, 0.1, 0.0, 0.0], {"x": 15.0, "y": 0.0})
        second = phase([0.0, 0.0, 0.0, 0.0, 0.0], {"x": 45.0, "y": 0.0}, 10)
        result = cam.verdict_from(first, second)
        self.assertEqual(result["verdict"], cam.BUG_PRESENT, result)
        self.assertFalse(result["cameraMovedAfterJump"] and result["cameraMovedFirstPhase"])

    def test_a_camera_that_follows_the_first_target_but_does_not_catch_the_jump_is_inconclusive(self):
        first = phase([0.0, 8.0, 14.0, 15.0, 15.0], {"x": 15.0, "y": 0.0})
        second = phase([15.0, 16.0, 17.0, 18.0, 19.0], {"x": 45.0, "y": 0.0}, 10)
        self.assertEqual(cam.verdict_from(first, second)["verdict"], cam.INCONCLUSIVE)

    def test_a_camera_that_ends_far_from_both_is_inconclusive_not_a_pass_or_a_bug(self):
        first = phase([30.0, 30.0, 30.0, 30.0], {"x": 15.0, "y": 0.0})
        second = phase([30.0, 30.0, 30.0, 30.0], {"x": 45.0, "y": 0.0}, 10)
        self.assertEqual(cam.verdict_from(first, second)["verdict"], cam.INCONCLUSIVE)

    def test_a_follow_needs_the_distance_to_shrink_after_the_jump(self):
        first = phase([14.0, 15.0, 15.0], {"x": 15.0, "y": 0.0})
        second = phase([44.0, 44.5, 44.9], {"x": 45.0, "y": 0.0}, 10)
        self.assertEqual(cam.verdict_from(first, second)["verdict"], cam.FOLLOWS)
        flat = phase([15.0, 15.0, 15.0], {"x": 15.0, "y": 0.0})
        stuck_at_target_that_did_not_move = phase([15.0, 15.0, 15.0], {"x": 15.0, "y": 0.0}, 10)
        self.assertNotEqual(cam.verdict_from(flat, stuck_at_target_that_did_not_move)["verdict"], cam.FOLLOWS)

    def test_the_bug_is_not_called_when_the_target_is_not_far_enough_from_the_camera(self):
        first = phase([0.0, 0.0, 0.0], {"x": 6.0, "y": 0.0})
        second = phase([0.0, 0.0, 0.0], {"x": 8.0, "y": 0.0}, 10)
        self.assertEqual(cam.verdict_from(first, second)["verdict"], cam.INCONCLUSIVE)

    def test_missing_positions_make_the_verdict_invalid(self):
        broken = [dict(sample(0.0, {"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}), camera=None, cameraToTarget=None, cameraToDeadBody=None)]
        self.assertEqual(cam.verdict_from(broken, broken)["verdict"], cam.INVALID)
        self.assertEqual(cam.verdict_from([], [])["verdict"], cam.INVALID)

    def test_the_two_rules_cannot_both_fire(self):
        first = phase([0.0, 0.0], {"x": 0.0, "y": 0.0})
        second = phase([0.0, 0.0], {"x": 0.0, "y": 0.0}, 10)
        self.assertNotEqual(cam.verdict_from(first, second)["verdict"], cam.BUG_PRESENT)

    def test_a_window_that_does_not_render_shows_as_no_frames_and_no_camera_movement(self):
        first = [sample(0.25 * index, {"x": 0.0, "y": 0.0}, {"x": 15.0, "y": 0.0}, frame=7) for index in range(4)]
        second = [sample(0.25 * index, {"x": 0.0, "y": 0.0}, {"x": 45.0, "y": 0.0}, frame=7) for index in range(4)]
        result = cam.verdict_from(first, second)
        self.assertFalse(result["framesAdvanced"])
        self.assertFalse(result["cameraMovedFirstPhase"])


class SampleTests(unittest.TestCase):
    def test_a_sample_computes_the_distances_and_survives_unreadable_fields(self):
        client = mock.Mock()
        values = {("static:PlayerCamera", "main.transform.position"): {"x": 3.0, "y": 4.0}, ("id:9", "transform.position"): {"x": 0.0, "y": 0.0},
                  ("player", "transform.position"): {"x": 6.0, "y": 8.0}, ("static:Together.UIInGame", "SpectatorModeActive"): True,
                  ("static:Time", "frameCount"): 12, ("static:Application", "isFocused"): False}

        def call(command, target=None, path=None, depth=0, nonpublic=False):
            if (target, path) in values:
                return values[(target, path)]
            raise RuntimeError("no member")

        client.call.side_effect = call
        result = cam.read_sample(client, 0.0, {"hostBody": "id:9"})
        self.assertEqual((result["cameraToTarget"], result["cameraToDeadBody"], result["targetToDeadBody"]), (5.0, 5.0, 10.0))
        self.assertTrue(result["spectatorModeActive"])
        self.assertFalse(result["targetNonNull"])
        self.assertEqual(result["customLookPos"], {"readError": "RuntimeError"})
        self.assertEqual((result["frame"], result["focused"]), (12, False))

    def test_a_phase_samples_every_step_for_the_duration(self):
        clock = [0.0]
        client = mock.Mock()
        with mock.patch.object(cam.time, "time", lambda: clock[0]), mock.patch.object(cam.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)), \
                mock.patch.object(cam, "read_sample", lambda game, started, handles: {"t": clock[0]}):
            samples = cam.sample_phase(client, {"hostBody": "id:1"}, seconds=6.0, step=0.25)
        self.assertEqual(len(samples), 24)


class StepTests(unittest.TestCase):
    def setUp(self):
        clock = [0.0]
        patches = [mock.patch.object(cam.time, "time", lambda: clock[0]), mock.patch.object(cam.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_client_is_killed_through_the_host_console_when_that_works(self):
        host, client = mock.Mock(), mock.Mock()
        state = {"dead": False}
        host.call.side_effect = lambda command, **arguments: state.__setitem__("dead", True) or {"output": ["Killed: ClientD"], "failed": False}
        with mock.patch.object(cam, "is_dead", lambda game: state["dead"]):
            result = cam.kill_client(host, client)
        self.assertEqual((result["method"], result["dead"]), ("host console kill", True))
        host.call.assert_called_once_with("console", line="kill ClientD")
        client.set.assert_not_called()

    def test_the_client_body_is_set_dead_when_the_host_command_does_nothing(self):
        host, client = mock.Mock(), mock.Mock()
        host.call.return_value = {"output": [], "failed": True}
        state = {"dead": False}
        client.set.side_effect = lambda target, path, value: state.__setitem__("dead", True)
        with mock.patch.object(cam, "is_dead", lambda game: state["dead"]):
            result = cam.kill_client(host, client)
        self.assertEqual(result["method"], "client brainHealth and heartRate set to 0")
        self.assertTrue(result["dead"])

    def test_a_client_that_never_dies_is_reported_not_dead(self):
        host, client = mock.Mock(), mock.Mock()
        with mock.patch.object(cam, "is_dead", lambda game: False):
            self.assertFalse(cam.kill_client(host, client)["dead"])

    def test_spectator_mode_started_by_the_game_is_not_started_again(self):
        client = mock.Mock()
        with mock.patch.object(cam, "safe_get", lambda game, target, path, nonpublic=False: True):
            self.assertEqual(cam.enter_spectator(client), {"active": True, "startedBy": "the game"})
        client.call.assert_not_called()

    def test_spectator_mode_is_started_through_the_link_when_the_game_does_not(self):
        client = mock.Mock()
        answers = iter([None] * 20 + [True])
        with mock.patch.object(cam, "safe_get", lambda game, target, path, nonpublic=False: next(answers, True)):
            result = cam.enter_spectator(client)
        self.assertEqual(result["startedBy"], "link call to UIInGame.StartSpectatorMode")
        client.call.assert_called_once_with("invoke", target=cam.UI_TYPE, method="StartSpectatorMode", args=[], types=[])

    def test_the_target_is_set_with_the_game_own_target_method_and_a_failure_is_reported(self):
        client = mock.Mock()
        self.assertTrue(cam.set_target(client, "id:9")["ok"])
        client.call.assert_called_once_with("invoke", target=cam.UI_TYPE, method="Spectator_SetTarget", args=["id:9", None], types=["Component", "String"])
        client.call.side_effect = RuntimeError("no overload")
        self.assertEqual(cam.set_target(client, "id:9")["errorType"], "RuntimeError")

    def test_a_pocket_search_uses_the_given_columns_and_restores_the_default(self):
        host = mock.Mock()
        host.get.return_value = 500
        seen = []

        def find(game, origin, half_width):
            seen.append(cam.static.FAR_COLUMNS)
            return {"x": 1.0, "y": 2.0}

        saved = cam.static.FAR_COLUMNS
        with mock.patch.object(cam.static, "find_far_pocket", find):
            cam.find_pocket(host, {"x": 0.0, "y": 0.0}, cam.NEAR_COLUMNS)
        self.assertEqual(seen, [cam.NEAR_COLUMNS])
        self.assertEqual(cam.static.FAR_COLUMNS, saved)


class CheckTests(unittest.TestCase):
    def context(self, **log):
        base_log = {"kill": {"dead": True, "method": "host console kill"}, "spectator": {"active": True}, "target": {"ok": True}, "result": {"verdict": cam.FOLLOWS}}
        base_log.update(log)
        return {"target": base_log}

    def test_follows_passes(self):
        self.assertEqual(cam.check(self.context()), [])

    def test_the_bug_is_reported_as_an_issue_with_its_name(self):
        issues = cam.check(self.context(result={"verdict": cam.BUG_PRESENT}))
        self.assertTrue(issues[0].startswith("BUG PRESENT"))

    def test_an_inconclusive_result_is_an_issue_with_its_reason(self):
        issues = cam.check(self.context(result={"verdict": cam.INCONCLUSIVE, "reason": "neither"}))
        self.assertEqual(issues, ["INCONCLUSIVE: neither"])

    def test_each_failed_setup_step_is_invalid_and_names_the_step(self):
        self.assertTrue(cam.check(self.context(setupError="no pocket"))[0].startswith("INVALID: no pocket"))
        self.assertIn("did not die", cam.check(self.context(kill={"dead": False, "method": "x"}))[0])
        self.assertIn("spectator mode is not active", cam.check(self.context(spectator={"active": False}))[0])
        self.assertIn("could not be set", cam.check(self.context(target={"ok": False}))[0])


class WiringTests(unittest.TestCase):
    def test_the_scenario_has_its_own_group_and_starts_with_no_extra_flags(self):
        self.assertEqual(scenarios.matching_scenario_names(["spectatorcam"]), ["spectatorcam_follow_by_client"])
        self.assertEqual(sorted(scenarios.counts_by_group(["spectatorcam"])), ["spectator"])
        self.assertEqual((test_desync.GROUP_HOST_ARGUMENTS["spectator"], test_desync.GROUP_CLIENT_ARGUMENTS["spectator"]), ([], []))

    def test_the_preflight_passes_and_ignores_other_launches(self):
        self.assertEqual(cam.preflight(["spectatorcam"], 1), [])
        self.assertEqual(cam.preflight(["spawned_crate"], 1), [])

    def test_the_limits_are_consistent(self):
        self.assertLess(cam.CLOSE_TO_TARGET, cam.FAR_FROM_TARGET)
        self.assertGreaterEqual(cam.smallest_column(cam.NEAR_COLUMNS), cam.MIN_START_DISTANCE)
        self.assertGreater(cam.smallest_column(cam.FAR_COLUMNS), cam.FAR_FROM_TARGET)

    def test_a_pair_of_limits_that_overlap_is_refused_by_the_preflight(self):
        with mock.patch.object(cam, "CLOSE_TO_TARGET", 12.0):
            self.assertTrue(cam.preflight(["spectatorcam"], 1))


if __name__ == "__main__":
    unittest.main()
