import unittest

from casualtieslink import diagblock

STATE = "cd=0.2 cons=100 overEnc=0 stim=0 stamina=95 conscious=True pos=(0,1) limb1=(0.2,1) look=(1,1) handSlot=0 holding=False"
HOST_STATE = "cd=0 cons=%s overEnc=0 stim=0 stamina=95 conscious=True pos=(0,1) limb1=(0.2,1) look=(1,1) handSlot=0 holding=False"


def client_line(t, seq, cons="100"):
    return "[Info   :  Together] [diagblock] t=%s CLIENT_SEND seq=%d victim=blk latchedBlock=True hitPos=(1,1) atkCooldown=0.2 %s" % (t, seq, STATE.replace("cons=100", "cons=" + cons))


def recv(t, n, cons="100"):
    return "[Info   :  Together] [diagblock] t=%s HOST_RECV n=%d client=2 worldReady=True gotAttacker=True awake=True %s" % (t, n, HOST_STATE % cons)


def parsed(t, seq):
    return "[Info   :  Together] [diagblock] t=%s HOST_PARSED seq=%d didhit=True hitobj=blk isBlock=True isNothing=False hitPos=(1,1)" % (t, seq)


def decided(t, seq, reason, counter="19.33", health="60"):
    return ("[Info   :  Together] [diagblock] t=%s HOST_DECIDED seq=%d block %s attackpower=19.33 counter=%s blockId=8 health=%s dLimb=1 totals applied=1 missed=0"
            % (t, seq, reason, counter, health))


def after(t, seq):
    return "[Info   :  Together] [diagblock] t=%s HOST_AFTER seq=%d copy cd=0.18" % (t, seq)


def refuse(t):
    return "[Info   :  Together] [diagblock] t=%s HOST_REFUSE cooldown copy=0.31 refusedTotal=1" % t


CLIENT_LOG = "\n".join(["noise", client_line("10.0", 1), client_line("10.3", 2), client_line("10.6", 3, cons="90"), "more noise"])
HOST_LOG = "\n".join([
    recv("10.1", 1), parsed("10.1", 1), decided("10.1", 1, "applied", "19.33"), after("10.1", 1),
    recv("10.4", 2), refuse("10.4"),
    recv("10.7", 3, cons="80"), parsed("10.7", 3), decided("10.7", 3, "out of reach", "19.33"), after("10.7", 3),
])


class ParseTests(unittest.TestCase):
    def test_only_diagblock_lines_are_read_with_time_kind_and_fields(self):
        entries = diagblock.parse_lines(CLIENT_LOG)
        self.assertEqual([entry["kind"] for entry in entries], ["CLIENT_SEND"] * 3)
        self.assertEqual(entries[0]["fields"]["seq"], "1")
        self.assertEqual(entries[2]["fields"]["cons"], "90")
        self.assertEqual(entries[1]["t"], 10.3)

    def test_the_decision_reason_is_taken_from_the_text(self):
        reasons = [entry["reason"] for entry in diagblock.parse_lines(HOST_LOG) if entry["kind"] == "HOST_DECIDED"]
        self.assertEqual(reasons, ["applied", "out of reach"])

    def test_a_non_block_decision_is_named(self):
        text = "[diagblock] t=1 HOST_DECIDED seq=4 non-block kind confirmed=True otherTotal=1"
        self.assertEqual(diagblock.parse_lines(text)[0]["reason"], "non-block")

    def test_text_without_markers_gives_nothing(self):
        self.assertEqual(diagblock.parse_lines("hit server cooldown\nnothing"), [])


