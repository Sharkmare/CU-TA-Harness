import math
import time

BODY_PATH = "transform.position"
HOLD_COMMAND = "hold_body"
RELEASE_COMMAND = "release_body"
STATUS_COMMAND = "hold_status"
MIN_TOLERANCE = 0.001
MAX_TOLERANCE = 5.0
HOLD_TOLERANCE = 0.05
PARKED_TOLERANCE = 0.5
PARKED_STRICT = "strict"
PARKED_RECORDED = "recorded"
DIAGNOSTIC_PATHS = ("rb.position", "body.transform.position", "limbs[0].transform.position", "limbs[1].transform.position", "rb.velocity", "rb.linearVelocity")
MIN_SEPARATION = 2.0
PARK_DISTANCE = 12.0
VERIFY_POLLS = 4
SEAT_ATTEMPTS = 3
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


def as_point(value):
    if isinstance(value, dict) and all(isinstance(value.get(axis), (int, float)) and not isinstance(value.get(axis), bool) and math.isfinite(value.get(axis)) for axis in ("x", "y")):
        return {"x": float(value["x"]), "y": float(value["y"])}
    return None


def optional_value(game, path):
    try:
        return game.get("player", path, depth=0)
    except Exception:
        return None


def holder_position(game):
    try:
        rows = game.call(STATUS_COMMAND)
    except Exception:
        return None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    return as_point(rows[0].get("position"))


def discover_diagnostic_paths(game):
    """The extra body paths this game answers, so a snapshot reads only those."""
    return [path for path in DIAGNOSTIC_PATHS if optional_value(game, path) is not None]


def parked_snapshot(game, paths):
    """One body seen three ways: the link's player position read, the holder's own view, and the extra transform and velocity paths."""
    return {"linkRead": as_point(optional_value(game, BODY_PATH)), "holder": holder_position(game), "paths": {path: optional_value(game, path) for path in paths}}


def snapshot_points(snapshot):
    named = [("linkRead", snapshot.get("linkRead")), ("holder", snapshot.get("holder"))]
    named += [(path, value) for path, value in (snapshot.get("paths") or {}).items() if path.endswith("position")]
    return [(name, as_point(value)) for name, value in named if as_point(value) is not None]


def closest_approach(snapshot, points):
    """The smallest distance any readable position of the snapshot has to any of the points, and which read it was; None when nothing was readable."""
    best = None
    for source, position in snapshot_points(snapshot):
        for point in points:
            distance = distance_between(position, point)
            if best is None or distance < best["distance"]:
                best = {"distance": round(distance, 4), "source": source}
    return best


def place_and_hold(game, target, tolerance=HOLD_TOLERANCE, sleep=None, observe=None):
    """Put the local body at the target, hold it there, and prove it stays within the tolerance over several polls. `observe` is called after every poll and its results are kept."""
    target = validate_point(target, "target")
    tolerance = validate_tolerance(tolerance)
    sleep = sleep or time.sleep
    status = hold_at(game, target, tolerance)
    drifts = []
    observations = []
    for _ in range(VERIFY_POLLS):
        sleep(VERIFY_INTERVAL_SECONDS)
        drifts.append(round(distance_between(read_position(game), target), 4))
        if observe is not None:
            observations.append(observe())
    final = game.call(STATUS_COMMAND)
    mine = [row for row in final if row.get("id") == status.get("id")] if isinstance(final, list) else []
    held = bool(mine) and bool(mine[0].get("heldWithinTolerance")) and not mine[0].get("lost")
    return {"ok": max(drifts) <= tolerance and held, "target": target, "tolerance": tolerance, "drifts": drifts, "heldWithinTolerance": held,
            "maxDriftSeenByHolder": mine[0].get("maxDrift") if mine else None, "exceededTicks": mine[0].get("exceededTicks") if mine else None, "observations": observations}


