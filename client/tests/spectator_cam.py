import math
import time

from casualtieslink.desync import Scenario

from . import desync_scenarios as base
from . import hook_scenarios as hooks
from . import static_copy as static

GROUP = "spectator"
NAME = "spectatorcam_follow_by_client"
CLIENT_PLAYER_NAME = "ClientD"
HOST_BODY_NAME = "Body_HostD"
SAMPLE_STEP_SECONDS = 0.25
PHASE_SECONDS = 6.0
NEAR_COLUMNS = (15.0, -15.0, 18.0, -18.0, 12.0, -12.0, 20.0, -20.0)
FAR_COLUMNS = (45.0, -45.0, 50.0, -50.0, 55.0, -55.0, 40.0, -40.0)
MIN_START_DISTANCE = 10.0
SETTLE_AFTER_MOVE_SECONDS = 1.5
DEATH_WAIT_SECONDS = 5.0
SPECTATOR_WAIT_SECONDS = 2.0
POLL_SECONDS = 0.25
CLOSE_TO_TARGET = 3.0
CLOSE_AFTER_JUMP = 5.0
FAR_FROM_TARGET = 10.0
UI_TYPE = "static:Together.UIInGame"
SPECTATOR_TYPE = "static:Together.Spectator"
CAMERA_TYPE = "static:PlayerCamera"
KILL_COMMAND = "kill"
FOLLOWS = "FOLLOWS"
BUG_PRESENT = "BUG PRESENT"
INCONCLUSIVE = "INCONCLUSIVE"
INVALID = "INVALID"


def point_of(value):
    if isinstance(value, dict) and "x" in value and "y" in value:
        return {"x": float(value["x"]), "y": float(value["y"])}
    return None


def distance(first, second):
    if first is None or second is None:
        return None
    return math.hypot(first["x"] - second["x"], first["y"] - second["y"])


def safe_get(game, target, path, nonpublic=False):
    try:
        return game.call("get", target=target, path=path, depth=0, nonpublic=nonpublic)
    except Exception as failure:
        return {"readError": type(failure).__name__}


def read_sample(client, started, handles):
    camera = point_of(safe_get(client, CAMERA_TYPE, "main.transform.position"))
    target = point_of(safe_get(client, handles["hostBody"], "transform.position"))
    dead = point_of(safe_get(client, "player", base.BODY_PATH))
    spectator_target = safe_get(client, SPECTATOR_TYPE, "SpectatorTarget", nonpublic=True)
    look = safe_get(client, CAMERA_TYPE, "main.customLookPos")
    return {"t": round(time.time() - started, 2), "camera": camera, "target": target, "deadBody": dead,
            "cameraToTarget": None if distance(camera, target) is None else round(distance(camera, target), 2),
            "cameraToDeadBody": None if distance(camera, dead) is None else round(distance(camera, dead), 2),
            "targetToDeadBody": None if distance(target, dead) is None else round(distance(target, dead), 2),
            "spectatorModeActive": safe_get(client, UI_TYPE, "SpectatorModeActive"),
            "targetNonNull": spectator_target is not None and not (isinstance(spectator_target, dict) and "readError" in spectator_target),
            "customLookPos": look, "frame": safe_get(client, "static:Time", "frameCount"), "focused": safe_get(client, "static:Application", "isFocused")}


def sample_phase(client, handles, seconds=PHASE_SECONDS, step=SAMPLE_STEP_SECONDS):
    started = time.time()
    samples = []
    while time.time() - started < seconds:
        samples.append(read_sample(client, started, handles))
        time.sleep(step)
    return samples


def last_with_distances(samples):
    for sample in reversed(samples):
        if sample["cameraToTarget"] is not None and sample["cameraToDeadBody"] is not None:
            return sample
    return None


def first_with_distances(samples):
    for sample in samples:
        if sample["cameraToTarget"] is not None and sample["cameraToDeadBody"] is not None:
            return sample
    return None


def camera_moved(samples):
    positions = [sample["camera"] for sample in samples if sample["camera"] is not None]
    return any(distance(positions[0], position) > 0.05 for position in positions[1:]) if len(positions) > 1 else False


def frames_advanced(samples):
    frames = [sample["frame"] for sample in samples if isinstance(sample["frame"], (int, float))]
    return len(frames) > 1 and frames[-1] > frames[0]


