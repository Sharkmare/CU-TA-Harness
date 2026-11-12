import json
import re
import time

from casualtieslink import desync

CUSTOM_CHARACTER = 3
EXPERIMENT_CHARACTER = 0
EXPERIMENT_CHARTYPE = 0
PVP_RULE_ARGUMENTS = ["--mp-setrule", "PVP", "1"]
PRE_RUN_TYPE = "PreRunScript"
PLAYER_TYPE = "ScavPlayer"
NAMESPACE_PREFIXES = ("", "Together.")
PLAYER_STATIC = "static:Together.ScavPlayer"
MENU_STATIC = "static:CasualtiesCharacters.CharacterMenu"
TAG_TYPE = "CharacterIdTag"
NET_BODY_TYPE = "NetBody"
CUSTOM_COMPONENT_TYPE = "CustomCharacter"
SAMPLE_CHARACTERS = 700
TAG_ID_FIELDS = ("Id", "id", "CharacterId", "characterId", "value", "Value")
PATCH_MARKERS = ("Failed to patch", "IL Compile Error", "Mismatching version")
LOADER_LOG_PATTERN = re.compile(r"character select|character\(s\)|fingerprint|Together with character support|Together without character support|character table|character \d+ \(", re.I)
FINGERPRINT_PATTERN = re.compile(r"character table fingerprint (\S+)")
BODY_PREFIX = "Body_"
PAGER_PATHS = {"page": "view.Page", "pageCount": "view.Pager.PageCount", "registered": "view.Pager.RegisteredCount", "counterText": "view.Counter.text",
               "nextArrowActive": "view.NextArrow.activeSelf", "previousArrowActive": "view.PreviousArrow.activeSelf", "lastSelected": "view.LastSelected"}
JOIN_ATTEMPT_SECONDS = 1.0
LOOKUP_ERRORS = []


def launch_counts(text):
    lines = text.splitlines()
    return {"attackTranspilerSuccess": sum(1 for line in lines if desync.TRANSPILER_SUCCESS in line),
            "markersNotFound": sum(1 for line in lines if desync.TRANSPILER_MISSING_MARKERS in line),
            "patchProblemLines": [line.strip()[:200] for line in lines if any(marker in line for marker in PATCH_MARKERS)],
            "exceptionLines": [line.strip()[:200] for line in desync.new_exception_lines("", text)]}


def loader_log_lines(text):
    return [line.strip()[:200] for line in text.splitlines() if LOADER_LOG_PATTERN.search(line)]


def fingerprints(text):
    return FINGERPRINT_PATTERN.findall(text)


def object_rows(game, type_name):
    for prefix in NAMESPACE_PREFIXES:
        try:
            rows = [(row["object"]["id"], row["object"]["name"]) for row in game.call("find", type=prefix + type_name)]
        except Exception as failure:
            LOOKUP_ERRORS.append("find %s%s: %s" % (prefix, type_name, str(failure)[:100]))
            continue
        if rows:
            return rows
    return []


def short_dump(game, handle, path="", depth=1):
    try:
        return json.dumps(game.call("get", target=handle, path=path, depth=depth, nonpublic=True), default=str)[:SAMPLE_CHARACTERS]
    except Exception as failure:
        return "unreadable: %s" % type(failure).__name__


def read_optional(game, handle, path, nonpublic=False):
    try:
        if nonpublic:
            return game.call("get", target=handle, path=path, depth=0, nonpublic=True)
        return game.get(handle, path, depth=0)
    except Exception:
        return None


def pager_state(game):
    state = {name: read_optional(game, MENU_STATIC, path, nonpublic=True) for name, path in PAGER_PATHS.items()}
    state["menuPresent"] = any(value is not None for value in state.values())
    return state


def select_character(game, character_id):
    rows = object_rows(game, PRE_RUN_TYPE)
    if not rows:
        return {"selected": False, "reason": "no PreRunScript object", "characterSelected": read_optional(game, "static:" + PRE_RUN_TYPE, "characterSelected")}
    game.call("invoke", target="id:%d" % rows[0][0], method="SelectCharacter", args=[character_id])
    return {"selected": True, "characterSelected": read_optional(game, "static:" + PRE_RUN_TYPE, "characterSelected")}


