import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "client"))

from casualtieslink import miningsummary


def main(argv=None):
    parser = argparse.ArgumentParser(description="One row per mining run from a reports folder, with counts and the shown cause of every never-broke run.")
    parser.add_argument("directory")
    arguments = parser.parse_args(argv)
    rows = miningsummary.summarise_directory(arguments.directory)
    for row in rows:
        print(json.dumps(row, default=str))
    print(json.dumps(miningsummary.counts(rows)))
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
