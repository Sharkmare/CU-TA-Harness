import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest

from casualtieslink.reports import prtable

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "prtable")
PROFILES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "profiles")
VERBOSE = "pr24-corpse-verbose"
FIXED = "pr24-corpse-fix"
PLAIN = "pr24-3d060fe-plain"
TIP_FIX = "pr24-3d060fe-corpse-fix"


def load(relative):
    return prtable.load_report(os.path.join(FIXTURES, relative))


def status_of(relative, profile=None):
    return prtable.run_status(load(relative), profile or {})


def corpse_profile(**changes):
    profile = {
        "name": "test", "topic": "CORPSE", "sources": ["corpse/*.json"], "params": {"real_rate_median_max": 0.3}, "superseded_confounders": ["^host hold at"],
        "header": [{"id": "game_version"}, {"id": "swings", "text": "{n} bare swings"}, {"id": "median_interval"}, {"id": "distance", "text": "corpse"}, {"id": "held"}],
        "builds": {},
        "tables": [{"kind": "pair_rows", "title": None, "builds": [{"label": "PR24", "build": VERBOSE}, {"label": "PR24+fix", "build": FIXED}],
                    "columns": [{"id": "host_hp", "label": "host hp"}, {"id": "client_min", "label": "client hp (min)"}, {"id": "broke", "label": "broke"}],
                    "rows": [{"label": "Milky/Dune", "scenario": "corpse_chain_by_client"}, {"label": "Dune/Dune", "scenario": "corpse_chain_dune_dune_by_client"},
                             {"label": "Milky/Milky", "scenario": "corpse_chain_milky_milky_by_client"}, {"label": "Dune/Milky", "scenario": "corpse_chain_dune_milky_by_client"}]}]}
    profile.update(changes)
    return profile


def hits_profile(rows, builds=None, sources=None):
    return {"name": "test", "topic": "HITS", "sources": sources or ["hits/*.json"], "params": {}, "header": [{"id": "game_version"}], "builds": {},
            "tables": [{"kind": "metric_rows", "title": None, "row_label": "", "builds": builds or [{"label": "plain", "build": PLAIN}, {"label": "fix", "build": TIP_FIX}], "rows": rows}]}


def table_cells(result, table=0):
    return {tuple(row[:2]) if result["tables"][table]["headers"][1] == "build" else row[0]: row for row in result["tables"][table]["rows"]}


class CorpseCellTests(unittest.TestCase):
    def cells(self, relative):
        cells = prtable.corpse_cells(load(relative))
        return cells["host_hp"], cells["client_min"], cells["broke"]

    def test_the_mixed_pair_on_the_control_build_never_breaks_and_the_client_copy_goes_to_minus_366(self):
        self.assertEqual(self.cells("corpse/mixed_pr24.json"), ("250", "-366.7", "never"))

    def test_the_mixed_pair_on_the_fix_build_breaks_at_swing_11_after_a_single_negative_reading(self):
        self.assertEqual(self.cells("corpse/mixed_fix.json"), ("3.2->gone", "-21.4->gone", "sw11"))

    def test_dune_and_dune_breaks_at_swing_11_on_the_control_and_on_the_fix(self):
        self.assertEqual(self.cells("corpse/dune_pr24.json"), ("3.2->gone", "3.2->gone", "sw11"))
        self.assertEqual(self.cells("corpse/dune_fix_confounded.json"), ("3.2->gone", "3.2->gone", "sw11"))

    def test_milky_and_milky_and_dune_host_milky_client_take_no_damage(self):
        for fixture in ("corpse/milky_pr24.json", "corpse/milky_fix.json", "corpse/dunemilky_fix.json"):
            with self.subTest(fixture=fixture):
                self.assertEqual(self.cells(fixture), ("250", "250", "never"))

    def test_a_copy_that_is_gone_before_any_reading_reads_as_gone_only(self):
        report = copy.deepcopy(load("corpse/mixed_fix.json"))
        report["measurements"] = [{"swing": 1, "hostHp": [None, None], "clientHp": [None, None]}]
        report["target"]["samples"] = []
        self.assertEqual(prtable.corpse_cells(report), {"host_hp": "->gone", "client_min": "->gone", "broke": "sw1"})

    def test_a_copy_that_vanishes_only_after_the_chain_is_not_reported_as_breaking_in_it(self):
        report = copy.deepcopy(load("corpse/milky_pr24.json"))
        report["target"]["samples"] = [{"host": 250.0, "client": 250.0}, {"host": None, "client": None}]
        self.assertEqual(prtable.corpse_cells(report)["broke"], "after sw25")

    def test_the_numbers_come_from_the_readings_not_from_a_cached_summary_field(self):
        report = copy.deepcopy(load("corpse/mixed_pr24.json"))
        report["target"]["prediction"]["clientMinHp"] = 999.0
        self.assertEqual(prtable.corpse_cells(report)["client_min"], "-366.7")
        report["measurements"][3]["clientHp"][1] = -500.0
        self.assertEqual(prtable.corpse_cells(report)["client_min"], "-500")


