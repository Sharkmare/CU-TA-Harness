import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REQUIRED_HEADER = "X-CasualtiesLink"


class FakeFailure(Exception):
    def __init__(self, message, status=400, kind="Exception"):
        super().__init__(message)
        self.status = status
        self.kind = kind


class FakeLink:
    def __init__(self, handlers=None, events=None, commands=None):
        self.handlers = dict(handlers or {})
        self.events = list(events or [])
        self.commands = list(commands or [])
        self.calls = []
        self.event_queries = []
        self.lock = threading.Lock()
        link = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *arguments):
                pass

            def reply(self, status, envelope):
                body = json.dumps(envelope).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path in ("", "/", "/describe"):
                    self.reply(200, {"ok": True, "result": {"plugin": "fake", "version": "0", "protocol": 1, "commands": link.commands}})
                elif parsed.path == "/events":
                    query = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query).items()}
                    link.event_queries.append(query)
                    self.reply(200, {"ok": True, "result": link.read_events(query)})
                else:
                    self.reply(404, {"ok": False, "error": "unknown GET path", "kind": "LinkException"})

            def do_POST(self):
                if self.headers.get(REQUIRED_HEADER) is None:
                    self.reply(403, {"ok": False, "error": "missing header", "kind": "LinkException"})
                    return
                name = self.path[len("/cmd/"):]
                length = int(self.headers.get("Content-Length", "0"))
                arguments = json.loads(self.rfile.read(length) or b"{}")
                with link.lock:
                    link.calls.append((name, arguments, dict(self.headers)))
                handler = link.handlers.get(name)
                if handler is None:
                    self.reply(404, {"ok": False, "error": "unknown command '%s'; GET /describe lists them" % name, "kind": "LinkException"})
                    return
                try:
                    result = handler(arguments) if callable(handler) else handler
                except FakeFailure as failure:
                    self.reply(failure.status, {"ok": False, "error": str(failure), "kind": failure.kind})
                    return
                self.reply(200, {"ok": True, "result": result})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)

    def read_events(self, query):
        since = int(query.get("since", "0"))
        wait = int(query.get("wait", "0")) / 1000.0
        wanted = query.get("type")
        deadline = time.time() + wait
        while True:
            found = [e for e in self.events if e["seq"] > since and (wanted is None or e["type"] == wanted)]
            if found or time.time() >= deadline:
                return {"events": found[:int(query.get("limit", "500"))], "last": max([e["seq"] for e in self.events] or [0])}
            time.sleep(0.01)

    def calls_to(self, name):
        return [arguments for called, arguments, _ in self.calls if called == name]

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc_info):
        self.server.shutdown()
        self.server.server_close()
