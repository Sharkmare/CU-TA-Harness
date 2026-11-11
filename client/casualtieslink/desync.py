import hashlib
import json
import os
import re
import threading
import time
import zipfile

SAMPLE_OFFSETS_SECONDS = (0.0, 2.0, 10.0)
FLAVOUR_BUILDS = ("stock-5.5.0", "stock-5.4.0", "fork")
STAGE_BUILD = "upstream-fixes"
KNOWN_BUILDS = FLAVOUR_BUILDS + (STAGE_BUILD,)
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
    return "stage" if build == STAGE_BUILD else "flavour:" + build


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
    def __init__(self, name, description, prepare, act, read, changed, offsets=SAMPLE_OFFSETS_SECONDS, group="default"):
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
    def __init__(self, scenario, baseline_host, baseline_client, samples, acted):
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
    return Observation(scenario, baseline_host, baseline_client, samples, perform_action)


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


def describe(observation, build, dll_hash, game_version=None):
    verdict = judge(observation)
    return {
        "gameVersion": game_version,
        "actionPerformedBy": "client",
        "build": build,
        "dllSha256": dll_hash,
        "scenario": observation.scenario.name,
        "description": observation.scenario.description,
        "actedOnClient": observation.acted,
        "verdict": verdict,
        "baseline": {"host": observation.baseline_host, "client": observation.baseline_client},
        "samples": [sample.as_dict() for sample in observation.samples],
    }


def format_report(report):
    lines = [
        "desync %s [%s] sha256 %s" % (report["scenario"], report["build"], report["dllSha256"]),
        "  %s" % report["description"],
        "  game version %s, action performed by the %s: %s" % (report.get("gameVersion"), report.get("actionPerformedBy", "client"), "yes" if report["actedOnClient"] else "SKIPPED (mutation)"),
        "  baseline  host=%s client=%s" % (report["baseline"]["host"], report["baseline"]["client"]),
    ]
    for sample in report["samples"]:
        marker = "" if sample["host"] == sample["client"] else "  <- instances disagree"
        lines.append("  t=%4.1fs   host=%s client=%s%s" % (sample["offset"], sample["host"], sample["client"], marker))
    lines.append("  verdict: %s" % report["verdict"])
    if report["verdict"] == VERDICT_REVERTED:
        lines.append("  the host value overwrote the client value")
    return "\n".join(lines)


def save_report(report, directory):
    os.makedirs(directory, exist_ok=True)
    name = "%s__%s.json" % (report["scenario"], re.sub(r"[^A-Za-z0-9.\-]", "_", build_label(report["build"], report["dllSha256"])))
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    return path



DELAY_ENVIRONMENT_VARIABLE = "CU_DESYNC_DELAY_MS"
JITTER_ENVIRONMENT_VARIABLE = "CU_DESYNC_JITTER_MS"
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


def delay_from_environment():
    return parse_delay(os.environ.get(DELAY_ENVIRONMENT_VARIABLE)), float(os.environ.get(JITTER_ENVIRONMENT_VARIABLE) or 0.0)


class SeriesScenario:
    def __init__(self, name, description, prepare, hit, read, cadence_seconds, max_hits, group="default",
                 interval_seconds=SERIES_INTERVAL_SECONDS, tail_seconds=SERIES_TAIL_SECONDS):
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
    def __init__(self, scenario, baseline, samples, hit_times, acted):
        self.scenario = scenario
        self.baseline = baseline
        self.samples = samples
        self.hit_times = hit_times
        self.acted = acted


def observe_series(scenario, host, client, perform_action=True, clock=time.monotonic, sleep=time.sleep):
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
                hit_times.append(round(clock() - started, 3))
                scenario.hit(client, context)
                sleep(scenario.cadence_seconds)
                latest = samples[-1] if samples else None
                if latest is not None and latest["client"][0] == EMPTY_BLOCK:
                    break
        sleep(scenario.tail_seconds)
    finally:
        stop.set()
        thread.join(timeout=5.0)
    return SeriesObservation(scenario, baseline, list(samples), hit_times, perform_action)


def side_findings(samples, side):
    resets = []
    gone_since = None
    reappeared = []
    broke_at = None
    previous = None
    for sample in samples:
        block, counter = sample[side]
        if previous is not None:
            previous_block, previous_counter = previous
            if previous_block != EMPTY_BLOCK and block != EMPTY_BLOCK and counter < previous_counter - COUNTER_DROP_EPSILON:
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


def describe_series(observation, build, dll_hash, game_version=None, delay_ms=None, jitter_ms=0.0):
    verdict, findings = judge_series(observation.samples)
    return {
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
    delay = "no proxy" if report.get("delayMs") is None else "%g ms one way (+ jitter up to %g ms)" % (report["delayMs"], report.get("jitterMs") or 0.0)
    lines = [
        "desync %s [%s] sha256 %s" % (report["scenario"], report["build"], report["dllSha256"]),
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
    delay = "none" if report.get("delayMs") is None else "%g" % report["delayMs"]
    name = "%s__%s__delay%s.json" % (report["scenario"], re.sub(r"[^A-Za-z0-9.\-]", "_", build_label(report["build"], report["dllSha256"])), delay)
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    return path
