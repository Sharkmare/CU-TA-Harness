import hashlib
import os
import tempfile
import unittest
from unittest import mock

from casualtieslink.scenarioengine import desync
from casualtieslink.games import instances
from scenarios import desync_scenarios as scenarios
from live import test_desync

BUILDS = (("pr24-3d060fe-corpse-fix", "pr24-3d060fe-corpse-fix-stage", instances.PR24_TIP_FIX_STAGE_ENVIRONMENT_VARIABLE, "stage_pr24_3d060fe_corpse_fix"),
          ("pr24-3d060fe-plain", "pr24-3d060fe-plain-stage", instances.PR24_TIP_PLAIN_STAGE_ENVIRONMENT_VARIABLE, "stage_pr24_3d060fe_plain"),
          ("pr24-3d060fe-corpse-fix2", "pr24-3d060fe-corpse-fix2-stage", instances.PR24_TIP_FIX2_STAGE_ENVIRONMENT_VARIABLE, "stage_pr24_3d060fe_corpse_fix2"))
PINNED_MD5 = {"pr24-3d060fe-corpse-fix": "fea4725f5d7466c9ecebbca7553d4740", "pr24-3d060fe-plain": "424f961ea469e10dd697029f04adc367", "pr24-3d060fe-corpse-fix2": "0325037dceac4dbc5ae851315205d76d"}
CUCORELIB_MD5 = "d696c8a1ccce7cb934c85a0e8cb21091"


class SwingBurstPackageTests(unittest.TestCase):
    def test_the_package_build_is_known_record_only_and_needs_cucorelib(self):
        self.assertIn("swingburst-package", desync.KNOWN_BUILDS)
        self.assertIn("swingburst-package", test_desync.RECORD_ONLY_BUILDS)
        self.assertIn("swingburst-package", instances.BUILDS_NEEDING_CUCORELIB)
        self.assertEqual(desync.STAGE_CHOICES["swingburst-package"], instances.SWINGBURST_PACKAGE_STAGE_CHOICE)

    def test_the_directory_is_the_variable_and_has_no_default_folder(self):
        with mock.patch.dict(os.environ, {instances.SWINGBURST_PACKAGE_STAGE_ENVIRONMENT_VARIABLE: "X:/extract/BepInEx"}):
            self.assertEqual(instances.stage_directory_by_build()["swingburst-package"](), "X:/extract/BepInEx")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(instances.SWINGBURST_PACKAGE_STAGE_ENVIRONMENT_VARIABLE, None)
            self.assertIn("UNSET_set_CU_SWINGBURST_PACKAGE_STAGE", instances.stage_directory_by_build()["swingburst-package"]())

    def test_the_package_stage_installs_its_own_together_and_cucorelib_folders(self):
        with tempfile.TemporaryDirectory() as stage, tempfile.TemporaryDirectory() as copy:
            for folder, name in (("Together", "CasualtiesMP.dll"), ("Together", "LiteNetLib.dll"), ("CUCoreLib", "CUCoreLib.dll")):
                os.makedirs(os.path.join(stage, "plugins", folder), exist_ok=True)
                with open(os.path.join(stage, "plugins", folder, name), "w") as handle:
                    handle.write(name)
            with mock.patch.dict(os.environ, {instances.SWINGBURST_PACKAGE_STAGE_ENVIRONMENT_VARIABLE: stage}):
                instances.install_stage_together(copy, instances.swingburst_package_stage_directory())
            self.assertEqual(sorted(os.listdir(os.path.join(copy, "BepInEx", "plugins", "Together"))), ["CasualtiesMP.dll", "LiteNetLib.dll"])
            self.assertEqual(os.listdir(os.path.join(copy, "BepInEx", "plugins", "CUCoreLib")), ["CUCoreLib.dll"])


