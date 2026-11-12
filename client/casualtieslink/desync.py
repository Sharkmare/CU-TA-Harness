import hashlib
import json
import os
import re
import threading
import time
import zipfile

from . import launchplan

SAMPLE_OFFSETS_SECONDS = (0.0, 2.0, 10.0)
FLAVOUR_BUILDS = ("stock-5.5.0", "stock-5.4.0", "fork")
STAGE_BUILD = "upstream-fixes"
DIAG_BUILD = "upstream-diag"
DIAG2_BUILD = "upstream-diag2"
DIAG3_BUILD = "upstream-diag3"
FIXED_BUILD = "upstream-fixed"
BASELINE_BUILD = "upstream-baseline"
FIXED_DIAG_BUILD = "upstream-fixed-diag"
FIXED_NOBUILD_BUILD = "upstream-fixed-nobuild"
FIXED_V2_BUILD = "upstream-fixed-v2"
FIXED_FINAL_BUILD = "upstream-fixed-final"
OFFICIAL_BUILD = "official-5.5.0"
FULLBUILD_CONTROL_BUILD = "fullbuild-control"
FULLBUILD_FIXED_BUILD = "fullbuild-fixed"
SPECTATOR_FIX_BUILD = "spectator-fix"
PR24_CONTROL_BUILD = "pr24-control"
PR24_FIXED_BUILD = "pr24-fixed"
PR24_VERBOSE_BUILD = "pr24-fixed-verbose"
PR24_CONTROL_VERBOSE_BUILD = "pr24-control-verbose"
STAGE_CHOICES = {STAGE_BUILD: "stage", DIAG_BUILD: "diag-stage", DIAG2_BUILD: "diag-stage2", DIAG3_BUILD: "diag-stage3",
                 FIXED_BUILD: "fullgame-stage", BASELINE_BUILD: "baseline-stage", FIXED_DIAG_BUILD: "fullgame-diag-stage",
                 FIXED_NOBUILD_BUILD: "fullgame-nobuild-stage", FIXED_V2_BUILD: "fullgame-v2-stage", FIXED_FINAL_BUILD: "fullgame-final-stage", OFFICIAL_BUILD: "official-stage",
                 FULLBUILD_CONTROL_BUILD: "fullbuild-control-stage", FULLBUILD_FIXED_BUILD: "fullbuild-fixed-stage", SPECTATOR_FIX_BUILD: "spectator-fix-stage",
                 PR24_CONTROL_BUILD: "pr24-control-stage", PR24_FIXED_BUILD: "pr24-fixed-stage", PR24_VERBOSE_BUILD: "pr24-fixed-verbose-stage", PR24_CONTROL_VERBOSE_BUILD: "pr24-control-verbose-stage"}
KNOWN_BUILDS = FLAVOUR_BUILDS + (STAGE_BUILD, DIAG_BUILD, DIAG2_BUILD, DIAG3_BUILD, FIXED_BUILD, BASELINE_BUILD, FIXED_DIAG_BUILD, FIXED_NOBUILD_BUILD, FIXED_V2_BUILD, FIXED_FINAL_BUILD, OFFICIAL_BUILD, FULLBUILD_CONTROL_BUILD, FULLBUILD_FIXED_BUILD, SPECTATOR_FIX_BUILD, PR24_CONTROL_BUILD, PR24_FIXED_BUILD, PR24_VERBOSE_BUILD, PR24_CONTROL_VERBOSE_BUILD)
DIAG_BUILDS = (DIAG_BUILD, DIAG2_BUILD, DIAG3_BUILD)
TRANSPILER_MARKER = "TRANSPILER"
PATCH_PROBLEM_MARKERS = ("Failed to patch", "IL Compile Error", "Ambiguous match")


TRANSPILER_SUCCESS = "Body.Attack TRANSPILER SUCCESS"
TRANSPILER_MISSING_MARKERS = "loop markers not found"
FAILED_ATTACK_PATCH = "Failed to patch: Body_Attack_MultiplayerPatch"
NO_SCATTER_LINE = "NoScatterPunish:"
NO_SCATTER_COMPLETE = "(2 of 2 Together checks replaced)"
EXCEPTION_PATTERN = re.compile(r"Exception|\[Error")


