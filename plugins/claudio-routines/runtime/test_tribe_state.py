import json
import os
import re
import subprocess
import sys
import unittest

import state
import tribe
import tribe_state
from support import make_state as make_watch_state
from support import ts
from tribe_support import (
    CHANNEL_A, LONG, NOW, PAGE_ID, PREVIOUS, TZ, WRITTEN, FileCase, make_check, make_state, make_warning, run_cli,
)

HERE = os.path.dirname(os.path.abspath(__file__))
REJECTION = r"^(?:expected .+ at |missing key |unexpected key |){path}(?:: |$)"


class CheckStateCase(unittest.TestCase):
    def message(self, document):
        with self.assertRaises(state.Rejected) as caught:
            tribe_state.check_state(document)
        return str(caught.exception)

    def rejects(self, path, mutate):
        document = make_state()
        mutate(document)
        self.assertRegex(self.message(document), REJECTION.format(path=re.escape(path)))

    def rejects_missing(self, *path):
        document = make_state()
        parent = document
        for key in path[:-1]:
            parent = parent[key]
        del parent[path[-1]]
        self.assertEqual(self.message(document), "missing key " + ".".join(path))


class AcceptedStateTest(CheckStateCase):
    def test_accepts_a_full_state(self):
        self.assertIsNone(tribe_state.check_state(make_state()))

    def test_accepts_the_baseline_state(self):
        self.assertIsNone(tribe_state.check_state(tribe_state.initial_state("example")))

    def test_accepts_a_warning_without_mitigation(self):
        document = make_state(warnings={"queue-depth": make_warning(mitigation=[], cites=[], runway="")})
        self.assertIsNone(tribe_state.check_state(document))

    def test_accepts_a_null_metric(self):
        self.assertIsNone(tribe_state.check_state(make_state(warnings={"queue-depth": make_warning(metric=None)})))

    def test_accepts_the_values_of_every_fixed_set(self):
        warnings = {
            f"w{index}": make_warning(severity=severity, when=when, confidence=confidence, status=status)
            for index, (severity, when, confidence, status) in enumerate(
                zip(("High", "Medium", "Low", "Low", "Low"), ("now", "within months", "watch", "now", "now"),
                    ("measured", "inferred", "reported", "measured", "measured"),
                    ("open", "in progress", "mitigated", "decided", "dropped"))
            )
        }
        self.assertIsNone(tribe_state.check_state(make_state(warnings=warnings)))

    def test_accepts_every_check_group(self):
        checks = {f"c{index}": make_check(group=group) for index, group in enumerate(tribe_state.CHECK_GROUPS)}
        self.assertIsNone(tribe_state.check_state(make_state(checks=checks)))


class RootRejectionTest(CheckStateCase):
    def test_rejects_a_state_that_is_not_an_object(self):
        self.assertEqual(self.message([]), "expected an object at <root>")

    def test_rejects_another_schema_name(self):
        self.rejects("schema", lambda s: s.update(schema="tribe-2"))

    def test_rejects_the_watch_schema_number(self):
        self.rejects("schema", lambda s: s.update(schema=2))

    def test_rejects_an_empty_digest(self):
        self.rejects("digest", lambda s: s.update(digest=""))

    def test_rejects_warnings_that_are_not_an_object(self):
        self.rejects("warnings", lambda s: s.update(warnings=[]))

    def test_rejects_a_warnings_key_with_capitals(self):
        self.rejects("warnings.Queue-Depth", lambda s: s["warnings"].update({"Queue-Depth": make_warning()}))

    def test_rejects_a_warnings_key_with_an_underscore(self):
        self.rejects("warnings.queue_depth", lambda s: s["warnings"].update({"queue_depth": make_warning()}))

    def test_rejects_a_checks_key_ending_with_a_dash(self):
        self.rejects("checks.ask-", lambda s: s["checks"].update({"ask-": make_check()}))

    def test_rejects_a_warnings_key_over_the_cap_with_a_capped_key_path(self):
        key = "a" * (tribe_state.KEY_CAP + 40)
        document = make_state()
        document["warnings"][key] = make_warning()

        message = self.message(document)

        self.assertIn(f"at most {tribe_state.KEY_CAP} characters at warnings.{'a' * tribe_state.KEY_CAP}", message)
        self.assertNotIn("a" * (tribe_state.KEY_CAP + 1), message)

    def test_rejects_a_retired_key_with_a_space(self):
        self.rejects("retired.old warning", lambda s: s["retired"].update({"old warning": "Old title"}))

    def test_rejects_an_empty_retired_title(self):
        self.rejects("retired.old-warning", lambda s: s["retired"].update({"old-warning": ""}))


