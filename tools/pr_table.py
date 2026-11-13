"""Print the compact result tables of a PR profile: python tools/pr_table.py client/profiles/corpse-fix.json [--format text|fenced|markdown|both]"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPOSITORY_ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "client"))

from casualtieslink.reports import prtable


def emit(text):
    """Write the text as ASCII bytes with LF line endings, so the output pastes the same on every platform."""
    sys.stdout.buffer.write(text.encode("ascii"))
    sys.stdout.buffer.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", help="profile file, for example client/profiles/corpse-fix.json")
    parser.add_argument("--format", choices=("text", "fenced", "markdown", "both"), default="text")
    parser.add_argument("--root", default=REPOSITORY_ROOT, help="the directory the profile's source patterns are relative to (default: the repository root)")
    arguments = parser.parse_args(argv)
    result = prtable.build_result(prtable.load_profile(arguments.profile), arguments.root)
    if arguments.format == "fenced":
        emit(prtable.render_fenced(result))
    if arguments.format in ("text", "both"):
        emit(prtable.render_text(result))
    if arguments.format == "both":
        emit("\n")
    if arguments.format in ("markdown", "both"):
        emit(prtable.render_markdown(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