def launch_log_checks(host_log, client_log, expect_no_scatter=True, expect_success=True, record_only=False):
    checks = {}
    for which, text in (("host", host_log), ("client", client_log)):
        checks[which + "TranspilerSuccess"] = sum(1 for line in text.splitlines() if TRANSPILER_SUCCESS in line)
        checks[which + "MarkersNotFound"] = sum(1 for line in text.splitlines() if TRANSPILER_MISSING_MARKERS in line)
        checks[which + "FailedAttackPatch"] = [line.strip() for line in text.splitlines() if FAILED_ATTACK_PATCH in line]
        checks[which + "PatchProblems"] = [line.strip()[:240] for line in text.splitlines() if any(marker in line for marker in PATCH_PROBLEM_MARKERS)]
    scatter = [line.strip() for line in host_log.splitlines() if NO_SCATTER_LINE in line]
    checks["noScatterLines"] = scatter
    issues = []
    for which in ("host", "client"):
        if expect_success and checks[which + "TranspilerSuccess"] < 1:
            issues.append("no 'Body.Attack TRANSPILER SUCCESS' line in the %s log" % which)
        if not expect_success and checks[which + "TranspilerSuccess"] > 0:
            issues.append("'Body.Attack TRANSPILER SUCCESS' in the %s log of a build that should not have the repaired hook" % which)
        if checks[which + "MarkersNotFound"]:
            issues.append("'loop markers not found' in the %s log" % which)
        if checks[which + "FailedAttackPatch"]:
            issues.append("'%s' in the %s log: %s" % (FAILED_ATTACK_PATCH, which, checks[which + "FailedAttackPatch"][0][:120]))
    if expect_no_scatter and not any(NO_SCATTER_COMPLETE in line for line in scatter):
        issues.append("no 'NoScatterPunish ... (2 of 2 Together checks replaced)' line in the host log")
    checks["issues"] = [] if record_only else issues
    checks["recordOnly"] = record_only
    return checks


def save_game_logs(games, directory, launch_id, class_name):
    folder = os.path.join(directory, re.sub(r"[^A-Za-z0-9.\-]", "_", "%s__%s" % (launch_id or "no-launch", class_name)))
    os.makedirs(folder, exist_ok=True)
    saved = []
    for which in ("host", "client"):
        text = games.log_text(which)
        if text:
            path = os.path.join(folder, which + "-LogOutput.log")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            saved.append(path)
    return saved


def save_launch_checks(checks, directory, launch_id):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "launch_checks__%s.json" % re.sub(r"[^A-Za-z0-9.\-]", "_", launch_id or "no-launch"))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(checks, handle, indent=2, sort_keys=True)
    return path


def new_exception_lines(before_text, after_text):
    before = set(line for line in before_text.splitlines() if EXCEPTION_PATTERN.search(line))
    return [line.strip() for line in after_text.splitlines() if EXCEPTION_PATTERN.search(line) and line not in before]


def transpiler_lines(log_text):
    return [line.strip() for line in log_text.splitlines() if TRANSPILER_MARKER in line]
DEFAULT_BUILD = "stock-5.5.0"
BUILD_ENVIRONMENT_VARIABLE = "CU_DESYNC_TOGETHER"
SKIP_ACTION_MUTATION = "skip-client-action"
HASH_PREFIX_LENGTH = 8
UNKNOWN_HASH = "unknown"

VERDICT_PERSISTED = "persisted"
VERDICT_REVERTED = "reverted-by-host"
VERDICT_DIVERGED = "diverged"
VERDICT_NEVER_CHANGED = "never-changed"
VERDICT_LOST = "not-there-from-the-start"


def parse_build(text):
    name = (text or DEFAULT_BUILD).strip().lower()
    if name not in KNOWN_BUILDS:
        raise ValueError("unknown Together build %r; choose one of %s" % (text, ", ".join(KNOWN_BUILDS)))
    return name


def together_choice(build):
    return STAGE_CHOICES.get(build) or "flavour:" + build


def sha256_of_bytes(content):
    return hashlib.sha256(content).hexdigest()


def sha256_of_file(path):
    with open(path, "rb") as handle:
        return sha256_of_bytes(handle.read())


def flavour_dll_hash(zip_path, build):
    entry = "BepInEx/together-flavours/%s/CasualtiesMP.dll" % build
    try:
        with zipfile.ZipFile(zip_path) as archive:
            return sha256_of_bytes(archive.read(entry))
    except (OSError, KeyError, zipfile.BadZipFile):
        return UNKNOWN_HASH


