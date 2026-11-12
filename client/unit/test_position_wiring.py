import unittest
from unittest import mock

from casualtieslink import desync, positioncontrol
from tests import desync_scenarios as scenarios
from tests import pvp_banded
from tests import spawned_crates as crates

from unit.test_positioncontrol import FakeBodyGame, no_sleep

HOST_PARK_DISTANCE = positioncontrol.PARK_DISTANCE


class CrateWiringTests(unittest.TestCase):
    def setUp(self):
        crates.reset_launch_state()
        self.addCleanup(crates.reset_launch_state)
        patcher = mock.patch.object(positioncontrol.time, "sleep", no_sleep)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.host = FakeBodyGame({"x": 0.0, "y": 0.0})
        self.client = FakeBodyGame({"x": 50.0, "y": 50.0})
        crates.STATE["anchor"] = {"x": 50.0, "y": 50.0}
        self.context = {"host": self.host, "hostHandle": "id:7", "clientHandle": "id:-7", "position": {"x": 53.0, "y": 50.0}}

    def physics(self):
        return mock.patch.object(crates, "crate_physics", lambda game, handle: {"bodyType": "Dynamic", "physicsActive": True})

    def test_the_seat_puts_the_client_where_asked_and_holds_it(self):
        crates.seat_client(self.client, {"x": 5.0, "y": 6.0})
        self.assertEqual((self.client.held["x"], self.client.held["y"]), (5.0, 6.0))

    def test_the_host_is_parked_away_from_the_anchor_and_held_and_the_start_positions_are_recorded(self):
        with self.physics():
            crates.position_setup(self.host, self.client, self.context)
        self.assertEqual(self.context["hostPark"], {"x": 50.0 - HOST_PARK_DISTANCE, "y": 50.0})
        self.assertEqual((self.host.held["x"], self.host.held["y"]), (50.0 - HOST_PARK_DISTANCE, 50.0))
        self.assertTrue(self.context["hostHold"]["ok"])
        start = self.context["startPositions"]
        self.assertEqual((start["host"], start["client"]), ({"x": 0.0, "y": 0.0}, {"x": 50.0, "y": 50.0}))
        self.assertEqual(start["copyState"], {"crateOnClient": {"bodyType": "Dynamic", "physicsActive": True}})

    def test_the_first_swing_runs_the_preflight_and_records_both_positions_and_the_separation(self):
        with self.physics():
            crates.position_setup(self.host, self.client, self.context)
            self.client.position = {"x": 50.0, "y": 50.0}
            band = {"ok": True, "distances": [3.0], "seat": {"x": 50.0, "y": 50.0}}
            with mock.patch.object(crates, "ensure_band", lambda host, client, handle, fallback: band), \
                    mock.patch.object(crates, "read_geometry", lambda client, host, context, aim: {}):
                crates.before_swing(self.client, self.context, 1, {"x": 53.0, "y": 50.0})
        check = self.context["positionControl"]
        self.assertTrue(check["ok"], check["issues"])
        self.assertEqual(check["separation"], HOST_PARK_DISTANCE)
        self.assertEqual(check["hostPosition"], {"x": 50.0 - HOST_PARK_DISTANCE, "y": 50.0})
        self.assertNotIn("positionFailure", self.context)

    def test_a_host_body_standing_in_the_swing_line_fails_the_preflight_and_stops_the_run_before_any_swing(self):
        with self.physics():
            crates.position_setup(self.host, self.client, self.context)
            self.host.position = {"x": 50.5, "y": 50.0}
            band = {"ok": True, "distances": [3.0], "seat": {"x": 50.0, "y": 50.0}}
            with mock.patch.object(crates, "ensure_band", lambda host, client, handle, fallback: band), \
                    mock.patch.object(crates, "read_geometry", lambda client, host, context, aim: {"never": "read"}):
                result = crates.before_swing(self.client, self.context, 1, {"x": 53.0, "y": 50.0})
        self.assertIsNone(result)
        self.assertFalse(self.context["positionFailure"]["ok"])
        self.assertTrue(any("overlap" in issue for issue in self.context["positionFailure"]["issues"]))

    def test_a_failed_preflight_is_an_invalid_run_that_is_not_counted_as_valid_or_as_a_missed_swing(self):
        issues = crates.check({"positionFailure": {"ok": False, "issues": ["the bodies are 0.5 apart, below the 2.000 minimum: they overlap"]}, "measurements": []})
        self.assertTrue(issues[0].startswith("INVALID: the position preflight failed before the first swing"))
        self.assertEqual((crates.STATE["valid"], crates.STATE["swing_failed"], crates.STATE["setup_failed"]), (0, 0, 1))
        self.assertEqual(dict(crates.STATE["reasons"]), {crates.POSITION_FAILURE_CATEGORY: 1})

    def test_the_preflight_only_runs_on_the_first_swing(self):
        with mock.patch.object(crates, "ensure_band", lambda host, client, handle, fallback: {"ok": True, "distances": [3.0], "seat": None}), \
                mock.patch.object(crates, "read_geometry", lambda client, host, context, aim: {}), mock.patch.object(crates, "run_preflight") as preflight, \
                mock.patch.object(crates, "crate_physics", lambda game, handle: {}):
            self.context["hostPark"] = {"x": 38.0, "y": 50.0}
            crates.before_swing(self.client, self.context, 2, {"x": 53.0, "y": 50.0})
        preflight.assert_not_called()

    def test_both_holds_are_released_after_the_swings_even_when_they_fail(self):
        with mock.patch.object(crates.world, "act", side_effect=RuntimeError("link died")):
            with self.assertRaises(RuntimeError):
                crates.act(self.client, self.context)
        self.assertIn(positioncontrol.RELEASE_COMMAND, [call[0] for call in self.client.calls])
        self.assertIn(positioncontrol.RELEASE_COMMAND, [call[0] for call in self.host.calls])


