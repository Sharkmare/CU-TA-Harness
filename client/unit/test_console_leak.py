import json
import unittest
from unittest import mock

from tests import console_leak as leak
from tests import desync_scenarios as scenarios

USER_NAME = "secretperson"
SAVE_LINE = "[<color=red>SERVER</color>] MP: SAVING TO FILE: C:/Users/%s/AppData/LocalLow/Orsoniks/CasualtiesUnknown/mp_save/abc.sv" % USER_NAME
HOST_SAVE_LINE = "MP: SAVING TO FILE: C:/Users/%s/AppData/LocalLow/Orsoniks/CasualtiesUnknown/mp_save/abc.sv" % USER_NAME


class FakeLogs:
    def __init__(self):
        self.text = {"host": "", "client": ""}

    def read(self, which):
        return self.text[which]


class FakeGame:
    def __init__(self, name, logs, consoles):
        self.name = name
        self.logs = logs
        self.consoles = consoles
        self.calls = []
        self.save_raises = None
        self.console_output = {}
        self.read_error = None

    def call(self, command, **arguments):
        self.calls.append((command, arguments))
        if command == "console_log":
            if self.read_error:
                raise RuntimeError(self.read_error)
            return list(self.consoles[self.name])
        if command == "save":
            if self.save_raises:
                raise self.save_raises
            self.on_save()
            return {"path": "C:/Users/%s/AppData/LocalLow/x/save.sv" % USER_NAME, "bytes": 1}
        if command == "console":
            return self.console_output.get(arguments["line"].split(" ")[0], {"output": [], "failed": False})
        raise AssertionError(command)


class World(unittest.TestCase):
    def setUp(self):
        self.logs = FakeLogs()
        self.consoles = {"host": [], "client": []}
        self.host = FakeGame("host", self.logs, self.consoles)
        self.client = FakeGame("client", self.logs, self.consoles)
        self.admin = False
        self.leaks_to_normal = False
        self.admin_accepted = True
        self.host.on_save = self.on_save
        self.host.console_output = {leak.HOST_PASSWORD_COMMAND: {"output": ["MP: Set server admin password."], "failed": False}}
        self.client.console_output = {leak.CLIENT_ADMIN_COMMAND: {"output": ["Requesting admin console: True"], "failed": False}}
        original_client_call = self.client.call

        def client_call(command, **arguments):
            if command == "console" and arguments["line"].startswith(leak.CLIENT_ADMIN_COMMAND) and self.admin_accepted:
                self.admin = True
                self.logs.text["host"] += "[Info] [ADMIN] ClientD ENTERS server console! (Entered correct password)\n"
            return original_client_call(command, **arguments)

        self.client.call = client_call
        clock = [0.0]
        patches = [mock.patch.object(leak.evidence, "read_log", self.logs.read), mock.patch.object(leak.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)),
                   mock.patch.object(leak.time, "time", lambda: clock[0])]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def on_save(self):
        self.consoles["host"].append(HOST_SAVE_LINE)
        self.logs.text["host"] += "[Info] %s\n" % HOST_SAVE_LINE
        if self.admin or self.leaks_to_normal:
            self.consoles["client"].append(SAVE_LINE)

    def run_scenario(self):
        context = leak.prepare(self.host, self.client)
        leak.act(self.client, context)
        return context, leak.check(context)


class ClaimTests(World):
    def test_the_claim_holds_when_only_the_admin_client_receives_the_line(self):
        context, issues = self.run_scenario()
        self.assertEqual(issues, [])
        normal, admin = context["target"]["normal"], context["target"]["admin"]
        self.assertEqual((normal["client"]["savingToFileLines"], normal["clientLogSavingLines"], normal["host"]["savingToFileLines"]), (0, 0, 1))
        self.assertEqual((admin["client"]["savingToFileLines"], admin["client"]["savingLinesWithServerPrefix"]), (1, 1))

    def test_the_admin_line_is_described_by_booleans_for_the_host_folders_only(self):
        context, issues = self.run_scenario()
        contains = context["target"]["admin"]["client"]["savingLinesContain"]
        self.assertEqual(contains, {"AppData": True, "LocalLow": True, "mp_save": True, "Users": True})

    def test_a_line_that_reaches_the_normal_client_refutes_the_claim_and_the_test_fails(self):
        self.leaks_to_normal = True
        context, issues = self.run_scenario()
        self.assertTrue(any(issue.startswith("CLAIM REFUTED") for issue in issues), issues)
        self.assertEqual(context["target"]["normal"]["client"]["savingToFileLines"], 1)

    def test_a_save_line_in_the_normal_clients_own_log_also_refutes_it(self):
        original = self.host.on_save

        def save_with_client_log():
            original()
            self.logs.text["client"] += "[Info] %s\n" % HOST_SAVE_LINE

        self.host.on_save = save_with_client_log
        context, issues = self.run_scenario()
        self.assertTrue(any(issue.startswith("CLAIM REFUTED") for issue in issues))
        self.assertEqual(context["target"]["normal"]["clientLogSavingLines"], 1)

    def test_an_admin_client_that_still_gets_nothing_is_reported_as_the_claim_not_shown(self):
        original = self.host.on_save

        def save_without_admin_delivery():
            self.consoles["host"].append(HOST_SAVE_LINE)
            self.logs.text["host"] += "[Info] %s\n" % HOST_SAVE_LINE

        self.host.on_save = save_without_admin_delivery
        context, issues = self.run_scenario()
        self.assertTrue(any(issue.startswith("CLAIM NOT SHOWN") for issue in issues), issues)

    def test_a_denied_admin_request_is_invalid_and_no_admin_phase_runs(self):
        self.admin_accepted = False
        context, issues = self.run_scenario()
        self.assertTrue(any("never showed the client entering the server console" in issue for issue in issues))
        self.assertIsNone(context["target"]["admin"])
        self.assertEqual(len([call for call in self.host.calls if call[0] == "save"]), 1)

    def test_a_save_trigger_that_logs_nothing_on_the_host_makes_the_normal_phase_invalid(self):
        self.host.on_save = lambda: None
        context, issues = self.run_scenario()
        self.assertTrue(any(issue.startswith("INVALID: no SAVING TO FILE line on the host console") for issue in issues))

    def test_an_unreadable_client_console_is_invalid_not_a_pass(self):
        self.client.read_error = "no console"
        context, issues = self.run_scenario()
        self.assertTrue(issues[0].startswith("INVALID: the client console could not be read"))

    def test_the_control_is_the_same_trigger_before_and_after_the_admin_switch(self):
        context, issues = self.run_scenario()
        saves = [call for call in self.host.calls if call[0] == "save"]
        self.assertEqual(len(saves), 2)
        self.assertEqual([entry["phase"] for entry in context["measurements"]], ["normal-client", "admin-switch", "admin-client"])


