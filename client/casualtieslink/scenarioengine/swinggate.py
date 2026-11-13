"""The gate every counted swing passes right before it is fired, and the run verdict that follows from it.

A run is all or nothing. A swing is fired only when, read fresh at that moment, the body sits on its seat (holder view and rb.position), the swinging limbs are where the rest pose
puts them and within reach of the target, the body faces the target, the attack cooldown is ready, the target is present, the distance is inside the band and no other body is
inside the swing box. The first swing of a run is also gated on the limb rest pose; later swings are not, because the limb and body recoil after a swing and a swing is judged by whether the limb is within reach. A swing that fails the gate is not fired and the run is INVALID. A swing that was fired with every gate passed and still did not land is a FAIL: a finding
about the product, reported apart from the invalid runs.
"""
import math
import time

from casualtieslink.scenarioengine import positioncontrol

LIMB_REST_TOLERANCE = 0.2
AIM_SETTLE_SECONDS = 0.5
READY_TIMEOUT_SECONDS = 3.0
READY_POLL_SECONDS = 0.1
LIMB_POSE_TOLERANCE = 0.5
LIMB_REACH = 4.5
COOLDOWN_READY = 0.005
SETTLE_TIMEOUT_SECONDS = 6.0
SETTLE_POLL_SECONDS = 0.15
SETTLE_READS_IN_A_ROW = 2
PARKED_MIN_DISTANCE = 6.0
GATED_LIMBS = ("limb1",)
LIMB_PATHS = {"limb0": "limbs[0].transform.position", "limb1": "limbs[1].transform.position"}
GATE_NAMES = ("seat", "limb", "facing", "cooldown", "target", "distance", "box")


def point_of(value):
    return positioncontrol.as_point(value)


def distance(first, second):
    return math.hypot(first["x"] - second["x"], first["y"] - second["y"])


def offset(limb, body):
    if limb is None or body is None:
        return None
    return {"x": limb["x"] - body["x"], "y": limb["y"] - body["y"]}


def read_pose(client, paths):
    """The body three ways, both limbs, the facing flag and the cooldown, read now."""
    snapshot = positioncontrol.parked_snapshot(client, list(paths))
    body = point_of(snapshot.get("linkRead"))
    limbs = {name: point_of(positioncontrol.optional_value(client, path)) for name, path in LIMB_PATHS.items()}
    return {"snapshot": snapshot, "body": body, "limb0": limbs["limb0"], "limb1": limbs["limb1"], "isRight": positioncontrol.optional_value(client, "isRight"),
            "cooldown": positioncontrol.optional_value(client, "attackCooldown")}


def settle_limbs(client, paths, target_of, sleep=None, now=None, timeout=SETTLE_TIMEOUT_SECONDS, poll=SETTLE_POLL_SECONDS, reads_in_a_row=SETTLE_READS_IN_A_ROW):
    """After any teleport or move: wait until both limbs keep the same place relative to the body on consecutive reads and limb 1 is within reach of the target. The pose then
    read is the rest pose the swings are gated against. A limb that never settles within the timeout gives no rest pose and the run is invalid."""
    sleep = sleep or time.sleep
    now = now or time.time
    started = now()
    rows = []
    stable = 0
    previous = None
    while now() - started < timeout:
        pose = read_pose(client, paths)
        target = target_of()
        current = {name: offset(pose[name], pose["body"]) for name in ("limb0", "limb1")}
        reach = None if pose["limb1"] is None or target is None else distance(pose["limb1"], target)
        rows.append({"seconds": round(now() - started, 2), "limb0": current["limb0"], "limb1": current["limb1"], "limb1ToTarget": None if reach is None else round(reach, 3)})
        steady = previous is not None and all(current[name] is not None and previous[name] is not None and distance(current[name], previous[name]) <= LIMB_REST_TOLERANCE for name in current)
        stable = stable + 1 if steady and reach is not None and reach <= LIMB_REACH else 0
        if stable >= reads_in_a_row - 1 and steady:
            return {"ok": True, "rest": current, "rows": rows}
        previous = current
        sleep(poll)
    return {"ok": False, "rest": None, "rows": rows}