class StatusTests(unittest.TestCase):
    def test_clean_runs_are_valid(self):
        self.assertEqual(status_of("corpse/mixed_pr24.json")[0], "valid")
        self.assertEqual(status_of("hits/pvp_fix_r1.json")[0], "valid")

    def test_a_run_with_missed_swings_but_no_invalid_marker_is_still_a_valid_run(self):
        self.assertEqual(status_of("hits/static_fix_r2.json")[0], "valid")

    def test_an_invalid_marker_makes_the_run_invalid_with_a_short_reason(self):
        self.assertEqual(status_of("hits/crate_fix_invalid.json"), ("invalid", "position preflight failed"))
        self.assertEqual(status_of("hits/static_fix_r5_invalid.json"), ("invalid", "client out of band"))

    def test_a_slow_run_is_excluded_only_when_the_profile_sets_a_rate_limit(self):
        self.assertEqual(status_of("corpse/mixed_pr24_slow.json", {"params": {"real_rate_median_max": 0.3}}), ("excluded", "slow swings 0.42 s"))
        self.assertEqual(status_of("corpse/mixed_pr24_slow.json", {})[0], "valid")

    def test_a_confounded_run_stays_confounded_unless_the_profile_lists_the_cause_as_superseded(self):
        self.assertEqual(status_of("corpse/dune_fix_confounded.json", {})[0], "confounded")
        self.assertEqual(status_of("corpse/dune_fix_confounded.json", {"superseded_confounders": ["^host hold at"]})[0], "valid")
        report = copy.deepcopy(load("corpse/dune_fix_confounded.json"))
        report["target"]["prediction"]["confoundedBy"].append("the parked host was 4.00 from the swing at swing 3, below 6.0")
        self.assertEqual(prtable.run_status(report, {"superseded_confounders": ["^host hold at"]})[0], "confounded")

    def test_a_confounded_issue_line_and_a_not_counted_line_are_recognised(self):
        report = {"issues": ["CONFOUNDED: the parked host was not far enough from the swing: x"]}
        self.assertEqual(prtable.run_status(report, {})[0], "confounded")
        report = {"issues": ["NOT COUNTED: the swings were fired before limb 1 came within 4.0 of the crate"]}
        self.assertEqual(prtable.run_status(report, {}), ("invalid", "limb gate not passed"))

    def test_an_unknown_reason_is_cut_to_five_words(self):
        report = {"issues": ["INVALID: something entirely new went wrong here today"]}
        self.assertEqual(prtable.run_status(report, {})[1], "something entirely new went wrong")


