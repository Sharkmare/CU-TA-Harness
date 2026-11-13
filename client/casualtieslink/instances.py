import glob
import os
import re
import shutil
import subprocess
import zipfile

from . import friendszip, testcopy
from .launcher import GameProcess, mp_arguments
from .pair import PREFS_REGISTRY_KEY, ProfileGuard
from .udpproxy import DelayProxy

MODS_ROOT_ENVIRONMENT_VARIABLE = "CU_MODS_ROOT"
STOCK_DIR_ENVIRONMENT_VARIABLE = "CU_STOCK_TOGETHER_DIR"
STOCK_DLL_ENVIRONMENT_VARIABLE = "CU_STOCK_TOGETHER_DLL"
PLUGINS_RELATIVE = os.path.join("BepInEx", "plugins")
CONFIG_RELATIVE = os.path.join("BepInEx", "config")
TOGETHER_FOLDER = "Together"
STOCK_EXCLUDED_FILES = ("Multiupdater.dll",)
FORK_ZIP_ENVIRONMENT_VARIABLE = "CU_FORK_TOGETHER_ZIP"
TOGETHER_IN_ZIP = "BepInEx/plugins/Together/"
FLAVOUR_ZIP_ENVIRONMENT_VARIABLE = "CU_FLAVOUR_ZIP"
FLAVOUR_PREFIX = "flavour:"
OFFICIAL_STAGE_CHOICE = "official-stage"
FULLBUILD_CONTROL_STAGE_CHOICE = "fullbuild-control-stage"
FULLBUILD_FIXED_STAGE_CHOICE = "fullbuild-fixed-stage"
SPECTATOR_FIX_STAGE_CHOICE = "spectator-fix-stage"
FRIENDS_ZIP_CHOICE = "friends-zip"
PR24_CONTROL_STAGE_CHOICE = "pr24-control-stage"
PR24_FIXED_STAGE_CHOICE = "pr24-fixed-stage"
PR24_VERBOSE_STAGE_CHOICE = "pr24-fixed-verbose-stage"
PR24_CONTROL_VERBOSE_STAGE_CHOICE = "pr24-control-verbose-stage"
PR24_CONTROL_VERBOSE_STAGE_ENVIRONMENT_VARIABLE = "CU_PR24_CONTROL_VERBOSE_STAGE"
PR24_VERBOSE_STAGE_ENVIRONMENT_VARIABLE = "CU_PR24_VERBOSE_STAGE"
PR24_CONTROL_STAGE_ENVIRONMENT_VARIABLE = "CU_PR24_CONTROL_STAGE"
PR24_FIXED_STAGE_ENVIRONMENT_VARIABLE = "CU_PR24_FIXED_STAGE"
OFFICIAL_STAGE_ENVIRONMENT_VARIABLE = "CU_OFFICIAL_STAGE"
FULLBUILD_CONTROL_STAGE_ENVIRONMENT_VARIABLE = "CU_FULLBUILD_CONTROL_STAGE"
FULLBUILD_FIXED_STAGE_ENVIRONMENT_VARIABLE = "CU_FULLBUILD_FIXED_STAGE"
SPECTATOR_FIX_STAGE_ENVIRONMENT_VARIABLE = "CU_SPECTATOR_FIX_STAGE"
FULLBUILD_PROJECT_FOLDER = "Private CU together"
TOGETHER_CONFIG_NAME = "CasualtiesMP.cfg"
PROBE_CONFIG_TEXT = "[Probe]\n\nFindTheBug = true\n"
FLAVOUR_OPTION = "--mp-flavour"
FLAVOUR_PATCHER = os.path.join("BepInEx", "patchers", "CT_FlavourSwitch.dll")
FLAVOUR_FOLDER = os.path.join("BepInEx", "together-flavours")
FLAVOUR_PACKAGE_PARTS = ("BepInEx/patchers/", "BepInEx/together-flavours/", "BepInEx/plugins/Together/")
SIZE_FOLDER = "CasualtiesSize"
LOADER_FOLDER = "CasualtiesCharacters"
AVALI_FOLDER = "CasualtiesCharacters-Avali"
SAMPLE_PACK_FOLDER = "CasualtiesCharacters-Sample"
NO_SCATTER_FOLDER = "NoScatterPunish"
MANAGED_FOLDERS = (SIZE_FOLDER, LOADER_FOLDER, AVALI_FOLDER, SAMPLE_PACK_FOLDER, NO_SCATTER_FOLDER)
SIZE_GUID = "hive.casualties.size"
LOADER_GUID = "hive.casualties.characters"
DEBUG_CONFIG_TEXT = "[Debug]\n\nEnabled = true\n"
MP_DISABLE_VALUE_PATTERN = re.compile(r"^\s*(CasualtiesMP_FORCE_DISABLE_MP_MOD_h\d+)\s+REG_DWORD\s+(0x[0-9a-fA-F]+)\s*$", re.M)
SESSION_ADDRESS = "127.0.0.1:7790"
HOST_PORT = 7650
PROXY_PORT = 7791
CLIENT_PORT = 7651
HOST_COPY_NAME = "CU-scenario-host"
CLIENT_COPY_NAME = "CU-scenario-client"
START_TIMEOUT_SECONDS = 240.0


