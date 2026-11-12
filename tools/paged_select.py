import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HARNESS, "client"))

from casualtieslink import instances, pagedselect

STATE_ROOT = os.path.join(HARNESS, ".state")
DEFAULT_SESSION_DIRECTORY = os.path.join(STATE_ROOT, "paged_select")
DEFAULT_PORT = instances.HOST_PORT


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run a singleplayer game from a copy with the friends zip plugin set and a test character pack, until a stop file appears in the session folder.")
    parser.add_argument("--zip-md5", required=True, help="the md5 the friends zip must have")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--characters", type=int, default=4, help="characters in the test pack")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--session-directory", default=DEFAULT_SESSION_DIRECTORY)
    arguments = parser.parse_args(argv)
    pagedselect.run_session(arguments.session_directory, os.path.join(STATE_ROOT, "paged_select_snapshots"), arguments.port, arguments.width, arguments.height,
                            arguments.characters, arguments.zip_md5, instances.mods_root())
    return 0


if __name__ == "__main__":
    sys.exit(main())
