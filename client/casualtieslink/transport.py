import json
import os
import urllib.error
import urllib.request

from .parsing import LinkError, parse_reply

DEFAULT_PORT = 7650
PORT_ENVIRONMENT_VARIABLE = "CASUALTIES_LINK_PORT"
REQUIRED_HEADER = "X-CasualtiesLink"
LOOPBACK = "127.0.0.1"
COMMAND_TIMEOUT_SECONDS = 140.0


def default_port():
    return int(os.environ.get(PORT_ENVIRONMENT_VARIABLE, DEFAULT_PORT))


class Transport:
    def __init__(self, port=None, host=LOOPBACK):
        self.port = port if port is not None else default_port()
        self.base = "http://%s:%d" % (host, self.port)

    def _open(self, request, timeout):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def call(self, command, arguments=None, timeout=COMMAND_TIMEOUT_SECONDS):
        body = json.dumps(arguments or {}).encode("utf-8")
        request = urllib.request.Request(
            "%s/cmd/%s" % (self.base, command), data=body, method="POST",
            headers={REQUIRED_HEADER: "1", "Content-Type": "application/json"})
        status, text = self._open(request, timeout)
        return parse_reply(text, status)

    def get(self, path, timeout=COMMAND_TIMEOUT_SECONDS):
        status, text = self._open(urllib.request.Request(self.base + path, method="GET"), timeout)
        return parse_reply(text, status)

    def describe(self):
        return self.get("/describe")

    def events(self, since=0, wait_ms=0, event_type=None, limit=500):
        path = "/events?since=%d&wait=%d&limit=%d" % (since, wait_ms, limit)
        if event_type:
            path += "&type=" + event_type
        return self.get(path, timeout=wait_ms / 1000.0 + 15.0)

    def is_up(self):
        try:
            self.call("status", timeout=5.0)
            return True
        except (OSError, LinkError):
            return False