def mods_root():
    return os.environ.get(MODS_ROOT_ENVIRONMENT_VARIABLE) or os.path.dirname(testcopy.REPO_ROOT)


def stock_together_dir():
    explicit = os.environ.get(STOCK_DIR_ENVIRONMENT_VARIABLE)
    if explicit:
        return explicit
    dll = os.environ.get(STOCK_DLL_ENVIRONMENT_VARIABLE)
    if dll:
        return os.path.dirname(dll)
    return os.path.join(os.path.dirname(mods_root()), "backup", "Together_5.4.0_original")


def latest_zip(directory, prefix, must_not_contain=("previous",)):
    candidates = [path for path in glob.glob(os.path.join(directory, prefix + "*.zip"))
                  if not any(word in os.path.basename(path) for word in must_not_contain)]
    if not candidates:
        raise FileNotFoundError("no %s*.zip in %s" % (prefix, directory))
    return sorted(candidates)[-1]


def extract_release(zip_path, copy):
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(copy)


def install_size(copy):
    source = os.path.join(mods_root(), "size-mod", "bin", "CasualtiesSize.dll")
    if not os.path.isfile(source):
        raise FileNotFoundError(source)
    folder = os.path.join(copy, PLUGINS_RELATIVE, SIZE_FOLDER)
    os.makedirs(folder, exist_ok=True)
    shutil.copy2(source, folder)
    return source


def install_loader(copy):
    archive = latest_zip(os.path.join(mods_root(), "CU Characters", "dist"), "CasualtiesCharacters-0")
    extract_release(archive, copy)
    return archive


def install_avali(copy):
    archive = latest_zip(os.path.join(mods_root(), "CU Character Avali", "dist"), "CasualtiesCharacters-Avali")
    extract_release(archive, copy)
    return archive


def install_sample_pack(copy):
    source = os.path.join(mods_root(), "CU Characters", "tests", "fixtures", "samplepack")
    if not os.path.isdir(source):
        raise FileNotFoundError(source)
    shutil.copytree(source, os.path.join(copy, PLUGINS_RELATIVE, SAMPLE_PACK_FOLDER))
    return source


def install_noscatter(copy):
    source = os.path.join(mods_root(), "no-scatter-punish", "bin", "NoScatterPunish.dll")
    if not os.path.isfile(source):
        raise FileNotFoundError(source)
    folder = os.path.join(copy, PLUGINS_RELATIVE, NO_SCATTER_FOLDER)
    os.makedirs(folder, exist_ok=True)
    shutil.copy2(source, folder)
    return source


PLUGIN_INSTALLERS = {"size": install_size, "loader": install_loader, "avali": install_avali, "samplepack": install_sample_pack, "noscatter": install_noscatter}
PLUGIN_DEBUG_GUIDS = {"size": SIZE_GUID, "loader": LOADER_GUID}


