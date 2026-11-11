import collections
import json
import math
import os
import time
import unittest

from casualtieslink.desync import Scenario

from . import desync_scenarios as base
from . import world_building as world

GROUP = "hook-evidence"
CRATE_ID = "medcrate"
SPAWN_OFFSET = 1.0
ANCHOR_TOLERANCE = 0.5
LOOKUP_RADIUS = 3.0
LISTED_TOGETHER_RADIUS = 0.5
CLIENT_NEAR_RADIUS = 3.0
FIND_TIMEOUT_SECONDS = 8.0
SETTLE_TIMEOUT_SECONDS = 6.0
SETTLED_STEP = 0.05
MIN_SETTLE_SECONDS = 2.0
CHECKPOINT_SECONDS = (0.5, 2.0)
POLL_SECONDS = 0.5
VALID_RUNS_WANTED = 10
STOP_AFTER_FAILED_RUNS = 3
MIN_HEALTH = 100.0
ATTACK_DISTANCE = 4.5
BAND_LOW = 2.5
BAND_HIGH = 3.2
BAND_RESEAT_OFFSET = 2.0
BAND_WAIT_SECONDS = 0.3
BAND_TRIES = 4
CAST_SAMPLE_STEP = 0.25
PHYSICS_ENGINE_TYPE = world.PHYSICS_ENGINE_TYPE
STOP_AFTER_SETUP_FAILURES = 5
FAILURE_FILE = "spawned_crate_failures.json"
FAILURE_DIRECTORY = None
STATE = {"anchor": None, "valid": 0, "swing_failed": 0, "setup_failed": 0, "spawned": 0, "reasons": collections.Counter(), "attempts": []}


class SetupFailure(AssertionError):
    def __init__(self, category, message):
        super().__init__(message)
        self.category = category


def reset_launch_state():
    STATE.update({"anchor": None, "valid": 0, "swing_failed": 0, "setup_failed": 0, "spawned": 0, "reasons": collections.Counter(), "attempts": []})


def record_failure(category, message):
    STATE["reasons"][category] += 1
    STATE["attempts"].append({"category": category, "message": message[:300]})
    print("SETUP FAILURES grouped: %s" % dict(STATE["reasons"]))
    if FAILURE_DIRECTORY:
        os.makedirs(FAILURE_DIRECTORY, exist_ok=True)
        with open(os.path.join(FAILURE_DIRECTORY, FAILURE_FILE), "w", encoding="utf-8") as handle:
            json.dump({"valid": STATE["valid"], "setupFailed": STATE["setup_failed"], "firstSwingFailed": STATE["swing_failed"], "reasons": dict(STATE["reasons"]),
                       "attempts": STATE["attempts"]}, handle, indent=2)


def host_ids_near(host, position):
    return {row["object"]["id"] for row in base.rows_near(host, "BuildingEntity", position, radius=LOOKUP_RADIUS)}


def wait_for_new_crate(host, spot, known_ids):
    deadline = time.time() + FIND_TIMEOUT_SECONDS
    while time.time() < deadline:
        fresh = [row for row in base.rows_near(host, "BuildingEntity", spot, radius=LOOKUP_RADIUS) if row["object"]["id"] not in known_ids]
        if fresh:
            return min(fresh, key=lambda row: base.distance(row["position"], spot))
        time.sleep(POLL_SECONDS)
    raise SetupFailure("no-new-crate", "the host lists no new %s within %.1f of (%.1f, %.1f) after %.0f s" % (CRATE_ID, LOOKUP_RADIUS, spot["x"], spot["y"], FIND_TIMEOUT_SECONDS))


def client_crate_position(client, near):
    rows = base.rows_near(client, "BuildingEntity", near, radius=CLIENT_NEAR_RADIUS)
    if not rows:
        return None
    return min(rows, key=lambda row: base.distance(row["position"], near))["position"]


def trace_point(label, started, host, handle, client, fallback):
    position = world.host_position(host, handle) or fallback
    return {"label": label, "seconds": round(time.time() - started, 2), "host": position, "client": client_crate_position(client, position)}


