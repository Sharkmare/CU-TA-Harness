import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HARNESS, "client"))

from casualtieslink import lock
from casualtieslink.games import recovery

STATE_ROOT = os.path.join(HARNESS, ".state")


def main(argv=None):
    parser = argparse.ArgumentParser(description="After an aborted game run: stop stray games, restore the profile and PlayerPrefs from a snapshot, delete the scenario copies and the stale lock. "
                                                 "Copy any raw game logs you need out of the copies first.")
    parser.add_argument("--stamp", default=None, help="snapshot stamp (default: the latest snapshot, taken at the start of the aborted run)")
    arguments = parser.parse_args(argv)
    print(json.dumps(recovery.recover(STATE_ROOT, lock.LOCK_PATH, arguments.stamp)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