LINK_FOLDER = "CasualtiesLink"
LINK_DLL_ENVIRONMENT_VARIABLE = "CU_LINK_DLL"


def link_dll():
    return os.environ.get(LINK_DLL_ENVIRONMENT_VARIABLE) or os.path.join(testcopy.REPO_ROOT, "plugin", "bin", "CasualtiesLink.dll")


def install_link(copy):
    source = link_dll()
    if not os.path.isfile(source):
        raise FileNotFoundError(source + " (build the plugin first: dotnet build plugin -c Release)")
    folder = os.path.join(copy, PLUGINS_RELATIVE, LINK_FOLDER)
    os.makedirs(folder, exist_ok=True)
    shutil.copy2(source, folder)
    return source


def install_stock_together(copy):
    target = os.path.join(copy, PLUGINS_RELATIVE, TOGETHER_FOLDER)
    if os.path.isdir(target):
        shutil.rmtree(target)
    source = stock_together_dir()
    if not os.path.isfile(os.path.join(source, "CasualtiesMP.dll")):
        raise FileNotFoundError(os.path.join(source, "CasualtiesMP.dll"))
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*STOCK_EXCLUDED_FILES))
    return source


def fork_zip():
    explicit = os.environ.get(FORK_ZIP_ENVIRONMENT_VARIABLE)
    if explicit:
        return explicit
    return os.path.join(os.path.expanduser("~"), "Downloads", "CasualtiesTogether-5.4.1-dune.3.zip")


def install_fork_together(copy):
    archive_path = fork_zip()
    if not os.path.isfile(archive_path):
        raise FileNotFoundError(archive_path)
    target = os.path.join(copy, PLUGINS_RELATIVE, TOGETHER_FOLDER)
    if os.path.isdir(target):
        shutil.rmtree(target)
    os.makedirs(target)
    with zipfile.ZipFile(archive_path) as archive:
        for name in archive.namelist():
            if name.startswith(TOGETHER_IN_ZIP) and not name.endswith("/"):
                destination = os.path.join(target, name[len(TOGETHER_IN_ZIP):])
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                with open(destination, "wb") as handle:
                    handle.write(archive.read(name))
    if not os.path.isfile(os.path.join(target, "CasualtiesMP.dll")):
        raise FileNotFoundError("no CasualtiesMP.dll under " + TOGETHER_IN_ZIP + " in " + archive_path)
    return archive_path


def flavour_zip():
    explicit = os.environ.get(FLAVOUR_ZIP_ENVIRONMENT_VARIABLE)
    if explicit:
        return explicit
    return os.path.join(os.path.expanduser("~"), "Downloads", "CasualtiesTogether-5.4.1+4.zip")


def flavour_name(together):
    if isinstance(together, str) and together.startswith(FLAVOUR_PREFIX):
        name = together[len(FLAVOUR_PREFIX):]
        if not re.fullmatch(r"[a-z0-9.\-]+", name):
            raise ValueError("not a flavour name: %r" % name)
        return name
    return None


def flavour_arguments(together):
    name = flavour_name(together)
    return [FLAVOUR_OPTION, name] if name else []


def install_flavour_package(copy):
    archive_path = flavour_zip()
    if not os.path.isfile(archive_path):
        raise FileNotFoundError(archive_path)
    for relative in (os.path.join(PLUGINS_RELATIVE, TOGETHER_FOLDER), FLAVOUR_FOLDER):
        folder = os.path.join(copy, relative)
        if os.path.isdir(folder):
            shutil.rmtree(folder)
    patcher = os.path.join(copy, FLAVOUR_PATCHER)
    if os.path.exists(patcher):
        os.remove(patcher)
    with zipfile.ZipFile(archive_path) as archive:
        for name in archive.namelist():
            if name.startswith(FLAVOUR_PACKAGE_PARTS) and not name.endswith("/"):
                destination = os.path.join(copy, *name.split("/"))
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                with open(destination, "wb") as handle:
                    handle.write(archive.read(name))
    if not os.path.isfile(patcher):
        raise FileNotFoundError("no " + FLAVOUR_PATCHER + " in " + archive_path)
    return archive_path