class PvpWiringTests(unittest.TestCase):
    def setUp(self):
        crates.reset_launch_state()
        self.addCleanup(crates.reset_launch_state)

    def test_a_victim_hold_that_does_not_verify_stops_the_run_before_any_punch_and_is_invalid(self):
        host, client = mock.Mock(), mock.Mock()
        context = {"host": host, "hostVictim": "id:9", "clientVictim": "id:-9", "measurements": []}
        with mock.patch.object(pvp_banded, "victim_position", lambda game, handle: {"x": 20.0, "y": 5.0}), mock.patch.object(pvp_banded, "record_start", lambda *a: None), \
                mock.patch.object(pvp_banded, "seat_victim", lambda game, spot: {"ok": False, "drifts": [0.9, 0.9]}), \
                mock.patch.object(pvp_banded.base, "player_position", lambda game: {"x": 16.8, "y": 5.0}), mock.patch.object(pvp_banded.hooks, "fire_one_swing") as fire:
            pvp_banded.act(client, context)
        fire.assert_not_called()
        self.assertEqual(context["measurements"], [])
        issues = pvp_banded.check(context)
        self.assertTrue(issues[0].startswith("INVALID: the position preflight failed"))
        self.assertEqual(crates.STATE["valid"], 0)
        self.assertEqual(dict(crates.STATE["reasons"]), {pvp_banded.POSITION_FAILURE_CATEGORY: 1})

    def test_an_overlapping_pair_at_the_first_punch_is_invalid_and_nothing_is_fired(self):
        host, client = mock.Mock(), mock.Mock()
        context = {"host": host, "hostVictim": "id:9", "clientVictim": "id:-9", "measurements": []}
        failed = {"ok": False, "issues": ["the bodies are 0.4 apart, below the 2.000 minimum: they overlap"]}
        with mock.patch.object(pvp_banded, "victim_position", lambda game, handle: {"x": 20.0, "y": 5.0}), mock.patch.object(pvp_banded, "record_start", lambda *a: None), \
                mock.patch.object(pvp_banded, "seat_victim", lambda game, spot: {"ok": True, "drifts": [0.0]}), mock.patch.object(pvp_banded, "preflight", lambda *a: failed), \
                mock.patch.object(pvp_banded.crates, "ensure_band", lambda *a, **k: {"ok": True, "distances": [2.85], "seat": {"x": 17.15, "y": 5.0}}), \
                mock.patch.object(pvp_banded.base, "player_position", lambda game: {"x": 16.8, "y": 5.0}), mock.patch.object(pvp_banded.hooks, "fire_one_swing") as fire:
            pvp_banded.act(client, context)
        fire.assert_not_called()
        self.assertIn("overlap", pvp_banded.check(context)[0])

    def test_the_victim_is_released_just_before_each_punch_and_both_holds_are_dropped_at_the_end(self):
        host, client = FakeBodyGame({"x": 20.0, "y": 5.0}), FakeBodyGame({"x": 17.15, "y": 5.0})
        context = {"host": host, "hostVictim": "id:9", "clientVictim": "id:-9", "measurements": []}
        released = []
        with mock.patch.object(pvp_banded, "victim_position", lambda game, handle: {"x": 20.0, "y": 5.0}), mock.patch.object(pvp_banded, "record_start", lambda *a: None), \
                mock.patch.object(pvp_banded, "seat_victim", lambda game, spot: {"ok": True, "drifts": [0.0]}), mock.patch.object(pvp_banded, "preflight", lambda *a: {"ok": True, "issues": []}), \
                mock.patch.object(pvp_banded.crates, "ensure_band", lambda *a, **k: {"ok": True, "distances": [2.85], "seat": {"x": 17.15, "y": 5.0}}), \
                mock.patch.object(pvp_banded.base, "player_position", lambda game: {"x": 17.15, "y": 5.0}), \
                mock.patch.object(pvp_banded.crates, "optional_read", lambda *a: None), mock.patch.object(pvp_banded.hooks, "limb_total", lambda game, handle: 100.0), \
                mock.patch.object(pvp_banded.hooks, "fire_one_swing", lambda game, aim: released.append(host.held is None) or False), mock.patch.object(pvp_banded.time, "sleep", no_sleep), \
                mock.patch.object(pvp_banded.evidence, "read_log", lambda which: ""):
            host.call(positioncontrol.HOLD_COMMAND, local=True, x=20.0, y=5.0, tolerance=0.05)
            pvp_banded.act(client, context)
        self.assertEqual(released, [True])
        self.assertIsNone(host.held)
        self.assertIn(positioncontrol.RELEASE_COMMAND, [call[0] for call in client.calls])


