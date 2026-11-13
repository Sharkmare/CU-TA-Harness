import heapq
import itertools
import json
import random
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOOPBACK = "127.0.0.1"
RECEIVE_BUFFER_BYTES = 65535
SOCKET_POLL_SECONDS = 0.2
MILLISECONDS_PER_SECOND = 1000.0
REORDER_EXTRA_DELAY_MS = 30.0
SETTING_NAMES = ("delay_ms", "jitter_ms", "loss", "reorder")
MAX_DELAY_MS = 5000.0
ALLOWED_CONTROL_HOSTS = ("127.0.0.1", "localhost")
CONTROL_BODY_LIMIT_BYTES = 4096


def validate_settings(delay_ms, jitter_ms, loss, reorder):
    if not 0 <= delay_ms <= MAX_DELAY_MS or not 0 <= jitter_ms <= MAX_DELAY_MS:
        raise ValueError("delay and jitter must be between 0 and %g ms" % MAX_DELAY_MS)
    if not 0 <= loss <= 1 or not 0 <= reorder <= 1:
        raise ValueError("loss and reorder are probabilities between 0 and 1")


class DelayProxy:
    """Forwards UDP between clients and a target with a one way delay that can change while it runs.

    Ordering: while delay, jitter, loss and reorder stay constant and jitter and reorder are 0, packets keep their order in each
    direction. Jitter, reorder (a fixed extra delay of REORDER_EXTRA_DELAY_MS for the chosen share of packets) and lowering the
    delay mid stream can all make a later packet overtake an earlier one. Loss drops packets. Jitter, loss and reorder draw from
    a random generator seeded with `seed`, so a run can be repeated.
    """

    def __init__(self, listen_port, target_port, delay_ms=0.0, jitter_ms=0.0, target_host=LOOPBACK, seed=None, clock=time.monotonic, loss=0.0, reorder=0.0):
        validate_settings(delay_ms, jitter_ms, loss, reorder)
        self.listen_port = listen_port
        self.target = (target_host, target_port)
        self.seed = seed if seed is not None else random.randrange(1, 2 ** 31)
        self.random = random.Random(self.seed)
        self.clock = clock
        self.settings_lock = threading.Lock()
        self.delay_ms = float(delay_ms)
        self.jitter_ms = float(jitter_ms)
        self.loss = float(loss)
        self.reorder = float(reorder)
        self.front = None
        self.upstreams = {}
        self.queue = []
        self.sequence = itertools.count()
        self.condition = threading.Condition()
        self.running = False
        self.threads = []
        self.control = None
        self.forwarded = {"toHost": 0, "toClient": 0}
        self.dropped = {"toHost": 0, "toClient": 0}
        self.planned = []
        self.trace = []

    def start(self):
        self.front = self.bound_socket(self.listen_port)
        self.running = True
        self.spawn(self.front_loop)
        self.spawn(self.send_loop)
        return self

    def stop(self):
        self.running = False
        if self.control is not None:
            self.control.stop()
            self.control = None
        with self.condition:
            self.condition.notify_all()
        for thread in self.threads:
            thread.join(timeout=2.0)
        for sock in [self.front] + list(self.upstreams.values()):
            if sock is not None:
                sock.close()
        self.upstreams.clear()
        self.threads = []

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def set(self, delay_ms=None, jitter_ms=None, loss=None, reorder=None):
        with self.settings_lock:
            new = (self.delay_ms if delay_ms is None else float(delay_ms),
                   self.jitter_ms if jitter_ms is None else float(jitter_ms),
                   self.loss if loss is None else float(loss),
                   self.reorder if reorder is None else float(reorder))
            validate_settings(*new)
            self.delay_ms, self.jitter_ms, self.loss, self.reorder = new

    def get(self):
        with self.settings_lock:
            return {"delay_ms": self.delay_ms, "jitter_ms": self.jitter_ms, "loss": self.loss, "reorder": self.reorder, "seed": self.seed}

    def mark(self):
        return len(self.planned)

    def trace_mark(self):
        return len(self.trace)

    def trace_since(self, mark=0):
        """Every packet forwarded since the mark: (moment the proxy received it on its clock, direction, size in bytes, delay in ms it was given)."""
        return list(self.trace[mark:])

    def delay_stats(self, mark=0):
        stats = {}
        for direction in ("toHost", "toClient"):
            values = [delay for name, delay in self.planned[mark:] if name == direction]
            stats[direction] = {"packets": len(values), "minMs": round(min(values), 2) if values else None,
                                "meanMs": round(sum(values) / len(values), 2) if values else None, "maxMs": round(max(values), 2) if values else None}
        stats["dropped"] = dict(self.dropped)
        return stats

    def start_control(self, port):
        self.control = ControlServer(self, port).start()
        return self.control

    @staticmethod
    def bound_socket(port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((LOOPBACK, port))
        sock.settimeout(SOCKET_POLL_SECONDS)
        return sock

    def spawn(self, target, *arguments):
        thread = threading.Thread(target=target, args=arguments, daemon=True)
        thread.start()
        self.threads.append(thread)

    def plan_packet(self):
        with self.settings_lock:
            delay, jitter, loss, reorder = self.delay_ms, self.jitter_ms, self.loss, self.reorder
            if loss and self.random.random() < loss:
                return None
            total = delay + (self.random.uniform(0.0, jitter) if jitter else 0.0)
            if reorder and self.random.random() < reorder:
                total += REORDER_EXTRA_DELAY_MS
        return total / MILLISECONDS_PER_SECOND

    def schedule(self, sock, destination, data, direction):
        delay = self.plan_packet()
        if delay is None:
            self.dropped[direction] += 1
            return
        received_at = self.clock()
        due = received_at + delay
        self.planned.append((direction, delay * MILLISECONDS_PER_SECOND))
        self.trace.append((received_at, direction, len(data), delay * MILLISECONDS_PER_SECOND))
        with self.condition:
            heapq.heappush(self.queue, (due, next(self.sequence), sock, destination, data, direction))
            self.condition.notify()

    def front_loop(self):
        while self.running:
            try:
                data, client = self.front.recvfrom(RECEIVE_BUFFER_BYTES)
            except socket.timeout:
                continue
            except OSError:
                return
            upstream = self.upstreams.get(client)
            if upstream is None:
                upstream = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                upstream.bind((LOOPBACK, 0))
                upstream.settimeout(SOCKET_POLL_SECONDS)
                self.upstreams[client] = upstream
                self.spawn(self.upstream_loop, upstream, client)
            self.schedule(upstream, self.target, data, "toHost")

    def upstream_loop(self, upstream, client):
        while self.running:
            try:
                data, _ = upstream.recvfrom(RECEIVE_BUFFER_BYTES)
            except socket.timeout:
                continue
            except OSError:
                return
            self.schedule(self.front, client, data, "toClient")

    def send_loop(self):
        while self.running:
            with self.condition:
                if not self.queue:
                    self.condition.wait(SOCKET_POLL_SECONDS)
                    continue
                due = self.queue[0][0]
                wait = due - self.clock()
                if wait > 0:
                    self.condition.wait(min(wait, SOCKET_POLL_SECONDS))
                    continue
                _, _, sock, destination, data, direction = heapq.heappop(self.queue)
            try:
                sock.sendto(data, destination)
                self.forwarded[direction] += 1
            except OSError:
                pass


def is_loopback_peer(address):
    return address in (LOOPBACK, "::1", "::ffff:127.0.0.1")


def is_allowed_host_header(value, port):
    if not value:
        return False
    host, _, given_port = value.partition(":")
    return host in ALLOWED_CONTROL_HOSTS and (not given_port or given_port == str(port))


class ControlServer:
    """Loopback only HTTP control for a DelayProxy. Off unless start_control is called.

    GET /get returns the settings. POST /set with a JSON object of delay_ms, jitter_ms, loss, reorder changes them for the
    packets that follow. A request from a peer that is not loopback, or with another Host header, is refused with 403.
    """

    def __init__(self, proxy, port):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *arguments):
                pass

            def reply(self, status, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def refused(self):
                if not is_loopback_peer(self.client_address[0]):
                    self.reply(403, {"ok": False, "error": "control is loopback only"})
                    return True
                if not is_allowed_host_header(self.headers.get("Host"), owner.port):
                    self.reply(403, {"ok": False, "error": "unexpected Host header"})
                    return True
                return False

            def do_GET(self):
                if self.refused():
                    return
                if self.path != "/get":
                    self.reply(404, {"ok": False, "error": "unknown path"})
                    return
                self.reply(200, {"ok": True, "settings": proxy.get()})

            def do_POST(self):
                if self.refused():
                    return
                if self.path != "/set":
                    self.reply(404, {"ok": False, "error": "unknown path"})
                    return
                length = int(self.headers.get("Content-Length") or 0)
                if length > CONTROL_BODY_LIMIT_BYTES:
                    self.reply(413, {"ok": False, "error": "body too large"})
                    return
                try:
                    values = json.loads(self.rfile.read(length) or b"{}")
                    unknown = [key for key in values if key not in SETTING_NAMES]
                    if unknown or not isinstance(values, dict):
                        raise ValueError("unknown settings %s; known: %s" % (unknown, ", ".join(SETTING_NAMES)))
                    proxy.set(**values)
                except (ValueError, TypeError) as exception:
                    self.reply(400, {"ok": False, "error": str(exception)})
                    return
                self.reply(200, {"ok": True, "settings": proxy.get()})

        self.port = port
        self.server = ThreadingHTTPServer((LOOPBACK, port), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.05), daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)
