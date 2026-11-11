import hashlib
import os
import re
import tempfile
import unittest
import zipfile
from unittest import mock

from casualtieslink import desync, instances, officialstage
from tests import desync_scenarios as scenarios
from tests import test_desync

STOCK_SOURCE = os.path.join(os.path.dirname(instances.mods_root()), "mods", "casualties-together-local", "tools", "stock_source.py")


def make_zip(directory, entries):
    path = os.path.join(directory, "release.zip")
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    with open(path, "rb") as handle:
        return path, hashlib.sha256(handle.read()).hexdigest()


PREFIX = officialstage.PLUGIN_PREFIX


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path, self.digest = make_zip(self.directory.name, {
            PREFIX + "CasualtiesMP.dll": b"main", PREFIX + "LiteNetLib.dll": b"net", PREFIX + "Multiupdater.dll": b"updater",
            "mod/BepInEx/patchers/CT_AutoUpdateApplier.dll": b"patcher", "CHANGELOG.txt": b"log"})
        self.destination = os.path.join(self.directory.name, "stage")

    def test_only_the_plugin_files_are_written_and_the_self_updater_is_left_out(self):
        written = officialstage.extract_official_stage(self.path, self.destination, self.digest)
        self.assertEqual(sorted(written), ["CasualtiesMP.dll", "LiteNetLib.dll"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.destination, "plugins", "Together"))), ["CasualtiesMP.dll", "LiteNetLib.dll"])
        self.assertEqual(written["CasualtiesMP.dll"], hashlib.sha256(b"main").hexdigest())

    def test_a_zip_with_the_wrong_hash_is_refused_before_anything_is_written(self):
        with self.assertRaises(ValueError) as caught:
            officialstage.extract_official_stage(self.path, self.destination, "0" * 64)
        self.assertIn("expected", str(caught.exception))
        self.assertFalse(os.path.exists(self.destination))

    def test_a_missing_zip_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            officialstage.extract_official_stage(os.path.join(self.directory.name, "none.zip"), self.destination, self.digest)

    def test_a_stage_folder_that_already_has_files_is_not_overwritten(self):
        officialstage.extract_official_stage(self.path, self.destination, self.digest)
        with self.assertRaises(FileExistsError):
            officialstage.extract_official_stage(self.path, self.destination, self.digest)

    def test_a_path_that_climbs_out_of_the_plugin_folder_is_refused(self):
        path, digest = make_zip(self.directory.name + "", {PREFIX + "CasualtiesMP.dll": b"main", PREFIX + "../evil.dll": b"x"})
        with self.assertRaises(ValueError):
            officialstage.extract_official_stage(path, os.path.join(self.directory.name, "stage2"), digest)

    def test_a_zip_without_the_main_dll_is_refused(self):
        path, digest = make_zip(self.directory.name, {PREFIX + "LiteNetLib.dll": b"net"})
        with self.assertRaises(ValueError) as caught:
            officialstage.extract_official_stage(path, os.path.join(self.directory.name, "stage3"), digest)
        self.assertIn("CasualtiesMP.dll", str(caught.exception))


class PinTests(unittest.TestCase):
    def test_the_pinned_hash_is_the_one_in_the_stock_source_table(self):
        if not os.path.isfile(STOCK_SOURCE):
            self.skipTest("stock_source.py not found")
        with open(STOCK_SOURCE, encoding="utf-8") as handle:
            text = handle.read()
        self.assertRegex(text, r'StockSource\("5\.5\.0", "%s",\s*"%s"' % (re.escape(officialstage.OFFICIAL_ZIP_NAME), officialstage.OFFICIAL_ZIP_SHA256))

    def test_the_pinned_hash_matches_the_release_zip_when_it_is_present(self):
        path = officialstage.default_zip_path()
        if not os.path.isfile(path):
            self.skipTest("release zip not found: %s" % path)
        self.assertEqual(officialstage.sha256_of_file(path), officialstage.OFFICIAL_ZIP_SHA256)

    def test_the_default_zip_path_can_be_overridden_by_the_environment(self):
        with mock.patch.dict(os.environ, {officialstage.ZIP_ENVIRONMENT_VARIABLE: "somewhere.zip"}):
            self.assertEqual(officialstage.default_zip_path(), "somewhere.zip")


