"""Lists the engine-called entry points a source range adds or changes: Harmony patches, Unity message methods, network receivers, coroutines and timers.

Usage: python tools/hook_diff.py --repo PATH --from 055da67 --to e9eb3ce [--json out.json]

The scan is textual and works on the git diff (added lines plus the enclosing file), so it finds what a commit range
introduces without running the game. The runtime inventory (plugin-hookprofiler, Control.Inventory) is the ground truth;
this gives the list of suspects to look for in it, and the per file counts to size the audit.
"""
import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict

PATCH_ATTRIBUTE = re.compile(r"\[HarmonyPatch\(([^\]]*)\)\]")
UNITY_MESSAGE = re.compile(r"\b(?:void|IEnumerator)\s+(Update|FixedUpdate|LateUpdate|OnGUI|OnCollisionEnter2D|OnCollisionStay2D|OnCollisionExit2D|OnTriggerEnter2D|OnTriggerStay2D|OnTriggerExit2D)\s*\(")
RECEIVER_ATTRIBUTE = re.compile(r"\[(Client|Server)Receiver\(")
COROUTINE_START = re.compile(r"\bStartCoroutine\s*\(")
TIMER_USE = re.compile(r"\b(InvokeRepeating|new\s+System\.Threading\.Timer|new\s+Timer\s*\(|System\.Timers|Task\.Run|new\s+Thread\s*\()")
PATCH_METHOD = re.compile(r"\bstatic\s+[\w<>\[\],\s]+?\s+(Prefix|Postfix|Transpiler|Finalizer)\s*\(")
KINDS = (("harmony-attribute", PATCH_ATTRIBUTE), ("patch-method", PATCH_METHOD), ("unity-message", UNITY_MESSAGE), ("receiver", RECEIVER_ATTRIBUTE),
         ("coroutine-start", COROUTINE_START), ("timer-or-thread", TIMER_USE))


def run_git(repo, *arguments):
    return subprocess.run(["git", "-C", repo] + list(arguments), capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def hits(text):
    found = defaultdict(list)
    for line in text.splitlines():
        for kind, pattern in KINDS:
            if pattern.search(line):
                found[kind].append(line.strip()[:160])
    return found


def scan(repo, start, end, pathspec="*.cs"):
    files = [line for line in run_git(repo, "diff", "--name-only", start, end, "--", pathspec).splitlines() if line]
    rows = []
    for path in files:
        before = hits(run_git(repo, "show", "%s:%s" % (start, path)))
        after = hits(run_git(repo, "show", "%s:%s" % (end, path)))
        added = {kind: [line for line in after.get(kind, []) if line not in before.get(kind, [])] for kind, _ in KINDS}
        removed = {kind: [line for line in before.get(kind, []) if line not in after.get(kind, [])] for kind, _ in KINDS}
        if any(added.values()) or any(removed.values()):
            rows.append({"file": path, "added": {k: v for k, v in added.items() if v}, "removed": {k: v for k, v in removed.items() if v}})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--json")
    arguments = parser.parse_args(argv)
    rows = scan(arguments.repo, arguments.start, arguments.end)
    totals = defaultdict(int)
    for row in rows:
        for kind, lines in row["added"].items():
            totals[kind] += len(lines)
    if arguments.json:
        with open(arguments.json, "w", encoding="utf-8") as handle:
            json.dump({"from": arguments.start, "to": arguments.end, "totalsAdded": totals, "files": rows}, handle, indent=1)
    for row in rows:
        print(row["file"], {kind: len(lines) for kind, lines in row["added"].items()}, "removed", {kind: len(lines) for kind, lines in row["removed"].items()})
    print("added totals", dict(totals))
    return 0


if __name__ == "__main__":
    sys.exit(main())
