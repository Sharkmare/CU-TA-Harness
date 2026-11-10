import time

from .parsing import LinkError
from .transport import Transport

CHARACTERS = {0: "Experiment", 1: "Milky", 2: "Dune"}
EVENT_POLL_MS = 500


class Game:
    def __init__(self, port=None):
        self.transport = Transport(port)
        self.events_cursor = 0

    def call(self, command, **arguments):
        return self.transport.call(command, arguments)

    def status(self):
        return self.call("status")

    def describe(self):
        return self.transport.describe()

    def state(self):
        return self.call("state")

    def start_run(self, character=0, preset=None, settings=None, skip_tutorial=True):
        arguments = {"character": character, "skip_tutorial": skip_tutorial}
        if preset:
            arguments["preset"] = preset
        if settings:
            arguments["settings"] = settings
        return self.call("start_run", **arguments)

    def wait_state(self, state, timeout=60.0):
        return self.call("wait_state", state=state, timeout=timeout)

    def quit_to_menu(self):
        return self.call("quit_to_menu")

    def console(self, line):
        return self.call("console", line=line)

    def spawn(self, item_id, **options):
        return self.call("spawn", id=item_id, **options)

    def list_items(self, item_id=None, limit=100):
        return self.call("list_items", id=item_id, limit=limit) if item_id else self.call("list_items", limit=limit)

    def player(self):
        return self.call("player")

    def get(self, target, path="", depth=1):
        return self.call("get", target=target, path=path, depth=depth)

    def set(self, target, path, value):
        return self.call("set", target=target, path=path, value=value)

    def timescale(self, value):
        return self.call("timescale", value=value)

    def step(self, frames=1):
        return self.call("step", frames=frames)

    def tap(self, action=None, key=None, frames=3):
        return self.call("input", **self._key_arguments(action, key, "tap", frames))

    def hold(self, action=None, key=None):
        return self.call("input", **self._key_arguments(action, key, "hold", 0))

    def release(self, action=None, key=None):
        return self.call("input", **self._key_arguments(action, key, "release", 0))

    @staticmethod
    def _key_arguments(action, key, mode, frames):
        arguments = {"mode": mode, "frames": frames}
        if action:
            arguments["action"] = action
        if key:
            arguments["key"] = key
        return arguments

    def screenshot(self, path):
        return self.call("screenshot", path=path)

    def save(self):
        return self.call("save")

    def load(self):
        return self.call("load")

    def log(self, since=0, tail=200, contains=None):
        arguments = {"since": since, "tail": tail}
        if contains:
            arguments["contains"] = contains
        return self.call("log", **arguments)

    def events(self, since=None, wait_ms=0, event_type=None):
        cursor = self.events_cursor if since is None else since
        return self.transport.events(cursor, wait_ms, event_type)["events"]

    def mark_events(self):
        self.events_cursor = self.transport.events(0, 0, limit=1)["last"]
        return self.events_cursor

    def wait_event(self, event_type, timeout=15.0, predicate=None):
        deadline = time.time() + timeout
        cursor = self.events_cursor
        while time.time() < deadline:
            for event in self.transport.events(cursor, EVENT_POLL_MS, event_type)["events"]:
                cursor = event["seq"]
                if predicate is None or predicate(event):
                    return event
        raise LinkError("no %s event within %.0fs" % (event_type, timeout))

    def ensure_menu(self):
        current = self.state()["state"]
        if current == "in-world":
            self.quit_to_menu()
        elif current == "loading":
            self.wait_state("menu")
