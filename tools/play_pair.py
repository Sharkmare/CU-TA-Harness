"""Launch a host and a client harness copy for a person to play, with the host standing still.

Usage:
  python tools/play_pair.py --build perf-chunksleep-c201ea8 --host-character 1 --client-character 2
Stop it by creating the stop file (default .state/play_pair.stop) or by closing either game window; the copies are then stopped, the profile restored and the lock released.
Characters: 0 Experiment, 1 Milky, 2 Dune.
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPOSITORY_ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "client"))
sys.path.insert(0, HERE)

import chunksleep_ab
import hookbench

DEFAULT_STOP_FILE = os.path.join(REPOSITORY_ROOT, ".state", "play_pair.stop")
POLL_SECONDS = 2.0


def choose(character):
    return lambda game: game.set("static:PreRunScript", "characterSelected", character)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build", required=True)
    parser.add_argument("--host-character", type=int, default=1)
    parser.add_argument("--client-character", type=int, default=2)
    parser.add_argument("--stop-file", default=DEFAULT_STOP_FILE)
    parser.add_argument("--no-hold-host", action="store_true", help="leave the host free to move")
    arguments = parser.parse_args(argv)

    from casualtieslink.games import instances
    from casualtieslink.lock import GameLock
    from casualtieslink.scenarioengine import positioncontrol
    from scenarios.desync_scenarios import ready_up

    if os.path.exists(arguments.stop_file):
        os.remove(arguments.stop_file)
    lock = GameLock("play_pair.py").acquire()
    games = instances.ScenarioGames(os.path.join(REPOSITORY_ROOT, ".state"))
    try:
        games.prepare()
        games.configure_host([], arguments.build)
        hookbench.install_profiler(games.host_copy)  # only for its position probe, nothing is wrapped
        games.host = games.launch_host([], arguments.build)
        games.host.start(instances.START_TIMEOUT_SECONDS, allow_existing=True)
        games.configure_client([], arguments.build)
        hookbench.install_profiler(games.client_copy)
        games.client = games.launch_client([], arguments.build)
        games.client.start(instances.START_TIMEOUT_SECONDS, allow_existing=True)
        host, client = games.host.game, games.client.game
        choosers = {host: choose(arguments.host_character), client: choose(arguments.client_character)}
        if not ready_up([host, client], timeout=hookbench.WORLD_TIMEOUT_SECONDS, before_ready=choosers):
            raise RuntimeError("the games did not reach a world")
        for member in (host, client):
            member.wait_state("in-world", timeout=hookbench.WORLD_TIMEOUT_SECONDS)
        landed = chunksleep_ab.wait_landed(host, "host")
        if not arguments.no_hold_host:
            chunksleep_ab.hold(host, landed)
        print("READY host held at %s; the client window is yours. Stop: create %s" % (landed, arguments.stop_file), flush=True)
        while not os.path.exists(arguments.stop_file):
            if games.host.process.poll() is not None or games.client.process.poll() is not None:
                print("a game window closed; stopping", flush=True)
                break
            time.sleep(POLL_SECONDS)
    finally:
        try:
            for member in (games.host, games.client):
                if member is not None:
                    positioncontrol.release_quietly(member.game)
        except Exception:
            pass
        games.stop()
        games.dispose()
        lock.release()
        print("stopped", flush=True)


if __name__ == "__main__":
    main()