def stage_dll_hash(stage_directory):
    path = os.path.join(stage_directory, "plugins", "Together", "CasualtiesMP.dll")
    try:
        return sha256_of_file(path)
    except OSError:
        return UNKNOWN_HASH


def build_label(build, dll_hash):
    return "%s@%s" % (build, dll_hash[:HASH_PREFIX_LENGTH])


def class_suffix(build, dll_hash):
    return re.sub(r"[^A-Za-z0-9]", "_", build_label(build, dll_hash))


class Scenario:
    network_sensitive = False

    def __init__(self, name, description, prepare, act, read, changed, offsets=SAMPLE_OFFSETS_SECONDS, group="default", check=None, max_repeat=None):
        self.max_repeat = max_repeat
        self.check = check
        self.offsets = offsets
        self.group = group
        self.name = name
        self.description = description
        self.prepare = prepare
        self.act = act
        self.read = read
        self.changed = changed


class Sample:
    def __init__(self, offset, host, client):
        self.offset = offset
        self.host = host
        self.client = client

    def as_dict(self):
        return {"offset": self.offset, "host": self.host, "client": self.client}


class Observation:
    def __init__(self, scenario, baseline_host, baseline_client, samples, acted, context=None):
        self.context = context or {}
        self.scenario = scenario
        self.baseline_host = baseline_host
        self.baseline_client = baseline_client
        self.samples = samples
        self.acted = acted


def observe(scenario, host, client, offsets=None, perform_action=True, clock=time.monotonic, sleep=time.sleep):
    offsets = offsets if offsets is not None else scenario.offsets
    context = scenario.prepare(host, client)
    baseline_host = scenario.read(host, context)
    baseline_client = scenario.read(client, context)
    if perform_action:
        scenario.act(client, context)
    started = clock()
    samples = []
    for offset in offsets:
        remaining = offset - (clock() - started)
        if remaining > 0:
            sleep(remaining)
        samples.append(Sample(offset, scenario.read(host, context), scenario.read(client, context)))
    return Observation(scenario, baseline_host, baseline_client, samples, perform_action, context)


def judge(observation):
    scenario = observation.scenario
    baseline = observation.baseline_host
    changed_on_client = [scenario.changed(sample.client, baseline) for sample in observation.samples]
    changed_on_host = [scenario.changed(sample.host, baseline) for sample in observation.samples]
    if not any(changed_on_client) and not any(changed_on_host):
        return VERDICT_NEVER_CHANGED
    if any(changed_on_client) and not changed_on_client[-1] and not changed_on_host[-1]:
        return VERDICT_REVERTED
    if any(sample.host != sample.client for sample in observation.samples):
        return VERDICT_DIVERGED
    if not all(changed_on_host):
        return VERDICT_LOST
    return VERDICT_PERSISTED


def describe(observation, build, dll_hash, game_version=None, launch_id=None, repetition=1, network=None, proxy_seed=None):
    verdict = judge(observation)
    return {
        "launchId": launch_id,
        "repetition": repetition,
        "network": network,
        "proxySeed": proxy_seed,
        "gameVersion": game_version,
        "actionPerformedBy": "client",
        "build": build,
        "dllSha256": dll_hash,
        "scenario": observation.scenario.name,
        "description": observation.scenario.description,
        "actedOnClient": observation.acted,
        "verdict": verdict,
        "measurements": observation.context.get("measurements"),
        "target": observation.context.get("target"),
        "missedAttempts": observation.context.get("missedAttempts"),
        "issues": observation.scenario.check(observation.context) if observation.scenario.check else [],
        "baseline": {"host": observation.baseline_host, "client": observation.baseline_client},
        "samples": [sample.as_dict() for sample in observation.samples],
    }


def format_report(report):
    lines = [
        "desync %s [%s] sha256 %s" % (report["scenario"], report["build"], report["dllSha256"]),
        "  launch %s, repetition %s, network %s" % (report.get("launchId"), report.get("repetition", 1), report.get("network")),
        "  %s" % report["description"],
        "  game version %s, action performed by the %s: %s" % (report.get("gameVersion"), report.get("actionPerformedBy", "client"), "yes" if report["actedOnClient"] else "SKIPPED (mutation)"),
        "  baseline  host=%s client=%s" % (report["baseline"]["host"], report["baseline"]["client"]),
    ]
    for sample in report["samples"]:
        marker = "" if sample["host"] == sample["client"] else "  <- instances disagree"
        lines.append("  t=%4.1fs   host=%s client=%s%s" % (sample["offset"], sample["host"], sample["client"], marker))
    if report.get("target"):
        lines.append("  target %s" % report["target"])
    if report.get("missedAttempts"):
        lines.append("  attempts before the first landed punch that changed nothing: %s" % report["missedAttempts"])
    for entry in (report.get("measurements") or [])[:40]:
        lines.append("  measurement %s" % entry)
    for issue in report.get("issues", []):
        lines.append("  ISSUE: %s" % issue)
    lines.append("  verdict: %s" % report["verdict"])
    if report["verdict"] == VERDICT_REVERTED:
        lines.append("  the host value overwrote the client value")
    return "\n".join(lines)