def settle_and_trace(host, client, handle, fallback):
    started = time.time()
    trace = [trace_point("spawn", started, host, handle, client, fallback)]
    pending = list(CHECKPOINT_SECONDS)
    previous = trace[0]["host"]
    deadline = started + SETTLE_TIMEOUT_SECONDS
    while time.time() < deadline:
        time.sleep(POLL_SECONDS)
        elapsed = time.time() - started
        current = world.host_position(host, handle) or previous
        while pending and elapsed >= pending[0]:
            trace.append(trace_point("after %.1f s" % pending.pop(0), started, host, handle, client, current))
        if elapsed >= MIN_SETTLE_SECONDS and not pending and base.distance(current, previous) <= SETTLED_STEP:
            return current, trace
        previous = current
    return previous, trace


def wait_for_client_listing(client, position):
    deadline = time.time() + FIND_TIMEOUT_SECONDS
    while time.time() < deadline:
        rows = base.rows_near(client, "BuildingEntity", position, radius=LISTED_TOGETHER_RADIUS)
        if rows:
            return rows[0]
        time.sleep(POLL_SECONDS)
    return None


def hold_client_at_anchor(client):
    current = base.player_position(client)
    if STATE["anchor"] is None:
        STATE["anchor"] = current
        return current
    if base.distance(current, STATE["anchor"]) > ANCHOR_TOLERANCE:
        client.set("player", base.BODY_PATH, {"x": STATE["anchor"]["x"], "y": STATE["anchor"]["y"], "z": 0.0})
        time.sleep(POLL_SECONDS * 2)
    return STATE["anchor"]


def spawn_crate(host, client):
    anchor = hold_client_at_anchor(client)
    spot = {"x": anchor["x"] + SPAWN_OFFSET, "y": anchor["y"]}
    known_ids = host_ids_near(host, spot)
    host.call("spawn", id=CRATE_ID, x=spot["x"], y=spot["y"], pickup=False)
    STATE["spawned"] += 1
    row = wait_for_new_crate(host, spot, known_ids)
    handle = "id:%d" % row["object"]["id"]
    settled, trace = settle_and_trace(host, client, handle, row["position"])
    described = world.describe_candidate(host, dict(row, position=settled))
    if described is None:
        raise SetupFailure("crate-unreadable", "the spawned %s %s has no readable health" % (CRATE_ID, handle))
    if described["health"] < MIN_HEALTH:
        raise SetupFailure("low-health", "the spawned %s has health %.1f, below %.0f" % (CRATE_ID, described["health"], MIN_HEALTH))
    client_row = wait_for_client_listing(client, settled)
    if client_row is None:
        raise SetupFailure("client-does-not-list-crate", "the client does not list the spawned %s %s within %.1f of the host position (%.2f, %.2f) after %.0f s" % (
            CRATE_ID, handle, LISTED_TOGETHER_RADIUS, settled["x"], settled["y"], FIND_TIMEOUT_SECONDS))
    distance = base.distance(base.player_position(client), settled)
    return dict(described, position=settled, startHealth=described["health"], healthBefore=described["health"], distance=round(distance, 2), spawnOffset=SPAWN_OFFSET,
                spawnedAt=spot, clientHandle="id:%d" % client_row["object"]["id"], spawnNumber=STATE["spawned"], settleTrace=trace, skippedPicks=[], timesUsedBefore=0)


def ensure_band(host, client, handle, fallback):
    history = []
    crate = fallback
    for attempt in range(BAND_TRIES + 1):
        crate = world.host_position(host, handle) or crate
        distance = base.distance(base.player_position(client), crate)
        history.append(round(distance, 2))
        if BAND_LOW <= distance <= BAND_HIGH:
            return {"ok": True, "reseats": attempt, "distances": history}
        if attempt == BAND_TRIES:
            break
        offset = BAND_RESEAT_OFFSET if distance > BAND_HIGH else (BAND_LOW + BAND_HIGH) / 2
        client.set("player", base.BODY_PATH, {"x": crate["x"] - offset, "y": crate["y"], "z": 0.0})
        time.sleep(BAND_WAIT_SECONDS)
    return {"ok": False, "reseats": BAND_TRIES, "distances": history}


def optional_read(game, path):
    try:
        return game.get("player", path, depth=0)
    except Exception as failure:
        return {"error": str(failure)[:100]}


def point_of(value):
    if isinstance(value, dict) and "x" in value and "y" in value:
        return {"x": float(value["x"]), "y": float(value["y"])}
    return None


