"""Wood block mining by a Dune (or Experiment) client on a Milky host: does the broken block come back on the client?

The test is block persistence, not swing landing. A run is judged in three steps:
  INVALID    a setup gate failed (client not seated and held, host not parked by distance, wrong characters, block not placed on both games, the proxy delay not observed), a swing was
             fired that did not damage the client's block, or the client never broke the block. Nothing is concluded from an invalid run.
  REVERSION  the client's copy of the cell held a block again after it had been empty (the host's copy is judged and recorded separately).
  persisted  the client broke the block and the cell stayed empty on both games until the end of the tail.

The swing loop only fires: each call waits for the attack cooldown and invokes Body.UseItemInHand the moment it is ready (the corpse chain's driver), so the swing spacing is the game's
cooldown and not the link's read time. Every read happens on the series sampler thread (SAMPLE_INTERVAL_SECONDS, in practice 0.1 s): the block id, the damage for the cell, the claw
health and the attack cooldown on the client, and the same on the host with the host copy of the client body. Per-swing numbers are therefore derived from the sampler (damage steps
and their times), and the swings carry their own invoke times. The packets the proxy forwarded are traced, so the host arrival time of every swing is estimated from the first packet the
client sent after the invoke plus the delay the proxy gave it.
"""
import time

from casualtieslink import desync
from casualtieslink.desync import SeriesScenario
from tests import desync_scenarios as base

WOOD_BLOCK_ID = 11
WOOD_HEALTH = 150.0
HOST_CHARACTER = 1
CLIENT_CHARACTERS = {"wood-mining-dune": 2, "wood-mining-experiment": 0}
SCRAPS_ID = "woodscraps"
SCRAPS_RADIUS = 2.5
SCRAPS_READ_SECONDS = 0.25
SAMPLE_INTERVAL_SECONDS = 0.05
SWING_POLL_SECONDS = 0.01
SWING_TIMEOUT_SECONDS = 12.0
MIN_DAMAGE_RISE = 5.0
HOST_COOLDOWN_SECONDS = 0.124
PROXY_DELAY_TOLERANCE = 0.8
CURVE_PATHS = ("clawDamageCurve", "clawDamageCurve.keys")
LIVE_VALUE_LIMIT = 600


def safe_get(game, target, path):
    try:
        return game.get(target, path, depth=0)
    except Exception as failure:
        return {"unreadable": str(failure)[:120]}


def number_or_none(value):
    return float(value) if isinstance(value, (int, float)) else None


def scrap_count(game, centre):
    try:
        return len(base.rows_near(game, "Item", centre, name=SCRAPS_ID, radius=SCRAPS_RADIUS))
    except Exception:
        return None


def wood_read(game, context):
    """One sample of one game: [block id, damage for the cell, {cell: damage}, woodscraps near the cell or None, claw health and attack cooldown of the swinging body (the host copy on the host)].
    The woodscraps are counted only once the cell is empty, and not more often than SCRAPS_READ_SECONDS."""
    is_host = game is context["hostGame"]
    side = "host" if is_host else "client"
    damage = base.crack_counter(game, context)
    block = base.block_value(game, context["position"])
    target, prefix = (context["hostBodyHandle"], "copy") if is_host else ("player", "")
    extra = {"claw": number_or_none(safe_get(game, target, "clawHealth")), "cooldown": number_or_none(safe_get(game, target, "attackCooldown"))}
    scraps = None
    now = time.monotonic()
    if block == desync.EMPTY_BLOCK and now - context["lastScrapRead"].get(side, 0.0) >= SCRAPS_READ_SECONDS:
        context["lastScrapRead"][side] = now
        scraps = scrap_count(game, context["position"])
    return [block, damage, {desync.TARGET_CELL_KEY: damage}, scraps, extra]


def live_values(game, target):
    """The claw damage curve and the arm power values of one body, read live; an unreadable value is kept as the reason it could not be read."""
    hand = safe_get(game, target, "handSlot")
    slot = int(hand) if isinstance(hand, (int, float)) else 1
    values = {"handSlot": hand, "armPowerMult": safe_get(game, target, "slots[%d].armPowerMult" % slot), "clawHealth": safe_get(game, target, "clawHealth"),
              "STR": safe_get(game, target, "skills.STR"), "charType": safe_get(game, target, "charType")}
    for path in CURVE_PATHS:
        values[path] = str(safe_get(game, target, path))[:LIVE_VALUE_LIMIT]
    return values


