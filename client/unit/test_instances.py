import os
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest import mock

from casualtieslink import instances


def touch(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def make_zip(path, files):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)


class InstanceFixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        base = self.directory.name
        self.mods = os.path.join(base, "mods")
        self.stock = os.path.join(base, "backup", "Together_5.4.0_original")
        self.copy = os.path.join(base, "copy")
        touch(os.path.join(self.mods, "size-mod", "bin", "CasualtiesSize.dll"), "size dll")
        make_zip(os.path.join(self.mods, "CU Characters", "dist", "CasualtiesCharacters-0.2.0.zip"),
                 {"BepInEx/plugins/CasualtiesCharacters/CasualtiesCharacters.dll": "loader 0.2.0"})
        make_zip(os.path.join(self.mods, "CU Characters", "dist", "CasualtiesCharacters-0.2.0.previous-abc.zip"),
                 {"BepInEx/plugins/CasualtiesCharacters/CasualtiesCharacters.dll": "old loader"})
        make_zip(os.path.join(self.mods, "CU Characters", "dist", "CasualtiesCharacters-0.3.0.zip"),
                 {"BepInEx/plugins/CasualtiesCharacters/CasualtiesCharacters.dll": "loader 0.3.0"})
        make_zip(os.path.join(self.mods, "CU Character Avali", "dist", "CasualtiesCharacters-Avali-1.0.0.zip"),
                 {"BepInEx/plugins/CasualtiesCharacters-Avali/pack.json": "avali"})
        touch(os.path.join(self.mods, "CU Characters", "tests", "fixtures", "samplepack", "pack.json"), "sample")
        touch(os.path.join(self.stock, "CasualtiesMP.dll"), "stock mp")
        touch(os.path.join(self.stock, "Multiupdater.dll"), "updater")
        touch(os.path.join(self.stock, "LiteNetLib.dll"), "stock lite")
        plugins = os.path.join(self.copy, "BepInEx", "plugins")
        touch(os.path.join(plugins, "Together", "CasualtiesMP.dll"), "fork mp")
        touch(os.path.join(plugins, "Together", "RefMagic.dll"), "fork only")
        touch(os.path.join(plugins, "CasualtiesLink", "CasualtiesLink.dll"), "link")
        touch(os.path.join(plugins, "CasualtiesSize", "CasualtiesSize.dll"), "leftover size")
        self.fresh_link = os.path.join(base, "built", "CasualtiesLink.dll")
        touch(self.fresh_link, "fresh link")
        self.environment = mock.patch.dict(os.environ, {instances.MODS_ROOT_ENVIRONMENT_VARIABLE: self.mods,
                                                       instances.STOCK_DIR_ENVIRONMENT_VARIABLE: self.stock,
                                                       instances.LINK_DLL_ENVIRONMENT_VARIABLE: self.fresh_link})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(self.directory.cleanup)

    def plugin_file(self, *parts):
        return os.path.join(self.copy, "BepInEx", "plugins", *parts)

    def read(self, path):
        with open(path) as handle:
            return handle.read()


