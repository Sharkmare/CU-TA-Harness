import http.client
import json
import socket
import statistics
import time
import unittest

from casualtieslink import udpproxy
from casualtieslink.udpproxy import LOOPBACK, DelayProxy

RECEIVE_TIMEOUT_SECONDS = 3.0
TOLERANCE_SECONDS = 0.04


def free_udp_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind((LOOPBACK, 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def udp_socket(port=0):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LOOPBACK, port))
    sock.settimeout(RECEIVE_TIMEOUT_SECONDS)
    return sock


class Rig:
    def __init__(self, delay_ms, jitter_ms=0.0, seed=1):
        self.host = udp_socket()
        self.proxy = DelayProxy(free_udp_port(), self.host.getsockname()[1], delay_ms, jitter_ms, seed=seed).start()
        self.client = udp_socket()

    def close(self):
        self.proxy.stop()
        self.host.close()
        self.client.close()

    def to_host(self, payload):
        self.client.sendto(payload, (LOOPBACK, self.proxy.listen_port))
        return self.host.recvfrom(65535)


class DelayProxyTests(unittest.TestCase):
    def test_a_packet_to_the_host_arrives_after_the_delay_and_not_much_later(self):
        rig = Rig(delay_ms=100)
        try:
            started = time.monotonic()
            data, _ = rig.to_host(b"hello")
            elapsed = time.monotonic() - started
        finally:
            rig.close()
        self.assertEqual(data, b"hello")
        self.assertGreaterEqual(elapsed, 0.1 - 0.005)
        self.assertLess(elapsed, 0.1 + TOLERANCE_SECONDS)

    def test_a_reply_from_the_host_is_delayed_too_and_reaches_the_same_client(self):
        rig = Rig(delay_ms=80)
        try:
            _, source = rig.to_host(b"ping")
            started = time.monotonic()
            rig.host.sendto(b"pong", source)
            data, _ = rig.client.recvfrom(65535)
            elapsed = time.monotonic() - started
        finally:
            rig.close()
        self.assertEqual(data, b"pong")
        self.assertGreaterEqual(elapsed, 0.08 - 0.005)
        self.assertLess(elapsed, 0.08 + TOLERANCE_SECONDS)

    def test_without_jitter_packets_keep_their_order(self):
        rig = Rig(delay_ms=30)
        try:
            for index in range(40):
                rig.client.sendto(bytes([index]), (LOOPBACK, rig.proxy.listen_port))
            received = [rig.host.recvfrom(65535)[0][0] for _ in range(40)]
        finally:
            rig.close()
        self.assertEqual(received, list(range(40)))

    def test_zero_delay_is_a_plain_pass_through(self):
        rig = Rig(delay_ms=0)
        try:
            started = time.monotonic()
            rig.to_host(b"x")
            elapsed = time.monotonic() - started
        finally:
            rig.close()
        self.assertLess(elapsed, TOLERANCE_SECONDS)

    def test_jitter_spreads_the_delay_inside_its_bounds(self):
        rig = Rig(delay_ms=50, jitter_ms=60, seed=7)
        delays = []
        try:
            for _ in range(25):
                started = time.monotonic()
                rig.to_host(b"j")
                delays.append(time.monotonic() - started)
        finally:
            rig.close()
        self.assertGreaterEqual(min(delays), 0.05 - 0.005)
        self.assertLess(max(delays), 0.11 + TOLERANCE_SECONDS)
        self.assertGreater(max(delays) - min(delays), 0.02)
        self.assertGreater(statistics.mean(delays), 0.06)

    def test_two_clients_get_their_own_replies(self):
        rig = Rig(delay_ms=20)
        second = udp_socket()
        try:
            _, first_source = rig.to_host(b"one")
            second.sendto(b"two", (LOOPBACK, rig.proxy.listen_port))
            _, second_source = rig.host.recvfrom(65535)
            rig.host.sendto(b"for-second", second_source)
            rig.host.sendto(b"for-first", first_source)
            self.assertEqual(second.recvfrom(65535)[0], b"for-second")
            self.assertEqual(rig.client.recvfrom(65535)[0], b"for-first")
        finally:
            second.close()
            rig.close()

    def test_the_forwarded_counters_count_both_directions(self):
        rig = Rig(delay_ms=5)
        try:
            _, source = rig.to_host(b"a")
            rig.host.sendto(b"b", source)
            rig.client.recvfrom(65535)
            counts = dict(rig.proxy.forwarded)
        finally:
            rig.close()
        self.assertEqual(counts, {"toHost": 1, "toClient": 1})

    def test_a_negative_delay_is_refused(self):
        with self.assertRaises(ValueError):
            DelayProxy(1, 2, delay_ms=-1)

    def test_stopping_frees_the_listen_port(self):
        port = free_udp_port()
        DelayProxy(port, 9, 1).start().stop()
        sock = udp_socket(port)
        sock.close()