class RunRejectionTest(CheckStateCase):
    def test_rejects_a_run_time_with_an_offset(self):
        self.rejects("run.at", lambda s: s["run"].update(at="2026-10-15T09:45:00+02:00"))

    def test_rejects_a_run_time_that_is_not_a_date(self):
        self.rejects("run.at", lambda s: s["run"].update(at="2026-13-15T09:45:00Z"))

    def test_rejects_a_window_that_ends_before_it_starts(self):
        self.rejects("run.window", lambda s: s["run"].update(window={"from_ts": 20, "to_ts": 10}))

    def test_rejects_a_window_bound_that_is_a_boolean(self):
        self.rejects("run.window.from_ts", lambda s: s["run"].update(window={"from_ts": True, "to_ts": 10}))

    def test_rejects_a_daily_metrics_day_that_is_not_a_date(self):
        self.rejects("run.daily_metrics_on", lambda s: s["run"].update(daily_metrics_on="15/10/2026"))

    def test_rejects_a_previous_page_id_outside_letters_digits_and_dashes(self):
        self.rejects("run.previous_page.id", lambda s: s["run"].update(previous_page={"id": "a b", "written_at": WRITTEN}))

    def test_rejects_a_previous_page_write_time_that_is_not_utc(self):
        self.rejects("run.previous_page.written_at", lambda s: s["run"].update(previous_page={"id": PAGE_ID, "written_at": "yesterday"}))

    def test_rejects_a_week_without_the_w(self):
        self.rejects("run.weekly_heading_week", lambda s: s["run"].update(weekly_heading_week="2026-42"))

    def test_rejects_a_week_above_53(self):
        self.rejects("run.weekly_heading_week", lambda s: s["run"].update(weekly_heading_week="2026-W54"))

    def test_rejects_another_layout_version(self):
        self.rejects("run.layout_version", lambda s: s["run"].update(layout_version=2))

    def test_rejects_a_model_name_that_is_not_text(self):
        self.rejects("run.models.collect", lambda s: s["run"].update(models={"collect": 3}))

    def test_rejects_a_posted_flag_that_is_not_a_boolean(self):
        self.rejects("run.posted", lambda s: s["run"].update(posted="yes"))


