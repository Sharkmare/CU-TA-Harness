import importlib.util
import os
import unittest

TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools", "package_log_check.py")
spec = importlib.util.spec_from_file_location("package_log_check", TOOL)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

GOOD = "[Info   :   BepInEx] Loading [Together 5.5.1]\n[Info   :   BepInEx] Loading [CUCoreLib 1.1]\nversion 1.0.1_MPv5.5.1fork45F0\nBody.Attack TRANSPILER SUCCESS :)\nTRANSPILER SUCCESS other\n"


class CheckTests(unittest.TestCase):
    def report(self, host=GOOD, client=GOOD):
        return {"host": checker.check_log(host), "client": checker.check_log(client)}

    def test_a_clean_pair_of_logs_has_no_problem(self):
        self.assertEqual(checker.problems(self.report()), [])

    def test_a_missing_or_doubled_plugin_a_missing_transpiler_line_and_foreign_strings_are_problems(self):
        bad = GOOD.replace("Loading [CUCoreLib 1.1]", "") + "Loading [Together 5.5.1]\nRESYNCGUARD kept\nSTEAMLIKE delivery on\n"
        found = checker.problems(self.report(client=bad))
        self.assertTrue(any("Together loaded 2 times" in line for line in found))
        self.assertTrue(any("CUCoreLib loaded 0 times" in line for line in found))
        self.assertTrue(any("RESYNCGUARD" in line for line in found))
        self.assertTrue(any("STEAMLIKE" in line for line in found))
        self.assertEqual(len(checker.problems(self.report(client=GOOD.replace("Body.Attack TRANSPILER SUCCESS :)", "")))), 1)

    def test_different_together_load_lines_are_a_problem(self):
        found = checker.problems(self.report(client=GOOD.replace("Together 5.5.1", "Together 5.5.2")))
        self.assertTrue(any("different Together load lines" in line for line in found))

    def test_the_swingburst_lines_are_counted_by_kind(self):
        data = checker.check_log(GOOD + "SWINGBURST accepted-by-credit a\nSWINGBURST accepted-by-credit b\nSWINGBURST dropped c\nSWINGBURST summary d\n")
        self.assertEqual(data["swingBurst"], {"dropped": 1, "acceptedByCredit": 2, "summary": 1})


if __name__ == "__main__":
    unittest.main()
