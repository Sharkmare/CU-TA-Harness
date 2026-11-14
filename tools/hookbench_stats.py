"""Comparison rules of the hook benchmark: noise floor from repeated identical runs, and a verdict on whether two builds differ.

A build is measured by several runs of the same scripted scene; every run gives one number per metric (mean frame time,
p95, p99, process CPU share, hook time per frame). The noise floor is the spread of those numbers between runs of the
SAME build. Two builds differ on a metric only when the gap between their run means is larger than the noise allows
(NOISE_MULTIPLE standard errors of the difference) and larger than MINIMUM_RELATIVE_GAP of the baseline mean.
"""
import math

NOISE_MULTIPLE = 3.0
MINIMUM_RELATIVE_GAP = 0.02
MINIMUM_RUNS = 3

METRICS = (
    ("frameMeanMs", lambda report: report["frames"]["meanMs"]),
    ("frameP95Ms", lambda report: report["frames"]["p95Ms"]),
    ("frameP99Ms", lambda report: report["frames"]["p99Ms"]),
    ("cpuShareOfOneCore", lambda report: report["processCpuShareOfOneCore"]),
    ("hookMsPerFrameMean", lambda report: report["hookSecondsPerFrame"]["meanMs"]),
)


def mean(values):
    return sum(values) / len(values)


def sample_deviation(values):
    if len(values) < 2:
        return 0.0
    centre = mean(values)
    return math.sqrt(sum((value - centre) ** 2 for value in values) / (len(values) - 1))


def describe(values):
    """Run count, mean, sample deviation and the relative noise (deviation over mean) of one metric across runs."""
    centre = mean(values)
    deviation = sample_deviation(values)
    return {"runs": len(values), "mean": centre, "deviation": deviation, "relativeNoise": deviation / centre if centre else 0.0}


def compare(baseline_values, candidate_values, multiple=NOISE_MULTIPLE, minimum_relative_gap=MINIMUM_RELATIVE_GAP):
    """Verdict for one metric. 'differs' needs enough runs on both sides, a gap beyond the noise and beyond the relative minimum."""
    if len(baseline_values) < MINIMUM_RUNS or len(candidate_values) < MINIMUM_RUNS:
        return {"verdict": "too few runs", "gap": None}
    base, cand = describe(baseline_values), describe(candidate_values)
    gap = cand["mean"] - base["mean"]
    standard_error = math.sqrt(base["deviation"] ** 2 / base["runs"] + cand["deviation"] ** 2 / cand["runs"])
    relative = gap / base["mean"] if base["mean"] else 0.0
    beyond_noise = abs(gap) > multiple * standard_error
    beyond_minimum = abs(relative) > minimum_relative_gap
    verdict = "no difference" if not (beyond_noise and beyond_minimum) else ("candidate slower" if gap > 0 else "candidate faster")
    return {"verdict": verdict, "gap": gap, "relativeGap": relative, "standardError": standard_error, "baseline": base, "candidate": cand}


def compare_reports(baseline_reports, candidate_reports):
    return {name: compare([extract(report) for report in baseline_reports], [extract(report) for report in candidate_reports]) for name, extract in METRICS}


def noise_floor(reports):
    """Per metric spread across repeated runs of one build."""
    return {name: describe([extract(report) for report in reports]) for name, extract in METRICS}


def hook_table(reports):
    """Per hook across runs: mean of calls and total ms per run, and the per run spread of total ms, sorted by mean total ms."""
    per_hook = {}
    for report in reports:
        for row in report["hooks"]:
            per_hook.setdefault(row["name"], []).append(row)
    table = []
    for name, rows in per_hook.items():
        totals = [row["totalMs"] for row in rows]
        table.append({
            "name": name, "kinds": rows[0]["kinds"], "targets": rows[0]["targets"], "runsSeen": len(rows),
            "meanCalls": mean([row["calls"] for row in rows]), "meanTotalMs": mean(totals), "totalMsDeviation": sample_deviation(totals),
            "meanUs": mean([row["meanUs"] for row in rows]), "netMeanUs": mean([row["netMeanUs"] for row in rows]),
            "p95Us": max(row["p95Us"] for row in rows), "p99Us": max(row["p99Us"] for row in rows), "maxUs": max(row["maxUs"] for row in rows),
            "callsPerFrame": mean([row["callsPerFrame"] for row in rows]), "callsPerFixedTick": mean([row["callsPerFixedTick"] for row in rows]),
        })
    return sorted(table, key=lambda row: -row["meanTotalMs"])
