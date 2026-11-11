import collections
import time

from casualtieslink.desync import Scenario

from . import desync_scenarios as base
from . import evidence_scenarios as evidence
from . import hook_scenarios as hooks

GROUP = "hook-evidence"
HEALTH_RANGE = (100.0, 400.0)
CANDIDATES_CONSIDERED = 60
HOST_LIST_LIMIT = 400
MAX_START_DISTANCE = 3.0
MOVE_OFFSET = 1.5
CLIENT_SEES_TARGET_SECONDS = 8.0
SWINGS = 5
SYNCHRONIZER_TYPE = "static:ScavMPBuildingSynchronizer"
USED = set()
PHYSICS_COUNTS = collections.Counter()


def key_of(position):
    return (round(position["x"], 1), round(position["y"], 1))


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
            "rigidbodyType": optional_get(host, handle, "rb.bodyType", nonpublic=True), "layer": optional_get(host, handle, "gameObject.layer"),
            "physicsActive": physics_active(host, handle)}


def host_candidates(host, anchor):
    rows = [row for row in host.call("find", type="BuildingEntity", limit=HOST_LIST_LIMIT) if "position" in row]
    rows.sort(key=lambda row: base.distance(row["position"], anchor))
    found = []
    for row in rows[:CANDIDATES_CONSIDERED]:
        described = describe_candidate(host, row)
        if described is not None:
            found.append(described)
    return found


def usable(candidate, used=USED, health_range=HEALTH_RANGE):
    low, high = health_range
    return ("corpse" not in candidate["name"].lower() and not candidate["cantHit"] and not candidate["indestructible"]
            and low <= candidate["health"] <= high and key_of(candidate["position"]) not in used)


def choose(candidates, anchor, counts=PHYSICS_COUNTS, used=USED):
    pool = [item for item in candidates if usable(item, used)]
    if not pool:
        return None
    wanted = [item for item in pool if item["physicsActive"] is not None and counts[item["physicsActive"]] == min(counts[True], counts[False])]
    chosen_pool = wanted or pool
    return min(chosen_pool, key=lambda item: base.distance(item["position"], anchor))


def wait_until_client_sees(client, position, timeout=CLIENT_SEES_TARGET_SECONDS):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = base.rows_near(client, "BuildingEntity", position, radius=0.5)
        if rows:
            return rows[0]
        time.sleep(0.5)
    return None


def prepare(host, client):
    base.empty_the_hand(client)
    anchor = base.player_position(client)
    candidates = host_candidates(host, anchor)
    chosen = choose(candidates, anchor)
    if chosen is None:
        raise AssertionError("no fresh hittable destructible building with health %s among the %d nearest on the host; saw %s" % (
            HEALTH_RANGE, len(candidates), sorted(set((item["name"][-30:], item["health"]) for item in candidates))[:8]))
    USED.add(key_of(chosen["position"]))
    if base.distance(anchor, chosen["position"]) > MAX_START_DISTANCE:
        client.set("player", base.BODY_PATH, {"x": chosen["position"]["x"] - MOVE_OFFSET, "y": chosen["position"]["y"], "z": 0.0})
        time.sleep(hooks.SETTLE_AFTER_SWING_SECONDS * 2)
    client_row = wait_until_client_sees(client, chosen["position"])
    if client_row is None:
        raise AssertionError("the client does not see the host's building %s at (%.1f, %.1f) within %.0f s" % (chosen["name"], chosen["position"]["x"], chosen["position"]["y"], CLIENT_SEES_TARGET_SECONDS))
    distance = base.distance(base.player_position(client), chosen["position"])
    if distance > MAX_START_DISTANCE:
        raise AssertionError("the client is %.2f from the building after the move, beyond %.1f" % (distance, MAX_START_DISTANCE))
    fresh_health = float(optional_get(host, chosen["handle"], "health") or 0.0)
    if fresh_health <= 0:
        raise AssertionError("the host building %s has health %.1f before the first swing" % (chosen["name"], fresh_health))
    PHYSICS_COUNTS[bool(chosen["physicsActive"])] += 1
    target = dict(chosen, distance=round(distance, 2), healthBefore=fresh_health, clientHandle="id:%d" % client_row["object"]["id"])
    return {"position": chosen["position"], "name": None, "host": host, "hostHandle": chosen["handle"], "clientHandle": target["clientHandle"], "target": target, "measurements": []}


def health_by_handle(game, handle):
    value = optional_get(game, handle, "health")
    return 0.0 if value is None else float(value)


def current_position(host, context):
    found = optional_get(host, context["hostHandle"], base.BODY_PATH)
    if isinstance(found, dict) and "x" in found:
        return {"x": float(found["x"]), "y": float(found["y"])}
    return context["position"]


def act(client, context):
    host = context["host"]
    entries = []
    for index in range(1, SWINGS + 1):
        aim = current_position(host, context)
        marks = {which: len(evidence.read_log(which).splitlines()) for which in ("host", "client")}
        before = (health_by_handle(host, context["hostHandle"]), health_by_handle(client, context["clientHandle"]))
        cooldown_before = float(client.get("player", "attackCooldown", depth=0))
        fired = hooks.fire_one_swing(client, aim)
        cooldown_after = float(client.get("player", "attackCooldown", depth=0))
        time.sleep(hooks.SETTLE_AFTER_SWING_SECONDS)
        after = (health_by_handle(host, context["hostHandle"]), health_by_handle(client, context["clientHandle"]))
        lines = {which: evidence.new_lines(marks[which], evidence.read_log(which)) for which in ("host", "client")}
        entries.append({"swing": index, "fired": fired, "aim": aim, "host": [before[0], after[0]], "client": [before[1], after[1]],
                        "hostDelta": round(before[0] - after[0], 3), "clientDelta": round(before[1] - after[1], 3),
                        "cooldown": [round(cooldown_before, 3), round(cooldown_after, 3)],
                        "hostLines": evidence.evidence_lines(lines["host"]), "clientLines": evidence.evidence_lines(lines["client"]),
                        "hostExceptions": evidence.exception_lines(lines["host"]), "clientExceptions": evidence.exception_lines(lines["client"])})
        if not fired:
            break
        if before[0] <= 0:
            break
    context["measurements"] = entries
    context["valid"] = bool(entries) and entries[0]["hostDelta"] > 0 and entries[0]["clientDelta"] > 0


def check(context):
    entries = context.get("measurements") or []
    if not entries:
        return ["INVALID: no swing recorded"]
    first = entries[0]
    if first["hostDelta"] <= 0 or first["clientDelta"] <= 0:
        return ["INVALID: the first swing changed nothing (host %.2f, client %.2f); target %s" % (first["hostDelta"], first["clientDelta"], context.get("target", {}).get("name"))]
    return []


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
    Scenario("worldhit_building_by_client", "the client stands within 3 of a building taken from the host's own list (fresh, hittable, 100 to 400 health) and hits it bare handed five times, re-aiming each swing; targets are grouped by physics-active or static",
             prepare, act, lambda game, context: 0, never_changes, group=GROUP, check=check),
]

base.SCENARIOS.extend(SCENARIOS)
