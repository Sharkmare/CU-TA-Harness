import os
import tempfile
import unittest
import zipfile
from unittest import mock

from casualtieslink.games import buildregistry, instances

REGISTRY = {
    "default": "example-flavour",
    "builds": {
        "example-flavour": {"kind": "flavour"},
        "example-stage": {"kind": "stage", "directory_env": "CU_EXAMPLE_STAGE", "directory": "builds/example/stage", "library_folders": ["ExampleLib"]},
        "example-python": {"kind": "python", "install": "unit.test_instances:install_example_build"},
    },
    "plugin_sets": {
        "example-dll": {"kind": "dll", "source": "example/bin/Example.dll", "folder": "Example", "debug_guid": "example.guid"},
        "example-dir": {"kind": "directory", "source": "example/fixtures/pack", "folder": "ExamplePack"},
        "example-zip": {"kind": "release-zip", "directory": "example/dist", "prefix": "Example-0", "folder": "ExampleLoaded"},
    },
    "probe_config": {"file": "Probe.cfg", "text": "[Probe]\n"},
}


def install_example_build(copy, debug):
    with open(os.path.join(copy, "python-build.txt"), "w") as handle:
        handle.write("debug" if debug else "plain")
    return "python-build"


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
        self.stock = os.path.join(base, "stock")
        self.copy = os.path.join(base, "copy")
        touch(os.path.join(self.mods, "example", "bin", "Example.dll"), "dll set")
        touch(os.path.join(self.mods, "example", "fixtures", "pack", "pack.json"), "directory set")
        make_zip(os.path.join(self.mods, "example", "dist", "Example-0.2.0.zip"), {"BepInEx/plugins/ExampleLoaded/a.dll": "release 0.2.0"})
        make_zip(os.path.join(self.mods, "example", "dist", "Example-0.2.0.previous-abc.zip"), {"BepInEx/plugins/ExampleLoaded/a.dll": "previous"})
        make_zip(os.path.join(self.mods, "example", "dist", "Example-0.3.0.zip"), {"BepInEx/plugins/ExampleLoaded/a.dll": "release 0.3.0"})
        touch(os.path.join(self.stock, "CasualtiesMP.dll"), "stock mp")
        touch(os.path.join(self.stock, "Multiupdater.dll"), "updater")
        plugins = os.path.join(self.copy, "BepInEx", "plugins")
        touch(os.path.join(plugins, "Together", "CasualtiesMP.dll"), "old mp")
        touch(os.path.join(plugins, "Together", "OldOnly.dll"), "old only")
        touch(os.path.join(plugins, "Example", "Example.dll"), "leftover")
        self.fresh_link = os.path.join(base, "built", "CasualtiesLink.dll")
        touch(self.fresh_link, "fresh link")
        self.environment = mock.patch.dict(os.environ, {buildregistry.MODS_ROOT_ENVIRONMENT_VARIABLE: self.mods, instances.STOCK_DIR_ENVIRONMENT_VARIABLE: self.stock,
                                                       instances.LINK_DLL_ENVIRONMENT_VARIABLE: self.fresh_link})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        registry = buildregistry.use(REGISTRY)
        registry.__enter__()
        self.addCleanup(registry.__exit__, None, None, None)
        self.addCleanup(self.directory.cleanup)

    def plugin_file(self, *parts):
        return os.path.join(self.copy, "BepInEx", "plugins", *parts)

    def read(self, path):
        with open(path) as handle:
            return handle.read()


