import collections
import json
import os
import time
import unittest

from casualtieslink.desync import Scenario

from . import desync_scenarios as base
from . import world_building as world

GROUP = world.GROUP
CRATE_ID = "medcrate"
SPAWN_OFFSET = 1.0
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
BARE_HAND_REACH = 4.0
REACH_MARGIN = 0.4
START_GATE = BARE_HAND_REACH - REACH_MARGIN
RESEAT_DISTANCE = 2.0
RESEAT_TRIES = 4
RESEAT_OFFSET = 1.0
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


def reseat_client(host, client, handle, fallback):
    for attempt in range(1, RESEAT_TRIES + 1):
        crate = world.host_position(host, handle) or fallback
        client.set("player", base.BODY_PATH, {"x": crate["x"] - RESEAT_OFFSET, "y": crate["y"], "z": 0.0})
        time.sleep(POLL_SECONDS * 2)
        crate = world.host_position(host, handle) or crate
        reached = base.distance(base.player_position(client), crate)
        if reached <= RESEAT_DISTANCE:
            return attempt, crate, reached
    return RESEAT_TRIES, crate, reached


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
        raise SetupFailure("crate-unreadable", "the spawned %s %s has no readable health" % (CRATE_ID, handle))
    if described["health"] < MIN_HEALTH:
        raise SetupFailure("low-health", "the spawned %s has health %.1f, below %.0f" % (CRATE_ID, described["health"], MIN_HEALTH))
    distance_before = base.distance(base.player_position(client), settled)
    reseat_tries = 0
    reseat_reached = None
    if distance_before > START_GATE:
        reseat_tries, settled, reseat_reached = reseat_client(host, client, handle, settled)
        if reseat_reached > START_GATE:
            raise SetupFailure("client-too-far-after-reseat", "the client is %.2f from the spawned %s after %d re-seats (was %.2f, gate %.1f)" % (
                reseat_reached, CRATE_ID, reseat_tries, distance_before, START_GATE))
    client_row = wait_for_client_listing(client, settled)
    if client_row is None:
        raise SetupFailure("client-does-not-list-crate", "the client does not list the spawned %s %s within %.1f of the host position (%.2f, %.2f) after %.0f s" % (
            CRATE_ID, handle, LISTED_TOGETHER_RADIUS, settled["x"], settled["y"], FIND_TIMEOUT_SECONDS))
    distance = base.distance(base.player_position(client), settled)
    if distance > START_GATE:
        raise SetupFailure("client-too-far-after-reseat", "the client is %.2f from the spawned %s, beyond %.1f" % (distance, CRATE_ID, START_GATE))
    return dict(described, position=settled, startHealth=described["health"], healthBefore=described["health"], distance=round(distance, 2), spawnOffset=SPAWN_OFFSET,
                spawnedAt=spot, clientHandle="id:%d" % client_row["object"]["id"], spawnNumber=STATE["spawned"], teleports=reseat_tries, reseated=reseat_tries > 0,
                reseatTries=reseat_tries, reseatReached=None if reseat_reached is None else round(reseat_reached, 2), distanceBeforeReseat=round(distance_before, 2), skippedPicks=[], timesUsedBefore=0)


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
        world.act(client, context)
    finally:
        try:
            context["host"].set(context["hostHandle"], "health", 0)
        except Exception:
            pass


def check(context):
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
    problems = []
    checks = [
        (RESEAT_DISTANCE <= START_GATE, "the re-seat target %.1f is stricter than the start gate %.1f" % (RESEAT_DISTANCE, START_GATE)),
        (START_GATE < BARE_HAND_REACH, "the start gate %.1f is not inside the bare-hand reach %.1f" % (START_GATE, BARE_HAND_REACH)),
        (SPAWN_OFFSET <= START_GATE, "the spawn offset %.1f is beyond the start gate %.1f" % (SPAWN_OFFSET, START_GATE)),
        (LISTED_TOGETHER_RADIUS <= LOOKUP_RADIUS, "the client listing radius %.1f exceeds the host lookup radius %.1f" % (LISTED_TOGETHER_RADIUS, LOOKUP_RADIUS)),
        (RESEAT_TRIES >= 1, "no re-seat tries are allowed"),
        (STOP_AFTER_SETUP_FAILURES >= 1 and STOP_AFTER_FAILED_RUNS >= 1, "an early stop is set to fire before any attempt"),
        (STOP_AFTER_SETUP_FAILURES < attempts, "the setup early stop %d is not below the %d planned attempts" % (STOP_AFTER_SETUP_FAILURES, attempts)),
        (STOP_AFTER_FAILED_RUNS < attempts, "the first-swing early stop %d is not below the %d planned attempts" % (STOP_AFTER_FAILED_RUNS, attempts)),
        (VALID_RUNS_WANTED <= attempts, "%d valid runs are wanted but only %d attempts are planned" % (VALID_RUNS_WANTED, attempts)),
        (world.SWINGS >= 1, "the swing count is below one"),
    ]
    for holds, message in checks:
        if not holds:
            problems.append(message)
    return problems


base.PREFLIGHTS.append(preflight)

SCENARIOS = [
    Scenario("spawned_crate_hit_by_client", "the host spawns a fresh medcrate beside the client at the same offset every run and the client hits it bare handed five times, re-aiming each swing, from at most the start gate away",
             prepare, act, lambda game, context: 0, world.never_changes, group=GROUP, check=check),
]

base.SCENARIOS.extend(SCENARIOS)
