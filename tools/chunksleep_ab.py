"""Chunk sleep correctness run: one build, host plus one client standing in different areas, the awake and asleep state of every watched object sampled on BOTH machines at fixed points.

Usage:
  python tools/chunksleep_ab.py --build full-release-c201ea8 --label base
  python tools/chunksleep_ab.py --build perf-chunksleep-c201ea8 --label fix
  python tools/chunksleep_ab.py --build perf-chunksleep-broken-c201ea8 --label broken
  python tools/chunksleep_ab.py --compare reports/base.json reports/fix.json reports/broken.json

The world seed is not controllable, so terrain differs between launches. What is identical across builds is the script and the labelled crates it spawns at fixed offsets from the host start.
Each sample also records, per machine, the invariant the mod promises: an object whose chunk is hot for that machine is awake. A build that wrongly skips a chunk breaks it.
"""
import argparse
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPOSITORY_ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "client"))
sys.path.insert(0, HERE)

import chunksleep_compare as compare
import hookbench
import hookbench_logs

PROBE_TARGET = "static:HookProfiler.SleepProbe"
CRATE_ID = "medcrate"
AREA_SPACING_CHUNKS = 6
CRATES_PER_GROUP = 10
CRATE_SPREAD = 6.0
CRATE_DROP = 3.0
SETTLE_SECONDS = 9.0
RESAMPLE_GAP_SECONDS = 3.0
KEEP_WINDOW_SECONDS = 10.0
KEEP_CHECK_SECONDS = 3.0
KEEP_EXPIRED_SECONDS = 16.0
HOLD_TOLERANCE = 0.5
LANDED_TIMEOUT_SECONDS = 120.0
LANDED_GAP_SECONDS = 2.0
LANDED_RADIUS = 0.3
TRACE_SECONDS = 4.0
HOLD_ARRIVE_SECONDS = 6.0
HOLD_ARRIVE_RADIUS = 2.0
CRATE_DROP_HEIGHT = 12.0
KEEP_PICK_RADIUS = 40.0
DEFAULT_OUT = os.path.join(REPOSITORY_ROOT, ".state", "chunksleep_ab")


def local_position(game):
    value = probe_call(game, "LocalPosition")
    return None if "error" in value else {"x": float(value["x"]), "y": float(value["y"])}


def probe_call(game, method, *strings):
    return hookbench.unwrap(game.call("invoke", target=PROBE_TARGET, method=method, args=list(strings), types=["String"] * len(strings)))


def compact(dump):
    """Rows as arrays to keep the saved report small: id, name, x, y, chunk, asleep, active, settled, hot."""
    rows = [[row["id"], row["name"], row["x"], row["y"], row["chunk"], row["asleep"], row["active"], row["settled"], row["hot"]] for row in dump["entries"]]
    return {"chunkSize": dump["chunkSize"], "unsettledTotal": dump["unsettledTotal"], "rows": rows}


def sample(machines, name, note=""):
    from casualtieslink.scenarioengine import positioncontrol
    taken = {"name": name, "note": note, "machines": {}}
    for machine, game in machines.items():
        entry = compact(probe_call(game, "Dump"))
        entry["player"] = local_position(game)
        taken["machines"][machine] = entry
    print("sample %-22s %s" % (name, {machine: len(entry["rows"]) for machine, entry in taken["machines"].items()}), flush=True)
    return taken


def trace_pulses(machines, seconds):
    """Poll the cheap pulse of every machine for `seconds` right after a move. Each row is the seconds since the move and, per machine, the frame, watched, awake and hot-but-off counts."""
    trace = []
    started = time.time()
    while time.time() - started < seconds:
        row = {"t": round(time.time() - started, 3)}
        for machine, game in machines.items():
            row[machine] = probe_call(game, "Pulse")
        trace.append(row)
    return trace


