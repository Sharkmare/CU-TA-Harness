import time

from casualtieslink.desync import Scenario

from scenarios import desync_scenarios as base
from scenarios import hook_scenarios as hooks

REGRESSION_GROUP = "hook-regression"
BUILDING_HEALTH_RANGE = (100.0, 400.0)
BUILDINGS_CONSIDERED = 60
REACH_OFFSET = 1.5
FIRST_SWING_LANDED_MINIMUM = 0.0
EXACTLY_ONCE_TOLERANCE = 0.35


USED_TARGETS = set()
FIRST_PUNCH_ATTEMPTS = 3


def target_key(position):
    return (round(position["x"], 1), round(position["y"], 1))


def pick_target(candidates, anchor, health_range=BUILDING_HEALTH_RANGE, exclude=()):
    low, high = health_range
    usable = [item for item in candidates
              if "corpse" not in item["name"].lower() and not item["indestructible"] and not item["cantHit"] and low <= item["health"] <= high
              and target_key(item["position"]) not in exclude]
    if not usable:
        return None
    return min(usable, key=lambda item: base.distance(item["position"], anchor))


def read_candidates(game, anchor):
    rows = [row for row in game.call("find", type="BuildingEntity", limit=400) if "position" in row]
    rows.sort(key=lambda row: base.distance(row["position"], anchor))
    found = []
    for row in rows[:BUILDINGS_CONSIDERED]:
        handle = "id:%d" % row["object"]["id"]
        try:
            found.append({"id": row["object"]["id"], "name": row["object"]["name"], "position": row["position"],
                          "health": float(game.get(handle, "health", depth=0)), "indestructible": bool(game.get(handle, "indestructible", depth=0)),
                          "cantHit": bool(game.get(handle, "cantHit", depth=0))})
        except Exception:
            continue
    return found


def landing_issues(entries):
    if not entries:
        return ["INVALID: no swing fired, so nothing was measured"]
    first = entries[0]
    if first["hostDelta"] <= FIRST_SWING_LANDED_MINIMUM or first["clientDelta"] <= FIRST_SWING_LANDED_MINIMUM:
        return ["INVALID: the first swing changed nothing (host %.2f, client %.2f); this run says nothing about the hook" % (first["hostDelta"], first["clientDelta"])]
    return []


def once_per_swing_issues(entries):
    if not entries:
        return []
    reference = entries[0]["hostDelta"]
    issues = []
    for entry in entries:
        if abs(entry["hostDelta"] - entry["clientDelta"]) > max(hooks.DAMAGE_AGREEMENT_TOLERANCE, 0.05 * abs(entry["hostDelta"])):
            issues.append("swing %d: host lost %.2f but the client sees %.2f" % (entry["swing"], entry["hostDelta"], entry["clientDelta"]))
        if entry["hostDelta"] <= 0:
            issues.append("swing %d changed nothing on the host (damage missing)" % entry["swing"])
        elif entry["hostDelta"] > hooks.DOUBLE_FACTOR * reference:
            issues.append("swing %d did %.2f against %.2f for the first swing (applied twice?)" % (entry["swing"], entry["hostDelta"], reference))
        elif entry["hostDelta"] < (1 - EXACTLY_ONCE_TOLERANCE) * reference and entry["hostDelta"] > 0:
            issues.append("swing %d did only %.2f against %.2f for the first swing (partly missing?)" % (entry["swing"], entry["hostDelta"], reference))
    return issues


def measure_until_invalid(client, read_host, read_client, target_of, extra=None, count=hooks.REGRESSION_SWINGS, attempts=1, missed=None):
    first = hooks.measure_swings(None, client, read_host, read_client, target_of, count=1, extra=extra)
    tries = 1
    while first and landing_issues(first) and tries < attempts:
        if missed is not None:
            missed.append(first[0])
        first = hooks.measure_swings(None, client, read_host, read_client, target_of, count=1, extra=extra)
        tries += 1
    if not first or landing_issues(first):
        return first
    rest = hooks.measure_swings(None, client, read_host, read_client, target_of, count=count - 1, extra=extra)
    for index, entry in enumerate(rest, start=2):
        entry["swing"] = index
    return first + rest