def save_report(report, directory):
    os.makedirs(directory, exist_ok=True)
    name = "%s__%s__r%s.json" % (report["scenario"], re.sub(r"[^A-Za-z0-9.\-]", "_", build_label(report["build"], report["dllSha256"])), report.get("repetition", 1))
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    return path



NETS_ENVIRONMENT_VARIABLE = "CU_DESYNC_NETS"
GROUP_ENVIRONMENT_VARIABLE = "CU_DESYNC_GROUP"
SETTLE_AFTER_NETWORK_CHANGE_SECONDS = 1.0
REPEAT_ENVIRONMENT_VARIABLE = "CU_DESYNC_REPEAT"
LAUNCH_ENVIRONMENT_VARIABLE = "CU_LAUNCH_ID"
SCENARIO_BUDGET_SECONDS = 120.0
DELAY_ENVIRONMENT_VARIABLE = "CU_DESYNC_DELAY_MS"
JITTER_ENVIRONMENT_VARIABLE = "CU_DESYNC_JITTER_MS"
TARGET_CELL_KEY = "0,0"
SERIES_INTERVAL_SECONDS = 0.25
SERIES_TAIL_SECONDS = 10.0
COUNTER_DROP_EPSILON = 0.01
VERDICT_CRACK_RESET = "crack-reset"
VERDICT_REAPPEARED = "reappeared-after-break"
VERDICT_NEVER_BROKE = "never-broke"
EMPTY_BLOCK = 0


def parse_delay(text):
    if text is None or text == "":
        return None
    value = float(text)
    if value < 0:
        raise ValueError("delay must not be negative: %r" % text)
    return value


class Run:
    def __init__(self, scenario, profile, repetition, name):
        self.scenario = scenario
        self.profile = profile
        self.repetition = repetition
        self.name = name


def expand_runs(scenarios, profiles, repeat):
    runs = []
    for scenario in scenarios:
        chosen = profiles if scenario.network_sensitive else [launchplan.DIRECT]
        for profile in chosen:
            count = (profile.repeat or repeat) if scenario.network_sensitive else repeat
            if getattr(scenario, "max_repeat", None):
                count = min(count, scenario.max_repeat)
            for repetition in range(1, count + 1):
                name = "test_" + scenario.name
                if scenario.network_sensitive:
                    name += "_" + profile.label()
                name += repetition_suffix(repetition, count)
                runs.append(Run(scenario, profile, repetition, name))
    return runs


def profiles_from_environment():
    text = os.environ.get(NETS_ENVIRONMENT_VARIABLE)
    if text:
        return launchplan.parse_profiles(text.split(","))
    delay, jitter = delay_from_environment()
    if delay is not None:
        return [launchplan.NetworkProfile(delay, jitter)]
    return [launchplan.DIRECT]


def group_from_environment():
    return os.environ.get(GROUP_ENVIRONMENT_VARIABLE) or None


def repeat_from_environment():
    count = int(os.environ.get(REPEAT_ENVIRONMENT_VARIABLE) or 1)
    if count < 1:
        raise ValueError("repeat must be at least 1")
    return count


def launch_id_from_environment():
    return os.environ.get(LAUNCH_ENVIRONMENT_VARIABLE) or None


def repetition_suffix(repetition, repeat):
    return "" if repeat <= 1 else "_r%02d" % repetition


def delay_from_environment():
    return parse_delay(os.environ.get(DELAY_ENVIRONMENT_VARIABLE)), float(os.environ.get(JITTER_ENVIRONMENT_VARIABLE) or 0.0)


