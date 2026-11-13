import os
import shutil
import time
import unittest

from casualtieslink.launcher import game_dir, mp_arguments
from casualtieslink.pair import GamePair, client_flags, host_flags

from live import rig

STATE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".state")
STOCK_DLL = os.environ.get("CU_STOCK_TOGETHER_DLL", "")
TOGETHER_LOG = os.path.join("BepInEx", "TogetherLogs", "together.log")
WORLD_WAIT_SECONDS = 150.0
SETTLE_SECONDS = 45.0
NO_DUNE_MUTATION = "no-dune"
STAT_KEYS = ("STR", "RES", "INT", "STRGainMult", "RESGainMult", "INTGainMult")
DUNE_SKILLS = {"STR": 17, "RES": 18, "INT": 0, "STRGainMult": 1.0, "RESGainMult": 1.0, "INTGainMult": 0.5}
PAIN_DAMPING = 0.7
BLEED_DAMPING = 0.8
DAMPING_TOLERANCE = 0.12
INJURY_SIZE = 10.0
DAMPING_SAMPLES = 3
PAIN_LIMB = 5
BLEED_LIMB = 2
LIMB_SKIN_HEALTH = 50.0
MISMATCH_OBSERVE_SECONDS = 45.0
PLAYER_BODY_PREFIX = "Body_"
HOST_BODY = "Body_HostD"
CLIENT_BODY = "Body_ClientD"
PAIR_ENABLED = os.environ.get(rig.PAIR_ENABLED_ENVIRONMENT_VARIABLE) == "1"
SKIP_REASON = "two instance tests start a host and a client game; run run_tests.py --pair"


def read_bodies(game):
    rows = {}
    for row in game.call("find", type="Body"):
        if not row["object"]["name"].startswith(PLAYER_BODY_PREFIX):
            continue
        handle = "id:%d" % row["object"]["id"]
        rows[row["object"]["name"]] = {
            "handle": handle,
            "charType": game.get(handle, "charType"),
            "skills": {key: game.get(handle, "skills." + key) for key in STAT_KEYS},
        }
    return rows


def wait_for_bodies(game, count, timeout=WORLD_WAIT_SECONDS):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if len([row for row in game.call("find", type="Body") if row["object"]["name"].startswith(PLAYER_BODY_PREFIX)]) >= count:
                return
        except Exception:
            pass
        time.sleep(1.0)
    raise AssertionError("fewer than %d bodies after %.0fs" % (count, timeout))


def together_log_text(directory=None):
    path = os.path.join(directory or game_dir(), TOGETHER_LOG)
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def layout_lines(directory=None):
    return [line for line in together_log_text(directory).splitlines() if "prefab: charType" in line]


