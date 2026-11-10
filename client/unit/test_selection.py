import os
import tempfile
import unittest

import selection

CONFIG = {
    "shared": ["lib/*.py"],
    "groups": [
        {"id": "a", "watch": ["tests/a.py"], "modules": ["tests.a"], "needs_game": False},
        {"id": "b", "watch": ["tests/b.py"], "modules": ["tests.b"], "needs_game": False},
    ],
}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = self.directory.name
        for name in ("lib/core.py", "tests/a.py", "tests/b.py"):
            self.write(name, "x = 1\n")

    def tearDown(self):
        self.directory.cleanup()

    def write(self, name, text):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)

    def passed_state(self):
        return {g["id"]: selection.group_fingerprint(self.root, CONFIG, g) for g in CONFIG["groups"]}

    def ids(self, state, **options):
        return [g["id"] for g in selection.select(self.root, CONFIG, state, **options)]

    def test_everything_runs_with_no_state(self):
        self.assertEqual(self.ids({}), ["a", "b"])

    def test_nothing_runs_when_nothing_changed(self):
        self.assertEqual(self.ids(self.passed_state()), [])

    def test_only_the_changed_groups_file_selects_that_group(self):
        state = self.passed_state()
        self.write("tests/b.py", "x = 2\n")
        self.assertEqual(self.ids(state), ["b"])

    def test_shared_file_selects_every_group(self):
        state = self.passed_state()
        self.write("lib/core.py", "x = 2\n")
        self.assertEqual(self.ids(state), ["a", "b"])

    def test_failed_group_stays_selected(self):
        state = self.passed_state()
        del state["a"]
        self.assertEqual(self.ids(state), ["a"])

    def test_added_shared_file_selects_everything(self):
        state = self.passed_state()
        self.write("lib/extra.py", "y = 1\n")
        self.assertEqual(self.ids(state), ["a", "b"])

    def test_deleted_watched_file_is_an_error_not_a_silent_skip(self):
        os.remove(os.path.join(self.root, "tests/a.py"))
        with self.assertRaises(ValueError):
            selection.select(self.root, CONFIG, {})

    def test_all_flag_runs_everything(self):
        self.assertEqual(self.ids(self.passed_state(), run_all=True), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