class CountTests(unittest.TestCase):
    def cell(self, row, build, sources=None):
        rows = [dict(row, sources=sources)] if sources else [row]
        result = prtable.build_result(hits_profile(rows), FIXTURES)
        return result["tables"][0]["rows"][0][1 if build == "plain" else 2], result["deviations"]

    def test_punches_that_landed_on_both_machines_are_counted_over_the_valid_runs(self):
        row = {"label": "PvP", "scenario": "pvp_banded_by_client", "metric": "swings_landed"}
        text, deviations = self.cell(row, "fix")
        self.assertEqual(text, "15/15")
        self.assertEqual(deviations, [])
        self.assertEqual(self.cell(row, "plain")[0], "5/5")

    def test_an_invalid_run_never_enters_a_count_and_is_listed_with_its_reason(self):
        row = {"label": "crate swings", "scenario": "spawned_crate_hit_by_client", "metric": "swings_landed"}
        text, deviations = self.cell(row, "fix")
        self.assertEqual(text, "10/10")
        self.assertEqual(deviations, ["crate swings fix: 1 invalid (position preflight failed)"])

    def test_turning_a_valid_run_invalid_removes_exactly_its_swings_from_the_count(self):
        with tempfile.TemporaryDirectory() as root:
            shutil.copytree(os.path.join(FIXTURES, "hits"), os.path.join(root, "hits"))
            path = os.path.join(root, "hits", "crate_fix_r1.json")
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            data["issues"] = ["INVALID: the position preflight failed before the first swing: x"]
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            result = prtable.build_result(hits_profile([{"label": "crate swings", "scenario": "spawned_crate_hit_by_client", "metric": "swings_landed"}]), root)
        self.assertEqual(result["tables"][0]["rows"][0][2], "5/5")
        self.assertEqual(result["deviations"], ["crate swings fix: 2 invalid (position preflight failed x2)"])

    def test_static_copy_counts_landed_over_all_swings_and_names_the_cause_when_every_miss_has_a_lagging_limb(self):
        row = {"label": "static", "scenario": "staticcrate_hit_by_client", "metric": "swings_landed", "miss_cause": {"field": "geometry.limb1Distance", "above": 4.0, "label": "limb lag"}}
        text, deviations = self.cell(row, "fix")
        self.assertEqual(text, "7/15 (misses: limb lag)")
        self.assertEqual(deviations, ["static fix: 1 invalid (client out of band)"])
        self.assertEqual(self.cell(row, "plain")[0], "4/5 (misses: limb lag)")

    def test_a_miss_that_the_cause_does_not_explain_changes_the_note_to_a_count(self):
        row = {"label": "static", "scenario": "staticcrate_hit_by_client", "metric": "swings_landed", "miss_cause": {"field": "geometry.limb1Distance", "above": 8.0, "label": "limb lag"}}
        self.assertEqual(self.cell(row, "fix")[0], "7/15 (6 of 8 misses: limb lag)")

    def test_no_cause_note_is_printed_when_the_profile_names_none(self):
        row = {"label": "static", "scenario": "staticcrate_hit_by_client", "metric": "swings_landed"}
        self.assertEqual(self.cell(row, "fix")[0], "7/15")

    def test_mining_counts_the_runs_with_the_wanted_verdict(self):
        row = {"label": "mining", "scenario": "v2check_dig_cracks", "metric": "verdict_count", "verdict": "persisted"}
        self.assertEqual(self.cell(row, "fix")[0], "2/2")
        self.assertEqual(self.cell(row, "plain")[0], "1/1")
        with tempfile.TemporaryDirectory() as root:
            shutil.copytree(os.path.join(FIXTURES, "hits"), os.path.join(root, "hits"))
            path = os.path.join(root, "hits", "mining_fix_r2.json")
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            data["verdict"] = "crack-reset"
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            result = prtable.build_result(hits_profile([row]), root)
        self.assertEqual(result["tables"][0]["rows"][0][2], "1/2")

    def test_the_attack_hook_cell_reads_the_launch_check_counts(self):
        row = {"label": "Body.Attack hook", "metric": "attack_hook"}
        result = prtable.build_result(hits_profile([row], sources=["hits/launch_checks*.json"]), FIXTURES)
        self.assertEqual(result["tables"][0]["rows"][0], ["Body.Attack hook", "-", "-"])

    def test_the_attack_hook_cell_with_named_launch_check_files(self):
        with tempfile.TemporaryDirectory() as root:
            for build, name in ((PLAIN, "plain"), (TIP_FIX, "fix")):
                shutil.copy(os.path.join(FIXTURES, "hits", "launch_checks_%s.json" % name), os.path.join(root, "launch_checks__L1-%s-hook-evidence.json" % build))
            row = {"label": "Body.Attack hook", "metric": "attack_hook"}
            result = prtable.build_result(hits_profile([row], sources=["launch_checks*.json"]), root)
            self.assertEqual(result["tables"][0]["rows"][0], ["Body.Attack hook", "1/game", "1/game"])
            path = os.path.join(root, "launch_checks__L1-%s-hook-evidence.json" % TIP_FIX)
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            data["hostTranspilerSuccess"] = 2
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            result = prtable.build_result(hits_profile([row], sources=["launch_checks*.json"]), root)
            self.assertEqual(result["tables"][0]["rows"][0][2], "host 2 client 1")

    def test_a_swing_counts_as_landed_only_when_both_machines_lost_health(self):
        self.assertTrue(prtable.landed({"hostDelta": 19.3, "clientDelta": 19.3}))
        self.assertFalse(prtable.landed({"hostDelta": 19.3, "clientDelta": 0.0}))
        self.assertFalse(prtable.landed({"hostDelta": 0.0, "clientDelta": 19.3}))
        self.assertFalse(prtable.landed({"hostDelta": None, "clientDelta": None}))

    def test_a_count_short_of_the_planned_runs_is_flagged(self):
        row = {"label": "PvP", "scenario": "pvp_banded_by_client", "metric": "swings_landed", "planned_runs": 6}
        text, deviations = self.cell(row, "fix")
        self.assertEqual(deviations, ["PvP plain: 5 of 6 runs not run", "PvP fix: 3 of 6 runs not run"])

    def test_a_build_with_no_runs_prints_a_dash_and_no_count(self):
        row = {"label": "PvP", "scenario": "pvp_banded_by_client", "metric": "swings_landed"}
        result = prtable.build_result(hits_profile([row], builds=[{"label": "other", "build": "no-such-build"}]), FIXTURES)
        self.assertEqual(result["tables"][0]["rows"], [["PvP", "-"]])


