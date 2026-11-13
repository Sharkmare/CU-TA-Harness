import os
import tempfile
import unittest

from casualtieslink.games import testcopy

BOOT = "gfx-enable-gfx-jobs=1\nsingle-instance=\nbuild-guid=abc\n"


def make_fake_game(root):
    os.makedirs(os.path.join(root, "CasualtiesUnknown_Data"))
    with open(os.path.join(root, testcopy.BOOT_CONFIG_RELATIVE), "w") as handle:
        handle.write(BOOT)
    os.makedirs(os.path.join(root, "BepInEx", "TogetherLogs"))
    with open(os.path.join(root, "BepInEx", "LogOutput.log"), "w") as handle:
        handle.write("old log")


class TestCopyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.source = os.path.join(self.directory.name, "game")
        self.destination = os.path.join(self.directory.name, "copy")
        make_fake_game(self.source)

    def tearDown(self):
        self.directory.cleanup()

    def boot_text(self, root):
        with open(os.path.join(root, testcopy.BOOT_CONFIG_RELATIVE)) as handle:
            return handle.read()

    def test_only_the_single_instance_line_is_removed(self):
        text, removed = testcopy.without_single_instance(BOOT)
        self.assertTrue(removed)
        self.assertEqual(text, "gfx-enable-gfx-jobs=1\nbuild-guid=abc\n")

    def test_copy_can_drop_the_line_and_leaves_the_source_alone(self):
        testcopy.make_copy(self.destination, self.source, remove_single_instance=True)
        self.assertNotIn("single-instance", self.boot_text(self.destination))
        self.assertIn("single-instance", self.boot_text(self.source))
        self.assertFalse(os.path.exists(os.path.join(self.destination, "BepInEx", "LogOutput.log")))

    def test_default_copy_is_unmodified(self):
        testcopy.make_copy(self.destination, self.source)
        self.assertIn("single-instance", self.boot_text(self.destination))

    def test_copy_is_rerunnable_and_removable(self):
        testcopy.make_copy(self.destination, self.source)
        testcopy.make_copy(self.destination, self.source)
        testcopy.remove_copy(self.destination)
        self.assertFalse(os.path.exists(self.destination))

    def test_a_folder_that_is_not_a_test_copy_is_never_deleted(self):
        os.makedirs(self.destination)
        with self.assertRaises(ValueError):
            testcopy.make_copy(self.destination, self.source)
        with self.assertRaises(ValueError):
            testcopy.remove_copy(self.destination)
        self.assertTrue(os.path.isdir(self.destination))

    def test_destinations_inside_the_source_or_this_repository_are_refused(self):
        with self.assertRaises(ValueError):
            testcopy.make_copy(os.path.join(self.source, "inner"), self.source)
        with self.assertRaises(ValueError):
            testcopy.make_copy(os.path.join(testcopy.REPO_ROOT, "game-copy"), self.source)

    def test_missing_line_is_an_error_not_a_silent_copy(self):
        with open(os.path.join(self.source, testcopy.BOOT_CONFIG_RELATIVE), "w") as handle:
            handle.write("gfx-enable-gfx-jobs=1\n")
        with self.assertRaises(RuntimeError):
            testcopy.make_copy(self.destination, self.source, remove_single_instance=True)


class RepositoryRootTests(unittest.TestCase):
    def test_the_repository_root_is_the_folder_holding_client_and_plugin(self):
        self.assertTrue(os.path.isfile(os.path.join(testcopy.REPO_ROOT, "client", "run_tests.py")))
        self.assertTrue(os.path.isdir(os.path.join(testcopy.REPO_ROOT, "plugin")))


if __name__ == "__main__":
    unittest.main()