class RedactionTests(World):
    def test_the_user_name_and_the_path_never_appear_in_the_recorded_measurements(self):
        self.leaks_to_normal = True
        context, issues = self.run_scenario()
        text = json.dumps(context["measurements"]) + json.dumps(context["target"])
        self.assertNotIn(USER_NAME, text)
        self.assertNotIn("C:/Users", text)
        self.assertNotIn("abc.sv", text)

    def test_a_save_reply_with_the_path_and_an_error_that_names_it_are_not_kept(self):
        self.host.save_raises = FileNotFoundError("Could not find file 'C:/Users/%s/AppData/LocalLow/x/save.sv'" % USER_NAME)
        self.host.on_save = self.on_save
        original_call = self.host.call

        def call(command, **arguments):
            if command == "save":
                self.on_save()
                raise self.host.save_raises
            return original_call(command, **arguments)

        self.host.call = call
        context, issues = self.run_scenario()
        text = json.dumps(context["measurements"])
        self.assertNotIn(USER_NAME, text)
        self.assertEqual(context["target"]["normal"]["saveReply"], {"replied": False, "errorType": "FileNotFoundError"})
        self.assertEqual(issues, [])

    def test_the_password_is_not_recorded(self):
        context, issues = self.run_scenario()
        password_line = [call for call in self.host.calls if call[0] == "console"][0][1]["line"]
        password = password_line.split(" ", 1)[1]
        self.assertGreaterEqual(len(password), 8)
        self.assertNotIn(password, json.dumps(context["measurements"]))

    def test_other_host_lines_with_paths_are_counted_by_marker_without_their_text(self):
        self.consoles["client"].append("[<color=red>SERVER</color>] MP: Loaded settings from C:/Users/%s/AppData/Roaming/x.cfg" % USER_NAME)
        lines, error = leak.console_lines(self.client)
        description = leak.describe_lines(lines)
        self.assertEqual(description["serverPrefixedLines"], 1)
        self.assertTrue(description["serverLinesContain"]["Users"])
        self.assertNotIn(USER_NAME, json.dumps(description))


class DescribeTests(unittest.TestCase):
    def test_lines_without_the_save_marker_count_zero(self):
        self.assertEqual(leak.describe_lines(["hello"])["savingToFileLines"], 0)

    def test_a_server_prefixed_line_is_counted_apart_from_a_plain_one(self):
        description = leak.describe_lines([SAVE_LINE, HOST_SAVE_LINE])
        self.assertEqual((description["savingToFileLines"], description["savingLinesWithServerPrefix"]), (2, 1))


class WiringTests(unittest.TestCase):
    def test_the_scenario_is_alone_in_its_own_startup_group_and_selectable(self):
        self.assertEqual(scenarios.matching_scenario_names(["consoleleak"]), ["consoleleak_save_line_by_client"])
        self.assertEqual(sorted(scenarios.counts_by_group(["consoleleak"])), ["console-leak"])

    def test_the_group_starts_both_games_with_no_extra_flags(self):
        from tests import test_desync
        self.assertEqual((test_desync.GROUP_HOST_ARGUMENTS["console-leak"], test_desync.GROUP_CLIENT_ARGUMENTS["console-leak"]), ([], []))
        self.assertNotIn("console-leak", test_desync.GROUP_CLIENT_CHARACTER)

    def test_the_preflight_passes_and_ignores_other_launches(self):
        self.assertEqual(leak.preflight(["consoleleak"], 1), [])
        self.assertEqual(leak.preflight(["spawned_crate"], 1), [])

    def test_the_official_build_runs_it_without_the_probe(self):
        from tests import test_desync
        self.assertIn("official-5.5.0", test_desync.BUILDS_WITHOUT_PROBE)


if __name__ == "__main__":
    unittest.main()