class TableTests(unittest.TestCase):
    def setUp(self):
        self.rows = diagblock.swing_table(diagblock.parse_lines(CLIENT_LOG), diagblock.parse_lines(HOST_LOG))

    def test_each_client_send_is_joined_to_the_host_record_in_order(self):
        self.assertEqual([row["outcome"] for row in self.rows], ["decided:applied", "refused-cooldown", "decided:out of reach"])
        self.assertTrue(all(row["seqMatches"] for row in self.rows if "seqMatches" in row))

    def test_a_refused_swing_keeps_the_host_cooldown_copy(self):
        self.assertEqual(self.rows[1]["refusedAtHostCooldown"], "0.31")

    def test_geometry_and_the_host_aim_are_kept_for_the_comparison(self):
        host = "\n".join([recv("10.1", 1), "[diagblock] t=10.1 HOST_PARSED seq=1 didhit=True hitobj=blk isBlock=True isNothing=False hitPos=(1,1) sentLimb1=(0.2,1) sentLook=(1,1) unarmed=True hostLimb1Before=(0.5,1) hostLookBefore=(3,3)",
                           decided("10.1", 1, "applied")])
        row = diagblock.swing_table(diagblock.parse_lines(client_line("10.0", 1)), diagblock.parse_lines(host))[0]
        self.assertEqual(row["clientGeometry"], {"pos": "(0,1)", "limb1": "(0.2,1)", "look": "(1,1)"})
        self.assertEqual(row["hostGeometry"]["pos"], "(0,1)")
        self.assertEqual((row["hostAim"]["hostLimb1Before"], row["hostAim"]["hostLookBefore"]), ("(0.5,1)", "(3,3)"))

    def test_decided_swings_carry_counter_health_and_the_cooldown_after(self):
        self.assertEqual(self.rows[0]["decided"]["counter"], "19.33")
        self.assertEqual(self.rows[0]["decided"]["health"], "60")
        self.assertEqual(self.rows[0]["hostCooldownAfter"], "0.18")

    def test_a_send_with_no_host_record_was_never_received(self):
        rows = diagblock.swing_table(diagblock.parse_lines(CLIENT_LOG), diagblock.parse_lines(HOST_LOG.split("\n")[0]))
        self.assertEqual([row["outcome"] for row in rows][1:], ["never-received", "never-received"])

    def test_a_sequence_mismatch_is_flagged(self):
        host = "\n".join([recv("10.1", 1), parsed("10.1", 9), decided("10.1", 9, "applied")])
        rows = diagblock.swing_table(diagblock.parse_lines(client_line("10.0", 1)), diagblock.parse_lines(host))
        self.assertFalse(rows[0]["seqMatches"])

    def test_consciousness_differences_between_client_and_host_are_listed(self):
        found = diagblock.differences(self.rows)
        self.assertEqual([(item["swing"], item["field"], item["client"], item["host"]) for item in found], [(3, "cons", "90", "80")])


class SummaryTests(unittest.TestCase):
    def test_the_summary_counts_outcomes_and_lists_lost_swings(self):
        summary = diagblock.summarise_run(CLIENT_LOG, HOST_LOG, [1.0, 1.3, 1.6])
        self.assertEqual(summary["clientSends"], 3)
        self.assertEqual(summary["hitsRequestedByHarness"], 3)
        self.assertEqual(summary["outcomes"], {"decided:applied": 1, "refused-cooldown": 1, "decided:out of reach": 1})
        self.assertEqual([item["index"] for item in summary["lost"]], [2, 3])

    def test_arrival_gaps_under_the_host_threshold_are_reported(self):
        host = "\n".join([recv("10.100", 1), recv("10.200", 2), recv("10.500", 3)])
        summary = diagblock.summarise_run(CLIENT_LOG, host)
        self.assertEqual(summary["shortestHostArrivalGap"], 0.1)
        self.assertEqual(summary["arrivalGapsUnder0124"], [0.1])

    def test_the_text_lines_name_each_swing_and_each_difference(self):
        lines = diagblock.summarise_run(CLIENT_LOG, HOST_LOG)["textLines"]
        self.assertTrue(lines[0].startswith("diagblock: client sends 3"))
        self.assertTrue(any("swing 2 seq 2: refused-cooldown" in line and "host cooldown copy=0.31" in line for line in lines))
        self.assertTrue(any("difference at swing 3: cons client 90 host 80" in line for line in lines))

    def test_an_empty_log_gives_an_empty_summary(self):
        summary = diagblock.summarise_run("", "")
        self.assertEqual((summary["clientSends"], summary["shortestHostArrivalGap"], summary["lost"]), (0, None, []))


NEW_CLIENT = ("[Info   :  Together] [diagblock] t=20.0 CLIENT_SEND seq=7 clientAttackPower=19.330000877380371 victim=blk latchedBlock=True hitPos=(1,1) atkCooldown=0.2 "
              "cd=0.2 charType=%s STR=%s RES=8 INT=7 armPow=1 bonusStr=0 claw=1 cons=100 overEnc=0 stim=0 stamina=95 conscious=True pos=(0,1) limb1=(0.2,1) look=(1,1) handSlot=0 holding=False")
NEW_RECV = ("[Info   :  Together] [diagblock] t=20.1 HOST_RECV n=1 client=2 worldReady=True gotAttacker=True awake=True "
            "cd=0 charType=%s STR=%s RES=8 INT=7 armPow=1 bonusStr=0 claw=1 cons=100 overEnc=0 stim=0 stamina=95 conscious=True pos=(0,1) limb1=(0.2,1) look=(1,1) handSlot=0 holding=False")
