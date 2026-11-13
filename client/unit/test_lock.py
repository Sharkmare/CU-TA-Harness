import os
import tempfile
import unittest

from casualtieslink import lock as lock_module
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

    def test_the_default_lock_does_not_depend_on_where_the_checkout_is(self):
        checkout = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(lock_module.__file__))))
        self.assertFalse(os.path.abspath(lock_module.LOCK_PATH).startswith(checkout + os.sep))
        self.assertEqual(lock_module.default_lock_path({}, self.directory.name), os.path.join(self.directory.name, lock_module.LOCK_FILE_NAME))

    def test_the_environment_variable_overrides_the_default_lock_path(self):
        self.assertEqual(lock_module.default_lock_path({lock_module.LOCK_ENVIRONMENT_VARIABLE: self.path}, "unused"), os.path.abspath(self.path))

    def test_two_locks_made_from_different_checkouts_collide(self):
        first = GameLock("checkout one").acquire()
        try:
            with self.assertRaises(GameLockHeld):
                GameLock("checkout two", lock_module.default_lock_path({}, tempfile.gettempdir())).acquire()
        finally:
            first.release()


if __name__ == "__main__":
    unittest.main()
