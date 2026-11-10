import contextlib
import io
import json
import unittest

from casualtieslink import cli

from .fake_link import FakeFailure, FakeLink

COMMANDS = [
    {"name": "spawn", "doc": "Creates an item", "args": [{"name": "id", "type": "string", "required": True, "doc": "", "default": None}]},
    {"name": "status", "doc": "Status", "args": []},
]


def run_cli(*arguments):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(arguments))
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def test_status_prints_the_reply_as_json(self):
        with FakeLink({"status": {"state": "menu", "pid": 5}}) as link:
            code, out, _ = run_cli("--port", str(link.port), "status")
        self.assertEqual((code, json.loads(out)), (0, {"state": "menu", "pid": 5}))

    def test_call_parses_key_value_pairs_as_json_when_it_can(self):
        with FakeLink({"spawn": {"made": 1}}, commands=COMMANDS) as link:
            code, out, _ = run_cli("--port", str(link.port), "call", "spawn", "id=bandage", "amount=3", "pickup=true")
        self.assertEqual(code, 0)
        self.assertEqual(link.calls_to("spawn"), [{"id": "bandage", "amount": 3, "pickup": True}])

    def test_call_refuses_a_missing_required_argument_before_sending_anything(self):
        with FakeLink({"spawn": {}}, commands=COMMANDS) as link:
            code, _, err = run_cli("--port", str(link.port), "call", "spawn", "amount=3")
        self.assertEqual(code, 1)
        self.assertIn("missing required arguments: id", err)
        self.assertEqual(link.calls_to("spawn"), [])

    def test_a_game_error_gives_exit_code_1_and_the_message_on_stderr(self):
        def refuse(arguments):
            raise FakeFailure("not in a world")
        with FakeLink({"player": refuse}, commands=COMMANDS) as link:
            code, out, err = run_cli("--port", str(link.port), "call", "player")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("not in a world", err)

    def test_a_key_without_equals_is_an_error(self):
        with FakeLink({"spawn": {}}, commands=COMMANDS) as link:
            code, _, err = run_cli("--port", str(link.port), "call", "spawn", "oops")
        self.assertEqual(code, 1)
        self.assertIn("key=value", err)

    def test_describe_lists_commands_and_marks_required_arguments(self):
        with FakeLink(commands=COMMANDS) as link:
            code, out, _ = run_cli("--port", str(link.port), "describe")
        self.assertEqual(code, 0)
        self.assertIn("spawn", out)
        self.assertIn("(id*)", out)

    def test_describe_one_command_prints_its_spec_and_an_unknown_one_fails(self):
        with FakeLink(commands=COMMANDS) as link:
            code, out, _ = run_cli("--port", str(link.port), "describe", "spawn")
            self.assertEqual((code, json.loads(out)["name"]), (0, "spawn"))
            code, _, err = run_cli("--port", str(link.port), "describe", "nope")
        self.assertEqual(code, 1)
        self.assertIn("nope", err)

    def test_events_pass_since_wait_and_type(self):
        with FakeLink(events=[{"seq": 9, "type": "death"}]) as link:
            code, out, _ = run_cli("--port", str(link.port), "events", "--since", "2", "--wait-ms", "0", "--type", "death")
        self.assertEqual(code, 0)
        self.assertEqual(link.event_queries[0]["since"], "2")
        self.assertEqual(json.loads(out)["events"][0]["seq"], 9)

    def test_the_mp_flag_parser_splits_name_and_value(self):
        self.assertEqual(cli.parse_mp_flags(["starthost", "setname=Alice"]), {"starthost": True, "setname": "Alice"})


if __name__ == "__main__":
    unittest.main()
