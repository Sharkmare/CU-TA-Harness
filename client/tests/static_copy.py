import time
import unittest

from casualtieslink import positioncontrol, swinggate
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
OFFER_RADIUS = 60.0
STATIC_HEALTH_HIGH = 20000.0
OFFER_LIMIT = 15
OFFER_MATCH_DISTANCE = 0.5
POCKET_ROWS = 4
SPAWN_LIFT = 0.5
WORLD_EDGE_MARGIN = 5
ATTEMPTS_WANTED = 6
STOP_AFTER_SETUP_FAILURES = 3
APPROACH_POLL_SECONDS = 0.1
APPROACH_TIMEOUT_SECONDS = 3.0
RETURN_SETTLE_SECONDS = 1.0
STATE = {"valid": 0, "setup_failed": 0, "static_at_far": 0, "static_at_swing": 0, "adopted": 0, "offers": None, "not_counted": 0}


def reset_launch_state():
    STATE.update({"valid": 0, "setup_failed": 0, "static_at_far": 0, "static_at_swing": 0, "adopted": 0, "offers": None, "not_counted": 0})


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


def world_offer(host, client, anchor):
    """What the world offers when there is no far pocket: the buildings nearest the client, each with its health and the physics state of the host copy and of the client copy."""
    host_rows = [row for row in host.call("find", type="BuildingEntity", limit=world.HOST_LIST_LIMIT) if "position" in row and base.distance(row["position"], anchor) <= OFFER_RADIUS]
    host_rows.sort(key=lambda row: base.distance(row["position"], anchor))
    client_rows = [row for row in client.call("find", type="BuildingEntity", limit=world.HOST_LIST_LIMIT) if "position" in row]
    offers = []
    for row in host_rows[:OFFER_LIMIT]:
        handle = "id:%d" % row["object"]["id"]
        described = world.describe_candidate(host, row)
        match = min(client_rows, key=lambda candidate: base.distance(candidate["position"], row["position"]), default=None)
        matched = match is not None and base.distance(match["position"], row["position"]) <= OFFER_MATCH_DISTANCE
        client_handle = "id:%d" % match["object"]["id"] if matched else None
        offers.append({"kind": world.kind_of({"name": row["object"]["name"]}), "handle": handle, "clientHandle": client_handle, "position": row["position"],
                       "distance": round(base.distance(row["position"], anchor), 1), "health": None if described is None else described["health"],
                       "cantHit": None if described is None else described["cantHit"], "indestructible": None if described is None else described["indestructible"],
                       "animal": None if described is None else described["animal"], "host": crates.crate_physics(host, handle),
                       "client": None if client_handle is None else crates.crate_physics(client, client_handle), "described": described})
    return offers


def static_offer_usable(offer):
    """A standing building is not a spawned crate, so its health may be far above the crate range: only a floor applies, so that one swing's damage shows."""
    low, high = world.HEALTH_RANGE[0], STATIC_HEALTH_HIGH
    described = offer["described"]
    return (described is not None and offer["client"] is not None and offer["client"]["physicsActive"] is False and not described["animal"] and not described["cantHit"]
            and not described["indestructible"] and "corpse" not in described["name"].lower() and low <= described["health"] <= high)


def offer_summary(offers):
    return [{key: offer[key] for key in ("kind", "handle", "distance", "health", "cantHit", "indestructible", "host", "client")} for offer in offers]


def adopt_static_building(offer, anchor, states):
    """A static building that already stands near the seat is the swing target. It is not ours to destroy, so the context marks it adopted."""
    described = offer["described"]
    target = dict(described, clientHandle=offer["clientHandle"], farDistance=offer["distance"], hostFarState=offer["host"], clientFarState=offer["client"], anchor=anchor, farAttempts=states,
                  adopted=True, startHealth=described["health"], healthBefore=described["health"], distance=offer["distance"], spawnOffset=None, spawnedAt=None, spawnNumber=0,
                  settleTrace=[], skippedPicks=[], timesUsedBefore=0)
    return {"position": described["position"], "name": None, "host": None, "hostHandle": described["handle"], "clientHandle": offer["clientHandle"], "target": target, "measurements": [],
            "anchor": anchor, "seatHeightFromClient": True}


