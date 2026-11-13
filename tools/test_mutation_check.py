import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from tools import mutation_check

PASSING_COMMAND = [sys.executable, "-c", "raise SystemExit(0)"]
FAILING_COMMAND = [sys.executable, "-c", "raise SystemExit(1)"]
ONE_MUTANT = [{"suite": "python", "file": "x.py", "old": "a", "new": "b", "label": "one"}]


class ControlRunTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.mutants_path = os.path.join(self.directory.name, "mutants.json")
        with open(self.mutants_path, "w", encoding="utf-8") as handle:
            json.dump(ONE_MUTANT, handle)

    def run_main(self, suite_command, judged):
        patches = [
            mock.patch.object(mutation_check, "MUTANTS_PATH", self.mutants_path),
            mock.patch.object(mutation_check, "copy_tree", lambda root: None),
            mock.patch.object(mutation_check, "suite_command", lambda suite, root: (suite_command, self.directory.name)),
            mock.patch.object(mutation_check, "run_mutant", judged),
        ]
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = mutation_check.main(["--suite", "python"])
        return code, output.getvalue()

    def test_a_failing_control_stops_before_any_mutant_is_judged(self):
        def never(scratch, index, mutant):
            raise AssertionError("a mutant was judged although the control failed")
        code, output = self.run_main(FAILING_COMMAND, never)
        self.assertEqual(code, 2)
        self.assertIn("CONTROL FAILED", output)

    def test_a_passing_control_lets_the_mutants_be_judged(self):
        code, output = self.run_main(PASSING_COMMAND, lambda scratch, index, mutant: ("caught", ""))
        self.assertEqual(code, 0)
        self.assertIn("1 of 1 mutants caught", output)

    def test_only_the_client_report_output_folder_is_left_out_of_the_copy(self):
        self.assertEqual(mutation_check.ignored_names(os.path.join("x", "client"), ["reports", "casualtieslink"]), {"reports"})
        self.assertEqual(mutation_check.ignored_names(os.path.join("x", "client", "casualtieslink"), ["reports", "games"]), set())

    def test_the_suite_gets_the_mods_root_of_the_real_repository(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(mutation_check.MODS_ROOT_ENVIRONMENT_VARIABLE, None)
            environment = mutation_check.suite_environment()
        self.assertEqual(environment[mutation_check.MODS_ROOT_ENVIRONMENT_VARIABLE], os.path.dirname(mutation_check.REPO))

    def test_the_suite_gets_the_link_plugin_built_in_the_real_repository(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(mutation_check.LINK_DLL_ENVIRONMENT_VARIABLE, None)
            environment = mutation_check.suite_environment()
        self.assertEqual(environment[mutation_check.LINK_DLL_ENVIRONMENT_VARIABLE], mutation_check.BUILT_LINK_DLL)


class MutantListTests(unittest.TestCase):
    def test_every_mutant_names_an_existing_file_and_an_anchor_that_occurs_once(self):
        with open(mutation_check.MUTANTS_PATH, encoding="utf-8") as handle:
            mutants = json.load(handle)
        problems = []
        for mutant in mutants:
            path = os.path.join(mutation_check.REPO, mutant["file"])
            if not os.path.isfile(path):
                problems.append("%s: no such file %s" % (mutant["label"], mutant["file"]))
                continue
            with open(path, encoding="utf-8") as handle:
                count = handle.read().replace("\r\n", "\n").count(mutant["old"])
            if count != 1:
                problems.append("%s: anchor found %d times in %s" % (mutant["label"], count, mutant["file"]))
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