def character_identities(host, client, context, client_wanted):
    return {"host": safe_get(host, "player", "charType"), "client": safe_get(client, "player", "charType"), "clientOnHost": safe_get(host, context["hostBodyHandle"], "charType"), "clientWanted": client_wanted}


def wood_prepare_for(client_wanted):
    def prepare(host, client):
        return wood_prepare(host, client, client_wanted)
    return prepare


def wood_prepare(host, client, client_wanted):
    context = base.fresh_block_prepare_with("fixed", "side", block_id=WOOD_BLOCK_ID)(host, client)
    context["identities"] = character_identities(host, client, context, client_wanted)
    context["woodSwings"] = []
    context["lastScrapRead"] = {}
    context["liveValues"] = {"client": live_values(client, "player"), "hostCopyOfClient": live_values(context["hostGame"], context["hostBodyHandle"]), "host": live_values(context["hostGame"], "player")}
    context["scrapsBefore"] = {"host": scrap_count(host, context["position"]), "client": scrap_count(client, context["position"])}
    return context


def fire_swing(client, target, sleep=time.sleep, clock=time.monotonic, timeout=SWING_TIMEOUT_SECONDS, pause=SWING_POLL_SECONDS):
    """Invoke Body.UseItemInHand at the target until the attack cooldown rises. Returns the monotonic time of the invoke that swung and how many invokes the game ignored before it, or None."""
    deadline = clock() + timeout
    ignored = 0
    while clock() < deadline:
        before = float(client.get("player", "attackCooldown", depth=0))
        invoked_at = clock()
        client.call("invoke", target="player", method="UseItemInHand", sets=[{"target": "player", "path": "targetLookPos", "value": {"x": target["x"], "y": target["y"], "z": 0.0}}])
        if float(client.get("player", "attackCooldown", depth=0)) > before + base.COOLDOWN_RISE_EPSILON:
            return {"invokedAt": invoked_at, "ignored": ignored}
        ignored += 1
        sleep(pause)
    return None


def wood_hit(client, context):
    fired = fire_swing(client, context["position"])
    if fired is None:
        return False
    swings = context["woodSwings"]
    previous = swings[-1]["invokedAt"] if swings else None
    swings.append({"swing": len(swings) + 1, "invokedAt": fired["invokedAt"], "ignoredAttempts": fired["ignored"], "interval": None if previous is None else round(fired["invokedAt"] - previous, 3)})
    return True


def side_values(samples, side):
    """(time, block, damage, claw, cooldown) of every sample of one side."""
    rows = []
    for sample in samples:
        reading = sample[side]
        extra = reading[4] if len(reading) > 4 and isinstance(reading[4], dict) else {}
        rows.append((sample["t"], reading[0], reading[1], extra.get("claw"), extra.get("cooldown")))
    return rows


def damage_steps(samples, side):
    """Rises of the damage for the cell between consecutive samples while the block stands: [(time of the sample that shows it, rise)]."""
    steps = []
    previous = 0.0
    for moment, block, damage, _, _ in side_values(samples, side):
        if block != desync.EMPTY_BLOCK:
            if damage >= previous + MIN_DAMAGE_RISE:
                steps.append((moment, damage - previous))
            previous = damage
        else:
            previous = 0.0
    return steps


def damage_units(steps, unit):
    """How many swings of `unit` damage each step holds (two swings can fall between two samples)."""
    return [(moment, max(1, round(rise / unit))) for moment, rise in steps] if unit else []


