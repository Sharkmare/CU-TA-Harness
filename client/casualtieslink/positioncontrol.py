import math
import time

BODY_PATH = "transform.position"
HOLD_COMMAND = "hold_body"
RELEASE_COMMAND = "release_body"
STATUS_COMMAND = "hold_status"
MIN_TOLERANCE = 0.001
MAX_TOLERANCE = 5.0
HOLD_TOLERANCE = 0.05
MIN_SEPARATION = 2.0
PARK_DISTANCE = 12.0
VERIFY_POLLS = 4
VERIFY_INTERVAL_SECONDS = 0.15
DIRECTIONS = {"left": (-1.0, 0.0), "right": (1.0, 0.0), "up": (0.0, 1.0), "down": (0.0, -1.0)}


class PositionControlError(ValueError):
    pass


def validate_point(point, name="point"):
    try:
        x, y = float(point["x"]), float(point["y"])
    except (KeyError, TypeError, ValueError):
        raise PositionControlError("%s needs numeric x and y, got %r" % (name, point))
    if not (math.isfinite(x) and math.isfinite(y)):
        raise PositionControlError("%s must be finite, got %r" % (name, point))
    return {"x": x, "y": y}


def validate_tolerance(tolerance):
    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool) or not math.isfinite(tolerance) or not MIN_TOLERANCE <= tolerance <= MAX_TOLERANCE:
        raise PositionControlError("tolerance must be between %s and %s, got %r" % (MIN_TOLERANCE, MAX_TOLERANCE, tolerance))
    return float(tolerance)


def distance_between(first, second):
    return math.hypot(first["x"] - second["x"], first["y"] - second["y"])


def direction_vector(direction):
    if isinstance(direction, str):
        if direction not in DIRECTIONS:
            raise PositionControlError("direction must be one of %s or an (x, y) pair, got %r" % (sorted(DIRECTIONS), direction))
        return DIRECTIONS[direction]
    try:
        x, y = float(direction[0]), float(direction[1])
    except (TypeError, ValueError, IndexError):
        raise PositionControlError("direction must be a name or an (x, y) pair, got %r" % (direction,))
    length = math.hypot(x, y)
    if not math.isfinite(length) or length == 0.0:
        raise PositionControlError("direction must not be zero, got %r" % (direction,))
    return (x / length, y / length)


def point_at(origin, direction, distance):
    origin = validate_point(origin, "origin")
    if not isinstance(distance, (int, float)) or isinstance(distance, bool) or not math.isfinite(distance) or distance <= 0:
        raise PositionControlError("distance must be a positive number, got %r" % (distance,))
    unit = direction_vector(direction)
    return {"x": origin["x"] + unit[0] * distance, "y": origin["y"] + unit[1] * distance}


def read_position(game):
    return validate_point(game.get("player", BODY_PATH, depth=0), "player position")


def hold_at(game, target, tolerance=HOLD_TOLERANCE):
    target = validate_point(target, "target")
    return game.call(HOLD_COMMAND, local=True, x=target["x"], y=target["y"], tolerance=validate_tolerance(tolerance))


def release(game, everyone=True):
    return game.call(RELEASE_COMMAND, all=bool(everyone), local=not everyone)


def release_quietly(game):
    try:
        return release(game)
    except Exception as failure:
        return {"released": None, "error": type(failure).__name__}


def place_and_hold(game, target, tolerance=HOLD_TOLERANCE, sleep=None):
    """Put the local body at the target, hold it there, and prove it stays within the tolerance over several polls."""
    target = validate_point(target, "target")
    tolerance = validate_tolerance(tolerance)
    sleep = sleep or time.sleep
    status = hold_at(game, target, tolerance)
    drifts = []
    for _ in range(VERIFY_POLLS):
        sleep(VERIFY_INTERVAL_SECONDS)
        drifts.append(round(distance_between(read_position(game), target), 4))
    final = game.call(STATUS_COMMAND)
    mine = [row for row in final if row.get("id") == status.get("id")] if isinstance(final, list) else []
    held = bool(mine) and bool(mine[0].get("heldWithinTolerance")) and not mine[0].get("lost")
    return {"ok": max(drifts) <= tolerance and held, "target": target, "tolerance": tolerance, "drifts": drifts, "heldWithinTolerance": held,
            "maxDriftSeenByHolder": mine[0].get("maxDrift") if mine else None, "exceededTicks": mine[0].get("exceededTicks") if mine else None}


def preflight_pair(host, client, host_target, client_target, tolerance=HOLD_TOLERANCE, min_separation=MIN_SEPARATION, copy_state=None):
    """Both bodies at their targets within the tolerance and not overlapping; the result goes into the report and decides whether the run counts."""
    host_target = validate_point(host_target, "host target")
    client_target = validate_point(client_target, "client target")
    tolerance = validate_tolerance(tolerance)
    if not isinstance(min_separation, (int, float)) or isinstance(min_separation, bool) or not math.isfinite(min_separation) or min_separation <= 0:
        raise PositionControlError("min_separation must be positive, got %r" % (min_separation,))
    host_position = read_position(host)
    client_position = read_position(client)
    host_drift = distance_between(host_position, host_target)
    client_drift = distance_between(client_position, client_target)
    separation = distance_between(host_position, client_position)
    issues = []
    if host_drift > tolerance:
        issues.append("the host body is %.3f from its target (tolerance %.3f)" % (host_drift, tolerance))
    if client_drift > tolerance:
        issues.append("the client body is %.3f from its target (tolerance %.3f)" % (client_drift, tolerance))
    if separation < min_separation:
        issues.append("the bodies are %.3f apart, below the %.3f minimum: they overlap" % (separation, min_separation))
    state = copy_state() if callable(copy_state) else copy_state
    return {"ok": not issues, "issues": issues, "hostPosition": host_position, "clientPosition": client_position, "hostTarget": host_target, "clientTarget": client_target,
            "hostDrift": round(host_drift, 4), "clientDrift": round(client_drift, 4), "separation": round(separation, 4), "tolerance": tolerance, "minSeparation": float(min_separation),
            "copyState": state}


def seat_pair(host, client, client_target, park_direction, tolerance=HOLD_TOLERANCE, min_separation=MIN_SEPARATION, park_distance=PARK_DISTANCE, copy_state=None, sleep=None):
    """Hold the attacking client at its seat and park the other player away from the swing line, then run the preflight."""
    client_target = validate_point(client_target, "client target")
    host_target = point_at(client_target, park_direction, park_distance)
    client_hold = place_and_hold(client, client_target, tolerance, sleep)
    host_hold = place_and_hold(host, host_target, tolerance, sleep)
    check = preflight_pair(host, client, host_target, client_target, tolerance, min_separation, copy_state)
    if not client_hold["ok"]:
        check["issues"].append("the client hold did not verify: drifts %s, exceeded ticks %s" % (client_hold["drifts"], client_hold["exceededTicks"]))
    if not host_hold["ok"]:
        check["issues"].append("the host hold did not verify: drifts %s, exceeded ticks %s" % (host_hold["drifts"], host_hold["exceededTicks"]))
    check["ok"] = not check["issues"]
    check["clientHold"] = client_hold
    check["hostHold"] = host_hold
    return check


def start_positions(host, client, copy_state=None):
    """The positions at the start of a swing run, for the report, even when nothing is held."""
    host_position = read_position(host)
    client_position = read_position(client)
    state = copy_state() if callable(copy_state) else copy_state
    return {"host": host_position, "client": client_position, "separation": round(distance_between(host_position, client_position), 4), "copyState": state}