def player_custom_ids(game):
    rows = [{"name": name, "customCharacter": read_optional(game, "id:%d" % identifier, "customCharacter")} for identifier, name in object_rows(game, PLAYER_TYPE)]
    local = read_optional(game, PLAYER_STATIC, "LocalPlayer.customCharacter")
    return {"rows": rows, "localPlayer": local, "ids": sorted({row["customCharacter"] for row in rows if isinstance(row["customCharacter"], int)} | ({local} if isinstance(local, int) else set()))}


def tag_rows(game):
    rows = {}
    for identifier, name in object_rows(game, TAG_TYPE):
        handle = "id:%d" % identifier
        for field in TAG_ID_FIELDS:
            value = read_optional(game, handle, field)
            if isinstance(value, int):
                rows[name] = value
                break
    return rows


def keys_with_custom(node, found=None, trail=""):
    found = {} if found is None else found
    if isinstance(node, dict):
        for key, value in node.items():
            here = trail + "." + str(key) if trail else str(key)
            if re.search(r"ustom|haracter", str(key)):
                found[here] = value
            keys_with_custom(value, found, here)
    return found


def sync_body_values(game):
    result = {}
    for identifier, name in object_rows(game, NET_BODY_TYPE):
        try:
            dump = game.call("get", target="id:%d" % identifier, path="syncBody", depth=2, nonpublic=True)
        except Exception as failure:
            result[name] = {"unreadable": type(failure).__name__}
            continue
        result[name] = keys_with_custom(dump)
    return result


def loader_components(game):
    result = {}
    for identifier, name in object_rows(game, CUSTOM_COMPONENT_TYPE):
        handle = "id:%d" % identifier
        body = read_optional(game, handle, "Body")
        result[(body or {}).get("name", name)] = read_optional(game, handle, "Id")
    return result


def body_species(game):
    species = {}
    for identifier, name in object_rows(game, "Body"):
        if name.startswith(BODY_PREFIX):
            species[name] = read_optional(game, "id:%d" % identifier, "charType")
    return species


def character_state(game):
    return {"players": player_custom_ids(game), "tags": tag_rows(game), "syncBodies": sync_body_values(game), "loaderComponents": loader_components(game),
            "bodySpecies": body_species(game), "characterSelected": read_optional(game, "static:" + PRE_RUN_TYPE, "characterSelected"), "pager": pager_state(game)}


def numbers_in(values):
    found = set()
    for value in values:
        if isinstance(value, dict):
            found |= numbers_in(value.values())
        elif isinstance(value, int) and not isinstance(value, bool):
            found.add(value)
    return found


def pick_issues(host_state, client_state, expected):
    issues = []
    for label, state in (("host", host_state), ("client", client_state)):
        readable = state["players"]["ids"]
        for body, character in expected.items():
            if character and character not in readable:
                issues.append("ScavPlayer.customCharacter on the %s machine does not include %d for %s (read %s)" % (label, character, body, readable))
            if state["tags"].get(body) != character:
                issues.append("CharacterIdTag of %s is %s on the %s machine, expected %d" % (body, state["tags"].get(body), label, character))
            loader = state["loaderComponents"].get(body)
            if character and loader != character:
                issues.append("the loader's CustomCharacter on %s is %s on the %s machine, expected %d" % (body, loader, label, character))
            if not character and loader is not None:
                issues.append("the loader attached a custom character to %s on the %s machine (id %s), expected a plain pick" % (body, label, loader))
            if state["bodySpecies"].get(body) != EXPERIMENT_CHARTYPE:
                issues.append("%s has species %s on the %s machine, expected Experiment (%d)" % (body, state["bodySpecies"].get(body), label, EXPERIMENT_CHARTYPE))
    return issues


def sync_body_issues(state, expected):
    readable = {body: numbers_in(values.values()) for body, values in state["syncBodies"].items() if isinstance(values, dict) and "unreadable" not in values}
    return {body: (character in readable.get(body, set())) for body, character in expected.items() if character}


def custom_pick_issues(host_state, client_state, custom_id, client_body, host_body):
    return pick_issues(host_state, client_state, {client_body: custom_id, host_body: EXPERIMENT_CHARACTER})


def join_attempts(game, character_id, ready, repick=True, in_world=None, timeout=150.0, clock=time.time, sleep=time.sleep):
    attempts = []
    deadline = clock() + timeout
    while clock() < deadline:
        if in_world(game):
            attempts.append({"inWorld": True})
            return attempts
        entry = {"pick": select_character(game, character_id) if repick else None, "ready": ready(game)}
        attempts.append(entry)
        sleep(JOIN_ATTEMPT_SECONDS)
    return attempts
