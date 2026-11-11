import re

MARKER = "[diagblock]"
LINE_PATTERN = re.compile(r"\[diagblock\] t=(?P<t>\S+) (?P<kind>[A-Z_]+)(?P<rest>.*)")
FIELD_PATTERN = re.compile(r"(\w+)=(\S+)")
CLIENT_SEND = "CLIENT_SEND"
HOST_RECV = "HOST_RECV"
HOST_REFUSE = "HOST_REFUSE"
HOST_DROP = "HOST_DROP"
HOST_PARSED = "HOST_PARSED"
HOST_DECIDED = "HOST_DECIDED"
HOST_AFTER = "HOST_AFTER"
COMPARED_FIELDS = ("cd", "cons", "overEnc", "stim", "stamina", "charType", "STR", "RES", "INT", "armPow", "bonusStr", "claw")
DIFFERENCE_FIELDS = ("cons", "overEnc", "stim", "charType", "STR", "RES", "INT", "armPow", "bonusStr", "claw")
GEOMETRY_FIELDS = ("pos", "limb1", "look")
PARSED_FIELDS = ("sentLimb1", "sentLook", "hostLimb1Before", "hostLookBefore", "hitPos")
APPLIED_REASON = "applied"


def parse_lines(text):
    entries = []
    for line in text.splitlines():
        if MARKER not in line:
            continue
        match = LINE_PATTERN.search(line)
        if not match:
            continue
        rest = match.group("rest")
        fields = dict(FIELD_PATTERN.findall(rest))
        reason = None
        if match.group("kind") == HOST_DECIDED:
            reason_match = re.search(r"block (applied|not applied \(unknown\)|out of reach|both cells air|hitPos not finite)", rest)
            reason = reason_match.group(1) if reason_match else None
            if " non-block kind" in rest:
                reason = "non-block"
        entries.append({"t": float(match.group("t")), "kind": match.group("kind"), "fields": fields, "reason": reason})
    return entries


def client_sends(entries):
    return [entry for entry in entries if entry["kind"] == CLIENT_SEND]


def host_records(entries):
    records = []
    current = None
    for entry in entries:
        kind = entry["kind"]
        if kind == HOST_RECV:
            current = {"recv": entry, "outcome": "received", "seq": None, "decided": None, "after": None, "refuse": None, "parsed": None}
            records.append(current)
        elif current is None:
            continue
        elif kind == HOST_REFUSE:
            current["outcome"] = "refused-cooldown"
            current["refuse"] = entry
        elif kind == HOST_DROP:
            current["outcome"] = "dropped-before-cooldown-check"
        elif kind == HOST_PARSED:
            current["outcome"] = "parsed"
            current["parsed"] = entry
            current["seq"] = entry["fields"].get("seq")
        elif kind == HOST_DECIDED:
            current["decided"] = entry
            current["seq"] = entry["fields"].get("seq", current["seq"])
            current["outcome"] = "decided:" + (entry["reason"] or "unknown")
        elif kind == HOST_AFTER:
            current["after"] = entry
    return records


def swing_table(client_entries, host_entries):
    sends = client_sends(client_entries)
    records = host_records(host_entries)
    rows = []
    for index, send in enumerate(sends):
        record = records[index] if index < len(records) else None
        row = {"index": index + 1, "seq": send["fields"].get("seq"), "clientT": send["t"], "clientAttackPower": send["fields"].get("clientAttackPower"),
               "client": {name: send["fields"].get(name) for name in COMPARED_FIELDS},
               "clientGeometry": {name: send["fields"].get(name) for name in GEOMETRY_FIELDS}}
        if record is None:
            row["outcome"] = "never-received"
        else:
            row["outcome"] = record["outcome"]
            row["hostT"] = record["recv"]["t"]
            row["host"] = {name: record["recv"]["fields"].get(name) for name in COMPARED_FIELDS}
            row["hostGeometry"] = {name: record["recv"]["fields"].get(name) for name in GEOMETRY_FIELDS}
            if record["parsed"] is not None:
                row["hostAim"] = {name: record["parsed"]["fields"].get(name) for name in PARSED_FIELDS}
            row["seqMatches"] = record["seq"] is None or record["seq"] == send["fields"].get("seq")
            if record["decided"] is not None:
                fields = record["decided"]["fields"]
                row["decided"] = {"reason": record["decided"]["reason"], "counter": fields.get("counter"), "health": fields.get("health"),
                                  "attackpower": fields.get("attackpower"), "blockId": fields.get("blockId")}
            if record["after"] is not None:
                row["hostCooldownAfter"] = record["after"]["fields"].get("cd")
                delta = record["after"]["fields"].get("blockDamageSumDelta")
                if delta is not None:
                    row["hostBlockDamageDelta"] = delta
                    row["hostRaycastMiss"] = record["outcome"] != "refused-cooldown" and float(delta) == 0.0
            if record["refuse"] is not None:
                row["refusedAtHostCooldown"] = record["refuse"]["fields"].get("copy")
        rows.append(row)
    return rows


