import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import collect
import state
import evaluate_support as fixtures

HERE = os.path.dirname(os.path.abspath(__file__))
FEATURES_MAIN = """
import json, sys, types
sys.path.insert(0, sys.argv[1])
for name, role in json.loads(sys.argv[2]).items():
    module = types.ModuleType("providers." + name)
    module.ROLE = role
    sys.modules[module.__name__] = module
import evaluate
sys.exit(evaluate.main(sys.argv[3:]))
"""
TZ = "Europe/Paris"
NEW_KEYS_IN_RANK_ORDER = [fixtures.KEY, "cpu"]


def spawn(*argv, env=None):
    return subprocess.run([sys.executable, "-B", *argv], capture_output=True, text=True, timeout=30, check=False, env=env)


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        os.makedirs(self.path("preview"))
        os.makedirs(self.path("collections"))
        self.write("config.json", fixtures.make_config())
        self.write("state.json", fixtures.make_state())
        self.write("window.json", fixtures.make_window())
        for name, document in fixtures.collections(notes=fixtures.notes([])).items():
            self.write(f"collections/{name}.json", document)

    def path(self, name):
        return os.path.join(self.dir, name)

    def write(self, name, document):
        fixtures.write_json(self.path(name), document)

    def read(self, name):
        with open(self.path(name), "rb") as handle:
            return handle.read()

    def read_json(self, name):
        return json.loads(self.read(name).decode("utf-8"))

    def features(self, tag="", env=None):
        argv = [
            "features", "--config", self.path("config.json"), "--routine", fixtures.ROUTINE, "--state", self.path("state.json"),
            "--window", self.path("window.json"), "--collections", self.path("collections"), "--place", "cloud",
            "--runtime", "runtime-a", "--out", self.path(f"features{tag}.json"), "--base-out", self.path(f"base{tag}.json"),
            "--rules-out", self.path(f"rules{tag}.json"),
        ]
        return spawn("-c", FEATURES_MAIN, HERE, json.dumps(fixtures.ADAPTER_ROLES), *argv, env=env)

    def judge(self):
        return spawn(
            os.path.join(HERE, "evaluate.py"), "judge", "--features", self.path("features.json"), "--base", self.path("base.json"),
            "--judgment", self.path("judgment.json"), "--out", self.path("facts.json"),
        )

    def annotate(self):
        return spawn(
            os.path.join(HERE, "evaluate.py"), "annotate", "--features", self.path("features.json"), "--facts", self.path("facts.json"),
            "--analysis", self.path("analysis.json"), "--preview", self.path("preview/summary.json"), "--out", self.path("facts.json"),
        )

    def apply(self, directory):
        prefix = f"{directory}/" if directory else ""
        return spawn(
            os.path.join(HERE, "state.py"), "apply", "--state", self.path("state.json"), "--facts", self.path("facts.json"),
            "--window", self.path("window.json"), "--tz", TZ, "--out", self.path(f"{prefix}next.json"),
            "--summary", self.path(f"{prefix}summary.json"), "--record", self.path(f"{prefix}record.json"),
        )

    def succeeded(self, result):
        self.assertEqual((result.returncode, result.stderr), (0, ""))

    def through_judge(self, judgment=None):
        self.succeeded(self.features())
        self.write("judgment.json", fixtures.judgment_of() if judgment is None else judgment)
        self.succeeded(self.judge())

    def through_annotate(self):
        self.through_judge()
        self.succeeded(self.apply("preview"))
        self.write("analysis.json", fixtures.analysis_of())
        self.succeeded(self.annotate())


class LoneSurrogateTest(PipelineTest):
    def test_features_exits_0_on_a_collection_whose_discovered_name_held_a_lone_surrogate(self):
        other = str(10**6 + 78)
        found = fixtures.monitor("Alert", other, name="API \ud800 errors")
        self.write("collections/alerts.json", collect.cleaned(fixtures.alerts(discovered=[found])))

        self.succeeded(self.features())

        self.assertEqual(self.read_json("features.json")["keys"][state.MONITOR_PREFIX + other]["title"], "API \ufffd errors")


class TrackedKeyTest(PipelineTest):
    def test_apply_accepts_a_tracked_monitor_key_that_is_not_a_monitor_id(self):
        self.write("state.json", fixtures.make_state(items={"monitor-abc": fixtures.make_item()}))
        self.through_judge()

        self.succeeded(self.apply(""))

        summary = self.read_json("summary.json")
        self.assertEqual("monitor-abc" in self.read_json("next.json")["items"], True)
        self.assertEqual({"key": "monitor-abc", "gap": "not a monitor id", "runs": 1} in summary["blind_spots"], True)


class OverrideTest(PipelineTest):
    def test_monitor_in_alert_judged_not_open_reaches_the_summary_and_the_record(self):
        closed = fixtures.monitor_verdict(rank=None, open=False, severity="Low", urgency="watch")
        self.through_judge(fixtures.judgment_of(**{fixtures.KEY: closed, "cpu": fixtures.cpu_verdict(rank=1)}))

        self.succeeded(self.apply(""))

        self.assertEqual(self.read_json("facts.json")["overrides"], [fixtures.KEY])
        self.assertEqual(self.read_json("summary.json")["overrides"], [{"key": fixtures.KEY, "title": "API monitor", "state": "Alert"}])
        self.assertEqual(self.read_json("record.json")["overrides"], [fixtures.KEY])

    def test_judgment_that_opens_every_alert_gives_no_override(self):
        self.through_judge()

        self.succeeded(self.apply(""))

        self.assertEqual(self.read_json("summary.json")["overrides"], [])


