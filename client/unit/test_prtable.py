import copy
import hashlib
import json
import os
import re
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
                    "rows": [{"label": "Milky/Dune", "scenario": "corpse_chain_by_client", "role": "MAIN", "expect": {"PR24+fix": {"broke": "sw11"}}},
                             {"label": "Dune/Dune", "scenario": "corpse_chain_dune_dune_by_client", "role": "MAIN", "expect": {"PR24+fix": {"broke": "sw11"}}},
                             {"label": "Milky/Milky", "scenario": "corpse_chain_milky_milky_by_client", "role": "MAIN", "expect": {"PR24+fix": {"broke": "never"}}},
                             {"label": "Dune/Milky", "scenario": "corpse_chain_dune_milky_by_client", "role": "MAIN", "expect": {"PR24+fix": {"broke": "never"}}}]}]}
    profile.update(changes)
    return profile


def hits_row(label, scenario, role="REGRESSION", **extra):
    return dict({"label": label, "scenario": scenario, "metric": "swings_landed", "role": role}, **extra)


def hits_profile(rows, builds=None, sources=None):
    return {"name": "test", "topic": "HITS", "sources": sources or ["hits/*.json"], "params": {}, "header": [{"id": "game_version"}], "builds": {},
            "tables": [{"kind": "metric_rows", "title": None, "builds": builds or [{"label": "plain", "build": PLAIN}, {"label": "fix", "build": TIP_FIX}], "rows": rows}]}


def mixed_profile():
    """The corpse table as MAIN and the hit counts as REGRESSION in one profile, from the fixtures."""
    profile = corpse_profile(sources=["corpse/*.json", "hits/*.json"])
    profile["tables"].append(hits_profile([hits_row("PvP punches", "pvp_banded_by_client", sources=["hits/pvp*.json"], expect={"fix": "all"}),
                                           hits_row("crate swings", "spawned_crate_hit_by_client", sources=["hits/crate*.json"]),
                                           hits_row("static copy", "staticcrate_hit_by_client", sources=["hits/static*.json"], miss_cause={"field": "geometry.limb1Distance", "above": 4.0, "label": "limb lag"}),
                                           {"label": "mining persisted", "scenario": "v2check_dig_cracks", "metric": "verdict_count", "verdict": "persisted", "role": "REGRESSION", "sources": ["hits/mining*.json"],
                                            "expect": {"fix": "all"}}])["tables"][0])
    return profile


def rows_of(result, label):
    return [row for table in result["tables"] for row in table["rows"] if row[0] == label]


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

    def test_a_run_with_missed_swings_but_no_marker_is_valid_at_report_level_and_reclassified_by_its_row(self):
        self.assertEqual(status_of("hits/static_fix_r2.json")[0], "valid")

    def test_an_invalid_marker_makes_the_run_invalid_with_a_short_reason(self):
        self.assertEqual(status_of("hits/crate_fix_invalid.json"), ("invalid", "position preflight failed"))
        self.assertEqual(status_of("hits/static_fix_r5_invalid.json"), ("invalid", "client out of band"))

    def test_a_fail_marker_makes_the_run_a_fail_not_an_invalid(self):
        self.assertEqual(prtable.run_status({"issues": ["FAIL: swing 3 did not land with every gate passed (host 0.00, client 0.00)"]}, {})[0], "fail")

    def test_an_invalid_marker_outranks_a_fail_marker_in_the_same_report(self):
        self.assertEqual(prtable.run_status({"issues": ["FAIL: x", "INVALID: y"]}, {})[0], "invalid")

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


