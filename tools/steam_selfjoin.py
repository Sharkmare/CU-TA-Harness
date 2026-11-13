"""Steam self-join experiment: two harness game copies, one account, the Steam transport. Usage: python tools/steam_selfjoin.py --label NAME [--stage-choice pr24-3d060fe-plain-stage] [--dry-run]

Safety rules the script enforces before it launches anything:
  - harness copies only (instances.ScenarioGames makes them under TEMP), never the installed game folder;
  - the host lobby type is "private" and the host has a throwaway password (--mp-setpass); the stage DLL is decompiled first and refused when its CreateLobby forces a public lobby;
  - Steam credentials and the Steam client settings are never touched; no invites are sent.
The machine-wide game lock is held for the whole run and the profile and PlayerPrefs are restored at the end.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPOSITORY_ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "client"))

from casualtieslink import instances
from casualtieslink.launcher import GameProcess, mp_arguments
from casualtieslink.lock import GameLock
from scenarios.desync_scenarios import ready_up

DEFAULT_STAGE_CHOICE = "pr24-3d060fe-plain-stage"
LOBBY_TYPE = "private"
THROWAWAY_PASSWORD = "throwaway-selfjoin"
STEAM_TRANSPORT_TYPE = "static:Together.TransportSteamworks"
LOBBY_ID_PATTERN = re.compile(r"\b(1\d{17})\b")
LOBBY_WAIT_SECONDS = 90.0
JOIN_WAIT_SECONDS = 90.0
POLL_SECONDS = 1.0
SMOKE_SECONDS = 60.0
STEP_PATTERNS = (
    ("lobby created", r"LobbyCreated|Create Lobby|Creating Lobby|CreateLobby"),
    ("lobby join attempt", r"joinlobby|OnWantToJoinLobby|Starting client and attempting join|JoinLobby|LobbyEnter"),
    ("p2p connect", r"ConnectP2P|connection request|OnConnectionStatusChanged|Accepting connection|was accepted"),
    ("connection closed", r"Connection closed|ClosedByPeer|ProblemDetectedLocally|end reason|EndReason"),
    ("handshake", r"[Ww]elcome|handshake|Handshake"),
    ("version or identity mismatch", r"Mismatching|mismatch|identity|Identity|invalid password|Invalid password|wrong password"),
    ("steam transport", r"TransportSteamworks|SteamNetworkingSockets|STEAM:"),
    ("real time status", r"GetConnectionRealTimeStatus|ping_ms|m_nPing|pending unreliable|connection quality"),
)
STAGE_DIRECTORY_BY_CHOICE = {"pr24-3d060fe-plain-stage": instances.pr24_tip_plain_stage_directory}


LOBBY_ID_PATHS = (("static:Together.KSteam", "CURRENT_LOBBY.lobby_steamID.m_SteamID"), ("static:Together.KSteam", "LobbyId.m_SteamID"), ("static:Together.KSteam", "CURRENT_LOBBY.lobby_steamID"))


def lobby_id_from_link(game, paths=LOBBY_ID_PATHS):
    """The id of the lobby the host created, read through the link from the mod's own lobby state; None until it exists."""
    for target, path in paths:
        try:
            value = game.get(target, path, depth=0)
        except Exception:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool) and int(value) > 0:
            return int(value)
        if isinstance(value, str) and value.isdigit() and int(value) > 0:
            return int(value)
    try:
        lobby = game.get("static:Together.KSteam", "CURRENT_LOBBY", depth=4)
    except Exception:
        return None
    nested = (lobby or {}).get("lobby_steamID") if isinstance(lobby, dict) else None
    value = nested.get("m_SteamID") if isinstance(nested, dict) else None
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and int(value) > 0 else None


def lobby_id_from_text(text):
    """The first Steam lobby id (an 18 digit number starting with 1) on a line that mentions a lobby."""
    for line in text.splitlines():
        if "obby" in line:
            found = LOBBY_ID_PATTERN.search(line)
            if found:
                return int(found.group(1))
    return None


