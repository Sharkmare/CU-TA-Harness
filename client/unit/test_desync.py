import json
import os
import tempfile
import unittest
import zipfile

from casualtieslink import desync


class FakeWorld:
    def __init__(self, value=0):
        self.value = value


def make_scenario(changed_when_above=0):
    return desync.Scenario(
        name="counter",
        description="a counter that the client raises",
        prepare=lambda host, client: None,
        act=lambda client, context: setattr(client, "value", 5),
        read=lambda game, context: game.value,
        changed=lambda value, baseline: value > baseline + changed_when_above,
    )


class Clock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class Script:
    def __init__(self, host_values, client_values):
        self.host_values = list(host_values)
        self.client_values = list(client_values)


def scripted_scenario(script):
    reads = {"host": iter(script.host_values), "client": iter(script.client_values)}
    return desync.Scenario(
        name="scripted", description="scripted reads", prepare=lambda host, client: None,
        act=lambda client, context: None,
        read=lambda game, context: next(reads[game]),
        changed=lambda value, baseline: value != baseline,
    )


def observe_script(host_values, client_values):
    scenario = scripted_scenario(Script(host_values, client_values))
    clock = Clock()
    return desync.observe(scenario, "host", "client", clock=clock, sleep=clock.sleep)


class ObserveTests(unittest.TestCase):
    def test_the_action_runs_on_the_client_only_and_values_are_read_at_each_offset(self):
        host, client = FakeWorld(), FakeWorld()
        clock = Clock()
        observation = desync.observe(make_scenario(), host, client, clock=clock, sleep=clock.sleep)
        self.assertEqual((host.value, client.value), (0, 5))
        self.assertEqual([sample.offset for sample in observation.samples], [0.0, 2.0, 10.0])
        self.assertEqual(clock.slept, [2.0, 8.0])
        self.assertEqual((observation.baseline_host, observation.baseline_client), (0, 0))

    def test_skipping_the_action_leaves_both_at_baseline(self):
        host, client = FakeWorld(), FakeWorld()
        clock = Clock()
        observation = desync.observe(make_scenario(), host, client, perform_action=False, clock=clock, sleep=clock.sleep)
        self.assertEqual(client.value, 0)
        self.assertFalse(observation.acted)
        self.assertEqual(desync.judge(observation), desync.VERDICT_NEVER_CHANGED)


class JudgeTests(unittest.TestCase):
    def test_agreement_on_a_changed_value_at_every_offset_persists(self):
        self.assertEqual(desync.judge(observe_script([0, 5, 5, 5], [0, 5, 5, 5])), desync.VERDICT_PERSISTED)

    def test_the_client_value_overwritten_by_the_host_is_a_revert(self):
        self.assertEqual(desync.judge(observe_script([0, 0, 0, 0], [0, 5, 0, 0])), desync.VERDICT_REVERTED)

    def test_a_client_that_keeps_a_change_the_host_never_took_is_divergence(self):
        self.assertEqual(desync.judge(observe_script([0, 0, 0, 0], [0, 5, 5, 5])), desync.VERDICT_DIVERGED)

    def test_nothing_changing_anywhere_is_never_changed(self):
        self.assertEqual(desync.judge(observe_script([0, 0, 0, 0], [0, 0, 0, 0])), desync.VERDICT_NEVER_CHANGED)

    def test_a_change_that_arrives_late_is_not_there_from_the_start(self):
        self.assertEqual(desync.judge(observe_script([0, 0, 0, 5], [0, 0, 0, 5])), desync.VERDICT_LOST)

    def test_both_instances_losing_the_change_is_a_revert(self):
        self.assertEqual(desync.judge(observe_script([0, 5, 0, 0], [0, 5, 0, 0])), desync.VERDICT_REVERTED)


