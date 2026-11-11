import os
import time
import unittest

from casualtieslink import desync
from casualtieslink.instances import ScenarioGames, flavour_zip, stage_directory

from . import rig
from .desync_scenarios import SCENARIOS, ready_up
from .test_pair import PAIR_ENABLED, SKIP_REASON, wait_for_bodies

STATE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".state")
REPORT_DIRECTORY = os.path.join(STATE_ROOT, "desync_reports")
WORLD_WAIT_SECONDS = 150.0
SETTLE_SECONDS = 10.0
TOGETHER_DLL_RELATIVE = os.path.join("BepInEx", "plugins", "Together", "CasualtiesMP.dll")

BUILD = desync.parse_build(os.environ.get(desync.BUILD_ENVIRONMENT_VARIABLE))
EXPECTED_HASH = desync.stage_dll_hash(stage_directory()) if BUILD == desync.STAGE_BUILD else desync.flavour_dll_hash(flavour_zip(), BUILD)
GAMES = None


def setUpModule():
    global GAMES
    if PAIR_ENABLED:
        GAMES = ScenarioGames(STATE_ROOT)
        GAMES.prepare()


def tearDownModule():
    if GAMES is not None:
        GAMES.dispose()


def scenario_test(scenario):
    def run(self):
        observation = desync.observe(scenario, self.host, self.client, perform_action=not rig.mutation_active(desync.SKIP_ACTION_MUTATION))
        report = desync.describe(observation, BUILD, EXPECTED_HASH)
        text = desync.format_report(report)
        print("\n" + text)
        desync.save_report(report, REPORT_DIRECTORY)
        self.assertEqual(report["verdict"], desync.VERDICT_PERSISTED, text)
    run.__name__ = "test_" + scenario.name
    run.__doc__ = scenario.description
    return run


class DesyncMixin:
    @classmethod
    def setUpClass(cls):
        if not PAIR_ENABLED or GAMES is None:
            raise unittest.SkipTest(SKIP_REASON)
        if EXPECTED_HASH == desync.UNKNOWN_HASH:
            raise unittest.SkipTest("no DLL found for build %s (set CU_FLAVOUR_ZIP or CU_UPSTREAM_STAGE)" % BUILD)
        try:
            cls.host, cls.client = GAMES.start([], [], together=desync.together_choice(BUILD))
            if not ready_up([cls.host, cls.client]):
                raise AssertionError("the lobby ready gate did not accept both players")
            cls.host.wait_state("in-world", timeout=WORLD_WAIT_SECONDS)
            cls.client.wait_state("in-world", timeout=WORLD_WAIT_SECONDS)
            wait_for_bodies(cls.host, 2)
            wait_for_bodies(cls.client, 2)
            cls.host.call("close_console")
            cls.client.call("close_console")
            time.sleep(SETTLE_SECONDS)
        except BaseException:
            for which in ("host", "client"):
                print("\n%s log tail:" % which)
                for line in GAMES.log_text(which).splitlines()[-40:]:
                    print("  " + line[:200])
            GAMES.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        if GAMES is not None:
            GAMES.stop()

    def test_the_games_run_the_requested_build(self):
        for which, copy in (("host", GAMES.host_copy), ("client", GAMES.client_copy)):
            self.assertEqual(desync.sha256_of_file(os.path.join(copy, TOGETHER_DLL_RELATIVE)), EXPECTED_HASH, "%s runs another Together DLL than %s" % (which, BUILD))


def build_class():
    members = {scenario_test(scenario).__name__: scenario_test(scenario) for scenario in SCENARIOS}
    name = "Desync_" + desync.class_suffix(BUILD, EXPECTED_HASH)
    return type(name, (DesyncMixin, unittest.TestCase), members)


DesyncBuildTests = build_class()
globals()[DesyncBuildTests.__name__] = DesyncBuildTests
del DesyncBuildTests

if __name__ == "__main__":
    unittest.main()
