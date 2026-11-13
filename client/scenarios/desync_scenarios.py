import math
import os
import unittest
import time

from casualtieslink import localcontent
from casualtieslink.scenarioengine import positioncontrol
from casualtieslink.scenarioengine.desync import Scenario, SeriesScenario
from scenarios.swing_driver import COOLDOWN_RISE_EPSILON

SCENARIOS = []
SERIES_SCENARIOS = []
NON_BUILDING_NAME_FRAGMENTS = tuple((localcontent.read_json("scenario_settings.json", {}) or {}).get("non_building_name_fragments", ()))
APPEAR_TIMEOUT_SECONDS = 20.0
NEARBY_RADIUS = 1.0
FALL_RADIUS = 3.0
BODY_PATH = "transform.position"


def player_position(game):
    value = game.get("player", BODY_PATH, depth=0)
    return {"x": float(value["x"]), "y": float(value["y"])}


def distance(first, second):
    return math.hypot(first["x"] - second["x"], first["y"] - second["y"])


def rows_near(game, component, position, name=None, radius=NEARBY_RADIUS):
    arguments = {"type": component, "limit": 200}
    if name:
        arguments["name"] = name
    return [row for row in game.call("find", **arguments) if "position" in row and distance(row["position"], position) <= radius]


def player_summary(game):
    try:
        return str(player_position(game))
    except Exception as exception:
        return "unknown (%s)" % exception


def nearest_summary(game, component, position, count=5):
    try:
        rows = [row for row in game.call("find", type=component, limit=400) if "position" in row]
    except Exception as exception:
        return "find failed: %s" % exception
    rows.sort(key=lambda row: distance(row["position"], position))
    return "; ".join("%s at (%.1f, %.1f)" % (row["object"]["name"], row["position"]["x"], row["position"]["y"]) for row in rows[:count]) or "none"


def wait_for_rows(game, component, position, name=None, timeout=APPEAR_TIMEOUT_SECONDS, radius=NEARBY_RADIUS):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = rows_near(game, component, position, name, radius=radius)
        if rows:
            return rows
        time.sleep(0.5)
    raise AssertionError("no %s%s near (%.1f, %.1f) on port %s within %.0fs; player at %s; nearest %s: %s" % (
        component, " named " + name if name else "", position["x"], position["y"], game.transport.port, timeout,
        player_summary(game), component, nearest_summary(game, component, position)))


def block_value(game, position):
    return int(game.call("invoke", target="world", method="GetBlock", args=[position], types=["Vector2"]))


def hand_slot(game):
    return int(game.get("player", "handSlot", depth=0))


SETTLE_SECONDS_AFTER_PICKUP = 2.0


def block_cell(game, position):
    half_width = int(game.get("world", "halfWidth", depth=0))
    half_height = int(game.get("world", "halfHeight", depth=0))
    return {"x": int(position["x"] + half_width), "y": int(position["y"] + half_height)}


def crack_counter(game, context):
    cell = context.get("cell") or block_cell(game, context["position"])
    found = game.call("invoke", target="world", method="GetBlockDamage", args=[cell], types=["Vector2Int"])
    if not isinstance(found, dict) or "damage" not in found:
        return 0.0
    return round(float(found["damage"]), 2)


def nearest_building(game, anchor):
    rows = [row for row in game.call("find", type="BuildingEntity", limit=200) if "position" in row]
    for row in sorted(rows, key=lambda row: distance(row["position"], anchor)):
        handle = "id:%d" % row["object"]["id"]
        name = row["object"]["name"].lower()
        if any(fragment in name for fragment in NON_BUILDING_NAME_FRAGMENTS) or game.get(handle, "indestructible", depth=0) or game.get(handle, "cantHit", depth=0):
            continue
        return row
    raise AssertionError("no breakable building near the client")


def building_health(game, context):
    rows = rows_near(game, "BuildingEntity", context["position"], radius=0.5)
    if not rows:
        return None
    return round(float(game.get("id:%d" % rows[0]["object"]["id"], "health", depth=0)), 1)


def body_handle_by_name(game, name):
    for row in game.call("find", type="Body"):
        if row["object"]["name"] == name:
            return "id:%d" % row["object"]["id"]
    raise AssertionError("no body named %s on port %s" % (name, game.transport.port))


def block_health(game, block_id):
    info = game.call("invoke", target="world", method="GetBlockInfo", args=[block_id], types=["UInt16"])
    return float(info["health"])


def empty_the_hand(client):
    slot = hand_slot(client)
    if client.call("invoke", target="player", method="GetItem", args=[slot], types=["Int32"]) is not None:
        client.call("invoke", target="player", method="DropItem", args=[slot], types=["Int32"])
        time.sleep(SETTLE_SECONDS_AFTER_PICKUP)


CLIENT_BODY_NAME = "Body_ClientD"


HOLD_CALL_PAUSE_SECONDS = 0.02
HOLD_MAX_CALLS = 1500


def hand_read(game, context):
    return [block_value(game, context["position"]), crack_counter(game, context)]


