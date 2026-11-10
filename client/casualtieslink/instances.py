import glob
import os
import re
import shutil
import subprocess
import zipfile

from . import testcopy
from .launcher import GameProcess, mp_arguments
from .pair import PREFS_REGISTRY_KEY, ProfileGuard

MODS_ROOT_ENVIRONMENT_VARIABLE = "CU_MODS_ROOT"
STOCK_DIR_ENVIRONMENT_VARIABLE = "CU_STOCK_TOGETHER_DIR"
STOCK_DLL_ENVIRONMENT_VARIABLE = "CU_STOCK_TOGETHER_DLL"
PLUGINS_RELATIVE = os.path.join("BepInEx", "plugins")
CONFIG_RELATIVE = os.path.join("BepInEx", "config")
TOGETHER_FOLDER = "Together"
STOCK_EXCLUDED_FILES = ("Multiupdater.dll",)
SIZE_FOLDER = "CasualtiesSize"
LOADER_FOLDER = "CasualtiesCharacters"
AVALI_FOLDER = "CasualtiesCharacters-Avali"
SAMPLE_PACK_FOLDER = "CasualtiesCharacters-Sample"
MANAGED_FOLDERS = (SIZE_FOLDER, LOADER_FOLDER, AVALI_FOLDER, SAMPLE_PACK_FOLDER)
SIZE_GUID = "hive.casualties.size"
LOADER_GUID = "hive.casualties.characters"
DEBUG_CONFIG_TEXT = "[Debug]\n\nEnabled = true\n"
MP_DISABLE_VALUE_PATTERN = re.compile(r"^\s*(CasualtiesMP_FORCE_DISABLE_MP_MOD_h\d+)\s+REG_DWORD\s+(0x[0-9a-fA-F]+)\s*$", re.M)
SESSION_ADDRESS = "127.0.0.1:7790"
HOST_PORT = 7650
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


PLUGIN_INSTALLERS = {"size": install_size, "loader": install_loader, "avali": install_avali, "samplepack": install_sample_pack}
PLUGIN_DEBUG_GUIDS = {"size": SIZE_GUID, "loader": LOADER_GUID}


def install_stock_together(copy):
    target = os.path.join(copy, PLUGINS_RELATIVE, TOGETHER_FOLDER)
    if os.path.isdir(target):
        shutil.rmtree(target)
    source = stock_together_dir()
    if not os.path.isfile(os.path.join(source, "CasualtiesMP.dll")):
        raise FileNotFoundError(os.path.join(source, "CasualtiesMP.dll"))
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*STOCK_EXCLUDED_FILES))
    return source


def clear_managed_plugins(copy):
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


def configure_instance(copy, plugins, stock_together=True, debug=True):
    unknown = [name for name in plugins if name not in PLUGIN_INSTALLERS]
    if unknown:
        raise ValueError("unknown plugin sets %s; known: %s" % (unknown, sorted(PLUGIN_INSTALLERS)))
    clear_managed_plugins(copy)
    installed = {}
    if stock_together:
        installed["together"] = install_stock_together(copy)
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


def client_arguments(extra=()):
    flags = {"nosteam": True, "startclient": True, "setname": "ClientD", "ip-port": SESSION_ADDRESS}
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
        self.prepared = False

    def prepare(self):
        self.guard.snapshot()
        testcopy.make_copy(self.host_copy)
        testcopy.make_copy(self.client_copy)
        ensure_mp_enabled()
        self.prepared = True

    def start(self, host_plugins, client_plugins, host_extra=(), client_extra=(), after_host_link=None, after_client_link=None):
        configure_instance(self.host_copy, host_plugins)
        configure_instance(self.client_copy, client_plugins)
        self.host = GameProcess(HOST_PORT, host_arguments(host_extra), directory=self.host_copy, manage_save=False,
                                window_args=["-screen-fullscreen", "0", "-screen-width", "640", "-screen-height", "360"])
        self.client = GameProcess(CLIENT_PORT, client_arguments(client_extra), directory=self.client_copy, manage_save=False,
                                  window_args=["-screen-fullscreen", "0", "-screen-width", "640", "-screen-height", "360"])
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

    def stop(self):
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
