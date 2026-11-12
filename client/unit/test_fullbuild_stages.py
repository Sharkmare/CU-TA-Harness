import os
import tempfile
import unittest
from unittest import mock

from casualtieslink import desync, instances
from tests import desync_scenarios as scenarios
from tests import test_desync

BUILDS = (("fullbuild-control", "fullbuild-control-stage", instances.FULLBUILD_CONTROL_STAGE_ENVIRONMENT_VARIABLE, "stage_fullbuild_control"),
          ("fullbuild-fixed", "fullbuild-fixed-stage", instances.FULLBUILD_FIXED_STAGE_ENVIRONMENT_VARIABLE, "stage_fullbuild_fixed"),
          ("pr24-control", "pr24-control-stage", instances.PR24_CONTROL_STAGE_ENVIRONMENT_VARIABLE, "stage_pr24_control"),
          ("pr24-fixed", "pr24-fixed-stage", instances.PR24_FIXED_STAGE_ENVIRONMENT_VARIABLE, "stage_pr24_fixed"))
PINNED_MD5 = {"fullbuild-control": "5f44699a7e034bdcbdb8ba66969d04de", "fullbuild-fixed": "2eda43381ed4445d367e27af5edefedb",
              "pr24-control": "f209be8eb9d37eda5a4aafa407deda0f", "pr24-fixed": "aac74832f4e3dd8a2c13d12cba785e3a"}


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

    def test_the_preflight_refuses_each_build_whose_dll_is_missing(self):
        for build, choice, variable, folder in BUILDS:
            with self.subTest(build=build), tempfile.TemporaryDirectory() as empty, mock.patch.dict(os.environ, {variable: empty}):
                problems = scenarios.preflight_problems(["spawned_crate"], 8, [build])
            self.assertEqual(len(problems), 1)
            self.assertIn(build, problems[0])

    def test_the_probe_stays_on_for_both_builds_and_only_the_control_records_the_launch_log_counts(self):
        self.assertNotIn("fullbuild-control", test_desync.BUILDS_WITHOUT_PROBE)
        self.assertNotIn("fullbuild-fixed", test_desync.BUILDS_WITHOUT_PROBE)
        self.assertIn("fullbuild-control", test_desync.RECORD_ONLY_BUILDS)
        self.assertNotIn("fullbuild-fixed", test_desync.RECORD_ONLY_BUILDS)
        self.assertNotIn("pr24-control", test_desync.BUILDS_WITHOUT_PROBE)
        self.assertNotIn("pr24-fixed", test_desync.BUILDS_WITHOUT_PROBE)
        self.assertIn("pr24-control", test_desync.RECORD_ONLY_BUILDS)
        self.assertNotIn("pr24-fixed", test_desync.RECORD_ONLY_BUILDS)

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