def verdict_from(before_jump, after_jump):
    end_b, start_c, end_c = last_with_distances(before_jump), first_with_distances(after_jump), last_with_distances(after_jump)
    if end_b is None or end_c is None or start_c is None:
        return {"verdict": INVALID, "reason": "the camera, target or dead body position could not be read in every phase"}
    detail = {"endOfFirstPhase": {"cameraToTarget": end_b["cameraToTarget"], "cameraToDeadBody": end_b["cameraToDeadBody"], "targetToDeadBody": end_b["targetToDeadBody"]},
              "afterJump": {"firstCameraToTarget": start_c["cameraToTarget"], "lastCameraToTarget": end_c["cameraToTarget"], "lastCameraToDeadBody": end_c["cameraToDeadBody"],
                            "lastTargetToDeadBody": end_c["targetToDeadBody"]},
              "cameraMovedFirstPhase": camera_moved(before_jump), "cameraMovedAfterJump": camera_moved(after_jump),
              "framesAdvanced": frames_advanced(before_jump) and frames_advanced(after_jump)}
    relocated = distance(end_b["camera"], end_c["camera"]) is not None and distance(end_b["camera"], end_c["camera"]) > FAR_FROM_TARGET
    detail["cameraRelocatedAcrossTheJump"] = relocated
    follows = (end_b["cameraToTarget"] <= CLOSE_TO_TARGET and end_c["cameraToTarget"] <= CLOSE_AFTER_JUMP
               and (end_c["cameraToTarget"] < start_c["cameraToTarget"] or relocated))
    bug = (end_b["cameraToDeadBody"] <= CLOSE_TO_TARGET and end_b["cameraToTarget"] > FAR_FROM_TARGET
           and end_c["cameraToDeadBody"] <= CLOSE_TO_TARGET and end_c["cameraToTarget"] > FAR_FROM_TARGET)
    if follows and bug:
        return dict(detail, verdict=INVALID, reason="both verdict rules matched, the target and the dead body are the same place")
    if follows:
        return dict(detail, verdict=FOLLOWS)
    if bug:
        return dict(detail, verdict=BUG_PRESENT)
    return dict(detail, verdict=INCONCLUSIVE, reason="the camera is neither at the target nor at the dead body at the end of both phases")


def find_pocket(host, origin, columns):
    half_width = int(host.get("world", "halfWidth", depth=0))
    saved = static.FAR_COLUMNS
    static.FAR_COLUMNS = columns
    try:
        return static.find_far_pocket(host, origin, half_width)
    finally:
        static.FAR_COLUMNS = saved


def move_host(host, pocket, settle=True):
    host.set("player", base.BODY_PATH, {"x": pocket["x"], "y": pocket["y"], "z": 0.0})
    if settle:
        time.sleep(SETTLE_AFTER_MOVE_SECONDS)


def is_dead(client):
    alive = safe_get(client, "player", "alive")
    return alive is False


def kill_client(host, client):
    result = {"method": None, "dead": False}
    try:
        output = host.call("console", line="%s %s" % (KILL_COMMAND, CLIENT_PLAYER_NAME))
        result["hostCommandFailed"] = bool((output or {}).get("failed"))
        result["method"] = "host console kill"
    except Exception as failure:
        result["hostCommandErrorType"] = type(failure).__name__
    deadline = time.time() + DEATH_WAIT_SECONDS
    while time.time() < deadline and not is_dead(client):
        time.sleep(POLL_SECONDS)
    if not is_dead(client):
        try:
            client.set("player", "brainHealth", 0)
            client.set("player", "heartRate", 0)
            result["method"] = "client brainHealth and heartRate set to 0"
        except Exception as failure:
            result["clientSetErrorType"] = type(failure).__name__
        deadline = time.time() + DEATH_WAIT_SECONDS
        while time.time() < deadline and not is_dead(client):
            time.sleep(POLL_SECONDS)
    result["dead"] = is_dead(client)
    return result


def enter_spectator(client):
    deadline = time.time() + SPECTATOR_WAIT_SECONDS
    while time.time() < deadline:
        if safe_get(client, UI_TYPE, "SpectatorModeActive") is True:
            return {"active": True, "startedBy": "the game"}
        time.sleep(POLL_SECONDS)
    try:
        client.call("invoke", target=UI_TYPE, method="StartSpectatorMode", args=[], types=[])
    except Exception as failure:
        return {"active": False, "startedBy": None, "errorType": type(failure).__name__}
    return {"active": safe_get(client, UI_TYPE, "SpectatorModeActive") is True, "startedBy": "link call to UIInGame.StartSpectatorMode"}