def official_stage_directory():
    explicit = os.environ.get(OFFICIAL_STAGE_ENVIRONMENT_VARIABLE)
    if explicit:
        return explicit
    return os.path.join(testcopy.REPO_ROOT, ".state", "stages", "official-5.5.0")


def fullbuild_stage_directory(variable, folder):
    explicit = os.environ.get(variable)
    if explicit:
        return explicit
    return os.path.join(mods_root(), FULLBUILD_PROJECT_FOLDER, "build", folder)


def fullbuild_control_stage_directory():
    return fullbuild_stage_directory(FULLBUILD_CONTROL_STAGE_ENVIRONMENT_VARIABLE, "stage_fullbuild_control")


def fullbuild_fixed_stage_directory():
    return fullbuild_stage_directory(FULLBUILD_FIXED_STAGE_ENVIRONMENT_VARIABLE, "stage_fullbuild_fixed")


def pr24_control_stage_directory():
    return fullbuild_stage_directory(PR24_CONTROL_STAGE_ENVIRONMENT_VARIABLE, "stage_pr24_control")


def pr24_fixed_stage_directory():
    return fullbuild_stage_directory(PR24_FIXED_STAGE_ENVIRONMENT_VARIABLE, "stage_pr24_fixed")


def pr24_verbose_stage_directory():
    return fullbuild_stage_directory(PR24_VERBOSE_STAGE_ENVIRONMENT_VARIABLE, "stage_pr24_fixed_verbose2")


def pr24_control_verbose_stage_directory():
    return fullbuild_stage_directory(PR24_CONTROL_VERBOSE_STAGE_ENVIRONMENT_VARIABLE, "stage_pr24_control_verbose")


def spectator_fix_stage_directory():
    return fullbuild_stage_directory(SPECTATOR_FIX_STAGE_ENVIRONMENT_VARIABLE, "stage_spectator_fix")


def stage_directory_by_build():
    return {"official-5.5.0": official_stage_directory, "fullbuild-control": fullbuild_control_stage_directory, "fullbuild-fixed": fullbuild_fixed_stage_directory,
            "spectator-fix": spectator_fix_stage_directory, "pr24-control": pr24_control_stage_directory, "pr24-fixed": pr24_fixed_stage_directory,
            "pr24-fixed-verbose": pr24_verbose_stage_directory, "pr24-control-verbose": pr24_control_verbose_stage_directory}


def install_stage_together(copy, directory):
    source = os.path.join(directory, "plugins", TOGETHER_FOLDER)
    if not os.path.isfile(os.path.join(source, "CasualtiesMP.dll")):
        raise FileNotFoundError(os.path.join(source, "CasualtiesMP.dll"))
    target = os.path.join(copy, PLUGINS_RELATIVE, TOGETHER_FOLDER)
    if os.path.isdir(target):
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*STOCK_EXCLUDED_FILES))
    return source


def remove_flavour_switch(copy):
    folder = os.path.join(copy, FLAVOUR_FOLDER)
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    patcher = os.path.join(copy, FLAVOUR_PATCHER)
    if os.path.exists(patcher):
        os.remove(patcher)


def write_probe_config(copy):
    folder = os.path.join(copy, CONFIG_RELATIVE)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, TOGETHER_CONFIG_NAME), "w") as handle:
        handle.write(PROBE_CONFIG_TEXT)


def clear_managed_plugins(copy):
    together_config = os.path.join(copy, CONFIG_RELATIVE, TOGETHER_CONFIG_NAME)
    if os.path.exists(together_config):
        os.remove(together_config)
    for name in MANAGED_FOLDERS:
        folder = os.path.join(copy, PLUGINS_RELATIVE, name)
        if os.path.isdir(folder):
            shutil.rmtree(folder)
    for guid in PLUGIN_DEBUG_GUIDS.values():
        config = os.path.join(copy, CONFIG_RELATIVE, guid + ".cfg")
        if os.path.exists(config):
            os.remove(config)


