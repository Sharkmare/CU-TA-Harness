import hashlib
import json
import os
import re
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

