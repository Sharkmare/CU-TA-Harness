import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "client"))

from casualtieslink import miningsummary, pr24log

FIRST_LINES = 6
LONG_RUN_SWINGS = 10


def main(argv=None):
    parser = argparse.ArgumentParser(description="Per mining run counts from the [PR24V] lines of the client log, partitioned by the swings each report fired.")
    parser.add_argument("reports_directory")
    parser.add_argument("client_log")
    arguments = parser.parse_args(argv)
    rows = miningsummary.summarise_directory(arguments.reports_directory)
    with open(arguments.client_log, encoding="utf-8", errors="replace") as handle:
        swings = pr24log.parse_swings(handle.read())
    runs, leftover = pr24log.split_by_counts(swings, [row["swingsFired"] for row in rows])
    print("log swings %d, report swings %d, left over %d" % (len(swings), sum(row["swingsFired"] for row in rows), leftover))
    for row, run in zip(rows, runs):
        print(json.dumps({"run": row["repetition"], "verdict": row["verdict"], "block": row["block"], "reach": row["firstDistance"], **pr24log.summarise(run)}))
        if row["swingsFired"] > LONG_RUN_SWINGS or row["verdict"] == "never-broke":
            for swing in run[:FIRST_LINES]:
                print("    " + " | ".join(swing["raw"])[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())
