import unittest
from unittest import mock

from tests import corpse_chain as chain
from tests import desync_scenarios as scenarios
from tests import spawned_crates as crates

CORPSE = {"x": 12.5, "y": 5.0}


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
        self.assertEqual(caught.exception.category, "client-body-on-host-not-dune")

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
        self.assertLess(chain.SEAT_DISTANCE, chain.MAX_SWING_DISTANCE)
        self.assertEqual(context["target"]["startPositions"], {"separation": 20.0})


class ActTests(unittest.TestCase):
    def setUp(self):
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

    def context(self, seat_ok=True):
        target = {"positionControl": {"ok": seat_ok, "issues": [] if seat_ok else ["the bodies overlap"]}, "hostFlags": {"cantHit": True}, "clientFlags": {"cantHit": False}}
        return {"position": dict(CORPSE), "host": self.host, "hostHandle": "id:7", "clientHandle": "id:-7", "target": target, "measurements": [], "samples": []}

    def fire(self, game, aim):
        self.fired.append(aim)
        self.client_hp = -20.0 if len(self.fired) >= 3 else self.client_hp - 80.0
        return True

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.clock[0] += seconds

    def patches(self, facing=True):
        look = {"x": CORPSE["x"], "y": CORPSE["y"]} if facing else {"x": 0.0, "y": 5.0}
        return [mock.patch.object(chain.time, "time", lambda: self.clock[0]), mock.patch.object(chain.time, "sleep", self.sleep),
                mock.patch.object(chain.world, "host_position", lambda host, handle: dict(CORPSE)), mock.patch.object(chain.base, "player_position", lambda game: {"x": 10.0, "y": 5.0}),
                mock.patch.object(chain.crates, "optional_read", lambda game, path: look if path == "targetLookPos" else True),
                mock.patch.object(chain.hooks, "fire_one_swing", self.fire),
                mock.patch.object(chain, "read_health", lambda game, handle: 250.0 if game is self.host else self.client_hp), mock.patch.object(chain, "read_flag", lambda game, handle: game is self.host),
                mock.patch.object(chain.banded, "destroy"), mock.patch.object(chain.positioncontrol, "release_quietly")]

    def run_act(self, context, facing=True):
        patches = self.patches(facing)
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        chain.act(self.client, context)

    def test_it_fires_the_planned_swings_at_the_planned_cadence_and_samples_after_the_last(self):
        context = self.context()
        self.run_act(context)
        self.assertEqual(len(context["measurements"]), chain.SWINGS)
        self.assertEqual(len(self.fired), chain.SWINGS)
        times = [item["t"] for item in context["measurements"]]
        self.assertAlmostEqual(times[1] - times[0], chain.CADENCE_SECONDS, places=2)
        self.assertAlmostEqual(times[-1] - times[0], chain.CADENCE_SECONDS * (chain.SWINGS - 1), places=2)
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

    def test_every_swing_aims_at_the_corpse(self):
        context = self.context()
        self.run_act(context)
        self.assertTrue(all(aim == CORPSE for aim in self.fired))

    def test_a_client_that_does_not_face_the_corpse_fires_nothing_and_the_run_is_invalid(self):
        context = self.context()
        self.run_act(context, facing=False)
        self.assertEqual(self.fired, [])
        self.assertFalse(context["facingBefore"]["facingCorpse"])
        issues = chain.check(context)
        self.assertTrue(issues[0].startswith("INVALID: the client does not face the corpse"), issues)

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
        self.assertEqual(scenarios.matching_scenario_names(["corpse_chain"]), [chain.NAME])
        self.assertEqual(sorted(scenarios.counts_by_group(["corpse_chain"])), [chain.GROUP])

    def test_the_group_starts_a_milky_host_and_a_dune_client_with_the_probe_on(self):
        from tests import test_desync
        self.assertEqual(test_desync.GROUP_HOST_CHARACTER[chain.GROUP], chain.HOST_CHARACTER)
        self.assertEqual(test_desync.GROUP_CLIENT_CHARACTER[chain.GROUP], chain.CLIENT_CHARACTER)
        self.assertIn(chain.GROUP, test_desync.PROBE_GROUPS)
        self.assertIn("--mp-verbose", test_desync.GROUP_HOST_ARGUMENTS[chain.GROUP])

    def test_the_preflight_passes_and_ignores_other_launches(self):
        self.assertEqual(chain.preflight(["corpse_chain"], 1), [])
        self.assertEqual(chain.preflight(["spawned_crate"], 1), [])

    def test_a_planned_launch_is_one_launch_of_one_run(self):
        from casualtieslink import launchplan
        counts = scenarios.counts_by_group(["corpse_chain", "launch_log_checks"])
        launches = launchplan.plan_launches(["pr24-corpse-verbose"], sorted(counts), launchplan.parse_profiles(["100:0"]), 1, ["corpse_chain", "launch_log_checks"])
        self.assertEqual(len(launches), 1)


if __name__ == "__main__":
    unittest.main()
