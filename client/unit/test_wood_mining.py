import unittest

from tests import wood_mining as wood

GOOD_IDENTITIES = {"host": 1, "client": 2, "clientOnHost": 2, "clientWanted": 2}
UNIT = 24.68


def finding(broke_at=None, reappeared=()):
    return {"brokeAt": broke_at, "resets": [], "reappeared": list(reappeared), "presentAtEnd": not broke_at or bool(reappeared)}


def good_context(**changes):
    context = {"positionControl": {"ok": True, "issues": []}, "placedByHost": True, "blockId": 11, "blockHealth": 150.0, "scrapsBefore": {"host": 0, "client": 0}}
    context.update(changes)
    return context


def swings_at(times):
    return [{"swing": index + 1, "t": moment, "invokedAt": 100.0 + moment, "ignoredAttempts": 0, "interval": None if index == 0 else round(moment - times[index - 1], 3)} for index, moment in enumerate(times)]


def reading(block, damage, scraps=None, claw=99.0, cooldown=0.0):
    return [block, damage, {"0,0": damage}, scraps, {"claw": claw, "cooldown": cooldown}]


def series(client_damages, host_damages, step=0.1, scraps_at_end=1):
    """Samples every `step` seconds; a damage of 0.0 after the first sample is the break."""
    samples = []
    for index, (client_damage, host_damage) in enumerate(zip(client_damages, host_damages)):
        last = index == len(client_damages) - 1
        samples.append({"t": round(index * step, 3), "client": reading(0 if client_damage == 0.0 and index else 11, client_damage, scraps_at_end if last else None),
                        "host": reading(0 if host_damage == 0.0 and index else 11, host_damage, scraps_at_end if last else None)})
    return samples


def climb(hits, final_zero=True):
    values = [0.0] + [UNIT * number for number in range(1, hits + 1)]
    return values + ([0.0] if final_zero else [])


class JudgeTests(unittest.TestCase):
    def judge(self, context=None, client=None, host=None, identities=None, swings=None, units=None, extra=()):
        swings = swings if swings is not None else swings_at([0.5, 0.7, 0.9, 1.1])
        units = units if units is not None else [(0.6, 1), (0.8, 1), (1.0, 1)]
        return wood.judge_wood_run(context or good_context(), {"client": client or finding(1.2), "host": host or finding(1.3)}, identities or GOOD_IDENTITIES, swings, units, extra)

    def test_a_run_where_the_client_broke_the_block_and_it_stayed_gone_is_persisted(self):
        self.assertEqual(self.judge()["verdict"], "persisted")

    def test_a_block_that_comes_back_on_the_client_after_the_break_is_a_reversion_with_its_timing(self):
        outcome = self.judge(client=finding(1.2, [{"t": 2.0, "goneFor": 0.8}]))
        self.assertEqual(outcome["verdict"], "reversion")
        self.assertEqual(outcome["clientReappeared"], [{"t": 2.0, "goneFor": 0.8}])

    def test_a_block_that_comes_back_only_on_the_host_is_recorded_but_not_a_client_reversion(self):
        outcome = self.judge(host=finding(1.3, [{"t": 2.0, "goneFor": 0.5}]))
        self.assertEqual(outcome["verdict"], "persisted")
        self.assertEqual(outcome["hostReappeared"], [{"t": 2.0, "goneFor": 0.5}])

    def test_a_run_whose_client_never_broke_the_block_is_invalid_not_persisted(self):
        outcome = self.judge(client=finding(None))
        self.assertEqual(outcome["verdict"], "invalid")
        self.assertIn("the client never broke the block", outcome["reasons"])

    def test_a_failed_position_control_makes_the_run_invalid_even_when_the_block_came_back(self):
        context = good_context(positionControl={"ok": False, "issues": ["host not parked"]})
        outcome = self.judge(context, client=finding(1.2, [{"t": 2.0, "goneFor": 1.0}]))
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

    def test_an_unobserved_proxy_delay_passed_in_as_a_problem_makes_the_run_invalid(self):
        outcome = self.judge(extra=["the proxy delay 100 ms was not observed (client to host mean 3.0 ms)"])
        self.assertEqual(outcome["verdict"], "invalid")