class ConfigureInstanceTests(InstanceFixture):
    def test_stock_together_replaces_the_fork_folder_without_the_updater(self):
        instances.configure_instance(self.copy, [])
        self.assertEqual(self.read(self.plugin_file("Together", "CasualtiesMP.dll")), "stock mp")
        self.assertTrue(os.path.exists(self.plugin_file("Together", "LiteNetLib.dll")))
        self.assertFalse(os.path.exists(self.plugin_file("Together", "Multiupdater.dll")))
        self.assertFalse(os.path.exists(self.plugin_file("Together", "RefMagic.dll")), "fork only files must not survive")

    def test_together_is_left_alone_when_stock_is_not_asked_for(self):
        instances.configure_instance(self.copy, [], stock_together=False)
        self.assertEqual(self.read(self.plugin_file("Together", "CasualtiesMP.dll")), "fork mp")

    def test_the_link_plugin_is_replaced_by_the_freshly_built_one(self):
        instances.configure_instance(self.copy, ["size", "loader"])
        self.assertEqual(self.read(self.plugin_file("CasualtiesLink", "CasualtiesLink.dll")), "fresh link")

    def test_a_missing_built_link_plugin_is_an_error_that_says_how_to_build_it(self):
        os.remove(self.fresh_link)
        with self.assertRaises(FileNotFoundError) as caught:
            instances.configure_instance(self.copy, [])
        self.assertIn("dotnet build", str(caught.exception))

    def test_leftover_managed_plugins_are_removed_before_the_new_set_is_installed(self):
        instances.configure_instance(self.copy, [])
        self.assertFalse(os.path.exists(self.plugin_file("CasualtiesSize")))

    def test_each_plugin_set_installs_its_files(self):
        instances.configure_instance(self.copy, ["size", "loader", "avali", "samplepack"])
        self.assertEqual(self.read(self.plugin_file("CasualtiesSize", "CasualtiesSize.dll")), "size dll")
        self.assertEqual(self.read(self.plugin_file("CasualtiesCharacters", "CasualtiesCharacters.dll")), "loader 0.3.0")
        self.assertEqual(self.read(self.plugin_file("CasualtiesCharacters-Avali", "pack.json")), "avali")
        self.assertEqual(self.read(self.plugin_file("CasualtiesCharacters-Sample", "pack.json")), "sample")

    def test_the_newest_release_zip_is_used_and_previous_ones_are_ignored(self):
        chosen = instances.latest_zip(os.path.join(self.mods, "CU Characters", "dist"), "CasualtiesCharacters-0")
        self.assertTrue(chosen.endswith("CasualtiesCharacters-0.3.0.zip"))

    def test_a_missing_release_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            instances.latest_zip(os.path.join(self.mods, "nothing"), "x")

    def test_switching_scenarios_leaves_only_the_requested_plugins(self):
        instances.configure_instance(self.copy, ["size", "loader", "avali"])
        instances.configure_instance(self.copy, ["loader", "samplepack"])
        self.assertFalse(os.path.exists(self.plugin_file("CasualtiesSize")))
        self.assertFalse(os.path.exists(self.plugin_file("CasualtiesCharacters-Avali")))
        self.assertTrue(os.path.exists(self.plugin_file("CasualtiesCharacters-Sample")))

    def test_debug_logging_is_switched_on_only_for_installed_plugins_and_cleared_afterwards(self):
        config = lambda guid: os.path.join(self.copy, "BepInEx", "config", guid + ".cfg")
        instances.configure_instance(self.copy, ["size"])
        self.assertIn("Enabled = true", self.read(config(instances.SIZE_GUID)))
        self.assertFalse(os.path.exists(config(instances.LOADER_GUID)))
        instances.configure_instance(self.copy, [])
        self.assertFalse(os.path.exists(config(instances.SIZE_GUID)))

    def test_debug_can_be_left_off(self):
        instances.configure_instance(self.copy, ["size"], debug=False)
        self.assertFalse(os.path.exists(os.path.join(self.copy, "BepInEx", "config", instances.SIZE_GUID + ".cfg")))

    def test_an_unknown_plugin_set_is_refused_before_anything_changes(self):
        with self.assertRaises(ValueError):
            instances.configure_instance(self.copy, ["size", "mystery"])
        self.assertEqual(self.read(self.plugin_file("Together", "CasualtiesMP.dll")), "fork mp")

    def test_a_stock_folder_without_the_mod_dll_is_an_error(self):
        os.remove(os.path.join(self.stock, "CasualtiesMP.dll"))
        with self.assertRaises(FileNotFoundError):
            instances.configure_instance(self.copy, [])

    def test_the_stock_folder_can_come_from_the_dll_variable(self):
        with mock.patch.dict(os.environ, {instances.STOCK_DLL_ENVIRONMENT_VARIABLE: os.path.join(self.stock, "CasualtiesMP.dll")}):
            os.environ.pop(instances.STOCK_DIR_ENVIRONMENT_VARIABLE)
            self.assertEqual(instances.stock_together_dir(), self.stock)


class MpEnabledTests(unittest.TestCase):
    def fake_run(self, output):
        calls = []

        def run(command, **options):
            calls.append(command)
            return SimpleNamespace(stdout=output)
        return run, calls

    def test_a_persisted_disable_flag_is_set_back_to_zero(self):
        run, calls = self.fake_run("    CasualtiesMP_FORCE_DISABLE_MP_MOD_h1046402504    REG_DWORD    0x1\r\n    other_h5    REG_DWORD    0x1\r\n")
        self.assertEqual(instances.ensure_mp_enabled(run), ["CasualtiesMP_FORCE_DISABLE_MP_MOD_h1046402504"])
        self.assertEqual(calls[1][:4], ["reg", "add", instances.PREFS_REGISTRY_KEY, "/v"])
        self.assertIn("0", calls[1])

    def test_an_already_enabled_flag_is_left_alone(self):
        run, calls = self.fake_run("    CasualtiesMP_FORCE_DISABLE_MP_MOD_h1046402504    REG_DWORD    0x0\r\n")
        self.assertEqual(instances.ensure_mp_enabled(run), [])
        self.assertEqual(len(calls), 1)


class ArgumentTests(unittest.TestCase):
    def test_host_and_client_use_direct_ip_without_steam_and_no_fork_flags(self):
        host, client = instances.host_arguments(), instances.client_arguments()
        for arguments in (host, client):
            self.assertIn("--mp-nosteam", arguments)
            self.assertIn(instances.SESSION_ADDRESS, arguments)
            self.assertNotIn("--mp-debug", arguments)
            self.assertNotIn("--mp-enable", arguments)
        self.assertIn("--mp-starthost", host)
        self.assertIn("--mp-immidiate-start", host)
        self.assertIn("--mp-startclient", client)
        self.assertNotIn("--mp-starthost", client)

    def test_extra_arguments_are_appended(self):
        self.assertEqual(instances.client_arguments(["--x"])[-1], "--x")


if __name__ == "__main__":
    unittest.main()
