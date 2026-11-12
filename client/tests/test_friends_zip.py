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
LEAVE_SECONDS = 30.0
RECONNECT_PAUSE_SECONDS = 3.0
HOST_BODY = "Body_HostD"
CLIENT_BODY = "Body_ClientD"
LOADER_ATTACH_LINE = "attached to " + CLIENT_BODY
EXPECTED_ZIP_MD5 = "59a9201fa7a5598d2be75db0df36ae72"
EXPECTED_TOGETHER_MD5 = "603694c113ebcc11d92101b7716b0aa2"
EXPECTED_TOGETHER_LABEL = "5.5.0+chars.2"
TOGETHER_DLL_IN_ZIP = "BepInEx/plugins/Together/CasualtiesMP.dll"
PVP_ACCEPT_RANGE = (2.0, 3.6)
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
        RECORD["lookupErrors"] = sorted(set(checks.LOOKUP_ERRORS))[:30]
        with open(os.path.join(REPORT_DIRECTORY, "friends_zip.json"), "w", encoding="utf-8") as handle:
            json.dump(RECORD, handle, indent=2, default=str)
    if GAMES is not None:
        GAMES.dispose()


def chooser(character_id):
    return lambda game: checks.select_character(game, character_id)


def in_world(game):
    try:
        return game.state()["state"] == "in-world"
    except Exception:
        return False


def enter_world(game, expected_bodies):
    game.wait_state("in-world", timeout=WORLD_WAIT_SECONDS)
    wait_for_bodies(game, expected_bodies, WORLD_WAIT_SECONDS)
    game.call("close_console")


def both_states(host, client):
    return checks.character_state(host), checks.character_state(client)


def sync_readings(host_state, client_state, expected):
    return {"host": checks.sync_body_issues(host_state, expected), "client": checks.sync_body_issues(client_state, expected)}


def attach_lines(game_name):
    return GAMES.log_text(game_name).count(LOADER_ATTACH_LINE)


def leave_and_reconnect(client, repick):
    client.console("disconnect")
    deadline = time.time() + LEAVE_SECONDS
    while time.time() < deadline and in_world(client):
        time.sleep(1.0)
    left = client.state()["state"]
    time.sleep(RECONNECT_PAUSE_SECONDS)
    client.console("connect %s" % SESSION_ADDRESS)
    attempts = checks.join_attempts(client, checks.CUSTOM_CHARACTER, try_ready, repick=repick, in_world=in_world)
    wait_for_bodies(client, 2, WORLD_WAIT_SECONDS)
    client.call("close_console")
    time.sleep(SETTLE_SECONDS)
    return {"stateAfterDisconnect": left, "attemptCount": len(attempts), "firstAttempts": attempts[:3], "lastAttempts": attempts[-3:], "repicked": repick}


