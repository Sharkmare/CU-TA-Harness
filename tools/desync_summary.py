import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "client"))

from casualtieslink import launchsummary

DEFAULT_DIRECTORY = os.path.join(os.path.dirname(HERE), ".state", "desync_reports")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Summarise the reports of one desync launch per network profile.")
    parser.add_argument("launch_id")
    parser.add_argument("--directory", default=DEFAULT_DIRECTORY)
    arguments = parser.parse_args(argv)
    reports = launchsummary.load_reports(arguments.directory, arguments.launch_id)
    if not reports:
        print("no reports for launch %s in %s" % (arguments.launch_id, arguments.directory))
        return 1
    print(launchsummary.format_summary(arguments.launch_id, launchsummary.summarise_launch(reports)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
