import io
import json
import os
import re
import unittest
from unittest import mock

import run_tests

CONFIG = os.path.join(os.path.dirname(os.path.abspath(run_tests.__file__)), "test_groups.json")
TESTS_DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(run_tests.__file__)), "tests")
INSTALLED_GROUPS = ("inert", "link", "run", "world")
ORIGINAL_RUN_ENTRY = run_tests.run_entry


class Recorder:
    def __init__(self):
        self.events = []


class FakeGuard:
    instances = []

    def __init__(self, root):
        self.root = root
        self.taken = False
        self.restored = 0
        FakeGuard.instances.append(self)
        self.recorder = None

    def snapshot(self):
        self.taken = True
        self.recorder.events.append("snapshot")

    def restore(self):
        self.restored += 1
        self.taken = False
        self.recorder.events.append("restore")


class MainHarness(unittest.TestCase):
    def setUp(self):
        self.recorder = Recorder()
        FakeGuard.instances = []
        self.started = []
        self.output = io.StringIO()

        def forbidden(name):
            def call(*args, **kwargs):
                raise AssertionError("%s was called: a game or a process would have started" % name)
            return call

        self.forbidden = forbidden
        recorder = self.recorder

        class RecordingGuard(FakeGuard):
            def __init__(self, root):
                super().__init__(root)
                self.recorder = recorder

        self.guard_class = RecordingGuard
        self.patches = [mock.patch.object(run_tests.selection, "save_state", lambda path, state: None), mock.patch("sys.stdout", self.output)]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def run_main(self, arguments, **replacements):
        defaults = {"GameProcess": self.forbidden("GameProcess"), "GameLock": self.forbidden("GameLock"), "run_module": self.forbidden("run_module"),
                    "run_command": self.forbidden("run_command"), "ProfileGuard": self.forbidden("ProfileGuard"), "run_entry": self.forbidden("run_entry")}
        defaults.update(replacements)
        patches = [mock.patch.object(run_tests, name, value) for name, value in defaults.items()]
        patches.append(mock.patch.object(run_tests.subprocess, "run", self.forbidden("subprocess.run")))
        for patch in patches:
            patch.start()
        try:
            return run_tests.main(arguments)
        finally:
            for patch in reversed(patches):
                patch.stop()


class RefusalTests(MainHarness):
    def test_a_run_without_flags_that_selects_the_single_game_groups_refuses_and_starts_nothing(self):
        code = self.run_main(["--all"])
        self.assertEqual(code, run_tests.REFUSED_EXIT_CODE)
        text = self.output.getvalue()
        for group in INSTALLED_GROUPS:
            self.assertIn(group, text.split("refusing", 1)[1].splitlines()[0])
        for flag in ("--offline", "--pair", "--builds", "--attach", "--allow-installed-launch", "--list"):
            self.assertIn(flag, text)
        self.assertEqual(FakeGuard.instances, [])

    def test_nothing_is_snapshotted_locked_or_run_when_it_refuses(self):
        self.run_main(["--all"])
        self.assertEqual(self.recorder.events, [])

    def test_the_offline_suite_never_refuses_and_never_starts_a_game(self):
        ran = []
        code = self.run_main(["--offline", "--all"], run_module=lambda module, fragment, failfast: ran.append(module) or mock.Mock(testsRun=1, failures=[], errors=[], skipped=[], expectedFailures=[], unexpectedSuccesses=[], wasSuccessful=lambda: True),
                             run_command=lambda unit: True, run_entry=ORIGINAL_RUN_ENTRY)
        self.assertEqual(code, 0)
        self.assertTrue(ran)
        self.assertFalse(any(module in ("tests.test_link", "tests.test_run", "tests.test_world", "tests.test_inert") for module in ran))

    def test_listing_never_refuses_and_never_starts_anything(self):
        self.assertEqual(self.run_main(["--list", "--all"]), 0)

    def test_attaching_to_a_running_game_does_not_refuse_or_snapshot_or_launch(self):
        bound = []
        code = self.run_main(["--attach", "--only", "link"], run_entry=lambda entry, state, totals, arguments, timings: [], Game=lambda port: mock.Mock(), **{})
        self.assertEqual(code, 0)
        self.assertEqual(self.recorder.events, [])

    def test_the_groups_that_start_their_own_copies_are_not_refused(self):
        self.assertEqual(run_tests.installed_launch_groups([{"group": {"id": "desync", "owns_game": True}}, {"group": {"id": "pair", "owns_game": True}}]), [])


