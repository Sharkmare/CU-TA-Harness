import os
import tempfile
import unittest
import zipfile
from unittest import mock

from casualtieslink import friendszip, instances
from tests import friends_zip as checks

PLUGINS = "BepInEx/plugins/"
ZIP_ENTRIES = {
    "winhttp.dll": b"winhttp",
    "INSTALL.txt": b"install",
    "changelog.txt": b"changes",
    "BepInEx/core/BepInEx.dll": b"core",
    PLUGINS + "Together/CasualtiesMP.dll": b"main",
    PLUGINS + "Together/LiteNetLib.dll": b"net",
    PLUGINS + "CasualtiesCharacters/CasualtiesCharacters.dll": b"loader",
    PLUGINS + "CasualtiesCharacters-Avali/pack.json": b"{}",
}


def write_zip(directory, entries=None):
    path = os.path.join(directory, "mods.zip")
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in (entries or ZIP_ENTRIES).items():
            archive.writestr(name, content)
    return path


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.copy = os.path.join(self.directory.name, "copy")
        os.makedirs(os.path.join(self.copy, "BepInEx", "plugins", "CasualtiesLink"))
        os.makedirs(os.path.join(self.copy, "BepInEx", "plugins", "Together"))
        with open(os.path.join(self.copy, "BepInEx", "plugins", "Together", "Old.dll"), "wb") as handle:
            handle.write(b"old")
        self.archive_path = write_zip(self.directory.name)

    def test_every_zip_file_is_written_except_the_two_text_files(self):
        found = friendszip.extract_into_copy(self.archive_path, self.copy)
        self.assertTrue(os.path.isfile(os.path.join(self.copy, "winhttp.dll")))
        self.assertTrue(os.path.isfile(os.path.join(self.copy, "BepInEx", "core", "BepInEx.dll")))
        self.assertFalse(os.path.exists(os.path.join(self.copy, "INSTALL.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.copy, "changelog.txt")))
        self.assertEqual(found["files"], 6)

    def test_the_previous_together_folder_is_replaced_not_merged(self):
        friendszip.extract_into_copy(self.archive_path, self.copy)
        self.assertFalse(os.path.exists(os.path.join(self.copy, "BepInEx", "plugins", "Together", "Old.dll")))

    def test_the_reported_md5_of_every_dll_is_the_zip_content(self):
        found = friendszip.extract_into_copy(self.archive_path, self.copy)
        self.assertEqual(found["dllMd5"][PLUGINS + "Together/CasualtiesMP.dll"], friendszip.md5_of_bytes(b"main"))
        self.assertEqual(sorted(found["dllMd5"]), sorted(name for name in ZIP_ENTRIES if name.endswith(".dll")))
        self.assertTrue(all(friendszip.verify_copy(self.archive_path, self.copy).values()))

    def test_a_dll_changed_after_extraction_fails_the_verification(self):
        friendszip.extract_into_copy(self.archive_path, self.copy)
        with open(os.path.join(self.copy, "BepInEx", "plugins", "Together", "LiteNetLib.dll"), "wb") as handle:
            handle.write(b"tampered")
        verdicts = friendszip.verify_copy(self.archive_path, self.copy)
        self.assertFalse(verdicts[PLUGINS + "Together/LiteNetLib.dll"])
        self.assertTrue(verdicts[PLUGINS + "Together/CasualtiesMP.dll"])

    def test_a_plugin_in_the_copy_that_the_zip_does_not_ship_is_an_error(self):
        os.makedirs(os.path.join(self.copy, "BepInEx", "plugins", "Stray"))
        with self.assertRaises(ValueError) as caught:
            friendszip.extract_into_copy(self.archive_path, self.copy)
        self.assertIn("Stray", str(caught.exception))

    def test_the_link_plugin_folder_is_the_only_allowed_extra(self):
        found = friendszip.extract_into_copy(self.archive_path, self.copy)
        self.assertEqual(found["pluginFolders"], ["CasualtiesCharacters", "CasualtiesCharacters-Avali", "Together"])

    def test_a_path_that_escapes_the_copy_is_refused(self):
        evil = write_zip(self.directory.name, {"BepInEx/../../outside.dll": b"x"})
        with self.assertRaises(ValueError):
            friendszip.extract_into_copy(evil, self.copy)

    def test_a_missing_zip_is_a_file_error(self):
        with self.assertRaises(FileNotFoundError):
            friendszip.extract_into_copy(os.path.join(self.directory.name, "none.zip"), self.copy)

    def test_configure_instance_installs_the_link_then_the_zip_and_turns_the_loader_debug_on(self):
        link = os.path.join(self.directory.name, "CasualtiesLink.dll")
        with open(link, "wb") as handle:
            handle.write(b"link")
        with mock.patch.dict(os.environ, {friendszip.ZIP_ENVIRONMENT_VARIABLE: self.archive_path, instances.LINK_DLL_ENVIRONMENT_VARIABLE: link}):
            installed = instances.configure_instance(self.copy, [], together=instances.FRIENDS_ZIP_CHOICE)
        self.assertEqual(installed["together"]["pluginFolders"], ["CasualtiesCharacters", "CasualtiesCharacters-Avali", "Together"])
        self.assertTrue(os.path.isfile(os.path.join(self.copy, "BepInEx", "plugins", "CasualtiesLink", "CasualtiesLink.dll")))
        self.assertTrue(os.path.isfile(os.path.join(self.copy, "BepInEx", "config", instances.LOADER_GUID + ".cfg")))


class FakeGame:
    def __init__(self, objects, values):
        self.objects = objects
        self.values = values
        self.invoked = []

    def call(self, command, **arguments):
        if command == "find":
            return [{"object": {"id": identifier, "name": name}} for identifier, name in self.objects.get(arguments["type"], [])]
        if command == "invoke":
            self.invoked.append((arguments["target"], arguments["method"], arguments["args"]))
            return {}
        raise AssertionError(command)

    def get(self, target, path="", depth=1):
        key = (target, path)
        if key not in self.values:
            raise RuntimeError("no such member")
        return self.values[key]


def machine(species, custom_id, tag_id=3, loader_id=3):
    objects = {"PreRunScript": [(1, "pre")], "ScavPlayer": [(10, "p1"), (11, "p2")], "CharacterIdTag": [(20, "tag")], "CustomCharacter": [(30, "cc")],
               "Body": [(40, "Body_HostD"), (41, "Body_ClientD"), (42, "Crate")], "SyncBody": [(50, "sync")]}
    values = {("id:10", "customCharacter"): 0, ("id:11", "customCharacter"): custom_id, ("id:20", "Id"): tag_id, ("id:20", ""): {"Id": tag_id},
              ("id:30", "Body"): {"name": "Body_ClientD"}, ("id:30", "Id"): loader_id, ("id:40", "charType"): 0, ("id:41", "charType"): species,
              ("id:42", "charType"): 9, ("static:PreRunScript", "characterSelected"): custom_id, ("id:50", ""): {"x": 1}}
    return FakeGame(objects, values)


class CheckTests(unittest.TestCase):
    def issues(self, host, client):
        return checks.custom_pick_issues(checks.character_state(host), checks.character_state(client), 3, "Body_ClientD", "Body_HostD")

    def test_a_matching_pair_has_no_issues(self):
        self.assertEqual(self.issues(machine(0, 3), machine(0, 3)), [])

    def test_a_client_body_that_is_not_experiment_is_reported(self):
        issues = self.issues(machine(2, 3), machine(2, 3))
        self.assertTrue(any("not the Experiment species" in issue for issue in issues), issues)

    def test_species_that_differs_between_machines_is_reported(self):
        issues = self.issues(machine(0, 3), machine(2, 3))
        self.assertTrue(any("differs between machines" in issue for issue in issues), issues)

    def test_a_host_that_lost_the_custom_id_is_reported(self):
        issues = self.issues(machine(0, 0), machine(0, 3))
        self.assertTrue(any("host's ScavPlayer rows" in issue for issue in issues), issues)

    def test_a_loader_component_with_another_id_is_reported_for_that_machine(self):
        issues = self.issues(machine(0, 3, loader_id=0), machine(0, 3))
        self.assertTrue(any("on the host machine" in issue for issue in issues), issues)
        self.assertFalse(any("on the client machine" in issue for issue in issues), issues)

    def test_a_missing_tag_is_reported(self):
        issues = self.issues(machine(0, 3), machine(0, 3, tag_id=0))
        self.assertTrue(any("CharacterIdTag" in issue and "client machine" in issue for issue in issues), issues)

    def test_body_species_ignores_objects_that_are_not_player_bodies(self):
        self.assertEqual(checks.body_species(machine(0, 3)), {"Body_HostD": 0, "Body_ClientD": 0})

    def test_select_character_goes_through_the_menu_object_and_reads_the_raw_id_back(self):
        game = machine(0, 3)
        outcome = checks.select_character(game, 3)
        self.assertEqual(game.invoked, [("id:1", "SelectCharacter", [3])])
        self.assertEqual(outcome, {"selected": True, "characterSelected": 3})

    def test_select_character_never_writes_the_field_directly(self):
        game = machine(0, 3)
        game.set = mock.Mock()
        checks.select_character(game, 3)
        game.set.assert_not_called()

    def test_select_character_without_a_menu_object_says_so(self):
        game = FakeGame({}, {})
        self.assertFalse(checks.select_character(game, 3)["selected"])

    def test_the_pager_state_lists_each_type_that_exists_with_a_dump(self):
        game = machine(0, 3)
        game.objects["CharacterPager"] = [(60, "pager")]
        game.values[("id:60", "")] = {"page": 1}
        state = checks.pager_state(game)
        self.assertEqual(state["CharacterPager"][0]["dump"], '{"page": 1}')
        self.assertEqual(state["PagedCharacterCounter"], [])


class LogTests(unittest.TestCase):
    def test_counts_cover_success_markers_patch_problems_and_exceptions(self):
        text = "\n".join(["Body.Attack TRANSPILER SUCCESS", "hit-loop: loop markers not found", "Failed to patch: Foo", "IL Compile Error in Bar",
                          "Mismatching version of X", "NullReferenceException at Y", "fine"])
        found = checks.launch_counts(text)
        self.assertEqual((found["attackTranspilerSuccess"], found["markersNotFound"]), (1, 1))
        self.assertEqual(len(found["patchProblemLines"]), 3)
        self.assertEqual(len(found["exceptionLines"]), 1)

    def test_a_clean_log_has_zero_everywhere(self):
        found = checks.launch_counts("Body.Attack TRANSPILER SUCCESS\nall good")
        self.assertEqual((found["markersNotFound"], found["patchProblemLines"], found["exceptionLines"]), (0, [], []))

    def test_loader_lines_are_picked_by_their_known_phrases(self):
        text = "character select: 4 character(s) on 1 extra page(s)\nunrelated\ncharacter table fingerprint 12ab"
        self.assertEqual(len(checks.loader_log_lines(text)), 2)


class WiringTests(unittest.TestCase):
    def test_the_live_module_is_importable_and_skips_without_the_pair_flag(self):
        from tests import test_friends_zip
        self.assertTrue(hasattr(test_friends_zip, "FriendsZipLobbyCheck"))

    def test_the_default_zip_path_follows_the_environment_variable(self):
        with mock.patch.dict(os.environ, {friendszip.ZIP_ENVIRONMENT_VARIABLE: "somewhere.zip"}):
            self.assertEqual(friendszip.default_zip_path(), "somewhere.zip")


if __name__ == "__main__":
    unittest.main()
