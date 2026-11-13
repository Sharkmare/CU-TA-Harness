import math
import statistics
import time

from casualtieslink.scenarioengine.desync import Scenario, SeriesScenario

from scenarios import desync_scenarios as base

HOOK_GROUP = "hook-check"
HOST_BODY_NAME = "Body_HostD"
REGRESSION_SWINGS = 5
SETTLE_AFTER_SWING_SECONDS = 1.0
ATTEMPT_PAUSE_SECONDS = 0.05
MAX_SWING_WAIT_SECONDS = 12.0
UNARMED_REACH = 4.0
DOUBLE_FACTOR = 1.6
DAMAGE_AGREEMENT_TOLERANCE = 1.0
SCATTER_TILES = 80 / 0.3
SCATTER_MARGIN_TILES = 15.0
SCATTER_SAMPLE_SECONDS = 4.0
SCATTER_HOLD_SECONDS = 45.0
SCATTER_COLUMNS = (285.0, -285.0, 305.0, -305.0, 335.0, -335.0)
POCKET_ROWS = 12
RADIATION_TOLERANCE = 0.5


def damage_issues(entries, requested):
    issues = []
    if len(entries) < requested:
        issues.append("only %d of %d swings fired" % (len(entries), requested))
    deltas = [entry["hostDelta"] for entry in entries if entry["hostDelta"] > 0]
    median = statistics.median(deltas) if deltas else 0.0
    for entry in entries:
        if abs(entry["hostDelta"] - entry["clientDelta"]) > max(DAMAGE_AGREEMENT_TOLERANCE, 0.05 * abs(entry["hostDelta"])):
            issues.append("swing %d: host lost %.2f but the client sees %.2f" % (entry["swing"], entry["hostDelta"], entry["clientDelta"]))
        if entry["hostDelta"] <= 0:
            issues.append("swing %d changed nothing on the host (damage missing)" % entry["swing"])
        elif median and entry["hostDelta"] > DOUBLE_FACTOR * median:
            issues.append("swing %d did %.2f against a median of %.2f (applied twice?)" % (entry["swing"], entry["hostDelta"], median))
    return issues


