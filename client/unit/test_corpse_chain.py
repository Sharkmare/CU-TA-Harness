import unittest
from unittest import mock

from tests import corpse_chain as chain
from tests import desync_scenarios as scenarios
from tests import spawned_crates as crates

CORPSE = {"x": 12.5, "y": 5.0}
CONTROL_NAME = chain.CONTROLS[0][0]


def entry(index, host, client, host_cant=True, client_cant=False):
    return {"swing": index, "t": index * 0.35, "fired": True, "hostHp": [250.0, host], "clientHp": [250.0, client], "hostCantHit": host_cant, "clientCantHit": client_cant}


def sample(host, client, host_cant=True):
    return {"t": 9.0, "host": host, "client": client, "hostCantHit": host_cant, "clientCantHit": False}


FLAGS = ({"cantHit": True}, {"cantHit": False})


class EvaluateTests(unittest.TestCase):
    def evaluate(self, entries, samples):
        return chain.evaluate(entries, samples, *FLAGS)

    def test_the_predicted_pattern_holds(self):
        entries = [entry(1, 250.0, 200.0), entry(2, 250.0, 100.0), entry(3, 250.0, -40.0)]
        samples = [sample(250.0, -40.0), sample(250.0, 120.0), sample(250.0, 249.0)]
        result = self.evaluate(entries, samples)
        self.assertEqual(result["verdict"], "prediction holds")
        self.assertEqual((result["hostMinHp"], result["clientMinHp"], result["clientFinalHp"]), (250.0, -40.0, 249.0))
        self.assertTrue(result["clientReturned"])
        self.assertEqual(result["refutedBy"], [])

    def test_a_host_copy_that_loses_health_refutes_it(self):
        result = self.evaluate([entry(1, 250.0, -10.0), entry(2, 180.0, -10.0)], [sample(180.0, 250.0)])
        self.assertEqual(result["verdict"], "prediction refuted")
        self.assertTrue(any("host copy's health fell" in reason for reason in result["refutedBy"]), result["refutedBy"])

    def test_a_host_copy_with_cant_hit_false_refutes_it(self):
        result = self.evaluate([entry(1, 250.0, -10.0, host_cant=False)], [sample(250.0, 250.0)])
        self.assertTrue(result["hostEverCantHitFalse"])
        self.assertTrue(any("cantHit was false" in reason for reason in result["refutedBy"]))

    def test_a_client_copy_that_never_drops_below_zero_refutes_it(self):
        result = self.evaluate([entry(1, 250.0, 200.0), entry(2, 250.0, 150.0)], [sample(250.0, 250.0)])
        self.assertTrue(any("never dropped below 0" in reason for reason in result["refutedBy"]))

    def test_a_client_copy_that_stays_below_zero_is_not_reported_as_returned(self):
        result = self.evaluate([entry(1, 250.0, -10.0)], [sample(250.0, -10.0)])
        self.assertFalse(result["clientReturned"])
        self.assertEqual(result["verdict"], "prediction holds")

    def test_unreadable_values_do_not_crash_and_leave_the_minimum_empty(self):
        result = self.evaluate([{"swing": 1, "hostHp": [None, None], "clientHp": [None, None], "hostCantHit": None, "clientCantHit": None}], [])
        self.assertIsNone(result["clientMinHp"])
        self.assertEqual(result["verdict"], "prediction refuted")


def hold_row(held=True, exceeded=0, lost=False, drift=0.01):
    return {"target": {"x": 1.0, "y": 2.0}, "position": {"x": 1.0, "y": 2.0}, "drift": drift, "maxDrift": drift, "exceededTicks": exceeded, "heldWithinTolerance": held, "lost": lost, "tolerance": 0.05}


def snapshots(host=None, client=None):
    row_host = [hold_row()] if host is None else host
    row_client = [hold_row()] if client is None else client
    return {moment: {"host": row_host, "client": row_client} for moment in ("beforeFirstSwing", "afterLastSwing", "end")}


