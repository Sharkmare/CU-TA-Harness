import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TOOLS)
MUTANTS_PATH = os.path.join(TOOLS, "mutants.json")
COPIED_FOLDERS = ("plugin", "plugin-tests", "client", "tools")
IGNORED = ("bin", "obj", "__pycache__", "reports", "*.dll", ".test_state.json")
MUTANT_TIMEOUT_SECONDS = 90
GROUPS_RELATIVE = os.path.join("client", "test_groups.json")
OFFLINE_GROUP = "client-offline"


def offline_python_modules(root):
    with open(os.path.join(root, GROUPS_RELATIVE), encoding="utf-8") as handle:
        groups = json.load(handle)["groups"]
    return next(group["modules"] for group in groups if group["id"] == OFFLINE_GROUP)


def suite_command(suite, root):
    if suite == "plugin":
        return ["dotnet", "run", "--project", os.path.join(root, "plugin-tests"), "-c", "Release", "--nologo", "-v", "q"], root
    if suite == "python":
        return [sys.executable, "-m", "unittest"] + offline_python_modules(root), os.path.join(root, "client")
    raise ValueError("unknown suite %r" % suite)


def copy_tree(root):
    for folder in COPIED_FOLDERS:
        shutil.copytree(os.path.join(REPO, folder), os.path.join(root, folder), ignore=shutil.ignore_patterns(*IGNORED))


def first_failure(suite, output):
    for line in output.splitlines():
        if line.startswith("FAIL") or line.startswith("ERROR"):
            return line[:100]
    return ""


def run_mutant(scratch, index, mutant):
    root = os.path.join(scratch, str(index))
    os.makedirs(root)
    copy_tree(root)
    path = os.path.join(root, mutant["file"])
    with open(path, encoding="utf-8") as handle:
        text = handle.read().replace("\r\n", "\n")
    if text.count(mutant["old"]) != 1:
        return "ANCHOR", "anchor found %d times" % text.count(mutant["old"])
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text.replace(mutant["old"], mutant["new"]))
    command, cwd = suite_command(mutant["suite"], root)
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=MUTANT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return "caught", "tests hung for %ds" % MUTANT_TIMEOUT_SECONDS
    output = completed.stdout + completed.stderr
    return ("caught" if completed.returncode != 0 else "SURVIVED"), first_failure(mutant["suite"], output)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Break the code on purpose in scratch copies and check that the offline tests notice.")
    parser.add_argument("--suite", choices=("plugin", "python"), default=None)
    parser.add_argument("--match", default=None, help="only mutants whose label contains this text")
    arguments = parser.parse_args(argv)
    with open(MUTANTS_PATH, encoding="utf-8") as handle:
        mutants = json.load(handle)
    mutants = [m for m in mutants if (arguments.suite is None or m["suite"] == arguments.suite) and (arguments.match is None or arguments.match in m["label"])]
    scratch = tempfile.mkdtemp(prefix="mutants_")
    problems = 0
    try:
        for index, mutant in enumerate(mutants):
            status, detail = run_mutant(scratch, index, mutant)
            problems += status != "caught"
            print("%-9s %-7s %-46s %s" % (status, mutant["suite"], mutant["label"], detail), flush=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print("%d of %d mutants caught" % (len(mutants) - problems, len(mutants)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
