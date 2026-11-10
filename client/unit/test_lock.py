import os
import tempfile
import unittest

from casualtieslink.lock import GameLock, GameLockHeld


class GameLockTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, ".game.lock")

    def tearDown(self):
        self.directory.cleanup()

    def test_second_acquire_is_refused_and_names_the_owner(self):
        first = GameLock("first", self.path).acquire()
        with self.assertRaises(GameLockHeld) as caught:
            GameLock("second", self.path).acquire()
        self.assertIn("first", str(caught.exception))
        first.release()

    def test_a_refused_lock_does_not_delete_the_owners_file(self):
        first = GameLock("first", self.path).acquire()
        second = GameLock("second", self.path)
        with self.assertRaises(GameLockHeld):
            second.acquire()
        second.release()
        self.assertTrue(os.path.exists(self.path))
        first.release()
        self.assertFalse(os.path.exists(self.path))


if __name__ == "__main__":
    unittest.main()
