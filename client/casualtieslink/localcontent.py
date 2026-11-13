"""Optional local content: a gitignored folder `local/` at the repository root that extends this repository.

The tracked tree must run and pass without it. What it can hold (all optional, all mirrored on the client layout):
  local/scenarios/, local/live/, local/unit/, local/casualtieslink/<package>/  modules that join the tracked packages of the same name
  local/test_groups.json   groups merged into client/test_groups.json (same id: its modules are appended)
  local/builds.json        the build and plugin set registry read by casualtieslink.games.buildregistry
  local/env.json           environment variable defaults, applied with setdefault
  local/scenarios.json     {"modules": [...]}: scenario modules imported, in this order, when the scenario registry is built
  local/profiles/          result table profiles for tools/pr_table.py
  local/mutants.json       mutants appended to tools/mutants.json
CU_LOCAL_DIR points the whole mechanism at another folder.
"""
import importlib
import json
import os

LOCAL_DIRECTORY_ENVIRONMENT_VARIABLE = "CU_LOCAL_DIR"
LOCAL_DIRECTORY_NAME = "local"
ENVIRONMENT_FILE = "env.json"
TEST_GROUPS_FILE = "test_groups.json"


def repository_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def local_directory():
    return os.environ.get(LOCAL_DIRECTORY_ENVIRONMENT_VARIABLE) or os.path.join(repository_root(), LOCAL_DIRECTORY_NAME)


def extend_package(package_name, package_path):
    """Let a tracked package also import the modules in the same-named folder under local/."""
    candidate = os.path.join(local_directory(), *package_name.split("."))
    if os.path.isdir(candidate) and candidate not in package_path:
        package_path.append(candidate)


def read_json(file_name, default=None):
    path = os.path.join(local_directory(), file_name)
    if not os.path.isfile(path):
        return default
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def apply_environment_defaults():
    for name, value in (read_json(ENVIRONMENT_FILE, {}) or {}).items():
        os.environ.setdefault(name, os.path.expanduser(value))


def merged_test_groups(config):
    local = read_json(TEST_GROUPS_FILE, None)
    if not local:
        return config
    groups = [dict(group) for group in config["groups"]]
    by_id = {group["id"]: group for group in groups}
    for extra in local["groups"]:
        if extra["id"] in by_id:
            by_id[extra["id"]]["modules"] = list(by_id[extra["id"]]["modules"]) + list(extra["modules"])
        else:
            groups.append(extra)
    return dict(config, groups=groups)


def import_scenario_modules():
    """Import the scenario modules local/scenarios.json lists; each one registers its scenarios by extending scenarios.desync_scenarios.SCENARIOS or SERIES_SCENARIOS."""
    for name in (read_json("scenarios.json", {}) or {}).get("modules", []):
        importlib.import_module("scenarios." + name)
