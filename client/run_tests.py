import argparse
import json
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import selection
from casualtieslink.lock import GameLock
from casualtieslink import Game, GameAlreadyRunning, GameProcess, mp_arguments
from casualtieslink.transport import default_port
from tests import rig

CONFIG_PATH = os.path.join(HERE, "test_groups.json")
STATE_PATH = os.path.join(HERE, selection.STATE_FILE_NAME)
DEFAULT_MP_FLAGS = ["disable"]
LOCK_PATH = os.path.join(HERE, "..", ".game.lock")


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--only", nargs="+")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--attach", action="store_true")
    parser.add_argument("--match", default=None, help="run only tests whose id contains this text")
    parser.add_argument("--budget-seconds", type=float, default=None, help="fail the run when it takes longer than this")
    parser.add_argument("--pair", action="store_true", help="run the two instance tests (starts a host and a client game)")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--mp", nargs="*", default=[], metavar="FLAG[=VALUE]", help="Together mod flags for the launched game (default: disable, because the mod blocks singleplayer)")
    parser.add_argument("--mutate", default=None, help="break a behaviour on purpose to prove a test can fail (corrupt-save)")
    return parser.parse_args(argv)


def matching(suite, fragment):
    selected = unittest.TestSuite()
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            selected.addTests(matching(item, fragment))
        elif fragment in item.id():
            selected.addTest(item)
    return selected


def run_group(group, fragment=None):
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for module in group["modules"]:
        suite.addTests(loader.loadTestsFromName(module))
    if fragment:
        suite = matching(suite, fragment)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return result


def add_result(totals, result):
    totals["run"] += result.testsRun
    totals["failures"] += len(result.failures) + len(result.unexpectedSuccesses)
    totals["errors"] += len(result.errors)
    totals["skipped"] += len(result.skipped)
    totals["expected_failures"] += len(result.expectedFailures)


def run_owned_game_groups(groups, config, state, fragment, totals):
    failed = []
    lock = GameLock("run_tests.py owned groups").acquire() if groups else None
    try:
        for group in groups:
            group_started = time.time()
            result = run_group(group, fragment)
            print("group %s: %d tests in %.0fs" % (group["id"], result.testsRun, time.time() - group_started))
            add_result(totals, result)
            if fragment:
                pass
            elif result.wasSuccessful() and result.testsRun > len(result.skipped):
                state[group["id"]] = selection.group_fingerprint(HERE, config, group)
            elif not result.wasSuccessful():
                failed.append(group["id"])
                state.pop(group["id"], None)
    finally:
        if lock:
            lock.release()
    return state, failed


def main(argv=None):
    program_started = time.time()
    arguments = parse_args(argv)
    with open(CONFIG_PATH, encoding="utf-8") as handle:
        config = json.load(handle)
    state = selection.load_state(STATE_PATH)
    chosen = selection.select(HERE, config, state, arguments.all, arguments.only)
    skipped = [g["id"] for g in config["groups"] if g not in chosen]
    print("selected: %s | skipped (unchanged since last pass): %s" % ([g["id"] for g in chosen], skipped))
    if arguments.list or not chosen:
        return 0
    if arguments.pair:
        os.environ[rig.PAIR_ENABLED_ENVIRONMENT_VARIABLE] = "1"
    if arguments.mutate:
        os.environ[rig.MUTATION_ENVIRONMENT_VARIABLE] = arguments.mutate

    port = arguments.port if arguments.port is not None else default_port()
    process = None
    totals = {"run": 0, "failures": 0, "errors": 0, "skipped": 0, "expected_failures": 0}
    state, owned_failures = run_owned_game_groups([g for g in chosen if g.get("owns_game")], config, state, arguments.match, totals)
    chosen = [g for g in chosen if not g.get("owns_game")]
    if any(g["needs_game"] for g in chosen):
        if arguments.attach:
            rig.bind(Game(port))
        else:
            lock = GameLock("run_tests.py shared session").acquire()
            process = GameProcess(port, mp_arguments(_flags(arguments.mp or DEFAULT_MP_FLAGS)))
            try:
                print("launched:", process.start()["version"], "pid", process.pid)
            except GameAlreadyRunning as exc:
                lock.release()
                print("not started:", exc)
                return 2
            rig.bind(process.game)

    failed_groups = list(owned_failures)
    try:
        for group in chosen:
            result = run_group(group, arguments.match)
            add_result(totals, result)
            if arguments.match:
                pass
            elif result.wasSuccessful() and result.testsRun > len(result.skipped):
                state[group["id"]] = selection.group_fingerprint(HERE, config, group)
            elif not result.wasSuccessful():
                failed_groups.append(group["id"])
                state.pop(group["id"], None)
    finally:
        if process is not None:
            process.close()
            lock.release()
        if not arguments.mutate and not arguments.match:
            selection.save_state(STATE_PATH, state)
    elapsed = time.time() - program_started
    print("ran %(run)d tests: %(failures)d failures, %(errors)d errors, %(skipped)d skipped, %(expected_failures)d expected failures in %(seconds).0fs; failed groups: %(failed)s" % dict(
        totals, seconds=elapsed, failed=failed_groups or "none"))
    over_budget = arguments.budget_seconds is not None and elapsed > arguments.budget_seconds
    if arguments.budget_seconds is not None:
        print("time budget %.0fs: used %.0fs, %s" % (arguments.budget_seconds, elapsed, "OVER" if over_budget else "within"))
    return 1 if failed_groups or over_budget else 0


def _flags(items):
    flags = {}
    for item in items:
        name, _, value = item.partition("=")
        flags[name] = value if value else True
    return flags


if __name__ == "__main__":
    sys.exit(main())
