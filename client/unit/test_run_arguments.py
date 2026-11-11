import os
import unittest
from unittest import mock

import run_tests
from casualtieslink import desync


class RunArgumentTests(unittest.TestCase):
    def test_the_together_option_is_read(self):
        self.assertEqual(run_tests.parse_args(["--pair", "--only", "desync", "--together", "fork"]).together, "fork")

    def test_without_the_option_none_is_given(self):
        self.assertIsNone(run_tests.parse_args(["--list"]).together)

    def test_the_build_reaches_the_environment_for_the_desync_module(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(desync.BUILD_ENVIRONMENT_VARIABLE, None)
            run_tests.main(["--list", "--only", "desync", "--together", "stock-5.4.0"])
            self.assertEqual(os.environ.get(desync.BUILD_ENVIRONMENT_VARIABLE), "stock-5.4.0")

    def test_an_unknown_build_is_refused_before_anything_starts(self):
        with self.assertRaises(ValueError):
            run_tests.main(["--list", "--only", "desync", "--together", "stock-1.0"])


if __name__ == "__main__":
    unittest.main()
