import time
import unittest

from casualtieslink import positioncontrol
from casualtieslink.desync import Scenario

from . import corpse_banded as banded
from . import desync_scenarios as base
from . import hook_scenarios as hooks
from . import spawned_crates as crates
from . import world_building as world

GROUP = "corpse-repro"
NAME = "corpse_chain_by_client"
HOST_CHARACTER = 1
CLIENT_CHARACTER = 2
CORPSE_ID = "corpse"
MIN_CORPSE_HEALTH = 1.0
SWINGS = 25
SWING_POLL_SECONDS = 0.01
SEAT_DISTANCE = 2.5
MIN_PARKED_DISTANCE = 6.0
MAX_SWING_DISTANCE = 4.5
AFTER_LAST_SWING_SECONDS = 2.0
FACING_SETTLE_SECONDS = 0.5
SAMPLE_INTERVAL_SECONDS = 0.1
RETURN_TOLERANCE_FRACTION = 0.05
HEALTH_DROP_EPSILON = 0.5
PARK_DIRECTION = "left"
STATE = {"setup_failed": 0}


def reset_launch_state():
    STATE.update({"setup_failed": 0})


def fail_setup(category, message):
    STATE["setup_failed"] += 1
    crates.record_failure(category, message)
    raise crates.SetupFailure(category, message)


def read_health(game, handle):
    return world.optional_get(game, handle, "health")


def read_flag(game, handle):
    return world.optional_get(game, handle, "cantHit")


def corpse_point(host, context):
    return world.host_position(host, context["hostHandle"]) or context["position"]


def side_of(origin, point):
    return 1 if point["x"] >= origin["x"] else -1


def facing_record(client, corpse):
    player = base.player_position(client)
    look = crates.point_of(crates.optional_read(client, "targetLookPos"))
    is_right = crates.optional_read(client, "isRight")
    corpse_side = side_of(player, corpse)
    return {"clientPosition": player, "corpse": corpse, "isRight": is_right, "lookPosition": look, "corpseSide": corpse_side,
            "lookSide": None if look is None else side_of(player, look), "facingCorpse": is_right is (corpse_side > 0)}


def hold_rows(game):
    try:
        rows = game.call(positioncontrol.STATUS_COMMAND)
    except Exception as failure:
        return {"error": "%s: %s" % (type(failure).__name__, str(failure)[:120])}
    if not isinstance(rows, list):
        return {"error": "the hold status is not a list: %s" % str(rows)[:80]}
    return [{key: row.get(key) for key in ("target", "position", "drift", "maxDrift", "exceededTicks", "heldWithinTolerance", "lost", "tolerance")} for row in rows]


def hold_snapshot(host, client):
    return {"host": hold_rows(host), "client": hold_rows(client)}


def hold_problems(snapshots, entries):
    """Anything that makes the corpse result confounded: a hold that is missing, lost, over its tolerance or unreadable, or a swing that was not fired."""
    problems = []
    for moment, snapshot in snapshots.items():
        for which in ("host", "client"):
            rows = snapshot[which]
            if isinstance(rows, dict):
                problems.append("%s hold status at %s unreadable: %s" % (which, moment, rows["error"]))
                continue
            if not rows:
                problems.append("no %s hold at %s" % (which, moment))
            for row in rows:
                if row.get("lost") or row.get("heldWithinTolerance") is not True or (row.get("exceededTicks") or 0) > 0:
                    problems.append("%s hold at %s: held within tolerance %s, exceeded ticks %s, max drift %s, lost %s" % (
                        which, moment, row.get("heldWithinTolerance"), row.get("exceededTicks"), row.get("maxDrift"), row.get("lost")))
    unfired = [entry["swing"] for entry in entries if not entry.get("fired")]
    if unfired:
        problems.append("swings that did not fire: %s" % unfired)
    facing_away = [entry["swing"] for entry in entries if entry.get("facingCorpse") is False]
    if facing_away:
        problems.append("the client faced away from the corpse after swings %s" % facing_away)
    return problems


