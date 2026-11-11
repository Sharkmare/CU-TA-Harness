import heapq
import itertools
import random
import socket
import threading
import time

LOOPBACK = "127.0.0.1"
RECEIVE_BUFFER_BYTES = 65535
SOCKET_POLL_SECONDS = 0.2
MILLISECONDS_PER_SECOND = 1000.0


class DelayProxy:
    def __init__(self, listen_port, target_port, delay_ms=0.0, jitter_ms=0.0, target_host=LOOPBACK, seed=None, clock=time.monotonic):
        if delay_ms < 0 or jitter_ms < 0:
            raise ValueError("delay and jitter must not be negative")
        self.listen_port = listen_port
        self.target = (target_host, target_port)
        self.delay_seconds = delay_ms / MILLISECONDS_PER_SECOND
        self.jitter_seconds = jitter_ms / MILLISECONDS_PER_SECOND
        self.random = random.Random(seed)
        self.clock = clock
        self.front = None
        self.upstreams = {}
        self.queue = []
        self.sequence = itertools.count()
        self.condition = threading.Condition()
        self.running = False
        self.threads = []
        self.forwarded = {"toHost": 0, "toClient": 0}

    def start(self):
        self.front = self.bound_socket(self.listen_port)
        self.running = True
        self.spawn(self.front_loop)
        self.spawn(self.send_loop)
        return self

    def stop(self):
        self.running = False
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

    def one_way_delay(self):
        return self.delay_seconds + (self.random.uniform(0.0, self.jitter_seconds) if self.jitter_seconds else 0.0)

    def schedule(self, sock, destination, data, direction):
        due = self.clock() + self.one_way_delay()
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
