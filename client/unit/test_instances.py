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
        instances.configure_instance(self.copy, [], together="keep")
        self.assertEqual(self.read(self.plugin_file("Together", "CasualtiesMP.dll")), "fork mp")

    def test_the_fork_build_comes_from_the_package_zip_and_replaces_the_folder(self):
        package = os.path.join(self.directory.name, "fork.zip")
        make_zip(package, {"BepInEx/plugins/Together/CasualtiesMP.dll": "fork 5.4.1", "BepInEx/plugins/Together/extra.dll": "extra", "INSTALL.txt": "text"})
        with mock.patch.dict(os.environ, {instances.FORK_ZIP_ENVIRONMENT_VARIABLE: package}):
            instances.configure_instance(self.copy, [], together="fork")
        self.assertEqual(self.read(self.plugin_file("Together", "CasualtiesMP.dll")), "fork 5.4.1")
        self.assertTrue(os.path.exists(self.plugin_file("Together", "extra.dll")))
        self.assertFalse(os.path.exists(self.plugin_file("Together", "RefMagic.dll")), "old files must not survive")
        self.assertFalse(os.path.exists(os.path.join(self.copy, "INSTALL.txt")), "only the Together folder is taken from the zip")

    def test_a_fork_zip_without_the_mod_dll_is_an_error(self):
        package = os.path.join(self.directory.name, "bad.zip")
        make_zip(package, {"INSTALL.txt": "text"})
        with mock.patch.dict(os.environ, {instances.FORK_ZIP_ENVIRONMENT_VARIABLE: package}):
            with self.assertRaises(FileNotFoundError):
                instances.configure_instance(self.copy, [], together="fork")

    def flavour_package(self):
        package = os.path.join(self.directory.name, "flavours.zip")
        make_zip(package, {
            "BepInEx/patchers/CT_FlavourSwitch.dll": "switch",
            "BepInEx/together-flavours/fork.manifest": "m",
            "BepInEx/together-flavours/fork/CasualtiesMP.dll": "fork",
            "BepInEx/plugins/Together/CasualtiesMP.dll": "fork",
            "INSTALL.txt": "text",
        })
        return package

    def test_the_flavour_package_installs_patcher_flavours_and_active_build(self):
        os.makedirs(os.path.join(self.copy, "BepInEx", "together-flavours", "old"))
        with mock.patch.dict(os.environ, {instances.FLAVOUR_ZIP_ENVIRONMENT_VARIABLE: self.flavour_package()}):
            instances.configure_instance(self.copy, [], together="flavour:stock-5.5.0")
        self.assertEqual(self.read(os.path.join(self.copy, "BepInEx", "patchers", "CT_FlavourSwitch.dll")), "switch")
        self.assertEqual(self.read(os.path.join(self.copy, "BepInEx", "together-flavours", "fork", "CasualtiesMP.dll")), "fork")
        self.assertEqual(self.read(self.plugin_file("Together", "CasualtiesMP.dll")), "fork")
        self.assertFalse(os.path.exists(os.path.join(self.copy, "BepInEx", "together-flavours", "old")), "stale flavours must go")
        self.assertFalse(os.path.exists(os.path.join(self.copy, "INSTALL.txt")))

    def test_a_flavour_package_without_the_patcher_is_an_error(self):
        package = os.path.join(self.directory.name, "nopatcher.zip")
        make_zip(package, {"BepInEx/plugins/Together/CasualtiesMP.dll": "fork"})
        with mock.patch.dict(os.environ, {instances.FLAVOUR_ZIP_ENVIRONMENT_VARIABLE: package}):
            with self.assertRaises(FileNotFoundError):
                instances.configure_instance(self.copy, [], together="flavour:fork")

    def test_the_launch_option_follows_the_flavour_and_only_then(self):
        self.assertEqual(instances.flavour_arguments("flavour:stock-5.4.0"), ["--mp-flavour", "stock-5.4.0"])
        self.assertEqual(instances.flavour_arguments("stock"), [])
        self.assertEqual(instances.flavour_arguments("fork"), [])

    def test_a_malformed_flavour_name_is_refused(self):
        for bad in ("flavour:", "flavour:Stock 5", "flavour:a/b"):
            with self.assertRaises(ValueError, msg=bad):
                instances.flavour_name(bad)

    def test_the_stage_build_replaces_together_without_the_updater(self):
        stage = os.path.join(self.directory.name, "stage")
        os.makedirs(os.path.join(stage, "plugins", "Together"))
        for name, content in (("CasualtiesMP.dll", "upstream"), ("Multiupdater.dll", "updater"), ("LiteNetLib.dll", "net")):
            with open(os.path.join(stage, "plugins", "Together", name), "w") as handle:
                handle.write(content)
        with mock.patch.dict(os.environ, {instances.STAGE_ENVIRONMENT_VARIABLE: stage}):
            instances.configure_instance(self.copy, [], together="stage")
        self.assertEqual(self.read(self.plugin_file("Together", "CasualtiesMP.dll")), "upstream")
        self.assertFalse(os.path.exists(self.plugin_file("Together", "Multiupdater.dll")))
        self.assertFalse(os.path.exists(self.plugin_file("Together", "RefMagic.dll")), "old files must not survive")

    def test_a_stage_without_the_mod_dll_is_an_error(self):
        with mock.patch.dict(os.environ, {instances.STAGE_ENVIRONMENT_VARIABLE: self.directory.name}):
            with self.assertRaises(FileNotFoundError):
                instances.configure_instance(self.copy, [], together="stage")

    def test_a_non_flavour_build_removes_the_switch_that_an_earlier_flavour_left(self):
        with mock.patch.dict(os.environ, {instances.FLAVOUR_ZIP_ENVIRONMENT_VARIABLE: self.flavour_package()}):
            instances.configure_instance(self.copy, [], together="flavour:fork")
        instances.configure_instance(self.copy, [], together="stock")
        self.assertFalse(os.path.exists(os.path.join(self.copy, "BepInEx", "patchers", "CT_FlavourSwitch.dll")))
        self.assertFalse(os.path.exists(os.path.join(self.copy, "BepInEx", "together-flavours")))

    def test_the_client_connects_to_the_given_address_and_the_host_to_the_session_address(self):
        self.assertIn("127.0.0.1:7791", instances.client_arguments(address="127.0.0.1:7791"))
        self.assertIn(instances.SESSION_ADDRESS, instances.client_arguments())
        self.assertIn(instances.SESSION_ADDRESS, instances.host_arguments())

    def test_the_diag_stage_build_is_installed_from_its_own_folder(self):
        stage = os.path.join(self.directory.name, "diag")
        os.makedirs(os.path.join(stage, "plugins", "Together"))
        with open(os.path.join(stage, "plugins", "Together", "CasualtiesMP.dll"), "w") as handle:
            handle.write("diag build")
        with mock.patch.dict(os.environ, {instances.DIAG_STAGE_ENVIRONMENT_VARIABLE: stage}):
            instances.configure_instance(self.copy, [], together="diag-stage")
        self.assertEqual(self.read(self.plugin_file("Together", "CasualtiesMP.dll")), "diag build")

    def test_the_probe_config_turns_the_evidence_loggers_on_and_is_cleared_for_the_next_launch(self):
        instances.write_probe_config(self.copy)
        config = os.path.join(self.copy, "BepInEx", "config", instances.TOGETHER_CONFIG_NAME)
        self.assertIn("FindTheBug = true", self.read(config))
        instances.configure_instance(self.copy, [], together="keep")
        self.assertFalse(os.path.exists(config))

    def test_the_second_diag_stage_has_its_own_folder_and_build_name(self):
        from casualtieslink import desync
        stage = os.path.join(self.directory.name, "diag2")
        os.makedirs(os.path.join(stage, "plugins", "Together"))
        with open(os.path.join(stage, "plugins", "Together", "CasualtiesMP.dll"), "w") as handle:
            handle.write("diag two")
        with mock.patch.dict(os.environ, {instances.DIAG_STAGE2_ENVIRONMENT_VARIABLE: stage}):
            instances.configure_instance(self.copy, [], together=desync.together_choice("upstream-diag2"))
        self.assertEqual(self.read(self.plugin_file("Together", "CasualtiesMP.dll")), "diag two")
        self.assertIn("upstream-diag2", desync.DIAG_BUILDS)

    def test_the_third_diag_stage_has_its_own_folder_and_build_name(self):
        from casualtieslink import desync
        stage = os.path.join(self.directory.name, "diag3")
        os.makedirs(os.path.join(stage, "plugins", "Together"))
        with open(os.path.join(stage, "plugins", "Together", "CasualtiesMP.dll"), "w") as handle:
            handle.write("diag three")
        with mock.patch.dict(os.environ, {instances.DIAG_STAGE3_ENVIRONMENT_VARIABLE: stage}):
            instances.configure_instance(self.copy, [], together=desync.together_choice("upstream-diag3"))
        self.assertEqual(self.read(self.plugin_file("Together", "CasualtiesMP.dll")), "diag three")
        self.assertIn("upstream-diag3", desync.DIAG_BUILDS)

    def test_the_diag_choice_follows_the_build_name(self):
        from casualtieslink import desync
        self.assertEqual(desync.together_choice("upstream-diag"), "diag-stage")
        self.assertEqual(desync.together_choice("upstream-fixes"), "stage")
        self.assertEqual(desync.parse_build("upstream-diag"), "upstream-diag")

    def test_an_unknown_together_choice_is_refused(self):
        with self.assertRaises(ValueError):
            instances.configure_instance(self.copy, [], together="newest")

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