def names_in(value):
    if isinstance(value, dict):
        collider = value.get("collider") if isinstance(value.get("collider"), dict) else value
        transform = value.get("transform") if isinstance(value.get("transform"), dict) else {}
        name = collider.get("name") or transform.get("name") or value.get("name")
        tag = collider.get("tag") or transform.get("tag") or value.get("tag")
        return {"name": name, "tag": tag, "distance": value.get("distance")}
    return {"name": None if value is None else str(value)[:100], "tag": None, "distance": None}


def unit_direction(origin, aim):
    length = math.hypot(aim["x"] - origin["x"], aim["y"] - origin["y"])
    if length == 0:
        return {"x": 1.0, "y": 0.0}
    return {"x": (aim["x"] - origin["x"]) / length, "y": (aim["y"] - origin["y"]) / length}


def cast_by_raycast_all(client, origin, direction):
    result = client.call("invoke", target=PHYSICS_ENGINE_TYPE, method="RaycastAll",
                         args=[{"x": origin["x"], "y": origin["y"]}, direction, ATTACK_DISTANCE], types=["Vector2", "Vector2", "Single"])
    if not isinstance(result, list):
        raise ValueError("RaycastAll returned %s" % type(result).__name__)
    return [names_in(item) for item in result]


def cast_by_point_samples(client, origin, direction):
    hits = []
    seen = set()
    steps = int(ATTACK_DISTANCE / CAST_SAMPLE_STEP) + 1
    for step in range(steps):
        reach = step * CAST_SAMPLE_STEP
        point = {"x": origin["x"] + direction["x"] * reach, "y": origin["y"] + direction["y"] * reach}
        found = world.collider_at(client, point)
        if "error" in found:
            return None, found["error"]
        name = found.get("name")
        if name and name not in seen:
            seen.add(name)
            hits.append({"name": name, "tag": None, "distance": round(reach, 2)})
    return hits, None


def mimic_cast(client, origin, aim):
    if origin is None:
        return {"method": None, "error": "limb1 position unreadable", "hits": []}
    direction = unit_direction(origin, aim)
    try:
        hits = cast_by_raycast_all(client, origin, direction)
        method = "RaycastAll"
        error = None
    except Exception as failure:
        hits, samples_error = cast_by_point_samples(client, origin, direction)
        method = "OverlapPoint samples"
        error = "RaycastAll failed: %s%s" % (str(failure)[:90], "; samples failed: " + samples_error if samples_error else "")
    hits = hits or []
    crate_places = [index for index, hit in enumerate(hits) if CRATE_ID in str(hit.get("name") or "").lower()]
    return {"method": method, "error": error, "attackDistance": ATTACK_DISTANCE, "hits": hits[:12], "crateIndex": crate_places[0] if crate_places else None,
            "hitsBeforeCrate": hits[:crate_places[0]] if crate_places else hits[:12]}


def read_geometry(client, host, context, aim):
    handle = context["hostHandle"]
    crate_host = world.host_position(host, handle) or context["position"]
    player = base.player_position(client)
    limb = point_of(optional_read(client, "limbs[1].transform.position"))
    return {"clientPosition": player, "crateHostPosition": crate_host, "crateClientPosition": client_crate_position(client, crate_host),
            "distance": round(base.distance(player, crate_host), 3), "standing": optional_read(client, "standing"), "isRight": optional_read(client, "isRight"),
            "limb1Position": limb, "targetLookPos": point_of(optional_read(client, "targetLookPos")), "intendedAim": aim,
            "limb1Distance": None if limb is None else round(base.distance(limb, crate_host), 3), "cast": mimic_cast(client, limb, aim)}


def before_swing(client, context, index, aim):
    host = context["host"]
    band = ensure_band(host, client, context["hostHandle"], context["position"])
    if not band["ok"]:
        context["bandFailure"] = {"swing": index, "distances": band["distances"]}
        return None
    return {"band": band, "geometry": read_geometry(client, host, context, aim)}