class HoldTests(unittest.TestCase):
    def test_holds_that_stayed_within_tolerance_and_all_swings_fired_are_not_a_problem(self):
        self.assertEqual(chain.hold_problems(snapshots(), [entry(1, 250.0, -10.0)]), [])

    def test_a_hold_that_exceeded_its_tolerance_is_a_problem_naming_the_machine_and_moment(self):
        problems = chain.hold_problems(snapshots(client=[hold_row(held=False, exceeded=3, drift=0.9)]), [entry(1, 250.0, -10.0)])
        self.assertTrue(any(problem.startswith("client hold at beforeFirstSwing") and "exceeded ticks 3" in problem for problem in problems), problems)
        self.assertFalse(any(problem.startswith("host hold") for problem in problems))

    def test_a_lost_body_is_a_problem(self):
        self.assertTrue(chain.hold_problems(snapshots(host=[hold_row(lost=True)]), [entry(1, 250.0, -10.0)]))

    def test_a_missing_hold_is_a_problem(self):
        problems = chain.hold_problems(snapshots(host=[]), [entry(1, 250.0, -10.0)])
        self.assertTrue(any("no host hold" in problem for problem in problems), problems)

    def test_an_unreadable_status_is_a_problem_not_a_pass(self):
        shot = snapshots()
        shot["end"]["client"] = {"error": "LinkError: unknown command"}
        self.assertTrue(any("unreadable" in problem for problem in chain.hold_problems(shot, [entry(1, 250.0, -10.0)])))

    def test_a_swing_that_did_not_fire_is_a_problem(self):
        unfired = dict(entry(2, 250.0, -10.0), fired=False)
        self.assertEqual(chain.hold_problems(snapshots(), [entry(1, 250.0, -10.0), unfired]), ["swings that did not fire: [2]"])

    def test_a_status_that_is_not_a_list_is_reported_as_an_error(self):
        game = mock.Mock()
        game.call.return_value = mock.Mock()
        self.assertIn("not a list", chain.hold_rows(game)["error"])

    def test_the_status_rows_keep_only_the_fields_the_report_needs(self):
        game = mock.Mock()
        game.call.return_value = [dict(hold_row(), id=5, ticks=900)]
        rows = chain.hold_rows(game)
        self.assertNotIn("id", rows[0])
        self.assertEqual(rows[0]["maxDrift"], 0.01)
        game.call.side_effect = RuntimeError("down")
        self.assertEqual(chain.hold_rows(game), {"error": "RuntimeError: down"})


class FireOneSwingTests(unittest.TestCase):
    def test_ignored_invokes_are_counted_until_the_cooldown_rises(self):
        rises_on_invoke = 3
        state = {"invokes": 0, "cooldown": 0.0}
        client = mock.Mock()

        def invoke(*args, **kwargs):
            state["invokes"] += 1
            if state["invokes"] == rises_on_invoke:
                state["cooldown"] = 0.2

        client.call.side_effect = invoke
        client.get.side_effect = lambda *args, **kwargs: state["cooldown"]
        attempts = {}
        with mock.patch.object(chain.hooks.time, "sleep", lambda seconds: None):
            self.assertTrue(chain.hooks.fire_one_swing(client, {"x": 1.0, "y": 2.0}, pause=0.01, attempts=attempts))
        self.assertEqual(attempts["ignored"], rises_on_invoke - 1)


