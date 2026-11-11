import copy
import os
import unittest

from casualtieslink.desync import Scenario

from . import desync_scenarios as base
from . import hook_scenarios as hooks
from . import pvp_banded
from . import regression_scenarios as regression
from . import spawned_crates as crates
from . import world_building as world

GROUP = "hook-dune"
CORPSE_NAME = "dune2_corpse_hit_by_client"
PVP_NAME = "dune1_pvp_banded_by_client"
CORPSE_ID = "corpse"
DUNE = 2
CLIENT_BODY_NAME = "Body_ClientD"
VALID_RUNS_WANTED = 6
STOP_AFTER_SETUP_FAILURES = 5
MIN_CORPSE_HEALTH = 1.0
PVP_RUNS_VARIABLE = "CU_DUNE_PVP_RUNS"
DEFAULT_PVP_RUNS = 3
STATE = {"valid": 0, "setup_failed": 0}


def reset_launch_state():
    STATE.update({"valid": 0, "setup_failed": 0})


def pvp_runs():
    return int(os.environ.get(PVP_RUNS_VARIABLE) or DEFAULT_PVP_RUNS)


def read_character(game, handle):
    try:
        return game.get(handle, "charType", depth=0)
    except Exception as failure:
        return {"error": str(failure)[:100]}


def characters_in_play(host, client):
    client_body_on_host = None
    try:
        client_body_on_host = base.body_handle_by_name(host, CLIENT_BODY_NAME)
    except Exception:
        pass
    return {"client": read_character(client, "player"), "host": read_character(host, "player"),
            "clientBodyOnHost": None if client_body_on_host is None else read_character(host, client_body_on_host)}


def destroy(host, handle):
    try:
        host.set(handle, "health", 0)
    except Exception:
        pass


def fail_setup(category, message):
    STATE["setup_failed"] += 1
    crates.record_failure(category, message)
    raise crates.SetupFailure(category, message)


def copy_flags(game, handle):
    return {"cantHit": world.optional_get(game, handle, "cantHit"), "indestructible": world.optional_get(game, handle, "indestructible"),
            "bodyType": world.optional_get(game, handle, "rb.bodyType", nonpublic=True), "physicsActive": world.physics_active(game, handle)}


def premise_holds(host_flags, client_flags):
    return host_flags["cantHit"] is True and client_flags["cantHit"] is False


def prepare(host, client):
    if STATE["valid"] >= VALID_RUNS_WANTED:
        raise unittest.SkipTest("%d valid corpse runs already recorded in this launch" % STATE["valid"])
    if STATE["valid"] == 0 and STATE["setup_failed"] >= STOP_AFTER_SETUP_FAILURES:
        raise unittest.SkipTest("stopped: the first %d corpse attempts all failed setup; reasons %s" % (STATE["setup_failed"], dict(crates.STATE["reasons"])))
    base.empty_the_hand(client)
    characters = characters_in_play(host, client)
    if characters["client"] != DUNE:
        fail_setup("client-not-dune", "the client's own body has charType %s, not Dune (%d); host %s, client body on the host %s" % (
            characters["client"], DUNE, characters["host"], characters["clientBodyOnHost"]))
    if characters["host"] == DUNE:
        fail_setup("host-is-dune", "the host's own body is Dune too, so the mixed case is not set up (client body on the host %s)" % characters["clientBodyOnHost"])
    try:
        target = crates.spawn_object(host, client, CORPSE_ID, MIN_CORPSE_HEALTH)
    except crates.SetupFailure as failure:
        STATE["setup_failed"] += 1
        crates.record_failure(failure.category, str(failure))
        raise
    host_flags = copy_flags(host, target["handle"])
    client_flags = copy_flags(client, target["clientHandle"])
    if not premise_holds(host_flags, client_flags):
        destroy(host, target["handle"])
        fail_setup("premise-not-met", "the corpse flags are not host cantHit true and client cantHit false: host %s, client %s" % (host_flags, client_flags))
    target = dict(target, characters=characters, hostFlags=host_flags, clientFlags=client_flags)
    return {"position": target["position"], "name": None, "host": host, "hostHandle": target["handle"], "clientHandle": target["clientHandle"],
            "target": target, "measurements": []}


def before_swing(client, context, index, aim):
    extra = crates.before_swing(client, context, index, aim)
    if extra is None:
        return None
    extra["flags"] = {"host": copy_flags(context["host"], context["hostHandle"]), "client": copy_flags(client, context["clientHandle"])}
    return extra


def act(client, context):
    try:
        world.act(client, context, before_swing=before_swing)
    finally:
        destroy(context["host"], context["hostHandle"])


def outcome_of(entry):
    host_hit = entry["hostDelta"] > 0
    client_hit = entry["clientDelta"] > 0
    if host_hit and client_hit:
        return "both"
    if client_hit:
        return "client-only"
    if host_hit:
        return "host-only"
    return "neither"


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
    outcomes = [outcome_of(entry) for entry in entries]
    issues = regression.once_per_swing_issues(entries)
    if any(outcome != "both" for outcome in outcomes):
        issues.insert(0, "corpse damage per swing: %s" % outcomes)
    return issues


def preflight(fragments, attempts, builds=()):
    selected = base.matching_scenario_names(fragments)
    if CORPSE_NAME not in selected and PVP_NAME not in selected:
        return []
    checks = [
        (STOP_AFTER_SETUP_FAILURES < attempts or CORPSE_NAME not in selected, "the corpse setup early stop %d is not below the %d planned attempts" % (STOP_AFTER_SETUP_FAILURES, attempts)),
        (VALID_RUNS_WANTED <= attempts or CORPSE_NAME not in selected, "%d valid corpse runs are wanted but only %d attempts are planned" % (VALID_RUNS_WANTED, attempts)),
        (pvp_runs() >= 1, "the Dune PvP run count %d is below one" % pvp_runs()),
        (DUNE == 2, "the client character is not Dune (2)"),
    ]
    return [message for holds, message in checks if not holds]


def pvp_clone():
    clone = copy.copy(pvp_banded.SCENARIOS[0])
    clone.name = PVP_NAME
    clone.group = GROUP
    clone.max_repeat = pvp_runs()
    return clone


base.PREFLIGHTS.append(preflight)

SCENARIOS = [
    pvp_clone(),
    Scenario(CORPSE_NAME, "a Dune client hits a host-spawned world corpse bare handed five times with the client held 2.5 to 3.2 from it; the host is an Experiment, so cantHit is true on the host copy and false on the client copy; health, flags and physics of both copies per swing",
             prepare, act, lambda game, context: 0, hooks.never_changes, group=GROUP, check=check),
]

base.SCENARIOS.extend(SCENARIOS)
