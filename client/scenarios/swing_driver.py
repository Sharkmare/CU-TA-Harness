"""Fire one swing of the local player at a target position."""
import time

MAX_SWING_WAIT_SECONDS = 12.0
ATTEMPT_PAUSE_SECONDS = 0.05
COOLDOWN_RISE_EPSILON = 0.005


def fire_one_swing(client, target, timeout=MAX_SWING_WAIT_SECONDS, pause=ATTEMPT_PAUSE_SECONDS, attempts=None):
    """Invokes the swing until the attack cooldown rises. With an attempts dict, every invoke that the game ignored (no cooldown rise) is counted under 'ignored'."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        before = float(client.get("player", "attackCooldown", depth=0))
        client.call("invoke", target="player", method="UseItemInHand",
                    sets=[{"target": "player", "path": "targetLookPos", "value": {"x": target["x"], "y": target["y"], "z": 0.0}}])
        if float(client.get("player", "attackCooldown", depth=0)) > before + COOLDOWN_RISE_EPSILON:
            return True
        if attempts is not None:
            attempts["ignored"] = attempts.get("ignored", 0) + 1
        time.sleep(pause)
    return False
