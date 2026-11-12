import os
import tempfile
import unittest

from casualtieslink import oswindow, pagedselect, pagedverify

PREVIOUS = {"x": 50.0, "y": 700.0}
NEXT = {"x": 1230.0, "y": 700.0}
SLOT_POSITIONS = [{"x": 200.0, "y": 300.0}, {"x": 640.0, "y": 300.0}, {"x": 1080.0, "y": 300.0}]


class FakeWorld:
    def __init__(self, arrows_work=True, slots_select_middle=False, labels=("<", ">")):
        self.page = 0
        self.count = 3
        self.selected = 1
        self.arrows_work = arrows_work
        self.slots_select_middle = slots_select_middle
        self.labels = labels
        self.keys = []
        self.size = (1280, 720)
        self.shots = []
        self.slide_open = True
        self.hover_selects = False
        self.back_works = True

    def ids(self):
        return [-1, -1, -1] if self.page == 0 else [3, 62, 99]

    def call(self, command, **arguments):
        if command == "screenshot":
            self.shots.append(arguments["path"])
            return {}
        if command == "invoke":
            self.size = tuple(arguments["args"][:2])
            return None
        if command == "find":
            if arguments["type"] == "UnityEngine.UI.Button":
                return [{"object": {"id": 9, "name": "Start"}, "position": {"x": 441.0, "y": 24.0}}, {"object": {"id": 8, "name": "Back"}, "position": {"x": 65.0, "y": 23.0}},
                        {"object": {"id": 7, "name": "Back"}, "position": {"x": 1230.0, "y": 700.0}}]
            return [{"object": {"id": 1, "name": "x"}}, {"object": {"id": 2, "name": "y"}}]
        path = arguments["path"]
        if path == "instance.charSelectName.text":
            return "name%d" % self.selected
        if path == "view.Slide.gameObject.activeInHierarchy":
            return self.slide_open
        if path in ("width", "height"):
            return self.size[0 if path == "width" else 1]
        if path == "view.Page":
            return self.page
        if path == "view.Pager.PageCount":
            return self.count
        if path == "view.Counter.text":
            return "Page %d / %d" % (self.page + 1, self.count)
        if path == "characterSelected":
            return self.selected
        if path.startswith("view.PreviousArrow.transform.position"):
            return PREVIOUS
        if path.startswith("view.NextArrow.transform.position"):
            return NEXT
        if path.startswith("view.Slots[") and path.endswith("].CharacterId"):
            return self.ids()[int(path[len("view.Slots["):].split("]")[0])]
        if path.startswith("view.Slots[") and path.endswith("Root.transform.position"):
            return SLOT_POSITIONS[int(path[len("view.Slots["):].split("]")[0])]
        if path.startswith("view.PreviousArrow"):
            return self.labels[0]
        if path.startswith("view.NextArrow"):
            return self.labels[1]
        raise RuntimeError("unknown path " + path)

    def click(self, x, y, size):
        if (x, y) == (65.0, 23.0):
            self.slide_open = self.slide_open and not self.back_works
        elif (x, y) == (PREVIOUS["x"], PREVIOUS["y"]) and self.arrows_work:
            self.page = (self.page - 1) % self.count
        elif (x, y) == (NEXT["x"], NEXT["y"]) and self.arrows_work:
            self.page = (self.page + 1) % self.count
        else:
            for index, position in enumerate(SLOT_POSITIONS):
                if (x, y) == (position["x"], position["y"]) and self.page > 0:
                    self.selected = self.ids()[1 if self.slots_select_middle else index]

    def key(self, name):
        self.keys.append(name)
        self.page = (self.page + (1 if name == "PageDown" else -1)) % self.count

    def focus(self):
        return True

    def hover(self, x, y, size):
        if self.hover_selects:
            self.selected = 62


def run(world):
    directory = tempfile.TemporaryDirectory()
    verifier = pagedverify.Verifier(world, world, directory.name, clock=lambda seconds: None)
    verifier.game = world
    verifier.verify_size("r", 1280, 720)
    directory.cleanup()
    return verifier


