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

    def test_the_trace_lists_every_forwarded_packet_with_its_receive_moment_size_and_delay_since_the_mark(self):
        clock = iter([10.0, 10.5, 11.0])
        proxy = DelayProxy(1, 2, delay_ms=40, clock=lambda: next(clock))
        proxy.schedule(None, None, b"abc", "toHost")
        mark = proxy.trace_mark()
        proxy.schedule(None, None, b"de", "toClient")
        proxy.schedule(None, None, b"fghi", "toHost")
        self.assertEqual(proxy.trace_since(mark), [(10.5, "toClient", 2, 40.0, 10.54), (11.0, "toHost", 4, 40.0, 11.04)])
        self.assertEqual(len(proxy.trace_since()), 3)

    def test_a_dropped_packet_is_not_traced(self):
        proxy = DelayProxy(1, 2, loss=1.0, seed=3)
        proxy.schedule(None, None, b"x", "toHost")
        self.assertEqual(proxy.trace_since(), [])

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


class StallClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def stall_proxy(clock, seed=7, **settings):
    proxy = DelayProxy(1, 2, clock=clock, seed=seed, **settings)
    with proxy.condition:
        proxy.configure_stalls(clock.now)
    return proxy


def send(proxy, clock, moment, label, direction="toHost"):
    clock.now = moment
    proxy.schedule(None, None, label, direction)


def advance(proxy, clock, moment):
    clock.now = moment
    with proxy.condition:
        proxy.advance_stalls(moment)


def dues(proxy):
    return {entry[4]: entry[0] for entry in proxy.queue}


def consecutive_gaps(proxy, labels):
    table = dues(proxy)
    return [round(table[later] - table[earlier], 6) for earlier, later in zip(labels, labels[1:])]


SWINGS = [(0.9, b"a"), (1.1, b"b"), (1.3, b"c"), (1.5, b"d")]