@unittest.skipUnless(PAIR_ENABLED, SKIP_REASON)
class FriendsZipLobbyCheck(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        RECORD["zip"] = {"md5": friendszip.md5_of_file(friendszip.default_zip_path())}
        if RECORD["zip"]["md5"] != EXPECTED_ZIP_MD5:
            raise AssertionError("the zip is not the verification zip %s: %s" % (EXPECTED_ZIP_MD5, RECORD["zip"]["md5"]))
        cls.host = GAMES.start_host_alone([], FRIENDS_ZIP_CHOICE, host_extra=checks.PVP_RULE_ARGUMENTS)
        cls.client = None
        matches = friendszip.verify_copy(friendszip.default_zip_path(), GAMES.host_copy)
        RECORD["zip"]["hostCopyDllMatches"] = {"allMatch": all(matches.values()), "dllCount": len(matches)}
        RECORD["zip"]["togetherDllMd5InHostCopy"] = friendszip.md5_of_file(os.path.join(GAMES.host_copy, *TOGETHER_DLL_IN_ZIP.split("/")))
        if RECORD["zip"]["togetherDllMd5InHostCopy"] != EXPECTED_TOGETHER_MD5:
            raise AssertionError("the Together DLL in the host copy is %s, expected %s" % (RECORD["zip"]["togetherDllMd5InHostCopy"], EXPECTED_TOGETHER_MD5))
        RECORD["pluginFoldersInHostCopy"] = sorted(friendszip.plugin_names_in_copy(GAMES.host_copy))
        try:
            RECORD["hostAlone"] = {"readyAccepted": ready_up([cls.host], before_ready={cls.host: chooser(checks.EXPERIMENT_CHARACTER)})}
            enter_world(cls.host, 1)
            time.sleep(SETTLE_SECONDS)
        except BaseException:
            RECORD["setupLogTail"] = GAMES.log_text("host").splitlines()[-40:]
            GAMES.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        RECORD["logsAtEnd"] = {which: checks.launch_counts(GAMES.log_text(which)) for which in ("host", "client")}
        RECORD["loaderLogLines"] = {which: checks.loader_log_lines(GAMES.log_text(which)) for which in ("host", "client")}
        RECORD["fingerprints"] = {which: checks.fingerprints(GAMES.log_text(which)) for which in ("host", "client")}
        desync.save_game_logs(GAMES, os.path.join(STATE_ROOT, "game_logs"), "friends-zip", cls.__name__)
        GAMES.stop()

    def test_01_true_late_join_with_the_custom_pick(self):
        RECORD["hostLaunchCounts"] = checks.launch_counts(GAMES.log_text("host"))
        RECORD["togetherLabelLineOnHost"] = ("Plugin CasualtiesMP version %s is loaded" % EXPECTED_TOGETHER_LABEL) in GAMES.log_text("host")
        type(self).client = GAMES.start_client_later([], FRIENDS_ZIP_CHOICE, client_extra=checks.PVP_RULE_ARGUMENTS)
        matches = friendszip.verify_copy(friendszip.default_zip_path(), GAMES.client_copy)
        RECORD["lateJoin"] = {"path": "pick path: PreRunScript.SelectCharacter(3) before every ready try, no --mp-mychar", "clientCopyDllMatches": all(matches.values()),
                              "pagerBeforePick": checks.pager_state(self.client)}
        first = checks.select_character(self.client, checks.CUSTOM_CHARACTER)
        RECORD["lateJoin"].update({"firstPick": first, "pagerAfterPick": checks.pager_state(self.client)})
        attempts = checks.join_attempts(self.client, checks.CUSTOM_CHARACTER, try_ready, repick=True, in_world=in_world)
        RECORD["lateJoin"].update({"attemptCount": len(attempts), "firstAttempts": attempts[:3], "lastAttempts": attempts[-3:]})
        enter_world(self.client, 2)
        wait_for_bodies(self.host, 2, WORLD_WAIT_SECONDS)
        time.sleep(SETTLE_SECONDS)
        expected = {CLIENT_BODY: checks.CUSTOM_CHARACTER, HOST_BODY: checks.EXPERIMENT_CHARACTER}
        host_state, client_state = both_states(self.host, self.client)
        issues = checks.pick_issues(host_state, client_state, expected)
        RECORD["lateJoin"].update({"host": host_state, "client": client_state, "issues": issues, "syncBodyCustomIdPresent": sync_readings(host_state, client_state, expected),
                                   "loaderAttachLineOnClient": LOADER_ATTACH_LINE in GAMES.log_text("client"), "loaderAttachLineOnHost": LOADER_ATTACH_LINE in GAMES.log_text("host")})
        self.assertEqual(issues, [])
        self.assertTrue(RECORD["lateJoin"]["loaderAttachLineOnClient"])

    def test_02_banded_pvp_from_the_late_client(self):
        pvp_banded.reset_launch_state()
        context = pvp_banded.prepare(self.host, self.client)
        pvp_banded.act(self.client, context, accept_range=PVP_ACCEPT_RANGE)
        issues = pvp_banded.check(context)
        RECORD["pvp"] = {"punches": [{"swing": entry["swing"], "hostDelta": entry["hostDelta"], "clientDelta": entry["clientDelta"], "fired": entry["fired"], "distance": entry["geometry"]["distance"],
                                      "acceptedOutsideBand": entry["band"].get("acceptedOutsideBand"), "bandDistances": entry["band"]["distances"]} for entry in context["measurements"]], "issues": issues,
                         "acceptRange": PVP_ACCEPT_RANGE}
        self.assertEqual(issues, [])
        self.assertEqual(len([entry for entry in context["measurements"] if entry["hostDelta"] > 0]), len(context["measurements"]), RECORD["pvp"])

    def test_03_launch_log_counts(self):
        counts = {which: checks.launch_counts(GAMES.log_text(which)) for which in ("host", "client")}
        RECORD["launchCounts"] = counts
        for which, found in counts.items():
            self.assertEqual(found["markersNotFound"], 0, which)
            self.assertGreaterEqual(found["attackTranspilerSuccess"], 1, which)

    def test_04_rejoin_without_a_repick(self):
        attaches_before = attach_lines("client")
        RECORD["rejoinNoRepick"] = leave_and_reconnect(self.client, repick=False)
        host_state, client_state = both_states(self.host, self.client)
        issues = checks.pick_issues(host_state, client_state, {CLIENT_BODY: checks.CUSTOM_CHARACTER, HOST_BODY: checks.EXPERIMENT_CHARACTER})
        attaches_after = attach_lines("client")
        if attaches_after <= attaches_before:
            issues.append("the loader attach line did not appear again on the client (%d before, %d after)" % (attaches_before, attaches_after))
        RECORD["rejoinNoRepick"].update({"host": host_state, "client": client_state, "clientOwnTag": client_state["tags"].get(CLIENT_BODY), "hostTagOfClient": host_state["tags"].get(CLIENT_BODY),
                                         "clientCharacterSelected": client_state["characterSelected"], "attachLinesOnClientBeforeAfter": [attaches_before, attaches_after],
                                         "bodyBuiltOrCharacterChanged": "not observable through the link; the loader attaches on those events, so a new attach line is the evidence", "issues": issues})
        self.assertEqual(issues, [])

    def test_05_rejoin_with_an_explicit_repick(self):
        attaches_before = attach_lines("client")
        RECORD["rejoinWithRepick"] = leave_and_reconnect(self.client, repick=True)
        host_state, client_state = both_states(self.host, self.client)
        issues = checks.pick_issues(host_state, client_state, {CLIENT_BODY: checks.CUSTOM_CHARACTER, HOST_BODY: checks.EXPERIMENT_CHARACTER})
        attaches_after = attach_lines("client")
        if attaches_after <= attaches_before:
            issues.append("the loader attach line did not appear again on the client (%d before, %d after)" % (attaches_before, attaches_after))
        RECORD["rejoinWithRepick"].update({"host": host_state, "client": client_state, "clientOwnTag": client_state["tags"].get(CLIENT_BODY), "attachLinesOnClientBeforeAfter": [attaches_before, attaches_after], "issues": issues})
        self.assertEqual(issues, [])

    def test_06_reverse_host_custom_client_plain(self):
        RECORD["logsBeforeReverse"] = {which: checks.launch_counts(GAMES.log_text(which)) for which in ("host", "client")}
        desync.save_game_logs(GAMES, os.path.join(STATE_ROOT, "game_logs"), "friends-zip", "first-pair")
        GAMES.stop()
        type(self).host, type(self).client = GAMES.start([], [], together=FRIENDS_ZIP_CHOICE, host_extra=checks.PVP_RULE_ARGUMENTS, client_extra=checks.PVP_RULE_ARGUMENTS)
        accepted = ready_up([self.host, self.client], before_ready={self.host: chooser(checks.CUSTOM_CHARACTER), self.client: chooser(checks.EXPERIMENT_CHARACTER)})
        RECORD["reverse"] = {"readyAccepted": accepted}
        self.assertTrue(accepted)
        enter_world(self.host, 2)
        enter_world(self.client, 2)
        time.sleep(SETTLE_SECONDS)
        expected = {HOST_BODY: checks.CUSTOM_CHARACTER, CLIENT_BODY: checks.EXPERIMENT_CHARACTER}
        host_state, client_state = both_states(self.host, self.client)
        issues = checks.pick_issues(host_state, client_state, expected)
        RECORD["reverse"].update({"host": host_state, "client": client_state, "issues": issues, "syncBodyCustomIdPresent": sync_readings(host_state, client_state, expected),
                                  "loaderAttachLineOnHost": "attached to " + HOST_BODY in GAMES.log_text("host")})
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