class VerifierTests(unittest.TestCase):
    def test_a_working_screen_passes_every_check(self):
        verifier = run(FakeWorld())
        self.assertEqual([row for row in verifier.results if not row["passed"]], [])
        self.assertGreaterEqual(len(verifier.results), 10)

    def test_arrows_that_do_nothing_fail_the_arrow_checks(self):
        verifier = run(FakeWorld(arrows_work=False))
        failed = [row["check"] for row in verifier.results if not row["passed"]]
        self.assertTrue(any("next arrow" in name for name in failed), failed)

    def test_every_click_selecting_the_middle_slot_fails_the_left_and_right_slot_checks(self):
        verifier = run(FakeWorld(slots_select_middle=True))
        failed = [row["check"] for row in verifier.results if not row["passed"]]
        self.assertIn("r: clicking slot 0 selects it", failed)
        self.assertIn("r: clicking slot 2 selects it", failed)
        self.assertNotIn("r: clicking slot 1 selects it", failed)

    def test_arrows_that_read_back_fail_the_label_check(self):
        verifier = run(FakeWorld(labels=("Back", "Back")))
        self.assertIn("r: arrow labels", [row["check"] for row in verifier.results if not row["passed"]])

    def test_the_keyboard_checks_press_the_real_keys(self):
        world = FakeWorld()
        run(world)
        self.assertEqual(world.keys, ["PageDown", "PageUp"])

    def test_a_slot_that_selects_on_hover_fails_the_hover_check(self):
        world = FakeWorld()
        world.hover_selects = True
        verifier = run(world)
        failed = [row["check"] for row in verifier.results if not row["passed"]]
        self.assertTrue(any("hovering slot" in name for name in failed), failed)

    def test_the_name_text_check_passes_when_each_click_gives_its_own_name(self):
        verifier = run(FakeWorld())
        row = next(row for row in verifier.results if "name text" in row["check"])
        self.assertTrue(row["passed"])
        self.assertEqual(len(row["observed"]["names"]), 3)

    def test_a_name_text_that_stays_the_same_fails_the_check(self):
        world = FakeWorld(slots_select_middle=True)
        verifier = run(world)
        self.assertIn("r: the name text follows each clicked slot", [row["check"] for row in verifier.results if not row["passed"]])

    def test_the_back_button_check_clicks_the_bottom_bar_button_not_the_arrow_clone(self):
        world = FakeWorld()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        verifier = pagedverify.Verifier(world, world, directory.name, clock=lambda seconds: None)
        self.assertTrue(verifier.click_back("back"))
        self.assertFalse(world.slide_open)

    def test_a_back_button_that_does_nothing_fails(self):
        world = FakeWorld()
        world.back_works = False
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        verifier = pagedverify.Verifier(world, world, directory.name, clock=lambda seconds: None)
        self.assertFalse(verifier.click_back("back"))

    def test_paging_wraps_in_both_directions(self):
        self.assertEqual((pagedverify.next_page(2, 3, 1), pagedverify.next_page(0, 3, -1)), (0, 2))

    def test_the_result_file_counts_passes_and_failures(self):
        verifier = run(FakeWorld(arrows_work=False))
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "out.json")
            verifier.write(path)
            import json
            data = json.load(open(path))
        self.assertEqual(data["passed"] + data["failed"], len(verifier.results))
        self.assertGreater(data["failed"], 0)


class CoordinateTests(unittest.TestCase):
    def test_unity_bottom_up_coordinates_become_desktop_top_down(self):
        self.assertEqual(oswindow.unity_to_screen((100, 200), (1280, 720), (1280, 720), 0, 0), (100, 920))
        self.assertEqual(oswindow.unity_to_screen((100, 200), (1280, 720), (1280, 720), 1280, 720), (1380, 200))

    def test_a_scaled_client_area_scales_the_point(self):
        self.assertEqual(oswindow.unity_to_screen((0, 0), (1920, 1080), (1280, 720), 640, 360), (960, 540))


class LoaderOverrideTests(unittest.TestCase):
    def test_the_loader_dll_replaces_the_one_in_the_copy_and_its_md5_is_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = os.path.join(directory, "copy", "BepInEx", "plugins", "CasualtiesCharacters")
            os.makedirs(folder)
            with open(os.path.join(folder, "CasualtiesCharacters.dll"), "wb") as handle:
                handle.write(b"old")
            source = os.path.join(directory, "new.dll")
            with open(source, "wb") as handle:
                handle.write(b"new")
            md5 = pagedselect.install_loader_dll(os.path.join(directory, "copy"), source)
            self.assertEqual(open(os.path.join(folder, "CasualtiesCharacters.dll"), "rb").read(), b"new")
            self.assertEqual(md5, pagedselect.friendszip.md5_of_bytes(b"new"))

    def test_a_copy_without_a_loader_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "new.dll")
            open(source, "wb").write(b"new")
            with self.assertRaises(FileNotFoundError):
                pagedselect.install_loader_dll(os.path.join(directory, "copy"), source)


if __name__ == "__main__":
    unittest.main()
