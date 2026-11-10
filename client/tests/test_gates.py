import os
import time
import unittest

from casualtieslink import observe
from casualtieslink.instances import ScenarioGames

from . import rig
from .test_pair import PAIR_ENABLED, PLAYER_BODY_PREFIX, SKIP_REASON, read_bodies, wait_for_bodies

STATE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".state")
HOST_BODY = "Body_HostD"
CLIENT_BODY = "Body_ClientD"
HELLO_SECONDS = 10.0
SIZE_HELLO = "CasualtiesSize.Hello"
LOADER_HELLO = "CasualtiesCharacters.Hello"
HELLO_SENDS_AT_MOST = 3
HEIGHT_FIELD = "heightMultiplier"
SIZE_TOLERANCE = 0.05
REPLICATION_SECONDS = 8.0
WORLD_WAIT_SECONDS = 150.0
FIRST_CUSTOM_CHARACTER = 3

GAMES = None


def setUpModule():
    global GAMES
    if PAIR_ENABLED:
        GAMES = ScenarioGames(STATE_ROOT)
        GAMES.prepare()


def tearDownModule():
    if GAMES is not None:
        GAMES.dispose()


def body_handle(game, name):
    rows = read_bodies(game)
    if name not in rows:
        raise AssertionError("%s not found among %s" % (name, sorted(rows)))
    return rows[name]["handle"]


def height(game, name):
    return float(game.get(body_handle(game, name), HEIGHT_FIELD))


def wait_until(check, timeout=REPLICATION_SECONDS, step=0.5):
    deadline = time.time() + timeout
    value = None
    while time.time() < deadline:
        value = check()
        if value:
            return value
        time.sleep(step)
    return value


def choose_loader_character(game):
    slot = int(game.get("static:CasualtiesCharacters.Registry", "HighestId"))
    if slot < FIRST_CUSTOM_CHARACTER:
        raise AssertionError("the loader has no custom character installed")
    game.set("static:PreRunScript", "characterSelected", slot)
    return slot


def custom_characters(game):
    try:
        rows = game.call("find", type="CustomCharacter")
    except Exception:
        return {}
    result = {}
    for row in rows:
        handle = "id:%d" % row["object"]["id"]
        body = game.get(handle, "Body", depth=0)
        result[body["name"]] = {"slot": game.get(handle, "Id"), "key": game.get(handle, "Definition.FullKey")}
    return result


def sent_to_host_names(game, hashes):
    counters = game.call("net_counters")
    return counters, observe.sent_by_direction(counters["counts"], hashes)


class ScenarioCase(unittest.TestCase):
    host_plugins = ()
    client_plugins = ()
    choose_character = False

    @classmethod
    def setUpClass(cls):
        if not PAIR_ENABLED or GAMES is None:
            raise unittest.SkipTest(SKIP_REASON)
        hook = None
        if cls.choose_character:
            def hook(game):
                cls.chosen_slot = choose_loader_character(game)
        cls.host, cls.client = GAMES.start(list(cls.host_plugins), list(cls.client_plugins), after_client_link=hook)
        cls.host.wait_state("in-world", timeout=WORLD_WAIT_SECONDS)
        cls.client.wait_state("in-world", timeout=WORLD_WAIT_SECONDS)
        wait_for_bodies(cls.host, 2)
        wait_for_bodies(cls.client, 2)
        cls.host.call("close_console")
        cls.client.call("close_console")
        time.sleep(HELLO_SECONDS)
        cls.hashes = observe.message_hashes(cls.client, [SIZE_HELLO, LOADER_HELLO])

    @classmethod
    def tearDownClass(cls):
        if GAMES is not None:
            for label, game in (("host", getattr(cls, "host", None)), ("client", getattr(cls, "client", None))):
                if game is not None:
                    try:
                        print("\n%s %s counters: %s" % (cls.__name__, label, game.call("net_counters")))
                    except Exception:
                        pass
            GAMES.stop()

    def logs(self, which):
        return GAMES.log_text(which) + "\n" + GAMES.log_text(which, os.path.join("BepInEx", "TogetherLogs", "together.log"))

    def assert_logs_clean(self):
        for which in ("host", "client"):
            self.assertEqual(observe.suspicious_lines(self.logs(which)), [], "%s log" % which)