def point_mouse_at(client, corpse):
    """The game turns the body toward the mouse every frame, so the injected mouse has to sit on the corpse for the body to face it."""
    client.call("mouse", wx=corpse["x"], wy=corpse["y"])
    time.sleep(FACING_SETTLE_SECONDS)


def release_mouse_quietly(client):
    try:
        client.call("mouse", clear=True)
    except Exception:
        pass


def prepare(host, client):
    base.empty_the_hand(client)
    characters = banded.characters_in_play(host, client)
    if characters["clientBodyOnHost"] != CLIENT_CHARACTER:
        fail_setup("client-body-on-host-not-dune", "the client body on the host has charType %s, expected Dune (%d); host %s, client %s" % (
            characters["clientBodyOnHost"], CLIENT_CHARACTER, characters["host"], characters["client"]))
    if characters["host"] != HOST_CHARACTER or characters["client"] != CLIENT_CHARACTER:
        fail_setup("characters-not-set", "expected host Milky (%d) and client Dune (%d), got host %s and client %s" % (HOST_CHARACTER, CLIENT_CHARACTER, characters["host"], characters["client"]))
    start = positioncontrol.start_positions(host, client)
    try:
        target = crates.spawn_object(host, client, CORPSE_ID, MIN_CORPSE_HEALTH)
    except crates.SetupFailure as failure:
        STATE["setup_failed"] += 1
        crates.record_failure(failure.category, str(failure))
        raise
    corpse = target["position"]
    seat = positioncontrol.seat_pair(host, client, {"x": corpse["x"] - SEAT_DISTANCE, "y": corpse["y"]}, PARK_DIRECTION,
                                      parked_policy=positioncontrol.PARKED_RECORDED)
    target = dict(target, characters=characters, hostFlags=banded.copy_flags(host, target["handle"]), clientFlags=banded.copy_flags(client, target["clientHandle"]), startPositions=start,
                  positionControl=seat)
    return {"position": corpse, "name": None, "host": host, "hostHandle": target["handle"], "clientHandle": target["clientHandle"], "target": target, "measurements": [], "samples": []}


def record_swing(index, started, fired, before, after, context, client, fired_at=None):
    host = context["host"]
    return {"swing": index, "t": round((time.time() if fired_at is None else fired_at) - started, 3), "fired": fired, "hostHp": [before["host"], after["host"]], "clientHp": [before["client"], after["client"]],
            "hostCantHit": read_flag(host, context["hostHandle"]), "clientCantHit": read_flag(client, context["clientHandle"])}


def read_both(client, context):
    return {"host": read_health(context["host"], context["hostHandle"]), "client": read_health(client, context["clientHandle"])}


def sample_after(client, context, started, seconds):
    samples = []
    deadline = time.time() + seconds
    while time.time() < deadline:
        samples.append({"t": round(time.time() - started, 3), **read_both(client, context),
                        "hostCantHit": read_flag(context["host"], context["hostHandle"]), "clientCantHit": read_flag(client, context["clientHandle"])})
        time.sleep(SAMPLE_INTERVAL_SECONDS)
    return samples


