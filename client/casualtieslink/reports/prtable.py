"""Compact result tables for one PR or topic, computed from the harness report JSONs and driven by a profile file.

A profile (client/profiles/*.json) names the report files, the builds to compare, the rows and the columns, and gives every test a role: MAIN (what the PR changes) or
REGRESSION (existing behaviour that must still hold). The numbers are read from the reports, never typed. The output has a MAIN block and a REGRESSION block, each with its
own tables and its own verdict line. Renderings from the same data: aligned text for a terminal or chat, the same text in a fenced code block, and GitHub-flavoured Markdown for a PR body.
"""
import glob
import hashlib
import json
import os
import re
import statistics

MISSING_CELL = "-"
INVALID_PREFIXES = ("INVALID", "NOT COUNTED")
CONFOUNDED_PREFIX = "CONFOUNDED"
GONE_SUFFIX = "->gone"
DEFAULT_REASONS = (
    (r"position preflight failed", "position preflight failed"),
    (r"could not be brought into the .* band", "client out of band"),
    (r"limb 1 came within", "limb gate not passed"),
    (r"first swing changed nothing", "first swing hit nothing"),
    (r"client seat did not verify", "client seat unverified"),
    (r"no swing recorded", "no swing recorded"),
    (r"does not face the corpse", "client not facing corpse"),
)
REQUIRED_PROFILE_KEYS = ("name", "topic", "sources", "tables")
ROLES = ("MAIN", "REGRESSION")
ROLE_HEADINGS = {"MAIN": "Main tests", "REGRESSION": "Regression tests"}
FAIL_PREFIX = "FAIL"


class ProfileError(ValueError):
    pass


def load_profile(path):
    with open(path, encoding="utf-8") as handle:
        profile = json.load(handle)
    for key in REQUIRED_PROFILE_KEYS:
        if key not in profile:
            raise ProfileError("profile %s has no %r" % (path, key))
    validate_profile(profile, path)
    return profile


def validate_profile(profile, where="profile"):
    for table in profile["tables"]:
        if table.get("kind") not in ("pair_rows", "metric_rows"):
            raise ProfileError("table %r has the unknown kind %r" % (table.get("title"), table.get("kind")))
        if not table.get("builds"):
            raise ProfileError("table %r lists no builds" % table.get("title"))
        for row in table.get("rows") or []:
            if row.get("role") not in ROLES:
                raise ProfileError("test %r in %s has no role: give it one of %s" % (row.get("label"), where, " or ".join(ROLES)))


