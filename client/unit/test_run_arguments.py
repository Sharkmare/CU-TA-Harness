import os
import unittest
from unittest import mock

import run_tests
from casualtieslink.games import buildregistry
from casualtieslink.scenarioengine import desync

REGISTRY = {"builds": {"example-flavour": {"kind": "flavour"}, "example-flavour-b": {"kind": "flavour"}}}


class RunArgumentTests(unittest.TestCase):
    def setUp(self):
        registry = buildregistry.use(REGISTRY)
        registry.__enter__()
        self.addCleanup(registry.__exit__, None, None, None)

    def test_the_together_option_is_read(self):
        self.assertEqual(run_tests.parse_args(["--pair", "--only", "desync", "--together", "example-flavour"]).together, "example-flavour")

    def test_without_the_option_none_is_given(self):
        self.assertIsNone(run_tests.parse_args(["--list"]).together)

    def test_the_build_reaches_the_environment_for_the_desync_module(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(desync.BUILD_ENVIRONMENT_VARIABLE, None)
            run_tests.main(["--list", "--only", "desync", "--together", "example-flavour-b"])
            self.assertEqual(os.environ.get(desync.BUILD_ENVIRONMENT_VARIABLE), "example-flavour-b")

    def test_the_delay_options_reach_the_environment(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for name in (desync.DELAY_ENVIRONMENT_VARIABLE, desync.JITTER_ENVIRONMENT_VARIABLE):
                os.environ.pop(name, None)
            run_tests.main(["--list", "--only", "desync", "--delay-ms", "100", "--jitter-ms", "20"])
            self.assertEqual(desync.delay_from_environment(), (100.0, 20.0))

    def test_without_a_delay_option_no_proxy_is_requested(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for name in (desync.DELAY_ENVIRONMENT_VARIABLE, desync.JITTER_ENVIRONMENT_VARIABLE):
                os.environ.pop(name, None)
            run_tests.main(["--list", "--only", "desync"])
            self.assertEqual(desync.delay_from_environment(), (None, 0.0))

    def test_a_delay_of_zero_still_means_a_proxy(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            run_tests.main(["--list", "--only", "desync", "--delay-ms", "0"])
            self.assertEqual(desync.delay_from_environment()[0], 0.0)

    def test_an_unknown_build_is_refused_before_anything_starts(self):
        with self.assertRaises(ValueError):
            run_tests.main(["--list", "--only", "desync", "--together", "nothing"])


if __name__ == "__main__":
    unittest.main()
