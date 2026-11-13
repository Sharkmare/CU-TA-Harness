import threading
import time
import unittest

from casualtieslink import positioncontrol, swinggate
from casualtieslink.desync import Scenario

from scenarios import corpse_banded as banded
from scenarios import desync_scenarios as base
from scenarios import hook_scenarios as hooks
from scenarios import spawned_crates as crates
from scenarios import world_building as world

GROUP = "corpse-repro"
NAME = "corpse_chain_by_client"
HOST_CHARACTER = 1
CLIENT_CHARACTER = 2
CHARACTER_NAMES = {0: "Experiment", 1: "Milky", 2: "Dune"}
CONTROLS = (("corpse_chain_dune_dune_by_client", "corpse-control-dune", 2, 2), ("corpse_chain_milky_milky_by_client", "corpse-control-milky", 1, 1),
            ("corpse_chain_dune_milky_by_client", "corpse-control-dune-milky", 2, 1))
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
SAMPLER_JOIN_SECONDS = 5.0
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
    """Anything that makes the corpse result confounded: a hold that is missing, lost, over its tolerance or unreadable, or a swing that was not fired. The parked host takes no part in the swing, so its drift is not judged here, only that its hold exists and is not lost; how close it stays is judged by parked_problems."""
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
                if which == "host" and not row.get("lost"):
                    continue
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


def point_mouse_at(client, corpse, settle=FACING_SETTLE_SECONDS):
    """The game turns the body toward the mouse every frame, so the injected mouse has to sit on the corpse for the body to face it."""
    client.call("mouse", wx=corpse["x"], wy=corpse["y"])
    if settle:
        time.sleep(settle)


def release_mouse_quietly(client):
    try:
        client.call("mouse", clear=True)
    except Exception:
        pass


def start_swing_gate(host, client, context, target):
    """The gate before the first swing: seat by holder and rb.position, limbs settled and in reach, facing, cooldown, corpse present, distance and the parked host out of the swing box. The swings that follow are
    sampled and judged by the sampler (facing, parked distance), not gated one by one, because a gate read per swing would slow the chain below a player's rate."""
    parked = target["positionControl"]["parkedHost"]
    gate = swinggate.Gate({"seat": target["positionControl"]["clientTarget"], "band": (SEAT_DISTANCE - 0.6, MAX_SWING_DISTANCE)}, crates.target_reader(host, client, context),
                          client_paths=context.get("clientPaths") or positioncontrol.discover_diagnostic_paths(client), parked_game=host, parked_paths=parked["paths"])
    settle = gate.settle(client)
    target["limbSettle"] = settle
    if not settle["ok"]:
        return {"swing": 1, "failures": [{"gate": "limb", "detail": "limbs did not settle within %.0f s" % swinggate.SETTLE_TIMEOUT_SECONDS}], "values": {}}
    verdict = gate.check(client)
    target["startGate"] = verdict
    if not verdict["passed"]:
        return dict(verdict, swing=1)
    return None


def prepare_for(host_character, client_character):
    """The scenario setup for one pair of characters: the characters are verified before anything is spawned."""
    host_name, client_name = CHARACTER_NAMES[host_character], CHARACTER_NAMES[client_character]

    def prepare_pair(host, client):
        return prepare_with(host, client, host_character, client_character, host_name, client_name)

    return prepare_pair


def prepare(host, client):
    return prepare_with(host, client, HOST_CHARACTER, CLIENT_CHARACTER, CHARACTER_NAMES[HOST_CHARACTER], CHARACTER_NAMES[CLIENT_CHARACTER])


def prepare_with(host, client, host_character, client_character, host_name, client_name):
    base.empty_the_hand(client)
    characters = banded.characters_in_play(host, client)
    if characters["clientBodyOnHost"] != client_character:
        fail_setup("client-body-on-host-wrong-character", "the client body on the host has charType %s, expected %s (%d); host %s, client %s" % (
            characters["clientBodyOnHost"], client_name, client_character, characters["host"], characters["client"]))
    if characters["host"] != host_character or characters["client"] != client_character:
        fail_setup("characters-not-set", "expected host %s (%d) and client %s (%d), got host %s and client %s" % (host_name, host_character, client_name, client_character, characters["host"], characters["client"]))
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