def damping_ratio(game, field, limb):
    samples = sorted(single_damping_ratio(game, field, limb) for _ in range(DAMPING_SAMPLES))
    return samples[len(samples) // 2]


def single_damping_ratio(game, field, limb):
    game.set("player", "limbs[%d].skinHealth" % limb, LIMB_SKIN_HEALTH)
    game.step(5)
    before = game.get("player", "limbs[%d].%s" % (limb, field))
    game.set("player", "limbs[%d].%s" % (limb, field), before + INJURY_SIZE)
    game.step(1)
    after = game.get("player", "limbs[%d].%s" % (limb, field))
    return (after - before) / INJURY_SIZE


def choose_character(character):
    if character is None:
        return None
    return lambda game: game.set("static:PreRunScript", "characterSelected", character)


class PairCase(unittest.TestCase):
    host_extra = ()
    client_extra = ()
    setchar = 2
    client_plugin_dll = None
    host_character = None
    client_character = None
    expect_join = True

    @classmethod
    def setUpClass(cls):
        if not PAIR_ENABLED:
            raise unittest.SkipTest(SKIP_REASON)
        host = dict(host_flags())
        client = dict(client_flags())
        if cls.setchar is not None and not rig.mutation_active(NO_DUNE_MUTATION):
            host["setchar"] = cls.setchar
            client["setchar"] = cls.setchar
        if cls.host_character is not None:
            host["mychar"] = cls.host_character
        if cls.client_character is not None:
            client["mychar"] = cls.client_character
        cls.pair = GamePair(STATE_ROOT,
                            host_extra_args=mp_arguments(host) + list(cls.host_extra),
                            client_extra_args=mp_arguments(client) + list(cls.client_extra),
                            client_plugin_dll=cls.client_plugin_dll,
                            after_host_link=choose_character(cls.host_character),
                            after_client_link=choose_character(cls.client_character))
        cls.pair.start()
        cls.host, cls.client = cls.pair.games
        cls.host.wait_state("in-world", timeout=WORLD_WAIT_SECONDS)
        cls.host.call("close_console")
        if cls.expect_join:
            cls.client.wait_state("in-world", timeout=WORLD_WAIT_SECONDS)
            cls.client.call("close_console")
            wait_for_bodies(cls.host, 2)
            wait_for_bodies(cls.client, 2)
            time.sleep(SETTLE_SECONDS)

    @classmethod
    def tearDownClass(cls):
        pair = getattr(cls, "pair", None)
        if pair is not None:
            print("\n%s bodies:" % cls.__name__)
            for label, game in zip(("host", "client"), pair.games):
                for row in game.call("bodies"):
                    print("  [%s] %s id=%s charType=%s root=%s parent=%s active=%s local=%s" % (label, row["object"]["name"], row["object"]["id"], row["charType"], row["root"], row.get("parent"), row.get("active"), row["local"]))
            print("\n%s layout lines:" % cls.__name__)
            for label, directory in ("host", None), ("client", pair.client_copy):
                for line in layout_lines(directory):
                    print("  [%s] %s" % (label, line))
            pair.close()


@unittest.skipUnless(PAIR_ENABLED, SKIP_REASON)
class DunePairTests(PairCase):
    def test_both_instances_see_both_players(self):
        for game in (self.host, self.client):
            self.assertEqual(sorted(read_bodies(game)), [CLIENT_BODY, HOST_BODY])

    def test_host_logs_an_accepted_handshake_with_equal_versions(self):
        text = together_log_text()
        line = next((l for l in text.splitlines() if "handshake accepted: name=ClientD" in l), None)
        self.assertIsNotNone(line, "no accepted handshake for ClientD in the host log")
        client_version = line.split("clientVersion=")[1].split()[0]
        our_version = line.split("ourVersion=")[1].split()[0]
        self.assertEqual(client_version, our_version)

    def test_every_body_is_dune_on_both_instances(self):
        for game in (self.host, self.client):
            for name, body in read_bodies(game).items():
                self.assertEqual(body["charType"], 2, "%s charType on %s" % (name, game.transport.port))

    def test_base_skills_and_multipliers_on_every_body(self):
        for game in (self.host, self.client):
            for name, body in read_bodies(game).items():
                self.assertEqual(body["skills"], DUNE_SKILLS, "%s skills on port %s" % (name, game.transport.port))

    def test_injuries_are_not_damped_by_default(self):
        for game in (self.host, self.client):
            self.assertAlmostEqual(damping_ratio(game, "pain", PAIN_LIMB), 1.0, delta=DAMPING_TOLERANCE)
            self.assertAlmostEqual(damping_ratio(game, "bleedAmount", BLEED_LIMB), 1.0, delta=DAMPING_TOLERANCE)


@unittest.skipUnless(PAIR_ENABLED, SKIP_REASON)
class DuneHardyOnTests(PairCase):
    host_extra = ("--mp-setrule", "DuneHardy", "1")
    client_extra = ("--mp-setrule", "DuneHardy", "1")

    def test_dune_hardy_damps_pain_and_bleeding_on_the_local_body(self):
        for game in (self.host, self.client):
            context = "port %s timeScale %s conscious %s" % (game.transport.port, game.get("static:Time", "timeScale"), game.get("player", "conscious"))
            self.assertAlmostEqual(damping_ratio(game, "pain", PAIN_LIMB), PAIN_DAMPING, delta=DAMPING_TOLERANCE, msg=context)
            self.assertAlmostEqual(damping_ratio(game, "bleedAmount", BLEED_LIMB), BLEED_DAMPING, delta=DAMPING_TOLERANCE, msg=context)


@unittest.skipUnless(PAIR_ENABLED, SKIP_REASON)
class KeepOwnCharacterTests(PairCase):
    setchar = None
    client_character = 2

    def test_each_player_keeps_their_own_character_on_both_instances(self):
        for game in (self.host, self.client):
            bodies = read_bodies(game)
            self.assertEqual(bodies[HOST_BODY]["charType"], 0, "host body seen on port %s" % game.transport.port)
            self.assertEqual(bodies[CLIENT_BODY]["charType"], 2, "client body seen on port %s" % game.transport.port)


@unittest.skipUnless(PAIR_ENABLED and STOCK_DLL and os.path.exists(STOCK_DLL), SKIP_REASON + "; set CU_STOCK_TOGETHER_DLL to a stock 5.4.0 CasualtiesMP.dll")
class StockClientTests(PairCase):
    client_plugin_dll = STOCK_DLL
    expect_join = False

    def test_stock_client_is_rejected_with_version_mismatch(self):
        deadline = time.time() + MISMATCH_OBSERVE_SECONDS
        client_log = ""
        while time.time() < deadline and "Version mismatch" not in client_log:
            time.sleep(2.0)
            client_log = open(os.path.join(self.pair.client_copy, "BepInEx", "LogOutput.log"), encoding="utf-8", errors="replace").read()
        self.assertIn("Version mismatch", client_log)
        self.assertNotIn("handshake accepted: name=ClientD", together_log_text())
        self.assertEqual(sorted(read_bodies(self.host)), [HOST_BODY])
        self.assertNotEqual(self.client.state()["state"], "in-world")


if __name__ == "__main__":
    unittest.main()
