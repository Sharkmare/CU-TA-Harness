"""Compact result table of the wood block mining launches: python tools/wood_mining_table.py A=.state/wood_dune_reports:d0-j0 B=.state/wood_dune_reports:d50-j60 C=.state/wood_exp_reports:d50-j60 [--format text|markdown]

Each argument is LABEL=REPORT_DIRECTORY:NETWORK, the network being the d<delay>-j<jitter> part of the report file names.
"""
import argparse
import glob
import json
import os
import statistics
import sys

HEADERS = ("variant", "client", "network", "valid", "REVERSION", "swings", "swing interval s", "damage per swing", "broke at swing", "scraps per break", "host damage = client damage at every swing", "host log drops")
MISSING = "-"


def load_runs(directory, network):
    runs = []
    for path in sorted(glob.glob(os.path.join(directory, "wood_mining_*__%s_r*.json" % network))):
        with open(path, encoding="utf-8") as handle:
            runs.append(json.load(handle))
    return runs


def damage_per_swing(run):
    """The rise of the client's damage for the cell per swing, read after each swing, up to the swing that broke the block."""
    previous = 0.0
    steps = []
    for entry in run["woodSwings"]:
        if entry["client"]["block"] == 0:
            break
        steps.append(entry["client"]["damage"] - previous)
        previous = entry["client"]["damage"]
    return statistics.median(steps) if steps else None


def broke_at_swing(run):
    for entry in run["woodSwings"]:
        if entry["client"]["block"] == 0:
            return entry["swing"]
    return None


def scraps_made(run):
    """The most woodscraps near the cell seen in any sample minus the count before the run; scraps of earlier runs stay in the world, so the count before is subtracted."""
    before = (run["woodRun"].get("scraps") or {}).get("before") or {}
    made = {}
    for side in ("client", "host"):
        seen = [sample[side][3] for sample in run["samples"] if len(sample[side]) > 3 and sample[side][3] is not None]
        made[side] = (max(seen) - before[side]) if seen and before.get(side) is not None else None
    return made


def host_matches_client(run):
    return all(abs(entry["host"]["damage"] - entry["client"]["damage"]) < 0.05 for entry in run["woodSwings"])


def join_unique(values):
    ordered = []
    for value in values:
        if value not in ordered:
            ordered.append(value)
    return "/".join(str(value) for value in ordered) if ordered else MISSING


def summarize(label, runs, client_name, network):
    valid = [run for run in runs if run["woodRun"]["verdict"] != "invalid"]
    reversions = [run for run in valid if run["woodRun"]["verdict"] == "reversion"]
    timing = "; ".join("%.2f s after the break" % run["woodRun"]["clientReappeared"][0]["goneFor"] for run in reversions)
    intervals = [value for run in valid for value in run["swings"]["clientIntervals"]]
    spacing = MISSING if not intervals else "%.2f to %.2f (mean %.2f)" % (min(intervals), max(intervals), statistics.mean(intervals))
    damage = [damage_per_swing(run) for run in valid]
    made = [scraps_made(run) for run in valid]
    drops = [run["woodRun"]["hostEventCounts"]["cooldown"] for run in valid]
    invalid = len(runs) - len(valid)
    return [label, client_name, network, "%d/%d%s" % (len(valid), len(runs), "" if not invalid else " (%d invalid)" % invalid),
            ("%d%s" % (len(reversions), " (%s)" % timing if timing else "")) if valid else MISSING,
            join_unique(run["woodRun"]["swingsFired"] for run in valid), spacing, join_unique("%.2f" % value for value in damage if value is not None),
            join_unique(broke_at_swing(run) for run in valid),
            join_unique("%s client/%s host" % (item["client"], item["host"]) for item in made),
            "%d/%d runs" % (len([run for run in valid if host_matches_client(run)]), len(valid)), join_unique(drops)]


def render_text(rows):
    grid = [HEADERS] + rows
    widths = [max(len(str(row[index])) for row in grid) for index in range(len(HEADERS))]
    return "\n".join("  ".join(str(cell).ljust(widths[index]) for index, cell in enumerate(row)).rstrip() for row in grid) + "\n"


def render_markdown(rows):
    def escape(value):
        return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("<", "\\<").replace(">", "\\>")
    lines = ["| " + " | ".join(HEADERS) + " |", "|" + "|".join("---" for _ in HEADERS) + "|"]
    lines.extend("| " + " | ".join(escape(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variants", nargs="+", help="LABEL=DIRECTORY:NETWORK")
    parser.add_argument("--format", choices=("text", "markdown"), default="text")
    arguments = parser.parse_args(argv)
    rows = []
    for item in arguments.variants:
        label, rest = item.split("=", 1)
        directory, network = rest.rsplit(":", 1)
        runs = load_runs(directory, network)
        client_name = {2: "Dune", 0: "Experiment"}.get((runs[0]["woodRun"]["identities"] or {}).get("clientWanted")) if runs else MISSING
        rows.append(summarize(label, runs, client_name, network))
    text = render_markdown(rows) if arguments.format == "markdown" else render_text(rows)
    sys.stdout.buffer.write(text.encode("ascii", "replace"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