class AllOrNothingTests(unittest.TestCase):
    def cell(self, row, build, sources=None):
        rows = [dict(row, sources=sources)] if sources else [row]
        result = prtable.build_result(hits_profile(rows), FIXTURES)
        return result["tables"][0]["rows"][0][1 if build == "plain" else 2], result["deviations"]

    def test_valid_runs_over_executed_runs_replace_swing_counts(self):
        row = hits_row("PvP", "pvp_banded_by_client")
        self.assertEqual(self.cell(row, "fix")[0], "3/3")
        self.assertEqual(self.cell(row, "plain")[0], "1/1")

    def test_an_invalid_run_never_enters_a_count_and_is_listed_with_its_reason(self):
        row = hits_row("crate swings", "spawned_crate_hit_by_client")
        text, deviations = self.cell(row, "fix")
        self.assertEqual(text, "2/3")
        self.assertEqual(deviations, ["crate swings fix: 1 invalid (position preflight failed)"])

    def test_one_missed_swing_excludes_the_whole_run_and_names_the_recorded_cause(self):
        row = hits_row("static", "staticcrate_hit_by_client", miss_cause={"field": "geometry.limb1Distance", "above": 4.0, "label": "limb lag"})
        text, deviations = self.cell(row, "fix")
        self.assertEqual(text, "1/4")
        self.assertEqual(deviations[-1], "static fix: 3 invalid (swing missed, limb lag x2, client out of band)")
        self.assertEqual(self.cell(row, "plain")[0], "0/1")
        self.assertEqual(self.cell(row, "plain")[1][0], "static plain: 1 invalid (swing missed, limb lag)")

    def test_a_run_with_a_miss_and_no_recorded_cause_is_invalid_for_want_of_a_gate_record(self):
        row = hits_row("static", "staticcrate_hit_by_client")
        text, deviations = self.cell(row, "fix")
        self.assertEqual(text, "1/4")
        self.assertIn("static fix: 3 invalid (swing missed, no gate record x2, client out of band)", deviations)

    def test_a_cause_that_does_not_explain_every_miss_is_not_named(self):
        row = hits_row("static", "staticcrate_hit_by_client", miss_cause={"field": "geometry.limb1Distance", "above": 9.0, "label": "limb lag"})
        self.assertIn("swing missed, no gate record", self.cell(row, "fix")[1][0])

    def test_a_missed_swing_with_every_gate_passed_is_a_fail_listed_apart_from_the_invalid_runs(self):
        with tempfile.TemporaryDirectory() as root:
            shutil.copytree(os.path.join(FIXTURES, "hits"), os.path.join(root, "hits"))
            path = os.path.join(root, "hits", "static_fix_r2.json")
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            for entry in data["measurements"]:
                entry["gate"] = {"passed": True, "failures": [], "values": {}}
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            result = prtable.build_result(hits_profile([hits_row("static", "staticcrate_hit_by_client", sources=["hits/static_fix*.json"])]), root)
        self.assertEqual(result["tables"][0]["rows"][0][2], "1/4")
        self.assertIn("static fix: 1 FAIL (swing 1 missed, every gate passed)", result["deviations"])
        self.assertTrue(result["blocks"][0]["verdict"].startswith("FAIL (1 run FAIL"), result["blocks"][0]["verdict"])

    def test_turning_a_valid_run_invalid_removes_exactly_that_run_from_the_count(self):
        with tempfile.TemporaryDirectory() as root:
            shutil.copytree(os.path.join(FIXTURES, "hits"), os.path.join(root, "hits"))
            path = os.path.join(root, "hits", "crate_fix_r1.json")
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            data["issues"] = ["INVALID: the position preflight failed before the first swing: x"]
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            result = prtable.build_result(hits_profile([hits_row("crate swings", "spawned_crate_hit_by_client")]), root)
        self.assertEqual(result["tables"][0]["rows"][0][2], "1/3")
        self.assertEqual(result["deviations"], ["crate swings fix: 2 invalid (position preflight failed x2)"])

    def test_mining_counts_the_runs_with_the_wanted_verdict_and_a_different_verdict_is_a_fail(self):
        row = {"label": "mining", "scenario": "v2check_dig_cracks", "metric": "verdict_count", "verdict": "persisted", "role": "REGRESSION"}
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
        self.assertIn("mining fix: 1 FAIL (verdict crack-reset)", result["deviations"])

    def test_the_attack_hook_cell_with_named_launch_check_files(self):
        with tempfile.TemporaryDirectory() as root:
            for build, name in ((PLAIN, "plain"), (TIP_FIX, "fix")):
                shutil.copy(os.path.join(FIXTURES, "hits", "launch_checks_%s.json" % name), os.path.join(root, "launch_checks__L1-%s-hook-evidence.json" % build))
            row = {"label": "Body.Attack hook", "metric": "attack_hook", "role": "REGRESSION"}
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
        row = hits_row("PvP", "pvp_banded_by_client", planned_runs=6)
        text, deviations = self.cell(row, "fix")
        self.assertEqual(deviations, ["PvP plain: 5 of 6 runs not run", "PvP fix: 3 of 6 runs not run"])

    def test_a_build_with_no_runs_prints_a_dash_and_no_count(self):
        row = hits_row("PvP", "pvp_banded_by_client")
        result = prtable.build_result(hits_profile([row], builds=[{"label": "other", "build": "no-such-build"}]), FIXTURES)
        self.assertEqual(result["tables"][0]["rows"], [["PvP", "-"]])