class BuildTests(unittest.TestCase):
    def test_the_official_build_is_a_known_stage_build_with_its_own_choice_and_folder(self):
        self.assertEqual(desync.parse_build("official-5.5.0"), "official-5.5.0")
        self.assertEqual(desync.together_choice("official-5.5.0"), "official-stage")
        self.assertIn("official-5.5.0", instances.stage_directory_by_build())
        self.assertTrue(instances.official_stage_directory().replace("\\", "/").endswith(".state/stages/official-5.5.0"))

    def test_the_official_stage_is_installed_without_the_self_updater(self):
        with tempfile.TemporaryDirectory() as stage:
            folder = os.path.join(stage, "plugins", "Together")
            os.makedirs(folder)
            for name in ("CasualtiesMP.dll", "Multiupdater.dll"):
                with open(os.path.join(folder, name), "w") as handle:
                    handle.write(name)
            with tempfile.TemporaryDirectory() as copy, mock.patch.dict(os.environ, {instances.OFFICIAL_STAGE_ENVIRONMENT_VARIABLE: stage}):
                instances.configure_instance(copy, [], together="official-stage")
                installed = os.listdir(os.path.join(copy, "BepInEx", "plugins", "Together"))
        self.assertEqual(installed, ["CasualtiesMP.dll"])

    def test_the_official_build_runs_without_our_probe_and_only_records_the_launch_log_counts(self):
        self.assertIn("official-5.5.0", test_desync.BUILDS_WITHOUT_PROBE)
        self.assertTrue(test_desync.BUILD_HAS_PROBE)
        self.assertFalse(test_desync.RECORD_ONLY_LAUNCH_CHECKS)

    def test_the_preflight_refuses_the_official_build_when_its_stage_is_missing(self):
        with tempfile.TemporaryDirectory() as empty, mock.patch.dict(os.environ, {instances.OFFICIAL_STAGE_ENVIRONMENT_VARIABLE: empty}):
            problems = scenarios.preflight_problems(["spawned_crate"], 8, ["official-5.5.0"])
        self.assertEqual(len(problems), 1)
        self.assertIn("official-5.5.0", problems[0])


class LaunchLogTests(unittest.TestCase):
    official_success = "[Info   :  Together] TRANSPILER: Body.Attack TRANSPILER SUCCESS :) \n"
    official_markers = "[Warning:  Together] Body.Attack TRANSPILER: hit-loop markers not found, leaving stock IL\n"

    def test_both_official_lines_are_counted_per_game_and_nothing_is_flagged_when_recording_only(self):
        checks = desync.launch_log_checks(self.official_success, self.official_markers + self.official_markers, expect_no_scatter=False, expect_success=None, record_only=True)
        self.assertEqual((checks["hostTranspilerSuccess"], checks["hostMarkersNotFound"], checks["clientTranspilerSuccess"], checks["clientMarkersNotFound"]), (1, 0, 0, 2))
        self.assertEqual(checks["issues"], [])
        self.assertTrue(checks["recordOnly"])

    def test_the_same_logs_are_issues_when_a_hook_is_expected(self):
        checks = desync.launch_log_checks(self.official_success, self.official_markers, expect_no_scatter=False, expect_success=True)
        self.assertTrue(any("no 'Body.Attack TRANSPILER SUCCESS'" in issue for issue in checks["issues"]))
        self.assertTrue(any("loop markers not found" in issue for issue in checks["issues"]))
        self.assertFalse(checks["recordOnly"])

    def test_the_official_warning_text_contains_the_marker_the_counter_searches_for(self):
        self.assertIn(desync.TRANSPILER_MISSING_MARKERS, self.official_markers)
        self.assertIn(desync.TRANSPILER_SUCCESS, self.official_success)


class ReadyUpTests(unittest.TestCase):
    def test_the_character_is_chosen_right_before_every_ready_attempt_of_that_game_only(self):
        host, client = mock.Mock(name="host"), mock.Mock(name="client")
        order = []
        attempts = {"count": 0}

        def try_ready(game):
            order.append(("ready", game))
            attempts["count"] += 1
            return attempts["count"] < 3

        with mock.patch.object(scenarios, "try_ready", try_ready), mock.patch.object(scenarios.time, "sleep", lambda seconds: None):
            done = scenarios.ready_up([host, client], before_ready={client: lambda game: order.append(("choose", game))})
        self.assertTrue(done)
        self.assertEqual(order[0], ("choose", client))
        self.assertEqual(order[1], ("ready", host))
        self.assertEqual(order[2], ("ready", client))
        self.assertTrue(all(entry[1] is client for entry in order if entry[0] == "choose"))
        self.assertGreaterEqual(len([entry for entry in order if entry[0] == "choose"]), 1)

    def test_without_a_chooser_ready_up_behaves_as_before(self):
        game = mock.Mock()
        with mock.patch.object(scenarios, "try_ready", lambda g: True), mock.patch.object(scenarios.time, "sleep", lambda seconds: None):
            self.assertTrue(scenarios.ready_up([game]))


if __name__ == "__main__":
    unittest.main()
