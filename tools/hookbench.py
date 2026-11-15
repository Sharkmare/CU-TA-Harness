"""Hook benchmark runner: one build, one scripted scene, per hook and per frame timing from inside the game.

Usage:
  python tools/hookbench.py --build upstream-full-release-e9eb3ce --label base --repeat 5
  python tools/hookbench.py --build upstream-full-release-e9eb3ce --label notele --disable Telekinesis,Drag,HeldRagdoll --repeat 5
  python tools/hookbench.py --build upstream-full-release-e9eb3ce --label burn --burn Telekinesis.Loose:200 --repeat 5
  python tools/hookbench.py --compare reports/base reports/notele

Every launch runs two passes in the same world: CLEAN (frame probe only, nothing wrapped) and WRAPPED (every hook timed).
Frame time and CPU come from the clean pass, so the timing wrappers do not inflate them; per hook numbers come from the
wrapped pass. Stop all other games first: the harness copies share the profile folder and PlayerPrefs with the installed game.
"""
import argparse
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPOSITORY_ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "client"))
sys.path.insert(0, HERE)

import hookbench_logs
import hookbench_stats as stats

PROFILER_DLL = os.path.join(REPOSITORY_ROOT, "plugin-hookprofiler", "bin", "HookProfiler.dll")
PROFILER_FOLDER = "HookProfiler"
CONTROL_TARGET = "static:HookProfiler.Control"
DEFAULT_REPORT_DIRECTORY = os.path.join(REPOSITORY_ROOT, ".state", "hookbench")
SCENE_SEED = 20261114
SCENE_BODIES = 8
SCENE_CRATES = 24
SCENE_SECONDS = 30.0
SCENE_SPREAD = 6.0
SCENE_DROP_HEIGHT = 7.0
BODY_ID = "guard"
CRATE_ID = "medcrate"
CRYSTAL_ID = "crystalenemy"
CRYSTALS = 3
WARMUP_SECONDS = 5.0
WORLD_TIMEOUT_SECONDS = 150.0


def control_call(game, method, *strings):
    return game.call("invoke", target=CONTROL_TARGET, method=method, args=list(strings), types=["String"] * len(strings))


def unwrap(value):
    """The link may wrap a string result; the profiler always returns JSON text."""
    if isinstance(value, dict) and "result" in value:
        value = value["result"]
    return json.loads(value) if isinstance(value, str) else value


def install_profiler(copy):
    from casualtieslink.games import instances
    import shutil
    if not os.path.isfile(PROFILER_DLL):
        raise FileNotFoundError(PROFILER_DLL + " (build it: dotnet build plugin-hookprofiler -c Release)")
    folder = os.path.join(copy, instances.PLUGINS_RELATIVE, PROFILER_FOLDER)
    os.makedirs(folder, exist_ok=True)
    shutil.copy2(PROFILER_DLL, folder)


def spawn_scene(host, bodies, crates, seed, spread, drop_height):
    """Bodies and crates dropped in a column over the host, same seed and order every run. Returns the handles."""
    generator = random.Random(seed)
    anchor = host.player()["position"] if isinstance(host.player(), dict) and "position" in host.player() else {"x": 0.0, "y": 0.0}
    handles = []
    for kind, count in ((BODY_ID, bodies), (CRATE_ID, crates), (CRYSTAL_ID, CRYSTALS)):
        for _ in range(count):
            x = anchor["x"] + generator.uniform(-spread, spread)
            y = anchor["y"] + drop_height + generator.uniform(0, spread)
            try:
                rows = host.spawn(kind, x=x, y=y, pickup=False)
            except Exception as failure:
                print("spawn %s failed: %s" % (kind, str(failure)[:120]), flush=True)
                break
            handles.extend(row["object"] for row in rows)
    return handles


def churn(host, arguments, handles, seconds):
    """For the recording time: every few seconds drop a new burst of bodies and crates over the host and remove the oldest, so collisions keep happening. Returns the number of bursts."""
    if arguments.burst_seconds <= 0:
        time.sleep(seconds)
        return 0
    deadline = time.time() + seconds
    generation = 0
    kept = []
    while time.time() < deadline:
        generation += 1
        kept.append(spawn_scene(host, arguments.burst_bodies, arguments.burst_crates, arguments.seed + generation, SCENE_SPREAD, SCENE_DROP_HEIGHT))
        if len(kept) > arguments.burst_keep:
            destroy_scene(host, kept.pop(0))
        time.sleep(min(arguments.burst_seconds, max(0.0, deadline - time.time())))
    for burst in kept:
        handles.extend(burst)
    return generation