class StallAndFlushTests(unittest.TestCase):
    def run_swings(self, **settings):
        clock = StallClock()
        proxy = stall_proxy(clock, **settings)
        for moment, label in SWINGS:
            send(proxy, clock, moment, label)
        advance(proxy, clock, 3.0)
        return proxy

    def test_a_stall_of_0_3_with_swings_0_2_apart_releases_packets_under_0_124_s_apart(self):
        proxy = self.run_swings(stall_interval_ms=1000, stall_duration_ms=300)
        gaps = consecutive_gaps(proxy, [b"a", b"b", b"c", b"d"])
        self.assertLess(min(gaps), 0.124)
        self.assertEqual(round(dues(proxy)[b"b"], 6), 1.3)

    def test_without_a_stall_the_same_swings_stay_0_2_s_apart(self):
        proxy = self.run_swings()
        self.assertEqual(consecutive_gaps(proxy, [b"a", b"b", b"c", b"d"]), [0.2, 0.2, 0.2])
        self.assertEqual(proxy.stall_trace, [])

    def test_every_held_packet_is_released_at_the_end_in_arrival_order_and_none_is_lost(self):
        clock = StallClock()
        proxy = stall_proxy(clock, stall_interval_ms=1000, stall_duration_ms=300)
        labels = [bytes([65 + index]) for index in range(8)]
        for index, label in enumerate(labels):
            send(proxy, clock, 1.0 + 0.04 * index, label)
        advance(proxy, clock, 3.0)
        self.assertEqual(len(proxy.queue), 8)
        self.assertEqual(proxy.stall_trace[0]["held"], 8)
        released = [dues(proxy)[label] for label in labels]
        self.assertEqual(released, sorted(released))
        self.assertEqual(proxy.dropped, {"toHost": 0, "toClient": 0})

    def test_the_stall_never_reorders_packets_over_many_random_arrivals(self):
        import random
        generator = random.Random(3)
        clock = StallClock()
        proxy = stall_proxy(clock, delay_ms=50, stall_interval_ms=400, stall_interval_spread_ms=200, stall_duration_ms=250, stall_duration_spread_ms=100, seed=11)
        moment = 0.0
        labels = []
        for index in range(300):
            moment += generator.uniform(0.005, 0.12)
            label = index.to_bytes(2, "big")
            labels.append(label)
            send(proxy, clock, moment, label)
        advance(proxy, clock, moment + 5.0)
        table = dues(proxy)
        self.assertEqual(len(table), 300)
        ordered = [table[label] for label in labels]
        self.assertEqual(ordered, sorted(ordered))
        self.assertGreater(len(proxy.stall_trace), 3)

    def test_the_trace_records_start_end_packets_held_and_the_release_times_of_each_stall(self):
        proxy = self.run_swings(stall_interval_ms=1000, stall_duration_ms=300)
        first = proxy.stall_trace[0]
        self.assertEqual((first["direction"], round(first["start"], 6), round(first["end"], 6), first["held"]), ("toHost", 1.0, 1.3, 1))
        self.assertEqual((round(first["releaseFirst"], 6), round(first["releaseLast"], 6), first["gapSeconds"]), (1.3, 1.3, 0.0))
        self.assertEqual(proxy.stall_trace_since(proxy.stall_trace_mark()), [])
        self.assertEqual(len(proxy.stall_trace_since(0)), len(proxy.stall_trace))

    def test_the_release_gap_spaces_the_flushed_packets(self):
        clock = StallClock()
        proxy = stall_proxy(clock, stall_interval_ms=1000, stall_duration_ms=300, stall_gap_ms=10)
        for moment, label in ((1.1, b"x"), (1.15, b"y"), (1.2, b"z")):
            send(proxy, clock, moment, label)
        advance(proxy, clock, 2.0)
        self.assertEqual([round(dues(proxy)[label], 6) for label in (b"x", b"y", b"z")], [1.3, 1.31, 1.32])

    def test_packets_after_the_stall_resume_the_normal_delay_and_stay_behind_the_flushed_ones(self):
        clock = StallClock()
        proxy = stall_proxy(clock, delay_ms=100, stall_interval_ms=1000, stall_duration_ms=300, stall_gap_ms=20)
        for moment, label in ((1.1, b"x"), (1.15, b"y"), (1.4, b"z")):
            send(proxy, clock, moment, label)
        advance(proxy, clock, 3.0)
        self.assertEqual(round(dues(proxy)[b"z"], 6), 1.5)
        self.assertLessEqual(dues(proxy)[b"y"], dues(proxy)[b"z"])

    def test_a_flush_waits_for_a_packet_queued_before_the_stall_that_is_still_in_flight(self):
        clock = StallClock()
        proxy = stall_proxy(clock, delay_ms=500, stall_interval_ms=1000, stall_duration_ms=300)
        send(proxy, clock, 0.95, b"a")
        send(proxy, clock, 1.1, b"b")
        advance(proxy, clock, 3.0)
        self.assertGreaterEqual(dues(proxy)[b"b"], dues(proxy)[b"a"])

    def test_a_packet_arriving_after_the_stall_is_never_due_before_the_last_flushed_one(self):
        clock = StallClock()
        proxy = stall_proxy(clock, stall_interval_ms=1000, stall_duration_ms=300, stall_gap_ms=100)
        for moment, label in ((1.05, b"x"), (1.1, b"y"), (1.15, b"w"), (1.35, b"z")):
            send(proxy, clock, moment, label)
        advance(proxy, clock, 3.0)
        table = dues(proxy)
        self.assertEqual([round(table[label], 6) for label in (b"x", b"y", b"w")], [1.3, 1.4, 1.5])
        self.assertGreaterEqual(table[b"z"], table[b"w"])

    def test_the_next_stall_starts_an_interval_after_the_last_one_ended(self):
        clock = StallClock()
        proxy = stall_proxy(clock, stall_interval_ms=1000, stall_duration_ms=300)
        advance(proxy, clock, 3.0)
        starts = [round(entry["start"], 6) for entry in proxy.stall_trace]
        self.assertEqual(starts, [1.0, 2.3])

    def test_only_the_client_to_host_direction_stalls_unless_the_other_one_is_asked_for(self):
        clock = StallClock()
        proxy = stall_proxy(clock, stall_interval_ms=1000, stall_duration_ms=300)
        send(proxy, clock, 1.1, b"h", "toHost")
        send(proxy, clock, 1.1, b"c", "toClient")
        self.assertEqual(round(dues(proxy)[b"c"], 6), 1.1)
        self.assertNotIn(b"h", dues(proxy))
        both_clock = StallClock()
        both = stall_proxy(both_clock, stall_interval_ms=1000, stall_duration_ms=300, stall_to_client=1)
        send(both, both_clock, 1.1, b"c", "toClient")
        self.assertNotIn(b"c", dues(both))

    def test_the_same_seed_gives_the_same_stalls_and_the_stall_does_not_change_the_jitter_sequence(self):
        def stalls(seed):
            clock = StallClock()
            proxy = stall_proxy(clock, seed=seed, stall_interval_ms=500, stall_interval_spread_ms=300, stall_duration_ms=200, stall_duration_spread_ms=100)
            advance(proxy, clock, 20.0)
            return [(round(entry["start"], 6), round(entry["end"], 6)) for entry in proxy.stall_trace]

        self.assertEqual(stalls(5), stalls(5))
        self.assertNotEqual(stalls(5), stalls(6))
        clock = StallClock()
        with_stall = stall_proxy(clock, delay_ms=100, jitter_ms=60, seed=5, stall_interval_ms=500, stall_duration_ms=200)
        advance(with_stall, clock, 10.0)
        without = DelayProxy(1, 2, delay_ms=100, jitter_ms=60, seed=5)
        self.assertGreater(len(with_stall.stall_trace), 5)
        self.assertEqual([with_stall.plan_packet() for _ in range(20)], [without.plan_packet() for _ in range(20)])

    def test_stall_values_are_validated_at_the_boundary(self):
        for settings in ({"stall_interval_ms": -1}, {"stall_interval_ms": 100, "stall_interval_spread_ms": 200}, {"stall_duration_ms": 100, "stall_duration_spread_ms": 101},
                         {"stall_interval_ms": 1e9}, {"stall_gap_ms": -5}, {"stall_to_client": 2}):
            with self.subTest(settings=settings):
                with self.assertRaises(ValueError):
                    DelayProxy(1, 2, **settings)
        proxy = DelayProxy(1, 2)
        with self.assertRaises(ValueError):
            proxy.set(stall_interval_ms=100, stall_interval_spread_ms=200)
        with self.assertRaises(ValueError):
            proxy.set(stall_nonsense=1)
        self.assertEqual(proxy.get()["stall_interval_ms"], 0.0)

    def test_turning_the_stall_off_releases_what_is_held_at_once(self):
        clock = StallClock()
        proxy = stall_proxy(clock, stall_interval_ms=1000, stall_duration_ms=300)
        send(proxy, clock, 1.1, b"x")
        clock.now = 1.15
        proxy.set(stall_interval_ms=0.0)
        self.assertEqual(round(dues(proxy)[b"x"], 6), 1.15)
        self.assertEqual(proxy.get()["stall_interval_ms"], 0.0)
        self.assertEqual(proxy.stall_trace[0]["held"], 1)

    def test_the_settings_report_the_stall_fields(self):
        settings = DelayProxy(1, 2, stall_interval_ms=500, stall_duration_ms=100, stall_gap_ms=3, stall_to_client=1).get()
        self.assertEqual((settings["stall_interval_ms"], settings["stall_duration_ms"], settings["stall_gap_ms"], settings["stall_to_client"]), (500.0, 100.0, 3.0, 1))

    def test_a_live_stall_holds_a_packet_until_the_stall_ends_and_then_delivers_it(self):
        host = udp_socket()
        proxy = DelayProxy(free_udp_port(), host.getsockname()[1], 0, 0, seed=1, stall_interval_ms=50, stall_duration_ms=300).start()
        client = udp_socket()
        try:
            began = time.monotonic()
            time.sleep(0.12)
            client.sendto(b"held", (LOOPBACK, proxy.listen_port))
            host.recvfrom(4096)
            elapsed = time.monotonic() - began
        finally:
            proxy.stop()
            host.close()
            client.close()
        self.assertGreaterEqual(elapsed, 0.30)
        self.assertLess(elapsed, 1.5)
        self.assertEqual(proxy.stall_trace[0]["held"], 1)


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