class SeriesScenario:
    network_sensitive = True

    def __init__(self, name, description, prepare, hit, read, cadence_seconds, max_hits, group="default",
                 interval_seconds=SERIES_INTERVAL_SECONDS, tail_seconds=SERIES_TAIL_SECONDS, cleanup=None):
        self.cleanup = cleanup
        self.name = name
        self.description = description
        self.prepare = prepare
        self.hit = hit
        self.read = read
        self.cadence_seconds = cadence_seconds
        self.max_hits = max_hits
        self.group = group
        self.interval_seconds = interval_seconds
        self.tail_seconds = tail_seconds


class SeriesObservation:
    def __init__(self, scenario, baseline, samples, hit_times, acted, context=None):
        self.context = context or {}
        self.scenario = scenario
        self.baseline = baseline
        self.samples = samples
        self.hit_times = hit_times
        self.acted = acted


def observe_series(scenario, host, client, perform_action=True, clock=time.monotonic, sleep=time.sleep, budget_seconds=SCENARIO_BUDGET_SECONDS):
    context = scenario.prepare(host, client)
    baseline = {"host": scenario.read(host, context), "client": scenario.read(client, context)}
    samples = []
    hit_times = []
    stop = threading.Event()
    started = clock()

    def sampler():
        while not stop.is_set():
            elapsed = clock() - started
            samples.append({"t": round(elapsed, 3), "host": scenario.read(host, context), "client": scenario.read(client, context)})
            stop.wait(scenario.interval_seconds)

    thread = threading.Thread(target=sampler, daemon=True)
    thread.start()
    try:
        if perform_action:
            for _ in range(scenario.max_hits):
                if clock() - started > budget_seconds:
                    break
                moment = round(clock() - started, 3)
                if scenario.hit(client, context) is not False:
                    hit_times.append(moment)
                sleep(scenario.cadence_seconds)
                latest = samples[-1] if samples else None
                if latest is not None and latest["client"][0] == EMPTY_BLOCK:
                    break
        sleep(scenario.tail_seconds)
    finally:
        stop.set()
        thread.join(timeout=5.0)
        if scenario.cleanup is not None:
            try:
                scenario.cleanup(host, client, context)
            except Exception as exception:
                context["cleanupError"] = str(exception)
    return SeriesObservation(scenario, baseline, list(samples), hit_times, perform_action, context)


def side_findings(samples, side):
    resets = []
    gone_since = None
    reappeared = []
    broke_at = None
    previous = None
    for index, sample in enumerate(samples):
        block, counter = sample[side][:2]
        if previous is not None:
            previous_block, previous_counter = previous
            following = samples[index + 1][side][0] if index + 1 < len(samples) else block
            if previous_block != EMPTY_BLOCK and block != EMPTY_BLOCK and following != EMPTY_BLOCK and counter < previous_counter - COUNTER_DROP_EPSILON:
                resets.append({"t": sample["t"], "from": previous_counter, "to": counter})
        if block == EMPTY_BLOCK and broke_at is None:
            broke_at = sample["t"]
        if block == EMPTY_BLOCK and gone_since is None:
            gone_since = sample["t"]
        if block != EMPTY_BLOCK and gone_since is not None:
            reappeared.append({"t": sample["t"], "goneFor": round(sample["t"] - gone_since, 3)})
            gone_since = None
        previous = (block, counter)
    return {"brokeAt": broke_at, "resets": resets, "reappeared": reappeared,
            "presentAtEnd": bool(samples) and samples[-1][side][0] != EMPTY_BLOCK}


def judge_series(samples):
    findings = {"host": side_findings(samples, "host"), "client": side_findings(samples, "client")}
    if findings["host"]["brokeAt"] is None and findings["client"]["brokeAt"] is None:
        return VERDICT_NEVER_BROKE, findings
    if findings["host"]["reappeared"] or findings["client"]["reappeared"]:
        return VERDICT_REAPPEARED, findings
    if findings["host"]["resets"] or findings["client"]["resets"]:
        return VERDICT_CRACK_RESET, findings
    return VERDICT_PERSISTED, findings


HOST_LOG_MARKERS = {
    "cooldownDrops": "hit server cooldown",
    "rangeDrops": "hit server range",
    "applied": "hit server apply",
    "unresolved": "hit server unresolved",
    "dropped": "hit server drop",
}
RATIO_TOLERANCE = 0.02
MIN_RATIO_PAIRS = 3
LATE_BREAK_SECONDS = 0.3


def host_log_counts(log_text):
    return {name: sum(1 for line in log_text.splitlines() if marker in line) for name, marker in HOST_LOG_MARKERS.items()}


