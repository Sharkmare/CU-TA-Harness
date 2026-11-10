import glob
import hashlib
import json
import os

STATE_FILE_NAME = ".test_state.json"


def expand(root, patterns):
    files = set()
    for pattern in patterns:
        for path in glob.glob(os.path.join(root, pattern), recursive=True):
            if os.path.isfile(path):
                files.add(os.path.normpath(path))
    return sorted(files)


def fingerprint(root, patterns):
    digest = hashlib.sha256()
    for path in expand(root, patterns):
        digest.update(os.path.relpath(path, root).replace("\\", "/").encode())
        with open(path, "rb") as handle:
            digest.update(handle.read())
    return digest.hexdigest()


def group_fingerprint(root, config, group):
    return fingerprint(root, list(config["shared"]) + list(group["watch"]))


def load_state(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def save_state(path, state):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=1, sort_keys=True)


def validate(config):
    seen = set()
    for group in config["groups"]:
        if group["id"] in seen:
            raise ValueError("duplicate group %s" % group["id"])
        seen.add(group["id"])
        if not group.get("modules"):
            raise ValueError("group %s runs nothing" % group["id"])


def select(root, config, state, run_all=False, only=None):
    validate(config)
    chosen = []
    for group in config["groups"]:
        if only and group["id"] not in only:
            continue
        if not expand(root, group["watch"]):
            raise ValueError("group %s watches no existing file" % group["id"])
        recorded = state.get(group["id"])
        if run_all or only or recorded != group_fingerprint(root, config, group):
            chosen.append(group)
    return chosen
