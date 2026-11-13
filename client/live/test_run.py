import unittest

from casualtieslink.commands import CHARACTERS

from live import shared_game


class StartRunTests(unittest.TestCase):
    def _assert_character(self, character):
        reply = shared_game.fresh_run(character)
        self.assertIn(CHARACTERS[character].lower(), reply["prefab"].lower())
        self.assertEqual(reply["state"], "in-world")
        link = shared_game.game()
        self.assertEqual(link.get("static:PreRunScript", "characterSelected"), character)
        self.assertTrue(link.player()["alive"])

    def test_character_0_spawns_experiment(self):
        self._assert_character(0)

    def test_character_1_spawns_milky(self):
        self._assert_character(1)

    def test_character_2_spawns_dune(self):
        self._assert_character(2)

    def test_start_run_outside_the_menu_is_an_error(self):
        from casualtieslink import LinkError
        shared_game.fresh_run(0)
        with self.assertRaises(LinkError):
            shared_game.game().start_run(0)

    def test_quit_to_menu_returns_to_the_menu_and_emits_scene_change(self):
        shared_game.fresh_run(0)
        link = shared_game.game()
        link.mark_events()
        link.quit_to_menu()
        self.assertEqual(link.state()["state"], "menu")
        event = link.wait_event("scene_changed", timeout=5)
        self.assertEqual(event["data"]["to"], "PreGen")


if __name__ == "__main__":
    unittest.main()