def judge(state, spec):
    """Pure: every gate against one fresh state. Returns the verdict with every value that decided it."""
    failures = []
    values = {}
    pose = state["pose"]
    body = pose["body"]
    seat = positioncontrol.judge_seat(pose["snapshot"], spec["seat"])
    values["seat"] = {"ok": seat["ok"], "holderDrift": seat["holderDrift"], "rbDrift": seat["rbDrift"], "holderVsRb": seat["holderVsRb"], "linkDrift": seat["linkDrift"], "linkReadDisagrees": seat["linkReadDisagrees"]}
    for issue in seat["issues"]:
        failures.append({"gate": "seat", "detail": issue})
    target_point = state["target"].get("position")
    rest = spec.get("rest")
    limb_values = {}
    for name in ("limb0", "limb1"):
        current = offset(pose[name], body)
        limb_values[name] = current
        gated = name in spec.get("gatedLimbs", GATED_LIMBS) and spec.get("restPoseGated", True)
        if rest is None or rest.get(name) is None:
            if gated:
                failures.append({"gate": "limb", "detail": "no rest pose for %s" % name})
        elif current is None:
            if gated:
                failures.append({"gate": "limb", "detail": "%s is not readable" % name})
        else:
            moved = distance(current, rest[name])
            limb_values[name + "Moved"] = round(moved, 3)
            if gated and moved > spec.get("limbPoseTolerance", LIMB_POSE_TOLERANCE):
                failures.append({"gate": "limb", "detail": "%s is %.2f from its rest pose (tolerance %.2f)" % (name, moved, spec.get("limbPoseTolerance", LIMB_POSE_TOLERANCE))})
    reach = None if pose["limb1"] is None or target_point is None else distance(pose["limb1"], target_point)
    limb_values["limb1ToTarget"] = None if reach is None else round(reach, 3)
    if reach is None or reach > spec.get("limbReach", LIMB_REACH):
        failures.append({"gate": "limb", "detail": "limb 1 is %s from the target (reach %.1f)" % ("unreadable" if reach is None else "%.2f" % reach, spec.get("limbReach", LIMB_REACH))})
    values["limb"] = limb_values
    wanted_right = None if body is None or target_point is None else target_point["x"] > body["x"]
    values["facing"] = {"isRight": pose["isRight"], "targetIsRight": wanted_right}
    if wanted_right is None or pose["isRight"] is not wanted_right:
        failures.append({"gate": "facing", "detail": "isRight %s, target on the %s" % (pose["isRight"], "unknown side" if wanted_right is None else ("right" if wanted_right else "left"))})
    cooldown = pose["cooldown"]
    values["cooldown"] = cooldown
    if not isinstance(cooldown, (int, float)) or cooldown > COOLDOWN_READY:
        failures.append({"gate": "cooldown", "detail": "attack cooldown %s" % cooldown})
    target = state["target"]
    values["target"] = {"present": target.get("present"), "health": target.get("health"), "hostCopy": target.get("hostCopy"), "clientCopy": target.get("clientCopy")}
    if not target.get("present") or not (target.get("health") or 0) > 0:
        failures.append({"gate": "target", "detail": "target not present or no health"})
    gap = None if body is None or target_point is None else distance(body, target_point)
    values["distance"] = None if gap is None else round(gap, 3)
    low, high = spec["band"]
    if gap is None or not low <= gap <= high:
        failures.append({"gate": "distance", "detail": "distance %s outside %.1f to %.1f" % ("unreadable" if gap is None else "%.2f" % gap, low, high)})
    values["box"] = None
    if state.get("parked") is not None and body is not None and target_point is not None:
        problems, smallest = positioncontrol.parked_distance_problems([("swing", state["parked"])], [body, target_point], spec.get("parkedMinDistance", PARKED_MIN_DISTANCE))
        values["box"] = {"smallest": smallest}
        for problem in problems:
            failures.append({"gate": "box", "detail": problem})
    return {"passed": not failures, "failures": failures, "values": values}


