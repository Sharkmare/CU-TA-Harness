import ast
import glob
import hashlib
import json
import os

STATE_FILE_NAME = ".test_state.json"
STATE_VERSION = 2
PLUGIN_WATCH = ["../plugin/*.cs", "../plugin/*.csproj"]
COMMAND_UNIT_PREFIX = "cmd:"


def unit_id(unit):
    if isinstance(unit, dict):
        return COMMAND_UNIT_PREFIX + unit["id"]
    return unit


def expand(root, patterns):
    files = set()
    for pattern in patterns:
        for path in glob.glob(os.path.join(root, pattern), recursive=True):
            if os.path.isfile(path):
                files.add(os.path.normpath(path))
    return sorted(files)


def file_hash(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read().replace(b"\r\n", b"\n")).hexdigest()


def module_path(search_roots, module):
    relative = module.replace(".", os.sep)
    for root in search_roots:
        for candidate in (relative + ".py", os.path.join(relative, "__init__.py")):
            path = os.path.join(root, candidate)
            if os.path.isfile(path):
                return os.path.normpath(path)
    return None


def package_initialisers(search_roots, module):
    parts = module.split(".")
    found = []
    for length in range(1, len(parts)):
        path = module_path(search_roots, ".".join(parts[:length]))
        if path:
            found.append(path)
    return found


def imported_modules(path, module):
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    is_package = os.path.basename(path) == "__init__.py"
    package = module if is_package else module.rpartition(".")[0]
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".") if package else []
                anchor = anchor[:len(anchor) - (node.level - 1)] if node.level > 1 else anchor
                base = ".".join(anchor + ([node.module] if node.module else []))
            if base:
                names.add(base)
                for alias in node.names:
                    names.add(base + "." + alias.name)
    return names


def dependency_files(search_roots, module):
    seen_modules = set()
    files = set()
    pending = [module]
    while pending:
        current = pending.pop()
        if current in seen_modules:
            continue
        seen_modules.add(current)
        path = module_path(search_roots, current)
        if path is None:
            continue
        files.add(path)
        files.update(package_initialisers(search_roots, current))
        pending.extend(imported_modules(path, current) - seen_modules)
    return sorted(files)


def unit_files(root, search_roots, group, unit):
    if isinstance(unit, dict):
        return expand(root, unit["watch"])
    files = set(dependency_files(search_roots, unit))
    if group.get("watch_plugin"):
        files.update(expand(root, PLUGIN_WATCH))
    return sorted(files)


def hashes_of(root, files):
    return {os.path.relpath(path, root).replace("\\", "/"): file_hash(path) for path in files}


def load_state(path):
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return {}
    if state.get("version") != STATE_VERSION:
        return {}
    return state.get("units", {})


def save_state(path, units):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": STATE_VERSION, "units": units}, handle, indent=1, sort_keys=True)


def validate(config):
    seen = set()
    for group in config["groups"]:
        if group["id"] in seen:
            raise ValueError("duplicate group %s" % group["id"])
        seen.add(group["id"])
        if not group.get("modules"):
            raise ValueError("group %s runs nothing" % group["id"])


def changed_files(recorded, current):
    if recorded is None:
        return ["never passed"]
    names = sorted(set(recorded) | set(current))
    return [name for name in names if recorded.get(name) != current.get(name)]


def select_units(root, search_roots, config, state, run_all=False, only=None, offline=False):
    validate(config)
    selected = []
    for group in config["groups"]:
        if only and group["id"] not in only:
            continue
        if offline and (group.get("needs_game") or group.get("owns_game")):
            continue
        chosen = []
        for unit in group["modules"]:
            files = unit_files(root, search_roots, group, unit)
            if not files:
                raise ValueError("unit %s of group %s has no files to watch" % (unit_id(unit), group["id"]))
            current = hashes_of(root, files)
            reasons = changed_files(state.get(unit_id(unit)), current)
            if run_all or only or reasons:
                chosen.append({"unit": unit, "reasons": ["forced"] if (run_all or only) and not reasons else reasons, "hashes": current})
        if chosen:
            selected.append({"group": group, "units": chosen})
    return selected


def record_pass(state, unit_entry):
    state[unit_id(unit_entry["unit"])] = unit_entry["hashes"]


def record_failure(state, unit_entry):
    state.pop(unit_id(unit_entry["unit"]), None)