class WarningRejectionTest(CheckStateCase):
    def rejects_field(self, field, value):
        self.rejects(f"warnings.queue-depth.{field}", lambda s: s["warnings"]["queue-depth"].update({field: value}))

    def test_rejects_a_severity_outside_the_fixed_set(self):
        self.rejects_field("severity", "Critical")

    def test_rejects_a_lowercase_severity(self):
        self.rejects_field("severity", "high")

    def test_rejects_the_word_months_for_when(self):
        self.rejects_field("when", "months")

    def test_rejects_a_confidence_outside_the_fixed_set(self):
        self.rejects_field("confidence", "high")

    def test_rejects_a_status_outside_the_fixed_set(self):
        self.rejects_field("status", "closed")

    def test_rejects_an_empty_title(self):
        self.rejects_field("title", "")

    def test_names_the_title_bounds(self):
        document = make_state(warnings={"queue-depth": make_warning(title="")})
        self.assertEqual(
            self.message(document),
            "expected a non-empty string of at most 300 characters without control characters at warnings.queue-depth.title",
        )

    def test_rejects_a_title_over_300_characters(self):
        self.rejects_field("title", LONG)

    def test_rejects_a_title_with_a_control_character(self):
        self.rejects_field("title", "line\nbreak")

    def test_rejects_an_empty_topic(self):
        self.rejects_field("topic", "")

    def test_rejects_a_runway_over_300_characters(self):
        self.rejects_field("runway", LONG)

    def test_rejects_a_risk_that_is_not_text(self):
        self.rejects_field("risk", None)

    def test_rejects_an_impact_with_a_control_character(self):
        self.rejects_field("impact", "a\x00b")

    def test_rejects_more_than_three_mitigations(self):
        self.rejects_field("mitigation", ["a", "b", "c", "d"])

    def test_names_the_mitigation_bounds_of_a_stored_warning(self):
        document = make_state(warnings={"queue-depth": make_warning(mitigation=["a", "b", "c", "d"])})
        self.assertEqual(self.message(document), "expected a list of 1 to 3 labels at warnings.queue-depth.mitigation")

    def test_rejects_a_mitigation_that_is_not_a_list(self):
        self.rejects_field("mitigation", "add a worker")

    def test_rejects_a_mitigation_label_with_a_control_character(self):
        self.rejects("warnings.queue-depth.mitigation[1]", lambda s: s["warnings"]["queue-depth"].update(mitigation=["a", "b\n"]))

    def test_rejects_cites_that_are_not_a_list(self):
        self.rejects_field("cites", {})

    def test_rejects_a_cite_that_is_not_an_object(self):
        self.rejects("warnings.queue-depth.cites[0]", lambda s: s["warnings"]["queue-depth"].update(cites=["x"]))

    def test_rejects_a_record_cite_without_a_link(self):
        self.rejects("warnings.queue-depth.cites[0].link", lambda s: s["warnings"]["queue-depth"].update(cites=[{"source": "channels"}]))

    def test_rejects_a_cite_with_neither_source_nor_feature(self):
        self.rejects("warnings.queue-depth.cites[0].source", lambda s: s["warnings"]["queue-depth"].update(cites=[{"name": "value"}]))

    def test_rejects_a_feature_cite_without_a_name(self):
        self.rejects("warnings.queue-depth.cites[0].name", lambda s: s["warnings"]["queue-depth"].update(cites=[{"feature": "metric:a"}]))

    def test_rejects_a_stored_feature_cite_that_carries_its_value(self):
        cite = {"feature": "metric:queue-depth", "name": "value", "value": 3}
        self.rejects("warnings.queue-depth.cites[0].value", lambda s: s["warnings"]["queue-depth"].update(cites=[cite]))

    def test_rejects_an_empty_metric_key(self):
        self.rejects_field("metric", "")

    def test_rejects_a_metric_that_is_a_number(self):
        self.rejects_field("metric", 5)

    def test_rejects_a_negative_run_count(self):
        self.rejects_field("runs_under", -1)

    def test_rejects_a_run_count_that_is_a_boolean(self):
        self.rejects_field("runs_under", True)

    def test_rejects_a_run_count_that_is_text(self):
        self.rejects_field("runs_under", "0")

    def test_rejects_a_since_that_is_not_utc(self):
        self.rejects_field("since", "2026-10-15")

    def test_rejects_a_warning_that_is_not_an_object(self):
        self.rejects("warnings.queue-depth", lambda s: s["warnings"].update({"queue-depth": []}))


class CheckRejectionTest(CheckStateCase):
    def rejects_field(self, field, value):
        self.rejects(f"checks.ask-export.{field}", lambda s: s["checks"]["ask-export"].update({field: value}))

    def test_rejects_a_group_outside_the_fixed_set(self):
        self.rejects_field("group", "Later")

    def test_rejects_the_dated_month_end_group_name(self):
        self.rejects_field("group", "Before the 2026-10-31 month-end")

    def test_rejects_an_empty_text(self):
        self.rejects_field("text", "")

    def test_rejects_a_text_over_300_characters(self):
        self.rejects_field("text", LONG)

    def test_rejects_an_empty_topic(self):
        self.rejects_field("topic", "")

    def test_rejects_a_since_that_is_not_utc(self):
        self.rejects_field("since", "soon")


class CursorRejectionTest(CheckStateCase):
    def test_rejects_an_event_cursor_that_is_text(self):
        self.rejects("cursors.observability.events_ts_ms", lambda s: s["cursors"]["observability"].update(events_ts_ms="1000"))

    def test_rejects_a_monitor_state_that_is_not_text(self):
        self.rejects("cursors.observability.monitors.1001", lambda s: s["cursors"]["observability"].update(monitors={"1001": 1}))

    def test_rejects_a_metric_value_that_is_text(self):
        self.rejects("cursors.observability.metrics.queue-depth", lambda s: s["cursors"]["observability"].update(metrics={"queue-depth": "5"}))

    def test_rejects_a_source_cursor_that_is_not_an_object(self):
        self.rejects("cursors.channels", lambda s: s["cursors"].update(channels=[]))


