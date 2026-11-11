import time

from casualtieslink.desync import Scenario

from . import desync_scenarios as base
from . import evidence_scenarios as evidence
from . import hook_scenarios as hooks
from . import regression_scenarios as regression
from . import spawned_crates as crates

GROUP = "hook-evidence"
NAME = "pvp_banded_by_client"
RUNS = 3
PUNCHES_PER_RUN = hooks.REGRESSION_SWINGS
PUNCH_LANDED_MINIMUM = 1.0
DRIFT_PAUSE_SECONDS = 0.4

# The unarmed cast starts at limbs[1] and is 4.5 long (Body.DoUnarmedAttack). Measured on crates, limbs[1] sits up to about 0.9 from the
# body centre, so a victim centre at most 3.2 away keeps the cast start within 4.2 of it, inside the 4.5 reach with the victim's own collider
# as margin. The bottom of the band keeps the punch from starting inside the victim. The punch to a limb is not shorter than the cast, so
# the crate band is used unchanged.
BAND_LOW = crates.BAND_LOW
BAND_HIGH = crates.BAND_HIGH
FAILURE_CATEGORY = "pvp-distance-band-unreachable"


def victim_position(game, handle):
    found = game.get(handle, base.BODY_PATH, depth=0)
    return {"x": float(found["x"]), "y": float(found["y"])}


def side_of_victim(client_position, victim):
    return 1 if client_position["x"] >= victim["x"] else -1


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


def act(client, context):
    host = context["host"]
    entries = []
    previous_after = None
    side = None
    for index in range(1, PUNCHES_PER_RUN + 1):
        victim = victim_position(host, context["hostVictim"])
        if side is None:
            side = side_of_victim(base.player_position(client), victim)
        band = crates.ensure_band(host, client, context["hostVictim"], victim, side=side)
        if not band["ok"]:
            context["bandFailure"] = {"swing": index, "distances": band["distances"]}
            break
        victim = victim_position(host, context["hostVictim"])
        victim_on_client = victim_position(client, context["clientVictim"])
        player = base.player_position(client)
        drift = idle_drift(host, context)
        geometry = {"clientPosition": player, "victimHostPosition": victim, "victimClientPosition": victim_on_client, "distance": round(base.distance(player, victim), 3),
                    "distanceToClientCopy": round(base.distance(player, victim_on_client), 3), "movedSincePreviousPunch": None if previous_after is None else round(base.distance(victim, previous_after), 3),
                    "idleDriftPerSecond": drift, "victimConscious": readable(host, context["hostVictim"], "conscious"), "side": side}
        marks = {which: len(evidence.read_log(which).splitlines()) for which in ("host", "client")}
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
    failure = context.get("bandFailure")
    if failure:
        message = "INVALID: the client could not be brought into the %.1f to %.1f band before punch %d (distances tried %s)" % (BAND_LOW, BAND_HIGH, failure["swing"], failure["distances"])
        crates.record_failure(FAILURE_CATEGORY, message)
        return [message]
    return regression.pvp_check(context)


SCENARIOS = [
    Scenario(NAME, "with the PVP rule on, the client is held 2.5 to 3.2 from the host's player before every punch and punches it five times; damage on host and client, once per punch, knockback, and the victim's idle limb drift per punch",
             regression.pvp_prepare, act, lambda game, context: 0, hooks.never_changes, group=GROUP, check=check, max_repeat=RUNS),
]

base.SCENARIOS.extend(SCENARIOS)