def settled_sample(machines, name, note=""):
    """Poll fast through the first seconds after a move (the latency of waking), wait for the objects to settle, then sample twice a few seconds apart; the second sample is the one compared, the first shows whether the state had settled."""
    trace = trace_pulses(machines, TRACE_SECONDS)
    time.sleep(max(0.0, SETTLE_SECONDS - TRACE_SECONDS))
    first = sample(machines, name + ".a", note)
    time.sleep(RESAMPLE_GAP_SECONDS)
    second = sample(machines, name, note)
    second["trace"] = trace
    second["stableSincePrevious"] = {machine: compare.awake_set(first["machines"][machine]) == compare.awake_set(second["machines"][machine]) for machine in machines}
    return second


def hold(game, point):
    """Teleport and hold the local body, then prove it arrived: the status text can fail while the hold itself works, so the position read decides."""
    from casualtieslink.scenarioengine import positioncontrol
    game.call("bodies")  # the hold driver finds its body through the link handle table, which only a listing fills
    try:
        positioncontrol.hold_at(game, point, HOLD_TOLERANCE)
    except Exception as failure:
        # the hold is stored and applied before the status text is built; the status lookup fails for a body the link never handed out as a handle.
        if "no live object" not in str(failure):
            raise
    deadline = time.time() + HOLD_ARRIVE_SECONDS
    while time.time() < deadline:
        position = local_position(game)
        if position and math.hypot(position["x"] - point["x"], position["y"] - point["y"]) <= HOLD_ARRIVE_RADIUS:
            return
        time.sleep(0.3)
    raise RuntimeError("the body did not reach %s; it is at %s" % (point, local_position(game)))


def spawn_group(host, label, center, groups):
    handles = []
    for index in range(CRATES_PER_GROUP):
        column = index % 5
        row = index // 5
        x = center["x"] - CRATE_SPREAD + column * (2 * CRATE_SPREAD / 4.0)
        y = center["y"] + CRATE_DROP_HEIGHT + row * 2.0
        rows = host.spawn(CRATE_ID, x=x, y=y, pickup=False)
        handles.extend(item["object"]["id"] for item in rows)
    groups[label] = {"center": center, "ids": handles}
    return handles


def wait_landed(game, name):
    """A new run starts with the body arriving in a pod; its position is not final until it stops moving. Two reads LANDED_GAP_SECONDS apart must agree."""
    deadline = time.time() + LANDED_TIMEOUT_SECONDS
    previous = None
    while time.time() < deadline:
        current = local_position(game)
        if current and previous and math.hypot(current["x"] - previous["x"], current["y"] - previous["y"]) < LANDED_RADIUS and (current["x"] != 0.0 or current["y"] != 0.0):
            return current
        previous = current
        time.sleep(LANDED_GAP_SECONDS)
    raise RuntimeError("%s body never settled; last position %s" % (name, previous))


def plan_areas(host_game):
    start = wait_landed(host_game, "host")
    chunk = hookbench.unwrap(probe_call(host_game, "ChunkKeyAt", str(start["x"]), str(start["y"])))
    size = chunk["chunkSize"]
    half_width = float(chunk["halfWidth"])
    spacing = AREA_SPACING_CHUNKS * size
    low = -half_width + 2 * size
    high = half_width - 2 * size
    host_x = min(max(start["x"], low + spacing), high - spacing) if high - low > 2 * spacing else start["x"]
    def chunk_centre(x):
        index = math.floor((x + half_width) / size)
        return index * size + size / 2.0 - half_width

    host_x = chunk_centre(host_x)
    areas = {"host": {"x": host_x, "y": start["y"]}, "client": {"x": host_x + spacing, "y": start["y"]}, "far": {"x": host_x - spacing, "y": start["y"]}}
    areas["farNext"] = {"x": areas["far"]["x"] - size, "y": start["y"]}
    areas["far2"] = {"x": areas["far"]["x"] - 2 * size, "y": start["y"]}
    return start, size, areas