@unittest.skipUnless(PAIR_ENABLED, SKIP_REASON)
class A_StockHostClientWithPluginsTests(ScenarioCase):
    host_plugins = ()
    client_plugins = ("size", "loader", "avali")
    choose_character = True

    def test_gates_report_the_host_as_not_ours(self):
        self.assertEqual(observe.size_gate_host_state(self.client), "NotOurs")
        self.assertIn(observe.loader_host_state(self.client), ("NoHost", "Waiting"))

    def test_the_host_has_none_of_our_plugins(self):
        self.assertEqual(observe.size_gate_host_state(self.host), observe.GATE_ABSENT)
        self.assertEqual(observe.loader_host_state(self.host), observe.GATE_ABSENT)

    def test_no_errors_or_unknown_message_complaints_in_either_log(self):
        self.assert_logs_clean()

    def test_the_client_sent_nothing_but_the_hellos(self):
        counters, sent = sent_to_host_names(self.client, self.hashes)
        self.assertTrue(counters["installed"], counters["status"])
        self.assertEqual(sorted(sent), ["toHost"], sent)
        self.assertEqual(sorted(sent["toHost"]), sorted([SIZE_HELLO, LOADER_HELLO]), sent)
        for name, count in sent["toHost"].items():
            self.assertLessEqual(count, HELLO_SENDS_AT_MOST, name)
        time.sleep(HELLO_SECONDS / 2)
        _, later = sent_to_host_names(self.client, self.hashes)
        self.assertEqual(later, sent, "messages kept going after the hello timeout")

    def test_the_host_sent_nothing_of_ours(self):
        counters, _ = sent_to_host_names(self.host, self.hashes)
        self.assertEqual(counters["counts"], {}, counters)

    def test_the_client_sizes_itself_but_is_refused_for_others(self):
        before = height(self.client, CLIENT_BODY)
        self.client.console("size @m 2")
        grew = wait_until(lambda: abs(height(self.client, CLIENT_BODY) - before * 2) < SIZE_TOLERANCE * before * 2)
        self.assertTrue(grew, "own size did not change locally")
        host_before = height(self.client, HOST_BODY)
        self.client.console("size HostD 2")
        refused = wait_until(lambda: "size needs the host" in str(self.client.call("console_log", tail=20)))
        self.assertTrue(refused, str(self.client.call("console_log", tail=20)))
        self.assertAlmostEqual(height(self.client, HOST_BODY), host_before, delta=SIZE_TOLERANCE)
        self.assertAlmostEqual(height(self.host, CLIENT_BODY), before, delta=SIZE_TOLERANCE * before, msg="the host must not see the client's size")

    def test_the_chosen_character_applies_only_on_the_client(self):
        mine = custom_characters(self.client)
        self.assertIn(CLIENT_BODY, mine)
        self.assertEqual(mine[CLIENT_BODY]["slot"], self.chosen_slot)
        self.assertEqual(custom_characters(self.host), {})


@unittest.skipUnless(PAIR_ENABLED, SKIP_REASON)
class C_HostWithPluginsClientWithoutTests(ScenarioCase):
    host_plugins = ("size", "loader", "avali")
    client_plugins = ()

    def test_the_client_is_untouched(self):
        self.assertEqual(observe.size_gate_host_state(self.client), observe.GATE_ABSENT)
        self.assertEqual(custom_characters(self.client), {})
        rows = read_bodies(self.client)
        self.assertEqual(rows[CLIENT_BODY]["charType"], 0)
        self.assertEqual(rows[HOST_BODY]["charType"], 0)

    def test_the_host_sent_the_client_nothing(self):
        counters = self.host.call("net_counters")
        self.assertTrue(counters["installed"], counters["status"])
        self.assertEqual(counters["counts"], {}, counters)

    def test_the_host_has_no_confirmed_peer(self):
        peers = observe.size_gate_peers(self.host)
        self.assertNotIn("Confirmed", [str(value) for value in peers.values()], peers)

    def test_sizing_the_client_from_the_host_changes_nothing_on_the_client(self):
        before = height(self.client, CLIENT_BODY)
        self.host.console("size ClientD 2")
        time.sleep(REPLICATION_SECONDS / 2)
        self.assertAlmostEqual(height(self.client, CLIENT_BODY), before, delta=SIZE_TOLERANCE * before)

    def test_no_errors_in_either_log(self):
        self.assert_logs_clean()


