import socket
import unittest

from casualtieslink import Game, LinkError
from casualtieslink.transport import REQUIRED_HEADER, Transport

from .fake_link import FakeFailure, FakeLink


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class TransportTests(unittest.TestCase):
    def test_a_call_posts_json_with_the_required_header_and_returns_the_result(self):
        with FakeLink({"status": {"state": "menu"}}) as link:
            result = Transport(link.port).call("status", {"a": 1})
        self.assertEqual(result, {"state": "menu"})
        name, arguments, headers = link.calls[0]
        self.assertEqual((name, arguments), ("status", {"a": 1}))
        self.assertIn(REQUIRED_HEADER.lower(), [key.lower() for key in headers])

    def test_an_error_reply_becomes_a_link_error_with_status_and_kind(self):
        def refuse(arguments):
            raise FakeFailure("not in a world", 400, "Exception")
        with FakeLink({"player": refuse}) as link:
            with self.assertRaises(LinkError) as caught:
                Transport(link.port).call("player")
        self.assertEqual((str(caught.exception), caught.exception.status, caught.exception.kind), ("not in a world", 400, "Exception"))

    def test_an_unknown_command_is_a_404_link_error(self):
        with FakeLink() as link:
            with self.assertRaises(LinkError) as caught:
                Transport(link.port).call("nope")
        self.assertEqual(caught.exception.status, 404)

    def test_a_closed_port_raises_an_os_error(self):
        with self.assertRaises(OSError):
            Transport(free_port()).call("status", timeout=2.0)

    def test_is_up_is_true_when_status_answers(self):
        with FakeLink({"status": {}}) as link:
            self.assertTrue(Transport(link.port).is_up())

    def test_describe_returns_the_command_list(self):
        commands = [{"name": "status", "doc": "d", "args": []}]
        with FakeLink(commands=commands) as link:
            self.assertEqual(Transport(link.port).describe()["commands"], commands)

    def test_events_pass_every_query_field(self):
        with FakeLink(events=[{"seq": 4, "type": "damage"}, {"seq": 5, "type": "death"}]) as link:
            reply = Transport(link.port).events(since=3, wait_ms=0, event_type="death", limit=7)
        self.assertEqual(link.event_queries[0], {"since": "3", "wait": "0", "limit": "7", "type": "death"})
        self.assertEqual([e["seq"] for e in reply["events"]], [5])


class GameTests(unittest.TestCase):
    def check(self, call, command, expected_arguments):
        with FakeLink({command: {"ok": True}}) as link:
            call(Game(link.port))
        self.assertEqual(link.calls_to(command), [expected_arguments])

    def test_start_run_sends_character_and_options(self):
        self.check(lambda g: g.start_run(2, preset="easy", settings={"healingrate": 2.0}), "start_run",
                   {"character": 2, "skip_tutorial": True, "preset": "easy", "settings": {"healingrate": 2.0}})

    def test_start_run_leaves_out_unset_options(self):
        self.check(lambda g: g.start_run(), "start_run", {"character": 0, "skip_tutorial": True})

    def test_tap_hold_and_release_become_input_commands(self):
        self.check(lambda g: g.tap(action="up"), "input", {"mode": "tap", "frames": 3, "action": "up"})
        self.check(lambda g: g.hold(key="D"), "input", {"mode": "hold", "frames": 0, "key": "D"})
        self.check(lambda g: g.release(action="attack"), "input", {"mode": "release", "frames": 0, "action": "attack"})

    def test_spawn_console_step_and_timescale(self):
        self.check(lambda g: g.spawn("bandage", condition=0.5), "spawn", {"id": "bandage", "condition": 0.5})
        self.check(lambda g: g.console("heal"), "console", {"line": "heal"})
        self.check(lambda g: g.step(7), "step", {"frames": 7})
        self.check(lambda g: g.timescale(0), "timescale", {"value": 0})

    def test_get_and_set_send_target_and_path(self):
        self.check(lambda g: g.get("player", "hunger", depth=2), "get", {"target": "player", "path": "hunger", "depth": 2})
        self.check(lambda g: g.set("player", "hunger", 40), "set", {"target": "player", "path": "hunger", "value": 40})

    def test_list_items_filters_only_when_asked(self):
        self.check(lambda g: g.list_items(), "list_items", {"limit": 100})
        self.check(lambda g: g.list_items("bandage", limit=5), "list_items", {"id": "bandage", "limit": 5})

    def test_log_sends_contains_only_when_given(self):
        self.check(lambda g: g.log(since=3, tail=10), "log", {"since": 3, "tail": 10})
        self.check(lambda g: g.log(contains="Error"), "log", {"since": 0, "tail": 200, "contains": "Error"})

    def test_simple_commands_have_no_arguments(self):
        for method, command in (("save", "save"), ("load", "load"), ("quit_to_menu", "quit_to_menu"), ("player", "player"), ("state", "state")):
            self.check(lambda g, m=method: getattr(g, m)(), command, {})

    def test_screenshot_sends_the_path(self):
        self.check(lambda g: g.screenshot("a.png"), "screenshot", {"path": "a.png"})

    def test_wait_event_returns_the_first_event_that_matches_the_predicate(self):
        events = [{"seq": 1, "type": "damage", "data": {"index": 1}}, {"seq": 2, "type": "damage", "data": {"index": 3}}]
        with FakeLink(events=events) as link:
            game = Game(link.port)
            found = game.wait_event("damage", timeout=3, predicate=lambda e: e["data"]["index"] == 3)
        self.assertEqual(found["seq"], 2)

    def test_wait_event_times_out_with_a_link_error(self):
        with FakeLink(events=[]) as link:
            with self.assertRaises(LinkError):
                Game(link.port).wait_event("death", timeout=0.1)

    def test_mark_events_hides_older_events(self):
        events = [{"seq": 1, "type": "damage", "data": {}}]
        with FakeLink(events=events) as link:
            game = Game(link.port)
            game.mark_events()
            self.assertEqual(game.events(), [])
            link.events.append({"seq": 2, "type": "damage", "data": {}})
            self.assertEqual([e["seq"] for e in game.events()], [2])

    def test_ensure_menu_leaves_a_world_and_waits_for_a_loading_game(self):
        with FakeLink({"state": {"state": "in-world"}, "quit_to_menu": {}}) as link:
            Game(link.port).ensure_menu()
        self.assertEqual(len(link.calls_to("quit_to_menu")), 1)
        with FakeLink({"state": {"state": "loading"}, "wait_state": {}}) as link:
            Game(link.port).ensure_menu()
        self.assertEqual(link.calls_to("wait_state"), [{"state": "menu", "timeout": 60.0}])
        with FakeLink({"state": {"state": "menu"}}) as link:
            Game(link.port).ensure_menu()
        self.assertEqual([name for name, _, _ in link.calls], ["state"])


if __name__ == "__main__":
    unittest.main()