def run_scenarios(machines, host_game, client_game, arguments):
    wait_landed(client_game, "client")
    start, size, areas = plan_areas(host_game)
    record = {"start": start, "chunkSize": size, "areas": areas, "samples": [], "groups": {}}
    hold(host_game, areas["host"])
    hold(client_game, areas["client"])
    time.sleep(3.0)
    for label in ("host", "client", "far", "farNext", "far2"):
        spawn_group(host_game, label, areas[label], record["groups"])
    record["samples"].append(settled_sample(machines, "idle_own_areas"))
    hold(client_game, areas["host"])
    record["samples"].append(settled_sample(machines, "client_in_host_area"))
    hold(client_game, areas["client"])
    record["samples"].append(settled_sample(machines, "client_back"))
    hold(host_game, areas["client"])
    record["samples"].append(settled_sample(machines, "host_in_client_area"))
    hold(host_game, areas["host"])
    record["samples"].append(settled_sample(machines, "host_back"))
    keeps = {}
    for machine, game in machines.items():
        keeps[machine] = probe_call(game, "ArmKeep", str(areas["far"]["x"]), str(areas["far"]["y"]), str(KEEP_PICK_RADIUS))
    record["keepArmed"] = keeps
    elapsed = 0.0
    record["keepTrace"] = trace_pulses(machines, KEEP_CHECK_SECONDS)
    elapsed = KEEP_CHECK_SECONDS
    for name, at in (("keep_active", KEEP_CHECK_SECONDS), ("keep_active.6s", 6.0), ("keep_active.9s", 9.0)):
        time.sleep(max(0.0, at - elapsed))
        elapsed = at
        record["samples"].append(sample(machines, name, "SimKeep armed on a far crate, window %.0fs" % KEEP_WINDOW_SECONDS))
    time.sleep(KEEP_EXPIRED_SECONDS - elapsed)
    record["samples"].append(sample(machines, "keep_expired"))
    time.sleep(RESAMPLE_GAP_SECONDS)
    record["samples"].append(sample(machines, "keep_expired.b"))
    return record


def run_launch(arguments):
    from casualtieslink.games import instances
    from casualtieslink.lock import GameLock
    from scenarios.desync_scenarios import ready_up
    lock = GameLock("chunksleep_ab.py").acquire()
    games = instances.ScenarioGames(os.path.join(REPOSITORY_ROOT, ".state"))
    record = {"build": arguments.build, "label": arguments.label}
    try:
        games.prepare()
        games.configure_host([], arguments.build)
        hookbench.install_profiler(games.host_copy)
        games.host = games.launch_host([], arguments.build)
        games.host.start(instances.START_TIMEOUT_SECONDS, allow_existing=True)
        games.configure_client([], arguments.build)
        hookbench.install_profiler(games.client_copy)
        games.client = games.launch_client([], arguments.build)
        games.client.start(instances.START_TIMEOUT_SECONDS, allow_existing=True)
        gamelist = [games.host.game, games.client.game]
        if not ready_up(gamelist, timeout=hookbench.WORLD_TIMEOUT_SECONDS):
            raise RuntimeError("the games did not reach a world")
        for member in (games.host, games.client):
            member.game.wait_state("in-world", timeout=hookbench.WORLD_TIMEOUT_SECONDS)
        time.sleep(5.0)
        machines = {"host": games.host.game, "client": games.client.game}
        record.update(run_scenarios(machines, games.host.game, games.client.game, arguments))
        return record
    finally:
        try:
            from casualtieslink.scenarioengine import positioncontrol
            for member in (games.host, games.client):
                if member is not None:
                    positioncontrol.release_quietly(member.game)
        except Exception:
            pass
        games.stop()
        logs = hookbench_logs.keep_logs({"host": games.host_copy, "client": games.client_copy}, os.path.join(arguments.out, arguments.label + "_logs"), arguments.label)
        record["keptLogs"] = logs
        print("kept logs:", logs, flush=True)
        games.dispose()
        lock.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build")
    parser.add_argument("--label", default="run")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--compare", nargs="+", metavar="REPORT", help="report files: the first is the baseline, the others are compared to it")
    arguments = parser.parse_args(argv)
    if arguments.compare:
        return compare.print_comparison(arguments.compare)
    if not arguments.build:
        parser.error("--build or --compare is required")
    os.makedirs(arguments.out, exist_ok=True)
    record = run_launch(arguments)
    path = os.path.join(arguments.out, arguments.label + ".json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(record, handle)
    print("saved", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
