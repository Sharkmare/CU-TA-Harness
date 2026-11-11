import collections
import re
import time
import unittest

from casualtieslink.desync import Scenario

from . import desync_scenarios as base
from . import evidence_scenarios as evidence
from . import hook_scenarios as hooks

GROUP = "hook-evidence"
HEALTH_RANGE = (100.0, 2500.0)
HOST_LIST_LIMIT = 400
MAX_START_DISTANCE = 3.0
MAX_TARGET_MOVE = 0.5
MOVE_OFFSET = 1.5
TELEPORT_ATTEMPTS = 4
TELEPORT_WAIT_SECONDS = 4.0
POLL_SECONDS = 0.25
SETTLE_SECONDS = 0.6
MAX_PICKS = 6
MIN_CANDIDATES = 4
VALID_RUNS_WANTED = 12
HEALTH_SYNC_SECONDS = 0.5
HEALTH_EPSILON = 0.01
SWINGS = 5
SYNCHRONIZER_TYPE = "static:ScavMPBuildingSynchronizer"
PHYSICS_ENGINE_TYPE = "static:UnityEngine.Physics2D"
KINEMATIC = "Kinematic"
USES = collections.Counter()
SKIPPED = set()
FIRST_POSITION = {}
PHYSICS_COUNTS = collections.Counter()
VALID_RUNS = [0]
SURVEY = {"candidates": None, "rows": 0}


def reset_launch_state():
    USES.clear()
    SKIPPED.clear()
    FIRST_POSITION.clear()
    PHYSICS_COUNTS.clear()
    VALID_RUNS[0] = 0
    SURVEY["candidates"] = None
    SURVEY["rows"] = 0


def optional_get(game, handle, path, nonpublic=False):
    try:
        return game.call("get", target=handle, path=path, depth=0, nonpublic=nonpublic)
    except Exception:
        return None


def physics_active(game, handle):
    try:
        return bool(game.call("invoke", target=SYNCHRONIZER_TYPE, method="BuildingHasActivePhysics", args=[handle], types=["BuildingEntity"]))
    except Exception:
        return None


def describe_candidate(host, row):
    handle = "id:%d" % row["object"]["id"]
    health = optional_get(host, handle, "health")
    if health is None:
        return None
    return {"handle": handle, "id": row["object"]["id"], "name": row["object"]["name"], "position": row["position"], "health": float(health),
            "cantHit": bool(optional_get(host, handle, "cantHit")), "indestructible": bool(optional_get(host, handle, "indestructible")),
            "animal": bool(optional_get(host, handle, "animal")),
            "rigidbodyType": optional_get(host, handle, "rb.bodyType", nonpublic=True), "layer": optional_get(host, handle, "gameObject.layer"),
            "physicsActive": physics_active(host, handle), "startHealth": float(health)}


def host_physics_candidates(host, anchor):
    rows = [row for row in host.call("find", type="BuildingEntity", limit=HOST_LIST_LIMIT) if "position" in row]
    rows.sort(key=lambda row: base.distance(row["position"], anchor))
    found = []
    for row in rows:
        if physics_active(host, "id:%d" % row["object"]["id"]) is not True:
            continue
        described = describe_candidate(host, row)
        if described is not None:
            found.append(described)
    return found, len(rows)


def kind_of(candidate):
    match = re.search(r"res: ([^)]+)\)", candidate["name"])
    return match.group(1) if match else candidate["name"][-24:]


def kinds_summary(candidates):
    counts = collections.Counter((kind_of(item), round(item["health"]), item["animal"], item["rigidbodyType"]) for item in candidates)
    return sorted(([kind, health, animal, body, count] for (kind, health, animal, body), count in counts.items()), key=lambda row: (-row[4], row[0]))


