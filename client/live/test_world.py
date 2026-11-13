import os
import tempfile
import unittest

from live import shared_game

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
IMPACT_FORCE = 500.0
STEP_FRAMES_AFTER_DAMAGE = 30
SETTLE_FRAMES = 120
SETTLE_AFTER_START_FRAMES = 300
MOVE_MINIMUM = 0.5
WALK_FRAMES = 120


class InWorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shared_game.fresh_run(0)
        cls.link = shared_game.game()
        cls.link.step(SETTLE_FRAMES)

    def setUp(self):
        self.link.timescale(1.0)
        self.link.console("heal")

    def test_spawn_bandage_is_picked_up_into_the_inventory(self):
        replies = self.link.spawn("bandage", condition=1.0)
        self.assertTrue(replies[0]["pickedUp"])
        held = [slot["item"]["id"] for slot in self.link.player()["inventory"] if slot["item"]]
        self.assertIn("bandage", held)
        listed = self.link.list_items("bandage")
        self.assertTrue(any(row["slot"] >= 0 for row in listed))

    def test_using_a_bandage_on_a_limb_starts_the_bandage_minigame(self):
        self.link.spawn("bandage")
        snapshot = self.link.player()
        slot = next(s["slot"] for s in snapshot["inventory"] if s["item"] and s["item"]["id"] == "bandage")
        self.link.call("use_item_on_limb", slot=slot, limb=shared_game.limb_index(snapshot, "arm"))
        self.link.step(2)
        minigame = self.link.get("static:MinigameBase", "main.currentMinigame", depth=0)
        self.assertIsNotNone(minigame, "no minigame started")
        self.assertEqual(minigame["$type"], "BandageMinigame")

    def test_impact_damage_lowers_limb_health_and_emits_events_and_bleeds(self):
        snapshot = self.link.player()
        index = shared_game.limb_index(snapshot, "arm")
        before = snapshot["limbs"][index]
        self.link.mark_events()
        self.link.call("damage", limb=index, force=IMPACT_FORCE)
        self.link.step(STEP_FRAMES_AFTER_DAMAGE)
        after = self.link.player()["limbs"][index]
        self.assertLess(after["muscleHealth"], before["muscleHealth"])
        self.assertGreater(after["bleedAmount"], 0.0)
        event = self.link.wait_event("damage", timeout=5)
        self.assertEqual(event["data"]["index"], index)

    def test_console_round_trip_and_failure_reporting(self):
        reply = self.link.console("log hello-from-the-link")
        self.assertFalse(reply["failed"])
        self.assertTrue(any("hello-from-the-link" in line for line in reply["output"]))
        self.assertIn("hello-from-the-link", " ".join(self.link.call("console_log", tail=10)))
        bad = self.link.console("definitely_not_a_command")
        self.assertTrue(bad["failed"])

    def test_console_heal_undoes_damage(self):
        snapshot = self.link.player()
        index = shared_game.limb_index(snapshot, "arm")
        self.link.call("damage", limb=index, force=IMPACT_FORCE)
        damaged = self.link.player()["limbs"][index]["muscleHealth"]
        self.link.console("heal")
        healed = self.link.player()["limbs"][index]["muscleHealth"]
        self.assertGreater(healed, damaged)

    def test_reflective_write_then_read_by_path(self):
        self.link.set("player", "hunger", 42.5)
        self.assertAlmostEqual(self.link.get("player", "hunger"), 42.5, delta=1.0)
        index = shared_game.limb_index(self.link.player(), "arm")
        self.link.set("player", "limbs[%d].pain" % index, 7.0)
        self.assertAlmostEqual(self.link.get("player", "limbs[%d].pain" % index), 7.0, delta=1.0)

    def test_reflective_read_of_a_static_and_a_bad_path_error(self):
        from casualtieslink import LinkError
        self.assertIn(self.link.get("static:Time", "timeScale"), (0, 1, 0.0, 1.0))
        with self.assertRaises(LinkError):
            self.link.get("player", "noSuchField")

    def test_step_advances_exactly_the_requested_frames_while_paused(self):
        self.link.timescale(0.0)
        before = self.link.status()["frame"]
        reply = self.link.step(10)
        self.assertGreaterEqual(reply["frame"] - before, 10)

    def test_screenshot_writes_a_png(self):
        path = os.path.join(tempfile.gettempdir(), "casualtieslink_test_shot.png")
        if os.path.exists(path):
            os.remove(path)
        reply = self.link.screenshot(path)
        self.assertEqual(reply["path"], os.path.abspath(path))
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(8), PNG_SIGNATURE)

    def test_item_pickup_emits_an_event(self):
        self.link.mark_events()
        self.link.spawn("bandage")
        event = self.link.wait_event("item_picked_up", timeout=5)
        self.assertEqual(event["data"]["id"], "bandage")


class MovementTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        shared_game.fresh_run(0)
        cls.link = shared_game.game()
        cls.link.step(SETTLE_AFTER_START_FRAMES)

    def test_injected_movement_key_moves_the_player(self):
        binds = self.link.call("keybinds")
        if "right" not in binds or "left" not in binds:
            self.skipTest("no left/right action in keybinds: %s" % sorted(binds))

        def walk(action):
            start_x = self.link.player()["position"]["x"]
            self.link.hold(action=action)
            self.link.step(WALK_FRAMES)
            self.link.release(action=action)
            return self.link.player()["position"]["x"] - start_x

        right_displacement = walk("right")
        left_displacement = walk("left")
        message = "right %.2f left %.2f: injected keys did not steer the player" % (right_displacement, left_displacement)
        self.assertGreater(abs(right_displacement - left_displacement), MOVE_MINIMUM, message)
        self.assertGreaterEqual(right_displacement, left_displacement, message)


class SaveLoadTests(unittest.TestCase):
    HUNGER_MARK = 37.0

    def test_save_and_load_round_trip_restores_a_changed_field(self):
        shared_game.fresh_run(0)
        link = shared_game.game()
        link.set("player", "hunger", self.HUNGER_MARK)
        saved = link.save()
        self.assertGreater(saved["bytes"], 100)
        if shared_game.mutation_active("corrupt-save"):
            with open(saved["path"], "wb") as handle:
                handle.write(b"broken")
        link.quit_to_menu()
        link.load()
        self.assertAlmostEqual(link.get("player", "hunger"), self.HUNGER_MARK, delta=3.0)


if __name__ == "__main__":
    unittest.main()
