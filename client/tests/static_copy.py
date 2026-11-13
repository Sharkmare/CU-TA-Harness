import time
import unittest

from casualtieslink.desync import Scenario

from . import desync_scenarios as base
from . import hook_scenarios as hooks
from . import spawned_crates as crates
from . import world_building as world

GROUP = "hook-evidence"
NAME = "staticcrate_hit_by_client"
FAR_COLUMNS = (45.0, -45.0, 50.0, -50.0, 55.0, -55.0, 60.0, -60.0)
MIN_FAR_DISTANCE = 40.0
FAR_ATTEMPTS = 4
POCKET_ROWS = 4
SPAWN_LIFT = 0.5
WORLD_EDGE_MARGIN = 5
ATTEMPTS_WANTED = 6
STOP_AFTER_SETUP_FAILURES = 3
APPROACH_POLL_SECONDS = 0.1
APPROACH_TIMEOUT_SECONDS = 3.0
RETURN_SETTLE_SECONDS = 1.0
STATE = {"valid": 0, "setup_failed": 0, "static_at_far": 0, "static_at_swing": 0}


def reset_launch_state():
    STATE.update({"valid": 0, "setup_failed": 0, "static_at_far": 0, "static_at_swing": 0})


def pocket_is_open(host, x, y):
    floor = base.block_value(host, {"x": x, "y": y - 1})
    body_cells = [base.block_value(host, {"x": x, "y": y + step}) for step in (0, 1, 2)]
    return floor > 0 and not any(body_cells)


def find_far_pocket(host, origin, half_width, farther_than=0.0):
    for column in FAR_COLUMNS:
        if abs(column) <= farther_than:
            continue
        x = origin["x"] + column
        if abs(x) > half_width - WORLD_EDGE_MARGIN:
            continue
        for rise in range(-POCKET_ROWS, POCKET_ROWS + 1):
            y = origin["y"] + rise
            if pocket_is_open(host, x, y):
                return {"x": x, "y": y + SPAWN_LIFT}
    return None


def fail_setup(category, message):
    STATE["setup_failed"] += 1
    crates.record_failure(category, message)
    raise crates.SetupFailure(category, message)


def prepare(host, client):
    if STATE["valid"] >= ATTEMPTS_WANTED:
        raise unittest.SkipTest("%d static-copy attempts already measured in this launch" % STATE["valid"])
    if STATE["valid"] == 0 and STATE["setup_failed"] >= STOP_AFTER_SETUP_FAILURES:
        raise unittest.SkipTest("stopped: the first %d static-copy attempts all failed setup; reasons %s" % (STATE["setup_failed"], dict(crates.STATE["reasons"])))
    base.empty_the_hand(client)
    anchor = crates.hold_client_at_anchor(client)
    half_width = int(host.get("world", "halfWidth", depth=0))
    states = []
    target = None
    far_distance = 0.0
    for attempt in range(1, FAR_ATTEMPTS + 1):
        pocket = find_far_pocket(host, anchor, half_width, farther_than=far_distance)
        if pocket is None:
            fail_setup("no-far-pocket", "no open pocket %s to %s tiles from the client at (%.1f, %.1f) in a world half width of %d, farther than %.0f; copy states so far %s" % (
                FAR_COLUMNS[0], FAR_COLUMNS[-1], anchor["x"], anchor["y"], half_width, far_distance, states))
        try:
            target = crates.spawn_object(host, client, crates.CRATE_ID, crates.MIN_HEALTH, spot=pocket)
        except crates.SetupFailure as failure:
            STATE["setup_failed"] += 1
            crates.record_failure("far-" + failure.category, str(failure))
            raise
        far_distance = base.distance(anchor, target["position"])
        client_flags = crates.crate_physics(client, target["clientHandle"])
        host_far = crates.crate_physics(host, target["handle"])
        states.append({"attempt": attempt, "distance": round(far_distance, 1), "clientBodyType": client_flags["bodyType"], "clientPhysicsActive": client_flags["physicsActive"],
                       "hostBodyType": host_far["bodyType"], "hostPhysicsActive": host_far["physicsActive"]})
        if far_distance < MIN_FAR_DISTANCE:
            crates_destroy(host, target["handle"])
            fail_setup("crate-not-far", "the spawned crate is only %.1f from the client, below %.0f" % (far_distance, MIN_FAR_DISTANCE))
        if client_flags["physicsActive"] is False:
            break
        crates_destroy(host, target["handle"])
    if client_flags["physicsActive"] is not False:
        fail_setup("client-copy-not-static-at-far", "the client copy is not Static at any tried distance, so no static-copy result is counted; copy state per distance %s" % states)
    STATE["static_at_far"] += 1
    target = dict(target, farDistance=round(far_distance, 1), hostFarState=host_far, clientFarState=client_flags, anchor=anchor, farAttempts=states)
    return {"position": target["position"], "name": None, "host": host, "hostHandle": target["handle"], "clientHandle": target["clientHandle"],
            "target": target, "measurements": [], "anchor": anchor}