def usable(candidate, skipped=SKIPPED, health_range=HEALTH_RANGE):
    low, high = health_range
    return (candidate["physicsActive"] is True and not candidate["animal"] and candidate["rigidbodyType"] != KINEMATIC
            and "corpse" not in candidate["name"].lower() and not candidate["cantHit"] and not candidate["indestructible"]
            and low <= candidate["health"] <= high and candidate["id"] not in skipped)


def survey(host, anchor):
    if SURVEY["candidates"] is None:
        SURVEY["candidates"], SURVEY["rows"] = host_physics_candidates(host, anchor)
        print("\nSURVEY: %d buildings in the host list, %d physics-active, %d usable" % (
            SURVEY["rows"], len(SURVEY["candidates"]), len([item for item in SURVEY["candidates"] if usable(item, skipped=set())])))
        for row in kinds_summary(SURVEY["candidates"]):
            print("SURVEY kind %s health %s animal %s body %s count %d" % tuple(row))
    return SURVEY["candidates"]


def enough_candidates(candidates):
    usable_now = [item for item in candidates if usable(item, skipped=set())]
    if len(usable_now) < MIN_CANDIDATES:
        raise AssertionError("SURVEY: only %d usable physics-active, non-animal buildings with health %s (need %d); %d physics-active in the host list; kinds %s" % (
            len(usable_now), HEALTH_RANGE, MIN_CANDIDATES, len(candidates), kinds_summary(candidates)[:12]))
    return usable_now


def choose(candidates, anchor, skipped=SKIPPED, uses=USES):
    pool = [item for item in candidates if usable(item, skipped)]
    if not pool:
        return None
    return min(pool, key=lambda item: (uses[item["id"]], base.distance(item["position"], anchor)))


def host_position(host, handle):
    found = optional_get(host, handle, base.BODY_PATH)
    if isinstance(found, dict) and "x" in found:
        return {"x": float(found["x"]), "y": float(found["y"])}
    return None


def refresh(host, candidate):
    position = host_position(host, candidate["handle"])
    health = optional_get(host, candidate["handle"], "health")
    if position is None or health is None:
        return None
    return dict(candidate, position=position, health=float(health))


def bring_client_to(host, client, candidate):
    for attempt in range(1, TELEPORT_ATTEMPTS + 1):
        position = host_position(host, candidate["handle"]) or candidate["position"]
        client.set("player", base.BODY_PATH, {"x": position["x"] - MOVE_OFFSET, "y": position["y"], "z": 0.0})
        deadline = time.time() + TELEPORT_WAIT_SECONDS
        while time.time() < deadline:
            time.sleep(POLL_SECONDS)
            position = host_position(host, candidate["handle"]) or position
            if base.distance(base.player_position(client), position) > MAX_START_DISTANCE:
                continue
            rows = base.rows_near(client, "BuildingEntity", position, radius=0.5)
            if rows:
                return rows[0], attempt
    return None, TELEPORT_ATTEMPTS


def restore_host_health(host, fresh):
    start = fresh["startHealth"]
    if fresh["health"] >= start - HEALTH_EPSILON:
        return False, None
    host.set(fresh["handle"], "health", start)
    time.sleep(HEALTH_SYNC_SECONDS)
    after = optional_get(host, fresh["handle"], "health")
    if after is None or float(after) < start - HEALTH_EPSILON:
        return False, "%s: the host health stayed at %s after setting %s" % (kind_of(fresh), after, start)
    return True, None


def align_client_health(client, client_handle, start):
    seen = optional_get(client, client_handle, "health")
    if seen is not None and abs(float(seen) - start) <= HEALTH_EPSILON:
        return False, seen
    client.set(client_handle, "health", start)
    return True, seen