def counter_increases(samples, side):
    increases = 0
    previous = 0.0
    for sample in samples:
        block, counter = sample[side][:2]
        if block != EMPTY_BLOCK and counter > previous + COUNTER_DROP_EPSILON:
            increases += 1
        if block != EMPTY_BLOCK:
            previous = counter
    return increases


def crack_steps(samples, side):
    steps = []
    previous = 0.0
    for sample in samples:
        block, counter = sample[side][:2]
        if block != EMPTY_BLOCK and counter > previous + COUNTER_DROP_EPSILON:
            steps.append(round(counter - previous, 4))
        previous = counter if block != EMPTY_BLOCK else 0.0
    return steps


def tile_hits(samples, side):
    hits = {}
    previous = {}
    for sample in samples:
        cells = sample[side][2] if len(sample[side]) > 2 and sample[side][0] != EMPTY_BLOCK else {}
        for cell, counter in cells.items():
            if counter > previous.get(cell, 0.0) + COUNTER_DROP_EPSILON:
                hits[cell] = hits.get(cell, 0) + 1
        previous = dict(cells)
    return hits


def host_step_times(samples):
    times = []
    previous = 0.0
    for sample in samples:
        block, counter = sample["host"][:2]
        if block != EMPTY_BLOCK and counter > previous + COUNTER_DROP_EPSILON:
            times.append(sample["t"])
        elif block != EMPTY_BLOCK and counter == 0.0 and previous > 0.0:
            times.append(sample["t"])
        elif block == EMPTY_BLOCK and previous > 0.0:
            times.append(sample["t"])
        previous = counter if block != EMPTY_BLOCK else 0.0
    return times


def classify_swings(hit_times, samples, delay_ms):
    delay = (delay_ms or 0.0) / MILLISECONDS_PER_SECOND
    arrivals = [hit_time + delay for hit_time in hit_times]
    accepted = [False] * len(hit_times)
    steps = host_step_times(samples)
    for step in steps:
        owners = [index for index, arrival in enumerate(arrivals) if arrival <= step]
        if owners:
            accepted[owners[-1]] = True
    host_break = next((sample["t"] for sample in samples if sample["host"][0] == EMPTY_BLOCK), None)
    if host_break is not None:
        accepted = [None if arrival > host_break else ok for arrival, ok in zip(arrivals, accepted)]
    return accepted


def swing_intervals(hit_times):
    return [round(later - earlier, 3) for earlier, later in zip(hit_times, hit_times[1:])]


def gap_summary(swing_log, accepted):
    summary = {}
    for label, wanted in (("accepted", True), ("dropped", False)):
        gaps = [entry["gap"] for entry, ok in zip(swing_log, accepted) if ok is wanted]
        summary[label] = {"count": len(gaps), "meanGap": round(sum(gaps) / len(gaps), 3) if gaps else None, "maxGap": max(gaps) if gaps else None}
    return summary


MILLISECONDS_PER_SECOND = 1000.0


HOST_ATTACK_COOLDOWN_SECONDS = 0.124


def verdict_hints(samples, hit_times, delay_ms, host_counts, findings, jitter_ms=0.0):
    hints = []
    intervals = swing_intervals(hit_times)
    if intervals:
        spread = (jitter_ms or 0.0) / MILLISECONDS_PER_SECOND
        close = [value for value in intervals if value - spread < HOST_ATTACK_COOLDOWN_SECONDS]
        hints.append("client swing intervals: shortest %.3f s, mean %.3f s; %d of %d could reach the host under the %.3f s cooldown after jitter of up to %.0f ms" % (
            min(intervals), sum(intervals) / len(intervals), len(close), len(intervals), HOST_ATTACK_COOLDOWN_SECONDS, jitter_ms or 0.0))
    pairs = [(s["client"][1], s["host"][1]) for s in samples if s["client"][0] != EMPTY_BLOCK and s["host"][0] != EMPTY_BLOCK and s["client"][1] > 0 and s["host"][1] > 0]
    if len(pairs) >= MIN_RATIO_PAIRS:
        ratios = [host / client for client, host in pairs]
        if max(ratios) - min(ratios) <= RATIO_TOLERANCE and abs(ratios[0] - 1.0) > RATIO_TOLERANCE:
            hints.append("constant host/client crack ratio %.2f: damage multiplier mismatch" % ratios[0])
    host_steps = counter_increases(samples, "host")
    client_steps = counter_increases(samples, "client")
    swings = len(hit_times)
    hints.append("swings requested %d, host crack steps %d, client crack steps %d" % (swings, host_steps, client_steps))
    if host_counts:
        hints.append("host log: cooldown drops %d, range drops %d, applied lines %d" % (host_counts["cooldownDrops"], host_counts["rangeDrops"], host_counts["applied"]))
        if host_counts["cooldownDrops"] > 0:
            hints.append("host dropped swings on the attacker cooldown")
        if host_counts["rangeDrops"] > 0:
            hints.append("host rejected swings for range")
    host_break, client_break = findings["host"]["brokeAt"], findings["client"]["brokeAt"]
    if host_break is not None and client_break is not None and host_break - client_break > LATE_BREAK_SECONDS:
        hints.append("host broke the block %.2f s after the client" % (host_break - client_break))
    if host_break is not None and client_break is not None and client_break - host_break > LATE_BREAK_SECONDS:
        hints.append("client saw the break %.2f s after the host" % (client_break - host_break))
    if swings > host_steps + 1 and delay_ms:
        hints.append("fewer host crack steps than swings at %g ms: dropped swings" % delay_ms)
    if not [h for h in hints if h.startswith("constant") or "dropped" in h or "rejected" in h or "after the" in h]:
        hints.append("no divergence pattern in this run")
    return hints


