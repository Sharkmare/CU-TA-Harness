import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "client"))

from casualtieslink import miningsummary, pr24log

FIRST_LINES = 6
WINDOW_BEFORE_SECONDS = 3.0
WINDOW_AFTER_SECONDS = 1.5
SECONDS_PER_DAY = 86400


def local_utc_offset_seconds():
    return datetime.datetime.now().astimezone().utcoffset().total_seconds()


def run_windows(rows, utc_offset_seconds):
    windows = []
    for row in rows:
        if row["endLocalSeconds"] is None or row["durationSeconds"] is None:
            windows.append((1.0, 0.0))
            continue
        end = (row["endLocalSeconds"] - utc_offset_seconds) % SECONDS_PER_DAY
        windows.append((end - row["durationSeconds"] - WINDOW_BEFORE_SECONDS, end + WINDOW_AFTER_SECONDS))
    return windows


def main(argv=None):
    parser = argparse.ArgumentParser(description="Per mining run counts from the [PR24V] lines of a client log, partitioned by each report's wall clock window.")
    parser.add_argument("reports_directory")
    parser.add_argument("client_log")
    parser.add_argument("--utc-offset-hours", type=float, default=None, help="local time minus the log clock (default: this machine's offset)")
    arguments = parser.parse_args(argv)
    offset = local_utc_offset_seconds() if arguments.utc_offset_hours is None else arguments.utc_offset_hours * 3600
    rows = miningsummary.summarise_directory(arguments.reports_directory)
    with open(arguments.client_log, encoding="utf-8", errors="replace") as handle:
        swings = pr24log.parse_swings(handle.read())
    runs = pr24log.split_by_windows(swings, run_windows(rows, offset))
    print("log swing lines %d, assigned to runs %d, report swings %d" % (len(swings), sum(len(run) for run in runs), sum(row["swingsFired"] for row in rows)))
    for row, run in zip(rows, runs):
        print(json.dumps({"run": row["repetition"], "verdict": row["verdict"], "block": row["block"], "reach": row["firstDistance"], "reportSwings": row["swingsFired"], **pr24log.summarise(run)}))
        if row["verdict"] != "persisted" or row["swingsFired"] > 10:
            for swing in run[:FIRST_LINES]:
                print("    " + " | ".join(swing["raw"])[:420])
    return 0


if __name__ == "__main__":
    sys.exit(main())
