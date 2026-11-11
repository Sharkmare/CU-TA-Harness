import math
import time

from casualtieslink.desync import Scenario

SETTLE_SECONDS = 3.0
APPEAR_TIMEOUT_SECONDS = 8.0
NEARBY_RADIUS = 1.0
GROUND_RADIUS = 2.0
SOLID_SEARCH_DEPTH = 10
UNBREAKABLE_DAMAGE = 100000.0
BODY_PATH = "transform.position"
GROUND_ITEM_ID = "bandage"
CONTAINER_ID = "backpack"
CORPSE_ID = "corpse"
CORPSE_KILLED_HEALTH = 0.0
SPAWN_OFFSET = 3.0
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


def corpse_act(client, context):
    client.set("id:%d" % context["clientHandle"], "health", CORPSE_KILLED_HEALTH)


def door_prepare(host, client):
    anchor = player_position(client)
    rows = [row for row in client.call("find", type="Openable", limit=200) if "position" in row]
    if not rows:
        raise AssertionError("no Openable in the client world")
    nearest = min(rows, key=lambda row: distance(row["position"], anchor))
    wait_for_rows(host, "Openable", nearest["position"])
    entity = rows_near(client, "BuildingEntity", nearest["position"], radius=0.5)
    if not entity:
        raise AssertionError("the nearest Openable has no BuildingEntity on the client")
    return {"position": nearest["position"], "name": None, "clientHandle": entity[0]["object"]["id"]}


def door_read(game, context):
    rows = rows_near(game, "BuildingEntity", context["position"], radius=0.5)
    if not rows:
        return None
    return round(float(game.get("id:%d" % rows[0]["object"]["id"], "health")), 3)


def door_act(client, context):
    client.set("id:%d" % context["clientHandle"], "health", 0)


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


SCENARIOS = [
    Scenario("block_removal_by_client", "the client breaks a solid block below itself; the block id there becomes 0 on both",
             block_prepare, block_act, block_read, lambda value, baseline: value != baseline and value == 0),
    Scenario("item_pickup_by_client", "the client picks a spawned item off the ground; the ground count near it drops on both",
             pickup_prepare, pickup_act, ground_count, fewer),
    Scenario("item_drop_by_client", "the client drops a held item; a ground item appears on both",
             drop_prepare, drop_act, ground_count, more),
    Scenario("corpse_damage_by_client", "the client damages a spawned corpse to zero health; the corpse is gone or at zero on both",
             corpse_prepare, corpse_act, corpse_health, lambda value, baseline: value is None or (baseline is not None and value < baseline)),
    Scenario("door_open_by_client", "the client opens (breaks) the nearest door; its health drops or it disappears on both",
             door_prepare, door_act, door_read, lambda value, baseline: value is None or (baseline is not None and value < baseline)),
    Scenario("container_load_by_client", "the client loads an item into a container; the container's item count rises on both",
             container_prepare, load_act, container_children, more),
    Scenario("container_unload_by_client", "the client takes an item out of a container; the container's item count falls on both",
             unload_prepare, unload_act, container_children, fewer),
]
