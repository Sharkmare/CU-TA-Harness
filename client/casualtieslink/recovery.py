import glob
import os
import re
import subprocess

from . import pair, testcopy
from .launcher import running_game_pids

SNAPSHOT_PATTERN = re.compile(r"^profile-(\d{8}-\d{6})$")
SCENARIO_COPY_NAMES = ("CU-scenario-host", "CU-scenario-client", "CU-paged-select")


def snapshot_stamps(state_root):
    stamps = []
    for path in glob.glob(os.path.join(state_root, "profile-*")):
        found = SNAPSHOT_PATTERN.match(os.path.basename(path))
        if found and os.path.isfile(os.path.join(state_root, "prefs-%s.reg" % found.group(1))):
            stamps.append(found.group(1))
    return sorted(stamps)


def latest_snapshot_stamp(state_root):
    stamps = snapshot_stamps(state_root)
    if not stamps:
        raise FileNotFoundError("no profile snapshot with a matching prefs export in " + state_root)
    return stamps[-1]


def stop_stray_games(run=subprocess.run, pids=None):
    found = running_game_pids() if pids is None else pids
    for pid in found:
        run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    return found


def recover(state_root, lock_path, stamp=None, temp_directory=None, kill_games=True):
    stamp = stamp or latest_snapshot_stamp(state_root)
    guard = pair.ProfileGuard(state_root)
    guard.folder_backup = os.path.join(state_root, "profile-" + stamp)
    guard.registry_backup = os.path.join(state_root, "prefs-" + stamp + ".reg")
    if not (os.path.isdir(guard.folder_backup) and os.path.isfile(guard.registry_backup)):
        raise FileNotFoundError("snapshot %s is incomplete in %s" % (stamp, state_root))
    killed = stop_stray_games() if kill_games else []
    guard.taken = True
    guard.restore()
    base = temp_directory or os.environ.get("TEMP", "")
    removed = []
    for name in SCENARIO_COPY_NAMES:
        folder = os.path.join(base, name)
        if os.path.exists(folder):
            testcopy.remove_copy(folder)
            removed.append(name)
    lock_removed = os.path.exists(lock_path)
    if lock_removed:
        os.remove(lock_path)
    return {"stamp": stamp, "killedGames": killed, "removedCopies": removed, "lockRemoved": lock_removed}