class Gate:
    def __init__(self, spec, read_target, client_paths=(), parked_game=None, parked_paths=()):
        self.spec = dict(spec)
        self.read_target = read_target
        self.client_paths = list(client_paths)
        self.parked_game = parked_game
        self.parked_paths = list(parked_paths)
        self.settle_record = None
        self.swings_passed = 0
        self.last_aim = None

    def aim(self, client, settle=0.0, sleep=None):
        """Put the injected mouse on the target: the game turns the body toward the mouse every frame, so a body that is not aimed turns away from the target between swings."""
        position = (self.read_target() or {}).get("position")
        self.last_aim = {"target": position, "sent": False, "error": None}
        if position is None:
            return False
        try:
            client.call("mouse", wx=position["x"], wy=position["y"])
        except Exception as failure:
            self.last_aim["error"] = str(failure)[:120]
            return False
        self.last_aim["sent"] = True
        if settle:
            (sleep or time.sleep)(settle)
        return True

    def release(self, client):
        try:
            client.call("mouse", clear=True)
        except Exception:
            pass

    def settle(self, client, **options):
        """Aim at the target, settle the limbs and keep the rest pose. Returns the record; the run is invalid when it is not ok."""
        self.aim(client, settle=AIM_SETTLE_SECONDS, sleep=options.get("sleep"))
        self.settle_record = settle_limbs(client, self.client_paths, lambda: (self.read_target() or {}).get("position"), **options)
        self.spec["rest"] = self.settle_record["rest"]
        return self.settle_record

    def wait_ready(self, client, sleep=None, now=None, timeout=READY_TIMEOUT_SECONDS, poll=READY_POLL_SECONDS):
        """Read the gate until it passes, then return that fresh passing verdict so the swing is fired at once. After a swing the limb and the body are in recoil for a moment, so the
        next swing waits for them; a gate that has not passed within the timeout is returned as failed and the swing is not fired."""
        sleep = sleep or time.sleep
        now = now or time.time
        started = now()
        verdict = self.check(client)
        waited = 0
        while not verdict["passed"] and now() - started < timeout:
            sleep(poll)
            verdict = self.check(client)
            waited += 1
        verdict["waitedReads"] = waited
        if verdict["passed"]:
            self.swings_passed += 1
        return verdict

    def check(self, client):
        self.aim(client)
        state = {"pose": read_pose(client, self.client_paths), "target": self.read_target() or {}}
        state["parked"] = None if self.parked_game is None else positioncontrol.parked_snapshot(self.parked_game, self.parked_paths)
        verdict = judge(state, dict(self.spec, restPoseGated=self.swings_passed == 0))
        verdict["aim"] = self.last_aim
        return verdict


def gate_reason(failure):
    names = sorted({item["gate"] for item in failure["failures"]})
    return "gate %s failed" % ", ".join(names)


def run_verdict(entries, gate_failure=None):
    """valid, invalid or fail with a message: all swings landed, or the run is out."""
    if gate_failure:
        first = gate_failure["failures"][0]
        return "invalid", "swing %d not fired, %s: %s" % (gate_failure["swing"], gate_reason(gate_failure), first["detail"])
    if not entries:
        return "invalid", "no swing recorded"
    for index, entry in enumerate(entries, 1):
        if not entry.get("fired", True):
            return "invalid", "swing %d did not fire" % entry.get("swing", index)
    for index, entry in enumerate(entries, 1):
        if (entry.get("hostDelta") or 0) <= 0 or (entry.get("clientDelta") or 0) <= 0:
            return "fail", "swing %d did not land with every gate passed (host %.2f, client %.2f)" % (entry.get("swing", index), entry.get("hostDelta") or 0, entry.get("clientDelta") or 0)
    return "valid", ""
