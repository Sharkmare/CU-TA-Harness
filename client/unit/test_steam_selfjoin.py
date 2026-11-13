import importlib.util
import os
import tempfile
import unittest

TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools", "steam_selfjoin.py")
spec = importlib.util.spec_from_file_location("steam_selfjoin", TOOL)
selfjoin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selfjoin)

GOOD_DECOMPILE = "class T {\n\tinternal bool CreateLobby(ELobbyType lobbyType)\n\t{\n\t\tSteamAPICall_t h = SteamMatchmaking.CreateLobby(lobbyType, Multiplayer.PLAYER_COUNT_LIMIT);\n\t}\n}"
FORCED_DECOMPILE = "class T {\n\tinternal bool CreateLobby(ELobbyType lobbyType)\n\t{\n\t\tlobbyType = ELobbyType.k_ELobbyTypePublic;\n\t\tSteamAPICall_t h = SteamMatchmaking.CreateLobby(lobbyType, 4);\n\t}\n}"


class StageSafetyTests(unittest.TestCase):
    def stage(self):
        directory = tempfile.mkdtemp()
        folder = os.path.join(directory, "plugins", "Together")
        os.makedirs(folder)
        open(os.path.join(folder, "CasualtiesMP.dll"), "wb").write(b"x")
        return directory

    def test_a_stage_that_passes_the_requested_lobby_type_through_is_accepted(self):
        self.assertEqual(selfjoin.stage_problems(self.stage(), lambda dll, name: GOOD_DECOMPILE), [])

    def test_a_stage_that_forces_a_public_lobby_is_refused(self):
        self.assertEqual(selfjoin.stage_problems(self.stage(), lambda dll, name: FORCED_DECOMPILE), ["CreateLobby of this stage forces a public lobby"])

    def test_a_missing_dll_or_a_missing_method_is_refused(self):
        self.assertEqual(len(selfjoin.stage_problems(tempfile.mkdtemp(), lambda dll, name: GOOD_DECOMPILE)), 1)
        self.assertEqual(len(selfjoin.stage_problems(self.stage(), lambda dll, name: "class T {}")), 1)

    def test_a_create_lobby_that_ignores_the_requested_type_is_refused(self):
        text = "class T {\n\tinternal bool CreateLobby(ELobbyType lobbyType)\n\t{\n\t\tSteamMatchmaking.CreateLobby(other, 4);\n\t}\n}"
        self.assertEqual(selfjoin.stage_problems(self.stage(), lambda dll, name: text), ["CreateLobby does not pass the requested lobby type through"])


class ArgumentTests(unittest.TestCase):
    def test_the_host_hosts_a_private_lobby_with_a_password(self):
        arguments = selfjoin.host_arguments("pw")
        self.assertEqual(arguments[arguments.index("--mp-hoststeam") + 1], "private")
        self.assertEqual(arguments[arguments.index("--mp-setpass") + 1], "pw")
        self.assertNotIn("public", arguments)

    def test_the_client_has_the_password_and_no_nosteam_flag(self):
        arguments = selfjoin.client_arguments("pw")
        self.assertIn("--mp-setpass", arguments)
        self.assertNotIn("--mp-nosteam", arguments)

    def test_only_a_readable_nonzero_lobby_type_aborts(self):
        self.assertFalse(selfjoin.lobby_type_is_not_private(0))
        self.assertTrue(selfjoin.lobby_type_is_not_private(2))
        self.assertTrue(selfjoin.lobby_type_is_not_private(1))
        self.assertFalse(selfjoin.lobby_type_is_not_private({"unreadable": "x"}))


class LogReadingTests(unittest.TestCase):
    def test_the_lobby_id_is_the_eighteen_digit_number_on_a_lobby_line(self):
        text = "noise 109775240000000001\nSTEAM: [513 - LobbyCreated] - k_EResultOK -- 109775241234567890\n"
        self.assertEqual(selfjoin.lobby_id_from_text(text), 109775241234567890)
        self.assertIsNone(selfjoin.lobby_id_from_text("nothing here"))

    def test_the_steps_list_the_first_matching_lines_per_side(self):
        logs = {"host": "a\nSTEAM: Accepting connection 1\nConnection closed for x\n", "client": "b\n"}
        steps = selfjoin.steps_from_logs(logs)
        self.assertEqual(steps["p2p connect"]["host"], ["STEAM: Accepting connection 1"])
        self.assertEqual(steps["p2p connect"]["client"], [])
        self.assertEqual(steps["connection closed"]["host"], ["Connection closed for x"])


if __name__ == "__main__":
    unittest.main()