class StageTests(unittest.TestCase):
    def test_each_build_is_known_and_has_its_own_choice_and_folder(self):
        for build, choice, variable, folder in BUILDS:
            with self.subTest(build=build):
                self.assertEqual(desync.parse_build(build), build)
                self.assertEqual(desync.together_choice(build), choice)
                self.assertIn(build, instances.stage_directory_by_build())
                self.assertTrue(instances.stage_directory_by_build()[build]().replace("\\", "/").endswith("Private CU together/build/" + folder))

    def test_each_stage_is_installed_from_its_environment_override(self):
        for build, choice, variable, folder in BUILDS:
            with self.subTest(build=build), tempfile.TemporaryDirectory() as stage:
                os.makedirs(os.path.join(stage, "plugins", "Together"))
                with open(os.path.join(stage, "plugins", "Together", "CasualtiesMP.dll"), "w") as handle:
                    handle.write(build)
                with tempfile.TemporaryDirectory() as copy, mock.patch.dict(os.environ, {variable: stage}):
                    instances.configure_instance(copy, [], together=choice)
                    with open(os.path.join(copy, "BepInEx", "plugins", "Together", "CasualtiesMP.dll")) as handle:
                        self.assertEqual(handle.read(), build)

    def test_a_stage_with_a_cucorelib_folder_installs_both_plugin_folders_and_one_without_installs_only_together(self):
        with tempfile.TemporaryDirectory() as stage, tempfile.TemporaryDirectory() as copy:
            os.makedirs(os.path.join(stage, "plugins", "Together"))
            os.makedirs(os.path.join(stage, "plugins", "CUCoreLib"))
            for relative in (("Together", "CasualtiesMP.dll"), ("CUCoreLib", "CUCoreLib.dll")):
                with open(os.path.join(stage, "plugins", *relative), "w") as handle:
                    handle.write(relative[0])
            instances.install_stage_together(copy, stage)
            with open(os.path.join(copy, "BepInEx", "plugins", "CUCoreLib", "CUCoreLib.dll")) as handle:
                self.assertEqual(handle.read(), "CUCoreLib")
            self.assertTrue(os.path.isfile(os.path.join(copy, "BepInEx", "plugins", "Together", "CasualtiesMP.dll")))
        with tempfile.TemporaryDirectory() as stage, tempfile.TemporaryDirectory() as copy:
            os.makedirs(os.path.join(stage, "plugins", "Together"))
            with open(os.path.join(stage, "plugins", "Together", "CasualtiesMP.dll"), "w") as handle:
                handle.write("x")
            instances.install_stage_together(copy, stage)
            self.assertFalse(os.path.exists(os.path.join(copy, "BepInEx", "plugins", "CUCoreLib")))

    def test_a_reinstall_replaces_a_stale_cucorelib_folder(self):
        with tempfile.TemporaryDirectory() as stage, tempfile.TemporaryDirectory() as copy:
            os.makedirs(os.path.join(stage, "plugins", "Together"))
            os.makedirs(os.path.join(stage, "plugins", "CUCoreLib"))
            with open(os.path.join(stage, "plugins", "Together", "CasualtiesMP.dll"), "w") as handle:
                handle.write("x")
            with open(os.path.join(stage, "plugins", "CUCoreLib", "CUCoreLib.dll"), "w") as handle:
                handle.write("new")
            stale = os.path.join(copy, "BepInEx", "plugins", "CUCoreLib")
            os.makedirs(stale)
            with open(os.path.join(stale, "old.dll"), "w") as handle:
                handle.write("old")
            instances.install_stage_together(copy, stage)
            self.assertEqual(sorted(os.listdir(stale)), ["CUCoreLib.dll"])

    def test_the_preflight_refuses_a_cucorelib_build_whose_library_is_missing(self):
        for build, variable in (("pr24-3d060fe-corpse-fix", instances.PR24_TIP_FIX_STAGE_ENVIRONMENT_VARIABLE), ("pr24-3d060fe-plain", instances.PR24_TIP_PLAIN_STAGE_ENVIRONMENT_VARIABLE),
                                ("pr24-3d060fe-corpse-fix2", instances.PR24_TIP_FIX2_STAGE_ENVIRONMENT_VARIABLE)):
            with self.subTest(build=build), tempfile.TemporaryDirectory() as stage, mock.patch.dict(os.environ, {variable: stage}):
                os.makedirs(os.path.join(stage, "plugins", "Together"))
                with open(os.path.join(stage, "plugins", "Together", "CasualtiesMP.dll"), "w") as handle:
                    handle.write("x")
                problems = scenarios.preflight_problems(["spawned_crate"], 8, [build])
                if build in instances.BUILDS_NEEDING_CUCORELIB:
                    self.assertEqual(len(problems), 1, problems)
                    self.assertIn("CUCoreLib", problems[0])
                else:
                    self.assertEqual(problems, [])

    def test_the_cucorelib_builds_are_record_only_and_the_library_on_disk_has_the_pinned_md5(self):
        self.assertIn("pr24-3d060fe-corpse-fix", test_desync.RECORD_ONLY_BUILDS)
        self.assertIn("pr24-3d060fe-plain", test_desync.RECORD_ONLY_BUILDS)
        for build in instances.BUILDS_NEEDING_CUCORELIB:
            library = os.path.join(instances.stage_directory_by_build()[build](), "plugins", "CUCoreLib", "CUCoreLib.dll")
            if not os.path.isfile(library):
                self.skipTest("stage not on this machine: " + library)
            with open(library, "rb") as handle:
                self.assertEqual(hashlib.md5(handle.read()).hexdigest(), CUCORELIB_MD5, build)

    def test_the_preflight_refuses_each_build_whose_dll_is_missing(self):
        for build, choice, variable, folder in BUILDS:
            with self.subTest(build=build), tempfile.TemporaryDirectory() as empty, mock.patch.dict(os.environ, {variable: empty}):
                problems = scenarios.preflight_problems(["spawned_crate"], 8, [build])
            self.assertEqual(len(problems), 1)
            self.assertIn(build, problems[0])

    def test_every_staged_build_records_the_launch_log_counts(self):
        for build in desync.STAGE_CHOICES:
            self.assertIn(build, test_desync.RECORD_ONLY_BUILDS, build)

    def test_the_stages_on_disk_have_the_pinned_md5_when_they_are_present(self):
        for build, md5 in PINNED_MD5.items():
            dll = os.path.join(instances.stage_directory_by_build()[build](), "plugins", "Together", "CasualtiesMP.dll")
            if not os.path.isfile(dll):
                self.skipTest("stage not present: %s" % dll)
            import hashlib
            with open(dll, "rb") as handle:
                self.assertEqual(hashlib.md5(handle.read()).hexdigest(), md5, build)


