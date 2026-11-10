import json
import unittest

from casualtieslink.launcher import mp_arguments
from casualtieslink.parsing import LinkError, parse_key_values, parse_reply, parse_value


class ParsingTests(unittest.TestCase):
    def test_ok_reply_returns_the_result(self):
        self.assertEqual(parse_reply(json.dumps({"ok": True, "result": {"a": 1}})), {"a": 1})

    def test_error_reply_raises_with_kind_and_status(self):
        with self.assertRaises(LinkError) as caught:
            parse_reply(json.dumps({"ok": False, "error": "nope", "kind": "LinkException"}), 404)
        self.assertEqual((str(caught.exception), caught.exception.kind, caught.exception.status), ("nope", "LinkException", 404))

    def test_non_json_reply_raises(self):
        with self.assertRaises(LinkError):
            parse_reply("<html>")

    def test_key_values_parse_json_when_possible(self):
        self.assertEqual(parse_key_values(["a=1", "b=true", "c=hello", 'd={"x":2}']), {"a": 1, "b": True, "c": "hello", "d": {"x": 2}})
        self.assertEqual(parse_value("bandage"), "bandage")

    def test_key_value_without_equals_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_key_values(["oops"])

    def test_mp_arguments_build_the_mod_flags(self):
        self.assertEqual(mp_arguments({"starthost": True, "setname": "Alice", "ip-port": "127.0.0.1:7777"}),
                         ["--mp-starthost", "--mp-setname", "Alice", "--mp-ip-port", "127.0.0.1:7777"])

    def test_unknown_mp_flag_is_rejected(self):
        with self.assertRaises(ValueError):
            mp_arguments({"bogus": True})


if __name__ == "__main__":
    unittest.main()
