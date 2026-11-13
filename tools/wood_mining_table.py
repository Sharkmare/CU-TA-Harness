"""Compact result table of the wood block mining launches at the cooldown rate: python tools/wood_mining_table.py D=.state/wood_fd_reports:d100-j100 E=.state/wood_fe_reports:d100-j100 [--format text|markdown] [--runs]

Each argument is LABEL=REPORT_DIRECTORY:NETWORK, the network being the d<delay>-j<jitter> part of the report file names. --runs prints the per-run bunching evidence instead of the summary.
"""
import argparse
import glob
import json
import os
import statistics
import sys

HEADERS = ("variant", "client", "network", "valid", "REVERSION", "swings per run", "client swing interval s (min / median / max)", "host arrival spacing s (min, estimated)",
           "arrivals under 0.124 s", "host cooldown drops (host log) / predicted", "host swings applied vs client", "scraps per break (client / host)")
RUN_HEADERS = ("run", "verdict", "swings", "client interval s (min / median / max)", "host arrival spacing s (min / median / max)", "arrivals under 0.124 s", "predicted host drops",
               "host cooldown drops (host log)", "SWINGBURST dropped / credit", "RESYNCGUARD kept / applied after window", "client broke s", "host broke s", "exposure window s",
               "client block back at s (gone for)", "block at end of tail (client / host)", "client swings applied", "host swings applied")
MISSING = "-"


def pre_damaged(report):
    return [side for side in ("host", "client") if report["baseline"][side][1] > 0]


def load_runs(directory, network):
    """The reports of one variant; a run whose cell held damage before the first swing is invalid whatever the report says (reports from before that rule are re-judged here)."""
    runs = []
    for path in sorted(glob.glob(os.path.join(directory, "wood_mining_*__%s_r*.json" % network))):
        with open(path, encoding="utf-8") as handle:
            report = json.load(handle)
        report["_name"] = os.path.basename(path)
        left_over = pre_damaged(report)
        if left_over and report["woodRun"]["verdict"] != "invalid":
            report["woodRun"] = dict(report["woodRun"], verdict="invalid", reasons=list(report["woodRun"]["reasons"]) + ["the %s already held damage for the cell before the first swing" % " and ".join(left_over)])
        runs.append(report)
    return runs


def join_unique(values):
    ordered = []
    for value in values:
        if value not in ordered:
            ordered.append(value)
    return ", ".join(str(value) for value in ordered) if ordered else MISSING


def triple(distribution):
    return MISSING if not distribution else "%.3f / %.3f / %.3f" % (distribution["min"], distribution["median"], distribution["max"])


def scraps_made(run):
    scraps = run["woodRun"]["scraps"]
    before, end = scraps.get("before") or {}, scraps.get("end") or {}
    return {side: (end[side] - before[side]) if end.get(side) is not None and before.get(side) is not None else None for side in ("client", "host")}


def interval_extremes(valid):
    """Smallest, median of the medians and largest client swing interval over the valid runs."""
    distributions = [run["woodRun"]["bunching"]["clientIntervals"] for run in valid if run["woodRun"]["bunching"]["clientIntervals"]]
    if not distributions:
        return MISSING
    return "%.3f / %.3f / %.3f" % (min(item["min"] for item in distributions), statistics.median(item["median"] for item in distributions), max(item["max"] for item in distributions))


def summarize(label, runs, client_name, network):
    valid = [run for run in runs if run["woodRun"]["verdict"] != "invalid"]
    reversions = [run for run in valid if run["woodRun"]["verdict"] == "reversion"]
    timing = "; ".join("%.2f s after the break" % run["woodRun"]["clientReappeared"][0]["goneFor"] for run in reversions)
    invalid = len(runs) - len(valid)
    spacing_min = [run["woodRun"]["bunching"]["hostArrivalSpacings"]["min"] for run in valid if run["woodRun"]["bunching"]["hostArrivalSpacings"]]
    under = sum(run["woodRun"]["bunching"]["arrivalsUnderCooldown"] for run in valid)
    estimated = sum(run["woodRun"]["bunching"]["arrivalsEstimated"] for run in valid)
    log_drops = sum((run.get("hostLog") or {}).get("cooldownDrops", 0) for run in valid)
    predicted = sum(run["woodRun"]["bunching"]["predictedHostDrops"] for run in valid)
    applied_client = sum(run["woodRun"]["damage"]["clientSwingsApplied"] for run in valid)
    applied_host = sum(run["woodRun"]["damage"]["hostSwingsApplied"] for run in valid)
    made = [scraps_made(run) for run in valid]
    return [label, client_name, network, "%d/%d%s" % (len(valid), len(runs), "" if not invalid else " (%d invalid)" % invalid),
            ("%d%s" % (len(reversions), " (%s)" % timing if timing else "")) if valid else MISSING,
            join_unique(run["woodRun"]["swingsFired"] for run in valid), interval_extremes(valid),
            MISSING if not spacing_min else "%.3f" % min(spacing_min), "%d of %d" % (under, estimated), "%d / %d" % (log_drops, predicted), "%d vs %d" % (applied_host, applied_client),
            join_unique("%s / %s" % (item["client"], item["host"]) for item in made)]


