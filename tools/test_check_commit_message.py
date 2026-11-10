import unittest

from tools.check_commit_message import LONG_DASHES, problems


class CommitMessageTests(unittest.TestCase):
    def test_a_plain_short_line_passes(self):
        self.assertEqual(problems("Add the game lock\n"), [])

    def test_a_long_subject_is_refused(self):
        self.assertTrue(problems("Add " + "x" * 80))

    def test_vague_subjects_are_refused(self):
        for subject in ("Update", "fix.", "WIP"):
            self.assertTrue(problems(subject), subject)

    def test_empty_message_is_refused(self):
        self.assertTrue(problems("\n\n# comment only\n"))

    def test_merge_and_fixup_commits_are_refused(self):
        self.assertTrue(problems("Merge branch main"))
        self.assertTrue(problems("fixup! Add the game lock"))

    def test_body_needs_a_blank_line_and_stays_short(self):
        self.assertTrue(problems("Add a thing\nbody right below"))
        self.assertEqual(problems("Add a thing\n\nOne reason line"), [])
        self.assertTrue(problems("Add a thing\n\n" + "\n".join("line %d" % i for i in range(6))))

    def test_long_dashes_are_refused(self):
        for dash in LONG_DASHES:
            self.assertTrue(problems("Add a thing %s and more" % dash))


if __name__ == "__main__":
    unittest.main()
