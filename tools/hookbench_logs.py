"""Keeps the logs of a game copy before the harness deletes the copy, so a hang can still be diagnosed afterwards."""
import os
import shutil

LOG_RELATIVE_PATHS = (os.path.join("BepInEx", "LogOutput.log"), os.path.join("BepInEx", "ErrorLog.log"))


def keep_logs(copies, destination, label):
    """Copy the BepInEx logs of each named game copy into destination as <label>_<name>_<logfile>. Returns the files written; a missing log is skipped, not an error."""
    os.makedirs(destination, exist_ok=True)
    written = []
    for name, directory in copies.items():
        if not directory:
            continue
        for relative in LOG_RELATIVE_PATHS:
            source = os.path.join(directory, relative)
            if os.path.isfile(source):
                target = os.path.join(destination, "%s_%s_%s" % (label, name, os.path.basename(relative)))
                shutil.copyfile(source, target)
                written.append(target)
    return written
