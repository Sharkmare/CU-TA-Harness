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
COPIED_FOLDERS = ("plugin", "plugin-tests", "client", "tools", "docs")
COPIED_FILES = ("README.md",)
IGNORED = ("bin", "obj", "__pycache__", "*.dll", ".test_state.json")
CLIENT_REPORTS_FOLDER = "reports"
MUTANT_TIMEOUT_SECONDS = 90
MODS_ROOT_ENVIRONMENT_VARIABLE = "CU_MODS_ROOT"
LINK_DLL_ENVIRONMENT_VARIABLE = "CU_LINK_DLL"
BUILT_LINK_DLL = os.path.join(REPO, "plugin", "bin", "CasualtiesLink.dll")
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


def suite_environment():
    environment = dict(os.environ)
    environment.setdefault(MODS_ROOT_ENVIRONMENT_VARIABLE, os.path.dirname(REPO))
    environment.setdefault(LINK_DLL_ENVIRONMENT_VARIABLE, BUILT_LINK_DLL)
    return environment


def run_suite(suite, root):
    command, cwd = suite_command(suite, root)
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=MUTANT_TIMEOUT_SECONDS, env=suite_environment())
    except subprocess.TimeoutExpired:
        return None, ""
    return completed.returncode, completed.stdout + completed.stderr


def control_run(scratch, suite):
    root = os.path.join(scratch, "control-" + suite)
    os.makedirs(root)
    copy_tree(root)
    returncode, output = run_suite(suite, root)
    if returncode == 0:
        return True, ""
    return False, "timed out" if returncode is None else first_failure(suite, output) or output.strip()[-200:]


def ignored_names(directory, names):
    skipped = set(shutil.ignore_patterns(*IGNORED)(directory, names))
    if os.path.basename(directory) == "client" and CLIENT_REPORTS_FOLDER in names:
        skipped.add(CLIENT_REPORTS_FOLDER)
    return skipped


def copy_tree(root):
    for folder in COPIED_FOLDERS:
        shutil.copytree(os.path.join(REPO, folder), os.path.join(root, folder), ignore=ignored_names)
    for name in COPIED_FILES:
        shutil.copy(os.path.join(REPO, name), os.path.join(root, name))


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
    returncode, output = run_suite(mutant["suite"], root)
    if returncode is None:
        return "caught", "tests hung for %ds" % MUTANT_TIMEOUT_SECONDS
    return ("caught" if returncode != 0 else "SURVIVED"), first_failure(mutant["suite"], output)


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
        for suite in sorted({mutant["suite"] for mutant in mutants}):
            passes, detail = control_run(scratch, suite)
            if not passes:
                print("CONTROL FAILED  the unmutated %s suite fails in its scratch copy, so no mutant can be judged: %s" % (suite, detail))
                return 2
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
