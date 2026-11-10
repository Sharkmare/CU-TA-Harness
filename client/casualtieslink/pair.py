import os
import shutil
import subprocess
import time

from . import testcopy
from .launcher import GameProcess, running_game_pids, mp_arguments
from .parsing import LinkError

PRODUCT_PROFILE_RELATIVE = os.path.join("AppData", "LocalLow", "Orsoniks", "CasualtiesUnknown")
PREFS_REGISTRY_KEY = r"HKCU\Software\Orsoniks\CasualtiesUnknown"
SMALL_WINDOW_ARGS = ["-screen-fullscreen", "0", "-screen-width", "640", "-screen-height", "360"]
HOST_LINK_PORT = 7650
CLIENT_LINK_PORT = 7651
SESSION_ADDRESS = "127.0.0.1:7790"
NO_STEAM_FLAG = "--mp-nosteam"
TOGETHER_DLL_RELATIVE = os.path.join("BepInEx", "plugins", "Together", "CasualtiesMP.dll")


def profile_dir():
    return os.path.join(os.path.expanduser("~"), PRODUCT_PROFILE_RELATIVE)


class ProfileGuard:

    def __init__(self, backup_root, directory=None):
        self.directory = directory or profile_dir()
        self.backup_root = backup_root
        self.stamp = time.strftime("%Y%m%d-%H%M%S")
        self.folder_backup = os.path.join(backup_root, "profile-" + self.stamp)
        self.registry_backup = os.path.join(backup_root, "prefs-" + self.stamp + ".reg")
        self.taken = False

    def snapshot(self):
        os.makedirs(self.backup_root, exist_ok=True)
        if os.path.isdir(self.directory):
            shutil.copytree(self.directory, self.folder_backup)
        subprocess.run(["reg", "export", PREFS_REGISTRY_KEY, self.registry_backup, "/y"], capture_output=True)
        self.taken = True

    def restore(self):
        if not self.taken:
            return
        if os.path.isdir(self.folder_backup):
            mirror(self.folder_backup, self.directory, top_level=True)
        if os.path.exists(self.registry_backup):
            subprocess.run(["reg", "import", self.registry_backup], capture_output=True)
        self.taken = False


def is_player_log(name):
    return name.startswith("Player") and name.endswith(".log")


def mirror(source, target, top_level=False):
    os.makedirs(target, exist_ok=True)
    for name in os.listdir(target):
        if top_level and is_player_log(name):
            continue
        if not os.path.exists(os.path.join(source, name)):
            path = os.path.join(target, name)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    for name in os.listdir(source):
        if top_level and is_player_log(name):
            continue
        source_path = os.path.join(source, name)
        target_path = os.path.join(target, name)
        if os.path.isdir(source_path):
            if os.path.exists(target_path) and not os.path.isdir(target_path):
                os.remove(target_path)
            mirror(source_path, target_path)
        else:
            if os.path.isdir(target_path):
                shutil.rmtree(target_path)
            shutil.copy2(source_path, target_path)


def host_flags(character=2, extra=None, debug=True):
    flags = {"enable": True, "ip-port": SESSION_ADDRESS, "setname": "HostD", "starthost": True, "immidiate-start": True}
    if debug:
        flags["debug"] = True
    flags.update(extra or {})
    return flags


def client_flags(character=2, extra=None, debug=True):
    flags = {"enable": True, "ip-port": SESSION_ADDRESS, "setname": "ClientD", "startclient": True}
    if debug:
        flags["debug"] = True
    flags.update(extra or {})
    return flags


class GamePair:

    def __init__(self, backup_root, host_extra_args=(), client_extra_args=(),
                 host_port=HOST_LINK_PORT, client_port=CLIENT_LINK_PORT, client_plugin_dll=None, after_client_link=None, after_host_link=None):
        self.guard = ProfileGuard(backup_root)
        window = SMALL_WINDOW_ARGS
        self.host = GameProcess(host_port, [NO_STEAM_FLAG] + list(host_extra_args), manage_save=False, window_args=window)
        self.client_extra_args = [NO_STEAM_FLAG] + list(client_extra_args)
        self.client_port = client_port
        self.client_plugin_dll = client_plugin_dll
        self.after_client_link = after_client_link
        self.after_host_link = after_host_link
        self.client = None
        self.client_copy = None

    def start(self, timeout=240.0):
        if running_game_pids():
            raise RuntimeError("CasualtiesUnknown.exe is already running; the pair only starts on an idle machine")
        self.guard.snapshot()
        try:
            self.host.start(timeout, allow_existing=False)
            if self.after_host_link:
                self.after_host_link(self.host.game)
            self.client_copy = testcopy.make_copy()
            if self.client_plugin_dll:
                shutil.copy2(self.client_plugin_dll, os.path.join(self.client_copy, TOGETHER_DLL_RELATIVE))
            self.client = GameProcess(self.client_port, self.client_extra_args, directory=self.client_copy,
                                      manage_save=False, window_args=SMALL_WINDOW_ARGS)
            self.client.start(timeout, allow_existing=True)
            if self.after_client_link:
                self.after_client_link(self.client.game)
        except Exception:
            self.close()
            raise
        return self

    @property
    def games(self):
        return self.host.game, self.client.game

    def close(self):
        for member in (self.client, self.host):
            try:
                if member is not None:
                    member.close()
            except Exception:
                pass
        time.sleep(3.0)
        if self.client_copy:
            testcopy.remove_copy(self.client_copy)
            self.client_copy = None
        self.guard.restore()