def unit_damage(steps):
    rises = sorted(rise for _, rise in steps)
    return rises[len(rises) // 2] if rises else None


def swing_intervals(swings):
    return [entry["interval"] for entry in swings if entry.get("interval") is not None]


def estimate_arrivals(swings, packets):
    """Host arrival time of each swing, estimated: the first packet the client sent at or after the invoke carries the swing message (the reliable message goes out with the next
    outgoing packet); its arrival is the moment the proxy was due to send it (received plus delay and jitter, or the release of a stall). packets: (received at, direction, size, delay ms,
    due at), same monotonic clock."""
    sent = sorted((received, due) for received, direction, _, _, due in packets if direction == "toHost")
    arrivals = []
    for entry in swings:
        found = next((due for received, due in sent if received >= entry["invokedAt"]), None)
        arrivals.append(found)
    return arrivals


def arrival_spacings(arrivals):
    """Spacing between the arrivals of consecutive swings in swing order; negative when a later swing overtook an earlier one."""
    return [round(later - earlier, 3) for earlier, later in zip(arrivals, arrivals[1:]) if earlier is not None and later is not None]


def predicted_host_drops(arrivals, cooldown=HOST_COOLDOWN_SECONDS):
    """The swings the host's cooldown gate would drop if it accepts a swing only when it arrives at least `cooldown` after the last accepted one, in arrival order."""
    accepted = None
    dropped = 0
    for moment in sorted(value for value in arrivals if value is not None):
        if accepted is None or moment - accepted >= cooldown:
            accepted = moment
        else:
            dropped += 1
    return dropped


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return None
    return {"n": len(ordered), "min": round(ordered[0], 3), "median": round(ordered[len(ordered) // 2], 3), "max": round(ordered[-1], 3)}


def setup_problems(context, identities):
    problems = []
    control = context.get("positionControl")
    if not control or not control.get("ok"):
        problems.append("position control: %s" % "; ".join((control or {}).get("issues") or ["not applied"]))
    if not context.get("placedByHost"):
        problems.append("the block was not placed by the host")
    if context.get("blockId") != WOOD_BLOCK_ID or context.get("blockHealth") != WOOD_HEALTH:
        problems.append("block %s with health %s, wanted %d with %.0f" % (context.get("blockId"), context.get("blockHealth"), WOOD_BLOCK_ID, WOOD_HEALTH))
    for who, wanted in (("host", HOST_CHARACTER), ("client", identities.get("clientWanted"))):
        if identities.get(who) != wanted:
            problems.append("%s charType %s, wanted %s" % (who, identities.get(who), wanted))
    if identities.get("clientOnHost") != identities.get("clientWanted"):
        problems.append("the client body on the host has charType %s, wanted %s" % (identities.get("clientOnHost"), identities.get("clientWanted")))
    return problems


def baseline_problems(baseline):
    """The cell must be undamaged on both games before the first swing: damage left over from an earlier run (a block that stayed broken on one side only) would shorten the run."""
    problems = []
    for side in ("host", "client"):
        reading = (baseline or {}).get(side)
        if reading and reading[1] > 0:
            problems.append("the %s already held %.1f damage for the cell before the first swing" % (side, reading[1]))
    return problems


def proxy_problems(report):
    """The proxy must show the delay that was asked for: the mean delay the client's packets got must be at least PROXY_DELAY_TOLERANCE of the planned one."""
    network = report.get("network") or {}
    wanted = network.get("delay_ms") or 0.0
    seen = ((report.get("proxyObserved") or {}).get("toHost") or {}).get("meanMs")
    if wanted > 0 and (seen is None or seen < wanted * PROXY_DELAY_TOLERANCE):
        return ["the proxy delay %.0f ms was not observed (client to host mean %s ms)" % (wanted, seen)]
    return []


def swing_problems(swings, client_units, broke_at):
    """Every swing fired up to the break must have damaged the client's block, except the one that broke it: swings up to the break may not exceed the damaging swings plus one."""
    if broke_at is None:
        return []
    fired = len([entry for entry in swings if entry["t"] <= broke_at])
    damaging = sum(units for _, units in client_units)
    if fired > damaging + 1:
        return ["%d swings were fired before the break but only %d damaged the client's block" % (fired, damaging)]
    return []


def judge_wood_run(context, findings, identities, swings, client_units, extra_problems=()):
    """valid-run rule and verdict of one run: invalid with reasons, reversion with its timing, or persisted."""
    client_findings, host_findings = findings["client"], findings["host"]
    reasons = setup_problems(context, identities) + list(extra_problems) + swing_problems(swings, client_units, client_findings["brokeAt"])
    if client_findings["brokeAt"] is None:
        reasons.append("the client never broke the block")
    if reasons:
        return {"verdict": "invalid", "reasons": reasons}
    outcome = {"verdict": "persisted", "reasons": [], "clientBrokeAt": client_findings["brokeAt"], "hostBrokeAt": host_findings["brokeAt"], "clientReappeared": client_findings["reappeared"],
               "hostReappeared": host_findings["reappeared"]}
    if client_findings["reappeared"]:
        outcome["verdict"] = "reversion"
    return outcome


def final_scraps(samples, side):
    """The most woodscraps counted near the cell on one side after the break."""
    seen = [sample[side][3] for sample in samples if len(sample[side]) > 3 and sample[side][3] is not None]
    return max(seen) if seen else None


def host_damage_record(samples, unit):
    """Host damage steps against client damage steps: the swings each machine applied to the block, the break counted as one."""
    client_steps, host_steps = damage_steps(samples, "client"), damage_steps(samples, "host")
    client_units, host_units = damage_units(client_steps, unit), damage_units(host_steps, unit)
    client_broke = any(block == desync.EMPTY_BLOCK for _, block, _, _, _ in side_values(samples, "client"))
    host_broke = any(block == desync.EMPTY_BLOCK for _, block, _, _, _ in side_values(samples, "host"))
    client_applied = sum(units for _, units in client_units) + (1 if client_broke else 0)
    host_applied = sum(units for _, units in host_units) + (1 if host_broke else 0)
    return {"unitDamage": None if unit is None else round(unit, 2), "clientSwingsApplied": client_applied, "hostSwingsApplied": host_applied, "hostMissed": client_applied - host_applied,
            "clientStepTimes": [round(moment, 2) for moment, _ in client_steps], "hostStepTimes": [round(moment, 2) for moment, _ in host_steps], "hostCooldownSeen": max(
                [value for _, _, _, _, value in side_values(samples, "host") if value is not None] or [None])}


def extend_report(report, observation, run_logs, packets):
    """Adds the swings, the sampler-derived damage record, the bunching evidence, the live values, the woodscraps counts and the run verdict to the series report; returns the issues that
    make the run fail."""
    context = observation.context
    started = context.get("seriesStarted") or 0.0
    swings = [dict(entry, t=round(entry["invokedAt"] - started, 3)) for entry in context.get("woodSwings") or []]
    unit = unit_damage(damage_steps(observation.samples, "client"))
    record = host_damage_record(observation.samples, unit)
    arrivals = estimate_arrivals(swings, packets)
    spacings = arrival_spacings(arrivals)
    bunching = {"clientIntervals": distribution(swing_intervals(swings)), "hostArrivalSpacings": distribution(spacings), "arrivalsUnderCooldown": len([value for value in spacings if value < HOST_COOLDOWN_SECONDS]),
                "arrivalsEstimated": len([value for value in arrivals if value is not None]), "swingsFired": len(swings), "predictedHostDrops": predicted_host_drops(arrivals),
                "hostCooldownSeconds": HOST_COOLDOWN_SECONDS, "ignoredAttempts": sum(entry["ignoredAttempts"] for entry in swings)}
    identities = context["identities"]
    client_units = damage_units(damage_steps(observation.samples, "client"), unit)
    judged = judge_wood_run(context, report["findings"], identities, swings, client_units, proxy_problems(report) + baseline_problems(getattr(observation, "baseline", None)))
    report["woodRun"] = dict(judged, swingsFired=len(swings), damage=record, bunching=bunching, scraps={"before": context.get("scrapsBefore"), "end": {side: final_scraps(observation.samples, side) for side in ("host", "client")}},
                             identities=identities)
    report["woodSwings"] = [dict(entry, arrivalEstimate=None if arrivals[index] is None else round(arrivals[index] - started, 3)) for index, entry in enumerate(swings)]
    report["liveValues"] = context.get("liveValues")
    if judged["verdict"] == "invalid":
        return ["INVALID: " + "; ".join(judged["reasons"])]
    if judged["verdict"] == "reversion":
        first = judged["clientReappeared"][0]
        return ["REVERSION: the client's block came back %.2f s after it broke (client broke at %.2f s, host at %s)" % (first["goneFor"], judged["clientBrokeAt"], judged["hostBrokeAt"])]
    return []


def make_scenario(name, description, group):
    scenario = SeriesScenario(name, description, wood_prepare_for(CLIENT_CHARACTERS[group]), wood_hit, wood_read, cadence_seconds=0.0, max_hits=base.HOLD_MAX_CALLS, group=group,
                              interval_seconds=SAMPLE_INTERVAL_SECONDS, cleanup=base.remove_fresh_block)
    scenario.extend_report = extend_report
    scenario.client_character = CLIENT_CHARACTERS[group]
    return scenario


WOOD_SCENARIOS = [
    make_scenario("wood_mining_dune", "a Dune client mines a host-placed wood block (id 11, 150 hp) with bare hands at the cooldown's rate, Milky host; both machines are sampled every 0.05 s and the cell is watched for 10 s after the break",
                  "wood-mining-dune"),
    make_scenario("wood_mining_experiment", "the same with an Experiment client (species control)", "wood-mining-experiment"),
]

base.SERIES_SCENARIOS.extend(WOOD_SCENARIOS)