class PrepareTests(unittest.TestCase):
    def setUp(self):
        crates.reset_launch_state()
        chain.reset_launch_state()
        self.addCleanup(crates.reset_launch_state)
        self.addCleanup(chain.reset_launch_state)

    def test_a_client_body_on_the_host_that_is_not_dune_is_a_setup_failure_before_anything_is_spawned(self):
        characters = {"client": 2, "host": 1, "clientBodyOnHost": 0}
        with mock.patch.object(chain.base, "empty_the_hand", lambda game: None), mock.patch.object(chain.banded, "characters_in_play", lambda host, client: characters), \
                mock.patch.object(chain.crates, "spawn_object") as spawn:
            with self.assertRaises(crates.SetupFailure) as caught:
                chain.prepare(mock.Mock(), mock.Mock())
        spawn.assert_not_called()
        self.assertEqual(caught.exception.category, "client-body-on-host-wrong-character")

    def test_the_wrong_host_character_is_a_setup_failure(self):
        characters = {"client": 2, "host": 0, "clientBodyOnHost": 2}
        with mock.patch.object(chain.base, "empty_the_hand", lambda game: None), mock.patch.object(chain.banded, "characters_in_play", lambda host, client: characters), \
                mock.patch.object(chain.crates, "spawn_object") as spawn:
            with self.assertRaises(crates.SetupFailure) as caught:
                chain.prepare(mock.Mock(), mock.Mock())
        spawn.assert_not_called()
        self.assertEqual(caught.exception.category, "characters-not-set")

    def test_the_client_is_seated_to_the_left_of_the_corpse_inside_the_swing_reach(self):
        characters = {"client": 2, "host": 1, "clientBodyOnHost": 2}
        seat = {"ok": True, "issues": []}
        spawned = {"position": dict(CORPSE), "handle": "id:7", "clientHandle": "id:-7"}
        with mock.patch.object(chain.base, "empty_the_hand", lambda game: None), mock.patch.object(chain.banded, "characters_in_play", lambda host, client: characters), \
                mock.patch.object(chain.positioncontrol, "start_positions", lambda host, client: {"separation": 20.0}), mock.patch.object(chain.crates, "spawn_object", lambda *a: spawned), \
                mock.patch.object(chain.positioncontrol, "seat_pair", return_value=seat) as seat_pair, mock.patch.object(chain.banded, "copy_flags", lambda game, handle: {"cantHit": True}):
            context = chain.prepare(mock.Mock(), mock.Mock())
        self.assertEqual(seat_pair.call_args.args[2], {"x": CORPSE["x"] - chain.SEAT_DISTANCE, "y": CORPSE["y"]})
        self.assertEqual(seat_pair.call_args.args[3], chain.PARK_DIRECTION)
        self.assertEqual(seat_pair.call_args.kwargs["parked_policy"], chain.positioncontrol.PARKED_RECORDED)
        self.assertLess(chain.SEAT_DISTANCE, chain.MAX_SWING_DISTANCE)
        self.assertEqual(context["target"]["startPositions"], {"separation": 20.0})


def reading(at, host, client, is_right=True, full=True):
    result = {"at": at, "host": host, "client": client, "hostCantHit": True, "clientCantHit": False}
    if full:
        result["isRight"] = is_right
        result["parked"] = {"linkRead": {"x": -2.0, "y": 5.0}, "holder": None, "paths": {}}
    return result


