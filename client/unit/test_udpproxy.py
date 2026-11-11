import socket
import statistics
import time
import unittest

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


if __name__ == "__main__":
    unittest.main()