def load_report(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data["_path"] = path
    return data


def expand_sources(patterns, root):
    found = []
    for pattern in patterns:
        found.extend(sorted(glob.glob(os.path.join(root, pattern))))
    seen = []
    for path in found:
        if path not in seen:
            seen.append(path)
    return seen


def short_reason(text, extra_reasons=()):
    for pattern, phrase in tuple(extra_reasons) + DEFAULT_REASONS:
        if re.search(pattern, text):
            return phrase
    stripped = re.sub(r"^[A-Z ]+:\s*", "", text)
    return " ".join(stripped.split()[:5])


def run_status(report, profile):
    """valid, invalid, confounded or excluded, with a short reason."""
    issues = report.get("issues") or []
    extra = [tuple(pair) for pair in profile.get("reasons", [])]
    for issue in issues:
        if issue.startswith(INVALID_PREFIXES):
            return "invalid", short_reason(issue, extra)
    for issue in issues:
        if issue.startswith(FAIL_PREFIX):
            return "fail", short_reason(issue, extra)
    for issue in issues:
        if issue.startswith(CONFOUNDED_PREFIX):
            return "confounded", short_reason(issue, extra)
    prediction = (report.get("target") or {}).get("prediction") or {}
    if str(prediction.get("verdict", "")).startswith("confounded"):
        superseded = [re.compile(pattern) for pattern in profile.get("superseded_confounders", [])]
        remaining = [item for item in prediction.get("confoundedBy", []) if not any(rule.search(item) for rule in superseded)]
        if remaining:
            return "confounded", short_reason(remaining[0], extra)
    rate_limit = profile.get("params", {}).get("real_rate_median_max")
    median = ((report.get("target") or {}).get("swingRate") or {}).get("medianSeconds")
    if rate_limit is not None and median is not None and median > rate_limit:
        return "excluded", "slow swings %.2f s" % median
    return "valid", ""


def landed(entry):
    return (entry.get("hostDelta") or 0) > 0 and (entry.get("clientDelta") or 0) > 0


def dig(entry, dotted):
    value = entry
    for part in dotted.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def format_number(value):
    if value is None:
        return MISSING_CELL
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return "%.1f" % value


def corpse_readings(report):
    """Every health reading of both copies, in order, with None where the copy was gone, and the swing at which a copy first went unreadable."""
    host, client = [], []
    broke = None
    for entry in report.get("measurements") or []:
        for pair, series in ((entry.get("hostHp") or [], host), (entry.get("clientHp") or [], client)):
            series.extend(pair)
        if broke is None and ((entry.get("hostHp") or [0, 0])[-1] is None or (entry.get("clientHp") or [0, 0])[-1] is None):
            broke = entry["swing"]
    for sample in (report.get("target") or {}).get("samples") or []:
        host.append(sample.get("host"))
        client.append(sample.get("client"))
    after_chain = broke is None and (None in host or None in client)
    return host, client, broke, after_chain


def corpse_cells(report):
    host, client, broke, after_chain = corpse_readings(report)

    def cell(series):
        values = [value for value in series if value is not None]
        if not values:
            return GONE_SUFFIX
        low = min(values)
        text = format_number(low)
        if None in series:
            return text + GONE_SUFFIX
        return text

    if broke is not None:
        broke_text = "sw%d" % broke
    elif after_chain:
        last = len(report.get("measurements") or [])
        broke_text = "after sw%d" % last
    else:
        broke_text = "never"
    return {"host_hp": cell(host), "client_min": cell(client), "broke": broke_text}


def distinct_join(values):
    ordered = []
    for value in values:
        if value not in ordered:
            ordered.append(value)
    return " / ".join(ordered) if ordered else MISSING_CELL


def reclassify(runs, row):
    """A swing test is all or nothing: a run in which any swing did not land is not a valid run. With every gate recorded as passed at fire time the miss is a FAIL; a run with no gate
    record (a report from before the gate) cannot show the miss was not caused by the setup, so it is invalid; the profile's miss_cause names a recorded cause when it explains every miss."""
    metric = row.get("metric")
    for run in runs:
        if run["_status"] != "valid":
            continue
        if metric == "swings_landed":
            entries = run.get("measurements") or []
            missed = [entry for entry in entries if not landed(entry)]
            if not missed:
                continue
            if all((entry.get("gate") or {}).get("passed") for entry in entries):
                run["_status"], run["_reason"] = "fail", "swing %s missed, every gate passed" % missed[0].get("swing", "?")
                continue
            cause = row.get("miss_cause")
            explained = bool(cause) and all((dig(entry, cause["field"]) or 0) > cause["above"] for entry in missed)
            run["_status"], run["_reason"] = "invalid", "swing missed, " + (cause["label"] if explained else "no gate record")
        elif metric == "verdict_count" and run.get("verdict") != row["verdict"]:
            run["_status"], run["_reason"] = "fail", "verdict %s" % run.get("verdict")


def count_cell(runs, row, profile):
    """valid runs over executed runs: a run counts only when every swing landed (or the verdict is the wanted one)."""
    if row["metric"] not in ("swings_landed", "verdict_count"):
        raise ProfileError("unknown metric %r" % row["metric"])
    if not runs:
        return MISSING_CELL, (0, 0)
    done = len([run for run in runs if run["_status"] == "valid"])
    return "%d/%d" % (done, len(runs)), (done, len(runs))


def attack_hook_cell(checks):
    if not checks:
        return MISSING_CELL
    hosts = {check.get("hostTranspilerSuccess") for check in checks}
    clients = {check.get("clientTranspilerSuccess") for check in checks}
    if hosts == {1} and clients == {1}:
        return "1/game"
    return "host %s client %s" % (",".join(sorted(str(value) for value in hosts)), ",".join(sorted(str(value) for value in clients)))


def group_runs(paths, profile):
    runs = []
    for path in paths:
        report = load_report(path)
        report["_name"] = os.path.basename(path)
        if os.path.basename(path).startswith("launch_checks"):
            report["_kind"] = "launch_checks"
            report["_build"] = re.sub(r"^launch_checks__L\d+-", "", os.path.basename(path)[:-5])
        else:
            if "scenario" not in report:
                continue
            report["_kind"] = "report"
            report["_status"], report["_reason"] = run_status(report, profile)
        runs.append(report)
    return runs


def runs_for(all_runs, scenario, build, sources=None, root=None):
    chosen = []
    allowed = None if sources is None else set(expand_sources(sources, root))
    for run in all_runs:
        if run["_kind"] != "report" or run.get("scenario", "").split("__")[0] != scenario or run.get("build") != build:
            continue
        if allowed is not None and run["_path"] not in allowed:
            continue
        chosen.append(run)
    return chosen


def checks_for(all_runs, build, sources=None, root=None):
    allowed = None if sources is None else set(expand_sources(sources, root))
    return [run for run in all_runs if run["_kind"] == "launch_checks" and run["_build"].startswith(build + "-") and (allowed is None or run["_path"] in allowed)]


def deviations_for(label, runs, planned=None):
    lines = []
    for status, word in (("fail", "FAIL"), ("invalid", "invalid"), ("confounded", "confounded"), ("excluded", "excluded")):
        picked = [run for run in runs if run["_status"] == status]
        if not picked:
            continue
        reasons = {}
        for run in picked:
            reasons[run["_reason"]] = reasons.get(run["_reason"], 0) + 1
        detail = ", ".join(reason if count == 1 else "%s x%d" % (reason, count) for reason, count in reasons.items())
        lines.append("%s: %d %s (%s)" % (label, len(picked), word, detail))
    if planned is not None and len(runs) < planned:
        lines.append("%s: %d of %d runs not run" % (label, planned - len(runs), planned))
    return lines


def header_line(profile, all_runs):
    """The topic, the game version and the parameters that define the test, read from the included runs."""
    valid = [run for run in all_runs if run["_kind"] == "report" and run["_status"] == "valid"]
    game = None
    parts = []
    for field in profile.get("header", []):
        kind = field["id"]
        if kind == "game_version":
            versions = sorted({str(run.get("gameVersion")) for run in valid})
            game = "game " + "/".join(versions) if versions else "game -"
        elif kind == "swings":
            counts = sorted({len(run.get("measurements") or []) for run in valid})
            parts.append(field["text"].format(n="/".join(str(count) for count in counts) if counts else MISSING_CELL))
        elif kind == "median_interval":
            medians = [((run.get("target") or {}).get("swingRate") or {}).get("medianSeconds") for run in valid]
            medians = [value for value in medians if value is not None]
            parts.append("median %.2f s" % statistics.median(medians) if medians else "median -")
        elif kind == "distance":
            values = [(run.get("target") or {}).get("swingDistance") for run in valid]
            values = [value for value in values if value is not None]
            parts.append("%s %s u" % (field["text"], format_number(statistics.median(values))) if values else "%s -" % field["text"])
        elif kind == "held":
            held = bool(valid) and all((run.get("target") or {}).get("holds") for run in valid)
            parts.append("bodies held" if held else "bodies free")
        elif kind == "text":
            parts.append(field["text"])
        else:
            raise ProfileError("unknown header field %r" % kind)
    return "  ".join([profile["topic"]] + ([game] if game else []) + ([", ".join(parts)] if parts else []))


def build_identity(profile, build, root, all_runs):
    """A shortened identity of a build: the md5 of its stage DLL when the profile names one and it exists, otherwise the first hex of the reports' dllSha256."""
    spec = profile.get("builds", {}).get(build, {})
    path = spec.get("stageDll")
    if path:
        full = os.path.normpath(os.path.join(root, path))
        if os.path.isfile(full):
            with open(full, "rb") as handle:
                return hashlib.md5(handle.read()).hexdigest()[:8]
    shas = sorted({run["dllSha256"][:8] for run in all_runs if run.get("build") == build and run.get("dllSha256")})
    return "/".join(shas) if shas else MISSING_CELL


def new_stats():
    return {"valid": 0, "invalid": 0, "fail": 0, "notrun": 0, "excluded": 0, "unmet": []}


def add_runs(stats, runs, planned):
    for run in runs:
        if run["_status"] == "valid":
            stats["valid"] += 1
        elif run["_status"] == "fail":
            stats["fail"] += 1
        elif run["_status"] == "excluded":
            stats["excluded"] += 1
        else:
            stats["invalid"] += 1
    if planned is not None and len(runs) < planned:
        stats["notrun"] += planned - len(runs)


def verdict_line(stats):
    """One line for a block: every valid run as expected, how many are invalid or not run, or FAIL with what failed."""
    extras = []
    if stats["invalid"]:
        extras.append("%d invalid" % stats["invalid"])
    if stats["excluded"]:
        extras.append("%d excluded" % stats["excluded"])
    if stats["notrun"]:
        extras.append("%d not run" % stats["notrun"])
    if stats["fail"] or stats["unmet"]:
        reasons = []
        if stats["fail"]:
            reasons.append("%d run%s FAIL" % (stats["fail"], "" if stats["fail"] == 1 else "s"))
        if stats["unmet"]:
            reasons.append("expected not met: " + "; ".join(stats["unmet"][:3]) + ("; and %d more" % (len(stats["unmet"]) - 3) if len(stats["unmet"]) > 3 else ""))
        return "FAIL (" + ", ".join(reasons) + ")" + ("".join(", " + item for item in extras))
    base = "all %d valid runs as expected" % stats["valid"] if stats["valid"] else "no valid run"
    return base + "".join(", " + item for item in extras)


def build_result(profile, root):
    validate_profile(profile)
    all_runs = group_runs(expand_sources(profile["sources"], root), profile)
    header_scenarios = {row["scenario"] for table in profile["tables"] if table["kind"] == "pair_rows" for row in table["rows"]}
    header_runs = [run for run in all_runs if run["_kind"] == "report" and run.get("scenario") in header_scenarios] if header_scenarios else all_runs
    result = {"header": header_line(profile, header_runs), "builds": [], "blocks": [], "tables": [], "deviations": []}
    seen_builds = []
    for table in profile["tables"]:
        for build in table["builds"]:
            if build["build"] not in [item[1] for item in seen_builds]:
                seen_builds.append((build["label"], build["build"]))
    result["builds"] = [(label, build_identity(profile, build, root, all_runs)) for label, build in seen_builds]
    blocks = {role: {"role": role, "heading": ROLE_HEADINGS[role], "tables": [], "stats": new_stats()} for role in ROLES}
    for table in profile["tables"]:
        for role in ROLES:
            rows = [row for row in table["rows"] if row["role"] == role]
            if not rows:
                continue
            block = blocks[role]
            if table["kind"] == "pair_rows":
                rendered = pair_table(table, rows, all_runs, root, result["deviations"], block["stats"])
            else:
                rendered = metric_table(table, rows, all_runs, root, result["deviations"], block["stats"])
            block["tables"].append(rendered)
    for role in ROLES:
        block = blocks[role]
        if block["tables"]:
            block["verdict"] = verdict_line(block["stats"])
            result["blocks"].append(block)
            result["tables"].extend(block["tables"])
    return result


def pair_table(table, rows_spec, all_runs, root, deviations, stats):
    columns = table["columns"]
    rows = []
    for pair in rows_spec:
        for build in table["builds"]:
            runs = runs_for(all_runs, pair["scenario"], build["build"], pair.get("sources"), root)
            valid = [run for run in runs if run["_status"] == "valid"]
            cells = [corpse_cells(run) for run in valid]
            row = [pair["label"], build["label"]] + [distinct_join([cell[column["id"]] for cell in cells]) if cells else MISSING_CELL for column in columns]
            rows.append(row)
            add_runs(stats, runs, pair.get("planned_runs"))
            for column_id, wanted in (pair.get("expect", {}).get(build["label"]) or {}).items():
                got = distinct_join([cell[column_id] for cell in cells]) if cells else MISSING_CELL
                if cells and got != wanted:
                    stats["unmet"].append("%s %s %s %s not %s" % (pair["label"], build["label"], column_id, got, wanted))
            deviations.extend(deviations_for("%s %s" % (pair["label"], build["label"]), runs, pair.get("planned_runs")))
    return {"title": table.get("title"), "headers": ["host/client", "build"] + [column["label"] for column in columns], "rows": rows}


def metric_table(table, rows_spec, all_runs, root, deviations, stats):
    rows = []
    for row in rows_spec:
        cells = []
        for build in table["builds"]:
            if row.get("metric") == "attack_hook":
                checks = checks_for(all_runs, build["build"], row.get("sources"), root)
                cells.append(attack_hook_cell(checks))
                continue
            runs = [run for run in runs_for(all_runs, row["scenario"], build["build"], row.get("sources"), root) if run["_status"] != "excluded"]
            reclassify(runs, row)
            text, counts = count_cell(runs, row, table)
            cells.append(text)
            add_runs(stats, runs, row.get("planned_runs"))
            expect = row.get("expect")
            if isinstance(expect, dict):
                expect = expect.get(build["label"])
            if expect == "all" and counts[1] and counts[0] != counts[1]:
                stats["unmet"].append("%s %s %d of %d" % (row["label"], build["label"], counts[0], counts[1]))
            deviations.extend(deviations_for("%s %s" % (row["label"], build["label"]), runs, row.get("planned_runs")))
        rows.append([row["label"]] + cells)
    return {"title": table.get("title"), "headers": [table.get("row_label", "test")] + [build["label"] for build in table["builds"]], "rows": rows}


def render_text(result):
    lines = [result["header"]]
    if result["builds"]:
        lines.append("builds  " + "  ".join("%s %s" % item for item in result["builds"]))
    for block in result["blocks"]:
        lines.append("")
        lines.append(block["role"])
        for table in block["tables"]:
            if table["title"]:
                lines.append(table["title"])
            grid = [table["headers"]] + table["rows"]
            widths = [max(len(str(row[index])) for row in grid) for index in range(len(table["headers"]))]
            for row in grid:
                lines.append("  ".join(str(cell).ljust(widths[index]) for index, cell in enumerate(row)).rstrip())
        lines.append("verdict  " + block["verdict"])
    if result["deviations"]:
        lines.append("")
        lines.extend(result["deviations"])
    return "\n".join(lines) + "\n"


def render_fenced(result):
    """The aligned text in a fenced code block, so the columns survive in a PR comment."""
    return "```text\n" + render_text(result) + "```\n"


def escape_cell(value):
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("<", "\\<").replace(">", "\\>")


def render_markdown(result):
    lines = ["**%s**" % escape_cell(result["header"])]
    if result["builds"]:
        lines.append("")
        lines.append("builds: " + ", ".join("%s `%s`" % (escape_cell(label), identity) for label, identity in result["builds"]))
    for block in result["blocks"]:
        lines.append("")
        lines.append("### " + block["heading"])
        for table in block["tables"]:
            lines.append("")
            if table["title"]:
                lines.append("**%s**" % escape_cell(table["title"]))
                lines.append("")
            lines.append("| " + " | ".join(escape_cell(cell) for cell in table["headers"]) + " |")
            lines.append("|" + "|".join("---" for _ in table["headers"]) + "|")
            for row in table["rows"]:
                lines.append("| " + " | ".join(escape_cell(cell) for cell in row) + " |")
        lines.append("")
        lines.append("Verdict: " + escape_cell(block["verdict"]))
    if result["deviations"]:
        lines.append("")
        lines.append("### Deviations")
        lines.append("")
        lines.extend("- " + escape_cell(item) for item in result["deviations"])
    return "\n".join(lines) + "\n"