def building_prepare(host, client):
    base.empty_the_hand(client)
    anchor = base.player_position(client)
    candidates = read_candidates(client, anchor)
    chosen = pick_target(candidates, anchor, exclude=USED_TARGETS)
    if chosen is None:
        raise AssertionError("no destructible building with health %s among the %d nearest; saw %s" % (
            BUILDING_HEALTH_RANGE, len(candidates), sorted(set((item["name"], item["health"]) for item in candidates))[:8]))
    USED_TARGETS.add(target_key(chosen["position"]))
    base.wait_for_rows(host, "BuildingEntity", chosen["position"], radius=0.5)
    client.set("player", base.BODY_PATH, {"x": chosen["position"]["x"] - REACH_OFFSET, "y": chosen["position"]["y"], "z": 0.0})
    time.sleep(hooks.SETTLE_AFTER_SWING_SECONDS * 2)
    after = base.player_position(client)
    if base.distance(after, chosen["position"]) > hooks.UNARMED_REACH:
        raise AssertionError("the client is %.1f from the building after the move, beyond the reach %.1f" % (base.distance(after, chosen["position"]), hooks.UNARMED_REACH))
    return {"position": chosen["position"], "name": None, "host": host, "building": {"name": chosen["name"], "health": chosen["health"]}, "measurements": [],
            "target": {"name": chosen["name"], "healthBefore": chosen["health"], "distance": round(base.distance(after, chosen["position"]), 2), "position": chosen["position"]}}


def building_act(client, context):
    context["measurements"] = measure_until_invalid(
        client, lambda: hooks.health_or_zero(context["host"], context), lambda: hooks.health_or_zero(client, context), lambda: context["position"])


def regression_check(context):
    entries = context.get("measurements") or []
    invalid = landing_issues(entries)
    if invalid:
        return invalid
    return once_per_swing_issues(entries)


def pvp_prepare(host, client):
    try:
        host.console("heal")
        time.sleep(hooks.SETTLE_AFTER_SWING_SECONDS * 2)
    except Exception:
        pass
    context = hooks.pvp_prepare(host, client)
    context["missedAttempts"] = []
    try:
        context["pvpRule"] = host.get("static:Together.Multiplayer", "rules.PVP", depth=0)
    except Exception as exception:
        context["pvpRule"] = "unreadable: %s" % exception
    return context


def pvp_act(client, context):
    host = context["host"]

    def victim_position():
        found = client.get(context["clientVictim"], base.BODY_PATH, depth=0)
        return {"x": float(found["x"]), "y": float(found["y"])}

    context["measurements"] = measure_until_invalid(
        client, lambda: hooks.limb_total(host, context["hostVictim"]), lambda: hooks.limb_total(client, context["clientVictim"]), victim_position,
        extra=lambda: round(float(host.get(context["hostVictim"], base.BODY_PATH, depth=0)["x"]), 3),
        attempts=FIRST_PUNCH_ATTEMPTS, missed=context["missedAttempts"])


def pvp_check(context):
    issues = regression_check(context)
    entries = context.get("measurements") or []
    moved = [abs(entry["extra"][1] - entry["extra"][0]) for entry in entries if entry.get("extra")]
    if entries and not landing_issues(entries) and moved and max(moved) == 0:
        issues.append("the victim was never knocked back (host x did not change at any swing); PVP rule reads %s" % context.get("pvpRule"))
    return issues


def never_changes(value, baseline):
    return False


REGRESSION_SCENARIOS = [
    Scenario("regress_building_hit_by_client", "the client moves next to a destructible building (100 to 400 health) and hits it bare handed; the first swing must damage it on host and client, every swing once",
             building_prepare, building_act, lambda game, context: 0, never_changes, group=REGRESSION_GROUP, check=regression_check),
    Scenario("regress_pvp_melee_by_client", "with the PVP rule on, the client punches the host's player; the first punch must damage the victim on host and client, every punch once, with knockback",
             pvp_prepare, pvp_act, lambda game, context: 0, never_changes, group=REGRESSION_GROUP, check=pvp_check),
]

base.SCENARIOS.extend(REGRESSION_SCENARIOS)