def swing_records(observation, delay_ms):
    log = observation.context.get("swingLog") or []
    accepted = classify_swings(observation.hit_times, observation.samples, delay_ms)
    records = [dict(entry, t=hit_time, acceptedByHost=ok) for entry, hit_time, ok in zip(log, observation.hit_times, accepted)]
    intervals = swing_intervals(observation.hit_times)
    return {"list": records, "gaps": gap_summary(log, accepted) if log else None,
            "acceptedCount": sum(1 for ok in accepted if ok is True), "droppedCount": sum(1 for ok in accepted if ok is False),
            "afterHostBreakCount": sum(1 for ok in accepted if ok is None),
            "clientIntervals": intervals,
            "shortestInterval": min(intervals) if intervals else None,
            "meanInterval": round(sum(intervals) / len(intervals), 3) if intervals else None}


def describe_series(observation, build, dll_hash, game_version=None, delay_ms=None, jitter_ms=0.0, host_counts=None, launch_id=None, repetition=1, network=None, proxy_seed=None):
    verdict, findings = judge_series(observation.samples)
    return {
        "launchId": launch_id,
        "repetition": repetition,
        "network": network,
        "proxySeed": proxy_seed,
        "block": {key: observation.context.get(key) for key in ("position", "blockId", "blockHealth", "cell")},
        "hostLog": host_counts,
        "swings": swing_records(observation, delay_ms),
        "crackSteps": {"client": crack_steps(observation.samples, "client"), "host": crack_steps(observation.samples, "host")},
        "tileHits": {"client": tile_hits(observation.samples, "client"), "host": tile_hits(observation.samples, "host")},
        "cleanupError": observation.context.get("cleanupError"),
        "startPositions": observation.context.get("startPositions"),
        "positionControl": observation.context.get("positionControl"),
        "aimPattern": observation.context.get("aimPattern"),
        "hints": verdict_hints(observation.samples, observation.hit_times, delay_ms, host_counts, findings, jitter_ms),
        "gameVersion": game_version,
        "actionPerformedBy": "client",
        "build": build,
        "dllSha256": dll_hash,
        "delayMs": delay_ms,
        "jitterMs": jitter_ms,
        "scenario": observation.scenario.name,
        "description": observation.scenario.description,
        "actedOnClient": observation.acted,
        "verdict": verdict,
        "findings": findings,
        "hitTimes": observation.hit_times,
        "baseline": observation.baseline,
        "samples": observation.samples,
    }


