import time
import unittest

from casualtieslink import positioncontrol
from casualtieslink.desync import Scenario

from . import desync_scenarios as base
from . import evidence_scenarios as evidence
from . import hook_scenarios as hooks
from . import regression_scenarios as regression
from . import spawned_crates as crates

GROUP = "hook-evidence"
NAME = "pvp_banded_by_client"
RUNS = 6
VALID_RUNS_WANTED = 3
STATE = {"valid": 0}
PUNCHES_PER_RUN = hooks.REGRESSION_SWINGS
PUNCH_LANDED_MINIMUM = 1.0
DRIFT_PAUSE_SECONDS = 0.4

# The unarmed cast starts at limbs[1] and is 4.5 long (Body.DoUnarmedAttack). Measured on crates, limbs[1] sits up to about 0.9 from the
# body centre, so a victim centre at most 3.2 away keeps the cast start within 4.2 of it, inside the 4.5 reach with the victim's own collider
# as margin. The bottom of the band keeps the punch from starting inside the victim. The punch to a limb is not shorter than the cast, so
# the crate band is used unchanged.
BAND_LOW = 2.5
BAND_HIGH = 3.2
FAILURE_CATEGORY = "pvp-distance-band-unreachable"
POSITION_FAILURE_CATEGORY = "pvp-position-preflight-failed"
RESTORE_FAILURE_CATEGORY = "pvp-victim-not-restored"
RESTORE_TOLERANCE = 1.0
RESTORE_SETTLE_SECONDS = 1.0
RESTORE_SYNC_SECONDS = 4.0
RESTORE_POLL_SECONDS = 0.5
LIMB_SCAN_LIMIT = 30
FULL_HEALTH = {"limbs": None, "total": None, "clientTotal": None}


def reset_launch_state():
    FULL_HEALTH.update({"limbs": None, "total": None, "clientTotal": None})
    STATE["valid"] = 0


def victim_position(game, handle):
    found = game.get(handle, base.BODY_PATH, depth=0)
    return {"x": float(found["x"]), "y": float(found["y"])}


def side_of_victim(client_position, victim):
    return 1 if client_position["x"] >= victim["x"] else -1


def read_limb_values(game, handle):
    values = []
    for index in range(LIMB_SCAN_LIMIT):
        try:
            values.append((float(game.get(handle, "limbs[%d].skinHealth" % index, depth=0)), float(game.get(handle, "limbs[%d].muscleHealth" % index, depth=0))))
        except Exception:
            break
    return values


def restore_victim(host, client, context):
    handle = context["hostVictim"]
    if FULL_HEALTH["limbs"] is None:
        FULL_HEALTH["limbs"] = read_limb_values(host, handle)
        FULL_HEALTH["total"] = hooks.limb_total(host, handle)
        FULL_HEALTH["clientTotal"] = hooks.limb_total(client, context["clientVictim"])
        return {"restored": False, "firstRun": True, "fullTotal": FULL_HEALTH["total"], "fullClientTotal": FULL_HEALTH["clientTotal"], "hostTotal": FULL_HEALTH["total"], "clientTotal": FULL_HEALTH["clientTotal"]}
    before = hooks.limb_total(host, handle)
    for index, (skin, muscle) in enumerate(FULL_HEALTH["limbs"]):
        host.set(handle, "limbs[%d].skinHealth" % index, skin)
        host.set(handle, "limbs[%d].muscleHealth" % index, muscle)
    time.sleep(RESTORE_SETTLE_SECONDS)
    deadline = time.time() + RESTORE_SYNC_SECONDS
    host_total = hooks.limb_total(host, handle)
    client_total = hooks.limb_total(client, context["clientVictim"])
    while time.time() < deadline and abs(client_total - FULL_HEALTH["clientTotal"]) > RESTORE_TOLERANCE:
        time.sleep(RESTORE_POLL_SECONDS)
        host_total = hooks.limb_total(host, handle)
        client_total = hooks.limb_total(client, context["clientVictim"])
    return {"restored": True, "firstRun": False, "fullTotal": FULL_HEALTH["total"], "fullClientTotal": FULL_HEALTH["clientTotal"], "hostTotalBefore": before, "hostTotal": host_total,
            "clientTotal": client_total, "ok": abs(host_total - FULL_HEALTH["total"]) <= RESTORE_TOLERANCE and abs(client_total - FULL_HEALTH["clientTotal"]) <= RESTORE_TOLERANCE}