NEW_DECIDED = ("[Info   :  Together] [diagblock] t=20.1 HOST_DECIDED seq=7 block applied attackpower=%s counter=19.33 blockId=8 health=60 dLimb=1 totals applied=1 missed=0")


class ExtraFieldTests(unittest.TestCase):
    def rows(self, client_str, host_str, power, host_power):
        client = NEW_CLIENT % ("2", client_str)
        host = "\n".join([NEW_RECV % ("0", host_str), parsed("20.1", 7), NEW_DECIDED % host_power])
        client = client.replace("clientAttackPower=19.330000877380371", "clientAttackPower=" + power)
        return diagblock.swing_table(diagblock.parse_lines(client), diagblock.parse_lines(host))

    def test_the_new_attacker_fields_are_read_by_key_whatever_their_order(self):
        row = self.rows("17", "9", "24.68", "19.33")[0]
        self.assertEqual(row["client"]["STR"], "17")
        self.assertEqual(row["host"]["STR"], "9")
        self.assertEqual((row["client"]["charType"], row["host"]["charType"]), ("2", "0"))
        self.assertEqual(row["client"]["cons"], "100")
        self.assertEqual(row["clientAttackPower"], "24.68")

    def test_a_str_and_chartype_difference_is_listed_for_the_swing(self):
        found = diagblock.differences(self.rows("17", "9", "24.68", "19.33"))
        self.assertEqual(sorted((item["field"], item["client"], item["host"]) for item in found), [("STR", "17", "9"), ("charType", "2", "0")])

    def test_equal_strength_and_attack_power_settle_the_damage_question(self):
        check = diagblock.damage_check(self.rows("9", "9", "19.330000877380371", "19.330000877380371"))
        self.assertTrue(check["strEqual"])
        self.assertTrue(check["attackPowerEqual"])

    def test_different_attack_power_is_reported_as_not_equal(self):
        check = diagblock.damage_check(self.rows("17", "9", "24.68", "19.33"))
        self.assertFalse(check["strEqual"])
        self.assertFalse(check["attackPowerEqual"])
        self.assertEqual((check["clientAttackPower"], check["hostAttackpower"]), ("24.68", "19.33"))

    def test_no_decided_swing_means_no_check(self):
        rows = diagblock.swing_table(diagblock.parse_lines(NEW_CLIENT % ("2", "17")), diagblock.parse_lines(NEW_RECV % ("0", "9")))
        self.assertIsNone(diagblock.damage_check(rows))

    def test_the_summary_text_states_the_first_swings_strength_and_power(self):
        host = "\n".join([NEW_RECV % ("0", "9"), parsed("20.1", 7), NEW_DECIDED % "19.33"])
        text = "\n".join(diagblock.summarise_run(NEW_CLIENT % ("2", "17"), host)["textLines"])
        self.assertIn("STR client 17 host 9 (equal False)", text)
        self.assertIn("charType client 2 host 0", text)


def after_delta(t, seq, delta):
    return "[Info   :  Together] [diagblock] t=%s HOST_AFTER seq=%d copy cd=0.13 blockDamageSumDelta=%s" % (t, seq, delta)


class RaycastMissTests(unittest.TestCase):
    def rows(self, deltas):
        client = "\n".join(client_line("10.%d" % index, index + 1) for index in range(len(deltas)))
        lines = []
        for index, delta in enumerate(deltas):
            lines += [recv("10.%d" % index, index + 1), parsed("10.%d" % index, index + 1), decided("10.%d" % index, index + 1, "applied"), after_delta("10.%d" % index, index + 1, delta)]
        return client, "\n".join(lines)

    def test_a_received_swing_with_no_block_damage_change_is_a_host_raycast_miss(self):
        client, host = self.rows(["19.33", "0", "19.33"])
        summary = diagblock.summarise_run(client, host)
        self.assertEqual([item["index"] for item in summary["hostRaycastMisses"]], [2])
        rows = diagblock.swing_table(diagblock.parse_lines(client), diagblock.parse_lines(host))
        self.assertEqual([row["hostBlockDamageDelta"] for row in rows], ["19.33", "0", "19.33"])
        self.assertIn("blockDamageSumDelta 0): [2]", "\n".join(summary["textLines"]))

    def test_a_refused_swing_is_not_counted_as_a_raycast_miss(self):
        client = client_line("10.0", 1)
        host = "\n".join([recv("10.1", 1), refuse("10.1"), after_delta("10.1", 1, "0")])
        self.assertEqual(diagblock.summarise_run(client, host)["hostRaycastMisses"], [])

    def test_older_lines_without_the_delta_give_no_misses(self):
        client, host = CLIENT_LOG, HOST_LOG
        self.assertEqual(diagblock.summarise_run(client, host)["hostRaycastMisses"], [])