class LiveControlTests(unittest.TestCase):
    def timed_round_trip(self, rig):
        started = time.monotonic()
        rig.to_host(b"t")
        return time.monotonic() - started

    def test_changing_the_delay_mid_stream_applies_to_the_next_packets(self):
        rig = Rig(delay_ms=20)
        try:
            before = self.timed_round_trip(rig)
            rig.proxy.set(delay_ms=150)
            after = self.timed_round_trip(rig)
            rig.proxy.set(delay_ms=10)
            back = self.timed_round_trip(rig)
        finally:
            rig.close()
        self.assertGreaterEqual(before, 0.015)
        self.assertLess(before, 0.02 + TOLERANCE_SECONDS)
        self.assertGreaterEqual(after, 0.145)
        self.assertLess(after, 0.15 + TOLERANCE_SECONDS)
        self.assertLess(back, 0.01 + TOLERANCE_SECONDS)

    def test_the_connection_survives_a_change_and_replies_still_arrive(self):
        rig = Rig(delay_ms=10)
        try:
            _, source = rig.to_host(b"a")
            rig.proxy.set(delay_ms=60, jitter_ms=20)
            rig.host.sendto(b"b", source)
            self.assertEqual(rig.client.recvfrom(65535)[0], b"b")
        finally:
            rig.close()

    def test_set_changes_only_the_named_values(self):
        proxy = DelayProxy(1, 2, delay_ms=40, jitter_ms=10, seed=5)
        proxy.set(jitter_ms=30)
        settings = proxy.get()
        self.assertEqual((settings["delay_ms"], settings["jitter_ms"], settings["loss"], settings["reorder"]), (40.0, 30.0, 0.0, 0.0))
        self.assertEqual(settings["seed"], 5)

    def test_out_of_range_values_are_refused_and_nothing_changes(self):
        proxy = DelayProxy(1, 2, delay_ms=40)
        for bad in ({"delay_ms": -1}, {"jitter_ms": 99999}, {"loss": 1.5}, {"reorder": -0.1}):
            with self.assertRaises(ValueError, msg=bad):
                proxy.set(**bad)
        self.assertEqual(proxy.get()["delay_ms"], 40.0)

    def test_jitter_bounds_hold_after_a_live_change_in_both_directions(self):
        rig = Rig(delay_ms=0, seed=3)
        delays_up = []
        delays_down = []
        try:
            rig.proxy.set(delay_ms=40, jitter_ms=50)
            _, source = rig.to_host(b"first")
            for _ in range(15):
                started = time.monotonic()
                rig.to_host(b"u")
                delays_up.append(time.monotonic() - started)
                started = time.monotonic()
                rig.host.sendto(b"d", source)
                rig.client.recvfrom(65535)
                delays_down.append(time.monotonic() - started)
        finally:
            rig.close()
        for delays in (delays_up, delays_down):
            self.assertGreaterEqual(min(delays), 0.04 - 0.005)
            self.assertLess(max(delays), 0.09 + TOLERANCE_SECONDS)
            self.assertGreater(max(delays) - min(delays), 0.015)

    def test_the_same_seed_gives_the_same_delay_sequence(self):
        first = DelayProxy(1, 2, delay_ms=10, jitter_ms=80, seed=42, loss=0.2, reorder=0.3)
        second = DelayProxy(1, 2, delay_ms=10, jitter_ms=80, seed=42, loss=0.2, reorder=0.3)
        other = DelayProxy(1, 2, delay_ms=10, jitter_ms=80, seed=43, loss=0.2, reorder=0.3)

        def plan(proxy):
            return [proxy.plan_packet() for _ in range(40)]

        self.assertEqual(plan(first), plan(second))
        self.assertNotEqual(plan(first), plan(other))

    def test_a_proxy_without_a_seed_picks_one_and_reports_it(self):
        proxy = DelayProxy(1, 2)
        self.assertGreater(proxy.get()["seed"], 0)

    def test_full_loss_drops_everything_and_none_drops_nothing(self):
        rig = Rig(delay_ms=0)
        try:
            rig.proxy.set(loss=1.0)
            rig.client.sendto(b"x", (LOOPBACK, rig.proxy.listen_port))
            rig.host.settimeout(0.3)
            with self.assertRaises(socket.timeout):
                rig.host.recvfrom(65535)
            rig.proxy.set(loss=0.0)
            rig.host.settimeout(3.0)
            self.assertEqual(rig.to_host(b"y")[0], b"y")
            dropped = dict(rig.proxy.dropped)
        finally:
            rig.close()
        self.assertEqual(dropped["toHost"], 1)

    def test_reorder_makes_a_share_of_packets_arrive_late(self):
        rig = Rig(delay_ms=5, seed=11)
        try:
            rig.proxy.set(reorder=0.5)
            for index in range(60):
                rig.client.sendto(bytes([index]), (LOOPBACK, rig.proxy.listen_port))
                time.sleep(0.004)
            received = [rig.host.recvfrom(65535)[0][0] for _ in range(60)]
        finally:
            rig.close()
        self.assertEqual(sorted(received), list(range(60)))
        self.assertNotEqual(received, list(range(60)))

    def test_lowering_the_delay_can_let_a_later_packet_overtake_as_documented(self):
        rig = Rig(delay_ms=200)
        try:
            rig.client.sendto(b"slow", (LOOPBACK, rig.proxy.listen_port))
            time.sleep(0.02)
            rig.proxy.set(delay_ms=0)
            rig.client.sendto(b"fast", (LOOPBACK, rig.proxy.listen_port))
            first = rig.host.recvfrom(65535)[0]
            second = rig.host.recvfrom(65535)[0]
        finally:
            rig.close()
        self.assertEqual((first, second), (b"fast", b"slow"))