def prepare(host, client):
    if STATE["valid"] >= VALID_RUNS_WANTED:
        raise unittest.SkipTest("%d valid PvP runs already recorded in this launch" % STATE["valid"])
    context = regression.pvp_prepare(host, client)
    restore = restore_victim(host, client, context)
    context["target"] = {"pvpRule": context.get("pvpRule"), "victimRestore": restore}
    if restore.get("restored") and not restore["ok"]:
        context["restoreFailure"] = restore
    return context


def idle_drift(host, context):
    first = hooks.limb_total(host, context["hostVictim"])
    time.sleep(DRIFT_PAUSE_SECONDS)
    second = hooks.limb_total(host, context["hostVictim"])
    return round((second - first) / DRIFT_PAUSE_SECONDS, 3)


def readable(game, handle, path):
    try:
        return game.get(handle, path, depth=0)
    except Exception as failure:
        return {"error": str(failure)[:100]}


def victim_copy_state(client, context):
    return {"victimOnClient": crates.crate_physics(client, context["clientVictim"])}


def record_start(host, client, context):
    context["startPositions"] = positioncontrol.start_positions(host, client, copy_state=lambda: victim_copy_state(client, context))


PATHS = {"victim": [], "client": []}


def seat_victim(host, spot):
    """The victim goes back to the same spot and is held there until just before the punch, so every punch starts from the same geometry. The victim takes part in the
    punch, so it is verified by the holder's view and rb.position, never by distance."""
    return positioncontrol.seat_swinging_body(host, spot, paths=PATHS["victim"])


def preflight(host, client, spot, band):
    return positioncontrol.preflight_views(host, client, spot, band.get("seat") or base.player_position(client), positioncontrol.ROLE_SWINGING, PATHS["victim"], PATHS["client"])


def release_holds(host, client):
    positioncontrol.release_quietly(client)
    positioncontrol.release_quietly(host)


def act(client, context, accept_range=None):
    host = context["host"]
    entries = []
    context["measurements"] = entries
    if context.get("restoreFailure"):
        return
    try:
        run_punches(host, client, context, entries, accept_range)
    finally:
        release_holds(host, client)