class RunTest(PipelineTest):
    def test_summary_lists_new_items_in_rank_order_and_the_next_state_stores_the_analysis(self):
        self.through_annotate()

        self.succeeded(self.apply(""))
        summary, stored = self.read_json("summary.json"), self.read_json("next.json")

        self.assertEqual([entry["key"] for entry in summary["new"]], NEW_KEYS_IN_RANK_ORDER)
        self.assertEqual(
            {key: (item["risk"], item["mitigation"], item["action"]) for key, item in stored["items"].items()},
            {key: ("the service degrades for every caller", ["roll back the last deploy"], "page the owner") for key in NEW_KEYS_IN_RANK_ORDER},
        )
        self.assertEqual(summary["new"][0]["reason"], [{"tag": "measured", "claim": "the value is above its limit"}])

    def test_preview_lists_the_keys_the_analysis_is_written_for_in_rank_order(self):
        self.through_judge()

        self.succeeded(self.apply("preview"))

        self.assertEqual([entry["key"] for entry in self.read_json("preview/summary.json")["new"]], NEW_KEYS_IN_RANK_ORDER)

    def test_preview_apply_leaves_the_real_outputs_unwritten(self):
        self.through_judge()

        self.succeeded(self.apply("preview"))

        self.assertEqual([os.path.exists(self.path(name)) for name in ("next.json", "summary.json", "record.json")], [False] * 3)

    def test_both_applies_give_the_same_lifecycle(self):
        self.through_annotate()
        self.succeeded(self.apply(""))

        preview, final = self.read_json("preview/next.json")["items"], self.read_json("next.json")["items"]

        stripped = {key: {name: value for name, value in item.items() if name not in state.OPTIONAL_FIELDS} for key, item in final.items()}
        self.assertEqual(preview, stripped)


class HashSeedTest(PipelineTest):
    NAMES = [f"m{index}" for index in range(8)]

    def test_features_outputs_are_byte_identical_under_two_hash_seeds(self):
        entries = {name: fixtures.ok() if index % 2 else fixtures.failed("HTTP 400 POST /query") for index, name in enumerate(self.NAMES)}
        self.write("config.json", fixtures.make_config(pack=[fixtures.metric_entry(key=name) for name in self.NAMES]))
        self.write("state.json", fixtures.make_state(items={name: fixtures.make_item() for name in self.NAMES[:4]}))
        self.write("collections/gauges.json", fixtures.gauges(metrics=[fixtures.metric(key=name) for name in self.NAMES], entries=entries))

        for seed in ("1", "2"):
            self.succeeded(self.features(tag=seed, env=dict(os.environ, PYTHONHASHSEED=seed)))
        outputs = {seed: [self.read(f"{name}{seed}.json") for name in ("features", "base", "rules")] for seed in ("1", "2")}

        self.assertEqual(outputs["1"], outputs["2"])


class RejectionTest(PipelineTest):
    def test_judgment_citing_another_value_exits_3_naming_the_key_path_and_writes_no_facts(self):
        self.succeeded(self.features())
        self.write("judgment.json", fixtures.judgment_of(**{fixtures.KEY: fixtures.monitor_verdict(), "cpu": fixtures.cpu_verdict(cites={"value": 91})}))

        result = self.judge()

        self.assertEqual((result.returncode, "verdicts.cpu.cites.value" in result.stderr, os.path.exists(self.path("facts.json"))), (3, True, False))

    def test_judgment_that_is_not_json_exits_3_and_writes_no_facts(self):
        self.succeeded(self.features())
        with open(self.path("judgment.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")

        result = self.judge()

        self.assertEqual((result.returncode, os.path.exists(self.path("facts.json"))), (3, False))

    def test_analysis_missing_a_listed_key_exits_3_and_leaves_the_facts_unchanged(self):
        self.through_judge()
        self.succeeded(self.apply("preview"))
        before = self.read("facts.json")
        self.write("analysis.json", fixtures.analysis_of(**{fixtures.KEY: fixtures.analysis_item({"state": "Alert"})}))

        result = self.annotate()

        self.assertEqual((result.returncode, "items.cpu" in result.stderr, self.read("facts.json")), (3, True, before))


class LoneSurrogateAnalysisTest(PipelineTest):
    def test_analysis_text_with_a_lone_surrogate_exits_3_naming_its_path(self):
        self.through_judge()
        self.succeeded(self.apply("preview"))
        item = fixtures.analysis_item({"state": "Alert"}, risk="grows \ud800")
        self.write("analysis.json", fixtures.analysis_of(**{fixtures.KEY: item, "cpu": fixtures.analysis_item({"value": 90})}))

        result = self.annotate()

        self.assertEqual((result.returncode, f"items.{fixtures.KEY}.risk" in result.stderr), (3, True))


if __name__ == "__main__":
    unittest.main()
