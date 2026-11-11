import os
import time
import unittest

from casualtieslink import desync, launchplan
from casualtieslink.instances import ScenarioGames, flavour_zip, stage_directory
from casualtieslink.launcher import mp_arguments

from . import rig
from .desync_scenarios import CORPSE_FLAGS, SCENARIOS, SERIES_SCENARIOS, ready_up, reset_between_scenarios
from .test_pair import PAIR_ENABLED, SKIP_REASON, wait_for_bodies

STATE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".state")
REPORT_DIRECTORY = os.path.join(STATE_ROOT, "desync_reports")
WORLD_WAIT_SECONDS = 150.0
SETTLE_SECONDS = 10.0
TOGETHER_DLL_RELATIVE = os.path.join("BepInEx", "plugins", "Together", "CasualtiesMP.dll")

BUILD = desync.parse_build(os.environ.get(desync.BUILD_ENVIRONMENT_VARIABLE))
EXPECTED_HASH = desync.stage_dll_hash(stage_directory()) if BUILD == desync.STAGE_BUILD else desync.flavour_dll_hash(flavour_zip(), BUILD)
PROFILES = desync.profiles_from_environment()
REPEAT = desync.repeat_from_environment()
LAUNCH_ID = desync.launch_id_from_environment()
ONLY_GROUP = desync.group_from_environment()
GAMES = None


def setUpModule():
    global GAMES
    if PAIR_ENABLED:
        GAMES = ScenarioGames(STATE_ROOT)
        GAMES.prepare()


def tearDownModule():
    if GAMES is not None:
        GAMES.dispose()


def check_games_answer(case):
    for label, game in (("host", case.host), ("client", case.client)):
        try:
            game.state()
        except Exception as exception:
            case.fail("the %s game does not answer: %s" % (label, exception))


def prepare_run(case, profile):
    check_games_answer(case)
    reset_between_scenarios(case.host, case.client)
    GAMES.apply_network(profile)
    time.sleep(desync.SETTLE_AFTER_NETWORK_CHANGE_SECONDS)


def restore_network():
    GAMES.apply_network(launchplan.DIRECT)


def scenario_method(run):
    scenario = run.scenario

    def method(self):
        prepare_run(self, run.profile)
        try:
            observation = desync.observe(scenario, self.host, self.client, perform_action=not rig.mutation_active(desync.SKIP_ACTION_MUTATION))
        finally:
            restore_network()
        report = desync.describe(observation, BUILD, EXPECTED_HASH, self.game_version, LAUNCH_ID, run.repetition, run.profile.as_dict(), GAMES.proxy.seed)
        text = desync.format_report(report)
        print("\n" + text)
        desync.save_report(report, REPORT_DIRECTORY)
        self.assertEqual(report["verdict"], desync.VERDICT_PERSISTED, text)
    method.__name__ = run.name
    method.__doc__ = scenario.description
    return method


def series_method(run):
    scenario = run.scenario

    def method(self):
        prepare_run(self, run.profile)
        try:
            observation = desync.observe_series(scenario, self.host, self.client, perform_action=not rig.mutation_active(desync.SKIP_ACTION_MUTATION))
        finally:
            restore_network()
        host_counts = desync.host_log_counts(GAMES.log_text("host"))
        report = desync.describe_series(observation, BUILD, EXPECTED_HASH, self.game_version, run.profile.delay_ms, run.profile.jitter_ms, host_counts,
                                        LAUNCH_ID, run.repetition, run.profile.as_dict(), GAMES.proxy.seed)
        text = desync.format_series_report(report)
        print("\n" + text)
        desync.save_series_report(report, REPORT_DIRECTORY)
        self.assertEqual(report["verdict"], desync.VERDICT_PERSISTED, text)
    method.__name__ = run.name
    method.__doc__ = scenario.description
    return method


class DesyncMixin:
    @classmethod
    def setUpClass(cls):
        if not PAIR_ENABLED or GAMES is None:
            raise unittest.SkipTest(SKIP_REASON)
        if EXPECTED_HASH == desync.UNKNOWN_HASH:
            raise unittest.SkipTest("no DLL found for build %s (set CU_FLAVOUR_ZIP or CU_UPSTREAM_STAGE)" % BUILD)
        try:
            cls.host, cls.client = GAMES.start([], [], together=desync.together_choice(BUILD), client_extra=cls.client_extra, host_extra=cls.host_extra, delay_ms=0.0)
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


GROUP_CLIENT_ARGUMENTS = {"default": [], "mixed-characters": mp_arguments(CORPSE_FLAGS), "hand-mining": ["--mp-verbose"]}
GROUP_HOST_ARGUMENTS = {"default": [], "mixed-characters": [], "hand-mining": ["--mp-verbose"]}


def build_classes():
    classes = []
    groups = sorted({scenario.group for scenario in SCENARIOS + SERIES_SCENARIOS})
    for group in groups:
        if ONLY_GROUP and group != ONLY_GROUP:
            continue
        members = {"client_extra": GROUP_CLIENT_ARGUMENTS[group], "host_extra": GROUP_HOST_ARGUMENTS[group]}
        for run in desync.expand_runs([scenario for scenario in SCENARIOS if scenario.group == group], PROFILES, REPEAT):
            members[run.name] = scenario_method(run)
        for run in desync.expand_runs([scenario for scenario in SERIES_SCENARIOS if scenario.group == group], PROFILES, REPEAT):
            members[run.name] = series_method(run)
        name = "Desync_%s_%s" % (desync.class_suffix(BUILD, EXPECTED_HASH), group.replace("-", "_"))
        classes.append(type(name, (DesyncMixin, unittest.TestCase), members))
    return classes


for generated in build_classes():
    globals()[generated.__name__] = generated
del generated


if __name__ == "__main__":
    unittest.main()
