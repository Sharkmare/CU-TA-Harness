"""Check the BepInEx logs of one launch of a friend package: python tools/package_log_check.py LOG_DIRECTORY [--expect-burst]

LOG_DIRECTORY holds host-LogOutput.log and client-LogOutput.log. Each log must show Together loaded once, CUCoreLib loaded once, the Body.Attack transpiler succeeding once, no RESYNCGUARD and
no STEAMLIKE text; the host log is read for the SWINGBURST lines. Exit code 1 when a check fails.
"""
import argparse
import json
import os
import re
import sys

SIDES = ("host", "client")
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+_MPv[\w.]+")
SWINGBURST_KINDS = (("dropped", "SWINGBURST dropped"), ("acceptedByCredit", "SWINGBURST accepted-by-credit"), ("summary", "SWINGBURST summary"))


def count(text, needle):
    return text.count(needle)


def check_log(text):
    versions = sorted(set(VERSION_PATTERN.findall(text)))
    return {"togetherLoaded": count(text, "Loading [Together "), "cucorelibLoaded": count(text, "Loading [CUCoreLib "), "attackTranspilerSuccess": count(text, "Body.Attack TRANSPILER SUCCESS"),
            "resyncGuardLines": count(text, "RESYNCGUARD"), "steamlikeLines": count(text, "STEAMLIKE"), "versions": versions,
            "swingBurst": {name: count(text, marker) for name, marker in SWINGBURST_KINDS}, "togetherLoadLine": next((line.strip() for line in text.splitlines() if "Loading [Together " in line), None)}


def problems(report):
    found = []
    for side in SIDES:
        data = report[side]
        if data["togetherLoaded"] != 1:
            found.append("%s: Together loaded %d times" % (side, data["togetherLoaded"]))
        if data["cucorelibLoaded"] != 1:
            found.append("%s: CUCoreLib loaded %d times" % (side, data["cucorelibLoaded"]))
        if data["attackTranspilerSuccess"] != 1:
            found.append("%s: Body.Attack transpiler success lines: %d" % (side, data["attackTranspilerSuccess"]))
        if data["resyncGuardLines"]:
            found.append("%s: %d RESYNCGUARD lines" % (side, data["resyncGuardLines"]))
        if data["steamlikeLines"]:
            found.append("%s: %d STEAMLIKE lines" % (side, data["steamlikeLines"]))
    if report["host"]["versions"] != report["client"]["versions"]:
        found.append("host and client log different version tags: %s against %s" % (report["host"]["versions"], report["client"]["versions"]))
    if not report["host"]["versions"]:
        found.append("no version tag in the host log")
    return found


def read(directory, side):
    with open(os.path.join(directory, "%s-LogOutput.log" % side), encoding="utf-8", errors="replace") as handle:
        return handle.read()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    parser.add_argument("--expect-burst", action="store_true", help="fail when the host log has no SWINGBURST line at all")
    arguments = parser.parse_args(argv)
    report = {side: check_log(read(arguments.directory, side)) for side in SIDES}
    found = problems(report)
    if arguments.expect_burst and not any(report["host"]["swingBurst"].values()):
        found.append("host: no SWINGBURST line")
    report["problems"] = found
    sys.stdout.write(json.dumps(report, indent=1) + "\n")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
