"""Seat the client inside a distance band of a target: the distance a swing is judged at."""
import math

from casualtieslink.scenarioengine import positioncontrol

BAND_LOW = 2.5
BAND_HIGH = 3.2
BAND_TARGET = (BAND_LOW + BAND_HIGH) / 2
BAND_GAIN = 0.6
MIN_RESEAT_OFFSET = 0.5
BAND_WAIT_SECONDS = 0.3
BAND_TRIES = 4


def host_position(host, handle):
    from scenarios import desync_scenarios as base
    try:
        found = host.get(handle, base.BODY_PATH, depth=0)
    except Exception:
        return None
    if isinstance(found, dict) and "x" in found:
        return {"x": float(found["x"]), "y": float(found["y"])}
    return None


def ensure_band(host, client, handle, fallback, side=-1, seat_y=None, seat=None, read_position=None):
    """Re-seat the client until it stands inside the distance band. The seat height is the crate's own height unless seat_y is given: a crate rests lower than a standing body, so a seat at the crate height pulls the held body into the floor and it fights the hold."""
    from scenarios import desync_scenarios as base
    seat_client = seat or positioncontrol.place_and_hold
    read_position = read_position or host_position
    history = []
    offsets = []
    seats = []
    crate = fallback
    offset = BAND_TARGET
    for attempt in range(BAND_TRIES + 1):
        crate = read_position(host, handle) or crate
        distance = base.distance(base.player_position(client), crate)
        history.append(round(distance, 2))
        if BAND_LOW <= distance <= BAND_HIGH:
            return {"ok": True, "reseats": attempt, "distances": history, "offsets": offsets, "seat": seats[-1] if seats else None}
        if attempt == BAND_TRIES:
            break
        if seat_y is not None:
            height = seat_y - crate["y"]
            offset = math.sqrt(max(BAND_TARGET ** 2 - height ** 2, MIN_RESEAT_OFFSET ** 2))
        elif attempt > 0:
            offset = max(MIN_RESEAT_OFFSET, offset + BAND_GAIN * (BAND_TARGET - distance))
        offsets.append(round(offset, 3))
        seat_point = {"x": crate["x"] + side * offset, "y": crate["y"] if seat_y is None else seat_y}
        seat_client(client, seat_point)
        seats.append(seat_point)
    return {"ok": False, "reseats": BAND_TRIES, "distances": history, "offsets": offsets, "seat": seats[-1] if seats else None}