class MiningWiringTests(unittest.TestCase):
    def test_the_client_is_held_where_it_stands_the_host_is_parked_and_both_are_recorded(self):
        host, client = FakeBodyGame({"x": 0.0, "y": 0.0}), FakeBodyGame({"x": 30.0, "y": 40.0})
        context = {}
        with mock.patch.object(positioncontrol.time, "sleep", no_sleep):
            scenarios.apply_position_control(host, client, context)
        self.assertEqual(context["startPositions"]["client"], {"x": 30.0, "y": 40.0})
        self.assertTrue(context["positionControl"]["ok"], context["positionControl"]["issues"])
        self.assertEqual((client.held["x"], client.held["y"]), (30.0, 40.0))
        self.assertEqual((host.held["x"], host.held["y"]), (30.0 - HOST_PARK_DISTANCE, 40.0))

    def test_a_link_failure_while_seating_is_recorded_as_a_failed_preflight_not_raised(self):
        class Broken(FakeBodyGame):
            def call(self, command, **arguments):
                raise RuntimeError("no such command")

        host, client = FakeBodyGame({"x": 0.0, "y": 0.0}), Broken({"x": 30.0, "y": 40.0})
        context = {}
        scenarios.apply_position_control(host, client, context)
        self.assertFalse(context["positionControl"]["ok"])
        self.assertIn("RuntimeError", context["positionControl"]["issues"][0])

    def test_a_leaking_lock_makes_the_mining_run_invalid(self):
        host, client = FakeBodyGame({"x": 0.0, "y": 0.0}), FakeBodyGame({"x": 30.0, "y": 40.0}, leaky=True)
        context = {}
        with mock.patch.object(positioncontrol.time, "sleep", no_sleep):
            scenarios.apply_position_control(host, client, context)
        self.assertFalse(context["positionControl"]["ok"])

    def test_the_cleanup_releases_both_holds_and_tolerates_a_missing_client(self):
        host, client = FakeBodyGame({"x": 0.0, "y": 0.0}), FakeBodyGame({"x": 30.0, "y": 40.0})
        host.call(positioncontrol.HOLD_COMMAND, local=True, x=0.0, y=0.0, tolerance=0.05)
        client.call(positioncontrol.HOLD_COMMAND, local=True, x=30.0, y=40.0, tolerance=0.05)
        scenarios.release_holds(host, client)
        self.assertEqual((host.held, client.held), (None, None))
        scenarios.release_holds(host, None)

    def test_the_series_report_carries_the_start_positions_and_the_preflight(self):
        context = {"position": {"x": 1.0, "y": 1.0}, "startPositions": {"separation": 12.0}, "positionControl": {"ok": True, "issues": []}}
        scenario = mock.Mock()
        scenario.interval_seconds = 0.1
        observation = desync.SeriesObservation(scenario, {"host": [8, 0.0], "client": [8, 0.0]}, [{"t": 0.0, "host": [8, 0.0], "client": [8, 0.0]}], [], True, context)
        report = desync.describe_series(observation, "b", "00" * 32, "1.0", 100.0)
        self.assertEqual(report["startPositions"], {"separation": 12.0})
        self.assertEqual(report["positionControl"], {"ok": True, "issues": []})


if __name__ == "__main__":
    unittest.main()