class ObservedDelayTests(unittest.TestCase):
    def test_the_proxy_reports_the_delays_it_planned_since_a_mark(self):
        rig = Rig(delay_ms=30)
        try:
            rig.to_host(b"a")
            mark = rig.proxy.mark()
            rig.proxy.set(delay_ms=120)
            rig.to_host(b"b")
            rig.to_host(b"c")
            stats = rig.proxy.delay_stats(mark)
            everything = rig.proxy.delay_stats()
        finally:
            rig.close()
        self.assertEqual(stats["toHost"]["packets"], 2)
        self.assertEqual((stats["toHost"]["minMs"], stats["toHost"]["maxMs"]), (120.0, 120.0))
        self.assertEqual(everything["toHost"]["packets"], 3)
        self.assertEqual(everything["toHost"]["minMs"], 30.0)

    def test_no_packets_give_no_numbers(self):
        proxy = DelayProxy(1, 2)
        self.assertEqual(proxy.delay_stats()["toClient"], {"packets": 0, "minMs": None, "meanMs": None, "maxMs": None})

    def test_jittered_delays_stay_inside_the_bounds_in_the_stats(self):
        proxy = DelayProxy(1, 2, delay_ms=100, jitter_ms=60, seed=5)
        for _ in range(50):
            proxy.schedule(None, None, b"x", "toHost")
        stats = proxy.delay_stats()["toHost"]
        self.assertGreaterEqual(stats["minMs"], 100.0)
        self.assertLessEqual(stats["maxMs"], 160.0)
        self.assertEqual(stats["packets"], 50)