def act(client, context):
    host = context["host"]
    target = context["target"]
    try:
        if not target["positionControl"]["ok"]:
            context["positionFailure"] = target["positionControl"]
            return
        corpse = corpse_point(host, context)
        point_mouse_at(client, corpse)
        target["facingBefore"] = facing_record(client, corpse)
        if not target["facingBefore"]["facingCorpse"]:
            context["facingBeforeFailure"] = target["facingBefore"]
            return
        distance = base.distance(base.player_position(client), corpse)
        target["swingDistance"] = round(distance, 3)
        if distance > MAX_SWING_DISTANCE:
            context["positionFailure"] = {"ok": False, "issues": ["the client is %.2f from the corpse, beyond %.1f" % (distance, MAX_SWING_DISTANCE)]}
            return
        started = time.time()
        entries = context["measurements"]
        snapshots = target["holds"] = {"beforeFirstSwing": hold_snapshot(host, client)}
        before = read_both(client, context)
        previous_fired_at = None
        parked_paths = target["positionControl"]["parkedHost"]["paths"]
        for index in range(1, SWINGS + 1):
            attempts = {"ignored": 0}
            fired = hooks.fire_one_swing(client, corpse_point(host, context), pause=SWING_POLL_SECONDS, attempts=attempts)
            fired_at = time.time()
            after = read_both(client, context)
            entries.append(record_swing(index, started, fired, before, after, context, client, fired_at))
            entries[-1]["ignoredAttempts"] = attempts["ignored"]
            entries[-1]["parkedHost"] = positioncontrol.parked_snapshot(host, parked_paths)
            entries[-1]["intervalSincePrevious"] = None if previous_fired_at is None else round(fired_at - previous_fired_at, 3)
            previous_fired_at = fired_at
            before = after
            facing = facing_record(client, corpse_point(host, context))
            entries[-1]["facingCorpse"] = facing["facingCorpse"]
            if index == 1:
                target["facingAfterFirstSwing"] = facing
            if not facing["facingCorpse"]:
                target["reaimedAfterSwing"] = target.get("reaimedAfterSwing", []) + [index]
                point_mouse_at(client, corpse_point(host, context))
        target["swingRate"] = swing_rate(entries)
        snapshots["afterLastSwing"] = hold_snapshot(host, client)
        context["samples"] = sample_after(client, context, started, AFTER_LAST_SWING_SECONDS)
        target["samples"] = context["samples"]
        snapshots["end"] = hold_snapshot(host, client)
        prediction = evaluate(entries, context["samples"], target["hostFlags"], target["clientFlags"])
        problems = hold_problems(snapshots, entries) + parked_problems(target, entries, target["positionControl"]["clientTarget"], corpse)
        target["holdProblems"] = problems
        if problems:
            prediction = dict(prediction, ifRead=prediction["verdict"], verdict="confounded: the corpse result is not read against the prediction", confoundedBy=problems)
        target["prediction"] = prediction
    finally:
        banded.destroy(host, context["hostHandle"])
        release_mouse_quietly(client)
        positioncontrol.release_quietly(client)
        positioncontrol.release_quietly(host)