def try_adopt(host, client, anchor, states, why):
    """The far spawn did not give a Static copy: list what the world offers near the client and adopt a usable static building as the swing target when there is one."""
    offers = world_offer(host, client, anchor)
    usable_offers = [offer for offer in offers if static_offer_usable(offer)]
    STATE["offers"] = offer_summary(offers)
    print("\nSTATIC OFFER (%s): %d buildings within %.0f of the client, %d usable static ones: %s" % (why, len(offers), OFFER_RADIUS, len(usable_offers), STATE["offers"]))
    if not usable_offers:
        return None
    context = adopt_static_building(usable_offers[0], anchor, states)
    context["host"] = host
    STATE["adopted"] += 1
    return context


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
            context = try_adopt(host, client, anchor, states, "no far pocket after %d attempts" % len(states))
            if context is not None:
                return context
            fail_setup("no-far-pocket", "no open pocket %s to %s tiles from the client at (%.1f, %.1f) in a world half width of %d, farther than %.0f; copy states so far %s; buildings the world offers within %.0f (none usable as a static target) %s" % (
                FAR_COLUMNS[0], FAR_COLUMNS[-1], anchor["x"], anchor["y"], half_width, far_distance, states, OFFER_RADIUS, STATE["offers"]))
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
            context = try_adopt(host, client, anchor, states, "the spawned crate ended %.1f from the client" % far_distance)
            if context is not None:
                return context
            fail_setup("crate-not-far", "the spawned crate is only %.1f from the client, below %.0f" % (far_distance, MIN_FAR_DISTANCE))
        if client_flags["physicsActive"] is False:
            break
        crates_destroy(host, target["handle"])
    if client_flags["physicsActive"] is not False:
        context = try_adopt(host, client, anchor, states, "the far copy was never Static")
        if context is not None:
            return context
        fail_setup("client-copy-not-static-at-far", "the client copy is not Static at any tried distance, so no static-copy result is counted; copy state per distance %s" % states)
    STATE["static_at_far"] += 1
    target = dict(target, farDistance=round(far_distance, 1), hostFarState=host_far, clientFarState=client_flags, anchor=anchor, farAttempts=states)
    return {"position": target["position"], "name": None, "host": host, "hostHandle": target["handle"], "clientHandle": target["clientHandle"],
            "target": target, "measurements": [], "anchor": anchor, "seatHeightFromClient": True}


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


def seat_and_gate(client, context):
    """After the one-step move: hold the client where it stands, verify the seat by the holder and rb.position, then let the limbs settle. The swings are gated from here on."""
    host = context["host"]
    seat = base.player_position(client)
    paths = positioncontrol.discover_diagnostic_paths(client)
    context["clientPaths"] = paths
    context["settledSeat"] = seat
    verified = positioncontrol.seat_swinging_body(client, seat, paths=paths)
    context["target"]["seatVerification"] = {"ok": verified["ok"], "issues": verified["issues"], "linkReadDisagrees": verified["linkReadDisagrees"]}
    if not verified["ok"]:
        context["positionFailure"] = {"ok": False, "issues": ["the client seat did not verify after the move: %s" % "; ".join(verified["issues"][:2])]}
        return False
    gate = crates.make_gate(host, client, context, seat)
    settle = gate.settle(client)
    context["target"]["limbSettle"] = settle
    if not settle["ok"]:
        context["positionFailure"] = {"ok": False, "issues": ["the limbs did not settle within %.0f s after the move" % swinggate.SETTLE_TIMEOUT_SECONDS]}
        return False
    context["gate"] = gate
    return True


def act(client, context):
    try:
        positioncontrol.release_quietly(client)
        approach(context["host"], client, context)
        if seat_and_gate(client, context):
            world.act(client, context, before_swing=crates.before_swing)
        first = (context["measurements"] or [{}])[0]
        copy_at_swing = ((first.get("physics") or {}).get("client") or {}).get("physicsActive")
        context["target"]["clientStaticAtFirstSwing"] = copy_at_swing is False
        if copy_at_swing is False:
            STATE["static_at_swing"] += 1
    finally:
        if context.get("gate") is not None:
            context["gate"].release(client)
        if not context["target"].get("adopted"):
            crates_destroy(context["host"], context["hostHandle"])
        return_to_anchor(client, context)


def check(context):
    position_failure = context.get("positionFailure")
    if position_failure:
        STATE["setup_failed"] += 1
        message = "INVALID: the position preflight failed before the first swing: %s" % "; ".join(position_failure["issues"])
        crates.record_failure(crates.POSITION_FAILURE_CATEGORY, message)
        return [message]
    failure = context.get("bandFailure")
    if failure:
        message = "INVALID: the client could not be brought into the %.1f to %.1f band before swing %d (distances tried %s)" % (crates.BAND_LOW, crates.BAND_HIGH, failure["swing"], failure["distances"])
        STATE["setup_failed"] += 1
        crates.record_failure("distance-band-unreachable", message)
        return [message]
    verdict, reason = swinggate.run_verdict(context.get("measurements"), context.get("gateFailure"))
    if verdict == "invalid":
        STATE["setup_failed"] += 1
        message = "INVALID: " + reason
        crates.record_failure("swing-gate", message)
        return [message]
    if verdict == "fail":
        STATE["not_counted"] += 1
        message = "FAIL: " + reason
        crates.record_failure("static-copy-swing-missed", message)
        return [message]
    STATE["valid"] += 1
    return []


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
