"""Wood block mining by a Dune (or Experiment) client on a Milky host: does the broken block come back on the client?

The test is block persistence, not swing landing. A run is judged in three steps:
  INVALID    a setup gate failed (client not seated and held, host not parked by distance, wrong characters, block not placed on both games), a fired swing did not damage the client's
             block, or the client never broke the block. Nothing is concluded from an invalid run.
  REVERSION  the client's copy of the cell held a block again after it had been empty (the host's copy is judged and recorded separately).
  persisted  the client broke the block and the cell stayed empty on both games until the end of the tail.
Every swing is fired by the held-click path (Body.UseItemInHand every 20 ms, the game's attack cooldown decides), and both machines are read after each fired swing.
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
MIN_DAMAGE_RISE = 5.0
HOST_EVENT_MARKERS = (("cooldown", "hit server cooldown"), ("range", "hit server range"), ("applied", "hit server apply"), ("unresolved", "hit server unresolved"), ("dropped", "hit server drop"))
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
    """One sample: the block id, the damage the game holds for the cell, the damage per neighbour cell (unused) and the woodscraps near the cell."""
    damage = base.crack_counter(game, context)
    return [base.block_value(game, context["position"]), damage, {desync.TARGET_CELL_KEY: damage}, scrap_count(game, context["position"])]


def client_reads(client, context):
    return {"damage": base.crack_counter(client, context), "block": base.block_value(client, context["position"]), "clawHealth": number_or_none(safe_get(client, "player", "clawHealth")),
            "cooldown": number_or_none(safe_get(client, "player", "attackCooldown")), "STR": number_or_none(safe_get(client, "player", "skills.STR"))}


def host_reads(host, context):
    handle = context["hostBodyHandle"]
    return {"damage": base.crack_counter(host, context), "block": base.block_value(host, context["position"]), "copyClawHealth": number_or_none(safe_get(host, handle, "clawHealth")),
            "copyCooldown": number_or_none(safe_get(host, handle, "attackCooldown")), "copySTR": number_or_none(safe_get(host, handle, "skills.STR"))}


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
    context["woodStarted"] = None
    context["liveValues"] = {"client": live_values(client, "player"), "hostCopyOfClient": live_values(context["hostGame"], context["hostBodyHandle"]), "host": live_values(context["hostGame"], "player")}
    context["scrapsBefore"] = {"host": scrap_count(host, context["position"]), "client": scrap_count(client, context["position"])}
    return context


def wood_hit(client, context):
    if context["woodStarted"] is None:
        context["woodStarted"] = time.monotonic()
    cooldown_before = number_or_none(safe_get(client, "player", "attackCooldown"))
    fired = base.aimed_hold_hit(client, context)
    if fired is False:
        return False
    moment = round(time.monotonic() - context["woodStarted"], 3)
    context["woodSwings"].append({"swing": len(context["woodSwings"]) + 1, "t": moment, "cooldownBefore": cooldown_before, "client": client_reads(client, context), "host": host_reads(context["hostGame"], context)})
    return True


def host_event_sequence(host_log_text):
    """The host's 'hit server' lines in order, each as the first marker name it contains."""
    events = []
    for line in host_log_text.splitlines():
        for name, marker in HOST_EVENT_MARKERS:
            if marker in line:
                events.append(name)
                break
    return events


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


def swing_problems(swings):
    """A fired swing must raise the client's damage for the cell, read right after it or after the next swing (the hit may be applied a moment after the cooldown rises), or break
    the block; a swing that did not hit the block means the aim or the position was off."""
    problems = []
    previous = 0.0
    for index, entry in enumerate(swings):
        client = entry["client"]
        if client["block"] == desync.EMPTY_BLOCK:
            break
        following = swings[index + 1]["client"] if index + 1 < len(swings) else None
        rose = client["damage"] >= previous + MIN_DAMAGE_RISE
        rose_later = following is not None and (following["block"] == desync.EMPTY_BLOCK or following["damage"] >= previous + MIN_DAMAGE_RISE)
        if not rose and not rose_later:
            problems.append("swing %d did not damage the client's block (%.1f to %.1f)" % (entry["swing"], previous, client["damage"]))
        previous = client["damage"]
    return problems


def judge_wood_run(context, findings, identities):
    """valid-run rule and verdict of one run: invalid with reasons, reversion with its timing, or persisted."""
    swings = context.get("woodSwings") or []
    reasons = setup_problems(context, identities) + swing_problems(swings)
    client_findings, host_findings = findings["client"], findings["host"]
    if client_findings["brokeAt"] is None:
        reasons.append("the client never broke the block")
    if reasons:
        return {"verdict": "invalid", "reasons": reasons}
    outcome = {"verdict": "persisted", "reasons": [], "clientBrokeAt": client_findings["brokeAt"], "hostBrokeAt": host_findings["brokeAt"], "clientReappeared": client_findings["reappeared"],
               "hostReappeared": host_findings["reappeared"]}
    if client_findings["reappeared"]:
        outcome["verdict"] = "reversion"
    return outcome


def final_scraps(samples):
    last = samples[-1] if samples else None
    if last is None:
        return {"host": None, "client": None}
    return {side: (last[side][3] if len(last[side]) > 3 else None) for side in ("host", "client")}


def extend_report(report, observation, run_logs):
    """Adds the per-swing reads, the host's event order, the live values, the woodscraps counts and the run verdict to the series report; returns the issues that make the run fail."""
    context = observation.context
    findings = report["findings"]
    identities = context["identities"]
    judged = judge_wood_run(context, findings, identities)
    events = host_event_sequence(run_logs["host"])
    report["woodRun"] = dict(judged, swingsFired=len(context.get("woodSwings") or []), hostEvents=events, hostEventCounts={name: events.count(name) for name, _ in HOST_EVENT_MARKERS},
                             scraps={"before": context.get("scrapsBefore"), "end": final_scraps(observation.samples)}, identities=identities)
    report["woodSwings"] = context.get("woodSwings")
    report["liveValues"] = context.get("liveValues")
    if judged["verdict"] == "invalid":
        return ["INVALID: " + "; ".join(judged["reasons"])]
    if judged["verdict"] == "reversion":
        first = judged["clientReappeared"][0]
        return ["REVERSION: the client's block came back %.2f s after it broke (client broke at %.2f s, host at %s)" % (first["goneFor"], judged["clientBrokeAt"], judged["hostBrokeAt"])]
    return []


def make_scenario(name, description, group):
    scenario = SeriesScenario(name, description, wood_prepare_for(CLIENT_CHARACTERS[group]), wood_hit, wood_read, cadence_seconds=base.HOLD_CALL_PAUSE_SECONDS, max_hits=base.HOLD_MAX_CALLS, group=group, cleanup=base.remove_fresh_block)
    scenario.extend_report = extend_report
    scenario.client_character = CLIENT_CHARACTERS[group]
    return scenario


WOOD_SCENARIOS = [
    make_scenario("wood_mining_dune", "a Dune client mines a host-placed wood block (id 11, 150 hp) with bare hands, held click, Milky host; both machines are read after every swing and the cell is watched for 10 s after the break",
                  "wood-mining-dune"),
    make_scenario("wood_mining_experiment", "the same with an Experiment client (species control)", "wood-mining-experiment"),
]

base.SERIES_SCENARIOS.extend(WOOD_SCENARIOS)
