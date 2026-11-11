import argparse
import json
import os
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
SEARCH_ROOTS = [HERE, REPO_ROOT]
sys.path.insert(0, HERE)
sys.path.insert(0, REPO_ROOT)

import selection
from casualtieslink import desync, launchplan, Game, GameAlreadyRunning, GameProcess, mp_arguments
from casualtieslink.lock import GameLock
from casualtieslink.transport import default_port
from tests import rig

CONFIG_PATH = os.path.join(HERE, "test_groups.json")
STATE_PATH = os.path.join(HERE, selection.STATE_FILE_NAME)
DEFAULT_MP_FLAGS = ["disable"]
SLOW_UNIT_SECONDS = 5.0
SCENARIO_BUDGET_SECONDS_PER_RUN = 60.0
LAUNCH_STARTUP_SECONDS = 150.0


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Change aware test runner. Only tests whose own files or imports changed run.")
    parser.add_argument("--all", action="store_true", help="run every unit, changed or not")
    parser.add_argument("--only", nargs="+", help="run these groups")
    parser.add_argument("--offline", action="store_true", help="run only groups that never start the game")
    parser.add_argument("--list", action="store_true", help="show what would run and why, then stop")
    parser.add_argument("--failfast", action="store_true", help="stop a module at its first failing test")
    parser.add_argument("--attach", action="store_true", help="use a game that is already running with the link")
    parser.add_argument("--match", nargs="+", default=None, help="run only tests whose id contains any of these texts")
    parser.add_argument("--budget-seconds", type=float, default=None, help="fail the run when it takes longer than this")
    parser.add_argument("--pair", action="store_true", help="run the two game tests (starts a host and a client game)")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--mp", nargs="*", default=[], metavar="FLAG[=VALUE]", help="Together mod flags for the launched game (default: disable, because the mod blocks singleplayer)")
    parser.add_argument("--together", default=None, metavar="BUILD", help="Together build for the desync group: %s" % ", ".join(desync.KNOWN_BUILDS))
    parser.add_argument("--builds", nargs="+", default=None, metavar="BUILD", help="desync group: run these Together builds, one game launch per build and startup group")
    parser.add_argument("--net", nargs="+", default=None, metavar="DELAY:JITTER[:LOSS[:REORDER]]", help="desync group: network profiles in ms (direct = none), changed live inside a launch")
    parser.add_argument("--repeat", type=int, default=1, help="desync group: run every scenario this many times inside one launch")
    parser.add_argument("--launch-id", default=None, help="desync group: name of this launch in the reports")
    parser.add_argument("--group", default=None, help="desync group: only the scenarios of this startup group")
    parser.add_argument("--delay-ms", default=None, metavar="MS", help="desync group: put a UDP delay proxy of this one way delay between client and host (0 keeps the proxy with no delay)")
    parser.add_argument("--jitter-ms", default="0", metavar="MS", help="desync group: extra random delay from 0 up to this many ms")
    parser.add_argument("--mutate", default=None, help="break a behaviour on purpose to prove a test can fail (corrupt-save, no-dune)")
    return parser.parse_args(argv)


def matching(suite, fragments):
    selected = unittest.TestSuite()
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            selected.addTests(matching(item, fragments))
        elif any(fragment in item.id() for fragment in fragments):
            selected.addTest(item)
    return selected


def run_module(module, fragment, failfast):
    suite = unittest.TestLoader().loadTestsFromName(module)
    if fragment:
        suite = matching(suite, fragment)
    return unittest.TextTestRunner(verbosity=2, failfast=failfast).run(suite)


def run_command(unit):
    completed = subprocess.run(unit["command"], cwd=HERE)
    return completed.returncode == 0


def new_totals():
    return {"run": 0, "failures": 0, "errors": 0, "skipped": 0, "expected_failures": 0, "commands": 0}


def add_result(totals, result):
    totals["run"] += result.testsRun
    totals["failures"] += len(result.failures) + len(result.unexpectedSuccesses)
    totals["errors"] += len(result.errors)
    totals["skipped"] += len(result.skipped)
    totals["expected_failures"] += len(result.expectedFailures)


def run_entry(entry, state, totals, arguments, timings):
    failed = []
    for unit_entry in entry["units"]:
        unit = unit_entry["unit"]
        started = time.time()
        if isinstance(unit, dict):
            if arguments.match:
                continue
            passed = run_command(unit)
            totals["commands"] += 1
            totals["failures"] += 0 if passed else 1
            ran_something = True
        else:
            result = run_module(unit, arguments.match, arguments.failfast)
            add_result(totals, result)
            passed = result.wasSuccessful()
            ran_something = result.testsRun > len(result.skipped)
        timings.append((time.time() - started, selection.unit_id(unit)))
        if arguments.match:
            continue
        if passed and ran_something:
            selection.record_pass(state, unit_entry)
        elif not passed:
            selection.record_failure(state, unit_entry)
            failed.append(selection.unit_id(unit))
    return failed


def describe_selection(selected, config, offline):
    chosen = {entry["group"]["id"]: entry for entry in selected}
    for group in config["groups"]:
        entry = chosen.get(group["id"])
        if offline and (group.get("needs_game") or group.get("owns_game")):
            print("  %-16s needs the game, skipped" % group["id"])
            continue
        if entry is None:
            print("  %-16s up to date" % group["id"])
            continue
        for unit_entry in entry["units"]:
            reasons = unit_entry["reasons"]
            shown = ", ".join(reasons[:3]) + (" and %d more" % (len(reasons) - 3) if len(reasons) > 3 else "")
            print("  %-16s %s: %s" % (group["id"], selection.unit_id(unit_entry["unit"]), shown))


