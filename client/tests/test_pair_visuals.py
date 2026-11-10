import time
import unittest

from . import rig
from .test_pair import (CLIENT_BODY, HOST_BODY, PAIR_ENABLED, PLAYER_BODY_PREFIX, SKIP_REASON, PairCase, read_bodies)

DUNE_SKILLS = {"STR": 17, "RES": 18, "INT": 0, "STRGainMult": 1.0, "RESGainMult": 1.0, "INTGainMult": 0.5}
EXPERIMENT_SKILLS = {"STR": 9, "RES": 8, "INT": 7, "STRGainMult": 1.0, "RESGainMult": 1.0, "INTGainMult": 1.0}
SKILLS_BY_CHARACTER = {0: EXPERIMENT_SKILLS, 2: DUNE_SKILLS}
REPORT_SETTLE_SECONDS = 8.0
AIM_OFFSET = 8.0
POINT_HOLD_SECONDS = 3.0
ANGLE_TOLERANCE_DEGREES = 15.0
MINIMUM_POINT_EFFECT_DEGREES = 10.0
POINT_KEY = "Mouse2"
IDLE_SETTLE_SECONDS = 1.5


def bodies(game):
    return game.call("bodies")


def remote_id(game):
    rows = [row for row in bodies(game) if not row["local"] and row["object"]["name"].startswith(PLAYER_BODY_PREFIX)]
    assert len(rows) == 1, "expected one remote body, saw %d" % len(rows)
    return rows[0]["object"]["id"]


def visuals(game, remote=False):
    if remote:
        return game.call("body_visuals", id=remote_id(game))
    return game.call("body_visuals", **{"local": True})


def appearance(view):
    sprites = sorted((leaf_of(s["path"]), sprite_family(s["path"], s["sprite"])) for s in view["sprites"])
    limb_children = [(limb["name"], [child for child in limb["children"] if not is_runtime_child(child)]) for limb in view["limbs"]]
    return {"sprites": sprites, "limbChildren": limb_children, "bodyController": view["bodyController"], "armsController": view["armsController"]}


EYE_STATE_FAMILIES = ("dune", "experiment", "milky")


def leaf_of(path):
    return path.split("/")[-1]


def sprite_family(path, sprite):
    if leaf_of(path) != "Eyes" or sprite is None:
        return sprite
    for family in EYE_STATE_FAMILIES:
        if sprite.startswith(family):
            return family + "Eyes"
    return sprite


def is_runtime_child(name):
    return name.endswith("(Clone)") or name.startswith("InvSlot")


def describe_difference(actual, expected):
    lines = []
    for key in expected:
        if actual[key] == expected[key]:
            continue
        if isinstance(expected[key], list):
            missing = [item for item in expected[key] if item not in actual[key]]
            extra = [item for item in actual[key] if item not in expected[key]]
            lines.append("%s: missing %s extra %s" % (key, missing[:6], extra[:6]))
        else:
            lines.append("%s: %r != %r" % (key, actual[key], expected[key]))
    return "; ".join(lines)


def circular_difference(first, second):
    return abs((first - second + 180.0) % 360.0 - 180.0)


class MixedCharacterChecks:
    setchar = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if PAIR_ENABLED:
            time.sleep(REPORT_SETTLE_SECONDS)

    def test_every_instance_sees_each_player_with_their_own_character(self):
        for game in (self.host, self.client):
            seen = read_bodies(game)
            self.assertEqual(seen[HOST_BODY]["charType"], self.host_character, "host body on port %s" % game.transport.port)
            self.assertEqual(seen[CLIENT_BODY]["charType"], self.client_character, "client body on port %s" % game.transport.port)

    def test_skills_follow_each_players_character(self):
        for game in (self.host, self.client):
            seen = read_bodies(game)
            self.assertEqual(seen[HOST_BODY]["skills"], SKILLS_BY_CHARACTER[self.host_character], "host body on port %s" % game.transport.port)
            self.assertEqual(seen[CLIENT_BODY]["skills"], SKILLS_BY_CHARACTER[self.client_character], "client body on port %s" % game.transport.port)

    def test_remote_bodies_look_like_the_local_body_of_that_character(self):
        host_reference = appearance(visuals(self.host))
        client_reference = appearance(visuals(self.client))
        self.assertNotEqual(host_reference, client_reference, "the two characters look identical, the comparison would prove nothing")
        host_as_seen = appearance(visuals(self.client, remote=True))
        client_as_seen = appearance(visuals(self.host, remote=True))
        self.assertEqual(host_as_seen, host_reference, "host player as seen by the client: " + describe_difference(host_as_seen, host_reference))
        self.assertEqual(client_as_seen, client_reference, "client player as seen by the host: " + describe_difference(client_as_seen, client_reference))


