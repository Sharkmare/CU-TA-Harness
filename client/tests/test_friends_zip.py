import json
import os
import time
import unittest

from casualtieslink.instances import FRIENDS_ZIP_CHOICE, SESSION_ADDRESS, ScenarioGames
from casualtieslink import desync, friendszip

from . import evidence_scenarios, friends_zip as checks, pvp_banded, spawned_crates
from .desync_scenarios import ready_up, try_ready
from .test_pair import PAIR_ENABLED, SKIP_REASON, wait_for_bodies

STATE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".state")
REPORT_DIRECTORY = os.path.join(STATE_ROOT, "friends_zip_reports")
WORLD_WAIT_SECONDS = 150.0
SETTLE_SECONDS = 10.0
REJOIN_LEAVE_SECONDS = 30.0
REJOIN_WAIT_SECONDS = 150.0
HOST_BODY = "Body_HostD"
CLIENT_BODY = "Body_ClientD"
GAMES = None
RECORD = {}


def setUpModule():
    global GAMES
    if PAIR_ENABLED:
        GAMES = ScenarioGames(STATE_ROOT)
        GAMES.prepare()
        evidence_scenarios.LOG_READER = GAMES.log_text
        spawned_crates.FAILURE_DIRECTORY = REPORT_DIRECTORY


def tearDownModule():
    if RECORD:
        os.makedirs(REPORT_DIRECTORY, exist_ok=True)
        with open(os.path.join(REPORT_DIRECTORY, "friends_zip.json"), "w", encoding="utf-8") as handle:
            json.dump(RECORD, handle, indent=2, default=str)
    if GAMES is not None:
        GAMES.dispose()


def chooser(character_id, label):
    def choose(game):
        outcome = checks.select_character(game, character_id)
        if label not in RECORD.setdefault("lobbyPick", {}):
            RECORD["lobbyPick"][label] = {"first": outcome, "pagerBeforeReady": checks.pager_state(game)}
        RECORD["lobbyPick"][label]["last"] = outcome
    return choose


def wait_until_in_world(game, timeout):
    game.wait_state("in-world", timeout=timeout)
    wait_for_bodies(game, 2, timeout)
    game.call("close_console")


@unittest.skipUnless(PAIR_ENABLED, SKIP_REASON)
class FriendsZipLobbyCheck(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        RECORD["zip"] = {"md5": friendszip.md5_of_file(friendszip.default_zip_path())}
        cls.host, cls.client = GAMES.start([], [], together=FRIENDS_ZIP_CHOICE, host_extra=checks.PVP_RULE_ARGUMENTS, client_extra=checks.PVP_RULE_ARGUMENTS)
        RECORD["zip"]["copyDllMatches"] = {which: friendszip.verify_copy(friendszip.default_zip_path(), copy) for which, copy in (("host", GAMES.host_copy), ("client", GAMES.client_copy))}
        RECORD["pluginFoldersInCopy"] = {which: sorted(friendszip.plugin_names_in_copy(copy)) for which, copy in (("host", GAMES.host_copy), ("client", GAMES.client_copy))}
        try:
            RECORD["lobbyPath"] = "normal lobby wait: both games ready through Together.CharacterSelectWait.SetLocalReady after SelectCharacter"
            accepted = ready_up([cls.host, cls.client], before_ready={cls.host: chooser(checks.EXPERIMENT_CHARACTER, "host"), cls.client: chooser(checks.CUSTOM_CHARACTER, "client")})
            RECORD["readyAccepted"] = accepted
            if not accepted:
                raise AssertionError("the lobby ready gate did not accept both players")
            wait_until_in_world(cls.host, WORLD_WAIT_SECONDS)
            wait_until_in_world(cls.client, WORLD_WAIT_SECONDS)
            time.sleep(SETTLE_SECONDS)
        except BaseException:
            RECORD["setupLogTail"] = {which: GAMES.log_text(which).splitlines()[-40:] for which in ("host", "client")}
            GAMES.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        RECORD["logsAtEnd"] = {which: checks.launch_counts(GAMES.log_text(which)) for which in ("host", "client")}
        RECORD["loaderLogLines"] = {which: checks.loader_log_lines(GAMES.log_text(which)) for which in ("host", "client")}
        desync.save_game_logs(GAMES, os.path.join(STATE_ROOT, "game_logs"), "friends-zip", cls.__name__)
        GAMES.stop()

    def test_01_launch_logs(self):
        counts = {which: checks.launch_counts(GAMES.log_text(which)) for which in ("host", "client")}
        RECORD["launchCounts"] = counts
        for which, found in counts.items():
            self.assertEqual(found["attackTranspilerSuccess"], 1, "%s: %s" % (which, found))
            self.assertEqual(found["markersNotFound"], 0, which)
            self.assertEqual(found["patchProblemLines"], [], which)

    def test_02_custom_pick_in_the_lobby_path(self):
        host_state, client_state = checks.character_state(self.host), checks.character_state(self.client)
        RECORD["afterLobby"] = {"host": host_state, "client": client_state}
        issues = checks.custom_pick_issues(host_state, client_state, checks.CUSTOM_CHARACTER, CLIENT_BODY, HOST_BODY)
        RECORD["afterLobby"]["issues"] = issues
        self.assertEqual(issues, [])

    def test_03_banded_pvp_with_the_zip_dll(self):
        pvp_banded.reset_launch_state()
        context = pvp_banded.prepare(self.host, self.client)
        pvp_banded.act(self.client, context)
        issues = pvp_banded.check(context)
        RECORD["pvp"] = {"punches": [{"swing": entry["swing"], "hostDelta": entry["hostDelta"], "clientDelta": entry["clientDelta"], "fired": entry["fired"]} for entry in context["measurements"]], "issues": issues}
        self.assertEqual(issues, [])
        landed = [entry for entry in context["measurements"] if entry["hostDelta"] > 0]
        self.assertEqual(len(landed), len(context["measurements"]), RECORD["pvp"])

    def test_04_late_join_with_the_custom_character(self):
        self.client.console("disconnect")
        deadline = time.time() + REJOIN_LEAVE_SECONDS
        while time.time() < deadline and self.client.state()["state"] == "in-world":
            time.sleep(1.0)
        RECORD["rejoin"] = {"stateAfterDisconnect": self.client.state()["state"]}
        time.sleep(3.0)
        self.client.console("connect %s" % SESSION_ADDRESS)
        deadline = time.time() + REJOIN_WAIT_SECONDS
        while time.time() < deadline and self.client.state()["state"] != "in-world":
            checks.select_character(self.client, checks.CUSTOM_CHARACTER)
            try_ready(self.client)
            time.sleep(1.0)
        wait_for_bodies(self.client, 2, WORLD_WAIT_SECONDS)
        self.client.call("close_console")
        time.sleep(SETTLE_SECONDS)
        host_state, client_state = checks.character_state(self.host), checks.character_state(self.client)
        issues = checks.custom_pick_issues(host_state, client_state, checks.CUSTOM_CHARACTER, CLIENT_BODY, HOST_BODY)
        RECORD["rejoin"].update({"host": host_state, "client": client_state, "issues": issues})
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
