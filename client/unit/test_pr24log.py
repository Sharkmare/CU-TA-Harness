import unittest

from casualtieslink import pr24log

HOOK_BODY = "hook#0(Body_HostD tag=Player at=1.0,2.0 dist=1.5 building=False body=True took=True breakLoop=False block=False)"
HOOK_GROUND = "hook#1(Ground tag=Untagged at=1.0,1.0 dist=2.0 building=False body=False took=False breakLoop=False block=False)"
LOG = "\n".join([
    "[Info   :  Together] noise",
    "[Info   :  Together] [PR24V] swing=1 t=10.5 result=True hookCalls=2 vanillaBlockDamages=0 lastHitWasBlock=False lastHitPos=1.0,2.0 attackerPos=0.0,0.0 " + HOOK_BODY + " " + HOOK_GROUND,
    "[Info   :  Together] [PR24V] swing=2 t=11.0 result=True hookCalls=1 vanillaBlockDamages=1 lastHitWasBlock=True lastHitPos=1.0,1.0 attackerPos=0.0,0.0",
    " hook#0(Block tag=Untagged at=1.0,1.0 dist=1.5 building=False body=False took=False breakLoop=True block=True)",
    " damageBlock(pos=1.0,1.0 dmg=19.33 total=19.33)",
    "[Info   :  Together] [PR24V] swing=3 t=11.5 result=False hookCalls=0 vanillaBlockDamages=0 lastHitWasBlock=False lastHitPos=0,0 attackerPos=0.0,0.0 cooldownAfter=1.05 animal(Rat at=2.0,3.0 cantHit=False) animal(Bird at=4.0,5.0 cantHit=True)",
    ""])


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.swings = pr24log.parse_swings(LOG)

    def test_each_header_line_becomes_one_swing(self):
        self.assertEqual([s["swing"] for s in self.swings], [1, 2, 3])
        self.assertEqual((self.swings[0]["t"], self.swings[0]["result"], self.swings[2]["result"]), (10.5, True, False))

    def test_hooks_on_the_same_line_are_parsed_with_their_flags(self):
        hooks = self.swings[0]["hooks"]
        self.assertEqual(len(hooks), 2)
        self.assertEqual((hooks[0]["collider"], hooks[0]["tag"], hooks[0]["body"], hooks[0]["took"]), ("Body_HostD", "Player", True, True))
        self.assertFalse(hooks[1]["took"])

    def test_continuation_lines_belong_to_the_swing_above(self):
        self.assertEqual(len(self.swings[1]["hooks"]), 1)
        self.assertTrue(self.swings[1]["hooks"][0]["block"])
        self.assertEqual(self.swings[1]["damageBlocks"], [{"pos": "1.0,1.0", "dmg": "19.33", "total": "19.33"}])

    def test_cooldown_and_animals_are_parsed_and_default_to_none_and_empty(self):
        self.assertIsNone(self.swings[0]["cooldownAfter"])
        self.assertEqual(self.swings[0]["animals"], [])
        self.assertEqual(self.swings[2]["cooldownAfter"], 1.05)
        self.assertEqual(self.swings[2]["animals"], [{"name": "Rat", "at": "2.0,3.0", "cantHit": False}, {"name": "Bird", "at": "4.0,5.0", "cantHit": True}])

    def test_animals_on_a_continuation_line_belong_to_the_swing_above(self):
        swings = pr24log.parse_swings(LOG + " animal(Dog at=1.0,1.0 cantHit=False)\n")
        self.assertEqual([a["name"] for a in swings[2]["animals"]], ["Rat", "Bird", "Dog"])

    def test_intervals_between_swings_are_their_time_differences(self):
        summary = pr24log.summarise(pr24log.parse_swings(LOG))
        self.assertEqual(summary["firstIntervals"], [0.5, 0.5])
        self.assertEqual(summary["meanInterval"], 0.5)
        self.assertEqual((summary["tookInFirstFourSwings"], summary["swingsWithAnimalsNear"], summary["animalNames"], summary["cooldownAfterFirstFour"]), (1, 1, ["Bird", "Rat"], [None, None, 1.05]))

    def test_lines_without_the_prefix_are_ignored(self):
        self.assertEqual(pr24log.parse_swings("nothing here\n " + HOOK_BODY), [])


class SummaryTests(unittest.TestCase):
    def test_a_swing_spent_on_a_body_counts_as_took_true_with_no_block_damage(self):
        summary = pr24log.summarise(pr24log.parse_swings(LOG))
        self.assertEqual((summary["swings"], summary["swingsWithTookTrue"], summary["swingsWithNoVanillaBlockDamage"], summary["noDamageAndNoTook"]), (3, 1, 2, 1))
        self.assertEqual((summary["firstDamagingSwing"], summary["tookColliders"]), (1, ["Body_HostD/Player"]))

    def test_the_log_is_split_by_the_swings_each_run_fired_and_leftovers_are_counted(self):
        runs, leftover = pr24log.split_by_counts(pr24log.parse_swings(LOG), [1, 1])
        self.assertEqual(([len(r) for r in runs], leftover), ([1, 1], 1))


if __name__ == "__main__":
    unittest.main()
