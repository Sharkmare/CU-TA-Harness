import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HARNESS, "client"))

from casualtieslink.games import instances
from casualtieslink.charselect import oswindow, pagedselect, pagedverify
from casualtieslink.commands import Game
from casualtieslink.launcher import running_game_pids

PRE_RUN = pagedverify.PRE_RUN

SESSION_DIRECTORY = os.path.join(HARNESS, ".state", "paged_select")
SIZES = (("r16x9", 1280, 720), ("r16x10", 1280, 800))
MENU_SETTLE_SECONDS = 1.5
SELF_CHECK_WAIT_SECONDS = 2.0
INTRO_SKIP_TRIES = 4
CHAR_SELECT_WAIT_SECONDS = 20.0


class OsActions:
    def __init__(self, pid):
        oswindow.make_dpi_aware()
        self.pid = pid

    def hwnd(self):
        return oswindow.window_for_pid(self.pid)

    def focus(self):
        return oswindow.focus(self.hwnd())

    def click(self, x, y, unity_size):
        hwnd = self.hwnd()
        origin, size = oswindow.client_geometry(hwnd)
        oswindow.focus(hwnd)
        target = oswindow.unity_to_screen(origin, size, unity_size, x, y)
        oswindow.click_screen(*target)

    def hover(self, x, y, unity_size):
        hwnd = self.hwnd()
        origin, size = oswindow.client_geometry(hwnd)
        oswindow.focus(hwnd)
        oswindow.move_screen(*oswindow.unity_to_screen(origin, size, unity_size, x, y))

    def key(self, name):
        oswindow.focus(self.hwnd())
        oswindow.press_key(name)


def self_check_lines():
    path = os.path.join(instances.copy_directory(pagedselect.GAME_COPY_NAME), "BepInEx", "LogOutput.log")
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return [line.rstrip() for line in handle if "SELFCHECK" in line]
    except OSError:
        return []


def open_character_screen(verifier, game):
    unity_size = verifier.unity_size()
    if verifier.read("instance.contentWarning.activeSelf", PRE_RUN):
        verifier.actions.click(unity_size[0] / 2.0, unity_size[1] / 2.0, unity_size)
        time.sleep(MENU_SETTLE_SECONDS)
    for _ in range(INTRO_SKIP_TRIES):
        if not verifier.read("textExists", "static:ScrollableText"):
            break
        verifier.actions.key("Escape")
        time.sleep(MENU_SETTLE_SECONDS)
    if not verifier.read("instance.runSettingsScreen.activeSelf", PRE_RUN):
        play = next(row for row in game.call("find", type="AdaptiveButton") if game.get("id:%d" % row["object"]["id"], "action", depth=0) == "Play")
        verifier.click_at(play["position"])
    start = next((row for row in game.call("find", type="UnityEngine.UI.Button") if row["object"]["name"] == "Start"), None)
    if start is None:
        return False
    verifier.click_at(start["position"])
    deadline = time.time() + CHAR_SELECT_WAIT_SECONDS
    while time.time() < deadline:
        try:
            if verifier.read("view.Slide.gameObject.activeInHierarchy"):
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify the paged character select with real OS clicks and keys on the running paged_select session.")
    parser.add_argument("--port", type=int, default=instances.HOST_PORT)
    parser.add_argument("--output", default=os.path.join(SESSION_DIRECTORY, "verify.json"))
    arguments = parser.parse_args(argv)
    pids = running_game_pids()
    if len(pids) != 1:
        raise SystemExit("expected exactly one running game, found %s" % pids)
    game = Game(arguments.port)
    verifier = pagedverify.Verifier(game, OsActions(pids[0]), os.path.join(SESSION_DIRECTORY, "verify_shots"))
    verifier.set_resolution(*SIZES[0][1:])
    opened = open_character_screen(verifier, game)
    verifier.record("the character screen opened through real clicks", opened, {"pids": pids})
    time.sleep(SELF_CHECK_WAIT_SECONDS)
    self_check = self_check_lines()
    print("\n".join(self_check) or "no SELFCHECK lines in the log")
    if opened:
        for label, width, height in SIZES:
            verifier.verify_size(label, width, height)
            verifier.capture_pages(label)
        verifier.click_back("the game's real Back button closes the character screen")
    verifier.results.append({"check": "loader SELFCHECK lines", "passed": any("SELFCHECK PASS" in line for line in self_check), "observed": self_check})
    verifier.write(arguments.output)
    summary = json.load(open(arguments.output, encoding="utf-8"))
    print("passed %d, failed %d" % (summary["passed"], summary["failed"]))
    for row in summary["results"]:
        print(("ok   " if row["passed"] else "FAIL ") + row["check"] + "  " + json.dumps(row["observed"], default=str)[:200])
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