class RolesAndVerdictTests(unittest.TestCase):
    def test_a_test_without_a_role_fails_profile_validation(self):
        profile = corpse_profile()
        del profile["tables"][0]["rows"][1]["role"]
        with self.assertRaises(prtable.ProfileError) as caught:
            prtable.validate_profile(profile)
        self.assertIn("Dune/Dune", str(caught.exception))
        with self.assertRaises(prtable.ProfileError):
            prtable.build_result(profile, FIXTURES)

    def test_a_role_that_is_neither_main_nor_regression_fails_validation(self):
        profile = corpse_profile()
        profile["tables"][0]["rows"][0]["role"] = "SMOKE"
        with self.assertRaises(prtable.ProfileError):
            prtable.validate_profile(profile)

    def test_the_main_block_comes_first_then_the_regression_block_each_with_its_own_tables_and_verdict(self):
        result = prtable.build_result(mixed_profile(), FIXTURES)
        self.assertEqual([block["role"] for block in result["blocks"]], ["MAIN", "REGRESSION"])
        self.assertEqual([row[0] for row in result["blocks"][0]["tables"][0]["rows"]], ["Milky/Dune", "Milky/Dune", "Dune/Dune", "Dune/Dune", "Milky/Milky", "Milky/Milky", "Dune/Milky", "Dune/Milky"])
        self.assertEqual([row[0] for row in result["blocks"][1]["tables"][0]["rows"]], ["PvP punches", "crate swings", "static copy", "mining persisted"])
        for block in result["blocks"]:
            self.assertTrue(block["verdict"])

    def test_changing_a_tests_role_in_the_profile_moves_it_between_the_blocks(self):
        profile = mixed_profile()
        profile["tables"][1]["rows"][0]["role"] = "MAIN"
        result = prtable.build_result(profile, FIXTURES)
        main_labels = [row[0] for table in result["blocks"][0]["tables"] for row in table["rows"]]
        regression_labels = [row[0] for table in result["blocks"][1]["tables"] for row in table["rows"]]
        self.assertIn("PvP punches", main_labels)
        self.assertNotIn("PvP punches", regression_labels)
        profile["tables"][1]["rows"][0]["role"] = "REGRESSION"
        for row in profile["tables"][0]["rows"]:
            row["role"] = "REGRESSION"
        result = prtable.build_result(profile, FIXTURES)
        self.assertEqual([block["role"] for block in result["blocks"]], ["REGRESSION"])

    def test_a_table_with_both_roles_is_split_into_both_blocks(self):
        profile = corpse_profile()
        profile["tables"][0]["rows"][3]["role"] = "REGRESSION"
        result = prtable.build_result(profile, FIXTURES)
        self.assertEqual([block["role"] for block in result["blocks"]], ["MAIN", "REGRESSION"])
        self.assertEqual({row[0] for row in result["blocks"][1]["tables"][0]["rows"]}, {"Dune/Milky"})

    def test_the_main_verdict_says_every_valid_run_was_as_expected_and_counts_the_invalid_and_not_run(self):
        profile = corpse_profile()
        for row in profile["tables"][0]["rows"]:
            row["planned_runs"] = 1
        result = prtable.build_result(profile, FIXTURES)
        self.assertEqual(result["blocks"][0]["verdict"], "all 7 valid runs as expected, 1 excluded, 1 not run")

    def test_an_expectation_that_the_valid_runs_do_not_meet_makes_the_block_a_fail(self):
        profile = corpse_profile()
        profile["tables"][0]["rows"][0]["expect"] = {"PR24+fix": {"broke": "never"}}
        result = prtable.build_result(profile, FIXTURES)
        self.assertEqual(result["blocks"][0]["verdict"], "FAIL (expected not met: Milky/Dune PR24+fix broke sw11 not never), 1 excluded")

    def test_the_regression_verdict_fails_when_a_count_that_must_be_all_valid_is_not(self):
        result = prtable.build_result(mixed_profile(), FIXTURES)
        regression = result["blocks"][1]["verdict"]
        self.assertTrue(regression.startswith("all ") or regression.startswith("FAIL"), regression)
        profile = mixed_profile()
        profile["tables"][1]["rows"][2]["expect"] = {"fix": "all"}
        verdict = prtable.build_result(profile, FIXTURES)["blocks"][1]["verdict"]
        self.assertTrue(verdict.startswith("FAIL (expected not met: static copy fix 1 of 4"), verdict)

    def test_the_text_and_markdown_headings_use_the_role_names(self):
        result = prtable.build_result(mixed_profile(), FIXTURES)
        text = prtable.render_text(result).splitlines()
        self.assertIn("MAIN", text)
        self.assertIn("REGRESSION", text)
        self.assertLess(text.index("MAIN"), text.index("REGRESSION"))
        markdown = prtable.render_markdown(result)
        self.assertIn("### Main tests", markdown)
        self.assertIn("### Regression tests", markdown)
        self.assertLess(markdown.index("### Main tests"), markdown.index("### Regression tests"))

    def test_the_shipped_profiles_give_every_test_a_role(self):
        for name in ("corpse-fix.json", "hit-fix.json"):
            with self.subTest(profile=name):
                profile = prtable.load_profile(os.path.join(PROFILES, name))
                roles = {row["role"] for table in profile["tables"] for row in table["rows"]}
                self.assertTrue(roles <= {"MAIN", "REGRESSION"})
        corpse = prtable.load_profile(os.path.join(PROFILES, "corpse-fix.json"))
        main = {row["scenario"] for table in corpse["tables"] for row in table["rows"] if row["role"] == "MAIN"}
        regression = {row.get("scenario") for table in corpse["tables"] for row in table["rows"] if row["role"] == "REGRESSION"}
        self.assertTrue(all(name.startswith("corpse_chain") for name in main))
        self.assertIn("pvp_banded_by_client", regression)


