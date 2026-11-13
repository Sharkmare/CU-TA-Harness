"""Mutation check of the swing gate: each mutation must make unit.test_swinggate fail. Usage: python tools/gate_mutation_check.py"""
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "client")
MUTATIONS = [
    ("casualtieslink/swinggate.py", "            if gated and moved > spec.get(\"limbPoseTolerance\", LIMB_POSE_TOLERANCE):", "            if False:", "limb pose tolerance ignored"),
    ("casualtieslink/swinggate.py", "    if reach is None or reach > spec.get(\"limbReach\", LIMB_REACH):", "    if False:", "limb reach ignored"),
    ("casualtieslink/swinggate.py", "    if wanted_right is None or pose[\"isRight\"] is not wanted_right:", "    if False:", "facing ignored"),
    ("casualtieslink/swinggate.py", "    if not isinstance(cooldown, (int, float)) or cooldown > COOLDOWN_READY:", "    if False:", "cooldown ignored"),
    ("casualtieslink/swinggate.py", "    if not target.get(\"present\") or not (target.get(\"health\") or 0) > 0:", "    if False:", "target presence ignored"),
    ("casualtieslink/swinggate.py", "    if gap is None or not low <= gap <= high:", "    if False:", "band ignored"),
    ("casualtieslink/swinggate.py", "        for problem in problems:\n            failures.append({\"gate\": \"box\"", "        for problem in []:\n            failures.append({\"gate\": \"box\"", "box ignored"),
    ("casualtieslink/swinggate.py", "    for issue in seat[\"issues\"]:\n        failures.append({\"gate\": \"seat\", \"detail\": issue})", "    for issue in []:\n        failures.append({\"gate\": \"seat\", \"detail\": issue})", "seat ignored"),
    ("casualtieslink/swinggate.py", "            return \"fail\", \"swing %d did not land", "            return \"invalid\", \"swing %d did not land", "a gate-passed miss classified invalid"),
    ("casualtieslink/swinggate.py", "    if gate_failure:\n        first = gate_failure[\"failures\"][0]\n        return \"invalid\"", "    if gate_failure:\n        first = gate_failure[\"failures\"][0]\n        return \"fail\"", "a gate failure classified fail"),
    ("casualtieslink/swinggate.py", "        steady = previous is not None and all(", "        steady = True or previous is not None and all(", "settle without waiting for steady limbs"),
    ("casualtieslink/swinggate.py", "        stable = stable + 1 if steady and reach is not None and reach <= LIMB_REACH else 0", "        stable = stable + 1 if steady else 0", "settle ignores reach"),
    ("casualtieslink/swinggate.py", "        while not verdict[\"passed\"] and now() - started < timeout:", "        while False:", "no wait for the recoil to settle"),
    ("casualtieslink/swinggate.py", "restPoseGated=self.swings_passed == 0", "restPoseGated=True", "the rest pose gates swing 2 and later"),
    ("casualtieslink/swinggate.py", "restPoseGated=self.swings_passed == 0", "restPoseGated=False", "the first swing is not gated on the rest pose"),
    ("casualtieslink/swinggate.py", "            self.swings_passed += 1", "            pass", "a passed swing is not counted"),
    ("tests/world_building.py", "            if not verdict[\"passed\"]:\n                context[\"gateFailure\"] = dict(verdict, swing=index)\n                break", "            if not verdict[\"passed\"]:\n                context[\"gateFailure\"] = dict(verdict, swing=index)", "a failed gate does not stop the swing"),
]

failures = []
for path, old, new, label in MUTATIONS:
    full = os.path.join(ROOT, path)
    original = open(full, "rb").read().decode()
    assert original.count(old) == 1, (label, original.count(old))
    open(full, "wb").write(original.replace(old, new).encode())
    try:
        result = subprocess.run([sys.executable, "-m", "unittest", "unit.test_swinggate"], cwd=ROOT, capture_output=True, text=True)
    finally:
        open(full, "wb").write(original.encode())
    caught = result.returncode != 0
    print("%-45s %s" % (label, "caught" if caught else "NOT CAUGHT"))
    if not caught:
        failures.append(label)
print("uncaught:", failures)