class ThreadRejectionTest(CheckStateCase):
    def test_rejects_threads_of_a_source_that_are_not_a_list(self):
        self.rejects("threads.channels", lambda s: s["threads"].update(channels={}))

    def test_rejects_a_thread_without_a_root(self):
        self.rejects("threads.channels[0].root_ts", lambda s: s["threads"].update(channels=[{"channel": CHANNEL_A}]))

    def test_rejects_a_thread_channel_that_is_empty(self):
        self.rejects("threads.channels[0].channel", lambda s: s["threads"].update(channels=[{"channel": "", "root_ts": "1.2"}]))

    def test_rejects_a_thread_without_links(self):
        self.rejects("threads.channels[0].links", lambda s: s["threads"].update(channels=[{"channel": CHANNEL_A, "root_ts": "1.2"}]))

    def test_rejects_a_thread_with_an_empty_list_of_links(self):
        self.rejects("threads.channels[0].links", lambda s: s["threads"].update(channels=[{"channel": CHANNEL_A, "root_ts": "1.2", "links": []}]))

    def test_rejects_a_thread_link_that_is_not_text(self):
        self.rejects("threads.channels[0].links[0]", lambda s: s["threads"].update(channels=[{"channel": CHANNEL_A, "root_ts": "1.2", "links": [3]}]))


class BlindSpotRejectionTest(CheckStateCase):
    def test_rejects_a_run_count_that_is_text(self):
        self.rejects("blind_spots[0].runs", lambda s: s["blind_spots"][0].update(runs="1"))

    def test_rejects_a_gap_over_300_characters(self):
        self.rejects("blind_spots[0].gap", lambda s: s["blind_spots"][0].update(gap=LONG))

    def test_rejects_a_blind_spot_without_a_key(self):
        self.rejects("blind_spots[0].key", lambda s: s["blind_spots"][0].pop("key"))


class MissingKeyTest(CheckStateCase):
    pass


def missing_key_test(path):
    def test(self):
        self.rejects_missing(*path.split("."))

    return test


MISSING_KEYS = (
    "schema", "digest", "run", "warnings", "checks", "cursors", "threads", "blind_spots", "retired",
    "run.at", "run.window", "run.daily_metrics_on", "run.previous_page", "run.weekly_heading_week", "run.layout_version",
    "run.models", "run.posted",
    "warnings.queue-depth.title", "warnings.queue-depth.topic", "warnings.queue-depth.severity", "warnings.queue-depth.when",
    "warnings.queue-depth.runway", "warnings.queue-depth.status", "warnings.queue-depth.confidence", "warnings.queue-depth.risk",
    "warnings.queue-depth.impact", "warnings.queue-depth.mitigation", "warnings.queue-depth.cites", "warnings.queue-depth.metric",
    "warnings.queue-depth.runs_under", "warnings.queue-depth.since",
    "checks.ask-export.text", "checks.ask-export.topic", "checks.ask-export.group", "checks.ask-export.since",
    "cursors.observability", "cursors.observability.events_ts_ms", "cursors.observability.monitors", "cursors.observability.metrics",
)
for key_path in MISSING_KEYS:
    setattr(MissingKeyTest, "test_rejects_missing_" + key_path.replace(".", "_").replace("-", "_"), missing_key_test(key_path))


