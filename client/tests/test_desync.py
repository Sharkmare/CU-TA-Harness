import os
import time
import unittest

from casualtieslink import desync, diagblock, launchplan
from casualtieslink.instances import ScenarioGames, diag_stage2_directory, diag_stage3_directory, diag_stage_directory, flavour_zip, stage_directory
from casualtieslink.launcher import mp_arguments

from . import rig
from .desync_scenarios import CLIENT_BODY_NAME, CORPSE_FLAGS, SCENARIOS, SERIES_SCENARIOS, body_handle_by_name, ready_up, reset_between_scenarios
from .test_pair import PAIR_ENABLED, SKIP_REASON, wait_for_bodies

STATE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".state")
REPORT_DIRECTORY = os.path.join(STATE_ROOT, "desync_reports")
WORLD_WAIT_SECONDS = 150.0
SETTLE_SECONDS = 10.0
TOGETHER_DLL_RELATIVE = os.path.join("BepInEx", "plugins", "Together", "CasualtiesMP.dll")

def expected_hash(build):
    if build == desync.STAGE_BUILD:
        return desync.stage_dll_hash(stage_directory())
    if build == desync.DIAG_BUILD:
        return desync.stage_dll_hash(diag_stage_directory())
    if build == desync.DIAG2_BUILD:
        return desync.stage_dll_hash(diag_stage2_directory())
    if build == desync.DIAG3_BUILD:
        return desync.stage_dll_hash(diag_stage3_directory())
    return desync.flavour_dll_hash(flavour_zip(), build)


BUILD = desync.parse_build(os.environ.get(desync.BUILD_ENVIRONMENT_VARIABLE))
EXPECTED_HASH = expected_hash(BUILD)
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


def games_answer(case):
    try:
        return {"host": case.host.state()["state"], "client": case.client.state()["state"]}
    except Exception as exception:
        return {"error": str(exception)}


def body_identity(case):
    found = {}
    for label, game in (("host", case.host), ("client", case.client)):
        try:
            handle = body_handle_by_name(game, CLIENT_BODY_NAME)
            found[label] = {"charType": game.get(handle, "charType", depth=0), "STR": game.get(handle, "skills.STR", depth=0)}
        except Exception as exception:
            found[label] = {"error": str(exception)}
    return found


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
        log_marks = {which: len(GAMES.log_text(which).splitlines()) for which in ("host", "client")}
        proxy_mark = GAMES.proxy.mark()
        try:
            observation = desync.observe_series(scenario, self.host, self.client, perform_action=not rig.mutation_active(desync.SKIP_ACTION_MUTATION))
        finally:
            restore_network()
        run_logs = {which: "\n".join(GAMES.log_text(which).splitlines()[log_marks[which]:]) for which in ("host", "client")}
        proxy_observed = GAMES.proxy.delay_stats(proxy_mark)
        host_counts = desync.host_log_counts(run_logs["host"])
        report = desync.describe_series(observation, BUILD, EXPECTED_HASH, self.game_version, run.profile.delay_ms, run.profile.jitter_ms, host_counts,
                                        LAUNCH_ID, run.repetition, run.profile.as_dict(), GAMES.proxy.seed)
        report["proxyObserved"] = proxy_observed
        report["gamesAnswerAfterRun"] = games_answer(self)
        report["clientBody"] = body_identity(self)
        report["transpilerLines"] = {which: desync.transpiler_lines(GAMES.log_text(which)) for which in ("host", "client")}
        if BUILD in desync.DIAG_BUILDS:
            report["diagBlock"] = diagblock.summarise_run(run_logs["client"], run_logs["host"], observation.hit_times, observation.context.get("swingLog"))
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
            cls.host, cls.client = GAMES.start([], [], together=desync.together_choice(BUILD), client_extra=cls.client_extra, host_extra=cls.host_extra, delay_ms=0.0, probe=cls.probe)
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


GROUP_CLIENT_ARGUMENTS = {"default": [], "mixed-characters": mp_arguments(CORPSE_FLAGS), "hand-mining": ["--mp-verbose"],
                          "mixed-hand-mining": mp_arguments(CORPSE_FLAGS) + ["--mp-verbose"]}
GROUP_HOST_ARGUMENTS = {"default": [], "mixed-characters": [], "hand-mining": ["--mp-verbose"], "mixed-hand-mining": ["--mp-verbose"]}
PROBE_GROUPS = ("hand-mining", "mixed-hand-mining")


def build_classes():
    classes = []
    groups = sorted({scenario.group for scenario in SCENARIOS + SERIES_SCENARIOS})
    for group in groups:
        if ONLY_GROUP and group != ONLY_GROUP:
            continue
        members = {"client_extra": GROUP_CLIENT_ARGUMENTS[group], "host_extra": GROUP_HOST_ARGUMENTS[group], "probe": group in PROBE_GROUPS}
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
