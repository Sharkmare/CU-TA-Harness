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
LOADER_PREFIX = "CasualtiesCharacters."
LOADER_HELLO = LOADER_PREFIX + "Hello"
LOADER_MESSAGE_NAMES = [LOADER_PREFIX + name for name in ("Hello", "Welcome", "Choose", "Changed")]
HELLO_SENDS_AT_MOST = 3
HELLO_SENDS_AT_LEAST = 2
LOADER_INERT_LINE = "characters are available in singleplayer only"
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
    try:
        slot = int(game.get("static:CasualtiesCharacters.Registry", "HighestId"))
    except Exception:
        return None
    if slot < FIRST_CUSTOM_CHARACTER:
        return None
    game.set("static:PreRunScript", "characterSelected", slot)
    return slot


def custom_characters(game):
    try:
        rows = game.call("find", type="CustomCharacter")
    except Exception as exception:
        print("custom_characters on port %s: %s" % (game.transport.port, exception))
        return {}
    result = {}
    for row in rows:
        handle = "id:%d" % row["object"]["id"]
        body = game.get(handle, "Body", depth=0)
        result[body["name"]] = {"slot": game.get(handle, "Id")}
    return result


def sent_to_host_names(game, hashes):
    counters = game.call("net_counters")
    return counters, observe.sent_by_direction(counters["counts"], hashes)


class ScenarioCase(unittest.TestCase):
    host_plugins = ()
    client_plugins = ()
    choose_character = False
    together = "stock"

    @classmethod
    def setUpClass(cls):
        if not PAIR_ENABLED or GAMES is None:
            raise unittest.SkipTest(SKIP_REASON)
        hook = None
        if cls.choose_character:
            def hook(game):
                cls.chosen_slot = choose_loader_character(game)
        cls.host, cls.client = GAMES.start(list(cls.host_plugins), list(cls.client_plugins), after_client_link=hook, together=cls.together)
        cls.host.wait_state("in-world", timeout=WORLD_WAIT_SECONDS)
        cls.client.wait_state("in-world", timeout=WORLD_WAIT_SECONDS)
        wait_for_bodies(cls.host, 2)
        wait_for_bodies(cls.client, 2)
        cls.host.call("close_console")
        cls.client.call("close_console")
        time.sleep(HELLO_SECONDS)
        cls.hashes = observe.message_hashes(cls.client, [SIZE_HELLO] + LOADER_MESSAGE_NAMES)

    @classmethod
    def plugin_log_lines(cls, which):
        wanted = ("casualties", "bridge", "together bridge", "exception", "[error", "[warning")
        return [line for line in GAMES.log_text(which).splitlines() if any(word in line.lower() for word in wanted)]

    @classmethod
    def tearDownClass(cls):
        if GAMES is not None:
            for which in ("host", "client"):
                print("\n%s %s log lines about our plugins:" % (cls.__name__, which))
                for line in cls.plugin_log_lines(which)[:60]:
                    print("  " + line[:220])
            for label, game in (("host", getattr(cls, "host", None)), ("client", getattr(cls, "client", None))):
                if game is not None:
                    try:
                        print("\n%s %s counters: %s" % (cls.__name__, label, game.call("net_counters")))
                    except Exception:
                        pass
            GAMES.stop()

    def logs(self, which):
        return GAMES.log_text(which) + "\n" + GAMES.log_text(which, os.path.join("BepInEx", "TogetherLogs", "together.log"))

    def assert_characters_inert(self):
        for label, game in (("host", self.host), ("client", self.client)):
            counters = game.call("net_counters")
            self.assertTrue(counters["installed"], counters["status"])
            self.assertEqual(observe.names_seen(counters["counts"], self.hashes, LOADER_PREFIX), set(), "%s sent loader messages: %s" % (label, counters["counts"]))
            self.assertEqual(observe.skin_appliers(game), 0, "%s has a skin applier" % label)
            self.assertEqual(custom_characters(game), {}, "%s has a custom character" % label)
            for name, row in read_bodies(game).items():
                self.assertEqual(row["charType"], 0, "%s: %s is not vanilla" % (label, name))
            self.assertEqual(observe.loader_host_state(game), observe.GATE_ABSENT, label)

    def assert_logs_clean(self):
        for which in ("host", "client"):
            self.assertEqual(observe.suspicious_lines(self.logs(which)), [], "%s log" % which)