class AllowedLaunchTests(MainHarness):
    def fake_process_class(self):
        recorder = self.recorder

        class FakeProcess:
            def __init__(self, port, arguments):
                self.game = mock.Mock()
                self.pid = 1

            def start(self):
                recorder.events.append("launch")
                return {"version": "test"}

            def close(self):
                recorder.events.append("close")

        return FakeProcess

    def fake_lock(self):
        recorder = self.recorder

        class FakeLock:
            def __init__(self, reason):
                pass

            def acquire(self):
                recorder.events.append("lock")
                return self

            def release(self):
                recorder.events.append("unlock")

        return FakeLock

    def run_allowed(self, run_entry, only="link"):
        return self.run_main(["--allow-installed-launch", "--only", only], GameProcess=self.fake_process_class(), GameLock=self.fake_lock(), ProfileGuard=self.guard_class,
                             run_entry=run_entry, rig=mock.Mock())

    def test_the_profile_is_snapshotted_before_the_game_starts_and_restored_after_it_closes(self):
        def run_entry(entry, state, totals, arguments, timings):
            self.recorder.events.append("run:" + entry["group"]["id"])
            return []

        self.assertEqual(self.run_allowed(run_entry), 0)
        events = self.recorder.events
        self.assertLess(events.index("snapshot"), events.index("launch"))
        self.assertLess(events.index("launch"), events.index("run:link"))
        self.assertLess(events.index("run:link"), events.index("close"))
        self.assertLess(events.index("close"), events.index("restore"))

    def test_a_single_game_group_never_runs_while_the_snapshot_guard_is_not_taken(self):
        seen = []

        def run_entry(entry, state, totals, arguments, timings):
            seen.append((entry["group"]["id"], [guard.taken for guard in FakeGuard.instances]))
            return []

        self.run_allowed(run_entry)
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0][1] and all(seen[0][1]), seen)

    def test_the_profile_is_restored_even_when_the_group_raises(self):
        def run_entry(entry, state, totals, arguments, timings):
            raise RuntimeError("the test run blew up")

        with self.assertRaises(RuntimeError):
            self.run_allowed(run_entry)
        self.assertEqual(self.recorder.events[-1], "restore")
        self.assertIn("close", self.recorder.events)
        self.assertTrue(all(guard.restored == 1 for guard in FakeGuard.instances))

    def test_the_inert_group_which_launches_its_own_game_from_the_installed_folder_is_guarded_too(self):
        events = []

        def run_entry(entry, state, totals, arguments, timings):
            events.append((entry["group"]["id"], [guard.taken for guard in FakeGuard.instances]))
            return []

        self.run_allowed(run_entry, only="inert")
        self.assertEqual(events, [("inert", [True])])
        self.assertEqual(self.recorder.events.count("snapshot"), 1)

    def test_one_snapshot_wraps_all_selected_single_game_groups(self):
        def run_entry(entry, state, totals, arguments, timings):
            self.recorder.events.append("run:" + entry["group"]["id"])
            return []

        self.run_main(["--allow-installed-launch", "--only", "inert", "link", "run"], GameProcess=self.fake_process_class(), GameLock=self.fake_lock(), ProfileGuard=self.guard_class,
                      run_entry=run_entry, rig=mock.Mock())
        self.assertEqual(self.recorder.events.count("snapshot"), 1)
        self.assertEqual(self.recorder.events.count("restore"), 1)
        events = self.recorder.events
        for group in ("run:inert", "run:link", "run:run"):
            self.assertLess(events.index("snapshot"), events.index(group))
            self.assertLess(events.index(group), events.index("restore"))


class ConfigTests(unittest.TestCase):
    def groups(self):
        with open(CONFIG, encoding="utf-8") as handle:
            return {group["id"]: group for group in json.load(handle)["groups"]}

    def test_the_four_single_game_groups_are_flagged(self):
        groups = self.groups()
        for group_id in INSTALLED_GROUPS:
            self.assertTrue(groups[group_id].get("uses_installed_game"), group_id)

    def test_the_copy_based_and_offline_groups_are_not_flagged(self):
        for group_id, group in self.groups().items():
            if group_id not in INSTALLED_GROUPS:
                self.assertFalse(group.get("uses_installed_game"), group_id)

    def test_every_test_module_that_starts_a_game_process_without_a_copy_belongs_to_a_flagged_group(self):
        groups = self.groups()
        flagged_modules = set()
        for group in groups.values():
            if group.get("uses_installed_game"):
                for module in group["modules"]:
                    flagged_modules.add(module if isinstance(module, str) else module.get("id"))
        problems = []
        for name in sorted(os.listdir(TESTS_DIRECTORY)):
            if not name.startswith("test_") or not name.endswith(".py"):
                continue
            with open(os.path.join(TESTS_DIRECTORY, name), encoding="utf-8") as handle:
                source = handle.read()
            for match in re.finditer(r"GameProcess\(([^)]*)\)", source):
                if "directory=" not in match.group(0) and "tests." + name[:-3] not in flagged_modules:
                    problems.append("%s starts GameProcess(%s) without a copy and is not in a group flagged uses_installed_game" % (name, match.group(1)[:50]))
            if "needs_game" in source:
                continue
        self.assertEqual(problems, [])

    def test_the_shared_session_groups_that_need_the_game_are_all_flagged(self):
        for group_id, group in self.groups().items():
            if group.get("needs_game"):
                self.assertTrue(group.get("uses_installed_game"), group_id)


if __name__ == "__main__":
    unittest.main()
