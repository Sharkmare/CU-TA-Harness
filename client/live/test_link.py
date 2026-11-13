import http.client
import unittest

from casualtieslink import LinkError
from casualtieslink.parsing import find_command

from live import shared_game


class LinkProtocolTests(unittest.TestCase):
    def test_status_reports_version_and_protocol(self):
        status = shared_game.game().status()
        self.assertEqual(status["plugin"], "CasualtiesLink")
        self.assertEqual(status["protocol"], 1)
        self.assertIn(status["state"], ("menu", "pre-run", "in-world", "loading"))
        self.assertGreater(status["frame"], 0)

    def test_describe_documents_every_command_with_arguments(self):
        description = shared_game.game().describe()
        names = [command["name"] for command in description["commands"]]
        for expected in ("status", "start_run", "console", "spawn", "player", "input", "get", "set", "screenshot", "save", "load"):
            self.assertIn(expected, names)
        for command in description["commands"]:
            self.assertTrue(command["doc"], "%s has no doc" % command["name"])
        start_run = find_command(description, "start_run")
        self.assertIn("character", [argument["name"] for argument in start_run["args"]])

    def test_unknown_command_is_a_404_with_a_hint(self):
        with self.assertRaises(LinkError) as caught:
            shared_game.game().call("no_such_command")
        self.assertEqual(caught.exception.status, 404)
        self.assertIn("describe", str(caught.exception))

    def test_missing_required_argument_is_an_error(self):
        with self.assertRaises(LinkError):
            shared_game.game().call("console")

    def _raw(self, method, path, headers):
        port = shared_game.game().transport.port
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.putrequest(method, path, skip_host="Host" in headers)
        for name, value in headers.items():
            connection.putheader(name, value)
        connection.endheaders(b"{}" if method == "POST" else None)
        response = connection.getresponse()
        status = response.status
        response.read()
        connection.close()
        return status

    def test_post_without_the_custom_header_is_refused(self):
        self.assertEqual(self._raw("POST", "/cmd/status", {"Content-Length": "2"}), 403)

    def test_browser_origin_is_refused(self):
        headers = {"Content-Length": "2", "X-CasualtiesLink": "1", "Origin": "http://evil.example"}
        self.assertEqual(self._raw("POST", "/cmd/status", headers), 403)

    def test_foreign_host_header_is_refused(self):
        headers = {"Host": "evil.example", "Content-Length": "2", "X-CasualtiesLink": "1"}
        self.assertIn(self._raw("POST", "/cmd/status", headers), (400, 403))

    def test_describe_type_lists_game_fields(self):
        reply = shared_game.game().call("describe_type", type="Body")
        self.assertIn("brainHealth", [member["name"] for member in reply["members"]])


if __name__ == "__main__":
    unittest.main()
