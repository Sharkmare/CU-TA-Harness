import unittest

from casualtieslink import observe
from casualtieslink.parsing import LinkError

from .fake_link import FakeFailure, FakeLink
from casualtieslink import Game


class SuspiciousLineTests(unittest.TestCase):
    def test_error_lines_that_mention_our_plugins_are_found(self):
        text = "[Info] CasualtiesSize loaded\n[Error] CasualtiesSize bridge failed: Exception x\n[Warning] fine\n"
        self.assertEqual(observe.suspicious_lines(text), ["[Error] CasualtiesSize bridge failed: Exception x"])

    def test_unrelated_errors_are_ignored_unless_asked_for(self):
        text = "[Error] Unity: shader missing\n"
        self.assertEqual(observe.suspicious_lines(text), [])
        self.assertEqual(observe.suspicious_lines(text, anywhere=True), ["[Error] Unity: shader missing"])

    def test_stock_complaints_about_messages_are_found(self):
        text = "something unknown message 1234 ignored\nNullReferenceException in CustomMessage handler\n"
        self.assertEqual(len(observe.suspicious_lines(text, anywhere=True)), 2)

    def test_clean_text_has_nothing(self):
        self.assertEqual(observe.suspicious_lines("all fine\nloaded\n", anywhere=True), [])


class SentSummaryTests(unittest.TestCase):
    def test_counts_are_grouped_by_direction_and_named_when_the_hash_is_known(self):
        counts = {"toHost:0a0b0c0d": 3, "toHost:ffffffff": 1, "toPlayer:0a0b0c0d": 2}
        result = observe.sent_by_direction(counts, {"0a0b0c0d": "size hello"})
        self.assertEqual(result, {"toHost": {"size hello": 3, "ffffffff": 1}, "toPlayer": {"size hello": 2}})

    def test_no_counts_is_empty(self):
        self.assertEqual(observe.sent_by_direction({}, {}), {})


class NamesSeenTests(unittest.TestCase):
    def test_only_names_with_the_prefix_count(self):
        names = {"aa": "CasualtiesSize.Hello", "bb": "CasualtiesCharacters.Hello", "cc": "Other.Thing"}
        counts = {"toHost:aa": 3, "toPlayer:bb": 1, "toHost:cc": 2, "toHost:dd": 4}
        self.assertEqual(observe.names_seen(counts, names, "CasualtiesCharacters."), {"CasualtiesCharacters.Hello"})
        self.assertEqual(observe.names_seen(counts, names, "Nothing."), set())

    def test_unknown_hashes_are_not_matched_to_a_prefix(self):
        self.assertEqual(observe.names_seen({"toHost:zz": 1}, {}, "X."), set())


class SkinApplierTests(unittest.TestCase):
    def test_the_count_comes_from_find(self):
        with FakeLink({"find": [{"object": {"id": 1}}, {"object": {"id": 2}}]}) as link:
            self.assertEqual(observe.skin_appliers(Game(link.port)), 2)

    def test_a_missing_type_counts_as_none(self):
        def missing(arguments):
            raise FakeFailure("no type named 'SkinApplier'")
        with FakeLink({"find": missing}) as link:
            self.assertEqual(observe.skin_appliers(Game(link.port)), 0)


class GateReadTests(unittest.TestCase):
    def test_a_state_is_read_through_a_nonpublic_path(self):
        with FakeLink({"get": lambda args: "NotOurs"}) as link:
            state = observe.size_gate_host_state(Game(link.port))
        self.assertEqual(state, "NotOurs")
        self.assertEqual(link.calls_to("get"), [{"target": "static:CasualtiesSize.TogetherBridge", "path": "Gate.Host", "depth": 0, "nonpublic": True}])

    def test_loader_state_uses_the_stock_bridge_channel(self):
        with FakeLink({"get": lambda args: "Welcomed"}) as link:
            self.assertEqual(observe.loader_host_state(Game(link.port)), "Welcomed")
        self.assertEqual(link.calls_to("get")[0]["target"], "static:CasualtiesCharacters.StockBridge")
        self.assertEqual(link.calls_to("get")[0]["path"], "channel.HostState")

    def test_a_plugin_that_is_not_loaded_reads_as_absent(self):
        def missing(arguments):
            raise FakeFailure("no type named 'TogetherBridge'")
        with FakeLink({"get": missing}) as link:
            self.assertEqual(observe.size_gate_host_state(Game(link.port)), observe.GATE_ABSENT)

    def test_peers_default_to_empty_when_the_plugin_is_missing(self):
        def missing(arguments):
            raise FakeFailure("no type")
        with FakeLink({"get": missing}) as link:
            self.assertEqual(observe.size_gate_peers(Game(link.port)), {})

    def test_message_hashes_map_hash_to_name(self):
        with FakeLink({"message_hash": lambda args: {"name": args["name"], "hash": "aa" if args["name"] == "A" else "bb"}}) as link:
            self.assertEqual(observe.message_hashes(Game(link.port), ["A", "B"]), {"aa": "A", "bb": "B"})


if __name__ == "__main__":
    unittest.main()