@unittest.skipUnless(PAIR_ENABLED, SKIP_REASON)
class A_StockHostClientWithPluginsTests(ScenarioCase):
    host_plugins = ()
    client_plugins = ("size", "loader", "avali")
    choose_character = True

    def test_the_size_gate_reports_the_host_as_not_ours(self):
        self.assertEqual(observe.size_gate_host_state(self.client), "NotOurs")

    def test_the_loader_and_avali_are_inert_on_stock_together(self):
        self.assert_characters_inert()
        self.assertIn(LOADER_INERT_LINE, GAMES.log_text("client"))

    def test_the_host_has_none_of_our_plugins(self):
        self.assertEqual(observe.size_gate_host_state(self.host), observe.GATE_ABSENT)
        self.assertEqual(observe.loader_host_state(self.host), observe.GATE_ABSENT)

    def test_no_errors_or_unknown_message_complaints_in_either_log(self):
        self.assert_logs_clean()

    def test_the_client_sent_nothing_but_the_hellos(self):
        counters, sent = sent_to_host_names(self.client, self.hashes)
        self.assertTrue(counters["installed"], counters["status"])
        self.assertEqual(sorted(sent), ["toHost"], sent)
        self.assertEqual(sorted(sent["toHost"]), [SIZE_HELLO], sent)
        for name, count in sent["toHost"].items():
            self.assertGreaterEqual(count, HELLO_SENDS_AT_LEAST, name)
            self.assertLessEqual(count, HELLO_SENDS_AT_MOST, name)
        time.sleep(HELLO_SECONDS / 2)
        _, later = sent_to_host_names(self.client, self.hashes)
        self.assertEqual(later, sent, "messages kept going after the hello timeout")

    def test_the_host_sent_nothing_of_ours(self):
        counters, _ = sent_to_host_names(self.host, self.hashes)
        self.assertEqual(counters["counts"], {}, counters)

    def test_the_client_can_size_itself_locally(self):
        before = height(self.client, CLIENT_BODY)
        reply = self.client.console("size @m 2")
        grew = wait_until(lambda: abs(height(self.client, CLIENT_BODY) - before * 2) < SIZE_TOLERANCE * before * 2)
        self.assertTrue(grew, "own size did not change locally: height %s before %s, console reply: %s" % (
            height(self.client, CLIENT_BODY), before, reply))
        self.assertAlmostEqual(height(self.host, CLIENT_BODY), before, delta=SIZE_TOLERANCE * before, msg="the host must not see the client's size")

    def test_the_client_is_refused_for_other_players_with_the_clear_text(self):
        before = height(self.client, CLIENT_BODY)
        host_before = height(self.client, HOST_BODY)
        self.client.console("size HostD 2")
        refused = wait_until(lambda: "sizing other players needs the host to run CasualtiesSize" in str(self.client.call("console_log", tail=20)))
        self.assertTrue(refused, str(self.client.call("console_log", tail=20)))
        self.assertAlmostEqual(height(self.client, HOST_BODY), host_before, delta=SIZE_TOLERANCE)
        self.assertAlmostEqual(height(self.host, HOST_BODY), host_before, delta=SIZE_TOLERANCE)



class StockFlavourMixin:
    flavour = None

    def test_the_switch_picked_the_flavour_on_both_games(self):
        for which in ("host", "client"):
            lines = observe.flavour_switch_lines(GAMES.log_text(which))
            self.assertEqual(len(lines), 1, "%s: %s" % (which, lines))
            self.assertEqual(lines[0]["flavour"], self.flavour, lines)
            self.assertEqual(observe.together_version(GAMES.log_text(which)), self.flavour.rpartition("-")[2], which)


@unittest.skipUnless(PAIR_ENABLED, SKIP_REASON)
class A_Stock550Tests(StockFlavourMixin, A_StockHostClientWithPluginsTests):
    together = "flavour:stock-5.5.0"
    flavour = "stock-5.5.0"


@unittest.skipUnless(PAIR_ENABLED, SKIP_REASON)
class A_Stock540Tests(StockFlavourMixin, A_StockHostClientWithPluginsTests):
    together = "flavour:stock-5.4.0"
    flavour = "stock-5.4.0"


@unittest.skipUnless(PAIR_ENABLED, SKIP_REASON)
class C_HostWithPluginsClientWithoutTests(ScenarioCase):
    host_plugins = ("size", "loader", "avali")
    client_plugins = ()

    def test_the_client_is_untouched(self):
        self.assertEqual(observe.size_gate_host_state(self.client), observe.GATE_ABSENT)
        self.assert_characters_inert()

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
    host_plugins = ("size",)
    client_plugins = ("size",)

    def test_the_size_gates_confirm_both_ways(self):
        self.assertEqual(observe.size_gate_host_state(self.client), "Confirmed")
        peers = observe.size_gate_peers(self.host)
        self.assertIn("Confirmed", [str(value) for value in peers.values()], peers)

    def test_host_sizes_the_client_and_it_shows_on_the_client_body(self):
        before = height(self.client, CLIENT_BODY)
        self.host.console("size ClientD 2")
        for game in (self.host, self.client):
            grew = wait_until(lambda g=game: abs(height(g, CLIENT_BODY) - before * 2) < SIZE_TOLERANCE * before * 2)
            self.assertTrue(grew, "client body did not reach x2 on port %s" % game.transport.port)
        self.host.console("size @a reset")

    def test_the_client_sent_only_size_messages(self):
        _, sent = sent_to_host_names(self.client, self.hashes)
        self.assertEqual(sorted(sent.get("toHost", {})), [SIZE_HELLO], sent)

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

    def test_the_loader_is_inert_so_pack_sets_cannot_clash(self):
        self.assert_characters_inert()

    def test_size_still_works_between_them(self):
        self.assertEqual(observe.size_gate_host_state(self.client), "Confirmed")

    def test_no_errors_in_either_log(self):
        self.assert_logs_clean()


if __name__ == "__main__":
    unittest.main()