def steps_from_logs(logs, patterns=STEP_PATTERNS, per_step=6):
    """For every step the first matching lines of each log: {step: {side: [line, ...]}}."""
    steps = {}
    for name, pattern in patterns:
        expression = re.compile(pattern)
        steps[name] = {side: [line.strip()[-240:] for line in text.splitlines() if expression.search(line)][:per_step] for side, text in logs.items()}
    return steps


def stage_problems(together_directory, decompile):
    """Refuse a stage whose CreateLobby overrides the lobby type with a public one. decompile(path, type) returns the decompiled text of the type."""
    dll = os.path.join(together_directory, "plugins", "Together", "CasualtiesMP.dll")
    if not os.path.isfile(dll):
        return ["the stage DLL %s does not exist" % dll]
    text = decompile(dll, "Together.TransportSteamworks")
    start = text.find("internal bool CreateLobby(")
    if start < 0:
        return ["TransportSteamworks.CreateLobby was not found in the decompiled stage"]
    body = text[start:start + 1500]
    if "k_ELobbyTypePublic" in body:
        return ["CreateLobby of this stage forces a public lobby"]
    if "SteamMatchmaking.CreateLobby(lobbyType" not in body:
        return ["CreateLobby does not pass the requested lobby type through"]
    return []


def decompile_with_ilspy(dll, type_name):
    result = subprocess.run(["ilspycmd", "-t", type_name, dll], capture_output=True, text=True, timeout=180)
    return result.stdout


def lobby_type_is_not_private(chosen):
    """_STEAM_CHOSEN_LOBBYTYPE is 0 for private, 1 friends only, 2 public. A value the link could not read is not proof of anything and does not abort (the compiled stage was checked for the private mapping)."""
    return isinstance(chosen, (int, float)) and not isinstance(chosen, bool) and chosen != 0


def host_arguments(password):
    return mp_arguments({"setname": "HostS", "verbose": True, "immidiate-start": True, "setpass": password}) + ["--mp-hoststeam", LOBBY_TYPE]


def client_arguments(password):
    return mp_arguments({"setname": "ClientS", "verbose": True, "setpass": password})


