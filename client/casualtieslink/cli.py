import argparse
import json
import os
import sys
import time

from .commands import Game
from .launcher import GameAlreadyRunning, GameProcess, mp_arguments
from .parsing import LinkError, find_command, missing_required, parse_key_values
from .transport import default_port


def build_parser():
    parser = argparse.ArgumentParser(prog="casualtieslink", description="Drive a running Casualties: Unknown through CasualtiesLink.")
    parser.add_argument("--port", type=int, default=None, help="link port (default CASUALTIES_LINK_PORT or 7650)")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("status", help="plugin status")
    describe = commands.add_parser("describe", help="list commands, or one command's arguments")
    describe.add_argument("name", nargs="?")
    call = commands.add_parser("call", help="call a link command with key=value arguments (values parse as JSON when they can)")
    call.add_argument("name")
    call.add_argument("pairs", nargs="*")
    events = commands.add_parser("events", help="print events since a sequence number")
    events.add_argument("--since", type=int, default=0)
    events.add_argument("--wait-ms", type=int, default=0)
    events.add_argument("--type", default=None)
    launch = commands.add_parser("launch", help="start the game with the link, keep it open until Enter, then close it")
    launch.add_argument("--stop-file", default=None, help="close the game when this file appears (for background use)")
    launch.add_argument("--mp", nargs="*", default=[], metavar="FLAG[=VALUE]", help="Together mod flags, e.g. starthost setname=Alice")
    return parser


def parse_mp_flags(items):
    flags = {}
    for item in items:
        name, _, value = item.partition("=")
        flags[name] = value if value else True
    return flags


def print_json(value):
    print(json.dumps(value, indent=2, sort_keys=True))


def run(arguments):
    game = Game(arguments.port)
    if arguments.action == "status":
        print_json(game.status())
    elif arguments.action == "describe":
        description = game.describe()
        if arguments.name:
            spec = find_command(description, arguments.name)
            if spec is None:
                raise LinkError("no command %r" % arguments.name)
            print_json(spec)
        else:
            for command in description["commands"]:
                names = ", ".join(("%s*" if a["required"] else "%s") % a["name"] for a in command["args"])
                print("%-16s %s  (%s)" % (command["name"], command["doc"], names))
    elif arguments.action == "call":
        values = parse_key_values(arguments.pairs)
        spec = find_command(game.describe(), arguments.name)
        if spec is not None and missing_required(spec, values):
            raise LinkError("missing required arguments: %s" % ", ".join(missing_required(spec, values)))
        print_json(game.call(arguments.name, **values))
    elif arguments.action == "events":
        print_json(game.transport.events(arguments.since, arguments.wait_ms, arguments.type))
    elif arguments.action == "launch":
        port = arguments.port if arguments.port is not None else default_port()
        process = GameProcess(port, mp_arguments(parse_mp_flags(arguments.mp)))
        print_json(process.start())
        try:
            if arguments.stop_file:
                while not os.path.exists(arguments.stop_file):
                    time.sleep(1.0)
                os.remove(arguments.stop_file)
            else:
                input("game is running; press Enter to close it\n")
        finally:
            process.close()


def main(argv=None):
    try:
        run(build_parser().parse_args(argv))
    except (LinkError, GameAlreadyRunning, OSError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    return 0