class ControlServerTests(unittest.TestCase):
    def setUp(self):
        self.proxy = DelayProxy(free_udp_port(), free_udp_port(), delay_ms=25, seed=9).start()
        self.control = self.proxy.start_control(0)

    def tearDown(self):
        self.proxy.stop()

    def request(self, method, path, body=None, host=None):
        connection = http.client.HTTPConnection(LOOPBACK, self.control.port, timeout=3)
        connection.putrequest(method, path, skip_host=bool(host), skip_accept_encoding=True)
        if host:
            connection.putheader("Host", host)
        payload = json.dumps(body).encode() if body is not None else b""
        connection.putheader("Content-Length", str(len(payload)))
        connection.endheaders(payload)
        response = connection.getresponse()
        data = json.loads(response.read() or b"{}")
        connection.close()
        return response.status, data

    def test_control_is_off_until_started_and_listens_on_loopback_only(self):
        self.assertEqual(self.control.server.server_address[0], LOOPBACK)
        self.assertIsNone(DelayProxy(free_udp_port(), 9).control)

    def test_get_returns_the_settings_and_the_seed(self):
        status, data = self.request("GET", "/get")
        self.assertEqual(status, 200)
        self.assertEqual((data["settings"]["delay_ms"], data["settings"]["seed"]), (25.0, 9))

    def test_set_changes_the_proxy_for_following_packets(self):
        status, _ = self.request("POST", "/set", {"delay_ms": 90, "jitter_ms": 15})
        self.assertEqual(status, 200)
        self.assertEqual(self.proxy.get()["delay_ms"], 90.0)
        self.assertEqual(self.proxy.get()["jitter_ms"], 15.0)

    def test_unknown_settings_and_bad_values_are_400_and_change_nothing(self):
        self.assertEqual(self.request("POST", "/set", {"speed": 1})[0], 400)
        self.assertEqual(self.request("POST", "/set", {"delay_ms": -5})[0], 400)
        self.assertEqual(self.request("POST", "/set", {"loss": 3})[0], 400)
        self.assertEqual(self.proxy.get()["delay_ms"], 25.0)

    def test_another_host_header_is_refused(self):
        status, _ = self.request("GET", "/get", host="evil.example:%d" % self.control.port)
        self.assertEqual(status, 403)
        self.assertEqual(self.request("POST", "/set", {"delay_ms": 1}, host="evil.example")[0], 403)
        self.assertEqual(self.proxy.get()["delay_ms"], 25.0)

    def test_only_loopback_peers_are_allowed(self):
        self.assertTrue(udpproxy.is_loopback_peer("127.0.0.1"))
        self.assertFalse(udpproxy.is_loopback_peer("192.168.1.20"))
        self.assertFalse(udpproxy.is_loopback_peer("10.20.0.6"))
        self.assertFalse(udpproxy.is_loopback_peer("0.0.0.0"))

    def test_unknown_paths_are_404(self):
        self.assertEqual(self.request("GET", "/nope")[0], 404)
        self.assertEqual(self.request("POST", "/get", {})[0], 404)

    def test_stopping_the_proxy_stops_the_control_port(self):
        port = self.control.port
        self.proxy.stop()
        with self.assertRaises(OSError):
            socket.create_connection((LOOPBACK, port), timeout=0.5)
        self.proxy = DelayProxy(free_udp_port(), 9)


if __name__ == "__main__":
    unittest.main()