class BuildEntriesTests(unittest.TestCase):
    def mark(self, swing, at, interval=None):
        return {"swing": swing, "firedAt": at, "fired": True, "ignoredAttempts": 1, "interval": interval}

    def test_the_health_before_is_the_last_reading_before_the_swing_and_after_the_first_at_or_after_it(self):
        samples = [reading(1.0, 250.0, 250.0), reading(1.4, 250.0, 225.0), reading(1.9, 250.0, 250.0)]
        entries = chain.build_entries([self.mark(1, 1.2), self.mark(2, 1.4, 0.2)], samples, 1.0, True)
        self.assertEqual(entries[0]["clientHp"], [250.0, 225.0])
        self.assertAlmostEqual(entries[0]["sampleLagSeconds"], 0.2)
        self.assertEqual(entries[1]["clientHp"], [250.0, 225.0])
        self.assertEqual((entries[0]["t"], entries[1]["intervalSincePrevious"], entries[1]["ignoredAttempts"]), (0.2, 0.2, 1))

    def test_facing_and_the_parked_host_come_from_the_first_full_reading_after_the_swing(self):
        samples = [reading(1.0, 250.0, 250.0), reading(1.3, 250.0, 250.0, full=False), reading(1.5, 250.0, 250.0, is_right=False)]
        entry = chain.build_entries([self.mark(1, 1.1)], samples, 1.0, True)[0]
        self.assertFalse(entry["facingCorpse"])
        self.assertEqual(entry["parkedHost"]["linkRead"], {"x": -2.0, "y": 5.0})
        entry_left = chain.build_entries([self.mark(1, 1.1)], samples, 1.0, False)[0]
        self.assertTrue(entry_left["facingCorpse"])

    def test_a_swing_after_the_last_reading_uses_the_last_reading(self):
        entries = chain.build_entries([self.mark(1, 9.0)], [reading(1.0, 250.0, 250.0)], 0.0, True)
        self.assertEqual(entries[0]["clientHp"], [250.0, 250.0])
        self.assertIsNone(entries[0]["facingCorpse"])


class SamplerThreadTests(unittest.TestCase):
    def test_the_thread_collects_readings_until_stopped_and_counts_failures(self):
        context = {"host": mock.Mock(), "hostHandle": "id:7", "clientHandle": "id:-7"}
        with mock.patch.object(chain, "read_health", return_value=250.0), mock.patch.object(chain, "read_flag", return_value=True),                 mock.patch.object(chain.crates, "optional_read", return_value=True), mock.patch.object(chain.positioncontrol, "parked_snapshot", return_value={"linkRead": None, "holder": None, "paths": {}}):
            sampler = chain.Sampler(mock.Mock(), context, [])
            sampler.start()
            deadline = chain.time.time() + 5.0
            while len(sampler.samples) < 3 and chain.time.time() < deadline:
                chain.time.sleep(0.005)
            sampler.light = True
            sampler.stop()
        self.assertGreaterEqual(len(sampler.samples), 3)
        self.assertIn("isRight", sampler.samples[0])
        self.assertFalse(sampler.thread.is_alive())

    def test_a_failing_read_is_counted_and_the_thread_keeps_going(self):
        context = {"host": mock.Mock(), "hostHandle": "id:7", "clientHandle": "id:-7"}
        with mock.patch.object(chain, "read_health", side_effect=RuntimeError("link")), mock.patch.object(chain, "SAMPLE_INTERVAL_SECONDS", 0.001):
            sampler = chain.Sampler(mock.Mock(), context, [])
            sampler.start()
            deadline = chain.time.time() + 5.0
            while sampler.failures < 2 and chain.time.time() < deadline:
                chain.time.sleep(0.005)
            sampler.stop()
        self.assertGreaterEqual(sampler.failures, 2)
        self.assertEqual(sampler.samples, [])

    def test_the_sampling_summary_reports_the_gaps(self):
        samples = [reading(0.0, 1.0, 1.0), reading(0.2, 1.0, 1.0), reading(0.7, 1.0, 1.0, full=False)]
        summary = chain.sampling_summary(samples, mock.Mock(failures=0))
        self.assertEqual((summary["samples"], summary["fullSamples"], summary["maxGapSeconds"]), (3, 2, 0.5))


class StepSampler(chain.Sampler):
    """The real sampler, stepped by the test instead of by a thread."""

    def start(self):
        pass

    def stop(self):
        pass