def start_walking(host):
    try:
        host.hold(key="D")
        return "holding D"
    except Exception as failure:
        return "walking failed: %s" % str(failure)[:100]


def stop_walking(host, state):
    if state.startswith("holding"):
        try:
            host.release(key="D")
        except Exception:
            pass


def destroy_scene(host, handles):
    for handle in handles:
        try:
            host.call("invoke", target="static:UnityEngine.Object", method="Destroy", args=["id:%d" % handle["id"]], types=["Object"])
        except Exception:
            pass


def one_pass(host, label, wrapped, arguments, seconds=None, client=None):
    """Record one pass on the host and, when a client game is given, on the client at the same time."""
    seconds = seconds or arguments.seconds
    if wrapped:
        control_call(host, "Wrap", "CasualtiesMP", arguments.burn or "")
    handles = spawn_scene(host, arguments.bodies, arguments.crates, arguments.seed, SCENE_SPREAD, SCENE_DROP_HEIGHT)
    time.sleep(WARMUP_SECONDS)
    walking = start_walking(host)
    control_call(host, "Begin", label)
    if client is not None:
        control_call(client, "Begin", label)
    bursts = churn(host, arguments, handles, seconds)
    report = unwrap(control_call(host, "End"))
    if client is not None:
        report["client"] = unwrap(control_call(client, "End"))
    report["bursts"] = bursts
    report["walking"] = walking
    stop_walking(host, walking)
    destroy_scene(host, handles)
    report["sceneObjects"] = len(handles)
    return report


def place_client_away(host, client, chunks):
    """Hold the client `chunks` chunks to the left of the host, so neither is in the other's 3x3, and wait until it has arrived. The host walks right during recording."""
    import chunksleep_ab
    start = chunksleep_ab.wait_landed(host, "host")
    chunksleep_ab.wait_landed(client, "client")
    size = hookbench_chunk_size(host, start)
    target = {"x": start["x"] - chunks * size, "y": start["y"]}
    chunksleep_ab.hold(client, target)
    return {"hostStart": start, "chunkSize": size, "clientTarget": target}


def hookbench_chunk_size(host, start):
    return unwrap(host.call("invoke", target="static:HookProfiler.SleepProbe", method="ChunkKeyAt", args=[str(start["x"]), str(start["y"])], types=["String", "String"]))["chunkSize"]


def run_launch(arguments, index):
    from casualtieslink.games import instances
    from casualtieslink.lock import GameLock
    from scenarios.desync_scenarios import ready_up
    lock = GameLock("hookbench.py").acquire()
    games = instances.ScenarioGames(os.path.join(REPOSITORY_ROOT, ".state"))
    record = {"build": arguments.build, "label": arguments.label, "launch": index, "mode": arguments.mode, "disable": arguments.disable, "burn": arguments.burn}
    try:
        games.prepare()
        games.configure_host([], arguments.build)
        install_profiler(games.host_copy)
        if arguments.mode == "solo":
            from casualtieslink.launcher import GameProcess
            games.host = GameProcess(instances.HOST_PORT, [], directory=games.host_copy, manage_save=False,
                                     window_args=["-screen-fullscreen", "0", "-screen-width", "640", "-screen-height", "360"])
        else:
            games.host = games.launch_host([], arguments.build)
        games.host.start(instances.START_TIMEOUT_SECONDS, allow_existing=True)
        gamelist = [games.host.game]
        if arguments.mode == "solo":
            try:
                games.host.game.start_run(character=arguments.character)
            except Exception as failure:
                print("start_run: %s; waiting for the world" % str(failure)[:120], flush=True)
            games.host.game.wait_state("in-world", timeout=WORLD_TIMEOUT_SECONDS)
            gamelist = []
        if arguments.mode == "pair":
            games.configure_client([], arguments.build)
            install_profiler(games.client_copy)
            games.client = games.launch_client([], arguments.build)
            games.client.start(instances.START_TIMEOUT_SECONDS, allow_existing=True)
            gamelist.append(games.client.game)
        if gamelist and not ready_up(gamelist, timeout=WORLD_TIMEOUT_SECONDS):
            raise RuntimeError("the games did not reach a world")
        for member in (games.host, games.client):
            if member is not None:
                member.game.wait_state("in-world", timeout=WORLD_TIMEOUT_SECONDS)
        host = games.host.game
        client = games.client.game if arguments.mode == "pair" else None
        if client is not None and arguments.client_away_chunks > 0:
            record["clientPlacement"] = place_client_away(host, client, arguments.client_away_chunks)
        record["setup"] = unwrap(control_call(host, "Setup", arguments.disable or "", "1"))
        if client is not None:
            record["clientSetup"] = unwrap(control_call(client, "Setup", arguments.disable or "", "1"))
        record["inventory"] = unwrap(control_call(host, "Inventory", "CasualtiesMP"))
        clean = None if arguments.hooked_only else one_pass(host, "clean", False, arguments)
        control_call(host, "Wrap", "CasualtiesMP", arguments.burn or "")
        if client is not None:
            control_call(client, "Wrap", "CasualtiesMP", arguments.burn or "")
        if arguments.granular_types:
            record["granular"] = unwrap(control_call(host, "WrapTypes", "CasualtiesMP", arguments.granular_types))
            if client is not None:
                record["clientGranular"] = unwrap(control_call(client, "WrapTypes", "CasualtiesMP", arguments.granular_types))
        wrapped = one_pass(host, "wrapped", True, arguments, client=client)
        record["clean"], record["wrapped"] = clean, wrapped
        if arguments.second_pass_seconds > 0:
            record["wrapped2"] = one_pass(host, "wrapped2", True, arguments, arguments.second_pass_seconds, client=client)
        record["install"] = json.loads(json.dumps(unwrap(control_call(host, "Wrap", "CasualtiesMP", ""))))
        return record
    finally:
        games.stop()
        record["keptLogs"] = hookbench_logs.keep_logs({"host": games.host_copy, "client": games.client_copy if arguments.mode == "pair" else None}, os.path.join(arguments.out, arguments.label, "logs"), "%s_%02d" % (arguments.label, index))
        print("kept logs:", record["keptLogs"], flush=True)
        games.dispose()
        lock.release()