def main(argv=None):
    program_started = time.time()
    arguments = parse_args(argv)
    os.environ[desync.REPEAT_ENVIRONMENT_VARIABLE] = str(arguments.repeat)
    if arguments.launch_id:
        os.environ[desync.LAUNCH_ENVIRONMENT_VARIABLE] = arguments.launch_id
    if arguments.group:
        os.environ[desync.GROUP_ENVIRONMENT_VARIABLE] = arguments.group
    if arguments.net:
        os.environ[desync.NETS_ENVIRONMENT_VARIABLE] = ",".join(arguments.net)
    if arguments.builds:
        return run_launch_plan(arguments)
    if arguments.delay_ms is not None:
        os.environ[desync.DELAY_ENVIRONMENT_VARIABLE] = str(desync.parse_delay(arguments.delay_ms))
        os.environ[desync.JITTER_ENVIRONMENT_VARIABLE] = str(desync.parse_delay(arguments.jitter_ms) or 0.0)
    if arguments.together:
        os.environ[desync.BUILD_ENVIRONMENT_VARIABLE] = desync.parse_build(arguments.together)
    with open(CONFIG_PATH, encoding="utf-8") as handle:
        config = json.load(handle)
    state = selection.load_state(STATE_PATH)
    selected = selection.select_units(HERE, SEARCH_ROOTS, config, state, arguments.all, arguments.only, arguments.offline)
    print("selection:")
    describe_selection(selected, config, arguments.offline)
    if arguments.list or not selected:
        return 0
    if arguments.pair:
        os.environ[rig.PAIR_ENABLED_ENVIRONMENT_VARIABLE] = "1"
    if arguments.mutate:
        os.environ[rig.MUTATION_ENVIRONMENT_VARIABLE] = arguments.mutate

    totals = new_totals()
    timings = []
    failed = []
    owned = [entry for entry in selected if entry["group"].get("owns_game")]
    shared = [entry for entry in selected if not entry["group"].get("owns_game")]
    needs_game = any(entry["group"].get("needs_game") for entry in shared)
    process = None
    lock = None
    try:
        if owned:
            lock = GameLock("run_tests.py owned groups").acquire()
            try:
                for entry in owned:
                    failed += run_entry(entry, state, totals, arguments, timings)
            finally:
                lock.release()
                lock = None
        if needs_game:
            port = arguments.port if arguments.port is not None else default_port()
            if arguments.attach:
                rig.bind(Game(port))
            else:
                lock = GameLock("run_tests.py shared session").acquire()
                process = GameProcess(port, mp_arguments(flags_from(arguments.mp or DEFAULT_MP_FLAGS)))
                try:
                    print("launched:", process.start()["version"], "pid", process.pid)
                except GameAlreadyRunning as exc:
                    print("not started:", exc)
                    return 2
                rig.bind(process.game)
        for entry in shared:
            failed += run_entry(entry, state, totals, arguments, timings)
    finally:
        if process is not None:
            process.close()
        if lock is not None:
            lock.release()
        if not arguments.mutate and not arguments.match:
            selection.save_state(STATE_PATH, state)
    elapsed = time.time() - program_started
    print("ran %(run)d tests and %(commands)d commands: %(failures)d failures, %(errors)d errors, %(skipped)d skipped, %(expected_failures)d expected failures in %(seconds).1fs; failed: %(failed)s" % dict(
        totals, seconds=elapsed, failed=failed or "none"))
    slow = sorted((item for item in timings if item[0] >= SLOW_UNIT_SECONDS), reverse=True)
    for seconds, name in slow[:5]:
        print("  slow: %s %.1fs" % (name, seconds))
    over_budget = arguments.budget_seconds is not None and elapsed > arguments.budget_seconds
    if arguments.budget_seconds is not None:
        print("time budget %.0fs: used %.0fs, %s" % (arguments.budget_seconds, elapsed, "OVER" if over_budget else "within"))
    return 1 if failed or over_budget else 0


def run_launch_plan(arguments):
    from tests.desync_scenarios import counts_by_group
    builds = [desync.parse_build(build) for build in arguments.builds]
    profiles = launchplan.parse_profiles(arguments.net)
    counts = counts_by_group(arguments.match)
    groups = [arguments.group] if arguments.group else sorted(counts)
    launches = launchplan.plan_launches(builds, groups, profiles, arguments.repeat, arguments.match)
    for line in launchplan.describe_launches(launches, counts):
        print(line)
    print("%d launches; one per scenario run would be %d" % (len(launches), launchplan.launches_without_grouping(launches, counts)))
    from tests.desync_scenarios import preflight_problems
    problems = preflight_problems(arguments.match, arguments.repeat)
    for problem in problems:
        print("PREFLIGHT: " + problem)
    print("preflight: %s" % ("%d problems, no launch" % len(problems) if problems else "ok"))
    if arguments.list or not arguments.pair:
        return 1 if problems else 0
    if problems:
        return 2
    failed = False
    for launch in launches:
        started = time.time()
        runs = launchplan.runs_in_launch(launch, counts)
        budget = SCENARIO_BUDGET_SECONDS_PER_RUN * runs + LAUNCH_STARTUP_SECONDS
        command = [sys.executable, os.path.abspath(__file__), "--pair", "--only", "desync"] + launch.arguments() + ["--budget-seconds", str(budget)]
        try:
            code = subprocess.run(command, timeout=budget + LAUNCH_STARTUP_SECONDS).returncode
        except subprocess.TimeoutExpired:
            code = -1
        failed = failed or code != 0
        print("%s: exit %s in %.0fs" % (launch.identifier, code, time.time() - started), flush=True)
    return 1 if failed else 0


def flags_from(items):
    flags = {}
    for item in items:
        name, _, value = item.partition("=")
        flags[name] = value if value else True
    return flags


if __name__ == "__main__":
    sys.exit(main())