FRESH_BLOCK_ID = 8
FRESH_BLOCK_LAYOUTS = {
    "side": [(2, 0), (-2, 0), (3, 0), (-3, 0)],
    "above": [(0, 3), (0, 4)],
    "below": [(0, -2), (0, -3)],
    "adjacent": [(1, 0), (-1, 0)],
}
WALK_KEYS = ("A", "D")
WALK_TAP_FRAMES = 6
WALK_PERIOD_SECONDS = 0.9
FRESH_BLOCK_VERIFY_SECONDS = 6.0
FRESH_BLOCK_HEALTH_RANGE = (60.0, 150.0)
AIM_CIRCLE_RADIUS = 0.4
AIM_CIRCLE_PERIOD_SECONDS = 3.0
AIM_DRIFT_BLOCKS = 1.0
AIM_DRIFT_PERIOD_SECONDS = 4.0


AIM_NEAR_X_SWAY = 0.3
AIM_NEAR_X_PERIOD_SECONDS = 2.0


def aim_point(pattern, center, elapsed, anchor_x=None):
    if pattern == "fixed":
        return dict(center)
    if pattern == "near_x":
        if anchor_x is None:
            raise ValueError("the near_x pattern needs the character's x")
        sway = AIM_NEAR_X_SWAY * math.sin(2 * math.pi * elapsed / AIM_NEAR_X_PERIOD_SECONDS)
        return {"x": anchor_x + sway, "y": center["y"]}
    if pattern == "circle":
        angle = 2 * math.pi * elapsed / AIM_CIRCLE_PERIOD_SECONDS
        return {"x": center["x"] + AIM_CIRCLE_RADIUS * math.cos(angle), "y": center["y"] + AIM_CIRCLE_RADIUS * math.sin(angle)}
    if pattern == "drift":
        phase = (elapsed / AIM_DRIFT_PERIOD_SECONDS) % 1.0
        triangle = 2 * phase if phase < 0.5 else 2 * (1 - phase)
        return {"x": center["x"] + AIM_DRIFT_BLOCKS * (triangle - 0.5), "y": center["y"]}
    raise ValueError("unknown aim pattern %r" % pattern)


def world_centre_of_cell(game, cell):
    half_width = int(game.get("world", "halfWidth", depth=0))
    half_height = int(game.get("world", "halfHeight", depth=0))
    return {"x": cell["x"] - half_width + 0.5, "y": cell["y"] - half_height + 0.5}


def wait_for_block_on_both(host, client, centre, expected, timeout=FRESH_BLOCK_VERIFY_SECONDS):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if block_value(host, centre) == expected and block_value(client, centre) == expected:
            return
        time.sleep(0.25)
    raise AssertionError("block %d at (%.1f, %.1f) is not on both games after %.0fs: host %s, client %s" % (
        expected, centre["x"], centre["y"], timeout, block_value(host, centre), block_value(client, centre)))


def place_fresh_block(host, client, layout="side", block_id=FRESH_BLOCK_ID):
    base = block_cell(client, player_position(client))
    low, high = FRESH_BLOCK_HEALTH_RANGE
    seen = []
    for column, rise in FRESH_BLOCK_LAYOUTS[layout]:
        cell = {"x": base["x"] + column, "y": base["y"] + rise}
        centre = world_centre_of_cell(client, cell)
        existing = block_value(host, centre)
        if existing == 0:
            host.call("invoke", target="world", method="SetBlock", args=[cell["x"], cell["y"], block_id], types=["Int32", "Int32", "UInt16"])
            wait_for_block_on_both(host, client, centre, block_id)
            health = block_health(client, block_id)
            if not low <= health <= high:
                raise AssertionError("block %d has health %s, outside %s" % (block_id, health, FRESH_BLOCK_HEALTH_RANGE))
            return cell, centre, block_id, health, True
        seen.append((column, rise, existing))
    raise AssertionError("no free cell for a %s block next to the client; occupied (column, rise, block) %s" % (layout, seen))


POSITION_CONTROL_ENABLED = True
PARK_DIRECTION = "left"


def apply_position_control(host, client, context, parked_policy=positioncontrol.PARKED_STRICT):
    """Hold the client where it stands, park and hold the host body away from the swing line, and record the start positions and the preflight. With PARKED_RECORDED the host's drift
    is recorded and never fails the seat; the caller judges the parked host by its distance."""
    context["startPositions"] = positioncontrol.start_positions(host, client)
    try:
        context["positionControl"] = positioncontrol.seat_pair(host, client, positioncontrol.read_position(client), PARK_DIRECTION, parked_policy=parked_policy)
    except Exception as failure:
        context["positionControl"] = {"ok": False, "issues": ["position control failed: %s: %s" % (type(failure).__name__, str(failure)[:160])]}
    return context