class CorpseTableTests(unittest.TestCase):
    def setUp(self):
        self.result = prtable.build_result(corpse_profile(), FIXTURES)

    def rows(self):
        return {(row[0], row[1]): row[2:] for row in self.result["tables"][0]["rows"]}

    def test_every_pair_and_build_has_one_row_in_the_profile_order(self):
        keys = [(row[0], row[1]) for row in self.result["tables"][0]["rows"]]
        self.assertEqual(keys, [("Milky/Dune", "PR24"), ("Milky/Dune", "PR24+fix"), ("Dune/Dune", "PR24"), ("Dune/Dune", "PR24+fix"), ("Milky/Milky", "PR24"),
                                ("Milky/Milky", "PR24+fix"), ("Dune/Milky", "PR24"), ("Dune/Milky", "PR24+fix")])

    def test_the_cells_are_the_extracted_numbers(self):
        rows = self.rows()
        self.assertEqual(rows[("Milky/Dune", "PR24")], ["250", "-366.7", "never"])
        self.assertEqual(rows[("Milky/Dune", "PR24+fix")], ["3.2->gone", "-21.4->gone", "sw11"])
        self.assertEqual(rows[("Dune/Dune", "PR24")], ["3.2->gone", "3.2->gone", "sw11"])
        self.assertEqual(rows[("Dune/Dune", "PR24+fix")], ["3.2->gone", "3.2->gone", "sw11"])
        self.assertEqual(rows[("Milky/Milky", "PR24")], ["250", "250", "never"])
        self.assertEqual(rows[("Milky/Milky", "PR24+fix")], ["250", "250", "never"])
        self.assertEqual(rows[("Dune/Milky", "PR24+fix")], ["250", "250", "never"])

    def test_a_pair_that_was_not_run_on_a_build_prints_dashes_and_one_not_run_line(self):
        self.assertEqual(self.rows()[("Dune/Milky", "PR24")], ["-", "-", "-"])
        profile = corpse_profile()
        for row in profile["tables"][0]["rows"]:
            row["planned_runs"] = 1
        self.assertIn("Dune/Milky PR24: 1 of 1 runs not run", prtable.build_result(profile, FIXTURES)["deviations"])

    def test_the_header_states_the_topic_game_version_and_the_parameters_that_define_the_test(self):
        self.assertEqual(self.result["header"], "CORPSE  game 1.0.1  25 bare swings, median 0.23 s, corpse 2.5 u, bodies held")

    def test_the_slow_run_is_excluded_from_the_numbers_and_flagged(self):
        self.assertIn("Milky/Dune PR24: 1 excluded (slow swings 0.42 s)", self.result["deviations"])
        self.assertEqual(self.rows()[("Milky/Dune", "PR24")][1], "-366.7")

    def test_without_a_rate_limit_the_slow_run_joins_the_cell(self):
        profile = corpse_profile(params={})
        result = prtable.build_result(profile, FIXTURES)
        row = [row for row in result["tables"][0]["rows"] if row[:2] == ["Milky/Dune", "PR24"]][0]
        self.assertEqual(row[3], "-366.7 / 200.6")

    def test_only_deviations_are_printed_below_the_tables(self):
        self.assertEqual(self.result["deviations"], ["Milky/Dune PR24: 1 excluded (slow swings 0.42 s)"])
        for line in self.result["deviations"]:
            self.assertRegex(line, r"(invalid|excluded|confounded|not run)")


