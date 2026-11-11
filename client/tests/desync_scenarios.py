import math
import time

from casualtieslink.desync import Scenario

SETTLE_SECONDS = 3.0
APPEAR_TIMEOUT_SECONDS = 20.0
NEARBY_RADIUS = 1.0
GROUND_RADIUS = 1.0
SOLID_SEARCH_DEPTH = 10
UNBREAKABLE_DAMAGE = 100000.0
BODY_PATH = "transform.position"
GROUND_ITEM_ID = "bandage"
CONTAINER_ID = "pouch"
CORPSE_ID = "corpse"
CORPSE_KILLED_HEALTH = 0.0
SPAWN_OFFSET = 1.5
INVENTORY_SLOT = 0


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


def wait_for_rows(game, component, position, name=None, timeout=APPEAR_TIMEOUT_SECONDS):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = rows_near(game, component, position, name)
        if rows:
            return rows
        time.sleep(0.5)
    raise AssertionError("no %s%s near (%.1f, %.1f) on port %s within %.0fs" % (
        component, " named " + name if name else "", position["x"], position["y"], game.transport.port, timeout))


def block_value(game, position):
    return int(game.call("invoke", target="world", method="GetBlock", args=[position], types=["Vector2"]))


def solid_block_below(game):
    base = player_position(game)
    for depth in range(1, SOLID_SEARCH_DEPTH + 1):
        candidate = {"x": base["x"], "y": base["y"] - depth}
        if block_value(game, candidate) > 0:
            return candidate
    raise AssertionError("no solid block within %d below the player at (%.1f, %.1f)" % (SOLID_SEARCH_DEPTH, base["x"], base["y"]))


def block_prepare(host, client):
    return {"position": solid_block_below(client)}


def block_act(client, context):
    client.call("invoke", target="world", method="DamageBlock", args=[context["position"], UNBREAKABLE_DAMAGE], types=["Vector2", "Single", "Boolean", "Boolean"])


def block_read(game, context):
    return block_value(game, context["position"])


def is_unparented(game, row):
    try:
        return game.get("id:%d" % row["object"]["id"], "transform.parent", depth=0) is None
    except Exception:
        return True


def ground_count(game, context):
    rows = rows_near(game, "Item", context["position"], context["name"], radius=GROUND_RADIUS)
    return sum(1 for row in rows if is_unparented(game, row))


def spawn_on_host(host, client, item_id):
    anchor = player_position(client)
    spot = {"x": anchor["x"] + SPAWN_OFFSET, "y": anchor["y"]}
    host.call("spawn", id=item_id, x=spot["x"], y=spot["y"], pickup=False)
    return spot


def item_on_both(host, client, item_id):
    spot = spawn_on_host(host, client, item_id)
    wait_for_rows(host, "Item", spot, item_id)
    rows = wait_for_rows(client, "Item", spot, item_id)
    return {"position": spot, "name": item_id, "clientHandle": rows[0]["object"]["id"]}


def pickup_prepare(host, client):
    return item_on_both(host, client, GROUND_ITEM_ID)


def pickup_act(client, context):
    client.call("invoke", target="player", method="PickUpItem", args=["id:%d" % context["clientHandle"], INVENTORY_SLOT, True], types=["Item", "Int32", "Boolean"])


def drop_prepare(host, client):
    context = item_on_both(host, client, GROUND_ITEM_ID)
    pickup_act(client, context)
    time.sleep(SETTLE_SECONDS)
    context["position"] = player_position(client)
    return context


def drop_act(client, context):
    client.call("invoke", target="player", method="DropItem", args=[INVENTORY_SLOT], types=["Int32"])


def corpse_health(game, context):
    rows = rows_near(game, "BuildingEntity", context["position"], context["name"])
    if not rows:
        return None
    return round(float(game.get("id:%d" % rows[0]["object"]["id"], "health")), 3)