@unittest.skipUnless(PAIR_ENABLED, SKIP_REASON)
class DuneHostExperimentClientTests(MixedCharacterChecks, PairCase):
    host_character = 2
    client_character = 0


@unittest.skipUnless(PAIR_ENABLED, SKIP_REASON)
class ExperimentHostDuneClientTests(MixedCharacterChecks, PairCase):
    host_character = 0
    client_character = 2


def aim_at_offset(game, dx, dy):
    position = game.call("player")["position"]
    game.call("mouse", wx=position["x"] + dx, wy=position["y"] + dy)


@unittest.skipUnless(PAIR_ENABLED, SKIP_REASON)
class PointingArmTests(PairCase):
    def point_and_compare(self, pointer, observer):
        aim_at_offset(observer, -AIM_OFFSET, -AIM_OFFSET)
        aim_at_offset(pointer, -AIM_OFFSET, -AIM_OFFSET)
        time.sleep(IDLE_SETTLE_SECONDS)
        idle_angle = visuals(pointer)["gunangle"]
        aim_at_offset(pointer, AIM_OFFSET, AIM_OFFSET)
        pointer.step(5)
        pointer.call("input", key=POINT_KEY, mode="tap", frames=3)
        time.sleep(POINT_HOLD_SECONDS)
        pointing_angle = visuals(pointer)["gunangle"]
        seen_by_observer = visuals(observer, remote=True)["gunangle"]
        pointer.call("release_input")
        observer.call("release_input")
        return idle_angle, pointing_angle, seen_by_observer

    def assert_arm_converges(self, pointer, observer):
        idle, pointing, seen = self.point_and_compare(pointer, observer)
        self.assertGreater(circular_difference(pointing, idle), MINIMUM_POINT_EFFECT_DEGREES, "pointing did not move the arm on its own instance")
        self.assertLess(circular_difference(seen, pointing), ANGLE_TOLERANCE_DEGREES, "pointing arm %.1f as seen remotely %.1f" % (pointing, seen))

    def test_host_pointing_arm_is_seen_at_the_same_angle_by_the_client(self):
        self.assert_arm_converges(self.host, self.client)

    def test_client_pointing_arm_is_seen_at_the_same_angle_by_the_host(self):
        self.assert_arm_converges(self.client, self.host)

    def test_every_body_has_its_own_animators_inside_its_own_root(self):
        for game in (self.host, self.client):
            views = [game.call("body_visuals", id=row["object"]["id"]) for row in bodies(game) if row["object"]["name"].startswith(PLAYER_BODY_PREFIX)]
            self.assertGreaterEqual(len(views), 2)
            for key in ("bodyAnimatorId", "armsAnimatorId"):
                identifiers = [view[key] for view in views]
                self.assertEqual(len(set(identifiers)), len(identifiers), "%s shared between bodies on port %s: %s" % (key, game.transport.port, identifiers))
            for view in views:
                for key in ("bodyAnimatorPath", "armsAnimatorPath"):
                    self.assertFalse(view[key].startswith("<outside"), "%s %s on port %s" % (key, view[key], game.transport.port))


if __name__ == "__main__":
    unittest.main()
