import unittest
from unittest import mock

from scenarios import band, swing_driver


class FakeClient:
    """A client whose attack cooldown rises after `ignored` invokes that did nothing."""

    def __init__(self, ignored=0):
        self.ignored = ignored
        self.cooldown = 0.0
        self.invokes = []

    def get(self, target, path, depth=0):
        assert (target, path) == ("player", "attackCooldown")
        return self.cooldown

    def call(self, command, **arguments):
        assert command == "invoke"
        self.invokes.append(arguments)
        if self.ignored > 0:
            self.ignored -= 1
        else:
            self.cooldown += 1.0


class FireOneSwingTests(unittest.TestCase):
    def test_a_swing_that_raises_the_cooldown_is_fired_once_at_the_target(self):
        client = FakeClient()
        self.assertTrue(swing_driver.fire_one_swing(client, {"x": 3.0, "y": 4.0}))
        self.assertEqual(len(client.invokes), 1)
        self.assertEqual(client.invokes[0]["method"], "UseItemInHand")
        self.assertEqual(client.invokes[0]["sets"][0]["value"], {"x": 3.0, "y": 4.0, "z": 0.0})

    def test_ignored_invokes_are_retried_and_counted(self):
        client = FakeClient(ignored=2)
        attempts = {}
        with mock.patch.object(swing_driver.time, "sleep", lambda seconds: None):
            self.assertTrue(swing_driver.fire_one_swing(client, {"x": 0.0, "y": 0.0}, attempts=attempts))
        self.assertEqual((len(client.invokes), attempts["ignored"]), (3, 2))

    def test_a_swing_the_game_never_accepts_gives_up_after_the_timeout(self):
        client = FakeClient(ignored=10 ** 6)
        clock = iter([0.0, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0])
        with mock.patch.object(swing_driver.time, "time", lambda: next(clock)), mock.patch.object(swing_driver.time, "sleep", lambda seconds: None):
            self.assertFalse(swing_driver.fire_one_swing(client, {"x": 0.0, "y": 0.0}, timeout=2.0))
        self.assertGreater(len(client.invokes), 1)


class BandTests(unittest.TestCase):
    TARGET = {"x": 20.0, "y": 5.0}

    def setUp(self):
        self.player = {"x": self.TARGET["x"] - band.BAND_TARGET, "y": 5.0}
        self.seats = []
        self.client = mock.Mock()
        self.client.get.side_effect = lambda target, path, depth=0: dict(self.player)

    def seat(self, client, point):
        self.seats.append(point)
        self.player = dict(point)

    def ensure(self, **options):
        return band.ensure_band(None, self.client, "id:1", self.TARGET, seat=self.seat, read_position=lambda host, handle: self.TARGET, **options)

    def test_every_distance_inside_the_band_needs_no_re_seat(self):
        for distance in (band.BAND_LOW, 2.9, band.BAND_HIGH):
            with self.subTest(distance=distance):
                self.player = {"x": self.TARGET["x"] - distance, "y": 5.0}
                result = self.ensure()
                self.assertEqual((result["ok"], result["reseats"], result["distances"]), (True, 0, [distance]))
        self.assertEqual(self.seats, [])

    def test_a_distance_outside_the_band_is_re_seated_to_the_band_middle(self):
        self.player = {"x": self.TARGET["x"] - 8.0, "y": 5.0}
        result = self.ensure()
        self.assertEqual((result["ok"], result["reseats"]), (True, 1))
        self.assertEqual(self.seats, [{"x": self.TARGET["x"] - band.BAND_TARGET, "y": 5.0}])

    def test_the_side_decides_which_side_of_the_target_is_seated(self):
        self.player = {"x": 0.0, "y": 5.0}
        self.ensure(side=1)
        self.assertGreater(self.seats[0]["x"], self.TARGET["x"])

    def test_a_seat_height_keeps_the_distance_in_the_band_with_a_shorter_offset(self):
        self.player = {"x": 0.0, "y": 5.0}
        result = self.ensure(seat_y=6.0)
        self.assertEqual(self.seats[0]["y"], 6.0)
        self.assertLess(abs(self.seats[0]["x"] - self.TARGET["x"]), band.BAND_TARGET)
        self.assertTrue(result["ok"])

    def test_a_seat_that_never_reaches_the_band_stops_after_the_planned_tries(self):
        def stuck(client, point):
            self.seats.append(point)

        self.player = {"x": 0.0, "y": 5.0}
        result = band.ensure_band(None, self.client, "id:1", self.TARGET, seat=stuck, read_position=lambda host, handle: self.TARGET)
        self.assertEqual((result["ok"], result["reseats"], len(self.seats)), (False, band.BAND_TRIES, band.BAND_TRIES))

    def test_the_offset_never_falls_below_the_minimum(self):
        self.player = {"x": self.TARGET["x"] - 50.0, "y": 5.0}
        result = self.ensure()
        self.assertTrue(all(offset >= band.MIN_RESEAT_OFFSET for offset in result["offsets"]))

    def test_the_host_position_read_gives_none_when_the_game_cannot_answer(self):
        host = mock.Mock()
        host.get.side_effect = RuntimeError("gone")
        self.assertIsNone(band.host_position(host, "id:1"))
        host.get.side_effect = None
        host.get.return_value = {"x": 1, "y": 2}
        self.assertEqual(band.host_position(host, "id:1"), {"x": 1.0, "y": 2.0})


if __name__ == "__main__":
    unittest.main()