class ParkedHostTests(unittest.TestCase):
    def control(self, parked):
        return {"ok": True, "issues": [], "clientTarget": {"x": 0.0, "y": 0.0}, "parkedHost": {"policy": "recorded", "position": parked}}

    def test_a_parked_host_far_enough_from_the_seat_is_fine_whatever_its_drift(self):
        self.assertEqual(wood.setup_problems(good_context(positionControl=self.control({"x": 12.0, "y": 0.0})), GOOD_IDENTITIES), [])

    def test_a_parked_host_closer_than_the_minimum_distance_makes_the_run_invalid(self):
        problems = wood.setup_problems(good_context(positionControl=self.control({"x": 3.0, "y": 0.0})), GOOD_IDENTITIES)
        self.assertEqual(len(problems), 1)
        self.assertIn("the parked host is only 3.0 from the client's seat", problems[0])

    def test_the_wood_scenario_asks_for_the_recorded_parking_policy(self):
        import inspect
        self.assertIn("PARKED_RECORDED", inspect.getsource(wood.wood_prepare))


class SwingProblemTests(unittest.TestCase):
    def test_swings_up_to_the_break_may_exceed_the_damaging_ones_by_the_breaking_swing_only(self):
        units = [(0.6, 1), (0.8, 1), (1.0, 1)]
        self.assertEqual(wood.swing_problems(swings_at([0.5, 0.7, 0.9, 1.1]), units, 1.2), [])
        problems = wood.swing_problems(swings_at([0.5, 0.7, 0.9, 1.1, 1.15]), units, 1.2)
        self.assertEqual(len(problems), 1)
        self.assertIn("5 swings were fired before the break but only 3 damaged", problems[0])

    def test_swings_after_the_break_are_not_counted(self):
        self.assertEqual(wood.swing_problems(swings_at([0.5, 0.7, 0.9, 1.1, 1.5, 1.7]), [(0.6, 1), (0.8, 1), (1.0, 1)], 1.2), [])

    def test_a_step_that_holds_two_swings_counts_as_two(self):
        self.assertEqual(wood.damage_units([(0.6, 49.4)], UNIT), [(0.6, 2)])
        self.assertEqual(wood.swing_problems(swings_at([0.5, 0.7, 0.9]), [(0.6, 2)], 1.0), [])

    def test_no_break_gives_no_swing_problem_because_the_run_is_invalid_anyway(self):
        self.assertEqual(wood.swing_problems(swings_at([0.5]), [], None), [])


class SamplerDerivedTests(unittest.TestCase):
    def test_damage_steps_are_the_rises_while_the_block_stands(self):
        samples = series(climb(3), climb(3))
        steps = wood.damage_steps(samples, "client")
        self.assertEqual([round(rise, 2) for _, rise in steps], [UNIT, UNIT, UNIT])
        self.assertEqual(wood.unit_damage(steps), UNIT)

    def test_the_host_record_counts_the_swings_each_machine_applied_with_the_break_as_one(self):
        record = wood.host_damage_record(series(climb(3), climb(3)), UNIT)
        self.assertEqual((record["clientSwingsApplied"], record["hostSwingsApplied"], record["hostMissed"]), (4, 4, 0))

    def test_a_host_that_applied_fewer_swings_than_the_client_is_counted_as_missed(self):
        host = [0.0, UNIT, UNIT * 2, UNIT * 2, UNIT * 2]
        record = wood.host_damage_record(series(climb(3), host), UNIT)
        self.assertEqual((record["clientSwingsApplied"], record["hostSwingsApplied"], record["hostMissed"]), (4, 2, 2))

    def test_the_most_woodscraps_after_the_break_is_taken_per_side(self):
        self.assertEqual(wood.final_scraps(series(climb(2), climb(2), scraps_at_end=3), "client"), 3)
        self.assertIsNone(wood.final_scraps(series(climb(2), climb(2), scraps_at_end=None), "host"))


