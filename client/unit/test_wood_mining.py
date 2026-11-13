import unittest

from tests import wood_mining as wood

GOOD_IDENTITIES = {"host": 1, "client": 2, "clientOnHost": 2, "clientWanted": 2}


def finding(broke_at=None, reappeared=()):
    return {"brokeAt": broke_at, "resets": [], "reappeared": list(reappeared), "presentAtEnd": not broke_at or bool(reappeared)}


def good_context(**changes):
    context = {"positionControl": {"ok": True, "issues": []}, "placedByHost": True, "blockId": 11, "blockHealth": 150.0,
               "woodSwings": [{"swing": number, "client": {"block": 11, "damage": 24.7 * number}} for number in range(1, 6)] + [{"swing": 6, "client": {"block": 0, "damage": 0.0}}],
               "scrapsBefore": {"host": 0, "client": 0}}
    context.update(changes)
    return context


def sample(block, scraps=0):
    return {"t": 1.0, "host": [block, 0.0, {}, scraps], "client": [block, 0.0, {}, scraps]}


class FakeObservation:
    def __init__(self, context, samples):
        self.context = context
        self.samples = samples


class JudgeTests(unittest.TestCase):
    def judge(self, context=None, client=None, host=None, identities=None):
        return wood.judge_wood_run(context or good_context(), {"client": client or finding(1.0), "host": host or finding(1.5)}, identities or GOOD_IDENTITIES)

    def test_a_run_where_the_client_broke_the_block_and_it_stayed_gone_is_persisted(self):
        self.assertEqual(self.judge()["verdict"], "persisted")

    def test_a_block_that_comes_back_on_the_client_after_the_break_is_a_reversion_with_its_timing(self):
        outcome = self.judge(client=finding(1.0, [{"t": 2.0, "goneFor": 1.0}]))
        self.assertEqual(outcome["verdict"], "reversion")
        self.assertEqual(outcome["clientReappeared"], [{"t": 2.0, "goneFor": 1.0}])

    def test_a_block_that_comes_back_only_on_the_host_is_recorded_but_not_a_client_reversion(self):
        outcome = self.judge(host=finding(1.5, [{"t": 2.0, "goneFor": 0.5}]))
        self.assertEqual(outcome["verdict"], "persisted")
        self.assertEqual(outcome["hostReappeared"], [{"t": 2.0, "goneFor": 0.5}])

    def test_a_run_whose_client_never_broke_the_block_is_invalid_not_persisted(self):
        outcome = self.judge(client=finding(None))
        self.assertEqual(outcome["verdict"], "invalid")
        self.assertIn("the client never broke the block", outcome["reasons"])

    def test_a_failed_position_control_makes_the_run_invalid_even_when_the_block_came_back(self):
        context = good_context(positionControl={"ok": False, "issues": ["host not parked"]})
        outcome = self.judge(context, client=finding(1.0, [{"t": 2.0, "goneFor": 1.0}]))
        self.assertEqual(outcome["verdict"], "invalid")
        self.assertIn("position control: host not parked", outcome["reasons"])

    def test_wrong_characters_make_the_run_invalid(self):
        outcome = self.judge(identities={"host": 2, "client": 2, "clientOnHost": 0, "clientWanted": 2})
        self.assertEqual(outcome["verdict"], "invalid")
        self.assertEqual(len(outcome["reasons"]), 2)

    def test_a_block_that_is_not_the_planned_wood_block_makes_the_run_invalid(self):
        self.assertEqual(self.judge(good_context(blockId=8, blockHealth=60.0))["verdict"], "invalid")

    def test_a_block_not_placed_by_the_host_makes_the_run_invalid(self):
        self.assertEqual(self.judge(good_context(placedByHost=False))["verdict"], "invalid")

    def test_a_swing_that_did_not_damage_the_clients_block_makes_the_run_invalid(self):
        context = good_context()
        context["woodSwings"][2]["client"]["damage"] = context["woodSwings"][1]["client"]["damage"]
        context["woodSwings"][3]["client"]["damage"] = context["woodSwings"][1]["client"]["damage"]
        outcome = self.judge(context)
        self.assertEqual(outcome["verdict"], "invalid")
        self.assertTrue(any("swing 3 did not damage" in reason for reason in outcome["reasons"]))

    def test_a_hit_applied_a_moment_after_the_swing_still_counts_when_the_next_read_shows_it(self):
        context = good_context()
        context["woodSwings"][2]["client"]["damage"] = context["woodSwings"][1]["client"]["damage"]
        context["woodSwings"][3]["client"]["damage"] = 24.7 * 4 + 24.7
        self.assertEqual(wood.swing_problems(context["woodSwings"][:4] + [{"swing": 5, "client": {"block": 0, "damage": 0.0}}]), [])

    def test_two_swings_in_a_row_without_damage_are_a_missed_swing(self):
        swings = [{"swing": 1, "client": {"block": 11, "damage": 24.7}}, {"swing": 2, "client": {"block": 11, "damage": 24.7}}, {"swing": 3, "client": {"block": 11, "damage": 24.7}},
                  {"swing": 4, "client": {"block": 11, "damage": 49.4}}]
        self.assertEqual(len(wood.swing_problems(swings)), 1)
        self.assertIn("swing 2 did not damage", wood.swing_problems(swings)[0])

    def test_swings_after_the_break_are_not_judged(self):
        context = good_context()
        context["woodSwings"].append({"swing": 7, "client": {"block": 0, "damage": 0.0}})
        self.assertEqual(self.judge(context)["verdict"], "persisted")