def differences(rows):
    found = []
    for row in rows:
        host = row.get("host")
        if not host:
            continue
        for name in DIFFERENCE_FIELDS:
            if row["client"].get(name) != host.get(name):
                found.append({"swing": row["index"], "field": name, "client": row["client"].get(name), "host": host.get(name)})
    return found


def inter_arrival(rows):
    times = [row["hostT"] for row in rows if "hostT" in row]
    return [round(later - earlier, 3) for earlier, later in zip(times, times[1:])]


def damage_check(rows):
    for row in rows:
        decided = row.get("decided")
        if not decided or "host" not in row:
            continue
        client_power = row.get("clientAttackPower")
        host_power = decided.get("attackpower")
        return {"swing": row["index"], "clientSTR": row["client"].get("STR"), "hostSTR": row["host"].get("STR"),
                "strEqual": row["client"].get("STR") == row["host"].get("STR"),
                "clientCharType": row["client"].get("charType"), "hostCharType": row["host"].get("charType"),
                "clientAttackPower": client_power, "hostAttackpower": host_power,
                "attackPowerEqual": client_power is not None and host_power is not None and float(client_power) == float(host_power)}
    return None


def summarise_run(client_log, host_log, hit_times=None):
    client_entries = parse_lines(client_log)
    host_entries = parse_lines(host_log)
    rows = swing_table(client_entries, host_entries)
    outcomes = {}
    for row in rows:
        outcomes[row["outcome"]] = outcomes.get(row["outcome"], 0) + 1
    gaps = inter_arrival(rows)
    lost = [row for row in rows if row["outcome"] != "decided:" + APPLIED_REASON]
    summary = {
        "clientSends": len(rows),
        "hitsRequestedByHarness": len(hit_times) if hit_times is not None else None,
        "outcomes": outcomes,
        "lost": [{"index": row["index"], "seq": row["seq"], "outcome": row["outcome"]} for row in lost],
        "shortestHostArrivalGap": min(gaps) if gaps else None,
        "arrivalGapsUnder0124": [gap for gap in gaps if gap < 0.124],
        "hostRaycastMisses": [{"index": row["index"], "seq": row["seq"], "outcome": row["outcome"]} for row in rows if row.get("hostRaycastMiss")],
        "fieldDifferences": differences(rows),
        "firstDamageCheck": damage_check(rows),
        "rows": rows,
    }
    summary["textLines"] = text_lines(summary)
    return summary


def text_lines(summary):
    lines = ["diagblock: client sends %d (harness swings %s), outcomes %s" % (summary["clientSends"], summary["hitsRequestedByHarness"], summary["outcomes"])]
    lines.append("diagblock: shortest host arrival gap %s s; gaps under 0.124 s: %s" % (summary["shortestHostArrivalGap"], summary["arrivalGapsUnder0124"] or "none"))
    for row in summary["rows"]:
        decided = row.get("decided") or {}
        lines.append("diagblock swing %d seq %s: %s, client cd=%s cons=%s, host cons=%s%s%s" % (
            row["index"], row["seq"], row["outcome"], row["client"].get("cd"), row["client"].get("cons"), (row.get("host") or {}).get("cons"),
            (", counter=%s health=%s" % (decided.get("counter"), decided.get("health"))) if decided else "",
            (", host cooldown copy=%s" % row["refusedAtHostCooldown"]) if "refusedAtHostCooldown" in row else ""))
    if summary["hostRaycastMisses"]:
        lines.append("diagblock: received swings that changed no block damage on the host (blockDamageSumDelta 0): %s" % [item["index"] for item in summary["hostRaycastMisses"]])
    check = summary.get("firstDamageCheck")
    if check:
        lines.append("diagblock first decided swing %(swing)d: STR client %(clientSTR)s host %(hostSTR)s (equal %(strEqual)s), charType client %(clientCharType)s host %(hostCharType)s, "
                     "clientAttackPower %(clientAttackPower)s host attackpower %(hostAttackpower)s (equal %(attackPowerEqual)s)" % check)
    for difference in summary["fieldDifferences"]:
        lines.append("diagblock difference at swing %(swing)d: %(field)s client %(client)s host %(host)s" % difference)
    return lines
