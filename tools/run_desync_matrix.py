import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUN_TESTS = os.path.join(os.path.dirname(HERE), "client", "run_tests.py")
PER_RUN_TIMEOUT_SECONDS = 300
DELAY_JITTER_PAIRS = ((100, 60), (250, 100))


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description="Run one desync test over builds, delays and repetitions, keeping each run's output.")
    parser.add_argument("--builds", nargs="+", required=True)
    parser.add_argument("--match", required=True, help="test name fragment, for example hold_mining")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--pairs", nargs="+", default=["%d:%d" % pair for pair in DELAY_JITTER_PAIRS], metavar="DELAY:JITTER")
    parser.add_argument("--output", required=True, help="directory for the per run output files")
    return parser.parse_args(argv)


def run_one(build, delay, jitter, match, output_path):
    command = [sys.executable, RUN_TESTS, "--pair", "--only", "desync", "--together", build,
               "--delay-ms", str(delay), "--jitter-ms", str(jitter), "--match", match, "--budget-seconds", str(PER_RUN_TIMEOUT_SECONDS - 20)]
    with open(output_path, "w", encoding="utf-8") as handle:
        try:
            completed = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, timeout=PER_RUN_TIMEOUT_SECONDS)
            return completed.returncode
        except subprocess.TimeoutExpired:
            return -1


def main(argv=None):
    arguments = parse_arguments(argv)
    os.makedirs(arguments.output, exist_ok=True)
    for build in arguments.builds:
        for pair in arguments.pairs:
            delay, _, jitter = pair.partition(":")
            for repetition in range(1, arguments.repetitions + 1):
                path = os.path.join(arguments.output, "%s_d%s_j%s_r%d.txt" % (build, delay, jitter, repetition))
                started = time.time()
                code = run_one(build, delay, jitter or "0", arguments.match, path)
                print("%s delay %s jitter %s run %d: exit %s in %.0fs -> %s" % (build, delay, jitter, repetition, code, time.time() - started, path), flush=True)


if __name__ == "__main__":
    main()