class ReadingTests(unittest.TestCase):
    def test_the_host_events_are_listed_in_log_order_by_the_first_marker_of_each_line(self):
        text = "x\n[Together] hit server apply a\n[Together] hit server cooldown b\nnoise\n[Together] hit server range c\n[Together] hit server apply d\n"
        self.assertEqual(wood.host_event_sequence(text), ["applied", "cooldown", "range", "applied"])

    def test_the_final_scrap_count_is_the_last_sample_of_each_side(self):
        self.assertEqual(wood.final_scraps([sample(11, 0), sample(0, 3)]), {"host": 3, "client": 3})
        self.assertEqual(wood.final_scraps([]), {"host": None, "client": None})


class ReportTests(unittest.TestCase):
    def extend(self, context, findings):
        report = {"findings": findings}
        context["identities"] = dict(GOOD_IDENTITIES)
        issues = wood.extend_report(report, FakeObservation(context, [sample(11), sample(0, 3)]), {"host": "hit server apply\nhit server cooldown", "client": ""})
        return report, issues

    def test_a_persisted_run_reports_no_issue_and_carries_the_per_swing_reads_and_events(self):
        report, issues = self.extend(good_context(), {"client": finding(1.0), "host": finding(1.5)})
        self.assertEqual(issues, [])
        self.assertEqual(report["woodRun"]["hostEventCounts"]["cooldown"], 1)
        self.assertEqual(report["woodRun"]["scraps"]["end"], {"host": 3, "client": 3})
        self.assertEqual(len(report["woodSwings"]), 6)

    def test_a_reversion_is_reported_as_an_issue_with_the_time_it_came_back(self):
        report, issues = self.extend(good_context(), {"client": finding(1.0, [{"t": 2.1, "goneFor": 1.1}]), "host": finding(1.5)})
        self.assertEqual(len(issues), 1)
        self.assertTrue(issues[0].startswith("REVERSION: the client's block came back 1.10 s after it broke"))

    def test_an_invalid_run_is_reported_as_an_invalid_issue(self):
        report, issues = self.extend(good_context(placedByHost=False), {"client": finding(1.0), "host": finding(1.5)})
        self.assertTrue(issues[0].startswith("INVALID: "))


class WiringTests(unittest.TestCase):
    def test_the_scenarios_run_a_milky_host_with_a_dune_or_an_experiment_client_in_their_own_groups(self):
        self.assertEqual(wood.HOST_CHARACTER, 1)
        self.assertEqual(wood.CLIENT_CHARACTERS, {"wood-mining-dune": 2, "wood-mining-experiment": 0})
        self.assertEqual([scenario.group for scenario in wood.WOOD_SCENARIOS], ["wood-mining-dune", "wood-mining-experiment"])

    def test_every_scenario_extends_its_report(self):
        for scenario in wood.WOOD_SCENARIOS:
            self.assertIs(scenario.extend_report, wood.extend_report)


if __name__ == "__main__":
    unittest.main()