def write_debug_config(copy, guid):
    folder = os.path.join(copy, CONFIG_RELATIVE)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, guid + ".cfg"), "w") as handle:
        handle.write(DEBUG_CONFIG_TEXT)


def configure_instance(copy, plugins, together="stock", debug=True):
    unknown = [name for name in plugins if name not in PLUGIN_INSTALLERS]
    if unknown:
        raise ValueError("unknown plugin sets %s; known: %s" % (unknown, sorted(PLUGIN_INSTALLERS)))
    clear_managed_plugins(copy)
    installed = {"link": install_link(copy)}
    if together != "keep" and not flavour_name(together):
        remove_flavour_switch(copy)
    if together == "stock":
        installed["together"] = install_stock_together(copy)
    elif together == "fork":
        installed["together"] = install_fork_together(copy)
    elif together == OFFICIAL_STAGE_CHOICE:
        installed["together"] = install_stage_together(copy, official_stage_directory())
    elif together == FULLBUILD_CONTROL_STAGE_CHOICE:
        installed["together"] = install_stage_together(copy, fullbuild_control_stage_directory())
    elif together == FULLBUILD_FIXED_STAGE_CHOICE:
        installed["together"] = install_stage_together(copy, fullbuild_fixed_stage_directory())
    elif together == SPECTATOR_FIX_STAGE_CHOICE:
        installed["together"] = install_stage_together(copy, spectator_fix_stage_directory())
    elif together == PR24_CONTROL_STAGE_CHOICE:
        installed["together"] = install_stage_together(copy, pr24_control_stage_directory())
    elif together == PR24_CONTROL_VERBOSE_STAGE_CHOICE:
        installed["together"] = install_stage_together(copy, pr24_control_verbose_stage_directory())
    elif together == PR24_VERBOSE_STAGE_CHOICE:
        installed["together"] = install_stage_together(copy, pr24_verbose_stage_directory())
    elif together == PR24_FIXED_STAGE_CHOICE:
        installed["together"] = install_stage_together(copy, pr24_fixed_stage_directory())
    elif together == FRIENDS_ZIP_CHOICE:
        installed["together"] = friendszip.extract_into_copy(friendszip.default_zip_path(), copy, remove_extras=True)
        if debug:
            write_debug_config(copy, LOADER_GUID)
    elif flavour_name(together):
        installed["together"] = install_flavour_package(copy)
    elif together != "keep":
        raise ValueError("together must be stock, fork, a stage choice, keep or flavour:<name>, not %r" % together)
    for name in plugins:
        installed[name] = PLUGIN_INSTALLERS[name](copy)
        if debug and name in PLUGIN_DEBUG_GUIDS:
            write_debug_config(copy, PLUGIN_DEBUG_GUIDS[name])
    return installed


def ensure_mp_enabled(run=subprocess.run):
    query = run(["reg", "query", PREFS_REGISTRY_KEY], capture_output=True, text=True)
    changed = []
    for name, value in MP_DISABLE_VALUE_PATTERN.findall(query.stdout or ""):
        if int(value, 16) != 0:
            run(["reg", "add", PREFS_REGISTRY_KEY, "/v", name, "/t", "REG_DWORD", "/d", "0", "/f"], capture_output=True, text=True)
            changed.append(name)
    return changed


def host_arguments(extra=()):
    flags = {"nosteam": True, "starthost": True, "immidiate-start": True, "setname": "HostD", "ip-port": SESSION_ADDRESS}
    return mp_arguments(flags) + list(extra)


def client_arguments(extra=(), address=SESSION_ADDRESS):
    flags = {"nosteam": True, "startclient": True, "setname": "ClientD", "ip-port": address}
    return mp_arguments(flags) + list(extra)


def copy_directory(name):
    return os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), name)