def fire_one_swing(client, target, timeout=MAX_SWING_WAIT_SECONDS, pause=ATTEMPT_PAUSE_SECONDS, attempts=None):
    """Invokes the swing until the attack cooldown rises. With an attempts dict, every invoke that the game ignored (no cooldown rise) is counted under 'ignored'."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        before = float(client.get("player", "attackCooldown", depth=0))
        client.call("invoke", target="player", method="UseItemInHand",
                    sets=[{"target": "player", "path": "targetLookPos", "value": {"x": target["x"], "y": target["y"], "z": 0.0}}])
        if float(client.get("player", "attackCooldown", depth=0)) > before + base.COOLDOWN_RISE_EPSILON:
            return True
        if attempts is not None:
            attempts["ignored"] = attempts.get("ignored", 0) + 1
        time.sleep(pause)
    return False


def measure_swings(host, client, read_host, read_client, target_of, count=REGRESSION_SWINGS, extra=None):
    entries = []
    for index in range(1, count + 1):
        before_host, before_client = read_host(), read_client()
        extra_before = extra() if extra else None
        if not fire_one_swing(client, target_of()):
            break
        time.sleep(SETTLE_AFTER_SWING_SECONDS)
        after_host, after_client = read_host(), read_client()
        entry = {"swing": index, "host": [before_host, after_host], "client": [before_client, after_client],
                 "hostDelta": round(before_host - after_host, 3), "clientDelta": round(before_client - after_client, 3)}
        if extra:
            entry["extra"] = [extra_before, extra()]
        entries.append(entry)
    return entries


def health_or_zero(game, context):
    value = base.building_health(game, context)
    return 0.0 if value is None else float(value)


def building_prepare(host, client):
    base.empty_the_hand(client)
    anchor = base.player_position(client)
    row = base.nearest_building(client, anchor)
    base.wait_for_rows(host, "BuildingEntity", row["position"], radius=0.5)
    if base.distance(row["position"], anchor) > UNARMED_REACH:
        client.set("player", base.BODY_PATH, {"x": row["position"]["x"] - 2.0, "y": row["position"]["y"], "z": 0.0})
        time.sleep(SETTLE_AFTER_SWING_SECONDS * 2)
    return {"position": row["position"], "name": None, "measurements": []}


def building_act(client, context):
    context["measurements"] = measure_swings(
        context["host"], client, lambda: health_or_zero(context["host"], context), lambda: health_or_zero(client, context), lambda: context["position"])


def building_prepare_with_host(host, client):
    context = building_prepare(host, client)
    context["host"] = host
    return context


def building_check(context):
    return damage_issues(context.get("measurements") or [], REGRESSION_SWINGS)


def limb_total(game, handle):
    total = 0.0
    index = 0
    while index < 30:
        try:
            skin = float(game.get(handle, "limbs[%d].skinHealth" % index, depth=0))
            muscle = float(game.get(handle, "limbs[%d].muscleHealth" % index, depth=0))
        except Exception:
            break
        total += skin + muscle
        index += 1
    if index == 0:
        raise AssertionError("no limbs readable on %s of port %s" % (handle, game.transport.port))
    return total


def pvp_prepare(host, client):
    base.empty_the_hand(client)
    victim_on_host = base.body_handle_by_name(host, HOST_BODY_NAME)
    victim_on_client = base.body_handle_by_name(client, HOST_BODY_NAME)
    here = base.player_position(client)
    there = client.get(victim_on_client, base.BODY_PATH, depth=0)
    target = {"x": float(there["x"]), "y": float(there["y"])}
    if base.distance(here, target) > UNARMED_REACH:
        client.set("player", base.BODY_PATH, {"x": target["x"] - 1.5, "y": target["y"], "z": 0.0})
        time.sleep(SETTLE_AFTER_SWING_SECONDS * 2)
    return {"position": target, "host": host, "hostVictim": victim_on_host, "clientVictim": victim_on_client, "measurements": []}


def pvp_act(client, context):
    host = context["host"]

    def victim_position():
        found = client.get(context["clientVictim"], base.BODY_PATH, depth=0)
        return {"x": float(found["x"]), "y": float(found["y"])}

    context["measurements"] = measure_swings(
        host, client, lambda: limb_total(host, context["hostVictim"]), lambda: limb_total(client, context["clientVictim"]), victim_position,
        extra=lambda: round(float(host.get(context["hostVictim"], base.BODY_PATH, depth=0)["x"]), 3))


def pvp_check(context):
    issues = damage_issues(context.get("measurements") or [], REGRESSION_SWINGS)
    moved = [abs(entry["extra"][1] - entry["extra"][0]) for entry in context.get("measurements") or [] if entry.get("extra")]
    if moved and max(moved) == 0:
        issues.append("the victim was never knocked back (host x did not change at any swing)")
    return issues


def find_far_pocket(host, origin, half_width_limit):
    for column in SCATTER_COLUMNS:
        x = origin["x"] + column
        if abs(x) > half_width_limit:
            continue
        for rise in range(-POCKET_ROWS, POCKET_ROWS + 1):
            y = origin["y"] + rise
            floor = base.block_value(host, {"x": x, "y": y - 1})
            body_cells = [base.block_value(host, {"x": x, "y": y + step}) for step in (0, 1, 2)]
            if floor > 0 and not any(body_cells):
                return {"x": x, "y": y + 0.2}
    return None


def netbody_handle_on_host(host, name):
    for row in host.call("find", type="NetBody", limit=50):
        handle = "id:%d" % row["object"]["id"]
        owner = host.get(handle, "body", depth=0)
        if isinstance(owner, dict) and owner.get("name") == name:
            return handle
    raise AssertionError("no NetBody for %s on the host" % name)


def scatter_state(host, body_handle, netbody_handle, client_handle_on_host):
    position = host.get(client_handle_on_host, base.BODY_PATH, depth=0)
    host_position = host.get("player", base.BODY_PATH, depth=0)
    return {"distanceTiles": round(math.hypot(float(position["x"]) - float(host_position["x"]), float(position["y"]) - float(host_position["y"])), 1),
            "radiationSickness": round(float(host.get(body_handle, "radiationSickness", depth=0)), 3),
            "eyePanicTime": round(float(host.get(body_handle, "eyePanicTime", depth=0)), 3),
            "chipPunishment": bool(host.get(netbody_handle, "chip_punishment_protocol", depth=0))}


def scatter_prepare(host, client):
    half_width = int(host.get("world", "halfWidth", depth=0))
    origin = base.player_position(client)
    pocket = find_far_pocket(host, origin, half_width - 5)
    handle = base.body_handle_by_name(host, base.CLIENT_BODY_NAME)
    return {"position": origin, "pocket": pocket, "host": host, "clientOnHost": handle, "netbody": netbody_handle_on_host(host, base.CLIENT_BODY_NAME), "measurements": []}


def scatter_act(client, context):
    host = context["host"]
    if context["pocket"] is None:
        context["measurements"].append({"error": "no open pocket far enough from the host"})
        return
    start = scatter_state(host, context["clientOnHost"], context["netbody"], context["clientOnHost"])
    context["measurements"].append({"t": 0.0, "phase": "before", **start})
    client.set("player", base.BODY_PATH, {"x": context["pocket"]["x"], "y": context["pocket"]["y"], "z": 0.0})
    started = time.time()
    try:
        while time.time() - started < SCATTER_HOLD_SECONDS:
            time.sleep(SCATTER_SAMPLE_SECONDS)
            context["measurements"].append({"t": round(time.time() - started, 1), "phase": "far", **scatter_state(host, context["clientOnHost"], context["netbody"], context["clientOnHost"])})
    finally:
        client.set("player", base.BODY_PATH, {"x": context["position"]["x"], "y": context["position"]["y"], "z": 0.0})


def scatter_check(context):
    entries = context.get("measurements") or []
    if entries and "error" in entries[0]:
        return ["could not set up: %s" % entries[0]["error"]]
    issues = []
    before = next((entry for entry in entries if entry.get("phase") == "before"), None)
    far = [entry for entry in entries if entry.get("phase") == "far"]
    if not far:
        return ["no samples while far from the host"]
    if max(entry["distanceTiles"] for entry in far) < SCATTER_TILES + SCATTER_MARGIN_TILES:
        issues.append("the client never got beyond %.0f tiles from the host (max %.1f)" % (SCATTER_TILES, max(entry["distanceTiles"] for entry in far)))
    if any(entry["chipPunishment"] for entry in far):
        issues.append("chip_punishment_protocol was true while far")
    growth = far[-1]["radiationSickness"] - before["radiationSickness"]
    if growth > RADIATION_TOLERANCE:
        issues.append("radiationSickness grew by %.3f while far" % growth)
    if max(entry["eyePanicTime"] for entry in far) > before["eyePanicTime"] + RADIATION_TOLERANCE:
        issues.append("eyePanicTime rose while far")
    return issues


def never_changes(value, baseline):
    return False


HOOK_MINING = SeriesScenario("hookcheck_dig_cracks", "held-click bare hand mining of a host-placed block on the build with the repaired Body.Attack transpiler",
                             base.fresh_block_prepare_with("fixed"), base.aimed_hold_hit, base.hand_read, cadence_seconds=base.HOLD_CALL_PAUSE_SECONDS,
                             max_hits=base.HOLD_MAX_CALLS, group=HOOK_GROUP, cleanup=base.remove_fresh_block)

HOOK_SCENARIOS = [
    Scenario("hook_building_hit_by_client", "the client hits the nearest building bare handed five times; the damage on host and client must be the same and applied once per swing",
             building_prepare_with_host, building_act, lambda game, context: 0, never_changes, group=HOOK_GROUP, check=building_check),
    Scenario("hook_pvp_melee_by_client", "the client punches the host's player five times; the victim's limb damage on host and client must agree, once per swing, with knockback",
             pvp_prepare, pvp_act, lambda game, context: 0, never_changes, group=HOOK_GROUP, check=pvp_check),
    Scenario("hook_scatter_distance_by_client", "the client stands more than 80 m (267 tiles) from the host for 45 s; the host side radiation, eye panic and chip flag of the client body must not move with NoScatterPunish loaded",
             scatter_prepare, scatter_act, lambda game, context: 0, never_changes, group=HOOK_GROUP, check=scatter_check),
]

base.SCENARIOS.extend(HOOK_SCENARIOS)
base.SERIES_SCENARIOS.append(HOOK_MINING)