class StateFileTest(FileCase):
    def test_loads_a_valid_state(self):
        self.assertEqual(tribe_state.load(self.write("state.json", make_state())), make_state())

    def test_load_names_the_state_and_the_key_path_of_a_rejection(self):
        document = make_state()
        document["warnings"]["queue-depth"]["severity"] = "Critical"
        with self.assertRaises(state.Rejected) as caught:
            tribe_state.load(self.write("state.json", document))
        self.assertTrue(str(caught.exception).startswith("state: expected one of Low, Medium, High at warnings.queue-depth.severity"))

    def test_load_rejects_a_missing_file_as_an_input_error(self):
        with self.assertRaises(state.InputError):
            tribe_state.load(self.path("absent.json"))

    def test_write_stores_canonical_json(self):
        tribe_state.write(self.path("state.json"), make_state())
        self.assert_canonical("state.json")

    def test_write_round_trips(self):
        tribe_state.write(self.path("state.json"), make_state())
        self.assertEqual(self.read("state.json"), make_state())

    def test_write_of_an_invalid_state_leaves_the_file_unchanged(self):
        path = self.write("state.json", make_state())
        with open(path, "rb") as handle:
            before = handle.read()
        with self.assertRaises(state.Rejected):
            tribe_state.write(path, make_state(warnings={"Bad Key": make_warning()}))
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_write_leaves_no_temp_file_when_it_fails(self):
        os.makedirs(self.path("state.json"))
        with self.assertRaises(state.InputError):
            tribe_state.write(self.path("state.json"), make_state())
        self.assertEqual(os.listdir(self.dir), ["state.json"])


class InitTest(FileCase):
    def init(self, digest="example"):
        return run_cli("init", "--digest", digest, "--out", self.path("state.json"))

    def test_writes_the_empty_baseline(self):
        self.init()
        self.assertEqual(self.read("state.json"), {
            "schema": "tribe-1",
            "digest": "example",
            "run": {
                "at": None,
                "window": None,
                "daily_metrics_on": None,
                "previous_page": None,
                "weekly_heading_week": None,
                "layout_version": 1,
                "models": {},
                "posted": False,
            },
            "warnings": {},
            "checks": {},
            "cursors": {"observability": {"events_ts_ms": None, "monitors": {}, "metrics": {}}},
            "threads": {},
            "blind_spots": [],
            "retired": {},
        })

    def test_exits_0(self):
        self.assertEqual(self.init()[0], 0)

    def test_baseline_passes_the_check(self):
        self.init()
        self.assertIsNone(tribe_state.check_state(self.read("state.json")))

    def test_baseline_is_canonical_json(self):
        self.init()
        self.assert_canonical("state.json")

    def test_empty_digest_exits_3_naming_the_key(self):
        code, _, err = self.init(digest="")
        self.assertEqual((code, "digest" in err), (3, True))

    def test_empty_digest_writes_nothing(self):
        self.init(digest="")
        self.assertEqual(os.listdir(self.dir), [])

    def test_unwritable_out_exits_2_naming_the_path(self):
        out = self.path(os.path.join("absent", "state.json"))
        code, _, err = run_cli("init", "--digest", "example", "--out", out)
        self.assertEqual((code, out in err), (2, True))