def format_series_report(report):
    delay = "no proxy"
    if report.get("network"):
        network = report["network"]
        delay = "%g ms one way, jitter up to %g ms, loss %g, reorder %g, seed %s" % (network["delay_ms"], network["jitter_ms"], network["loss"], network["reorder"], report.get("proxySeed"))
    elif report.get("delayMs") is not None:
        delay = "%g ms one way (+ jitter up to %g ms)" % (report["delayMs"], report.get("jitterMs") or 0.0)
    lines = [
        "desync %s [%s] sha256 %s" % (report["scenario"], report["build"], report["dllSha256"]),
        "  launch %s, repetition %s" % (report.get("launchId"), report.get("repetition", 1)),
        "  %s" % report["description"],
        "  game version %s, action performed by the %s, network: %s" % (report.get("gameVersion"), report.get("actionPerformedBy", "client"), delay),
        "  hits %d, first at %.2fs, last at %.2fs" % (len(report["hitTimes"]), report["hitTimes"][0] if report["hitTimes"] else 0.0, report["hitTimes"][-1] if report["hitTimes"] else 0.0),
        "  baseline  host=%s client=%s" % (report["baseline"]["host"], report["baseline"]["client"]),
    ]
    for side in ("host", "client"):
        found = report["findings"][side]
        lines.append("  %s: broke at %s, crack resets %s, reappeared %s, present at end: %s" % (
            side, found["brokeAt"], [(item["t"], item["from"], item["to"]) for item in found["resets"]] or "none",
            [(item["t"], item["goneFor"]) for item in found["reappeared"]] or "never", found["presentAtEnd"]))
    block = report.get("block") or {}
    lines.insert(4, "  block id %s, health %s, at %s" % (block.get("blockId"), block.get("blockHealth"), block.get("position")))
    swings = report.get("swings") or {}
    if swings:
        lines.append("  swings sent %d; accepted by the host (approximate, by crack steps): %d, dropped: %d, sent after the host had already broken the block: %d" % (
            len(report["hitTimes"]), swings["acceptedCount"], swings["droppedCount"], swings.get("afterHostBreakCount", 0)))
        for label, found in (swings.get("gaps") or {}).items():
            lines.append("  %s swings: %d, host copy of the client body to its real position, mean %s, max %s world units" % (label, found["count"], found["meanGap"], found["maxGap"]))
    if report.get("tileHits") and (report["tileHits"]["client"] or report["tileHits"]["host"]):
        hits = report["tileHits"]
        lines.append("  tile hits (offset from the target block: crack increases), client %s, host %s; aim pattern %s" % (hits["client"], hits["host"], report.get("aimPattern")))
        other_host = sum(count for cell, count in hits["host"].items() if cell != TARGET_CELL_KEY)
        other_client = sum(count for cell, count in hits["client"].items() if cell != TARGET_CELL_KEY)
        lines.append("  increases on tiles other than the target: client %d, host %d" % (other_client, other_host))
    if report.get("transpilerLines"):
        for which in ("host", "client"):
            lines.append("  %s Body.Attack transpiler lines: %s" % (which, report["transpilerLines"][which] or "none"))
    if report.get("cleanupError"):
        lines.append("  cleanup error: %s" % report["cleanupError"])
    if report.get("crackSteps"):
        lines.append("  crack steps per sample, client %s, host %s" % (report["crackSteps"]["client"], report["crackSteps"]["host"]))
    for hint in report.get("hints", []):
        lines.append("  hint: %s" % hint)
    if report.get("proxyObserved"):
        for direction in ("toHost", "toClient"):
            observed = report["proxyObserved"][direction]
            lines.append("  proxy %s: %d packets, planned one way delay min %s mean %s max %s ms" % (direction, observed["packets"], observed["minMs"], observed["meanMs"], observed["maxMs"]))
    if report.get("clientBody"):
        lines.append("  client body: %s" % report["clientBody"])
    for line in report.get("diagBlock", {}).get("textLines", []):
        lines.append("  " + line)
    previous = None
    for sample in report["samples"]:
        state = (sample["host"], sample["client"])
        if state != previous:
            lines.append("  t=%6.2fs   host=%s client=%s" % (sample["t"], sample["host"], sample["client"]))
        previous = state
    lines.append("  verdict: %s" % report["verdict"])
    return "\n".join(lines)


def save_series_report(report, directory):
    os.makedirs(directory, exist_ok=True)
    if report.get("network"):
        network = report["network"]
        label = "d%g-j%g" % (network["delay_ms"], network["jitter_ms"])
    else:
        label = "delay%s_jitter%g" % ("none" if report.get("delayMs") is None else "%g" % report["delayMs"], report.get("jitterMs") or 0.0)
    stamp = time.strftime("%H%M%S")
    name = "%s__%s__%s_r%s__%s.json" % (report["scenario"], re.sub(r"[^A-Za-z0-9.\-]", "_", build_label(report["build"], report["dllSha256"])), label, report.get("repetition", 1), stamp)
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    return path
