"""Compact result tables for one PR or topic, computed from the harness report JSONs and driven by a profile file.

A profile (client/profiles/*.json) names the report files, the builds to compare, the rows and the columns. The numbers are read from the reports, never typed.
Two renderings come from the same data: aligned text for a terminal or chat, and a Markdown table for a PR body.
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


class ProfileError(ValueError):
    pass


def load_profile(path):
    with open(path, encoding="utf-8") as handle:
        profile = json.load(handle)
    for key in REQUIRED_PROFILE_KEYS:
        if key not in profile:
            raise ProfileError("profile %s has no %r" % (path, key))
    for table in profile["tables"]:
        if table.get("kind") not in ("pair_rows", "metric_rows"):
            raise ProfileError("table %r has the unknown kind %r" % (table.get("title"), table.get("kind")))
        if not table.get("builds"):
            raise ProfileError("table %r lists no builds" % table.get("title"))
    return profile


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


def count_cell(runs, row, profile):
    """landed/total swings, or verdict count, over the valid runs of one cell, with the miss-cause note when the profile asks for one."""
    metric = row["metric"]
    if metric == "swings_landed":
        entries = [entry for run in runs for entry in (run.get("measurements") or [])]
        if not entries:
            return MISSING_CELL, None
        done = len([entry for entry in entries if landed(entry)])
        text = "%d/%d" % (done, len(entries))
        cause = row.get("miss_cause")
        misses = [entry for entry in entries if not landed(entry)]
        if cause and misses:
            explained = [entry for entry in misses if (dig(entry, cause["field"]) or 0) > cause["above"]]
            if len(explained) == len(misses):
                text += " (misses: %s)" % cause["label"]
            elif explained:
                text += " (%d of %d misses: %s)" % (len(explained), len(misses), cause["label"])
        return text, None
    if metric == "verdict_count":
        if not runs:
            return MISSING_CELL, None
        done = len([run for run in runs if run.get("verdict") == row["verdict"]])
        return "%d/%d" % (done, len(runs)), None
    raise ProfileError("unknown metric %r" % metric)


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
    for status, word in (("invalid", "invalid"), ("confounded", "confounded"), ("excluded", "excluded")):
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


def build_result(profile, root):
    all_runs = group_runs(expand_sources(profile["sources"], root), profile)
    result = {"header": header_line(profile, all_runs), "builds": [], "tables": [], "deviations": []}
    seen_builds = []
    for table in profile["tables"]:
        for build in table["builds"]:
            if build["build"] not in [item[1] for item in seen_builds]:
                seen_builds.append((build["label"], build["build"]))
    result["builds"] = ["%s %s" % (label, build_identity(profile, build, root, all_runs)) for label, build in seen_builds]
    for table in profile["tables"]:
        if table["kind"] == "pair_rows":
            rendered = pair_table(table, all_runs, profile, root, result["deviations"])
        else:
            rendered = metric_table(table, all_runs, profile, root, result["deviations"])
        result["tables"].append(rendered)
    return result


def pair_table(table, all_runs, profile, root, deviations):
    columns = table["columns"]
    rows = []
    for pair in table["rows"]:
        for build in table["builds"]:
            runs = runs_for(all_runs, pair["scenario"], build["build"], pair.get("sources"), root)
            valid = [run for run in runs if run["_status"] == "valid"]
            cells = [corpse_cells(run) for run in valid]
            row = [pair["label"], build["label"]] + [distinct_join([cell[column["id"]] for cell in cells]) if cells else MISSING_CELL for column in columns]
            rows.append(row)
            deviations.extend(deviations_for("%s %s" % (pair["label"], build["label"]), runs, pair.get("planned_runs")))
    return {"title": table.get("title"), "headers": ["host/client", "build"] + [column["label"] for column in columns], "rows": rows}


def metric_table(table, all_runs, profile, root, deviations):
    rows = []
    for row in table["rows"]:
        cells = []
        for build in table["builds"]:
            if row.get("metric") == "attack_hook":
                checks = checks_for(all_runs, build["build"], row.get("sources"), root)
                cells.append(attack_hook_cell(checks))
                continue
            runs = runs_for(all_runs, row["scenario"], build["build"], row.get("sources"), root)
            valid = [run for run in runs if run["_status"] == "valid"]
            text, _ = count_cell(valid, row, profile)
            cells.append(text)
            deviations.extend(deviations_for("%s %s" % (row["label"], build["label"]), runs, row.get("planned_runs")))
        rows.append([row["label"]] + cells)
    return {"title": table.get("title"), "headers": [table.get("row_label", "")] + [build["label"] for build in table["builds"]], "rows": rows}


def render_text(result):
    lines = [result["header"]]
    if result["builds"]:
        lines.append("builds  " + "  ".join(result["builds"]))
    for table in result["tables"]:
        lines.append("")
        if table["title"]:
            lines.append(table["title"])
        grid = [table["headers"]] + table["rows"]
        widths = [max(len(str(row[index])) for row in grid) for index in range(len(table["headers"]))]
        for row in grid:
            lines.append("  ".join(str(cell).ljust(widths[index]) for index, cell in enumerate(row)).rstrip())
    if result["deviations"]:
        lines.append("")
        lines.extend(result["deviations"])
    return "\n".join(lines) + "\n"


def render_markdown(result):
    lines = ["**%s**" % result["header"]]
    if result["builds"]:
        lines.append("")
        lines.append("builds: " + ", ".join(result["builds"]))
    for table in result["tables"]:
        lines.append("")
        if table["title"]:
            lines.append("**%s**" % table["title"])
            lines.append("")
        lines.append("| " + " | ".join(table["headers"]) + " |")
        lines.append("|" + "|".join("---" for _ in table["headers"]) + "|")
        for row in table["rows"]:
            lines.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |")
    if result["deviations"]:
        lines.append("")
        lines.extend("- " + item for item in result["deviations"])
    return "\n".join(lines) + "\n"
