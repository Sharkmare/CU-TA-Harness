import glob
import json
import math
import os

REPORT_PATTERN = "v2check_dig_cracks__*.json"
NEVER_BROKE = "never-broke"


def distances(report):
    result = []
    for swing in (report.get("swings") or {}).get("list") or []:
        if swing.get("clientPosition") and swing.get("aim"):
            result.append(math.hypot(swing["clientPosition"]["x"] - swing["aim"]["x"], swing["clientPosition"]["y"] - swing["aim"]["y"]))
    return result


def cause_for(row):
    if row["verdict"] != NEVER_BROKE:
        return None
    if row["clientCrackSteps"] == 0 and row["hostCrackSteps"] == 0:
        far = row["distanceMax"] is not None and row["distanceMax"] > row["firstDistance"] * 2
        return "no crack step on the client's own copy or the host from any swing%s; the block took no damage on either side, so the swings did not hit it locally (hook victim not sent, nothing for the host to apply)" % (
            ", and the client ended %.1f from the block" % row["distanceMax"] if far else "")
    if row["clientCrackSteps"] > 0 and row["hostCrackSteps"] == 0:
        return "the client cracked its own copy but the host applied no crack step: not shown why"
    return "not shown"


def summarise_report(report):
    swing = report.get("swings") or {}
    listed = swing.get("list") or []
    reach = distances(report)
    findings = report.get("findings") or {}
    host_log = report.get("hostLog") or {}
    row = {"verdict": report.get("verdict"), "repetition": report.get("repetition"), "block": (report.get("block") or {}).get("position"),
           "firstDistance": round(reach[0], 2) if reach else None, "distanceMin": round(min(reach), 2) if reach else None, "distanceMax": round(max(reach), 2) if reach else None,
           "swingsFired": len(listed), "swingsAcceptedByHost": swing.get("acceptedCount"), "hostApplied": host_log.get("applied"), "hostDropped": host_log.get("dropped"),
           "hostCrackSteps": len((report.get("crackSteps") or {}).get("host") or []), "clientCrackSteps": len((report.get("crackSteps") or {}).get("client") or []),
           "hostBrokeAt": (findings.get("host") or {}).get("brokeAt"), "clientBrokeAt": (findings.get("client") or {}).get("brokeAt"),
           "hostPresentAtEnd": (findings.get("host") or {}).get("presentAtEnd"), "reappeared": bool((findings.get("host") or {}).get("reappeared") or (findings.get("client") or {}).get("reappeared"))}
    row["cause"] = cause_for(row)
    return row


def summarise_directory(directory):
    rows = []
    for path in sorted(glob.glob(os.path.join(directory, REPORT_PATTERN))):
        with open(path, encoding="utf-8") as handle:
            rows.append(summarise_report(json.load(handle)))
    rows.sort(key=lambda row: row["repetition"] or 0)
    return rows


def counts(rows):
    broke = [row for row in rows if row["verdict"] != NEVER_BROKE]
    return {"runs": len(rows), "persisted": sum(1 for row in rows if row["verdict"] == "persisted"), "neverBroke": len(rows) - len(broke),
            "other": sorted({row["verdict"] for row in rows} - {"persisted", NEVER_BROKE}), "reappeared": sum(1 for row in rows if row["reappeared"])}
