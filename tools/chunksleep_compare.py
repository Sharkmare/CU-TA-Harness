"""Comparison rules for chunksleep_ab reports. Rows are [id, name, x, y, chunk, asleep, active, settled, hot]."""
import json

ROW_ID, ROW_NAME, ROW_X, ROW_Y, ROW_CHUNK, ROW_ASLEEP, ROW_ACTIVE, ROW_SETTLED, ROW_HOT = range(9)


def awake_set(machine_entry):
    return frozenset(row[ROW_ID] for row in machine_entry["rows"] if row[ROW_ACTIVE])


def invariant_violations(machine_entry):
    """Objects whose chunk is hot for this machine but that are switched off. The mod promises none after the settle time."""
    return [row for row in machine_entry["rows"] if row[ROW_HOT] and not row[ROW_ACTIVE]]


MATCH_RADIUS = 3.0


def base_name(name):
    """The host names a spawned crate 'medcrate(Clone)'; a client names the synced copy 'SyncInfo(building, id: 62, res: medcrate)'. Both reduce to 'medcrate'."""
    if "res: " in name:
        return name.split("res: ", 1)[1].rstrip(")")
    return name.replace("(Clone)", "").strip()


def group_states(machine_entry, group_ids, references=None):
    """Awake flag per labelled object in spawn order; None for an object the machine does not watch. The ids are the host's instance ids, so another machine
    is matched by name and place against `references`, the (name, x, y) of each object as the host saw it first."""
    by_id = {row[ROW_ID]: row for row in machine_entry["rows"]}
    states = []
    for index, identifier in enumerate(group_ids):
        row = by_id.get(identifier)
        if row is None and references:
            name, x, y = references[index]
            near = [candidate for candidate in machine_entry["rows"] if base_name(candidate[ROW_NAME]) == base_name(name) and abs(candidate[ROW_X] - x) <= MATCH_RADIUS and abs(candidate[ROW_Y] - y) <= MATCH_RADIUS]
            row = near[0] if len(near) == 1 else None
        states.append(None if row is None else bool(row[ROW_ACTIVE]))
    return states


def reference_places(report):
    """Where the host saw each labelled object in the first sample."""
    first_host = report["samples"][0]["machines"]["host"]
    by_id = {row[ROW_ID]: row for row in first_host["rows"]}
    return {label: [(by_id[i][ROW_NAME], by_id[i][ROW_X], by_id[i][ROW_Y]) if i in by_id else None for i in group["ids"]] for label, group in report["groups"].items()}


def summarize_group(states):
    return {"awake": sum(1 for state in states if state is True), "asleep": sum(1 for state in states if state is False), "unwatched": sum(1 for state in states if state is None)}


def first_divergence(baseline_states, candidate_states):
    for index, (baseline, candidate) in enumerate(zip(baseline_states, candidate_states)):
        if baseline is not None and candidate is not None and baseline != candidate:
            return {"index": index, "baseline": baseline, "candidate": candidate}
    return None


def machine_report(report):
    """Per sample and machine: totals, invariant violations, and the per group summary and state vector."""
    rows = {}
    places = reference_places(report)
    for taken in report["samples"]:
        for machine, entry in taken["machines"].items():
            groups = {}
            for label, group in report["groups"].items():
                references = places[label] if all(places[label]) else None
                states = group_states(entry, group["ids"], references)
                groups[label] = {"summary": summarize_group(states), "states": states}
            rows[(taken["name"], machine)] = {
                "watched": len(entry["rows"]),
                "awake": sum(1 for row in entry["rows"] if row[ROW_ACTIVE]),
                "violations": len(invariant_violations(entry)),
                "violationNames": sorted({row[ROW_NAME] for row in invariant_violations(entry)})[:5],
                "unsettled": entry.get("unsettledTotal"),
                "groups": groups,
            }
    return rows


def compare_reports(baseline, candidate):
    """Differences of the candidate against the baseline in the labelled groups, keyed by sample and machine. Empty means identical awake and asleep sets for every labelled object."""
    baseline_rows, candidate_rows = machine_report(baseline), machine_report(candidate)
    differences = []
    for key in sorted(baseline_rows):
        if key not in candidate_rows:
            differences.append({"sample": key[0], "machine": key[1], "problem": "missing in candidate"})
            continue
        for label in baseline_rows[key]["groups"]:
            first = first_divergence(baseline_rows[key]["groups"][label]["states"], candidate_rows[key]["groups"][label]["states"])
            if first:
                differences.append({"sample": key[0], "machine": key[1], "group": label, "baseline": baseline_rows[key]["groups"][label]["summary"],
                                    "candidate": candidate_rows[key]["groups"][label]["summary"], "firstDivergence": first})
    return differences


def settle_time(trace, machine):
    """Seconds after the move until the machine's hot-but-off count is zero and stays zero for the rest of the trace; None when it never settles. Also the peak count seen."""
    peak = 0
    last_bad = None
    for row in trace:
        count = row[machine]["hotOff"]
        peak = max(peak, count)
        if count > 0:
            last_bad = row["t"]
    if trace and trace[-1][machine]["hotOff"] > 0:
        return None, peak
    return (0.0 if last_bad is None else last_bad), peak


def latency_rows(report):
    """Per move and machine: (settle seconds, peak hot-but-off, number of polls)."""
    rows = {}
    traces = [(taken["name"], taken.get("trace")) for taken in report["samples"] if taken.get("trace")]
    if report.get("keepTrace"):
        traces.append(("keep_armed", report["keepTrace"]))
    for name, trace in traces:
        for machine in trace[0]:
            if machine == "t":
                continue
            seconds, peak = settle_time(trace, machine)
            rows[(name, machine)] = (seconds, peak, len(trace))
    return rows


def print_comparison(paths):
    reports = []
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            reports.append((path, json.load(handle)))
    baseline_path, baseline = reports[0]
    for path, report in reports:
        print("== %s (build %s)" % (path, report["build"]))
        rows = machine_report(report)
        for key in sorted(rows, key=lambda item: (list(r["name"] for r in report["samples"]).index(item[0]), item[1])):
            row = rows[key]
            groups = " ".join("%s=%d/%d" % (label, group["summary"]["awake"], group["summary"]["awake"] + group["summary"]["asleep"]) for label, group in row["groups"].items())
            print("  %-22s %-6s watched=%-5d awake=%-5d hot-but-off=%-3d unsettled=%-5s groups(awake/total) %s" % (key[0], key[1], row["watched"], row["awake"], row["violations"], row["unsettled"], groups))
        for key, (seconds, peak, polls) in sorted(latency_rows(report).items()):
            print("  wake latency %-22s %-6s hot-but-off gone after %s s, peak %d, %d polls" % (key[0], key[1], "never" if seconds is None else "%.2f" % seconds, peak, polls))
        if report is not baseline:
            differences = compare_reports(baseline, report)
            print("  labelled differences against %s: %d" % (baseline_path, len(differences)))
            for difference in differences[:12]:
                print("   ", json.dumps(difference))
    return 0
