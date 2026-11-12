import json
import os
import time

MENU = "static:CasualtiesCharacters.CharacterMenu"
PRE_RUN = "static:PreRunScript"
SCREEN = "static:UnityEngine.Screen"
SLOT_COUNT = 3
SETTLE_SECONDS = 1.2
RESOLUTION_SETTLE_SECONDS = 3.0
ARROW_PREFIX = "PagedCharacterArrow"
EXPECTED_ARROW_LABELS = {"PreviousArrow": "<", "NextArrow": ">"}


def next_page(page, page_count, direction):
    return (page + direction) % page_count


def arrow_label_issues(labels):
    issues = []
    for name, expected in EXPECTED_ARROW_LABELS.items():
        if labels.get(name) != expected:
            issues.append("%s reads %r, expected %r" % (name, labels.get(name), expected))
    return issues


class Verifier:
    def __init__(self, game, actions, screenshot_directory, clock=time.sleep):
        self.game = game
        self.actions = actions
        self.screenshot_directory = screenshot_directory
        self.sleep = clock
        self.results = []

    def read(self, path, target=MENU):
        return self.game.call("get", target=target, path=path, depth=0, nonpublic=True)

    def unity_size(self):
        return (int(self.read("width", SCREEN)), int(self.read("height", SCREEN)))

    def click_at(self, position):
        self.actions.click(position["x"], position["y"], self.unity_size())
        self.sleep(SETTLE_SECONDS)

    def shot(self, name):
        os.makedirs(self.screenshot_directory, exist_ok=True)
        return self.game.call("screenshot", path=os.path.join(self.screenshot_directory, name + ".png"))

    def record(self, label, passed, observed):
        self.results.append({"check": label, "passed": bool(passed), "observed": observed})
        return passed

    def page_state(self):
        return {"page": self.read("view.Page"), "pageCount": self.read("view.Pager.PageCount"), "counter": self.read("view.Counter.text"), "selected": self.read("characterSelected", PRE_RUN)}

    def arrow_labels(self):
        labels = {}
        for member in EXPECTED_ARROW_LABELS:
            try:
                labels[member] = self.read("view.%s.transform.GetChild(0).GetComponentInChildren<TMPro.TMP_Text>().text" % member)
            except Exception:
                labels[member] = self.label_through_find(member)
        return labels

    def label_through_find(self, member):
        wanted = ARROW_PREFIX + EXPECTED_ARROW_LABELS[member]
        for row in self.game.call("find", type="TextMeshProUGUI"):
            handle = "id:%d" % row["object"]["id"]
            try:
                parent = self.game.call("get", target=handle, path="transform.parent.name", depth=0)
                if parent == wanted:
                    return self.game.call("get", target=handle, path="text", depth=0)
            except Exception:
                continue
        return None

    def set_resolution(self, width, height):
        self.game.call("invoke", target=SCREEN, method="SetResolution", args=[width, height, False], types=["Int32", "Int32", "Boolean"])
        self.sleep(RESOLUTION_SETTLE_SECONDS)
        self.actions.focus()

    def click_arrow(self, member, direction, label):
        before = self.page_state()
        self.click_at(self.read("view.%s.transform.position" % member))
        after = self.page_state()
        expected = next_page(before["page"], before["pageCount"], direction)
        self.record(label, after["page"] == expected, {"before": before["page"], "after": after["page"], "expected": expected, "counter": after["counter"]})

    def click_slots(self, size_label):
        for index in range(SLOT_COUNT):
            ids = [self.read("view.Slots[%d].CharacterId" % slot) for slot in range(SLOT_COUNT)]
            if ids[index] < 0:
                continue
            self.click_at(self.read("view.Slots[%d].Root.transform.position" % index))
            selected = self.read("characterSelected", PRE_RUN)
            self.record("%s: clicking slot %d selects it" % (size_label, index), selected == ids[index], {"slotIds": ids, "selected": selected})
            self.shot("%s_slot%d" % (size_label, index))

    def key_paging(self, size_label):
        for key, direction in (("PageDown", 1), ("PageUp", -1)):
            before = self.page_state()
            self.actions.key(key)
            self.sleep(SETTLE_SECONDS)
            after = self.page_state()
            expected = next_page(before["page"], before["pageCount"], direction)
            self.record("%s: real %s key" % (size_label, key), after["page"] == expected, {"before": before["page"], "after": after["page"], "expected": expected})

    def verify_size(self, label, width, height):
        self.set_resolution(width, height)
        self.record("%s: window size" % label, self.unity_size() == (width, height), {"unity": self.unity_size()})
        self.shot("%s_start" % label)
        self.record("%s: arrow labels" % label, not arrow_label_issues(self.arrow_labels()), self.arrow_labels())
        self.click_arrow("NextArrow", 1, "%s: next arrow" % label)
        self.shot("%s_after_next" % label)
        self.click_slots(label)
        self.click_arrow("NextArrow", 1, "%s: next arrow again" % label)
        self.click_arrow("NextArrow", 1, "%s: next arrow wraps to the first page" % label)
        self.click_arrow("PreviousArrow", -1, "%s: previous arrow wraps to the last page" % label)
        self.click_arrow("PreviousArrow", -1, "%s: previous arrow" % label)
        self.key_paging(label)
        self.shot("%s_end" % label)

    def write(self, path):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"passed": sum(1 for row in self.results if row["passed"]), "failed": sum(1 for row in self.results if not row["passed"]), "results": self.results}, handle, indent=1, default=str)