def set_target(client, handle):
    try:
        client.call("invoke", target=UI_TYPE, method="Spectator_SetTarget", args=[handle, None], types=["Component", "String"])
        return {"method": "UIInGame.Spectator_SetTarget(host body)", "ok": True}
    except Exception as failure:
        return {"method": "UIInGame.Spectator_SetTarget(host body)", "ok": False, "errorType": type(failure).__name__}


def prepare(host, client):
    return {"position": None, "name": None, "host": host, "measurements": [], "target": {}}


def act(client, context):
    host = context["host"]
    log = context["target"]
    origin = base.player_position(client)
    near = find_pocket(host, origin, NEAR_COLUMNS)
    if near is None:
        log["setupError"] = "no open pocket 12 to 20 tiles from the client for the host"
        return
    move_host(host, near)
    log["hostHandleOnClient"] = base.body_handle_by_name(client, HOST_BODY_NAME)
    handles = {"hostBody": log["hostHandleOnClient"]}
    start_gap = distance(point_of(safe_get(client, handles["hostBody"], "transform.position")), base.player_position(client))
    log["hostToClientAtStart"] = None if start_gap is None else round(start_gap, 2)
    if start_gap is None or start_gap < MIN_START_DISTANCE:
        log["setupError"] = "the host is only %s tiles from the client body, below %.0f" % (log["hostToClientAtStart"], MIN_START_DISTANCE)
        return
    log["kill"] = kill_client(host, client)
    log["spectator"] = enter_spectator(client)
    log["target"] = set_target(client, handles["hostBody"])
    time.sleep(SETTLE_AFTER_MOVE_SECONDS)
    first = sample_phase(client, handles)
    far = find_pocket(host, base.player_position(client), FAR_COLUMNS)
    if far is None:
        log["setupError"] = "no open pocket 40 to 55 tiles from the client body for the host"
        log["samplesFirst"] = first
        return
    move_host(host, far, settle=False)
    second = sample_phase(client, handles)
    log["samplesFirst"], log["samplesSecond"] = first, second
    log["result"] = verdict_from(first, second)
    context["measurements"] = [{"phase": "first", "samples": first}, {"phase": "after-jump", "samples": second}]


def check(context):
    log = context.get("target") or {}
    if log.get("setupError"):
        return ["INVALID: %s" % log["setupError"]]
    if not (log.get("kill") or {}).get("dead"):
        return ["INVALID: the client body did not die (%s)" % (log.get("kill") or {}).get("method")]
    if not (log.get("spectator") or {}).get("active"):
        return ["INVALID: spectator mode is not active on the client (%s)" % (log.get("spectator") or {})]
    if not (log.get("target") or {}).get("ok"):
        return ["INVALID: the spectator target could not be set: %s" % (log.get("target") or {})]
    result = log.get("result") or {}
    if result.get("verdict") == FOLLOWS:
        return []
    return ["%s: %s" % (result.get("verdict", INVALID), result.get("reason") or "the camera stayed at the dead body while the target was far away")]


def preflight(fragments, attempts, builds=()):
    if NAME not in base.matching_scenario_names(fragments):
        return []
    checks = [(SAMPLE_STEP_SECONDS > 0 and PHASE_SECONDS > SAMPLE_STEP_SECONDS, "the sampling step is not shorter than the phase"),
              (smallest_column(NEAR_COLUMNS) >= MIN_START_DISTANCE, "a near column is closer than %.0f tiles" % MIN_START_DISTANCE),
              (smallest_column(FAR_COLUMNS) > FAR_FROM_TARGET, "a far column is not beyond %.0f tiles" % FAR_FROM_TARGET),
              (CLOSE_TO_TARGET < FAR_FROM_TARGET, "the close and far limits overlap")]
    return [message for holds, message in checks if not holds]


def smallest_column(columns):
    return min(abs(column) for column in columns)


base.PREFLIGHTS.append(preflight)

SCENARIOS = [
    Scenario(NAME, "the client dies and spectates the host: the camera must follow the host's body, sampled for six seconds with the host 12 to 20 tiles away and six more after the host jumps 40 to 55 tiles; verdict FOLLOWS or BUG PRESENT by the distances of the camera to the target and to the client's own dead body",
             prepare, act, lambda game, context: 0, hooks.never_changes, offsets=(0.0,), group=GROUP, check=check),
]

base.SCENARIOS.extend(SCENARIOS)
