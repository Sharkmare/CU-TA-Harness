import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hookbench_logs as logs


class KeepLogsTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.copy = os.path.join(self.root, "copy")
        os.makedirs(os.path.join(self.copy, "BepInEx"))
        with open(os.path.join(self.copy, "BepInEx", "LogOutput.log"), "w") as handle:
            handle.write("hang reason: world generation stalled\n")
        self.destination = os.path.join(self.root, "kept")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_the_log_survives_the_deletion_of_the_copy(self):
        written = logs.keep_logs({"host": self.copy}, self.destination, "run")
        shutil.rmtree(self.copy)
        self.assertFalse(os.path.exists(self.copy))
        self.assertEqual(len(written), 1)
        self.assertTrue(os.path.isfile(written[0]), "the kept log is gone after the copy was deleted")
        with open(written[0]) as handle:
            self.assertIn("world generation stalled", handle.read())

    def test_without_keeping_the_log_is_lost(self):
        shutil.rmtree(self.copy)
        self.assertFalse(os.path.isdir(self.destination))

    def test_a_missing_log_or_directory_is_skipped(self):
        self.assertEqual(logs.keep_logs({"host": os.path.join(self.root, "nothing"), "client": None}, self.destination, "run"), [])

    def test_each_copy_gets_its_own_file(self):
        other = os.path.join(self.root, "other")
        os.makedirs(os.path.join(other, "BepInEx"))
        with open(os.path.join(other, "BepInEx", "LogOutput.log"), "w") as handle:
            handle.write("client side\n")
        written = logs.keep_logs({"host": self.copy, "client": other}, self.destination, "run")
        self.assertEqual(sorted(os.path.basename(path) for path in written), ["run_client_LogOutput.log", "run_host_LogOutput.log"])


if __name__ == "__main__":
    unittest.main()