def try_setup(host, client, chosen):
    fresh = refresh(host, chosen)
    if fresh is None:
        return None, "%s could not be read" % kind_of(chosen)
    first_position = FIRST_POSITION.setdefault(chosen["id"], fresh["position"])
    if base.distance(fresh["position"], first_position) > MAX_TARGET_MOVE:
        SKIPPED.add(chosen["id"])
        return None, "%s was shoved from %s to %s since it was first picked, skipped for the rest of the launch" % (kind_of(chosen), first_position, fresh["position"])
    host_reset, failure = restore_host_health(host, fresh)
    if failure:
        return None, failure
    client_row, attempts = bring_client_to(host, client, fresh)
    if client_row is None:
        return None, "%s: the client never reached it within %.1f with it loaded after %d teleports (client at %s, building at %s)" % (
            kind_of(chosen), MAX_START_DISTANCE, attempts, base.player_position(client), host_position(host, fresh["handle"]))
    time.sleep(SETTLE_SECONDS)
    settled = host_position(host, fresh["handle"])
    if settled is None or base.distance(settled, fresh["position"]) > MAX_TARGET_MOVE:
        return None, "%s moved from %s to %s while the client came over" % (kind_of(chosen), fresh["position"], settled)
    distance = base.distance(base.player_position(client), settled)
    if distance > MAX_START_DISTANCE:
        return None, "%s: the client is %.2f away at the first swing" % (kind_of(chosen), distance)
    client_handle = "id:%d" % client_row["object"]["id"]
    client_reset, client_seen = align_client_health(client, client_handle, fresh["startHealth"])
    return dict(fresh, position=settled, distance=round(distance, 2), clientHandle=client_handle, teleports=attempts, health=fresh["startHealth"],
                hostHealthReset=host_reset, hostHealthBeforeReset=fresh["health"], clientHealthReset=client_reset, clientHealthBeforeReset=client_seen,
                timesUsedBefore=USES[chosen["id"]] - 1), None


def prepare(host, client):
    if VALID_RUNS[0] >= VALID_RUNS_WANTED:
        raise unittest.SkipTest("%d valid runs already recorded in this launch" % VALID_RUNS[0])
    base.empty_the_hand(client)
    anchor = base.player_position(client)
    candidates = survey(host, anchor)
    enough_candidates(candidates)
    skipped = []
    for _ in range(MAX_PICKS):
        chosen = choose(candidates, base.player_position(client))
        if chosen is None:
            break
        USES[chosen["id"]] += 1
        target, reason = try_setup(host, client, chosen)
        if target is None:
            skipped.append(reason)
            continue
        PHYSICS_COUNTS[True] += 1
        target = dict(target, healthBefore=target["startHealth"], skippedPicks=skipped, surveyCandidates=len(candidates), distinctTargets=len(USES))
        return {"position": target["position"], "name": None, "host": host, "hostHandle": target["handle"], "clientHandle": target["clientHandle"],
                "target": target, "measurements": []}
    raise AssertionError("no setup succeeded in %d picks: %s" % (MAX_PICKS, skipped))


def health_by_handle(game, handle):
    value = optional_get(game, handle, "health")
    return 0.0 if value is None else float(value)


def current_position(host, context):
    return host_position(host, context["hostHandle"]) or context["position"]


def collider_at(client, point):
    try:
        found = client.call("invoke", target=PHYSICS_ENGINE_TYPE, method="OverlapPoint", args=[{"x": point["x"], "y": point["y"]}], types=["Vector2"])
    except Exception as failure:
        return {"error": str(failure)[:120]}
    if isinstance(found, dict):
        return {"name": found.get("name") or str(found)[:120]}
    return {"name": None if found is None else str(found)[:120]}