class ReportTests(unittest.TestCase):
    def report(self, host_values, client_values, acted=True):
        observation = observe_script(host_values, client_values)
        observation.acted = acted
        return desync.describe(observation, "stock-5.5.0", "ab" * 32, "1.0")

    def test_the_report_carries_build_hash_both_values_and_the_verdict(self):
        text = desync.format_report(self.report([0, 0, 0, 0], [0, 5, 0, 0]))
        self.assertIn("[stock-5.5.0]", text)
        self.assertIn("sha256 " + "ab" * 32, text)
        self.assertIn("t= 0.0s   host=0 client=5", text)
        self.assertIn("verdict: reverted-by-host", text)
        self.assertIn("game version 1.0, action performed by the client: yes", text)
        self.assertIn("the host value overwrote the client value", text)

    def test_disagreeing_rows_are_marked(self):
        text = desync.format_report(self.report([0, 0, 0, 0], [0, 5, 5, 5]))
        self.assertEqual(text.count("instances disagree"), 3)

    def test_a_skipped_action_says_so(self):
        self.assertIn("SKIPPED (mutation)", desync.format_report(self.report([0, 0, 0, 0], [0, 0, 0, 0], acted=False)))

    def test_the_saved_report_is_json_named_by_scenario_build_and_hash_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = desync.save_report(self.report([0, 5, 5, 5], [0, 5, 5, 5]), directory)
            self.assertEqual(os.path.basename(path), "scripted__stock-5.5.0_abababab__r1.json")
            with open(path, encoding="utf-8") as handle:
                loaded = json.load(handle)
        self.assertEqual(loaded["verdict"], desync.VERDICT_PERSISTED)
        self.assertEqual(loaded["dllSha256"], "ab" * 32)


class BuildTests(unittest.TestCase):
    def test_known_builds_parse_and_default_to_stock_5_5_0(self):
        self.assertEqual(desync.parse_build("FORK"), "fork")
        self.assertEqual(desync.parse_build(None), desync.DEFAULT_BUILD)
        self.assertEqual(desync.parse_build(" upstream-fixes "), "upstream-fixes")

    def test_an_unknown_build_names_the_choices(self):
        with self.assertRaises(ValueError) as caught:
            desync.parse_build("stock-9")
        self.assertIn("stock-5.4.0", str(caught.exception))

    def test_flavour_builds_map_to_the_flavour_choice_and_upstream_to_stage(self):
        self.assertEqual(desync.together_choice("stock-5.4.0"), "flavour:stock-5.4.0")
        self.assertEqual(desync.together_choice("fork"), "flavour:fork")
        self.assertEqual(desync.together_choice("upstream-fixes"), "stage")

    def test_the_flavour_hash_is_read_from_the_package_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            package = os.path.join(directory, "package.zip")
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("BepInEx/together-flavours/fork/CasualtiesMP.dll", b"fork bytes")
            self.assertEqual(desync.flavour_dll_hash(package, "fork"), desync.sha256_of_bytes(b"fork bytes"))
            self.assertEqual(desync.flavour_dll_hash(package, "stock-5.5.0"), desync.UNKNOWN_HASH)
            self.assertEqual(desync.flavour_dll_hash(os.path.join(directory, "missing.zip"), "fork"), desync.UNKNOWN_HASH)

    def test_the_stage_hash_is_read_from_the_staged_dll(self):
        with tempfile.TemporaryDirectory() as directory:
            os.makedirs(os.path.join(directory, "plugins", "Together"))
            with open(os.path.join(directory, "plugins", "Together", "CasualtiesMP.dll"), "wb") as handle:
                handle.write(b"upstream bytes")
            self.assertEqual(desync.stage_dll_hash(directory), desync.sha256_of_bytes(b"upstream bytes"))
            self.assertEqual(desync.stage_dll_hash(os.path.join(directory, "nothing")), desync.UNKNOWN_HASH)

    def test_the_label_and_class_suffix_carry_build_and_short_hash(self):
        self.assertEqual(desync.build_label("fork", "0123456789abcdef"), "fork@01234567")
        self.assertEqual(desync.class_suffix("stock-5.5.0", "0123456789abcdef"), "stock_5_5_0_01234567")


if __name__ == "__main__":
    unittest.main()