class ActTests(unittest.TestCase):
    def setUp(self):
        self.sampler = None
        chain.reset_launch_state()
        crates.reset_launch_state()
        self.addCleanup(chain.reset_launch_state)
        self.addCleanup(crates.reset_launch_state)
        self.client = mock.Mock()
        self.host = mock.Mock()
        self.client.call.return_value = [hold_row()]
        self.host.call.return_value = [hold_row()]
        self.clock = [100.0]
        self.sleeps = []
        self.fired = []
        self.client_hp = 250.0
        self.parked_x = []

    def context(self, seat_ok=True):
        parked = {"paths": ["rb.position"], "observations": [self.parked_snapshot(None, [])] * 2, "afterPreflight": self.parked_snapshot(None, [])}
        target = {"positionControl": {"ok": seat_ok, "issues": [] if seat_ok else ["the bodies overlap"], "parkedHost": parked, "clientTarget": {"x": 10.0, "y": 5.0}}, "hostFlags": {"cantHit": True}, "clientFlags": {"cantHit": False}}
        return {"position": dict(CORPSE), "host": self.host, "hostHandle": "id:7", "clientHandle": "id:-7", "target": target, "measurements": [], "samples": []}

    def parked_snapshot(self, game, paths):
        position = {"x": self.parked_x[0] if self.parked_x else -2.0, "y": 5.0}
        return {"linkRead": position, "holder": position, "paths": {"rb.position": position}}

    def make_sampler(self, client, context, paths):
        self.sampler = StepSampler(client, context, paths)
        return self.sampler

    def sample(self):
        if self.sampler is not None:
            self.sampler.sample_once()

    def fire(self, game, aim, pause=None, attempts=None):
        self.sample()
        self.fired.append(aim)
        self.clock[0] += 0.16
        if attempts is not None:
            attempts["ignored"] = attempts.get("ignored", 0) + 2
        self.client_hp = -20.0 if len(self.fired) >= 3 else self.client_hp - 80.0
        return True

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.clock[0] += seconds
        self.sample()

    def patches(self, facing=True):
        look = {"x": CORPSE["x"], "y": CORPSE["y"]}
        return [mock.patch.object(chain.time, "time", lambda: self.clock[0]), mock.patch.object(chain.time, "sleep", self.sleep),
                mock.patch.object(chain.world, "host_position", lambda host, handle: dict(CORPSE)), mock.patch.object(chain.base, "player_position", lambda game: {"x": 10.0, "y": 5.0}),
                mock.patch.object(chain.crates, "optional_read", lambda game, path: look if path == "targetLookPos" else (facing() if callable(facing) else facing)),
                mock.patch.object(chain.hooks, "fire_one_swing", self.fire),
                mock.patch.object(chain, "read_health", lambda game, handle: 250.0 if game is self.host else self.client_hp), mock.patch.object(chain, "read_flag", lambda game, handle: game is self.host),
                mock.patch.object(chain.banded, "destroy"), mock.patch.object(chain.positioncontrol, "release_quietly"),
                mock.patch.object(chain.positioncontrol, "parked_snapshot", self.parked_snapshot), mock.patch.object(chain, "make_sampler", self.make_sampler)]

    def run_act(self, context, facing=True):
        patches = self.patches(facing)
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        chain.act(self.client, context)

    def test_it_fires_the_planned_swings_as_fast_as_the_cooldown_allows_and_samples_after_the_last(self):
        context = self.context()
        self.run_act(context)
        self.assertEqual(len(context["measurements"]), chain.SWINGS)
        self.assertEqual(len(self.fired), chain.SWINGS)
        intervals = [item["intervalSincePrevious"] for item in context["measurements"]]
        self.assertIsNone(intervals[0])
        self.assertTrue(all(abs(value - 0.16) < 0.01 for value in intervals[1:]), intervals)
        self.assertTrue(all(item["ignoredAttempts"] == 2 for item in context["measurements"]))
        rate = context["target"]["swingRate"]
        self.assertEqual((rate["intervals"], rate["ignoredAttemptsTotal"]), (chain.SWINGS - 1, 2 * chain.SWINGS))
        self.assertAlmostEqual(rate["medianSeconds"], 0.16, places=2)
        planned = round(chain.AFTER_LAST_SWING_SECONDS / chain.SAMPLE_INTERVAL_SECONDS)
        self.assertIn(len(context["samples"]), (planned, planned + 1))
        self.assertEqual(context["target"]["prediction"]["verdict"], "prediction holds")

    def hold_status_for(self, game, exceeded=0):
        return [hold_row(held=exceeded == 0, exceeded=exceeded)]

    def test_the_hold_status_is_taken_before_the_first_swing_after_the_last_and_at_the_end(self):
        context = self.context()
        self.host.call.side_effect = lambda command, **arguments: self.hold_status_for(self.host)
        self.client.call.side_effect = lambda command, **arguments: self.hold_status_for(self.client)
        self.run_act(context)
        holds = context["target"]["holds"]
        self.assertEqual(sorted(holds), ["afterLastSwing", "beforeFirstSwing", "end"])
        self.assertEqual(context["target"]["holdProblems"], [])
        self.assertEqual(context["target"]["prediction"]["verdict"], "prediction holds")

    def test_a_hold_over_its_tolerance_labels_the_corpse_result_confounded_instead_of_reading_the_prediction(self):
        context = self.context()
        self.host.call.side_effect = lambda command, **arguments: self.hold_status_for(self.host)
        self.client.call.side_effect = lambda command, **arguments: self.hold_status_for(self.client, exceeded=4)
        self.run_act(context)
        prediction = context["target"]["prediction"]
        self.assertTrue(prediction["verdict"].startswith("confounded"))
        self.assertEqual(prediction["ifRead"], "prediction holds")
        self.assertTrue(prediction["confoundedBy"])

    def test_a_parked_host_that_stays_far_enough_leaves_the_verdict_standing_and_records_the_distances(self):
        context = self.context()
        self.run_act(context)
        target = context["target"]
        self.assertEqual(target["prediction"]["verdict"], "prediction holds")
        self.assertEqual(target["holdProblems"], [])
        self.assertGreaterEqual(target["parkedDistances"]["smallestSeen"], chain.MIN_PARKED_DISTANCE)
        self.assertEqual(len(target["parkedDistances"]["perMoment"]), 2 + 1 + chain.SWINGS)
        self.assertTrue(all("parkedHost" in item for item in context["measurements"]))

    def test_a_swing_with_the_parked_host_closer_than_the_minimum_labels_the_corpse_result_confounded(self):
        context = self.context()
        close_at_swing = 7
        original = self.parked_snapshot

        def snapshot(game, paths):
            if len(self.fired) == close_at_swing:
                position = {"x": CORPSE["x"] - 5.0, "y": CORPSE["y"]}
                return {"linkRead": {"x": -2.0, "y": 5.0}, "holder": {"x": -2.0, "y": 5.0}, "paths": {"rb.position": position}}
            return original(game, paths)

        self.parked_snapshot = snapshot
        self.run_act(context)
        prediction = context["target"]["prediction"]
        self.assertTrue(prediction["verdict"].startswith("confounded"))
        self.assertTrue(any("rb.position" in problem for problem in prediction["confoundedBy"]), prediction["confoundedBy"])
        self.assertEqual(len(prediction["confoundedBy"]), 1)
        self.assertIn("at sample %d" % (close_at_swing + 1), prediction["confoundedBy"][0])

    def test_a_parked_host_with_no_readable_position_labels_the_result_confounded(self):
        context = self.context()
        self.parked_snapshot = lambda game, paths: {"linkRead": None, "holder": None, "paths": {}}
        self.run_act(context)
        self.assertTrue(context["target"]["prediction"]["verdict"].startswith("confounded"))
        self.assertTrue(any("no readable parked host position" in problem for problem in context["target"]["holdProblems"]))

    def test_every_swing_aims_at_the_corpse(self):
        context = self.context()
        self.run_act(context)
        self.assertTrue(all(aim == CORPSE for aim in self.fired))

    def test_a_client_that_does_not_face_the_corpse_with_the_mouse_on_it_fires_nothing_and_the_run_is_invalid(self):
        context = self.context()
        self.run_act(context, facing=False)
        self.assertEqual(self.fired, [])
        issues = chain.check(context)
        self.assertTrue(issues[0].startswith("INVALID: the client does not face the corpse before the first swing"), issues)

    def test_the_injected_mouse_is_put_on_the_corpse_before_the_first_swing_and_cleared_afterwards(self):
        context = self.context()
        self.run_act(context)
        calls = [call for call in self.client.call.call_args_list if call.args and call.args[0] == "mouse"]
        self.assertEqual(calls[0].kwargs, {"wx": CORPSE["x"], "wy": CORPSE["y"]})
        self.assertEqual(calls[-1].kwargs, {"clear": True})

    def test_a_client_that_turns_away_during_the_swings_is_re_aimed_and_the_result_is_confounded_not_invalid(self):
        context = self.context()
        self.run_act(context, facing=lambda: not self.fired)
        self.assertEqual(len(self.fired), chain.SWINGS)
        target = context["target"]
        self.assertTrue(target["facingBefore"]["facingCorpse"])
        self.assertFalse(target["facingAfterFirstSwing"]["facingCorpse"])
        self.assertEqual(target["reaimedAfterSwing"], list(range(2, chain.SWINGS + 1)))
        self.assertTrue(target["prediction"]["verdict"].startswith("confounded"))
        self.assertTrue(any("faced away" in problem for problem in target["holdProblems"]))
        self.assertEqual(chain.check(context), [])

    def test_a_client_that_faces_the_corpse_records_the_facing_before_and_after_the_first_swing(self):
        context = self.context()
        self.run_act(context)
        target = context["target"]
        self.assertTrue(target["facingBefore"]["facingCorpse"])
        self.assertTrue(target["facingAfterFirstSwing"]["facingCorpse"])

    def test_the_look_position_is_not_used_to_judge_facing_because_the_game_resets_it_every_frame(self):
        with mock.patch.object(chain.base, "player_position", lambda game: {"x": 10.0, "y": 5.0}), \
                mock.patch.object(chain.crates, "optional_read", lambda game, path: {"x": -22.0, "y": 9.0} if path == "targetLookPos" else True):
            record = chain.facing_record(mock.Mock(), {"x": 12.5, "y": 5.0})
        self.assertEqual((record["lookSide"], record["corpseSide"]), (-1, 1))
        self.assertTrue(record["facingCorpse"])

    def test_a_failed_seat_fires_nothing_and_is_invalid_and_the_holds_are_still_released(self):
        context = self.context(seat_ok=False)
        self.run_act(context)
        self.assertEqual(self.fired, [])
        self.assertIn("the bodies overlap", chain.check(context)[0])
        self.assertEqual(chain.positioncontrol.release_quietly.call_count, 2)

    def test_a_client_beyond_the_swing_reach_fires_nothing(self):
        context = self.context()
        patches = self.patches()
        patches[3] = mock.patch.object(chain.base, "player_position", lambda game: {"x": -5.0, "y": 5.0})
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        chain.act(self.client, context)
        self.assertEqual(self.fired, [])
        self.assertIn("beyond", chain.check(context)[0])

    def test_the_corpse_is_destroyed_and_both_holds_dropped_even_when_a_swing_raises(self):
        context = self.context()
        patches = self.patches()
        patches[5] = mock.patch.object(chain.hooks, "fire_one_swing", side_effect=RuntimeError("link died"))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        with self.assertRaises(RuntimeError):
            chain.act(self.client, context)
        chain.banded.destroy.assert_called_once()
        self.assertEqual(chain.positioncontrol.release_quietly.call_count, 2)