class RegistryTests(unittest.TestCase):
    def test_every_scenario_a_shipped_profile_names_exists_in_the_scenario_registry(self):
        from tests import desync_scenarios
        known = set(desync_scenarios.matching_scenario_names([]))
        for name in ("corpse-fix.json", "hit-fix.json"):
            profile = prtable.load_profile(os.path.join(PROFILES, name))
            for table in profile["tables"]:
                for row in table["rows"]:
                    if row.get("scenario"):
                        self.assertIn(row["scenario"], known, "%s: %s" % (name, row["label"]))

    def test_the_cli_prints_the_fenced_variant_and_both(self):
        import subprocess
        import sys
        tool = os.path.join(os.path.dirname(os.path.dirname(PROFILES)), "tools", "pr_table.py")
        with tempfile.TemporaryDirectory() as folder:
            profile_path = os.path.join(folder, "profile.json")
            with open(profile_path, "w", encoding="utf-8") as handle:
                json.dump(corpse_profile(), handle)
            fenced = subprocess.run([sys.executable, "-I", tool, profile_path, "--format", "fenced", "--root", FIXTURES], capture_output=True)
            both = subprocess.run([sys.executable, "-I", tool, profile_path, "--format", "both", "--root", FIXTURES], capture_output=True)
        self.assertEqual(fenced.returncode, 0, fenced.stderr)
        self.assertTrue(fenced.stdout.startswith(b"```text\n") and fenced.stdout.endswith(b"```\n"))
        self.assertIn(b"### Main tests", both.stdout)
        self.assertIn(b"MAIN\n", both.stdout)
        self.assertNotIn(b"\r", fenced.stdout + both.stdout)


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
        result = prtable.build_result(corpse_profile(params={}), FIXTURES)
        row = [row for row in result["tables"][0]["rows"] if row[:2] == ["Milky/Dune", "PR24"]][0]
        self.assertEqual(row[3], "-366.7 / 200.6")

    def test_only_deviations_are_printed_below_the_tables(self):
        self.assertEqual(self.result["deviations"], ["Milky/Dune PR24: 1 excluded (slow swings 0.42 s)"])


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
        rows = [hits_row("PvP", "pvp_banded_by_client")]
        two = prtable.build_result(hits_profile(rows), FIXTURES)["tables"][0]
        three = prtable.build_result(hits_profile(rows, builds=[{"label": "plain", "build": PLAIN}, {"label": "fix", "build": TIP_FIX}, {"label": "none", "build": "x"}]), FIXTURES)["tables"][0]
        self.assertEqual(two["headers"], ["test", "plain", "fix"])
        self.assertEqual(three["headers"], ["test", "plain", "fix", "none"])
        self.assertEqual(three["rows"][0], ["PvP", "1/1", "3/3", "-"])

    def test_the_header_fields_come_from_the_profile(self):
        profile = corpse_profile(header=[{"id": "game_version"}, {"id": "text", "text": "real rate"}])
        self.assertEqual(prtable.build_result(profile, FIXTURES)["header"], "CORPSE  game 1.0.1  real rate")

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
        self.assertEqual(result["builds"][0][0], "PR24")


UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def table_rows(markdown):
    """The pipe-table lines of a Markdown text split into cells on unescaped pipes."""
    tables, current = [], []
    for line in markdown.splitlines():
        if line.startswith("|"):
            current.append([cell.strip() for cell in UNESCAPED_PIPE.split(line)[1:-1]])
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


class RenderingTests(unittest.TestCase):
    def setUp(self):
        self.result = prtable.build_result(mixed_profile(), FIXTURES)

    def test_the_text_rendering_starts_with_the_header_and_has_aligned_columns(self):
        lines = prtable.render_text(self.result).splitlines()
        self.assertEqual(lines[0], self.result["header"])
        block = lines[lines.index("MAIN") + 1:lines.index("verdict  " + self.result["blocks"][0]["verdict"])]
        self.assertEqual(len(block), 1 + len(self.result["blocks"][0]["tables"][0]["rows"]))
        columns = [line.index("build") if line.startswith("host/client") else line.index("PR24") for line in block]
        self.assertEqual(len(set(columns)), 1)

    def test_both_renderings_carry_every_verdict_and_deviation_and_nothing_else_below_the_tables(self):
        text = prtable.render_text(self.result)
        markdown = prtable.render_markdown(self.result)
        for block in self.result["blocks"]:
            self.assertIn("verdict  " + block["verdict"], text)
            self.assertIn("Verdict: " + prtable.escape_cell(block["verdict"]), markdown)
        for item in self.result["deviations"]:
            self.assertIn(item, text)
            self.assertIn("- " + prtable.escape_cell(item), markdown)

    def test_the_text_output_has_no_narration_words(self):
        text = prtable.render_text(self.result).lower()
        for word in ("guard", "setup", "launched", "cleanup", "restored"):
            self.assertNotIn(word, text)

    def test_the_fenced_variant_wraps_the_same_text_in_one_balanced_code_block(self):
        fenced = prtable.render_fenced(self.result)
        self.assertTrue(fenced.startswith("```text\n"))
        self.assertTrue(fenced.endswith("\n```\n"))
        self.assertEqual(fenced.count("```"), 2)
        self.assertEqual(fenced[len("```text\n"):-len("```\n")], prtable.render_text(self.result))