PARSED3 = ("[Info   :  Together] [diagblock] t=%s HOST_PARSED seq=%d didhit=False hitobj=nothing isBlock=False isNothing=True hitPos=(0,0) sentLimb1=(1,2) sentLook=(3,4) unarmed=True "
           "hostLimb1Before=(1.5,2) hostLookBefore=(9,9) hostIsRight=False hostStanding=True hostRootX=0.25 wouldFlip=True")
AFTER3 = "[Info   :  Together] [diagblock] t=%s HOST_AFTER seq=%d copy cd=0.13 blockDamageSumDelta=0 limb1After=(0.5,2) isRightAfter=True"


class FlipSuspectTests(unittest.TestCase):
    def summary(self, would_flip, after_limb):
        parsed3 = PARSED3.replace("wouldFlip=True", "wouldFlip=%s" % would_flip)
        after3 = AFTER3.replace("limb1After=(0.5,2)", "limb1After=%s" % after_limb)
        host = "\n".join([recv("10.1", 1), parsed3 % ("10.1", 1), decided("10.1", 1, "applied"), after3 % ("10.1", 1)])
        return diagblock.summarise_run(client_line("10.0", 1), host)

    def test_a_would_flip_swing_is_a_flip_suspect_and_a_lost_one_is_counted_as_such(self):
        summary = self.summary("True", "(0.5,2)")
        self.assertEqual(summary["flipSuspects"], [{"index": 1, "seq": "1", "limb1Shift": 0.5, "lost": True}])
        self.assertIn("flip suspects (wouldFlip true) at swings [1]; lost among them 1", "\n".join(summary["textLines"]))

    def test_no_flip_means_no_suspect(self):
        self.assertEqual(self.summary("False", "(1,2)")["flipSuspects"], [])

    def test_the_limb_shift_is_the_distance_between_the_sent_and_the_after_position(self):
        self.assertEqual(self.summary("True", "(4,6)")["rows"][0]["limb1Shift"], 5.0)

    def test_a_lost_swing_line_says_whether_the_limb_moved_far(self):
        far = "\n".join(self.summary("True", "(4,6)")["textLines"])
        near = "\n".join(self.summary("True", "(1.1,2)")["textLines"])
        self.assertIn("(shift 5.0, far True)", far)
        self.assertIn("(shift 0.1, far False)", near)

    def test_missing_fields_give_no_shift(self):
        rows = diagblock.swing_table(diagblock.parse_lines(client_line("10.0", 1)), diagblock.parse_lines(recv("10.1", 1)))
        diagblock.mark_flip_suspects(rows)
        self.assertIsNone(rows[0]["limb1Shift"])
        self.assertFalse(rows[0]["flipSuspect"])


class FlipFieldTests(unittest.TestCase):
    def rows(self, swing_log=None):
        client = client_line("10.0", 1)
        host = "\n".join([recv("10.1", 1), PARSED3 % ("10.1", 1), decided("10.1", 1, "applied"), AFTER3 % ("10.1", 1)])
        return client, host, diagblock.swing_table(diagblock.parse_lines(client), diagblock.parse_lines(host))

    def test_the_flip_fields_of_the_parse_and_the_after_line_are_kept(self):
        _, _, rows = self.rows()
        self.assertEqual(rows[0]["hostAim"]["wouldFlip"], "True")
        self.assertEqual((rows[0]["hostAim"]["hostIsRight"], rows[0]["hostAim"]["hostRootX"]), ("False", "0.25"))
        self.assertEqual((rows[0]["hostAfter"]["limb1After"], rows[0]["hostAfter"]["isRightAfter"]), ("(0.5,2)", "True"))

    def test_a_lost_swing_line_names_flip_side_and_limb_data_with_the_client_side(self):
        client, host, _ = self.rows()
        summary = diagblock.summarise_run(client, host, [1.0], [{"isRight": True, "aim": {"x": 1.0, "y": 2.0}}])
        text = "\n".join(summary["textLines"])
        self.assertIn("lost swing 1 seq 1: wouldFlip=True hostIsRight=False clientIsRight=True hostStanding=True hostRootX=0.25, sentLimb1=(1,2) limb1After=(0.5,2) (shift 0.5, far False), isRightAfter=True", text)

    def test_a_swing_log_of_another_length_is_ignored_rather_than_misjoined(self):
        client, host, _ = self.rows()
        summary = diagblock.summarise_run(client, host, [1.0], [{"isRight": True}, {"isRight": False}])
        self.assertNotIn("clientIsRight", summary["rows"][0])


if __name__ == "__main__":
    unittest.main()