class ScenarioGames:
    def __init__(self, backup_root, host_copy=None, client_copy=None):
        self.guard = ProfileGuard(backup_root)
        self.host_copy = host_copy or copy_directory(HOST_COPY_NAME)
        self.client_copy = client_copy or copy_directory(CLIENT_COPY_NAME)
        self.host = None
        self.client = None
        self.proxy = None
        self.prepared = False

    def prepare(self):
        self.guard.snapshot()
        testcopy.make_copy(self.host_copy)
        testcopy.make_copy(self.client_copy)
        ensure_mp_enabled()
        self.prepared = True

    def start(self, host_plugins, client_plugins, host_extra=(), client_extra=(), after_host_link=None, after_client_link=None, together="stock", host_together=None, client_together=None, delay_ms=None, jitter_ms=0.0, control_port=None, probe=False):
        host_together = host_together or together
        client_together = client_together or together
        self.configure_host(host_plugins, host_together, probe)
        self.configure_client(client_plugins, client_together, probe)
        self.host = self.launch_host(host_extra, host_together)
        client_address = SESSION_ADDRESS
        if delay_ms is not None:
            self.proxy = DelayProxy(PROXY_PORT, int(SESSION_ADDRESS.rpartition(":")[2]), delay_ms, jitter_ms).start()
            if control_port is not None:
                self.proxy.start_control(control_port)
            client_address = "%s:%d" % (SESSION_ADDRESS.rpartition(":")[0], PROXY_PORT)
        self.client = self.launch_client(client_extra, client_together, client_address)
        try:
            self.host.start(START_TIMEOUT_SECONDS, allow_existing=True)
            if after_host_link:
                after_host_link(self.host.game)
            self.client.start(START_TIMEOUT_SECONDS, allow_existing=True)
            if after_client_link:
                after_client_link(self.client.game)
        except Exception:
            self.stop()
            raise
        return self.host.game, self.client.game

    def configure_host(self, host_plugins, together, probe=False):
        configure_instance(self.host_copy, host_plugins, together=together)
        if probe:
            write_probe_config(self.host_copy)

    def configure_client(self, client_plugins, together, probe=False):
        configure_instance(self.client_copy, client_plugins, together=together)
        if probe:
            write_probe_config(self.client_copy)

    def launch_host(self, host_extra, together):
        return GameProcess(HOST_PORT, host_arguments(list(host_extra) + flavour_arguments(together)), directory=self.host_copy, manage_save=False,
                           window_args=["-screen-fullscreen", "0", "-screen-width", "640", "-screen-height", "360"])

    def launch_client(self, client_extra, together, address=SESSION_ADDRESS):
        return GameProcess(CLIENT_PORT, client_arguments(list(client_extra) + flavour_arguments(together), address), directory=self.client_copy, manage_save=False,
                           window_args=["-screen-fullscreen", "0", "-screen-width", "640", "-screen-height", "360"])

    def start_host_alone(self, host_plugins, together, host_extra=()):
        self.configure_host(host_plugins, together)
        self.host = self.launch_host(host_extra, together)
        try:
            self.host.start(START_TIMEOUT_SECONDS, allow_existing=True)
        except Exception:
            self.stop()
            raise
        return self.host.game

    def start_client_later(self, client_plugins, together, client_extra=()):
        self.configure_client(client_plugins, together)
        self.client = self.launch_client(client_extra, together)
        try:
            self.client.start(START_TIMEOUT_SECONDS, allow_existing=True)
        except Exception:
            self.stop_client()
            raise
        return self.client.game

    def stop_client(self):
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

    def apply_network(self, profile):
        if self.proxy is None:
            raise RuntimeError("these games were started without the delay proxy")
        self.proxy.set(**profile.as_dict())

    def stop(self):
        if self.proxy is not None:
            self.proxy.stop()
            self.proxy = None
        for member in (self.client, self.host):
            if member is not None:
                try:
                    member.close()
                except Exception:
                    pass
        self.client = None
        self.host = None

    def dispose(self):
        self.stop()
        for directory in (self.host_copy, self.client_copy):
            testcopy.remove_copy(directory)
        if self.prepared:
            self.guard.restore()
            self.prepared = False

    def log_text(self, which, relative=os.path.join("BepInEx", "LogOutput.log")):
        directory = self.host_copy if which == "host" else self.client_copy
        try:
            with open(os.path.join(directory, relative), encoding="utf-8", errors="replace") as handle:
                return handle.read()
        except OSError:
            return ""