def preflight_pair(host, client, host_target, client_target, tolerance=HOLD_TOLERANCE, min_separation=MIN_SEPARATION, copy_state=None, host_drift_counts=True):
    """Both bodies at their targets within the tolerance and not overlapping; the result goes into the report and decides whether the run counts. With host_drift_counts False the host's drift is reported but is not an issue."""
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
    if host_drift_counts and host_drift > tolerance:
        issues.append("the host body is %.3f from its target (tolerance %.3f)" % (host_drift, tolerance))
    if client_drift > tolerance:
        issues.append("the client body is %.3f from its target (tolerance %.3f)" % (client_drift, tolerance))
    if separation < min_separation:
        issues.append("the bodies are %.3f apart, below the %.3f minimum: they overlap" % (separation, min_separation))
    state = copy_state() if callable(copy_state) else copy_state
    return {"ok": not issues, "issues": issues, "hostPosition": host_position, "clientPosition": client_position, "hostTarget": host_target, "clientTarget": client_target,
            "hostDrift": round(host_drift, 4), "clientDrift": round(client_drift, 4), "separation": round(separation, 4), "tolerance": tolerance, "minSeparation": float(min_separation),
            "copyState": state}


def seat_pair(host, client, client_target, park_direction, tolerance=HOLD_TOLERANCE, min_separation=MIN_SEPARATION, park_distance=PARK_DISTANCE, copy_state=None, sleep=None, attempts=SEAT_ATTEMPTS,
              parked_policy=PARKED_STRICT):
    """Seat the pair, and when a seat fails its verification release both holds and seat again, up to the attempt count. Every attempt's issues stay in the report.
    The client takes part in the swing and is always held to `tolerance`. The host is only parked out of the way: with PARKED_STRICT it is held and checked to the same
    tolerance; with PARKED_RECORDED it is held at PARKED_TOLERANCE, its drift is recorded from three kinds of read (parked_snapshot at every verification poll) and it
    never fails the seat, so the caller has to check how close it stays."""
    if parked_policy not in (PARKED_STRICT, PARKED_RECORDED):
        raise PositionControlError("parked_policy must be %r or %r, got %r" % (PARKED_STRICT, PARKED_RECORDED, parked_policy))
    earlier_issues = []
    for attempt in range(1, attempts + 1):
        check = seat_pair_once(host, client, client_target, park_direction, tolerance, min_separation, park_distance, copy_state, sleep, parked_policy)
        check["seatAttempts"] = attempt
        check["earlierAttemptIssues"] = list(earlier_issues)
        if check["ok"]:
            return check
        earlier_issues.append(check["issues"])
        release_quietly(client)
        release_quietly(host)
    return check


def seat_pair_once(host, client, client_target, park_direction, tolerance, min_separation, park_distance, copy_state, sleep, parked_policy):
    """Hold the attacking client at its seat and park the other player away from the swing line, then run the preflight."""
    client_target = validate_point(client_target, "client target")
    host_target = point_at(client_target, park_direction, park_distance)
    recorded = parked_policy == PARKED_RECORDED
    paths = discover_diagnostic_paths(host) if recorded else []
    client_hold = place_and_hold(client, client_target, tolerance, sleep)
    host_hold = place_and_hold(host, host_target, PARKED_TOLERANCE if recorded else tolerance, sleep, observe=(lambda: parked_snapshot(host, paths)) if recorded else None)
    check = preflight_pair(host, client, host_target, client_target, tolerance, min_separation, copy_state, host_drift_counts=not recorded)
    if not client_hold["ok"]:
        check["issues"].append("the client hold did not verify: drifts %s, exceeded ticks %s" % (client_hold["drifts"], client_hold["exceededTicks"]))
    if not host_hold["ok"] and not recorded:
        check["issues"].append("the host hold did not verify: drifts %s, exceeded ticks %s" % (host_hold["drifts"], host_hold["exceededTicks"]))
    check["ok"] = not check["issues"]
    check["clientHold"] = client_hold
    check["hostHold"] = host_hold
    check["parkedHost"] = {"policy": parked_policy, "position": check["hostPosition"], "target": host_target, "rawDriftReads": host_hold["drifts"], "largestRead": max(host_hold["drifts"], default=None),
                           "driftNow": check["hostDrift"], "tolerance": host_hold["tolerance"], "exceededTicks": host_hold["exceededTicks"], "maxDriftSeenByHolder": host_hold["maxDriftSeenByHolder"],
                           "paths": paths, "observations": host_hold["observations"], "afterPreflight": parked_snapshot(host, paths) if recorded else None}
    return check


def start_positions(host, client, copy_state=None):
    """The positions at the start of a swing run, for the report, even when nothing is held."""
    host_position = read_position(host)
    client_position = read_position(client)
    state = copy_state() if callable(copy_state) else copy_state
    return {"host": host_position, "client": client_position, "separation": round(distance_between(host_position, client_position), 4), "copyState": state}
