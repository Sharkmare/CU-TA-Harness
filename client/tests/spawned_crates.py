import time
import unittest

from casualtieslink.desync import Scenario

from . import desync_scenarios as base
from . import world_building as world

GROUP = world.GROUP
CRATE_ID = "medcrate"
SPAWN_OFFSET = 1.75
ANCHOR_TOLERANCE = 0.5
LOOKUP_RADIUS = 3.0
LISTED_TOGETHER_RADIUS = 0.5
FIND_TIMEOUT_SECONDS = 8.0
SETTLE_TIMEOUT_SECONDS = 6.0
SETTLED_STEP = 0.05
POLL_SECONDS = 0.5
VALID_RUNS_WANTED = 10
STOP_AFTER_FAILED_RUNS = 3
MIN_HEALTH = 100.0
STATE = {"anchor": None, "valid": 0, "failed": 0, "spawned": 0}


def reset_launch_state():
    STATE.update({"anchor": None, "valid": 0, "failed": 0, "spawned": 0})


def host_ids_near(host, position):
    return {row["object"]["id"] for row in base.rows_near(host, "BuildingEntity", position, radius=LOOKUP_RADIUS)}


def wait_for_new_crate(host, spot, known_ids):
    deadline = time.time() + FIND_TIMEOUT_SECONDS
    while time.time() < deadline:
        fresh = [row for row in base.rows_near(host, "BuildingEntity", spot, radius=LOOKUP_RADIUS) if row["object"]["id"] not in known_ids]
        if fresh:
            return min(fresh, key=lambda row: base.distance(row["position"], spot))
        time.sleep(POLL_SECONDS)
    raise AssertionError("the host lists no new %s within %.1f of (%.1f, %.1f) after %.0f s" % (CRATE_ID, LOOKUP_RADIUS, spot["x"], spot["y"], FIND_TIMEOUT_SECONDS))


def wait_until_settled(host, handle, fallback):
    deadline = time.time() + SETTLE_TIMEOUT_SECONDS
    previous = world.host_position(host, handle) or fallback
    while time.time() < deadline:
        time.sleep(POLL_SECONDS)
        current = world.host_position(host, handle) or previous
        if base.distance(current, previous) <= SETTLED_STEP:
            return current
        previous = current
    return previous


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
    settled = wait_until_settled(host, handle, row["position"])
    described = world.describe_candidate(host, dict(row, position=settled))
    if described is None:
        raise AssertionError("the spawned %s %s has no readable health" % (CRATE_ID, handle))
    client_row = wait_for_client_listing(client, settled)
    if client_row is None:
        raise AssertionError("the client does not list the spawned %s %s within %.1f of the host position (%.2f, %.2f) after %.0f s" % (
            CRATE_ID, handle, LISTED_TOGETHER_RADIUS, settled["x"], settled["y"], FIND_TIMEOUT_SECONDS))
    distance = base.distance(base.player_position(client), settled)
    if distance > world.MAX_START_DISTANCE:
        raise AssertionError("the client is %.2f from the spawned %s, beyond %.1f" % (distance, CRATE_ID, world.MAX_START_DISTANCE))
    if described["health"] < MIN_HEALTH:
        raise AssertionError("the spawned %s has health %.1f, below %.0f" % (CRATE_ID, described["health"], MIN_HEALTH))
    return dict(described, startHealth=described["health"], healthBefore=described["health"], distance=round(distance, 2), spawnOffset=SPAWN_OFFSET,
                spawnedAt=spot, clientHandle="id:%d" % client_row["object"]["id"], spawnNumber=STATE["spawned"], teleports=0, skippedPicks=[], timesUsedBefore=0)


def prepare(host, client):
    if STATE["valid"] >= VALID_RUNS_WANTED:
        raise unittest.SkipTest("%d valid runs already recorded in this launch" % STATE["valid"])
    if STATE["valid"] == 0 and STATE["failed"] >= STOP_AFTER_FAILED_RUNS:
        raise unittest.SkipTest("stopped: %d runs in a row ended without a landed first swing, the spawned %s looks unhittable or unreachable" % (STATE["failed"], CRATE_ID))
    base.empty_the_hand(client)
    try:
        target = spawn_crate(host, client)
    except AssertionError:
        STATE["failed"] += 1
        raise
    return {"position": target["position"], "name": None, "host": host, "hostHandle": target["handle"], "clientHandle": target["clientHandle"],
            "target": target, "measurements": []}


def act(client, context):
    try:
        world.act(client, context)
    finally:
        try:
            context["host"].set(context["hostHandle"], "health", 0)
        except Exception:
            pass


def check(context):
    issues = world.check_first_swing(context)
    if issues:
        STATE["failed"] += 1
    else:
        STATE["valid"] += 1
    return issues


SCENARIOS = [
    Scenario("spawned_crate_hit_by_client", "the host spawns a fresh medcrate 1.75 beside the client at the same offset every run and the client hits it bare handed five times, re-aiming each swing; the first runs decide whether a spawned crate is hittable at all",
             prepare, act, lambda game, context: 0, world.never_changes, group=GROUP, check=check),
]

base.SCENARIOS.extend(SCENARIOS)