class ProfileDrivesTheOutputTests(unittest.TestCase):
    def test_dropping_a_column_removes_it_from_the_headers_and_the_rows(self):
        profile = corpse_profile()
        profile["tables"][0]["columns"] = [profile["tables"][0]["columns"][2]]
        table = prtable.build_result(profile, FIXTURES)["tables"][0]
        self.assertEqual(table["headers"], ["host/client", "build", "broke"])
        self.assertEqual(table["rows"][0], ["Milky/Dune", "PR24", "never"])

    def test_renaming_labels_and_reordering_rows_changes_the_output(self):
        profile = corpse_profile()
        profile["tables"][0]["columns"][0]["label"] = "host"
        profile["tables"][0]["builds"][0]["label"] = "control"
        profile["tables"][0]["rows"].reverse()
        table = prtable.build_result(profile, FIXTURES)["tables"][0]
        self.assertEqual(table["headers"][2], "host")
        self.assertEqual(table["rows"][0][:2], ["Dune/Milky", "control"])

    def test_a_second_build_column_appears_when_the_profile_lists_it(self):
        rows = [{"label": "PvP", "scenario": "pvp_banded_by_client", "metric": "swings_landed"}]
        two = prtable.build_result(hits_profile(rows), FIXTURES)["tables"][0]
        three = prtable.build_result(hits_profile(rows, builds=[{"label": "plain", "build": PLAIN}, {"label": "fix", "build": TIP_FIX}, {"label": "none", "build": "x"}]), FIXTURES)["tables"][0]
        self.assertEqual(two["headers"], ["", "plain", "fix"])
        self.assertEqual(three["headers"], ["", "plain", "fix", "none"])
        self.assertEqual(three["rows"][0], ["PvP", "5/5", "15/15", "-"])

    def test_the_header_fields_come_from_the_profile(self):
        profile = corpse_profile(header=[{"id": "game_version"}, {"id": "text", "text": "real rate"}])
        self.assertEqual(prtable.build_result(profile, FIXTURES)["header"], "CORPSE  game 1.0.1  real rate")

    def test_the_miss_cause_note_follows_the_profile_row(self):
        with_cause = {"label": "static", "scenario": "staticcrate_hit_by_client", "metric": "swings_landed", "miss_cause": {"field": "geometry.limb1Distance", "above": 4.0, "label": "limb lag"}}
        without = {"label": "static", "scenario": "staticcrate_hit_by_client", "metric": "swings_landed"}
        self.assertIn("limb lag", prtable.build_result(hits_profile([with_cause]), FIXTURES)["tables"][0]["rows"][0][2])
        self.assertNotIn("limb lag", prtable.build_result(hits_profile([without]), FIXTURES)["tables"][0]["rows"][0][2])

    def test_a_profile_without_its_required_keys_or_with_an_unknown_table_kind_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "bad.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"name": "x", "topic": "X"}, handle)
            with self.assertRaises(prtable.ProfileError):
                prtable.load_profile(path)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"name": "x", "topic": "X", "sources": [], "tables": [{"kind": "pie", "builds": [{"label": "a", "build": "b"}]}]}, handle)
            with self.assertRaises(prtable.ProfileError):
                prtable.load_profile(path)

    def test_the_shipped_profiles_load_and_name_scenarios_columns_and_builds(self):
        for name in ("corpse-fix.json", "hit-fix.json"):
            with self.subTest(profile=name):
                profile = prtable.load_profile(os.path.join(PROFILES, name))
                self.assertTrue(profile["sources"])
                for table in profile["tables"]:
                    self.assertTrue(table["builds"])
                    self.assertTrue(table.get("rows"))

    def test_the_shipped_corpse_profile_compares_the_control_with_the_fix_build(self):
        profile = prtable.load_profile(os.path.join(PROFILES, "corpse-fix.json"))
        self.assertEqual([build["build"] for build in profile["tables"][0]["builds"]], [VERBOSE, FIXED])
        self.assertEqual([column["label"] for column in profile["tables"][0]["columns"]], ["host hp", "client hp (min)", "broke"])


