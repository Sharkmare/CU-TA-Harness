import os
import tempfile
import unittest

import selection

CONFIG = {
    "groups": [
        {"id": "needs-game", "modules": ["tests.test_one", "tests.test_two"], "needs_game": True, "watch_plugin": True},
        {"id": "owns-game", "modules": ["tests.test_four"], "owns_game": True, "watch_plugin": True},
        {"id": "offline", "modules": ["tests.test_three"]},
        {"id": "commands", "modules": [{"id": "dotnet", "command": ["dotnet", "run"], "watch": ["../plugin-tests/*.cs"]}]},
    ],
}

FILES = {
    "client/pkg/__init__.py": "",
    "client/pkg/a.py": "A = 1\n",
    "client/pkg/b.py": "B = 1\n",
    "client/pkg/c.py": "from . import a\n",
    "client/pkg/deep/__init__.py": "",
    "client/pkg/deep/d.py": "from .. import b\n",
    "client/tests/__init__.py": "",
    "client/tests/test_one.py": "from pkg import a\n",
    "client/tests/test_two.py": "import pkg.b\n",
    "client/tests/test_three.py": "from pkg.c import A\n",
    "client/tests/test_four.py": "from pkg.deep.d import B\n",
    "plugin/p.cs": "class P {}\n",
    "plugin-tests/t.cs": "class T {}\n",
}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.base = self.directory.name
        for name, text in FILES.items():
            self.write(name, text)
        self.root = os.path.join(self.base, "client")
        self.roots = [self.root]

    def tearDown(self):
        self.directory.cleanup()

    def write(self, name, text):
        path = os.path.join(self.base, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="") as handle:
            handle.write(text)

    def select(self, state, **options):
        return selection.select_units(self.root, self.roots, CONFIG, state, **options)

    def names(self, selected):
        return sorted(selection.unit_id(u["unit"]) for entry in selected for u in entry["units"])

    def pass_everything(self):
        state = {}
        for entry in self.select({}):
            for unit_entry in entry["units"]:
                selection.record_pass(state, unit_entry)
        return state

    def test_everything_is_selected_with_no_state_and_says_why(self):
        selected = self.select({})
        self.assertEqual(self.names(selected), ["cmd:dotnet", "tests.test_four", "tests.test_one", "tests.test_three", "tests.test_two"])
        self.assertEqual(selected[0]["units"][0]["reasons"], ["never passed"])

    def test_nothing_is_selected_when_nothing_changed(self):
        self.assertEqual(self.select(self.pass_everything()), [])

    def test_a_changed_module_selects_only_what_imports_it_directly_or_through_others(self):
        state = self.pass_everything()
        self.write("client/pkg/a.py", "A = 2\n")
        selected = self.select(state)
        self.assertEqual(self.names(selected), ["tests.test_one", "tests.test_three"])
        self.assertEqual(selected[0]["units"][0]["reasons"], ["pkg/a.py"])

    def test_a_relative_import_two_levels_up_is_followed(self):
        state = self.pass_everything()
        self.write("client/pkg/b.py", "B = 2\n")
        self.assertEqual(self.names(self.select(state)), ["tests.test_four", "tests.test_two"])

    def test_a_package_initialiser_selects_everything_below_it(self):
        state = self.pass_everything()
        self.write("client/pkg/__init__.py", "X = 1\n")
        self.assertEqual(self.names(self.select(state)), ["tests.test_four", "tests.test_one", "tests.test_three", "tests.test_two"])

    def test_a_changed_test_file_selects_only_itself(self):
        state = self.pass_everything()
        self.write("client/tests/test_two.py", "import pkg.b\nX = 1\n")
        self.assertEqual(self.names(self.select(state)), ["tests.test_two"])

    def test_plugin_sources_select_only_groups_that_watch_the_plugin(self):
        state = self.pass_everything()
        self.write("plugin/p.cs", "class P { int x; }\n")
        self.assertEqual(self.names(self.select(state)), ["tests.test_four", "tests.test_one", "tests.test_two"])

    def test_command_units_watch_their_own_globs(self):
        state = self.pass_everything()
        self.write("plugin-tests/t.cs", "class T { int x; }\n")
        self.assertEqual(self.names(self.select(state)), ["cmd:dotnet"])

    def test_offline_never_selects_groups_that_start_the_game(self):
        selected = self.select({}, offline=True)
        self.assertEqual(self.names(selected), ["cmd:dotnet", "tests.test_three"])

    def test_a_failed_unit_stays_selected_until_it_passes(self):
        state = self.pass_everything()
        unit_entry = self.select({}, only=["offline"])[0]["units"][0]
        selection.record_failure(state, unit_entry)
        self.assertEqual(self.names(self.select(state)), ["tests.test_three"])

    def test_line_ending_changes_alone_do_not_select_anything(self):
        state = self.pass_everything()
        self.write("client/pkg/a.py", "A = 1\r\n")
        self.assertEqual(self.select(state), [])

    def test_a_deleted_dependency_is_noticed(self):
        state = self.pass_everything()
        os.remove(os.path.join(self.root, "pkg", "c.py"))
        selected = self.select(state)
        unit_entry = next(u for entry in selected for u in entry["units"] if u["unit"] == "tests.test_three")
        self.assertIn("pkg/c.py", unit_entry["reasons"])

    def test_all_forces_every_unit(self):
        state = self.pass_everything()
        selected = self.select(state, run_all=True)
        self.assertEqual(len(self.names(selected)), 5)
        self.assertEqual(selected[0]["units"][0]["reasons"], ["forced"])

    def test_a_unit_with_nothing_to_watch_is_an_error(self):
        config = {"groups": [{"id": "g", "modules": ["tests.missing"]}]}
        with self.assertRaises(ValueError):
            selection.select_units(self.root, self.roots, config, {})

    def test_imported_modules_resolves_relative_levels(self):
        path = os.path.join(self.root, "pkg", "deep", "d.py")
        self.assertIn("pkg.b", selection.imported_modules(path, "pkg.deep.d"))

    def test_old_state_files_are_ignored(self):
        state_path = os.path.join(self.base, "state.json")
        with open(state_path, "w") as handle:
            handle.write('{"link": "abc"}')
        self.assertEqual(selection.load_state(state_path), {})

    def test_state_round_trips(self):
        state_path = os.path.join(self.base, "state.json")
        selection.save_state(state_path, {"tests.test_one": {"pkg/a.py": "h"}})
        self.assertEqual(selection.load_state(state_path), {"tests.test_one": {"pkg/a.py": "h"}})


if __name__ == "__main__":
    unittest.main()
