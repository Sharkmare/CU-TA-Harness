import collections
import itertools
import re
import time

from casualtieslink.desync import Scenario

from . import desync_scenarios as base
from . import hook_scenarios as hooks

EVIDENCE_GROUP = "hook-evidence"
BUILDING_RESOURCES = ("leadbush", "geyser", "stoneplant", "hydreed")
SPAWN_OFFSET = 2.0
SPAWN_HEALTH_RANGE = (100.0, 400.0)
SWINGS = 5
LINE_LIMIT = 8
LINE_WIDTH = 220
EXCEPTION = re.compile(r"Exception|\[Error")
FIND_THE_BUG_TYPE = "static:KrokV5Optimization.FindTheBug"

LOG_READER = None
RESOURCE_CYCLE = itertools.cycle(BUILDING_RESOURCES)


def read_log(which):
    if LOG_READER is None:
        return ""
    return LOG_READER(which)


def find_the_bug_enabled(game):
    try:
        return bool(game.call("get", target=FIND_THE_BUG_TYPE, path="Enabled.Value", depth=0, nonpublic=True))
    except Exception:
        return None


def new_lines(before_count, text):
    return text.splitlines()[before_count:]


def evidence_lines(lines):
    wanted = [line.strip()[:LINE_WIDTH] for line in lines if "evidencebag" in line.lower() or "damage " in line or "hit send" in line or "hit client" in line or "hit server" in line]
    return wanted[:LINE_LIMIT]


def exception_lines(lines):
    return [line.strip()[:LINE_WIDTH] for line in lines if EXCEPTION.search(line)][:LINE_LIMIT]


def stage_of_miss(entry):
    if entry["hostDelta"] > 0 and entry["clientDelta"] > 0:
        return "landed"
    client_damage = [line for line in entry["clientLines"] if "damage client" in line or ("damage" in line and "local=" in line)]
    host_decision = [line for line in entry["hostLines"] if "hit server" in line]
    if not entry["fired"]:
        return "no swing fired (cooldown never cleared)"
    if not client_damage:
        return "client: no DamageBuilding line (hit loop or hook did not reach the building)"
    if not host_decision:
        return "host: no 'hit server' decision line"
    return "host decided but no damage on either side"


def summarise(entries):
    groups = collections.OrderedDict()
    for entry in entries:
        stage = stage_of_miss(entry)
        groups.setdefault(stage, []).append(entry["swing"])
    return groups


def spawn_building(host, client, resource):
    anchor = base.player_position(client)
    spot = {"x": anchor["x"] + SPAWN_OFFSET, "y": anchor["y"]}
    host.call("spawn", id=resource, x=spot["x"], y=spot["y"], pickup=False)
    host_rows = base.wait_for_rows(host, "BuildingEntity", spot, radius=base.FALL_RADIUS)
    client_rows = base.wait_for_rows(client, "BuildingEntity", spot, radius=base.FALL_RADIUS)
    handle = "id:%d" % host_rows[0]["object"]["id"]
    health = float(host.get(handle, "health", depth=0))
    low, high = SPAWN_HEALTH_RANGE
    if not low <= health <= high:
        raise AssertionError("spawned %s has health %s, outside %s" % (resource, health, SPAWN_HEALTH_RANGE))
    return host_rows[0], client_rows[0], handle, health


def evidence_prepare(host, client):
    base.empty_the_hand(client)
    resource = next(RESOURCE_CYCLE)
    host_row, client_row, handle, health = spawn_building(host, client, resource)
    position = client_row["position"]
    distance = round(base.distance(base.player_position(client), position), 2)
    return {"position": position, "name": None, "host": host, "hostHandle": handle, "measurements": [],
            "target": {"resource": resource, "name": host_row["object"]["name"], "healthBefore": health, "distance": distance, "position": position}}


def health_of(game, context):
    return hooks.health_or_zero(game, context)


def evidence_act(client, context):
    host = context["host"]
    entries = []
    for index in range(1, SWINGS + 1):
        marks = {which: len(read_log(which).splitlines()) for which in ("host", "client")}
        before = (health_of(host, context), health_of(client, context))
        cooldown_before = float(client.get("player", "attackCooldown", depth=0))
        fired = hooks.fire_one_swing(client, context["position"])
        cooldown_after = float(client.get("player", "attackCooldown", depth=0))
        time.sleep(hooks.SETTLE_AFTER_SWING_SECONDS)
        after = (health_of(host, context), health_of(client, context))
        lines = {which: new_lines(marks[which], read_log(which)) for which in ("host", "client")}
        entries.append({"swing": index, "fired": fired, "host": [before[0], after[0]], "client": [before[1], after[1]],
                        "hostDelta": round(before[0] - after[0], 3), "clientDelta": round(before[1] - after[1], 3),
                        "cooldown": [round(cooldown_before, 3), round(cooldown_after, 3)],
                        "hostLines": evidence_lines(lines["host"]), "clientLines": evidence_lines(lines["client"]),
                        "hostExceptions": exception_lines(lines["host"]), "clientExceptions": exception_lines(lines["client"])})
        if not fired:
            break
    context["measurements"] = entries
    context["stages"] = {stage: swings for stage, swings in summarise(entries).items()}
    try:
        host.set(context["hostHandle"], "health", 0)
    except Exception:
        pass


def evidence_check(context):
    entries = context.get("measurements") or []
    if not entries:
        return ["INVALID: no swing recorded"]
    return []


def never_changes(value, baseline):
    return False


EVIDENCE_SCENARIOS = [
    Scenario("evidence_building_hit_by_client", "the host spawns a building next to the client, the client hits it bare handed five times; per swing the health deltas on both games and the evidence lines of that swing",
             evidence_prepare, evidence_act, lambda game, context: 0, never_changes, group=EVIDENCE_GROUP, check=evidence_check),
]

base.SCENARIOS.extend(EVIDENCE_SCENARIOS)