def run_punches(host, client, context, entries, accept_range):
    PATHS["victim"] = positioncontrol.discover_diagnostic_paths(host)
    PATHS["client"] = positioncontrol.discover_diagnostic_paths(client)
    spot = None
    previous_after = None
    side = None
    for index in range(1, PUNCHES_PER_RUN + 1):
        victim = victim_position(host, context["hostVictim"])
        moved_before_seat = None if previous_after is None else round(base.distance(victim, previous_after), 3)
        if spot is None:
            spot = victim
            record_start(host, client, context)
        victim_hold = seat_victim(host, spot)
        if not victim_hold["ok"]:
            context["positionFailure"] = {"ok": False, "issues": ["the victim hold did not verify before punch %d: %s; link reads %s" % (index, "; ".join(victim_hold.get("issues") or ["no detail"]), victim_hold["drifts"])]}
            break
        victim = spot
        if side is None:
            side = side_of_victim(base.player_position(client), victim)
        band = crates.ensure_band(host, client, context["hostVictim"], victim, side=side)
        if not band["ok"] and accept_range and accept_range[0] <= band["distances"][-1] <= accept_range[1]:
            band["acceptedOutsideBand"] = band["distances"][-1]
            band["ok"] = True
        if not band["ok"]:
            context["bandFailure"] = {"swing": index, "distances": band["distances"]}
            break
        if index == 1:
            context["positionControl"] = preflight(host, client, spot, band)
            if not context["positionControl"]["ok"]:
                context["positionFailure"] = context["positionControl"]
                break
        victim = victim_position(host, context["hostVictim"])
        victim_on_client = victim_position(client, context["clientVictim"])
        player = base.player_position(client)
        drift = idle_drift(host, context)
        geometry = {"clientPosition": player, "victimHostPosition": victim, "victimClientPosition": victim_on_client, "distance": round(base.distance(player, victim), 3),
                    "distanceToClientCopy": round(base.distance(player, victim_on_client), 3), "movedSincePreviousPunch": moved_before_seat,
                    "idleDriftPerSecond": drift, "victimConscious": readable(host, context["hostVictim"], "conscious"), "side": side}
        limb = crates.point_of(crates.optional_read(client, "limbs[1].transform.position"))
        geometry["limb1Position"] = limb
        geometry["limb1ToBodyDistance"] = None if limb is None else round(base.distance(limb, victim_on_client), 3)
        geometry["aimIsBodyCentre"] = True
        marks = {which: len(evidence.read_log(which).splitlines()) for which in ("host", "client")}
        positioncontrol.release_quietly(host)
        before = (hooks.limb_total(host, context["hostVictim"]), hooks.limb_total(client, context["clientVictim"]), round(float(host.get(context["hostVictim"], base.BODY_PATH, depth=0)["x"]), 3))
        fired = hooks.fire_one_swing(client, victim_on_client)
        time.sleep(hooks.SETTLE_AFTER_SWING_SECONDS)
        after = (hooks.limb_total(host, context["hostVictim"]), hooks.limb_total(client, context["clientVictim"]), round(float(host.get(context["hostVictim"], base.BODY_PATH, depth=0)["x"]), 3))
        lines = {which: evidence.new_lines(marks[which], evidence.read_log(which)) for which in ("host", "client")}
        previous_after = victim_position(host, context["hostVictim"])
        entries.append({"swing": index, "fired": fired, "host": [before[0], after[0]], "client": [before[1], after[1]], "extra": [before[2], after[2]],
                        "hostDelta": round(before[0] - after[0], 3), "clientDelta": round(before[1] - after[1], 3), "band": band, "geometry": geometry,
                        "hostHookCalls": evidence.hook_call_lines(lines["host"]), "clientHookCalls": evidence.hook_call_lines(lines["client"]),
                        "hostLines": evidence.evidence_lines(lines["host"]), "clientLines": evidence.evidence_lines(lines["client"]),
                        "hostExceptions": evidence.exception_lines(lines["host"]), "clientExceptions": evidence.exception_lines(lines["client"])})
        if not fired:
            break
    context["measurements"] = entries


def check(context):
    position_failure = context.get("positionFailure")
    if position_failure:
        message = "INVALID: the position preflight failed: %s" % "; ".join(position_failure["issues"])
        crates.record_failure(POSITION_FAILURE_CATEGORY, message)
        return [message]
    lost = context.get("restoreFailure")
    if lost:
        message = "INVALID: the victim's limbs could not be restored before the run (full host %.2f, host %.2f; full client %.2f, client %.2f)" % (
            lost["fullTotal"], lost["hostTotal"], lost["fullClientTotal"], lost["clientTotal"])
        crates.record_failure(RESTORE_FAILURE_CATEGORY, message)
        return [message]
    failure = context.get("bandFailure")
    if failure:
        message = "INVALID: the client could not be brought into the %.1f to %.1f band before punch %d (distances tried %s)" % (BAND_LOW, BAND_HIGH, failure["swing"], failure["distances"])
        crates.record_failure(FAILURE_CATEGORY, message)
        return [message]
    if len(context.get("measurements") or []) >= PUNCHES_PER_RUN:
        STATE["valid"] += 1
    return regression.pvp_check(context)


SCENARIOS = [
    Scenario(NAME, "with the PVP rule on, the client is held 2.5 to 3.2 from the host's player before every punch and punches it five times; damage on host and client, once per punch, knockback, and the victim's idle limb drift per punch",
             prepare, act, lambda game, context: 0, hooks.never_changes, group=GROUP, check=check, max_repeat=RUNS),
]

base.SCENARIOS.extend(SCENARIOS)