class PatchProblemTests(unittest.TestCase):
    log = "\n".join([
        "[Error  :  Together] Failed to patch: MovementCourse_Start_MultiplayerPatch: Patching exception in method null",
        "[Error  :  Together] Failed to patch: WorldGeneration_SetBlock_MultiplayerPatch: Ambiguous match for HarmonyMethod[(class=WorldGeneration)]",
        "[Error  :  Together] Failed to patch: DamagingCrate_OnCollisionEnter2D_MultiplayerPatch: IL Compile Error (unknown location)",
        "[Info   :  Together] nothing wrong here", ""])

    def test_every_patch_problem_line_is_kept_by_name_per_game(self):
        checks = desync.launch_log_checks(self.log, "[Info] fine\n", expect_no_scatter=False, expect_success=None, record_only=True)
        self.assertEqual(len(checks["hostPatchProblems"]), 3)
        self.assertEqual(checks["clientPatchProblems"], [])
        joined = " ".join(checks["hostPatchProblems"])
        for name in ("MovementCourse_Start", "WorldGeneration_SetBlock", "DamagingCrate_OnCollisionEnter2D"):
            self.assertIn(name, joined)

    def test_a_log_without_problems_has_empty_lists_and_the_old_checks_are_unchanged(self):
        checks = desync.launch_log_checks("Body.Attack TRANSPILER SUCCESS :)\n", "Body.Attack TRANSPILER SUCCESS :)\n", expect_no_scatter=False)
        self.assertEqual((checks["hostPatchProblems"], checks["clientPatchProblems"], checks["issues"]), ([], [], []))

    def test_the_attack_patch_failure_is_still_an_issue_when_a_hook_is_expected(self):
        text = "[Error] Failed to patch: Body_Attack_MultiplayerPatch: IL Compile Error\n"
        checks = desync.launch_log_checks(text, text, expect_no_scatter=False, expect_success=True)
        self.assertTrue(any("Failed to patch: Body_Attack_MultiplayerPatch" in issue for issue in checks["issues"]))
        self.assertEqual(len(checks["hostPatchProblems"]), 1)


if __name__ == "__main__":
    unittest.main()
