"""Mutation check of the PR result tables: each mutation must make unit.test_prtable fail. Usage: python tools/prtable_mutation_check.py"""
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "client")
TARGET = "casualtieslink/reports/prtable.py"
MUTATIONS = [
    ("return (entry.get(\"hostDelta\") or 0) > 0 and (entry.get(\"clientDelta\") or 0) > 0", "return (entry.get(\"hostDelta\") or 0) > 0", "a swing counts as landed on the host alone"),
    ("        if issue.startswith(INVALID_PREFIXES):", "        if False:", "invalid markers ignored"),
    ("        if issue.startswith(FAIL_PREFIX):", "        if False:", "fail markers ignored"),
    ("        low = min(values)", "        low = max(values)", "the highest reading instead of the lowest"),
    ("    reclassify(runs, row)\n", "", "a run with a missed swing keeps counting as valid"),
    ("            if row.get(\"role\") not in ROLES:", "            if False:", "an unlabelled test passes validation"),
    ("    for role in ROLES:\n        block = blocks[role]\n        if block[\"tables\"]:", "    for role in reversed(ROLES):\n        block = blocks[role]\n        if block[\"tables\"]:", "regression block before main"),
    (".replace(\"<\", \"\\\\<\").replace(\">\", \"\\\\>\")", "", "angle brackets not escaped"),
    (".replace(\"|\", \"\\\\|\")", "", "pipes not escaped"),
    ("        lines.append(\"### \" + block[\"heading\"])", "        lines.append(\"## \" + block[\"heading\"])", "wrong heading level"),
    ("    return \"```text\\n\" + render_text(result) + \"```\\n\"", "    return render_text(result)", "no code fence"),
    ("            if expect == \"all\" and counts[1] and counts[0] != counts[1]:", "            if False:", "an unmet all-valid expectation is not a fail"),
    ("    if stats[\"fail\"] or stats[\"unmet\"]:", "    if False:", "a failing block says OK"),
]

uncaught = []
for old, new, label in MUTATIONS:
    full = os.path.join(ROOT, TARGET)
    with open(full, "rb") as handle:
        original_bytes = handle.read()
    original = original_bytes.decode().replace("\r\n", "\n")
    if original.count(old) != 1:
        print("%-55s ANCHOR NOT FOUND (%d)" % (label, original.count(old)))
        uncaught.append(label)
        continue
    with open(full, "wb") as handle:
        handle.write(original.replace(old, new).encode())
    try:
        result = subprocess.run([sys.executable, "-m", "unittest", "unit.test_prtable"], cwd=ROOT, capture_output=True, text=True)
    finally:
        with open(full, "wb") as handle:
            handle.write(original_bytes)
    caught = result.returncode != 0
    print("%-55s %s" % (label, "caught" if caught else "NOT CAUGHT"))
    if not caught:
        uncaught.append(label)
print("uncaught:", uncaught)
sys.exit(1 if uncaught else 0)
