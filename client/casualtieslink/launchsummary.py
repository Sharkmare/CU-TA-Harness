import glob
import json
import os

LOST_OUTCOME_PREFIX = "decided:"
APPLIED_OUTCOME = "decided:applied"


def load_reports(directory, launch_id):
    reports = []
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        with open(path, encoding="utf-8") as handle:
            report = json.load(handle)
        if report.get("launchId") == launch_id:
            reports.append(report)
    return reports


def profile_label(report):
    network = report.get("network") or {}
    return "d%g-j%g" % (network.get("delay_ms", 0.0), network.get("jitter_ms", 0.0))


def empty_profile_summary():
    return {"blocksMined": 0, "blocksNeverBroke": 0, "reappearedAfterBreak": 0, "crackResets": 0, "swingsHarness": 0,
            "swingsSent": 0, "swingsReceived": 0, "swingsAccepted": 0, "lossByReason": {}, "proxyMeanDelayMs": [], "proxyMaxDelayMs": [],
            "gamesDownAfterRun": 0, "reappearedRuns": []}


def add_report(summary, report):
    if report["verdict"] == "never-broke":
        summary["blocksNeverBroke"] += 1
    else:
        summary["blocksMined"] += 1
    if report["verdict"] == "reappeared-after-break":
        summary["reappearedAfterBreak"] += 1
        summary["reappearedRuns"].append(report.get("repetition"))
    if report["verdict"] == "crack-reset":
        summary["crackResets"] += 1
    summary["swingsHarness"] += len(report.get("hitTimes", []))
    diag = report.get("diagBlock")
    if diag:
        summary["swingsSent"] += diag["clientSends"]
        for row in diag["rows"]:
            if row["outcome"] != "never-received":
                summary["swingsReceived"] += 1
            if row["outcome"] == APPLIED_OUTCOME:
                summary["swingsAccepted"] += 1
            else:
                reason = row["outcome"][len(LOST_OUTCOME_PREFIX):] if row["outcome"].startswith(LOST_OUTCOME_PREFIX) else row["outcome"]
                summary["lossByReason"][reason] = summary["lossByReason"].get(reason, 0) + 1
    observed = report.get("proxyObserved") or {}
    for direction in ("toHost", "toClient"):
        found = observed.get(direction) or {}
        if found.get("meanMs") is not None:
            summary["proxyMeanDelayMs"].append(found["meanMs"])
            summary["proxyMaxDelayMs"].append(found["maxMs"])
    answers = report.get("gamesAnswerAfterRun") or {}
    if "error" in answers:
        summary["gamesDownAfterRun"] += 1


def summarise_launch(reports):
    profiles = {}
    for report in reports:
        add_report(profiles.setdefault(profile_label(report), empty_profile_summary()), report)
    for summary in profiles.values():
        delays = summary.pop("proxyMeanDelayMs")
        maxima = summary.pop("proxyMaxDelayMs")
        summary["proxyMeanDelayMs"] = round(sum(delays) / len(delays), 2) if delays else None
        summary["proxyMaxDelayMs"] = max(maxima) if maxima else None
    return profiles


def format_summary(launch_id, profiles):
    lines = ["launch %s" % launch_id]
    for label in sorted(profiles, key=lambda text: tuple(float(part[1:]) for part in text.split("-"))):
        found = profiles[label]
        lines.append("  %s: blocks mined %d (never broke %d), reappeared after break %d (runs %s), crack resets %d" % (
            label, found["blocksMined"], found["blocksNeverBroke"], found["reappearedAfterBreak"], found["reappearedRuns"] or "none", found["crackResets"]))
        lines.append("      swings: harness %d, client sent %d, host received %d, accepted %d, lost by reason %s" % (
            found["swingsHarness"], found["swingsSent"], found["swingsReceived"], found["swingsAccepted"], found["lossByReason"] or "none"))
        lines.append("      proxy planned one way delay: mean %s ms, max %s ms; games unanswering after a run: %d" % (
            found["proxyMeanDelayMs"], found["proxyMaxDelayMs"], found["gamesDownAfterRun"]))
    return "\n".join(lines)