class StockAndLinkTests(InstanceFixture):
    def test_stock_together_replaces_the_folder_without_the_updater(self):
        instances.configure_instance(self.copy, [])
        self.assertEqual(self.read(self.plugin_file("Together", "CasualtiesMP.dll")), "stock mp")
        self.assertFalse(os.path.exists(self.plugin_file("Together", "Multiupdater.dll")))
        self.assertFalse(os.path.exists(self.plugin_file("Together", "OldOnly.dll")), "files of the earlier build must not survive")

    def test_the_stock_folder_can_come_from_the_dll_variable(self):
        with mock.patch.dict(os.environ, {instances.STOCK_DLL_ENVIRONMENT_VARIABLE: os.path.join(self.stock, "CasualtiesMP.dll")}):
            os.environ.pop(instances.STOCK_DIR_ENVIRONMENT_VARIABLE)
            instances.configure_instance(self.copy, [])
        self.assertEqual(self.read(self.plugin_file("Together", "CasualtiesMP.dll")), "stock mp")

    def test_without_a_stock_folder_the_error_names_the_variable(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(instances.STOCK_DIR_ENVIRONMENT_VARIABLE)
            os.environ.pop(instances.STOCK_DLL_ENVIRONMENT_VARIABLE, None)
            with self.assertRaisesRegex(FileNotFoundError, instances.STOCK_DIR_ENVIRONMENT_VARIABLE):
                instances.configure_instance(self.copy, [])

    def test_a_stock_folder_without_the_mod_dll_is_an_error(self):
        with mock.patch.dict(os.environ, {instances.STOCK_DIR_ENVIRONMENT_VARIABLE: self.directory.name}):
            with self.assertRaises(FileNotFoundError):
                instances.configure_instance(self.copy, [])

    def test_together_is_left_alone_with_keep(self):
        instances.configure_instance(self.copy, [], together="keep")
        self.assertEqual(self.read(self.plugin_file("Together", "CasualtiesMP.dll")), "old mp")

    def test_the_link_plugin_is_the_freshly_built_one(self):
        instances.configure_instance(self.copy, [], together="keep")
        self.assertEqual(self.read(self.plugin_file("CasualtiesLink", "CasualtiesLink.dll")), "fresh link")

    def test_a_missing_built_link_plugin_says_how_to_build_it(self):
        with mock.patch.dict(os.environ, {instances.LINK_DLL_ENVIRONMENT_VARIABLE: os.path.join(self.directory.name, "none.dll")}):
            with self.assertRaisesRegex(FileNotFoundError, "dotnet build"):
                instances.configure_instance(self.copy, [], together="keep")

    def test_an_unknown_together_choice_is_refused(self):
        with self.assertRaises(ValueError):
            instances.configure_instance(self.copy, [], together="newest")


class RegistryBuildTests(InstanceFixture):
    def flavour_package(self):
        package = os.path.join(self.directory.name, "flavours.zip")
        make_zip(package, {"BepInEx/patchers/CT_FlavourSwitch.dll": "switch", "BepInEx/together-flavours/example/CasualtiesMP.dll": "flavour",
                           "BepInEx/plugins/Together/CasualtiesMP.dll": "flavour", "INSTALL.txt": "text"})
        return package

    def make_stage(self, with_library=True):
        stage = os.path.join(self.directory.name, "stage")
        touch(os.path.join(stage, "plugins", "Together", "CasualtiesMP.dll"), "stage mp")
        touch(os.path.join(stage, "plugins", "Together", "Multiupdater.dll"), "updater")
        if with_library:
            touch(os.path.join(stage, "plugins", "ExampleLib", "ExampleLib.dll"), "library")
        return stage

    def test_the_flavour_package_installs_patcher_flavours_and_active_build(self):
        with mock.patch.dict(os.environ, {instances.FLAVOUR_ZIP_ENVIRONMENT_VARIABLE: self.flavour_package()}):
            instances.configure_instance(self.copy, [], together="flavour:example")
        self.assertTrue(os.path.exists(os.path.join(self.copy, "BepInEx", "patchers", "CT_FlavourSwitch.dll")))
        self.assertEqual(self.read(self.plugin_file("Together", "CasualtiesMP.dll")), "flavour")
        self.assertFalse(os.path.exists(os.path.join(self.copy, "INSTALL.txt")))

    def test_a_flavour_package_needs_its_variable(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(instances.FLAVOUR_ZIP_ENVIRONMENT_VARIABLE, None)
            with self.assertRaisesRegex(FileNotFoundError, instances.FLAVOUR_ZIP_ENVIRONMENT_VARIABLE):
                instances.configure_instance(self.copy, [], together="flavour:example")

    def test_the_launch_option_follows_the_flavour_and_only_then(self):
        self.assertEqual(instances.flavour_arguments("flavour:example"), ["--mp-flavour", "example"])
        self.assertEqual(instances.flavour_arguments("example-stage"), [])

    def test_a_malformed_flavour_name_is_refused(self):
        for bad in ("flavour:", "flavour:Up", "flavour:a b", "flavour:../x"):
            with self.assertRaises(ValueError, msg=bad):
                instances.flavour_name(bad)

    def test_a_stage_build_installs_together_and_its_library_folders_from_the_variable(self):
        with mock.patch.dict(os.environ, {"CU_EXAMPLE_STAGE": self.make_stage()}):
            instances.configure_instance(self.copy, [], together="example-stage")
        self.assertEqual(self.read(self.plugin_file("Together", "CasualtiesMP.dll")), "stage mp")
        self.assertFalse(os.path.exists(self.plugin_file("Together", "Multiupdater.dll")))
        self.assertFalse(os.path.exists(self.plugin_file("Together", "OldOnly.dll")))
        self.assertEqual(self.read(self.plugin_file("ExampleLib", "ExampleLib.dll")), "library")

    def test_a_stage_directory_falls_back_to_its_path_under_the_mods_root(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("CU_EXAMPLE_STAGE", None)
            directory = instances.stage_directory_by_build()["example-stage"]()
        self.assertEqual(os.path.normpath(directory), os.path.normpath(os.path.join(self.mods, "builds", "example", "stage")))

    def test_a_stage_without_the_mod_dll_is_an_error(self):
        with mock.patch.dict(os.environ, {"CU_EXAMPLE_STAGE": self.directory.name}):
            with self.assertRaises(FileNotFoundError):
                instances.configure_instance(self.copy, [], together="example-stage")

    def test_the_stage_choice_is_the_build_name_with_a_suffix(self):
        self.assertEqual(instances.stage_choice("example-stage"), "example-stage-stage")
        with mock.patch.dict(os.environ, {"CU_EXAMPLE_STAGE": self.make_stage()}):
            instances.configure_instance(self.copy, [], together=instances.stage_choice("example-stage"))
        self.assertEqual(self.read(self.plugin_file("Together", "CasualtiesMP.dll")), "stage mp")

    def test_builds_needing_library_folders_are_listed(self):
        self.assertEqual(instances.builds_needing_library_folders(), {"example-stage": ["ExampleLib"]})

    def test_a_python_build_is_installed_by_its_function_with_the_debug_flag(self):
        installed = instances.configure_instance(self.copy, [], together="example-python", debug=False)
        self.assertEqual(installed["together"], "python-build")
        self.assertEqual(self.read(os.path.join(self.copy, "python-build.txt")), "plain")

    def test_a_non_flavour_build_removes_the_switch_that_an_earlier_flavour_left(self):
        with mock.patch.dict(os.environ, {instances.FLAVOUR_ZIP_ENVIRONMENT_VARIABLE: self.flavour_package()}):
            instances.configure_instance(self.copy, [], together="flavour:example")
        instances.configure_instance(self.copy, [], together="stock")
        self.assertFalse(os.path.exists(os.path.join(self.copy, "BepInEx", "patchers", "CT_FlavourSwitch.dll")))
        self.assertFalse(os.path.exists(os.path.join(self.copy, "BepInEx", "together-flavours")))

    def test_a_build_of_an_unknown_kind_is_refused_when_the_registry_is_read(self):
        with buildregistry.use({"builds": {"odd": {"kind": "teleport"}}}):
            with self.assertRaises(ValueError):
                buildregistry.builds()

    def test_without_a_registry_only_the_builtin_choices_exist(self):
        with buildregistry.use({}):
            self.assertEqual(buildregistry.desync_builds(), ())
            with self.assertRaises(ValueError):
                instances.configure_instance(self.copy, [], together="example-stage")


class PluginSetTests(InstanceFixture):
    def test_each_plugin_set_installs_its_files(self):
        installed = instances.configure_instance(self.copy, ["example-dll", "example-dir", "example-zip"], together="keep")
        self.assertEqual(self.read(self.plugin_file("Example", "Example.dll")), "dll set")
        self.assertEqual(self.read(self.plugin_file("ExamplePack", "pack.json")), "directory set")
        self.assertEqual(self.read(self.plugin_file("ExampleLoaded", "a.dll")), "release 0.3.0")
        self.assertEqual(sorted(installed), ["example-dir", "example-dll", "example-zip", "link"])

    def test_the_newest_release_zip_is_used_and_previous_ones_are_ignored(self):
        instances.configure_instance(self.copy, ["example-zip"], together="keep")
        self.assertEqual(self.read(self.plugin_file("ExampleLoaded", "a.dll")), "release 0.3.0")

    def test_a_missing_release_is_an_error(self):
        os.remove(os.path.join(self.mods, "example", "dist", "Example-0.3.0.zip"))
        os.remove(os.path.join(self.mods, "example", "dist", "Example-0.2.0.zip"))
        with self.assertRaises(FileNotFoundError):
            instances.configure_instance(self.copy, ["example-zip"], together="keep")

    def test_leftover_managed_plugins_are_removed_before_the_new_set_is_installed(self):
        instances.configure_instance(self.copy, [], together="keep")
        self.assertFalse(os.path.exists(self.plugin_file("Example")))

    def test_switching_sets_leaves_only_the_requested_plugins(self):
        instances.configure_instance(self.copy, ["example-dll", "example-dir"], together="keep")
        instances.configure_instance(self.copy, ["example-dir"], together="keep")
        self.assertFalse(os.path.exists(self.plugin_file("Example")))
        self.assertTrue(os.path.exists(self.plugin_file("ExamplePack", "pack.json")))

    def test_debug_logging_is_switched_on_only_for_installed_sets_and_cleared_afterwards(self):
        config = os.path.join(self.copy, "BepInEx", "config", "example.guid.cfg")
        instances.configure_instance(self.copy, ["example-dll"], together="keep")
        self.assertIn("Enabled = true", self.read(config))
        instances.configure_instance(self.copy, [], together="keep")
        self.assertFalse(os.path.exists(config))

    def test_debug_can_be_left_off(self):
        instances.configure_instance(self.copy, ["example-dll"], together="keep", debug=False)
        self.assertFalse(os.path.exists(os.path.join(self.copy, "BepInEx", "config", "example.guid.cfg")))

    def test_an_unknown_plugin_set_is_refused_before_anything_changes(self):
        with self.assertRaises(ValueError):
            instances.configure_instance(self.copy, ["example-dll", "nothing"], together="keep")
        self.assertEqual(self.read(self.plugin_file("Example", "Example.dll")), "leftover")

    def test_the_probe_config_comes_from_the_registry(self):
        instances.write_probe_config(self.copy)
        self.assertEqual(self.read(os.path.join(self.copy, "BepInEx", "config", "Probe.cfg")), "[Probe]\n")
        other = os.path.join(self.directory.name, "other")
        with buildregistry.use({}):
            instances.write_probe_config(other)
        self.assertFalse(os.path.exists(other))


class MpEnabledTests(unittest.TestCase):
    def test_a_persisted_disable_flag_is_set_back_to_zero(self):
        calls = []

        def run(command, **options):
            calls.append(command)
            output = "    CasualtiesMP_FORCE_DISABLE_MP_MOD_h123    REG_DWORD    0x1\n" if command[1] == "query" else ""
            return mock.Mock(stdout=output)

        self.assertEqual(instances.ensure_mp_enabled(run=run), ["CasualtiesMP_FORCE_DISABLE_MP_MOD_h123"])
        self.assertTrue(any(command[1] == "add" and command[command.index("/d") + 1] == "0" for command in calls))

    def test_an_already_enabled_flag_is_left_alone(self):
        calls = []

        def run(command, **options):
            calls.append(command)
            return mock.Mock(stdout="    CasualtiesMP_FORCE_DISABLE_MP_MOD_h123    REG_DWORD    0x0\n")

        self.assertEqual(instances.ensure_mp_enabled(run=run), [])
        self.assertFalse(any(command[1] == "add" for command in calls))


class ArgumentTests(unittest.TestCase):
    def test_the_client_connects_to_the_given_address_and_the_host_to_the_session_address(self):
        self.assertIn("127.0.0.1:7791", instances.client_arguments(address="127.0.0.1:7791"))
        self.assertIn(instances.SESSION_ADDRESS, instances.client_arguments())
        self.assertIn(instances.SESSION_ADDRESS, instances.host_arguments())

    def test_extra_arguments_are_appended(self):
        self.assertEqual(instances.host_arguments(["--extra"])[-1], "--extra")
        self.assertEqual(instances.client_arguments(["--extra"])[-1], "--extra")


if __name__ == "__main__":
    unittest.main()