@unittest.skipUnless(PAIR_ENABLED, SKIP_REASON)
class B_BothWithPluginsTests(ScenarioCase):
    host_plugins = ("size", "loader", "avali")
    client_plugins = ("size", "loader", "avali")
    choose_character = True

    def test_both_gates_confirm(self):
        self.assertEqual(observe.size_gate_host_state(self.client), "Confirmed")
        self.assertEqual(observe.loader_host_state(self.client), "Welcomed")
        peers = observe.size_gate_peers(self.host)
        self.assertIn("Confirmed", [str(value) for value in peers.values()], peers)

    def test_host_sizes_the_client_and_it_shows_on_the_client_body(self):
        before = height(self.client, CLIENT_BODY)
        self.host.console("size ClientD 2")
        for game in (self.host, self.client):
            grew = wait_until(lambda g=game: abs(height(g, CLIENT_BODY) - before * 2) < SIZE_TOLERANCE * before * 2)
            self.assertTrue(grew, "client body did not reach x2 on port %s" % game.transport.port)
        self.host.console("size @a reset")

    def test_the_client_character_applies_on_both_games(self):
        for game in (self.host, self.client):
            found = wait_until(lambda g=game: custom_characters(g).get(CLIENT_BODY))
            self.assertTrue(found, "no custom character on %s as seen on port %s" % (CLIENT_BODY, game.transport.port))
            self.assertEqual(found["slot"], self.chosen_slot)
        rows = [read_bodies(game)[CLIENT_BODY] for game in (self.host, self.client)]
        self.assertEqual(rows[0]["charType"], rows[1]["charType"])
        self.assertEqual(rows[0]["skills"], rows[1]["skills"])

    def test_a_player_who_joins_late_sees_the_current_state(self):
        self.host.console("size @m 2")
        before = height(self.client, HOST_BODY)
        self.client.console("disconnect")
        time.sleep(3.0)
        self.host.console("size @m 3")
        time.sleep(1.0)
        self.client.console("connect 127.0.0.1:7790")
        wait_for_bodies(self.client, 2)
        late = wait_until(lambda: height(self.client, HOST_BODY) > before * 1.2, REPLICATION_SECONDS * 2)
        self.assertTrue(late, "rejoined client did not receive the host size")
        self.host.console("size @a reset")

    def test_no_errors_in_either_log(self):
        self.assert_logs_clean()


@unittest.skipUnless(PAIR_ENABLED, SKIP_REASON)
class D_DifferentPackSetsTests(ScenarioCase):
    host_plugins = ("size", "loader", "samplepack")
    client_plugins = ("size", "loader", "avali")
    choose_character = True

    def test_both_games_keep_running(self):
        for game in (self.host, self.client):
            self.assertEqual(game.state()["state"], "in-world")

    def test_the_loader_refuses_the_mismatching_pack_set(self):
        self.assertEqual(observe.loader_host_state(self.client), "Refused")

    def test_size_still_works_between_them(self):
        self.assertEqual(observe.size_gate_host_state(self.client), "Confirmed")

    def test_the_clients_character_is_not_shown_on_the_host(self):
        self.assertNotIn(CLIENT_BODY, custom_characters(self.host))

    def test_no_errors_in_either_log(self):
        self.assert_logs_clean()


if __name__ == "__main__":
    unittest.main()