class BunchingTests(unittest.TestCase):
    def test_the_arrival_of_a_swing_is_the_first_packet_after_the_invoke_plus_its_delay(self):
        swings = [{"invokedAt": 100.05}, {"invokedAt": 100.30}]
        packets = [(100.04, "toHost", 80, 10.0, 100.05), (100.06, "toHost", 80, 100.0, 100.16), (100.31, "toClient", 80, 1.0, 100.311), (100.32, "toHost", 80, 150.0, 100.47)]
        arrivals = wood.estimate_arrivals(swings, packets)
        self.assertAlmostEqual(arrivals[0], 100.16)
        self.assertAlmostEqual(arrivals[1], 100.47)

    def test_a_swing_with_no_later_packet_has_no_arrival_estimate(self):
        self.assertEqual(wood.estimate_arrivals([{"invokedAt": 200.0}], [(100.0, "toHost", 80, 5.0, 100.005)]), [None])

    def test_spacings_are_in_swing_order_and_negative_when_a_later_swing_overtakes(self):
        self.assertEqual(wood.arrival_spacings([1.0, 1.2, 1.15, None, 2.0]), [0.2, -0.05])

    def test_the_cooldown_rule_drops_swings_that_arrive_closer_than_the_cooldown_after_the_last_accepted(self):
        self.assertEqual(wood.predicted_host_drops([1.0, 1.2, 1.3, 1.5]), 1)
        self.assertEqual(wood.predicted_host_drops([1.0, 1.2, 1.4]), 0)
        self.assertEqual(wood.predicted_host_drops([1.0, 1.05, 1.1, 1.15]), 2)
        self.assertEqual(wood.predicted_host_drops([None, 1.0]), 0)

    def test_the_distribution_has_the_count_and_the_extremes(self):
        self.assertEqual(wood.distribution([0.3, 0.2, 0.25]), {"n": 3, "min": 0.2, "median": 0.25, "max": 0.3})
        self.assertIsNone(wood.distribution([]))


class SwingBurstRecordTests(unittest.TestCase):
    LOG = "x\n[Info] SWINGBURST dropped client=1 gap=0.020 credit=0.100\n[Info] SWINGBURST accepted-by-credit client=1 gap=0.050 credit=0.400\nnoise\n[Info] SWINGBURST summary client=1 accepted-normally=5 accepted-by-credit=1 dropped=1\n"

    def test_the_swingburst_lines_are_counted_by_kind_and_the_first_ones_kept(self):
        record = wood.swingburst_record(self.LOG)
        self.assertEqual(record["lines"], 3)
        self.assertEqual(record["counts"], {"dropped": 1, "acceptedByCredit": 1, "summary": 1})
        self.assertTrue(record["first"][0].endswith("credit=0.100"))

    def test_a_log_without_swingburst_lines_gives_zero_counts(self):
        self.assertEqual(wood.swingburst_record("nothing here\n")["counts"], {"dropped": 0, "acceptedByCredit": 0, "summary": 0})

    def test_the_report_carries_the_stall_summary_and_the_swingburst_record(self):
        observation = ReportTests.Observation(good_context(), series(climb(3), climb(3)))
        observation.baseline = {"host": [11, 0.0], "client": [11, 0.0]}
        context = observation.context
        context["identities"] = dict(GOOD_IDENTITIES)
        context["seriesStarted"] = 100.0
        context["woodSwings"] = [{"swing": index + 1, "invokedAt": 100.0 + moment, "ignoredAttempts": 0, "interval": None} for index, moment in enumerate([0.5, 0.7, 0.9, 1.1])]
        report = {"findings": {"client": finding(0.4), "host": finding(0.4)}, "network": {"delay_ms": 0.0}, "proxyObserved": {},
                  "stallTrace": [{"start": 1.0, "end": 1.3, "held": 2}, {"start": 2.0, "end": 2.4, "held": 3}]}
        wood.extend_report(report, observation, {"host": self.LOG, "client": ""}, [])
        self.assertEqual(report["woodRun"]["stalls"], {"count": 2, "packetsHeld": 5, "longest": 0.4})
        self.assertEqual(report["swingBurst"]["counts"]["dropped"], 1)