def prepare(host, client):
    if STATE["valid"] >= VALID_RUNS_WANTED:
        raise unittest.SkipTest("%d valid runs already recorded in this launch" % STATE["valid"])
    if STATE["valid"] == 0 and STATE["swing_failed"] >= STOP_AFTER_FAILED_RUNS:
        raise unittest.SkipTest("stopped: %d runs without a landed first swing and no valid run, the spawned %s looks unhittable; reasons %s" % (
            STATE["swing_failed"], CRATE_ID, dict(STATE["reasons"])))
    if STATE["valid"] == 0 and STATE["setup_failed"] >= STOP_AFTER_SETUP_FAILURES:
        raise unittest.SkipTest("stopped: the first %d attempts all failed setup; reasons %s" % (STATE["setup_failed"], dict(STATE["reasons"])))
    base.empty_the_hand(client)
    try:
        target = spawn_crate(host, client)
    except SetupFailure as failure:
        STATE["setup_failed"] += 1
        record_failure(failure.category, str(failure))
        raise
    return {"position": target["position"], "name": None, "host": host, "hostHandle": target["handle"], "clientHandle": target["clientHandle"],
            "target": target, "measurements": []}


def act(client, context):
    try:
        world.act(client, context, before_swing=before_swing)
    finally:
        try:
            context["host"].set(context["hostHandle"], "health", 0)
        except Exception:
            pass


def check(context):
    failure = context.get("bandFailure")
    if failure:
        STATE["setup_failed"] += 1
        message = "INVALID: the client could not be brought into the %.1f to %.1f band before swing %d (distances tried %s)" % (BAND_LOW, BAND_HIGH, failure["swing"], failure["distances"])
        record_failure("distance-band-unreachable", message)
        return [message]
    issues = world.check_first_swing(context)
    if issues:
        STATE["swing_failed"] += 1
        record_failure("first-swing-no-damage", issues[0])
    else:
        STATE["valid"] += 1
    return issues


def preflight(fragments, attempts):
    selected = base.matching_scenario_names(fragments)
    if "spawned_crate_hit_by_client" not in selected:
        return []
    checks = [
        (BAND_LOW < BAND_HIGH, "the distance band %.1f to %.1f is empty" % (BAND_LOW, BAND_HIGH)),
        (BAND_HIGH < ATTACK_DISTANCE, "the band top %.1f is not inside the attack distance %.1f" % (BAND_HIGH, ATTACK_DISTANCE)),
        (0 < BAND_RESEAT_OFFSET <= BAND_HIGH, "the re-seat offset %.1f is outside 0 to the band top %.1f" % (BAND_RESEAT_OFFSET, BAND_HIGH)),
        (SPAWN_OFFSET <= BAND_HIGH, "the spawn offset %.1f is beyond the band top %.1f" % (SPAWN_OFFSET, BAND_HIGH)),
        (LISTED_TOGETHER_RADIUS <= LOOKUP_RADIUS, "the client listing radius %.1f exceeds the host lookup radius %.1f" % (LISTED_TOGETHER_RADIUS, LOOKUP_RADIUS)),
        (BAND_TRIES >= 1, "no band re-seat tries are allowed"),
        (BAND_WAIT_SECONDS > 0, "the wait after a re-seat is not positive"),
        (STOP_AFTER_SETUP_FAILURES >= 1 and STOP_AFTER_FAILED_RUNS >= 1, "an early stop is set to fire before any attempt"),
        (STOP_AFTER_SETUP_FAILURES < attempts, "the setup early stop %d is not below the %d planned attempts" % (STOP_AFTER_SETUP_FAILURES, attempts)),
        (STOP_AFTER_FAILED_RUNS < attempts, "the first-swing early stop %d is not below the %d planned attempts" % (STOP_AFTER_FAILED_RUNS, attempts)),
        (VALID_RUNS_WANTED <= attempts, "%d valid runs are wanted but only %d attempts are planned" % (VALID_RUNS_WANTED, attempts)),
        (world.SWINGS >= 1, "the swing count is below one"),
        (CHECKPOINT_SECONDS == tuple(sorted(CHECKPOINT_SECONDS)) and max(CHECKPOINT_SECONDS) <= MIN_SETTLE_SECONDS,
         "the settle checkpoints %s are not ordered inside the minimum settle time %.1f" % (CHECKPOINT_SECONDS, MIN_SETTLE_SECONDS)),
    ]
    return [message for holds, message in checks if not holds]


base.PREFLIGHTS.append(preflight)

SCENARIOS = [
    Scenario("spawned_crate_hit_by_client", "the host spawns a fresh medcrate beside the client at the same offset every run and the client hits it bare handed five times, re-aiming each swing, with the client held 2.5 to 3.2 from the crate before every swing",
             prepare, act, lambda game, context: 0, world.never_changes, group=GROUP, check=check),
]

base.SCENARIOS.extend(SCENARIOS)