class WindowTest(FileCase):
    def window(self, document, now=NOW, *flags, tz=TZ):
        code, _, err = run_cli(
            "window", "--state", self.write("state.json", document), "--now", now, "--tz", tz, "--out", self.path("window.json"), *flags
        )
        return code, err

    def test_baseline_state_reads_the_last_three_hours(self):
        self.window(tribe_state.initial_state("example"))
        self.assertEqual(self.read("window.json")["from_ts"], ts(NOW) - 3 * 3600)

    def test_window_starts_at_the_run_time_of_the_state(self):
        self.window(make_state())
        window = self.read("window.json")
        self.assertEqual((window["from_ts"], window["to_ts"]), (ts(PREVIOUS), ts(NOW)))

    def test_window_equals_the_watch_window_for_the_same_run_time(self):
        self.window(make_state())
        self.assertEqual(self.read("window.json"), state.compute_window(make_watch_state(at=PREVIOUS), state.parse_time(NOW), state.load_zone(TZ)))

    def test_window_is_capped_at_72_hours(self):
        self.window(make_state(at="2026-10-01T00:00:00Z"))
        window = self.read("window.json")
        self.assertEqual((window["from_ts"], window["cut"]["from_ts"]), (ts(NOW) - 72 * 3600, ts("2026-10-01T00:00:00Z")))

    def test_since_makes_an_explicit_uncapped_window(self):
        self.window(make_state(), NOW, "--since", "2026-10-01T00:00:00Z")
        window = self.read("window.json")
        self.assertEqual((window["from_ts"], window["explicit"], window["cut"]), (ts("2026-10-01T00:00:00Z"), True, None))

    def test_report_only_keeps_the_normal_start_and_marks_the_window_explicit(self):
        self.window(make_state(), NOW, "--report-only")
        window = self.read("window.json")
        self.assertEqual((window["from_ts"], window["explicit"]), (ts(PREVIOUS), True))

    def test_window_file_is_canonical_json(self):
        self.window(make_state())
        with open(self.path("window.json"), "rb") as handle:
            raw = handle.read()
        self.assertEqual(raw, state.dump(json.loads(raw)))

    def test_now_before_the_run_time_exits_3(self):
        code, err = self.window(make_state(), "2026-10-15T07:00:00Z")
        self.assertEqual((code, "--now" in err), (3, True))

    def test_invalid_state_exits_3_naming_the_key_path(self):
        document = make_state()
        document["run"]["posted"] = "yes"
        code, err = self.window(document)
        self.assertEqual((code, "run.posted" in err), (3, True))

    def test_watch_state_exits_3(self):
        self.assertEqual(self.window(make_watch_state())[0], 3)

    def test_missing_state_exits_2(self):
        code, _, _ = run_cli("window", "--state", self.path("absent.json"), "--now", NOW, "--tz", TZ, "--out", self.path("window.json"))
        self.assertEqual(code, 2)

    def test_unknown_time_zone_exits_2(self):
        self.assertEqual(self.window(make_state(), tz="Nowhere/Land")[0], 2)

    def test_invalid_now_exits_2(self):
        self.assertEqual(self.window(make_state(), "noon")[0], 2)

    def test_since_and_report_only_together_exit_2(self):
        self.assertEqual(self.window(make_state(), NOW, "--since", PREVIOUS, "--report-only")[0], 2)


class ParserTest(unittest.TestCase):
    def parse(self, *argv):
        return tribe.build_parser().parse_args(list(argv))

    def test_parses_init(self):
        args = self.parse("init", "--digest", "example", "--out", "state.json")
        self.assertEqual((args.command, args.digest, args.out), ("init", "example", "state.json"))

    def test_parses_window(self):
        args = self.parse("window", "--state", "s", "--now", "n", "--tz", "z", "--since", "t", "--out", "w")
        self.assertEqual((args.command, args.state, args.now, args.tz, args.since, args.out), ("window", "s", "n", "z", "t", "w"))

    def test_parses_window_report_only(self):
        args = self.parse("window", "--state", "s", "--now", "n", "--tz", "z", "--report-only", "--out", "w")
        self.assertEqual((args.report_only, args.since), (True, None))

    def test_parses_seed_with_repeated_pages(self):
        args = self.parse("seed", "--page", "a", "--page", "b", "--routine", "r", "--config", "c", "--out", "s")
        self.assertEqual((args.command, args.page, args.routine, args.config, args.out), ("seed", ["a", "b"], "r", "c", "s"))

    def test_runs_init_window_and_seed_through_the_commands_map(self):
        self.assertLessEqual({"init", "window", "seed"}, set(tribe.COMMANDS))


class ScriptTest(FileCase):
    def run_script(self, *argv):
        return subprocess.run([sys.executable, os.path.join(HERE, "tribe.py"), *argv], capture_output=True, text=True, check=False)

    def test_script_init_exits_0_and_writes_the_state(self):
        result = self.run_script("init", "--digest", "example", "--out", self.path("state.json"))
        self.assertEqual((result.returncode, self.read("state.json")["schema"]), (0, "tribe-1"))

    def test_script_exits_3_when_now_is_before_the_run_time(self):
        result = self.run_script("window", "--state", self.write("state.json", make_state()), "--now", "2026-10-15T07:00:00Z",
                                 "--tz", TZ, "--out", self.path("window.json"))
        self.assertEqual(result.returncode, 3)


class PageKeyTest(CheckStateCase):
    def test_rejects_a_previous_page_id_with_dashes(self):
        self.rejects("run.previous_page.id", lambda document: document["run"]["previous_page"].update(id="ab-" * 10 + "ab"))

    def test_rejects_a_previous_page_id_in_upper_case(self):
        self.rejects("run.previous_page.id", lambda document: document["run"]["previous_page"].update(id=PAGE_ID.upper()))


if __name__ == "__main__":
    unittest.main()