def crates_destroy(host, handle):
    try:
        host.set(handle, "health", 0)
    except Exception:
        pass


def approach(host, client, context):
    handle = context["hostHandle"]
    crate = world.host_position(host, handle) or context["position"]
    client.set("player", base.BODY_PATH, {"x": crate["x"] - crates.BAND_TARGET, "y": crate["y"], "z": 0.0})
    started = time.time()
    timeline = []
    while time.time() - started < APPROACH_TIMEOUT_SECONDS:
        time.sleep(APPROACH_POLL_SECONDS)
        crate = world.host_position(host, handle) or crate
        distance = base.distance(base.player_position(client), crate)
        state = crates.crate_physics(client, context["clientHandle"])
        timeline.append({"seconds": round(time.time() - started, 2), "distance": round(distance, 2), "clientBodyType": state["bodyType"], "clientPhysicsActive": state["physicsActive"]})
        if crates.BAND_LOW <= distance <= crates.BAND_HIGH:
            break
    context["target"]["approach"] = timeline
    return timeline


def return_to_anchor(client, context):
    anchor = context.get("anchor")
    if anchor is None:
        return
    try:
        client.set("player", base.BODY_PATH, {"x": anchor["x"], "y": anchor["y"], "z": 0.0})
        time.sleep(RETURN_SETTLE_SECONDS)
    except Exception:
        pass


def act(client, context):
    try:
        approach(context["host"], client, context)
        world.act(client, context, before_swing=crates.before_swing)
        first = (context["measurements"] or [{}])[0]
        copy_at_swing = ((first.get("physics") or {}).get("client") or {}).get("physicsActive")
        context["target"]["clientStaticAtFirstSwing"] = copy_at_swing is False
        if copy_at_swing is False:
            STATE["static_at_swing"] += 1
    finally:
        crates_destroy(context["host"], context["hostHandle"])
        return_to_anchor(client, context)


def check(context):
    failure = context.get("bandFailure")
    if failure:
        message = "INVALID: the client could not be brought into the %.1f to %.1f band before swing %d (distances tried %s)" % (crates.BAND_LOW, crates.BAND_HIGH, failure["swing"], failure["distances"])
        STATE["setup_failed"] += 1
        crates.record_failure("distance-band-unreachable", message)
        return [message]
    entries = context.get("measurements") or []
    if not entries:
        return ["INVALID: no swing recorded"]
    STATE["valid"] += 1
    issues = []
    for entry in entries:
        if entry["hostDelta"] <= 0 or entry["clientDelta"] <= 0:
            copy = ((entry.get("physics") or {}).get("client") or {}).get("physicsActive")
            issues.append("swing %d: host %.2f, client %.2f (client copy physicsActive %s)" % (entry["swing"], entry["hostDelta"], entry["clientDelta"], copy))
    return issues


def preflight(fragments, attempts, builds=()):
    if NAME not in base.matching_scenario_names(fragments):
        return []
    checks = [
        (STOP_AFTER_SETUP_FAILURES < ATTEMPTS_WANTED, "the static-copy early stop %d is not below the %d attempts" % (STOP_AFTER_SETUP_FAILURES, ATTEMPTS_WANTED)),
        (ATTEMPTS_WANTED <= attempts, "%d static-copy attempts are wanted but only %d attempts are planned" % (ATTEMPTS_WANTED, attempts)),
        (min(abs(column) for column in FAR_COLUMNS) >= MIN_FAR_DISTANCE, "a far column is closer than %.0f tiles" % MIN_FAR_DISTANCE),
        (APPROACH_POLL_SECONDS < APPROACH_TIMEOUT_SECONDS, "the approach poll is not shorter than its timeout"),
    ]
    return [message for holds, message in checks if not holds]


base.PREFLIGHTS.append(preflight)

SCENARIOS = [
    Scenario(NAME, "the host spawns a medcrate more than 40 tiles from the client, the client's copy must be Static there; then the client is moved beside it in one step and swings at once, five swings, with the client copy's physics state timeline and per swing",
             prepare, act, lambda game, context: 0, hooks.never_changes, group=GROUP, check=check),
]

base.SCENARIOS.extend(SCENARIOS)
