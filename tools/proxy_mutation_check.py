"""Mutation check of the proxy stall-and-flush mode: each mutation must make unit.test_udpproxy fail. Usage: python tools/proxy_mutation_check.py"""
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "client")
TARGET = "casualtieslink/udpproxy.py"
MUTATIONS = [
    ("            when = base + position * gap\n", "            when = base + (len(state.held) - 1 - position) * gap\n", "held packets released in reverse order"),
    ("        base = max(state.end, state.last_due)\n", "        base = state.end\n", "a flush can overtake packets queued before the stall"),
    ("            due = max(due, state.flush_floor)\n", "            pass\n", "later packets can overtake the flushed ones"),
    ("            if state.end is not None:\n                state.held.append(", "            if False:\n                state.held.append(", "nothing is held during a stall"),
    ("            heapq.heappush(self.queue, (when, next(self.sequence), sock, destination, data, direction))\n            _, name, size", "            _, name, size", "held packets are never released"),
    ("    if interval_spread_ms > interval_ms:\n", "    if False:\n", "an interval spread above the mean is accepted"),
    ("        self.stall_random = random.Random(self.seed ^ STALL_SEED_MASK)", "        self.stall_random = self.random", "stalls share the jitter generator"),
    ("        return self.stall_active() and (direction == TO_HOST or bool(self.stall[\"stall_to_client\"]))", "        return self.stall_active()", "the host to client direction stalls without being asked"),
    ("                state.next_start = state.end_of_last + self.draw_seconds(", "                state.next_start = state.started_at_never + self.draw_seconds(", "the next stall is not scheduled after the end"),
]

uncaught = []
for old, new, label in MUTATIONS:
    full = os.path.join(ROOT, TARGET)
    with open(full, "rb") as handle:
        original = handle.read().decode()
    if original.count(old) != 1:
        print("%-60s ANCHOR NOT FOUND (%d)" % (label, original.count(old)))
        uncaught.append(label)
        continue
    with open(full, "wb") as handle:
        handle.write(original.replace(old, new).encode())
    try:
        result = subprocess.run([sys.executable, "-m", "unittest", "unit.test_udpproxy.StallAndFlushTests"], cwd=ROOT, capture_output=True, text=True, timeout=120)
        caught = result.returncode != 0
    except subprocess.TimeoutExpired:
        caught = True
    finally:
        with open(full, "wb") as handle:
            handle.write(original.encode())
    print("%-60s %s" % (label, "caught" if caught else "NOT CAUGHT"))
    if not caught:
        uncaught.append(label)
print("uncaught:", uncaught)
sys.exit(1 if uncaught else 0)
