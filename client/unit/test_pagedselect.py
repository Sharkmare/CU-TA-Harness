import json
import os
import tempfile
import unittest
from unittest import mock

from casualtieslink.charselect import pagedselect


class TestPackTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.template = os.path.join(self.directory.name, "template.json")
        with open(self.template, "w", encoding="utf-8") as handle:
            json.dump({"key": "scout", "base": "experiment", "name": {"en": "Scout"}, "skills": [1]}, handle)
        self.plugins = os.path.join(self.directory.name, "plugins")
        os.makedirs(self.plugins)

    def test_the_pack_has_a_manifest_and_one_file_per_character_with_unique_keys(self):
        keys = pagedselect.write_test_pack(self.plugins, 5, self.template)
        folder = os.path.join(self.plugins, pagedselect.TEST_PACK_FOLDER)
        self.assertEqual(keys, ["tester1", "tester2", "tester3", "tester4", "tester5"])
        self.assertEqual(sorted(os.listdir(os.path.join(folder, "characters"))), [key + ".json" for key in keys])
        self.assertEqual(json.load(open(os.path.join(folder, "pack.json")))["id"], "testpack")

    def test_the_bases_cycle_through_the_three_game_characters(self):
        pagedselect.write_test_pack(self.plugins, 4, self.template)
        folder = os.path.join(self.plugins, pagedselect.TEST_PACK_FOLDER, "characters")
        bases = [json.load(open(os.path.join(folder, "tester%d.json" % number)))["base"] for number in range(1, 5)]
        self.assertEqual(bases, ["experiment", "milky", "dune", "experiment"])

    def test_each_character_gets_its_own_name_and_the_rest_of_the_template(self):
        pagedselect.write_test_pack(self.plugins, 2, self.template)
        folder = os.path.join(self.plugins, pagedselect.TEST_PACK_FOLDER, "characters")
        second = json.load(open(os.path.join(folder, "tester2.json")))
        self.assertEqual((second["name"], second["skills"]), ({"en": "Tester 2"}, [1]))

    def test_zero_characters_is_refused(self):
        with self.assertRaises(ValueError):
            pagedselect.write_test_pack(self.plugins, 0, self.template)

    def test_the_real_template_exists_in_the_mods_tree(self):
        from casualtieslink.games import instances
        self.assertTrue(os.path.isfile(os.path.join(instances.mods_root(), pagedselect.TEMPLATE_RELATIVE)))


class SessionGuardTests(unittest.TestCase):
    def test_a_wrong_zip_md5_stops_before_anything_starts(self):
        with mock.patch.object(pagedselect.friendszip, "md5_of_file", return_value="aaa"), mock.patch.object(pagedselect, "GameProcess") as process:
            with self.assertRaises(ValueError):
                pagedselect.run_session("x", "y", 7650, 1280, 720, 4, "bbb", "z")
        process.assert_not_called()

    def test_a_running_game_stops_the_session(self):
        with mock.patch.object(pagedselect.friendszip, "md5_of_file", return_value="aaa"), mock.patch.object(pagedselect, "running_game_pids", return_value=[5]):
            with self.assertRaises(RuntimeError):
                pagedselect.run_session("x", "y", 7650, 1280, 720, 4, "aaa", "z")

    def test_the_window_arguments_carry_the_size(self):
        self.assertEqual(pagedselect.window_arguments(1280, 800)[-4:], ["-screen-width", "1280", "-screen-height", "800"])


if __name__ == "__main__":
    unittest.main()
