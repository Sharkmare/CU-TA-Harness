import json
import re

from casualtieslink import desync

CUSTOM_CHARACTER = 3
EXPERIMENT_CHARACTER = 0
PVP_RULE_ARGUMENTS = ["--mp-setrule", "PVP", "1"]
PRE_RUN_TYPE = "PreRunScript"
PAGER_TYPES = ("CharacterPager", "PagedCharacterCounter", "PagedCharacterArrow")
TAG_TYPE = "CharacterIdTag"
SYNC_BODY_TYPE = "SyncBody"
PLAYER_TYPE = "ScavPlayer"
CUSTOM_COMPONENT_TYPE = "CustomCharacter"
SAMPLE_CHARACTERS = 600
TAG_ID_FIELDS = ("Id", "id", "CharacterId", "characterId", "value", "Value")
PATCH_MARKERS = ("Failed to patch", "IL Compile Error", "Mismatching version")
LOADER_LOG_PATTERN = re.compile(r"character select|character\(s\)|fingerprint|Together with character support|Together without character support|character table|characters? (?:applied|registered)", re.I)
BODY_PREFIX = "Body_"


def launch_counts(text):
    lines = text.splitlines()
    return {"attackTranspilerSuccess": sum(1 for line in lines if desync.TRANSPILER_SUCCESS in line),
            "markersNotFound": sum(1 for line in lines if desync.TRANSPILER_MISSING_MARKERS in line),
            "patchProblemLines": [line.strip()[:200] for line in lines if any(marker in line for marker in PATCH_MARKERS)],
            "exceptionLines": [line.strip()[:200] for line in desync.new_exception_lines("", text)]}


def loader_log_lines(text):
    return [line.strip()[:200] for line in text.splitlines() if LOADER_LOG_PATTERN.search(line)]


def object_rows(game, type_name):
    try:
        return [(row["object"]["id"], row["object"]["name"]) for row in game.call("find", type=type_name)]
    except Exception:
        return []


def short_dump(game, handle):
    try:
        return json.dumps(game.get(handle, "", depth=1), default=str)[:SAMPLE_CHARACTERS]
    except Exception as failure:
        return "unreadable: %s" % type(failure).__name__


def read_optional(game, handle, path):
    try:
        return game.get(handle, path, depth=0)
    except Exception:
        return None


def pager_state(game):
    return {type_name: [{"name": name, "dump": short_dump(game, "id:%d" % identifier)} for identifier, name in object_rows(game, type_name)] for type_name in PAGER_TYPES}


def select_character(game, character_id):
    rows = object_rows(game, PRE_RUN_TYPE)
    if not rows:
        return {"selected": False, "reason": "no PreRunScript object", "characterSelected": read_optional(game, "static:" + PRE_RUN_TYPE, "characterSelected")}
    game.call("invoke", target="id:%d" % rows[0][0], method="SelectCharacter", args=[character_id])
    return {"selected": True, "characterSelected": read_optional(game, "static:" + PRE_RUN_TYPE, "characterSelected")}


def player_rows(game):
    return [{"name": name, "customCharacter": read_optional(game, "id:%d" % identifier, "customCharacter")} for identifier, name in object_rows(game, PLAYER_TYPE)]


def tag_rows(game):
    rows = []
    for identifier, name in object_rows(game, TAG_TYPE):
        handle = "id:%d" % identifier
        value = next(((field, read_optional(game, handle, field)) for field in TAG_ID_FIELDS if isinstance(read_optional(game, handle, field), int)), (None, None))
        rows.append({"name": name, "field": value[0], "id": value[1], "dump": short_dump(game, handle)})
    return rows


def sync_body_rows(game):
    return [{"name": name, "dump": short_dump(game, "id:%d" % identifier)} for identifier, name in object_rows(game, SYNC_BODY_TYPE)]


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
    return {"players": player_rows(game), "tags": tag_rows(game), "syncBodies": sync_body_rows(game), "loaderComponents": loader_components(game),
            "bodySpecies": body_species(game), "characterSelected": read_optional(game, "static:" + PRE_RUN_TYPE, "characterSelected")}


def custom_pick_issues(host_state, client_state, custom_id, client_body, host_body):
    issues = []
    client_ids = sorted(row["customCharacter"] for row in client_state["players"] if row["customCharacter"] is not None)
    host_ids = sorted(row["customCharacter"] for row in host_state["players"] if row["customCharacter"] is not None)
    if custom_id not in client_ids:
        issues.append("the client's players do not include custom id %d (read %s)" % (custom_id, client_ids))
    if custom_id not in host_ids:
        issues.append("the host's ScavPlayer rows do not include custom id %d (read %s)" % (custom_id, host_ids))
    for label, state in (("host", host_state), ("client", client_state)):
        if state["loaderComponents"].get(client_body) != custom_id:
            issues.append("the loader's CustomCharacter on %s is %s on the %s machine, expected %d" % (client_body, state["loaderComponents"].get(client_body), label, custom_id))
        tagged = [row["id"] for row in state["tags"] if row["id"] is not None]
        if custom_id not in tagged:
            issues.append("no CharacterIdTag with id %d on the %s machine (read %s)" % (custom_id, label, tagged))
    base = [state["bodySpecies"].get(client_body) for state in (host_state, client_state)]
    reference = host_state["bodySpecies"].get(host_body)
    if base[0] is None or base[0] != base[1]:
        issues.append("the client body species differs between machines (host %s, client %s)" % tuple(base))
    if reference is None or base[0] != reference:
        issues.append("the client body species %s is not the Experiment species of the host body (%s)" % (base[0], reference))
    return issues