def fresh_block_prepare_with(pattern, layout="side", walk=False, block_id=FRESH_BLOCK_ID, parked_policy=positioncontrol.PARKED_STRICT):
    def prepare(host, client):
        empty_the_hand(client)
        cell, centre, block, health, placed = place_fresh_block(host, client, layout, block_id)
        context = {"position": centre, "blockId": block, "blockHealth": health, "cell": cell, "placedByHost": placed, "aimPattern": pattern, "layout": layout, "walk": walk,
                   "hostGame": host, "hostBodyHandle": body_handle_by_name(host, CLIENT_BODY_NAME), "swingLog": [], "firstCall": None, "lastWalk": 0.0, "walkIndex": 0}
        if POSITION_CONTROL_ENABLED:
            apply_position_control(host, client, context, parked_policy)
        return context
    return prepare


def walk_a_little(client, context):
    now = time.time()
    if now - context["lastWalk"] < WALK_PERIOD_SECONDS:
        return
    context["lastWalk"] = now
    key = WALK_KEYS[context["walkIndex"] % len(WALK_KEYS)]
    context["walkIndex"] += 1
    client.call("input", key=key, mode="tap", frames=WALK_TAP_FRAMES)


def release_holds(*games):
    for game in games:
        if game is not None:
            positioncontrol.release_quietly(game)


def remove_fresh_block(host, client, context):
    release_holds(host, client)
    centre = context["position"]
    if context.get("placedByHost") and block_value(host, centre) != 0:
        host.call("invoke", target="world", method="SetBlock", args=[context["cell"]["x"], context["cell"]["y"], 0], types=["Int32", "Int32", "UInt16"])


def aimed_hold_hit(client, context):
    if context["firstCall"] is None:
        context["firstCall"] = time.time()
    if context.get("walk"):
        walk_a_little(client, context)
    real = player_position(client)
    target = aim_point(context["aimPattern"], context["position"], time.time() - context["firstCall"], real["x"])
    before = float(client.get("player", "attackCooldown", depth=0))
    is_right = client.get("player", "isRight", depth=0)
    copy = context["hostGame"].get(context["hostBodyHandle"], BODY_PATH, depth=0)
    client.call("invoke", target="player", method="UseItemInHand",
                sets=[{"target": "player", "path": "targetLookPos", "value": {"x": target["x"], "y": target["y"], "z": 0.0}}])
    after = float(client.get("player", "attackCooldown", depth=0))
    if after <= before + COOLDOWN_RISE_EPSILON:
        return False
    copy = {"x": float(copy["x"]), "y": float(copy["y"])}
    context["swingLog"].append({"clientPosition": real, "hostCopyPosition": copy, "gap": round(distance(real, copy), 3), "aim": target, "isRight": is_right})
    return True


READY_TYPE = "static:Together.CharacterSelectWait"
READY_TIMEOUT_SECONDS = 90.0


def try_ready(game):
    try:
        game.call("invoke", target=READY_TYPE, method="SetLocalReady", args=[True])
        return bool(game.get(READY_TYPE, "LocalConfirmed", depth=0))
    except Exception as exception:
        if "no type named" in str(exception):
            return None
        return False


PREFLIGHTS = []


def preflight_problems(fragments, attempts, builds=()):
    problems = []
    for check in PREFLIGHTS:
        problems.extend(check(fragments, attempts, builds))
    return problems


def stage_dll_preflight(fragments, attempts, builds):
    from casualtieslink.games import instances
    directories = instances.stage_directory_by_build()
    problems = []
    for build in builds:
        if build in directories:
            dll = os.path.join(directories[build](), "plugins", instances.TOGETHER_FOLDER, "CasualtiesMP.dll")
            if not os.path.isfile(dll):
                problems.append("the Together DLL of build %s is missing: %s" % (build, dll))
            else:
                for folder in instances.builds_needing_library_folders().get(build, ()):
                    library = os.path.join(directories[build](), "plugins", folder, folder + ".dll")
                    if not os.path.isfile(library):
                        problems.append("build %s needs the %s plugin and %s is missing" % (build, folder, library))
    return problems


PREFLIGHTS.append(stage_dll_preflight)


def matching_scenario_names(fragments):
    names = [scenario.name for scenario in SCENARIOS + SERIES_SCENARIOS]
    if not fragments:
        return names
    return [name for name in names if any(fragment in name for fragment in fragments)]


def counts_by_group(fragments):
    counts = {}
    selected = set(matching_scenario_names(fragments))
    for scenario in SCENARIOS + SERIES_SCENARIOS:
        if scenario.name not in selected:
            continue
        entry = counts.setdefault(scenario.group, {"plain": 0, "network": 0})
        entry["network" if scenario.network_sensitive else "plain"] += 1
    return counts


def reset_between_scenarios(host, client):
    try:
        client.call("release_input")
    except Exception:
        pass
    empty_the_hand(client)


def ready_up(games, timeout=READY_TIMEOUT_SECONDS, step=1.0, before_ready=None):
    pending = list(games)
    deadline = time.time() + timeout
    while pending and time.time() < deadline:
        if before_ready:
            for game in pending:
                chooser = before_ready.get(game)
                if chooser:
                    chooser(game)
        pending = [game for game in pending if try_ready(game) is False]
        if pending:
            time.sleep(step)
    return not pending


localcontent.import_scenario_modules()