class CheckAndWiringTests(unittest.TestCase):
    def test_a_run_with_swings_and_no_setup_failure_has_no_issues_whatever_the_prediction_says(self):
        self.assertEqual(chain.check({"measurements": [entry(1, 100.0, 100.0)]}), [])

    def test_no_swing_is_invalid(self):
        self.assertEqual(chain.check({"measurements": []}), ["INVALID: no swing recorded"])

    def test_the_scenario_is_alone_in_its_own_startup_group_and_selectable(self):
        self.assertEqual(scenarios.matching_scenario_names(["corpse_chain_by_client"]), [chain.NAME])
        self.assertEqual(sorted(scenarios.counts_by_group(["corpse_chain_by_client"])), [chain.GROUP])

    def test_each_control_is_alone_in_its_own_group_and_selectable_by_its_own_name(self):
        from tests import test_desync
        for name, group, host_character, client_character in chain.CONTROLS:
            self.assertEqual(scenarios.matching_scenario_names([name]), [name])
            self.assertEqual(sorted(scenarios.counts_by_group([name])), [group])
            self.assertEqual((test_desync.GROUP_HOST_CHARACTER[group], test_desync.GROUP_CLIENT_CHARACTER[group]), (host_character, client_character))
            self.assertIn(group, test_desync.PROBE_GROUPS)
            self.assertIn("--mp-verbose", test_desync.GROUP_HOST_ARGUMENTS[group])
            self.assertIn("--mp-verbose", test_desync.GROUP_CLIENT_ARGUMENTS[group])
        self.assertEqual([(host, client) for _, _, host, client in chain.CONTROLS], [(2, 2), (1, 1)])

    def test_a_control_verifies_its_own_characters_before_spawning_anything(self):
        prepare_milky_pair = chain.prepare_for(1, 1)
        characters = {"client": 2, "host": 1, "clientBodyOnHost": 2}
        with mock.patch.object(chain.base, "empty_the_hand", lambda game: None), mock.patch.object(chain.banded, "characters_in_play", lambda host, client: characters), \
                mock.patch.object(chain.crates, "spawn_object") as spawn:
            with self.assertRaises(crates.SetupFailure) as caught:
                prepare_milky_pair(mock.Mock(), mock.Mock())
        spawn.assert_not_called()
        self.assertEqual(caught.exception.category, "client-body-on-host-wrong-character")
        self.assertIn("expected Milky (1)", str(caught.exception))

    def test_the_group_starts_a_milky_host_and_a_dune_client_with_the_probe_on(self):
        from tests import test_desync
        self.assertEqual(test_desync.GROUP_HOST_CHARACTER[chain.GROUP], chain.HOST_CHARACTER)
        self.assertEqual(test_desync.GROUP_CLIENT_CHARACTER[chain.GROUP], chain.CLIENT_CHARACTER)
        self.assertIn(chain.GROUP, test_desync.PROBE_GROUPS)
        self.assertIn("--mp-verbose", test_desync.GROUP_HOST_ARGUMENTS[chain.GROUP])

    def test_the_preflight_passes_and_ignores_other_launches(self):
        self.assertEqual(chain.preflight(["corpse_chain_by_client"], 1), [])
        self.assertEqual(chain.preflight([CONTROL_NAME], 1), [])
        self.assertEqual(chain.preflight(["spawned_crate"], 1), [])

    def test_a_planned_launch_is_one_launch_of_one_run(self):
        from casualtieslink import launchplan
        for fragment in ["corpse_chain_by_client"] + [name for name, *_ in chain.CONTROLS]:
            counts = scenarios.counts_by_group([fragment, "launch_log_checks"])
            launches = launchplan.plan_launches(["pr24-corpse-verbose"], sorted(counts), launchplan.parse_profiles(["100:0"]), 1, [fragment, "launch_log_checks"])
            self.assertEqual(len(launches), 1, fragment)


if __name__ == "__main__":
    unittest.main()