class BaselineProblemTests(unittest.TestCase):
    def test_damage_left_on_the_cell_before_the_first_swing_is_a_problem_per_side(self):
        problems = wood.baseline_problems({"host": [11, 135.3], "client": [11, 0.0]})
        self.assertEqual(len(problems), 1)
        self.assertIn("the host already held 135.3 damage", problems[0])

    def test_an_undamaged_cell_or_no_baseline_is_fine(self):
        self.assertEqual(wood.baseline_problems({"host": [11, 0.0], "client": [11, 0.0]}), [])
        self.assertEqual(wood.baseline_problems(None), [])

    def test_a_run_whose_cell_was_pre_damaged_is_invalid_in_the_report(self):
        observation = ReportTests.Observation(good_context(), series(climb(3), climb(3)))
        observation.baseline = {"host": [11, 135.3], "client": [11, 0.0]}
        context = observation.context
        context["identities"] = dict(GOOD_IDENTITIES)
        context["seriesStarted"] = 100.0
        context["woodSwings"] = [{"swing": index + 1, "invokedAt": 100.0 + moment, "ignoredAttempts": 0, "interval": None} for index, moment in enumerate([0.5, 0.7, 0.9, 1.1])]
        report = {"findings": {"client": finding(0.4), "host": finding(0.4)}, "network": {"delay_ms": 0.0}, "proxyObserved": {}}
        issues = wood.extend_report(report, observation, {"host": "", "client": ""}, [])
        self.assertTrue(issues[0].startswith("INVALID: the host already held 135.3 damage"))


class ProxyProblemTests(unittest.TestCase):
    def test_a_delay_the_proxy_did_not_give_is_a_problem(self):
        report = {"network": {"delay_ms": 100.0}, "proxyObserved": {"toHost": {"meanMs": 3.0}}}
        self.assertEqual(len(wood.proxy_problems(report)), 1)

    def test_an_observed_delay_or_no_delay_asked_is_fine(self):
        self.assertEqual(wood.proxy_problems({"network": {"delay_ms": 100.0}, "proxyObserved": {"toHost": {"meanMs": 130.0}}}), [])
        self.assertEqual(wood.proxy_problems({"network": {"delay_ms": 0.0}, "proxyObserved": {"toHost": {"meanMs": None}}}), [])

    def test_missing_proxy_numbers_with_a_delay_asked_are_a_problem(self):
        self.assertEqual(len(wood.proxy_problems({"network": {"delay_ms": 100.0}, "proxyObserved": {}})), 1)


class FireSwingTests(unittest.TestCase):
    class FakeClient:
        def __init__(self, cooldowns):
            self.cooldowns = list(cooldowns)
            self.invokes = 0
            self.last = None

        def get(self, target, path, depth=0):
            return self.cooldowns.pop(0)

        def call(self, name, **arguments):
            self.invokes += 1
            self.last = arguments

    def test_it_invokes_until_the_cooldown_rises_and_counts_the_ignored_invokes(self):
        client = self.FakeClient([0.0, 0.0, 0.0, 0.0, 0.0, 0.2])
        fired = wood.fire_swing(client, {"x": 1.0, "y": 2.0}, sleep=lambda seconds: None, clock=iter(range(100)).__next__)
        self.assertEqual(client.invokes, 3)
        self.assertEqual(fired["ignored"], 2)
        self.assertEqual(client.last["sets"][0]["value"], {"x": 1.0, "y": 2.0, "z": 0.0})

    def test_it_gives_up_after_the_timeout(self):
        client = self.FakeClient([0.0, 0.0] * 50)
        ticks = iter([0.0, 1.0, 20.0, 21.0, 22.0])
        self.assertIsNone(wood.fire_swing(client, {"x": 0.0, "y": 0.0}, sleep=lambda seconds: None, clock=lambda: next(ticks), timeout=12.0))


