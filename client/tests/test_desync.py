import os
import time
import unittest

from casualtieslink import desync
from casualtieslink.launcher import mp_arguments
from casualtieslink.instances import ScenarioGames, flavour_zip, stage_directory

from . import rig
from .desync_scenarios import CORPSE_FLAGS, SCENARIOS, SERIES_SCENARIOS, ready_up
from .test_pair import PAIR_ENABLED, SKIP_REASON, wait_for_bodies

STATE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".state")
REPORT_DIRECTORY = os.path.join(STATE_ROOT, "desync_reports")
WORLD_WAIT_SECONDS = 150.0
SETTLE_SECONDS = 10.0
TOGETHER_DLL_RELATIVE = os.path.join("BepInEx", "plugins", "Together", "CasualtiesMP.dll")

BUILD = desync.parse_build(os.environ.get(desync.BUILD_ENVIRONMENT_VARIABLE))
EXPECTED_HASH = desync.stage_dll_hash(stage_directory()) if BUILD == desync.STAGE_BUILD else desync.flavour_dll_hash(flavour_zip(), BUILD)
DELAY_MS, JITTER_MS = desync.delay_from_environment()
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
        report = desync.describe(observation, BUILD, EXPECTED_HASH, self.game_version)
        text = desync.format_report(report)
        print("\n" + text)
        desync.save_report(report, REPORT_DIRECTORY)
        self.assertEqual(report["verdict"], desync.VERDICT_PERSISTED, text)
    run.__name__ = "test_" + scenario.name
    run.__doc__ = scenario.description
    return run


def series_test(scenario):
    def run(self):
        observation = desync.observe_series(scenario, self.host, self.client, perform_action=not rig.mutation_active(desync.SKIP_ACTION_MUTATION))
        report = desync.describe_series(observation, BUILD, EXPECTED_HASH, self.game_version, DELAY_MS, JITTER_MS)
        text = desync.format_series_report(report)
        print("\n" + text)
        desync.save_series_report(report, REPORT_DIRECTORY)
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
            cls.host, cls.client = GAMES.start([], [], together=desync.together_choice(BUILD), client_extra=cls.client_extra, delay_ms=DELAY_MS, jitter_ms=JITTER_MS)
            if not ready_up([cls.host, cls.client]):
                raise AssertionError("the lobby ready gate did not accept both players")
            cls.host.wait_state("in-world", timeout=WORLD_WAIT_SECONDS)
            cls.client.wait_state("in-world", timeout=WORLD_WAIT_SECONDS)
            wait_for_bodies(cls.host, 2)
            wait_for_bodies(cls.client, 2)
            cls.host.call("close_console")
            cls.client.call("close_console")
            time.sleep(SETTLE_SECONDS)
            cls.game_version = str(cls.client.get("static:Application", "version", depth=0))
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


GROUP_CLIENT_ARGUMENTS = {"default": [], "mixed-characters": mp_arguments(CORPSE_FLAGS), "hand-mining": []}


def build_classes():
    classes = []
    for group in sorted({scenario.group for scenario in SCENARIOS + SERIES_SCENARIOS}):
        members = {}
        for scenario in SCENARIOS:
            if scenario.group == group:
                member = scenario_test(scenario)
                members[member.__name__] = member
        for scenario in SERIES_SCENARIOS:
            if scenario.group == group:
                member = series_test(scenario)
                members[member.__name__] = member
        members["client_extra"] = GROUP_CLIENT_ARGUMENTS[group]
        if group == "default":
            members["test_the_games_run_the_requested_build"] = DesyncMixin.test_the_games_run_the_requested_build
        delay = "" if DELAY_MS is None else "_delay%g" % DELAY_MS
        name = "Desync_%s_%s%s" % (desync.class_suffix(BUILD, EXPECTED_HASH), group.replace("-", "_"), delay.replace(".", "_"))
        classes.append(type(name, (DesyncMixin, unittest.TestCase), members))
    return classes


for generated in build_classes():
    globals()[generated.__name__] = generated
del generated


if __name__ == "__main__":
    unittest.main()
