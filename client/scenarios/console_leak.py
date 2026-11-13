import secrets
import time

from casualtieslink.desync import Scenario

from scenarios import desync_scenarios as base
from scenarios import evidence_scenarios as evidence
from scenarios import hook_scenarios as hooks

GROUP = "console-leak"
NAME = "consoleleak_save_line_by_client"
CONSOLE_TAIL = 100
SETTLE_AFTER_SAVE_SECONDS = 2.0
ADMIN_WAIT_SECONDS = 8.0
POLL_SECONDS = 0.5
PASSWORD_BYTES = 9
SAVE_MARKER = "SAVING TO FILE"
SERVER_PREFIX_MARKER = "SERVER</color>]"
PATH_MARKERS = ("AppData", "LocalLow", "mp_save", "Users")
HOST_SET_PASSWORD_MARKER = "Set server admin password"
HOST_ENTER_MARKERS = ("ENTERS", "server console")
HOST_PASSWORD_COMMAND = "adminpriv-password"
CLIENT_ADMIN_COMMAND = "admin"


def describe_lines(lines):
    save_lines = [line for line in lines if SAVE_MARKER in line]
    server_lines = [line for line in lines if SERVER_PREFIX_MARKER in line]
    return {"consoleLines": len(lines), "savingToFileLines": len(save_lines), "serverPrefixedLines": len(server_lines),
            "savingLinesWithServerPrefix": len([line for line in save_lines if SERVER_PREFIX_MARKER in line]),
            "savingLinesContain": {marker: any(marker in line for line in save_lines) for marker in PATH_MARKERS},
            "serverLinesContain": {marker: any(marker in line for line in server_lines) for marker in PATH_MARKERS},
            "anyLineContains": {marker: any(marker in line for line in lines) for marker in PATH_MARKERS}}


def console_lines(game):
    try:
        lines = game.call("console_log", tail=CONSOLE_TAIL)
    except Exception as failure:
        return None, type(failure).__name__
    return [str(line) for line in lines], None


def log_count(which, marker):
    return sum(1 for line in evidence.read_log(which).splitlines() if marker in line)


def trigger_host_save(host):
    try:
        host.call("save")
        return {"replied": True}
    except Exception as failure:
        return {"replied": False, "errorType": type(failure).__name__}


def save_phase(name, host, client):
    host_marks = len(evidence.read_log("host").splitlines())
    client_marks = len(evidence.read_log("client").splitlines())
    reply = trigger_host_save(host)
    time.sleep(SETTLE_AFTER_SAVE_SECONDS)
    client_lines, client_error = console_lines(client)
    host_lines, host_error = console_lines(host)
    host_log = evidence.new_lines(host_marks, evidence.read_log("host"))
    client_log = evidence.new_lines(client_marks, evidence.read_log("client"))
    return {"phase": name, "saveReply": reply, "client": None if client_lines is None else describe_lines(client_lines), "clientReadError": client_error,
            "host": None if host_lines is None else describe_lines(host_lines), "hostReadError": host_error,
            "hostLogSavingLines": sum(1 for line in host_log if SAVE_MARKER in line), "clientLogSavingLines": sum(1 for line in client_log if SAVE_MARKER in line)}


def host_log_has_enter(lines):
    return any(all(marker in line for marker in HOST_ENTER_MARKERS) for line in lines)


def make_client_admin(host, client):
    password = secrets.token_urlsafe(PASSWORD_BYTES)
    host_marks = len(evidence.read_log("host").splitlines())
    result = {"passwordSet": False, "requested": False, "hostLogShowsEnter": False}
    try:
        output = host.call("console", line="%s %s" % (HOST_PASSWORD_COMMAND, password))
        result["passwordSet"] = any(HOST_SET_PASSWORD_MARKER in str(line) for line in (output or {}).get("output", []))
        result["hostCommandFailed"] = bool((output or {}).get("failed"))
    except Exception as failure:
        result["hostCommandErrorType"] = type(failure).__name__
    try:
        output = client.call("console", line="%s %s" % (CLIENT_ADMIN_COMMAND, password))
        result["requested"] = True
        result["clientCommandFailed"] = bool((output or {}).get("failed"))
    except Exception as failure:
        result["clientCommandErrorType"] = type(failure).__name__
    deadline = time.time() + ADMIN_WAIT_SECONDS
    while time.time() < deadline:
        if host_log_has_enter(evidence.new_lines(host_marks, evidence.read_log("host"))):
            result["hostLogShowsEnter"] = True
            break
        time.sleep(POLL_SECONDS)
    return result


def prepare(host, client):
    return {"position": None, "name": None, "host": host, "measurements": [], "target": {}}


def act(client, context):
    host = context["host"]
    normal = save_phase("normal-client", host, client)
    admin_step = make_client_admin(host, client)
    admin = save_phase("admin-client", host, client) if admin_step["hostLogShowsEnter"] else None
    context["measurements"] = [normal, {"phase": "admin-switch", **admin_step}] + ([admin] if admin else [])
    context["target"] = {"normal": normal, "adminStep": admin_step, "admin": admin}


def check(context):
    target = context.get("target") or {}
    normal, step, admin = target.get("normal"), target.get("adminStep"), target.get("admin")
    issues = []
    if normal is None or normal["client"] is None:
        return ["INVALID: the client console could not be read in the normal phase (%s)" % (normal or {}).get("clientReadError")]
    if normal["host"] is None or normal["host"]["savingToFileLines"] < 1:
        issues.append("INVALID: no SAVING TO FILE line on the host console after the save trigger in the normal phase, so that phase says nothing")
    if normal["client"]["savingToFileLines"] > 0 or normal["clientLogSavingLines"] > 0:
        issues.append("CLAIM REFUTED: a SAVING TO FILE line reached the NORMAL client (console %d, log %d)" % (normal["client"]["savingToFileLines"], normal["clientLogSavingLines"]))
    if not step or not step["hostLogShowsEnter"]:
        issues.append("INVALID: the host log never showed the client entering the server console (password set %s, requested %s)" % ((step or {}).get("passwordSet"), (step or {}).get("requested")))
        return issues
    if admin is None or admin["client"] is None:
        issues.append("INVALID: the client console could not be read in the admin phase")
        return issues
    if admin["client"]["savingToFileLines"] < 1:
        issues.append("CLAIM NOT SHOWN: no SAVING TO FILE line reached the ADMIN client although it entered the server console")
    return issues


def preflight(fragments, attempts, builds=()):
    if NAME not in base.matching_scenario_names(fragments):
        return []
    checks = [(CONSOLE_TAIL >= 1, "the console tail is below one"), (SETTLE_AFTER_SAVE_SECONDS > 0, "the settle time after a save is not positive"),
              (SAVE_MARKER != "", "the save marker is empty")]
    return [message for holds, message in checks if not holds]


base.PREFLIGHTS.append(preflight)

SCENARIOS = [
    Scenario(NAME, "the host saves the world while the client is a normal player and again after the client entered admin mode with a password set on the host; whether the host's SAVING TO FILE console line reaches the client console and the client log, redacted to counts and booleans",
             prepare, act, lambda game, context: 0, hooks.never_changes, offsets=(0.0,), group=GROUP, check=check),
]

base.SCENARIOS.extend(SCENARIOS)