class ReportTests(unittest.TestCase):
    class Observation:
        def __init__(self, context, samples):
            self.context = context
            self.samples = samples

    def extend(self, context, samples, findings, network=None, proxy=None, packets=()):
        report = {"findings": findings, "network": network or {"delay_ms": 0.0}, "proxyObserved": proxy or {}}
        context.setdefault("identities", dict(GOOD_IDENTITIES))
        context["seriesStarted"] = 100.0
        times = [0.5, 0.7, 0.9, 1.1]
        context.setdefault("woodSwings", [{"swing": index + 1, "invokedAt": 100.0 + moment, "ignoredAttempts": 0, "interval": None if index == 0 else round(moment - times[index - 1], 3)}
                                         for index, moment in enumerate(times)])
        issues = wood.extend_report(report, self.Observation(context, samples), {"host": "", "client": ""}, list(packets))
        return report, issues

    def good_samples(self):
        return series(climb(3), climb(3))

    def test_a_persisted_run_reports_no_issue_and_carries_the_damage_record_and_the_bunching(self):
        packets = [(100.0 + 0.1 * index, "toHost", 80, 100.0, 100.1 + 0.1 * index) for index in range(20)]
        report, issues = self.extend(good_context(), self.good_samples(), {"client": finding(0.4), "host": finding(0.4)}, packets=packets)
        self.assertEqual(issues, [])
        record = report["woodRun"]["damage"]
        self.assertEqual((record["clientSwingsApplied"], record["hostSwingsApplied"], record["hostMissed"]), (4, 4, 0))
        self.assertEqual(report["woodRun"]["bunching"]["arrivalsEstimated"], 4)
        self.assertEqual(report["woodRun"]["bunching"]["clientIntervals"]["n"], 3)
        self.assertEqual(report["woodRun"]["scraps"]["end"], {"host": 1, "client": 1})

    def test_a_reversion_is_reported_as_an_issue_with_the_time_it_came_back(self):
        report, issues = self.extend(good_context(), self.good_samples(), {"client": finding(0.4, [{"t": 1.5, "goneFor": 0.9}]), "host": finding(0.4)})
        self.assertEqual(len(issues), 1)
        self.assertTrue(issues[0].startswith("REVERSION: the client's block came back 0.90 s after it broke"))

    def test_an_invalid_run_is_reported_as_an_invalid_issue(self):
        report, issues = self.extend(good_context(placedByHost=False), self.good_samples(), {"client": finding(0.4), "host": finding(0.4)})
        self.assertTrue(issues[0].startswith("INVALID: "))

    def test_a_run_whose_proxy_delay_was_not_observed_is_invalid(self):
        report, issues = self.extend(good_context(), self.good_samples(), {"client": finding(0.4), "host": finding(0.4)}, network={"delay_ms": 100.0}, proxy={"toHost": {"meanMs": 2.0}})
        self.assertIn("the proxy delay 100 ms was not observed", issues[0])


class WiringTests(unittest.TestCase):
    def test_the_scenarios_run_a_milky_host_with_a_dune_or_an_experiment_client_in_their_own_groups(self):
        self.assertEqual(wood.HOST_CHARACTER, 1)
        self.assertEqual(wood.CLIENT_CHARACTERS, {"wood-mining-dune": 2, "wood-mining-experiment": 0})
        self.assertEqual([scenario.group for scenario in wood.WOOD_SCENARIOS], ["wood-mining-dune", "wood-mining-experiment"])

    def test_every_scenario_extends_its_report_samples_fast_and_fires_without_a_pause_between_calls(self):
        for scenario in wood.WOOD_SCENARIOS:
            self.assertIs(scenario.extend_report, wood.extend_report)
            self.assertEqual(scenario.interval_seconds, wood.SAMPLE_INTERVAL_SECONDS)
            self.assertEqual(scenario.cadence_seconds, 0.0)

    def test_the_swing_poll_is_shorter_than_the_cooldown_so_the_swing_rate_is_the_games(self):
        self.assertLess(wood.SWING_POLL_SECONDS, 0.05)
        self.assertGreater(wood.HOST_COOLDOWN_SECONDS, 0.1)


if __name__ == "__main__":
    unittest.main()