def corpse_prepare(host, client):
    spot = spawn_on_host(host, client, CORPSE_ID)
    wait_for_rows(host, "BuildingEntity", spot, CORPSE_ID)
    rows = wait_for_rows(client, "BuildingEntity", spot, CORPSE_ID)
    return {"position": spot, "name": CORPSE_ID, "clientHandle": rows[0]["object"]["id"]}


def container_children(game, context):
    rows = rows_near(game, "Container", context["position"], context["name"])
    if not rows:
        return None
    return int(game.get("id:%d" % rows[0]["object"]["id"], "itemCount"))


def container_prepare(host, client):
    spot = spawn_on_host(host, client, CONTAINER_ID)
    wait_for_rows(host, "Container", spot, CONTAINER_ID)
    container = wait_for_rows(client, "Container", spot, CONTAINER_ID)[0]
    held = {"x": spot["x"] + SPAWN_OFFSET / 2, "y": spot["y"]}
    host.call("spawn", id=GROUND_ITEM_ID, x=held["x"], y=held["y"], pickup=False)
    item = wait_for_rows(client, "Item", held, GROUND_ITEM_ID)[0]
    return {"position": spot, "name": CONTAINER_ID, "containerHandle": container["object"]["id"], "itemHandle": item["object"]["id"]}


def load_act(client, context):
    client.call("invoke", target="id:%d" % context["containerHandle"], method="LoadItem", args=["id:%d" % context["itemHandle"]])


def unload_prepare(host, client):
    context = container_prepare(host, client)
    load_act(client, context)
    time.sleep(SETTLE_SECONDS)
    return context


def unload_act(client, context):
    client.call("invoke", target="id:%d" % context["containerHandle"], method="UnloadItem", args=["id:%d" % context["itemHandle"]])


def fewer(value, baseline):
    return value is not None and baseline is not None and value < baseline


def more(value, baseline):
    return value is not None and baseline is not None and value > baseline




PICKAXE_ID = "pickaxe"
BREAD_ID = "bread"
DYNAMITE_ID = "dynamite"
SWING_PAUSE_SECONDS = 0.7
MAX_SWINGS = 15
REACH_BLOCKS = 4
CRATER_RADIUS = 4
HUNGER_START = 40.0
HUNGER_GAIN = 5.0
FUSE_OFFSETS_SECONDS = (6.0, 8.0, 12.0)
DIG_OFFSETS_SECONDS = (0.0, 3.0, 8.0)
THROW_RADIUS = 12.0
CORPSE_FLAGS = {"setchar": 2}


def hand_slot(game):
    return int(game.get("player", "handSlot", depth=0))


def hold_on_client(host, client, item_id):
    context = item_on_both(host, client, item_id)
    client.call("invoke", target="player", method="PickUpItem", args=["id:%d" % context["clientHandle"], hand_slot(client), True], types=["Item", "Int32", "Boolean"])
    time.sleep(SETTLE_SECONDS_AFTER_PICKUP)
    return context


SETTLE_SECONDS_AFTER_PICKUP = 2.0


def look_at(game, position):
    game.set("player", "targetLookPos", {"x": position["x"], "y": position["y"], "z": 0.0})


def swing(client, position, times=1):
    for _ in range(times):
        look_at(client, position)
        client.call("invoke", target="player", method="UseItemInHand")
        time.sleep(SWING_PAUSE_SECONDS)


def solid_block_within_reach(game):
    base = player_position(game)
    for depth in range(1, REACH_BLOCKS + 1):
        candidate = {"x": base["x"], "y": base["y"] - depth}
        if block_value(game, candidate) > 0:
            return candidate
    raise AssertionError("no solid block within %d below the player at (%.1f, %.1f)" % (REACH_BLOCKS, base["x"], base["y"]))


def dig_prepare(host, client):
    hold_on_client(host, client, PICKAXE_ID)
    return {"position": solid_block_within_reach(client)}


def dig_act(client, context):
    for _ in range(MAX_SWINGS):
        if block_value(client, context["position"]) == 0:
            return
        swing(client, context["position"])


def crack_prepare(host, client):
    return dig_prepare(host, client)


def crack_act(client, context):
    swing(client, context["position"])