def read_log(directory):
    try:
        with open(os.path.join(directory, "BepInEx", "LogOutput.log"), encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def wait_for(condition, timeout, poll=POLL_SECONDS):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(poll)
    return None


def link_read(game, target, path):
    try:
        return game.get(target, path, depth=1)
    except Exception as failure:
        return {"unreadable": str(failure)[:160]}


def body_count(game):
    try:
        return len(game.call("find", type="Body"))
    except Exception as failure:
        return "unreadable: %s" % str(failure)[:80]


def smoke(games, seconds, interval=5.0):
    """Both bodies visible on both games every few seconds for `seconds`; the link reads give the proof that the two copies see each other over the Steam transport."""
    readings = []
    started = time.time()
    while time.time() - started < seconds:
        readings.append({"t": round(time.time() - started, 1), "hostSees": body_count(games.host.game), "clientSees": body_count(games.client.game)})
        time.sleep(interval)
    return {"readings": readings, "bothSeeBothAlways": all(item["hostSees"] == 2 and item["clientSees"] == 2 for item in readings)}


def run(label, stage_choice, dry_run, output_directory):
    stage_directory = STAGE_DIRECTORY_BY_CHOICE[stage_choice]()
    problems = stage_problems(stage_directory, decompile_with_ilspy)
    record = {"label": label, "stage": stage_directory, "stageChoice": stage_choice, "lobbyType": LOBBY_TYPE, "stageProblems": problems, "outcome": None, "steps": {}}
    if problems:
        record["outcome"] = "REFUSED BEFORE LAUNCH"
        return record
    if dry_run:
        record["outcome"] = "DRY RUN OK"
        return record
    lock = GameLock("steam_selfjoin.py").acquire()
    games = instances.ScenarioGames(os.path.join(REPOSITORY_ROOT, ".state"))
    try:
        games.prepare()
        games.configure_host([], stage_choice)
        games.configure_client([], stage_choice)
        games.host = GameProcess(instances.HOST_PORT, host_arguments(THROWAWAY_PASSWORD), directory=games.host_copy, manage_save=False,
                                 window_args=["-screen-fullscreen", "0", "-screen-width", "640", "-screen-height", "360"])
        games.host.start(instances.START_TIMEOUT_SECONDS, allow_existing=True)
        record["hostStarted"] = True
        lobby_id = wait_for(lambda: lobby_id_from_link(games.host.game) or lobby_id_from_text(read_log(games.host_copy)), LOBBY_WAIT_SECONDS)
        record["lobbyId"] = lobby_id
        record["hostLobbyRead"] = link_read(games.host.game, "static:Together.KSteam", "CURRENT_LOBBY")
        chosen = link_read(games.host.game, "static:Together.UIMainMenu", "_STEAM_CHOSEN_LOBBYTYPE")
        record["lobbyTypeRead"] = chosen
        if lobby_type_is_not_private(chosen):
            record["outcome"] = "ABORTED: the host lobby type reads %r, not private (0); the client was not started" % (chosen,)
            return record
        if lobby_id is None:
            record["outcome"] = "HUNG: no lobby id in the host log within %.0f s" % LOBBY_WAIT_SECONDS
            return record
        games.client = GameProcess(instances.CLIENT_PORT, client_arguments(THROWAWAY_PASSWORD), directory=games.client_copy, manage_save=False,
                                   window_args=["-screen-fullscreen", "0", "-screen-width", "640", "-screen-height", "360"])
        games.client.start(instances.START_TIMEOUT_SECONDS, allow_existing=True)
        record["joinCall"] = games.client.game.call("invoke", target=STEAM_TRANSPORT_TYPE, method="OnWantToJoinLobby", args=[lobby_id], types=["UInt64"])
        try:
            record["readyUp"] = bool(ready_up([games.host.game, games.client.game], timeout=JOIN_WAIT_SECONDS))
            games.host.game.wait_state("in-world", timeout=JOIN_WAIT_SECONDS)
            games.client.game.wait_state("in-world", timeout=JOIN_WAIT_SECONDS)
            joined = True
        except Exception as failure:
            joined = False
            record["joinWaitError"] = str(failure)[:200]
        record["clientInWorld"] = joined
        if joined:
            record["smoke"] = smoke(games, SMOKE_SECONDS)
        record["outcome"] = "CONNECTED" if joined else "HUNG: the client did not reach the world within %.0f s" % JOIN_WAIT_SECONDS
        return record
    finally:
        record["logs"] = {"host": read_log(games.host_copy)[-60000:], "client": read_log(games.client_copy)[-60000:]}
        record["steps"] = steps_from_logs(record["logs"])
        games.dispose()
        lock.release()
        os.makedirs(output_directory, exist_ok=True)
        with open(os.path.join(output_directory, "%s.json" % label), "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--stage-choice", default=DEFAULT_STAGE_CHOICE, choices=sorted(STAGE_DIRECTORY_BY_CHOICE))
    parser.add_argument("--dry-run", action="store_true", help="only the safety checks, no game")
    parser.add_argument("--out", default=os.path.join(REPOSITORY_ROOT, ".state", "steam_selfjoin"))
    arguments = parser.parse_args(argv)
    record = run(arguments.label, arguments.stage_choice, arguments.dry_run, arguments.out)
    print(json.dumps({key: record[key] for key in record if key not in ("logs", "steps")}, indent=1, default=str))
    return 0 if record["outcome"] in ("CONNECTED", "DRY RUN OK") else 1


if __name__ == "__main__":
    sys.exit(main())