class Sampler:
    """Reads the corpse copies, the facing and the parked host on its own thread, so the swing loop only fires swings and the swing rate stays the cooldown's rate."""

    def __init__(self, client, context, parked_paths):
        self.client = client
        self.context = context
        self.parked_paths = parked_paths
        self.samples = []
        self.light = False
        self.failures = 0
        self.stop_event = threading.Event()
        self.thread = None

    def sample_once(self):
        host = self.context["host"]
        reading = {"host": read_health(host, self.context["hostHandle"]), "client": read_health(self.client, self.context["clientHandle"]),
                   "hostCantHit": read_flag(host, self.context["hostHandle"]), "clientCantHit": read_flag(self.client, self.context["clientHandle"])}
        reading["at"] = time.time()
        if not self.light:
            reading["isRight"] = crates.optional_read(self.client, "isRight")
            reading["parked"] = positioncontrol.parked_snapshot(host, self.parked_paths)
        self.samples.append(reading)

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.sample_once()
            except Exception:
                self.failures += 1
                time.sleep(SAMPLE_INTERVAL_SECONDS)

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=SAMPLER_JOIN_SECONDS)

    def latest_full(self):
        return next((reading for reading in reversed(self.samples) if "isRight" in reading), None)


def make_sampler(client, context, parked_paths):
    return Sampler(client, context, parked_paths)


def build_entries(marks, samples, started, corpse_is_right):
    """One entry per swing from the sampler's readings: the health before is the last reading before the swing, the health after is the first reading at or after it."""
    entries = []
    for mark in marks:
        fired_at = mark["firedAt"]
        before = next((reading for reading in reversed(samples) if reading["at"] < fired_at), None)
        after = next((reading for reading in samples if reading["at"] >= fired_at), None)
        before = before or after or samples[-1]
        after = after or samples[-1]
        full = next((reading for reading in samples if reading["at"] >= fired_at and "isRight" in reading), None)
        entries.append({"swing": mark["swing"], "t": round(fired_at - started, 3), "fired": mark["fired"], "hostHp": [before["host"], after["host"]], "clientHp": [before["client"], after["client"]],
                        "hostCantHit": after["hostCantHit"], "clientCantHit": after["clientCantHit"], "ignoredAttempts": mark["ignoredAttempts"], "intervalSincePrevious": mark["interval"],
                        "sampleLagSeconds": round(after["at"] - fired_at, 3), "isRight": None if full is None else full["isRight"],
                        "facingCorpse": None if full is None else full["isRight"] is corpse_is_right, "parkedHost": None if full is None else full["parked"]})
    return entries