def act(client, context, before_swing=None):
    host = context["host"]
    entries = []
    for index in range(1, SWINGS + 1):
        aim = current_position(host, context)
        extra = {}
        if before_swing is not None:
            extra = before_swing(client, context, index, aim)
            if extra is None:
                break
        marks = {which: len(evidence.read_log(which).splitlines()) for which in ("host", "client")}
        before = (health_by_handle(host, context["hostHandle"]), health_by_handle(client, context["clientHandle"]))
        probe = collider_at(client, aim)
        cooldown_before = float(client.get("player", "attackCooldown", depth=0))
        fired = hooks.fire_one_swing(client, aim)
        cooldown_after = float(client.get("player", "attackCooldown", depth=0))
        time.sleep(hooks.SETTLE_AFTER_SWING_SECONDS)
        moved_to = current_position(host, context)
        after = (health_by_handle(host, context["hostHandle"]), health_by_handle(client, context["clientHandle"]))
        lines = {which: evidence.new_lines(marks[which], evidence.read_log(which)) for which in ("host", "client")}
        entries.append({"swing": index, "fired": fired, "aim": aim, "host": [before[0], after[0]], "client": [before[1], after[1]],
                        "hostDelta": round(before[0] - after[0], 3), "clientDelta": round(before[1] - after[1], 3),
                        "cooldown": [round(cooldown_before, 3), round(cooldown_after, 3)], "colliderAtAim": probe, "displacement": round(base.distance(aim, moved_to), 3),
                        "clientDistance": round(base.distance(base.player_position(client), aim), 2),
                        "hostLines": evidence.evidence_lines(lines["host"]), "clientLines": evidence.evidence_lines(lines["client"]),
                        "hostExceptions": evidence.exception_lines(lines["host"]), "clientExceptions": evidence.exception_lines(lines["client"]),
                        "hostHookCalls": evidence.hook_call_lines(lines["host"]), "clientHookCalls": evidence.hook_call_lines(lines["client"]), **extra})
        if not fired:
            break
        if before[0] <= 0:
            break
    context["measurements"] = entries
    context["valid"] = bool(entries) and entries[0]["hostDelta"] > 0 and entries[0]["clientDelta"] > 0


def check_first_swing(context):
    entries = context.get("measurements") or []
    if not entries:
        return ["INVALID: no swing recorded"]
    first = entries[0]
    if first["hostDelta"] <= 0 or first["clientDelta"] <= 0:
        return ["INVALID: the first swing changed nothing (host %.2f, client %.2f); target %s" % (first["hostDelta"], first["clientDelta"], context.get("target", {}).get("name"))]
    return []


def check(context):
    issues = check_first_swing(context)
    if not issues:
        VALID_RUNS[0] += 1
    return issues


def never_changes(value, baseline):
    return False


def group_by_physics(reports):
    groups = {}
    for report in reports:
        target = report.get("target") or {}
        key = {True: "physics-active", False: "static", None: "physics unknown"}[target.get("physicsActive")]
        entry = groups.setdefault(key, {"runs": 0, "invalid": 0, "firedSwings": 0, "landedSwings": 0, "bySwing": {}, "targets": collections.Counter()})
        entry["runs"] += 1
        entry["targets"][target.get("name", "?")[-24:]] += 1
        measurements = report.get("measurements") or []
        first_landed = bool(measurements) and measurements[0]["hostDelta"] > 0 and measurements[0]["clientDelta"] > 0
        if not first_landed:
            entry["invalid"] += 1
            continue
        for measurement in measurements:
            landed = measurement["hostDelta"] > 0 and measurement["clientDelta"] > 0
            entry["firedSwings"] += 1
            entry["landedSwings"] += landed
            slot = entry["bySwing"].setdefault(measurement["swing"], [0, 0])
            slot[0] += landed
            slot[1] += 1
    return groups


SCENARIOS = [
    Scenario("worldhit_building_by_client", "the client stands within 3 of a physics-active, non-animal building taken from the host's own list (health 100 to 400, re-picked if it moves) and hits it bare handed five times, re-aiming each swing",
             prepare, act, lambda game, context: 0, never_changes, group=GROUP, check=check),
]

base.SCENARIOS.extend(SCENARIOS)

from . import spawned_crates  # noqa: E402,F401

from . import v2_suite  # noqa: E402,F401

from . import pvp_banded  # noqa: E402,F401

from . import corpse_banded  # noqa: E402,F401