def numbers_in(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from numbers_in(child)
    elif isinstance(value, list):
        for child in value:
            yield from numbers_in(child)


def block_cell(game, position):
    half_width = int(game.get("world", "halfWidth", depth=0))
    half_height = int(game.get("world", "halfHeight", depth=0))
    return {"x": int(position["x"] + half_width), "y": int(position["y"] + half_height)}


def crack_read(game, context):
    cell = block_cell(game, context["position"])
    rows = game.get("world", "blockDamages", depth=3)
    for node in numbers_in(rows):
        cell_node = node.get("pos")
        if isinstance(cell_node, dict) and cell_node.get("x") == cell["x"] and cell_node.get("y") == cell["y"] and "damage" in node:
            return round(float(node["damage"]), 2)
    return 0.0


def nearest_building(game, anchor):
    rows = [row for row in game.call("find", type="BuildingEntity", limit=200) if "position" in row]
    for row in sorted(rows, key=lambda row: distance(row["position"], anchor)):
        handle = "id:%d" % row["object"]["id"]
        name = row["object"]["name"].lower()
        if "corpse" in name or game.get(handle, "indestructible", depth=0) or game.get(handle, "cantHit", depth=0):
            continue
        return row
    raise AssertionError("no breakable building near the client")


def building_prepare(host, client):
    hold_on_client(host, client, PICKAXE_ID)
    row = nearest_building(client, player_position(client))
    wait_for_rows(host, "BuildingEntity", row["position"], radius=0.5)
    return {"position": row["position"], "name": None, "clientHandle": row["object"]["id"]}


def building_act(client, context):
    for _ in range(MAX_SWINGS):
        if building_health(client, context) is None:
            return
        swing(client, context["position"])


def building_health(game, context):
    rows = rows_near(game, "BuildingEntity", context["position"], radius=0.5)
    if not rows:
        return None
    return round(float(game.get("id:%d" % rows[0]["object"]["id"], "health", depth=0)), 1)


def corpse_punch_prepare(host, client):
    hold_on_client(host, client, PICKAXE_ID)
    return corpse_prepare(host, client)


def corpse_punch_act(client, context):
    swing(client, context["position"], times=4)


def door_prepare(host, client):
    anchor = player_position(client)
    rows = [row for row in client.call("find", type="Openable", limit=200) if "position" in row]
    instant = [row for row in rows if client.get("id:%d" % row["object"]["id"], "instantOpen", depth=0)]
    if not instant:
        raise AssertionError("no instantOpen Openable in the client world (%d Openables)" % len(rows))
    nearest = min(instant, key=lambda row: distance(row["position"], anchor))
    wait_for_rows(host, "Openable", nearest["position"])
    return {"position": nearest["position"], "name": None, "clientHandle": nearest["object"]["id"]}


def door_act(client, context):
    client.call("invoke", target="id:%d" % context["clientHandle"], method="OnUse")


def door_read(game, context):
    return building_health(game, context)


def throw_prepare(host, client):
    context = hold_on_client(host, client, GROUND_ITEM_ID)
    context["position"] = player_position(client)
    return context


def throw_act(client, context):
    client.call("invoke", target="player", method="ThrowItem", args=[1.0])


def thrown_count(game, context):
    rows = rows_near(game, "Item", context["position"], context["name"], radius=THROW_RADIUS)
    return sum(1 for row in rows if is_unparented(game, row))


def body_handle_by_name(game, name):
    for row in game.call("find", type="Body"):
        if row["object"]["name"] == name:
            return "id:%d" % row["object"]["id"]
    raise AssertionError("no body named %s on port %s" % (name, game.transport.port))


def eat_prepare(host, client):
    handle = body_handle_by_name(host, "Body_ClientD")
    host.set(handle, "hunger", HUNGER_START)
    time.sleep(SETTLE_SECONDS_AFTER_PICKUP)
    hold_on_client(host, client, BREAD_ID)
    return {"bodyName": "Body_ClientD"}


def eat_act(client, context):
    client.call("invoke", target="player", method="UseItemInHand")


def hunger_read(game, context):
    return round(float(game.get(body_handle_by_name(game, context["bodyName"]), "hunger", depth=0)), 1)


def crater_sum(game, centre):
    total = 0
    for dx in range(-CRATER_RADIUS, CRATER_RADIUS + 1):
        for dy in range(-CRATER_RADIUS, CRATER_RADIUS + 1):
            total += block_value(game, {"x": centre["x"] + dx, "y": centre["y"] + dy})
    return total


def crater_prepare(host, client):
    hold_on_client(host, client, DYNAMITE_ID)
    wall = solid_block_within_reach(client)
    return {"position": wall}


def crater_act(client, context):
    client.call("invoke", target="player", method="UseItemInHand")
    time.sleep(SWING_PAUSE_SECONDS)
    look_at(client, context["position"])
    client.call("invoke", target="player", method="ThrowItem", args=[0.3])


def crater_read(game, context):
    return crater_sum(game, context["position"])


def gone_or_lower(value, baseline):
    return value is None or (baseline is not None and value < baseline)


def lower_sum(value, baseline):
    return value < baseline


SCENARIOS = [
    Scenario("block_removal_by_client", "control: the client calls WorldGeneration.DamageBlock directly (the vanilla local call, not Together's carrier); the block id there becomes 0 on both",
             block_prepare, block_act, block_read, lambda value, baseline: value != baseline and value == 0),
    Scenario("S1_block_dig_by_client", "the client digs a block with a pickaxe through Body.UseItemInHand; the block is gone on both and stays gone",
             dig_prepare, dig_act, block_read, lambda value, baseline: value != baseline and value == 0, offsets=DIG_OFFSETS_SECONDS),
    Scenario("S2_block_crack_by_client", "the client hits a block once; the host and client damage counters for that block are equal",
             crack_prepare, crack_act, crack_read, lambda value, baseline: value > baseline),
    Scenario("S3_corpse_punch_by_client", "a Dune client hits a corpse (host is not Dune); the corpse health agrees on both",
             corpse_punch_prepare, corpse_punch_act, corpse_health, gone_or_lower, group="mixed-characters"),
    Scenario("S5_building_break_by_client", "the client breaks the nearest building with a pickaxe; destroyed on both, not rebuilt",
             building_prepare, building_act, building_health, gone_or_lower, offsets=DIG_OFFSETS_SECONDS),
    Scenario("S6_door_open_by_client", "the client uses an instant-open door; its state is equal on both",
             door_prepare, door_act, door_read, gone_or_lower),
    Scenario("S7_item_pickup_by_client", "the client picks a spawned item off the ground; the ground count near it drops on both",
             pickup_prepare, pickup_act, ground_count, fewer),
    Scenario("S7_item_drop_by_client", "the client drops a held item; a ground item appears on both",
             drop_prepare, drop_act, ground_count, more),
    Scenario("S7_item_throw_by_client", "the client throws a held item; a ground item appears near it on both",
             throw_prepare, throw_act, thrown_count, more),
    Scenario("S9_eat_by_client", "the client eats bread; its hunger value rises and the host agrees",
             eat_prepare, eat_act, hunger_read, lambda value, baseline: value >= baseline + HUNGER_GAIN),
    Scenario("S14_grenade_crater_by_client", "the client lights and throws dynamite at a wall; the crater is the same on both",
             crater_prepare, crater_act, crater_read, lower_sum, offsets=FUSE_OFFSETS_SECONDS),
    Scenario("container_load_by_client", "the client loads an item into a container; the container's item count rises on both",
             container_prepare, load_act, container_children, more),
    Scenario("container_unload_by_client", "the client takes an item out of a container; the container's item count falls on both",
             unload_prepare, unload_act, container_children, fewer),
]


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


def ready_up(games, timeout=READY_TIMEOUT_SECONDS, step=1.0):
    pending = list(games)
    deadline = time.time() + timeout
    while pending and time.time() < deadline:
        pending = [game for game in pending if try_ready(game) is False]
        if pending:
            time.sleep(step)
    return not pending
