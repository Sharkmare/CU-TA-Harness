import os
import shutil
import subprocess
import time

from .commands import Game
from .parsing import LinkError

GAME_DIR_ENVIRONMENT_VARIABLE = "CASUALTIES_GAME_DIR"
DEFAULT_GAME_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\Casualties Unknown"
GAME_EXE = "CasualtiesUnknown.exe"
WINDOW_ARGS = ["-screen-fullscreen", "0", "-screen-width", "1280", "-screen-height", "720"]
START_TIMEOUT_SECONDS = 180.0
QUIT_TIMEOUT_SECONDS = 30.0
LINK_PORT_ARGUMENT = "--link-port"
SAVE_FILE_NAME = "save.sv"
SAVE_BACKUP_SUFFIX = ".prerig"

MP_FLAGS_WITHOUT_VALUE = ("starthost", "startclient", "startserver", "sethost", "setclient", "setserver",
                          "startnetwork", "immidiate-start", "setstarttutorial", "setstartdebug", "verbose", "disable", "enable", "debug", "nosteam")
MP_FLAGS_WITH_VALUE = ("ip-port", "setname", "setpass", "log-level", "log-cat", "setchar", "debug-categories", "mychar")


class GameAlreadyRunning(RuntimeError):
    pass


def game_dir():
    return os.environ.get(GAME_DIR_ENVIRONMENT_VARIABLE, DEFAULT_GAME_DIR)


def running_game_pids():
    output = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + GAME_EXE, "/FO", "CSV", "/NH"],
                            capture_output=True, text=True).stdout
    pids = []
    for line in output.splitlines():
        fields = [field.strip('"') for field in line.split('","')]
        if len(fields) >= 2 and fields[0].strip('"').lower() == GAME_EXE.lower():
            pids.append(int(fields[1]))
    return pids


def mp_arguments(flags):
    arguments = []
    for name, value in flags.items():
        if name in MP_FLAGS_WITHOUT_VALUE:
            if value:
                arguments.append("--mp-" + name)
        elif name in MP_FLAGS_WITH_VALUE:
            arguments.extend(["--mp-" + name, str(value)])
        else:
            raise ValueError("unknown mp flag %r; known: %s" % (name, ", ".join(MP_FLAGS_WITHOUT_VALUE + MP_FLAGS_WITH_VALUE)))
    return arguments


class GameProcess:

    def __init__(self, port, extra_args=(), directory=None, link_enabled=True, manage_save=True, window_args=None):
        self.port = port
        self.link_enabled = link_enabled
        self.manage_save = manage_save
        self.window_args = list(WINDOW_ARGS if window_args is None else window_args)
        self.directory = directory or game_dir()
        self.extra_args = list(extra_args)
        self.process = None
        self.game = Game(port)
        self.pid = None
        self.saved_backup = None

    def start(self, timeout=START_TIMEOUT_SECONDS, allow_existing=False):
        existing = running_game_pids()
        if existing and not allow_existing:
            raise GameAlreadyRunning("CasualtiesUnknown.exe is already running (pid %s); a second launch of an online game loses the match" % existing)
        command = [os.path.join(self.directory, GAME_EXE)] + self.window_args + self.extra_args
        if self.link_enabled:
            command += [LINK_PORT_ARGUMENT, str(self.port)]
        self.process = subprocess.Popen(command, cwd=self.directory)
        self.pid = self.process.pid
        if not self.link_enabled:
            return None
        self._wait_for_link(timeout)
        if self.manage_save:
            self._backup_save()
        return self.game.status()

    def _wait_for_link(self, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("game exited with code %s before the link answered; read BepInEx/LogOutput.log" % self.process.returncode)
            if self.game.transport.is_up():
                return
            time.sleep(1.0)
        raise TimeoutError("link on port %d did not answer within %.0fs; read BepInEx/LogOutput.log" % (self.port, timeout))

    def _save_path(self):
        return os.path.join(self.game.status()["persistentDataPath"], SAVE_FILE_NAME)

    def _backup_save(self):
        path = self._save_path()
        if os.path.exists(path):
            self.saved_backup = path + SAVE_BACKUP_SUFFIX
            shutil.copy2(path, self.saved_backup)

    def _restore_save(self, path):
        if self.saved_backup and os.path.exists(self.saved_backup):
            shutil.copy2(self.saved_backup, path)
            os.remove(self.saved_backup)
        elif os.path.exists(path):
            os.remove(path)

    def terminate(self):
        if self.process is not None:
            self.process.kill()
            self.process.wait(10)
            self.process = None

    def close(self):
        if self.process is None:
            return
        if not self.link_enabled:
            return self.terminate()
        save_path = None
        try:
            save_path = self._save_path() if self.manage_save else None
            self.game.call("quit", timeout=10.0)
        except (OSError, LinkError):
            pass
        try:
            self.process.wait(QUIT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(10)
        if save_path:
            self._restore_save(save_path)
        self.process = None