def end_blocks(run):
    last = run["samples"][-1] if run.get("samples") else None
    return MISSING if last is None else "%s / %s" % (last["client"][0], last["host"][0])


def burst_cell(run):
    counts = (run.get("swingBurst") or {}).get("counts") or {}
    return "%s / %s" % (counts.get("dropped", MISSING), counts.get("acceptedByCredit", MISSING))


def guard_cell(run):
    totals = (run.get("resyncGuard") or {}).get("summaryTotals") or {}
    counts = (run.get("resyncGuard") or {}).get("counts") or {}
    kept = max(counts.get("kept", 0), totals.get("kept-through-resync", 0))
    return "%d / %s" % (kept, totals.get("applied-after-window", MISSING))


def window_cell(wood):
    if wood.get("clientBrokeAt") is None or wood.get("hostBrokeAt") is None:
        return MISSING
    return "%.2f" % (wood["hostBrokeAt"] - wood["clientBrokeAt"])


def run_rows(runs):
    rows = []
    for run in runs:
        wood = run["woodRun"]
        bunching = wood["bunching"]
        reappeared = wood.get("clientReappeared") or []
        rows.append([run["_name"].split("__")[-1][:-5], wood["verdict"] + ("" if not wood["reasons"] else ": " + "; ".join(wood["reasons"])), wood["swingsFired"], triple(bunching["clientIntervals"]),
                     triple(bunching["hostArrivalSpacings"]), bunching["arrivalsUnderCooldown"], bunching["predictedHostDrops"], (run.get("hostLog") or {}).get("cooldownDrops", MISSING),
                     burst_cell(run), guard_cell(run), wood.get("clientBrokeAt", MISSING), wood.get("hostBrokeAt", MISSING), window_cell(wood),
                     MISSING if not reappeared else "%.2f (%.2f s)" % (reappeared[0]["t"], reappeared[0]["goneFor"]), end_blocks(run), wood["damage"]["clientSwingsApplied"],
                     wood["damage"]["hostSwingsApplied"]])
    return rows


def render_text(headers, rows):
    grid = [headers] + rows
    widths = [max(len(str(row[index])) for row in grid) for index in range(len(headers))]
    return "\n".join("  ".join(str(cell).ljust(widths[index]) for index, cell in enumerate(row)).rstrip() for row in grid) + "\n"


def render_markdown(headers, rows):
    def escape(value):
        return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("<", "\\<").replace(">", "\\>")
    lines = ["| " + " | ".join(escape(header) for header in headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(escape(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variants", nargs="+", help="LABEL=DIRECTORY:NETWORK")
    parser.add_argument("--format", choices=("text", "markdown"), default="text")
    parser.add_argument("--runs", action="store_true", help="the per-run bunching evidence")
    arguments = parser.parse_args(argv)
    render = render_markdown if arguments.format == "markdown" else render_text
    chunks = []
    summary = []
    for item in arguments.variants:
        label, rest = item.split("=", 1)
        directory, network = rest.rsplit(":", 1)
        runs = load_runs(directory, network)
        client_name = {2: "Dune", 0: "Experiment"}.get((runs[0]["woodRun"]["identities"] or {}).get("clientWanted")) if runs else MISSING
        if arguments.runs:
            chunks.append(("%s (%s, %s)" % (label, client_name, network), run_rows(runs)))
        else:
            summary.append(summarize(label, runs, client_name, network))
    if arguments.runs:
        text = "\n".join(("**%s**\n\n" % title if arguments.format == "markdown" else title + "\n") + render(RUN_HEADERS, rows) for title, rows in chunks)
    else:
        text = render(HEADERS, summary)
    sys.stdout.buffer.write(text.encode("ascii", "replace"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