def swing_rate(entries):
    intervals = sorted(entry["intervalSincePrevious"] for entry in entries if entry.get("intervalSincePrevious") is not None)
    if not intervals:
        return {"intervals": 0}
    return {"intervals": len(intervals), "minSeconds": intervals[0], "medianSeconds": intervals[len(intervals) // 2], "maxSeconds": intervals[-1],
            "ignoredAttemptsTotal": sum(entry.get("ignoredAttempts") or 0 for entry in entries)}


def parked_problems(target, entries, client_point, corpse):
    """The parked host is not held strictly, so what matters for the swing is that it never comes closer than MIN_PARKED_DISTANCE to the client or the corpse, by the nearest of
    its position reads. Anything closer, or nothing readable, labels the corpse result confounded."""
    parked = target["positionControl"]["parkedHost"]
    moments = [("preflight read %d" % number, snapshot) for number, snapshot in enumerate(parked["observations"], 1)] + [("after preflight", parked["afterPreflight"])]
    moments += [("swing %d" % entry["swing"], entry.get("parkedHost")) for entry in entries]
    closest = []
    problems = []
    for moment, snapshot in moments:
        approach = positioncontrol.closest_approach(snapshot, [client_point, corpse]) if snapshot else None
        closest.append({"moment": moment, "closest": approach})
        if approach is None:
            problems.append("no readable parked host position at %s" % moment)
        elif approach["distance"] < MIN_PARKED_DISTANCE:
            problems.append("the parked host was %.2f from the client or the corpse at %s (by %s), below %.1f" % (approach["distance"], moment, approach["source"], MIN_PARKED_DISTANCE))
    readable = [item["closest"]["distance"] for item in closest if item["closest"]]
    target["parkedDistances"] = {"minimumAllowed": MIN_PARKED_DISTANCE, "smallestSeen": min(readable, default=None), "perMoment": closest}
    return problems


def start_health(entries, which):
    for entry in entries:
        value = entry["hostHp" if which == "host" else "clientHp"][0]
        if isinstance(value, (int, float)):
            return float(value)
    return None


def evaluate(entries, samples, host_flags, client_flags):
    """The Together session's prediction: the host copy never loses health and keeps cantHit true; the client copy goes below zero and comes back."""
    readings = [(entry["hostHp"], entry["clientHp"]) for entry in entries]
    host_values = [v for pair in readings for v in pair[0] if isinstance(v, (int, float))] + [s["host"] for s in samples if isinstance(s["host"], (int, float))]
    client_values = [v for pair in readings for v in pair[1] if isinstance(v, (int, float))] + [s["client"] for s in samples if isinstance(s["client"], (int, float))]
    host_start, client_start = start_health(entries, "host"), start_health(entries, "client")
    host_cant_hit = [host_flags.get("cantHit")] + [entry["hostCantHit"] for entry in entries] + [s["hostCantHit"] for s in samples]
    last_client = next((s["client"] for s in reversed(samples) if isinstance(s["client"], (int, float))), None)
    summary = {"hostStartHp": host_start, "clientStartHp": client_start, "hostMinHp": min(host_values, default=None), "clientMinHp": min(client_values, default=None),
               "hostEverCantHitFalse": any(flag is False for flag in host_cant_hit), "clientFinalHp": last_client,
               "clientReadingsBelowZero": len([v for v in client_values if v < 0]), "clientCantHitFalseThroughout": all(flag is False for flag in [client_flags.get("cantHit")] + [entry["clientCantHit"] for entry in entries])}
    reasons = []
    if host_start is not None and summary["hostMinHp"] is not None and summary["hostMinHp"] < host_start - HEALTH_DROP_EPSILON:
        reasons.append("the host copy's health fell from %.1f to %.1f" % (host_start, summary["hostMinHp"]))
    if summary["hostEverCantHitFalse"]:
        reasons.append("the host copy's cantHit was false at some reading")
    if summary["clientMinHp"] is None or summary["clientMinHp"] >= 0:
        reasons.append("the client copy never dropped below 0 (minimum %s)" % summary["clientMinHp"])
    summary["clientReturned"] = bool(client_start is not None and last_client is not None and abs(last_client - client_start) <= abs(client_start) * RETURN_TOLERANCE_FRACTION)
    summary["refutedBy"] = reasons
    summary["verdict"] = "prediction holds" if not reasons else "prediction refuted"
    return summary


def check(context):
    for key, label in (("positionFailure", "the position preflight failed"), ("facingBeforeFailure", "the client does not face the corpse before the first swing")):
        failure = context.get(key)
        if failure:
            STATE["setup_failed"] += 1
            detail = "; ".join(failure.get("issues", [])) if "issues" in failure else "isRight %s, corpse side %s, look side %s" % (failure.get("isRight"), failure.get("corpseSide"), failure.get("lookSide"))
            message = "INVALID: %s: %s" % (label, detail)
            crates.record_failure(key, message)
            return [message]
    if not context.get("measurements"):
        return ["INVALID: no swing recorded"]
    return []


def preflight(fragments, attempts, builds=()):
    if NAME not in base.matching_scenario_names(fragments):
        return []
    checks = [(SWINGS >= 1, "the swing count is below one"), (SWING_POLL_SECONDS > 0, "the swing poll interval is not positive"), (SEAT_DISTANCE < MAX_SWING_DISTANCE, "the seat distance is not inside the swing reach"),
              (HOST_CHARACTER != CLIENT_CHARACTER, "host and client are the same character"), (AFTER_LAST_SWING_SECONDS >= 1.0, "the logging after the last swing is below one second")]
    return [message for holds, message in checks if not holds]


base.PREFLIGHTS.append(preflight)

SCENARIOS = [
    Scenario(NAME, "host Milky and client Dune, both held; the host spawns a world corpse next to the client, the client faces it and swings bare handed 25 times, each as soon as the attack cooldown allows (a player's rate); health and cantHit of both copies per swing and every 0.1 s for two seconds after the last swing, against the Together session's prediction",
             prepare, act, lambda game, context: 0, hooks.never_changes, group=GROUP, check=check, max_repeat=1),
]

base.SCENARIOS.extend(SCENARIOS)