class GitHubMarkdownTests(unittest.TestCase):
    def setUp(self):
        self.result = prtable.build_result(mixed_profile(), FIXTURES)
        self.markdown = prtable.render_markdown(self.result)

    def test_every_table_row_has_as_many_cells_as_its_header(self):
        tables = table_rows(self.markdown)
        self.assertEqual(len(tables), 2)
        for table in tables:
            self.assertTrue(all(len(row) == len(table[0]) for row in table), table)

    def test_the_separator_row_follows_the_header_and_has_one_dash_cell_per_column(self):
        for table in table_rows(self.markdown):
            self.assertTrue(all(cell == "---" for cell in table[1]), table[1])
            self.assertEqual(len(table[1]), len(table[0]))

    def test_a_pipe_in_a_cell_is_escaped_and_no_cell_holds_an_unescaped_pipe(self):
        result = {"header": "H", "builds": [], "blocks": [{"role": "MAIN", "heading": "Main tests", "verdict": "v", "tables": [{"title": None, "headers": ["a", "b"], "rows": [["x", "p|q"]]}]}], "tables": [], "deviations": []}
        markdown = prtable.render_markdown(result)
        self.assertIn("p\\|q", markdown)
        self.assertEqual(table_rows(markdown), [[["a", "b"], ["---", "---"], ["x", "p\\|q"]]])

    def test_angle_brackets_in_cells_and_lines_are_escaped(self):
        for table in table_rows(self.markdown):
            for row in table:
                for cell in row:
                    self.assertNotRegex(cell, r"(?<!\\)[<>]")
        self.assertIn("-\\>gone", self.markdown)
        self.assertNotRegex(re.sub(r"```.*?```", "", self.markdown, flags=re.S), r"(?<!\\)[<>]")

    def test_there_are_no_tabs_no_trailing_spaces_no_carriage_returns_and_one_final_newline(self):
        self.assertNotIn("\t", self.markdown)
        self.assertNotIn("\r", self.markdown)
        self.assertTrue(self.markdown.endswith("\n") and not self.markdown.endswith("\n\n"))
        for line in self.markdown.splitlines():
            self.assertEqual(line, line.rstrip(), repr(line))

    def test_the_output_is_ascii_without_dashes_emoji_or_box_drawing(self):
        for rendering in (self.markdown, prtable.render_text(self.result), prtable.render_fenced(self.result)):
            rendering.encode("ascii")
            for character in "–—•─│":
                self.assertNotIn(character, rendering)

    def test_the_headings_are_level_three_in_the_order_main_regression_and_deviations_only_when_there_are_any(self):
        headings = [line for line in self.markdown.splitlines() if line.startswith("#")]
        self.assertEqual(headings[:2], ["### Main tests", "### Regression tests"])
        self.assertEqual(headings[2:], ["### Deviations"] if self.result["deviations"] else [])
        clean = prtable.build_result(corpse_profile(params={}, sources=["corpse/milky_pr24.json"]), FIXTURES)
        self.assertNotIn("### Deviations", prtable.render_markdown(clean))

    def test_backticks_surround_only_build_identities(self):
        inline = re.findall(r"`([^`]*)`", self.markdown)
        self.assertTrue(inline)
        for identity in inline:
            self.assertRegex(identity, r"^[0-9a-f]{8}$|^-$")
        self.assertEqual(self.markdown.count("`") % 2, 0)

    def test_there_is_no_html_and_no_blank_line_inside_a_table(self):
        self.assertNotRegex(self.markdown, r"</?[a-zA-Z][^>]*>")
        lines = self.markdown.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("|") and index + 1 < len(lines) and lines[index + 1] == "":
                self.assertTrue(index + 2 >= len(lines) or not lines[index + 2].startswith("|"))

    def test_cell_text_stays_short_enough_for_a_narrow_view(self):
        for table in table_rows(self.markdown):
            for row in table:
                for cell in row:
                    self.assertLessEqual(len(cell), 40, cell)

    def test_the_markdown_matches_the_golden_file(self):
        self.assertEqual(self.markdown, golden("golden_corpse.md"))

    def test_the_text_and_fenced_renderings_match_their_golden_files(self):
        self.assertEqual(prtable.render_text(self.result), golden("golden_corpse.txt"))
        self.assertEqual(prtable.render_fenced(self.result), "```text\n" + golden("golden_corpse.txt") + "```\n")


def golden(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8", newline="") as handle:
        return handle.read()


class RendererTests(unittest.TestCase):
    """The Markdown rendered by a real Markdown library turns the tables into table elements. The libraries are python-markdown (tables extension) and markdown-it-py; GitHub's own
    cmark-gfm is not installed here, so these tests show the pipe tables parse, not that GitHub renders them."""

    def setUp(self):
        self.markdown = prtable.render_markdown(prtable.build_result(mixed_profile(), FIXTURES))

    def test_python_markdown_turns_both_tables_into_table_elements_with_the_right_cell_counts(self):
        try:
            import markdown as python_markdown
        except ImportError:
            self.skipTest("python-markdown is not installed")
        html = python_markdown.markdown(self.markdown, extensions=["tables"])
        self.assertEqual(html.count("<table>"), 2)
        self.assertEqual(html.count("<h3>"), 3)
        for table in re.findall(r"<table>.*?</table>", html, flags=re.S):
            header = len(re.findall(r"<th>", table))
            for row in re.findall(r"<tr>(.*?)</tr>", table, flags=re.S)[1:]:
                self.assertEqual(len(re.findall(r"<td", row)), header)
        self.assertIn("-&gt;gone", html)

    def test_markdown_it_turns_both_tables_into_table_elements_and_keeps_the_escaped_text(self):
        try:
            from markdown_it import MarkdownIt
        except ImportError:
            self.skipTest("markdown-it-py is not installed")
        html = MarkdownIt("commonmark").enable("table").render(self.markdown)
        self.assertEqual(html.count("<table>"), 2)
        self.assertEqual(html.count("<h3>"), 3)
        self.assertNotIn("|---|", html)
        self.assertIn("-&gt;gone", html)

    def test_the_fenced_text_variant_renders_as_one_code_block_and_no_table(self):
        try:
            from markdown_it import MarkdownIt
        except ImportError:
            self.skipTest("markdown-it-py is not installed")
        html = MarkdownIt("commonmark").enable("table").render(prtable.render_fenced(prtable.build_result(mixed_profile(), FIXTURES)))
        self.assertEqual(html.count("<pre>"), 1)
        self.assertEqual(html.count("<table>"), 0)


if __name__ == "__main__":
    unittest.main()