def sampling_summary(samples, sampler):
    gaps = sorted(round(later["at"] - earlier["at"], 3) for earlier, later in zip(samples, samples[1:]))
    return {"samples": len(samples), "fullSamples": len([reading for reading in samples if "isRight" in reading]), "failures": sampler.failures,
            "medianGapSeconds": gaps[len(gaps) // 2] if gaps else None, "maxGapSeconds": gaps[-1] if gaps else None}


def act(client, context):
    host = context["host"]
    target = context["target"]
    sampler = None
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
        corpse_is_right = side_of(target["positionControl"]["clientTarget"], corpse) > 0
        start_gate = start_swing_gate(host, client, context, target)
        if start_gate is not None:
            context["gateFailure"] = start_gate
            return
        snapshots = target["holds"] = {"beforeFirstSwing": hold_snapshot(host, client)}
        sampler = make_sampler(client, context, target["positionControl"]["parkedHost"]["paths"])
        sampler.start()
        started = time.time()
        marks = []
        previous_fired_at = None
        for index in range(1, SWINGS + 1):
            attempts = {"ignored": 0}
            fired = hooks.fire_one_swing(client, corpse, pause=SWING_POLL_SECONDS, attempts=attempts)
            fired_at = time.time()
            marks.append({"swing": index, "firedAt": fired_at, "fired": fired, "ignoredAttempts": attempts["ignored"], "interval": None if previous_fired_at is None else round(fired_at - previous_fired_at, 3)})
            previous_fired_at = fired_at
            latest = sampler.latest_full()
            if latest is not None and latest["isRight"] is not corpse_is_right:
                target["reaimedAfterSwing"] = target.get("reaimedAfterSwing", []) + [index]
                point_mouse_at(client, corpse, settle=0.0)
        sampler.light = True
        deadline = time.time() + AFTER_LAST_SWING_SECONDS
        while time.time() < deadline:
            time.sleep(SAMPLE_INTERVAL_SECONDS)
        sampler.stop()
        samples = list(sampler.samples)
        entries = context["measurements"]
        entries.extend(build_entries(marks, samples, started, corpse_is_right))
        target["facingAfterFirstSwing"] = {"isRight": entries[0]["isRight"], "corpseIsRight": corpse_is_right, "facingCorpse": entries[0]["facingCorpse"]}
        target["swingRate"] = swing_rate(entries)
        target["sampling"] = sampling_summary(samples, sampler)
        snapshots["afterLastSwing"] = hold_snapshot(host, client)
        context["samples"] = [{"t": round(reading["at"] - started, 3), "host": reading["host"], "client": reading["client"], "hostCantHit": reading["hostCantHit"], "clientCantHit": reading["clientCantHit"]}
                              for reading in samples if reading["at"] > marks[-1]["firedAt"]]
        target["samples"] = context["samples"]
        snapshots["end"] = hold_snapshot(host, client)
        prediction = evaluate(entries, context["samples"], target["hostFlags"], target["clientFlags"])
        problems = hold_problems(snapshots, entries) + parked_problems(target, samples, target["positionControl"]["clientTarget"], corpse)
        target["holdProblems"] = problems
        if problems:
            prediction = dict(prediction, ifRead=prediction["verdict"], verdict="confounded: the corpse result is not read against the prediction", confoundedBy=problems)
        target["prediction"] = prediction
    finally:
        if sampler is not None:
            sampler.stop()
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


def parked_problems(target, samples, client_point, corpse):
    """The parked host is not held strictly, so what matters for the swing is that it never comes closer than MIN_PARKED_DISTANCE to the client or the corpse, by the nearest of
    its position reads, at the preflight and at every sampler reading during the chain. Anything closer, or nothing readable, labels the corpse result confounded."""
    parked = target["positionControl"]["parkedHost"]
    moments = [("preflight read %d" % number, snapshot) for number, snapshot in enumerate(parked["observations"], 1)] + [("after preflight", parked["afterPreflight"])]
    moments += [("sample %d" % number, reading.get("parked")) for number, reading in enumerate(samples, 1) if "isRight" in reading]
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
    gate_failure = context.get("gateFailure")
    if gate_failure:
        STATE["setup_failed"] += 1
        message = "INVALID: swing 1 not fired, %s: %s" % (swinggate.gate_reason(gate_failure), gate_failure["failures"][0]["detail"])
        crates.record_failure("swing-gate", message)
        return [message]
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
    if not set(base.matching_scenario_names(fragments)) & ({NAME} | {name for name, *_ in CONTROLS}):
        return []
    checks = [(SWINGS >= 1, "the swing count is below one"), (SWING_POLL_SECONDS > 0, "the swing poll interval is not positive"), (SEAT_DISTANCE < MAX_SWING_DISTANCE, "the seat distance is not inside the swing reach"),
              (HOST_CHARACTER != CLIENT_CHARACTER, "host and client are the same character"), (AFTER_LAST_SWING_SECONDS >= 1.0, "the logging after the last swing is below one second")]
    return [message for holds, message in checks if not holds]


base.PREFLIGHTS.append(preflight)

SCENARIOS = [
    Scenario(NAME, "host Milky and client Dune, both held; the host spawns a world corpse next to the client, the client faces it and swings bare handed 25 times, each as soon as the attack cooldown allows (a player's rate); health and cantHit of both copies per swing and every 0.1 s for two seconds after the last swing, against the Together session's prediction",
             prepare, act, lambda game, context: 0, hooks.never_changes, group=GROUP, check=check, max_repeat=1),
]

SCENARIOS += [
    Scenario(name, "control: host %s and client %s, otherwise the same run as the mixed pair: both held; the host spawns a world corpse next to the client, the client faces it and swings bare handed 25 times, each as soon as the attack cooldown allows; health and cantHit of both copies per swing and every 0.1 s for two seconds after the last swing" % (
        CHARACTER_NAMES[host_character], CHARACTER_NAMES[client_character]), prepare_for(host_character, client_character), act, lambda game, context: 0, hooks.never_changes, group=group, check=check, max_repeat=1)
    for name, group, host_character, client_character in CONTROLS
]

base.SCENARIOS.extend(SCENARIOS)