def save(record, directory, label, index):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "%s_%02d.json" % (label, index))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(record, handle)
    return path


def load_records(directory):
    records = []
    for name in sorted(os.listdir(directory)):
        if name.endswith(".json"):
            with open(os.path.join(directory, name), encoding="utf-8") as handle:
                records.append(json.load(handle))
    return records


def compare_directories(baseline_directory, candidate_directory):
    baseline, candidate = load_records(baseline_directory), load_records(candidate_directory)
    result = {
        "baselineNoise": stats.noise_floor([record["clean"] for record in baseline]),
        "candidateNoise": stats.noise_floor([record["clean"] for record in candidate]),
        "frameAndCpu": stats.compare_reports([record["clean"] for record in baseline], [record["clean"] for record in candidate]),
        "baselineHooks": stats.hook_table([record["wrapped"] for record in baseline])[:30],
        "candidateHooks": stats.hook_table([record["wrapped"] for record in candidate])[:30],
    }
    print(json.dumps(result, indent=1))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build")
    parser.add_argument("--label", default="run")
    parser.add_argument("--mode", choices=("pair", "host", "solo"), default="pair")
    parser.add_argument("--hooked-only", action="store_true", help="skip the clean pass")
    parser.add_argument("--granular-types", default="", help="simple type names whose every method is timed as well")
    parser.add_argument("--second-pass-seconds", type=float, default=0.0, help="record a second pass of this length in the same launch")
    parser.add_argument("--burst-seconds", type=float, default=0.0, help="drop a new burst of bodies and crates this often during recording (0 = none)")
    parser.add_argument("--burst-bodies", type=int, default=3)
    parser.add_argument("--burst-crates", type=int, default=10)
    parser.add_argument("--burst-keep", type=int, default=6, help="bursts kept alive before the oldest is removed")
    parser.add_argument("--character", type=int, default=2)
    parser.add_argument("--client-away-chunks", type=int, default=0, help="pair mode: hold the client this many chunks left of the host and profile it too")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--disable", help="comma separated type name fragments whose Harmony patches are removed before measuring")
    parser.add_argument("--burn", help="fragment:microseconds,... deliberate extra cost in matching hooks (proves the benchmark can fail)")
    parser.add_argument("--bodies", type=int, default=SCENE_BODIES)
    parser.add_argument("--crates", type=int, default=SCENE_CRATES)
    parser.add_argument("--seconds", type=float, default=SCENE_SECONDS)
    parser.add_argument("--seed", type=int, default=SCENE_SEED)
    parser.add_argument("--out", default=DEFAULT_REPORT_DIRECTORY)
    parser.add_argument("--compare", nargs=2, metavar=("BASELINE_DIR", "CANDIDATE_DIR"))
    arguments = parser.parse_args(argv)
    if arguments.compare:
        compare_directories(*arguments.compare)
        return 0
    if not arguments.build:
        parser.error("--build is required unless --compare is used")
    directory = os.path.join(arguments.out, arguments.label)
    for index in range(arguments.repeat):
        print("launch %d of %d" % (index + 1, arguments.repeat), flush=True)
        print(save(run_launch(arguments, index), directory, arguments.label, index), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
