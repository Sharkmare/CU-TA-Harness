import copy
import json
import os
import time

from . import friendszip, instances, testcopy
from .launcher import GameProcess, running_game_pids
from .lock import GameLock
from .pair import ProfileGuard

TEST_PACK_FOLDER = "CasualtiesCharacters-Testpack"
TEST_PACK_MANIFEST = {"id": "testpack", "name": "Test pack", "version": "1.0.0", "minLoader": "0.2.0"}
TEST_BASES = ("experiment", "milky", "dune")
TEMPLATE_RELATIVE = os.path.join("CU Characters", "tests", "fixtures", "samplepack", "characters", "sample_scout.json")
STOP_FILE_NAME = "stop"
SESSION_FILE_NAME = "session.json"
STOP_POLL_SECONDS = 2.0
SINGLEPLAYER_ARGUMENTS = ["--mp-disable"]
GAME_COPY_NAME = "CU-paged-select"


def write_test_pack(plugins_folder, count, template_path):
    if count < 1:
        raise ValueError("the test pack needs at least one character")
    with open(template_path, encoding="utf-8") as handle:
        template = json.load(handle)
    folder = os.path.join(plugins_folder, TEST_PACK_FOLDER)
    os.makedirs(os.path.join(folder, "characters"))
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as handle:
        json.dump(TEST_PACK_MANIFEST, handle)
    keys = []
    for index in range(count):
        character = copy.deepcopy(template)
        key = "tester%d" % (index + 1)
        character["key"] = key
        character["base"] = TEST_BASES[index % len(TEST_BASES)]
        character["name"] = {"en": "Tester %d" % (index + 1)}
        with open(os.path.join(folder, "characters", key + ".json"), "w", encoding="utf-8") as handle:
            json.dump(character, handle, indent=2)
        keys.append(key)
    return keys


def window_arguments(width, height):
    return ["-screen-fullscreen", "0", "-screen-width", str(width), "-screen-height", str(height)]


def run_session(session_directory, snapshot_root, port, width, height, character_count, expected_zip_md5, mods_root):
    zip_path = friendszip.default_zip_path()
    actual = friendszip.md5_of_file(zip_path)
    if actual != expected_zip_md5:
        raise ValueError("the zip md5 is %s, expected %s" % (actual, expected_zip_md5))
    if running_game_pids():
        raise RuntimeError("a game is already running")
    os.makedirs(session_directory, exist_ok=True)
    stop_path = os.path.join(session_directory, STOP_FILE_NAME)
    if os.path.exists(stop_path):
        os.remove(stop_path)
    destination = instances.copy_directory(GAME_COPY_NAME)
    guard = ProfileGuard(snapshot_root)
    process = None
    with GameLock("paged select check"):
        guard.snapshot()
        try:
            testcopy.make_copy(destination)
            installed = instances.configure_instance(destination, [], together=instances.FRIENDS_ZIP_CHOICE)
            keys = write_test_pack(os.path.join(destination, instances.PLUGINS_RELATIVE), character_count, os.path.join(mods_root, TEMPLATE_RELATIVE))
            process = GameProcess(port, SINGLEPLAYER_ARGUMENTS, directory=destination, manage_save=False, window_args=window_arguments(width, height))
            status = process.start(instances.START_TIMEOUT_SECONDS)
            with open(os.path.join(session_directory, SESSION_FILE_NAME), "w", encoding="utf-8") as handle:
                json.dump({"port": port, "width": width, "height": height, "testPackKeys": keys, "zipMd5": actual, "removedFromCopy": installed["together"]["removedFromCopy"],
                           "gameVersion": status.get("version")}, handle, indent=2)
            while not os.path.exists(stop_path):
                if process.process.poll() is not None:
                    break
                time.sleep(STOP_POLL_SECONDS)
        finally:
            if process is not None:
                process.close()
            testcopy.remove_copy(destination)
            guard.restore()