class BuildIdentityTests(unittest.TestCase):
    def test_without_a_stage_file_the_identity_is_the_start_of_the_reports_dll_hash(self):
        report = load("corpse/mixed_pr24.json")
        identity = prtable.build_identity({"builds": {}}, VERBOSE, FIXTURES, [report])
        self.assertEqual(identity, report["dllSha256"][:8])
        self.assertEqual(len(identity), 8)

    def test_with_a_stage_file_the_identity_is_its_md5_prefix(self):
        with tempfile.TemporaryDirectory() as root:
            dll = os.path.join(root, "stage", "CasualtiesMP.dll")
            os.makedirs(os.path.dirname(dll))
            with open(dll, "wb") as handle:
                handle.write(b"abc")
            identity = prtable.build_identity({"builds": {"b": {"stageDll": "stage/CasualtiesMP.dll"}}}, "b", root, [])
        self.assertEqual(identity, hashlib.md5(b"abc").hexdigest()[:8])

    def test_a_build_with_neither_prints_a_dash(self):
        self.assertEqual(prtable.build_identity({"builds": {}}, "nope", FIXTURES, []), "-")

    def test_the_builds_are_printed_once_in_the_header_block(self):
        result = prtable.build_result(corpse_profile(), FIXTURES)
        self.assertEqual(len(result["builds"]), 2)
        self.assertTrue(result["builds"][0].startswith("PR24 "))


class RenderingTests(unittest.TestCase):
    def setUp(self):
        self.result = prtable.build_result(corpse_profile(), FIXTURES)

    def test_the_text_rendering_starts_with_the_header_and_has_aligned_columns(self):
        lines = prtable.render_text(self.result).splitlines()
        self.assertEqual(lines[0], self.result["header"])
        block = lines[lines.index("") + 1:lines.index("", lines.index("") + 1)]
        self.assertEqual(len(block), 1 + len(self.result["tables"][0]["rows"]))
        columns = [line.index("build") if line.startswith("host/client") else line.index("PR24") for line in block]
        self.assertEqual(len(set(columns)), 1)

    def test_the_markdown_rendering_has_a_pipe_table_with_the_same_cells(self):
        text = prtable.render_markdown(self.result)
        lines = [line for line in text.splitlines() if line.startswith("|")]
        self.assertEqual(lines[1], "|---|---|---|---|---|")
        cells = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
        self.assertEqual(cells[0], self.result["tables"][0]["headers"])
        self.assertEqual(cells[2:], [[str(cell) for cell in row] for row in self.result["tables"][0]["rows"]])

    def test_both_renderings_carry_every_deviation_and_nothing_else_below_the_tables(self):
        text = prtable.render_text(self.result)
        markdown = prtable.render_markdown(self.result)
        for item in self.result["deviations"]:
            self.assertIn(item, text)
            self.assertIn("- " + item, markdown)

    def test_a_pipe_in_a_cell_is_escaped_in_markdown(self):
        result = {"header": "H", "builds": [], "tables": [{"title": None, "headers": ["a", "b"], "rows": [["x", "p|q"]]}], "deviations": []}
        self.assertIn("p\\|q", prtable.render_markdown(result))

    def test_the_text_output_has_no_narration_words(self):
        text = prtable.render_text(self.result).lower()
        for word in ("guard", "setup", "launched", "cleanup", "restored"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
