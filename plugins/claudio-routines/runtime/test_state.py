import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import state
from support import (
    NOW, PREVIOUS, TZ, make_analysis, make_facts, make_item, make_run_context, make_state, make_window, obs, run_cli,
    ts,
)

HERE = os.path.dirname(os.path.abspath(__file__))


def analysis_of(source, names):
    return {name: source[name] for name in names}


class CliCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def path(self, name):
        return os.path.join(self.dir, name)

    def write(self, name, document):
        with open(self.path(name), "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        return self.path(name)

    def read(self, name):
        with open(self.path(name), encoding="utf-8") as handle:
            return json.load(handle)

    def read_bytes(self, name):
        with open(self.path(name), "rb") as handle:
            return handle.read()

    def assert_canonical(self, name):
        text = self.read_bytes(name).decode("utf-8")
        self.assertEqual(text, json.dumps(json.loads(text), indent=2, sort_keys=True, ensure_ascii=False) + "\n")


class WindowTest(CliCase):
    def run_window(self, previous_state, now, *flags, tz=TZ):
        state_path = self.write("state.json", previous_state)
        code, _, err = run_cli(
            "window", "--state", state_path, "--now", now, "--tz", tz, "--out", self.path("window.json"), *flags
        )
        return code, err

    def window(self, previous_state, now, *flags, tz=TZ):
        code, err = self.run_window(previous_state, now, *flags, tz=tz)
        return code, self.read("window.json"), err

    def test_window_starts_at_previous_run_and_ends_now(self):
        code, result, _ = self.window(make_state(), NOW)
        self.assertEqual(code, 0)
        self.assertEqual((result["from_ts"], result["to_ts"]), (ts(PREVIOUS), ts(NOW)))
        self.assertIsNone(result["cut"])

    def test_baseline_run_reads_the_last_three_hours(self):
        code, result, _ = self.window(make_state(at=None), "2026-06-01T11:20:00Z")
        self.assertEqual(code, 0)
        self.assertEqual(result["from_ts"], ts("2026-06-01T08:20:00Z"))
        self.assertEqual(result["buckets"], ["Mon 10:00+02:00", "Mon 11:00+02:00", "Mon 12:00+02:00", "Mon 13:00+02:00"])

    def test_baseline_run_retries_known_gaps(self):
        _, result, _ = self.window(make_state(at=None), NOW)
        self.assertTrue(result["retry_known_gaps"])

    def test_same_local_date_does_not_retry_known_gaps(self):
        _, result, _ = self.window(make_state(), NOW)
        self.assertFalse(result["retry_known_gaps"])

    def test_new_local_date_retries_known_gaps_even_on_the_same_utc_date(self):
        _, result, _ = self.window(make_state(at="2026-06-01T21:30:00Z"), "2026-06-01T22:30:00Z")
        self.assertTrue(result["retry_known_gaps"])

    def test_window_longer_than_72_hours_is_cut_and_names_the_unread_span(self):
        code, result, _ = self.window(make_state(at="2026-06-01T00:00:00Z"), "2026-06-05T00:00:00Z")
        self.assertEqual(code, 0)
        self.assertEqual(result["from_ts"], ts("2026-06-02T00:00:00Z"))
        self.assertEqual(result["cut"], {"from_ts": ts("2026-06-01T00:00:00Z"), "to_ts": ts("2026-06-02T00:00:00Z")})
        self.assertEqual(len(result["buckets"]), 72)

    def test_window_of_exactly_72_hours_is_not_cut(self):
        _, result, _ = self.window(make_state(at="2026-06-01T00:00:00Z"), "2026-06-04T00:00:00Z")
        self.assertIsNone(result["cut"])
        self.assertEqual(result["from_ts"], ts("2026-06-01T00:00:00Z"))

    def test_buckets_start_at_the_hour_containing_the_window_start(self):
        _, result, _ = self.window(make_state(at="2026-06-01T10:40:00Z"), "2026-06-01T12:00:00Z")
        self.assertEqual(result["buckets"], ["Mon 12:00+02:00", "Mon 13:00+02:00"])

    def test_buckets_align_on_local_hours_in_a_half_hour_offset_zone(self):
        _, result, _ = self.window(make_state(at="2026-06-01T10:40:00Z"), "2026-06-01T12:00:00Z", tz="Asia/Kolkata")
        self.assertEqual(result["buckets"], ["Mon 16:00+05:30", "Mon 17:00+05:30"])

    def test_first_bucket_is_the_local_hour_containing_the_window_start(self):
        _, result, _ = self.window(make_state(at="2026-06-01T10:20:00Z"), "2026-06-01T11:40:00Z", tz="Asia/Kolkata")
        self.assertEqual(result["buckets"], ["Mon 15:00+05:30", "Mon 16:00+05:30", "Mon 17:00+05:30"])

    def test_now_equal_to_previous_run_gives_an_empty_window(self):
        code, result, _ = self.window(make_state(), PREVIOUS)
        self.assertEqual(code, 0)
        self.assertEqual(result["buckets"], [])

    def test_spring_forward_day_has_no_bucket_for_the_skipped_hour(self):
        _, result, _ = self.window(make_state(at="2026-03-28T23:30:00Z"), "2026-03-29T02:30:00Z")
        self.assertEqual(result["buckets"], ["Sun 00:00+01:00", "Sun 01:00+01:00", "Sun 03:00+02:00", "Sun 04:00+02:00"])

    def test_fall_back_day_has_two_distinct_buckets_for_the_repeated_hour(self):
        _, result, _ = self.window(make_state(at="2026-10-24T23:30:00Z"), "2026-10-25T02:30:00Z")
        self.assertEqual(result["buckets"], ["Sun 01:00+02:00", "Sun 02:00+02:00", "Sun 02:00+01:00", "Sun 03:00+01:00"])

    def test_now_with_an_offset_is_read_as_the_same_instant(self):
        _, result, _ = self.window(make_state(), "2026-06-01T13:00:00+02:00")
        self.assertEqual(result["to_ts"], ts(NOW))

    def test_now_before_previous_run_is_rejected_and_writes_nothing(self):
        code, err = self.run_window(make_state(), "2026-06-01T09:59:59Z")
        self.assertEqual(code, 3)
        self.assertIn("run.at", err)
        self.assertFalse(os.path.exists(self.path("window.json")))

    def test_wrong_state_schema_is_rejected_with_its_key_path(self):
        previous_state = make_state()
        previous_state["schema"] = 1
        code, err = self.run_window(previous_state, NOW)
        self.assertEqual(code, 3)
        self.assertIn("schema", err)

    def test_state_without_previous_run_time_is_rejected_with_its_key_path(self):
        previous_state = make_state()
        del previous_state["run"]["at"]
        code, err = self.run_window(previous_state, NOW)
        self.assertEqual(code, 3)
        self.assertIn("missing key run.at", err)

    def test_unparseable_previous_run_time_is_rejected(self):
        code, err = self.run_window(make_state(at="yesterday"), NOW)
        self.assertEqual(code, 3)
        self.assertIn("run.at", err)

    def test_unknown_time_zone_is_a_usage_error(self):
        code, err = self.run_window(make_state(), NOW, tz="Mars/Olympus")
        self.assertEqual(code, 2)
        self.assertIn("--tz", err)

    def test_unparseable_now_is_a_usage_error(self):
        code, err = self.run_window(make_state(), "soon")
        self.assertEqual(code, 2)
        self.assertIn("--now", err)

    def test_now_without_utc_offset_is_a_usage_error(self):
        code, _ = self.run_window(make_state(), "2026-06-01T11:00:00")
        self.assertEqual(code, 2)

    def test_missing_state_file_is_an_input_error(self):
        code, _, err = run_cli("window", "--state", self.path("absent.json"), "--now", NOW, "--tz", TZ, "--out", self.path("w.json"))
        self.assertEqual(code, 2)
        self.assertIn("absent.json", err)

    def test_state_file_with_invalid_json_is_an_input_error(self):
        with open(self.path("state.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        code, _, _ = run_cli("window", "--state", self.path("state.json"), "--now", NOW, "--tz", TZ, "--out", self.path("w.json"))
        self.assertEqual(code, 2)

    def test_missing_flag_is_a_usage_error(self):
        code, _, _ = run_cli("window", "--state", self.path("state.json"), "--now", NOW)
        self.assertEqual(code, 2)

    def test_window_without_since_is_not_explicit(self):
        _, result, _ = self.window(make_state(), NOW)
        self.assertIs(result["explicit"], False)

    def test_since_starts_the_window_there_and_marks_it_explicit(self):
        code, result, _ = self.window(make_state(), NOW, "--since", "2026-06-01T08:30:00Z")
        self.assertEqual(code, 0)
        self.assertEqual((result["from_ts"], result["to_ts"], result["explicit"]), (ts("2026-06-01T08:30:00Z"), ts(NOW), True))

    def test_since_more_than_72_hours_back_is_not_cut(self):
        _, result, _ = self.window(make_state(), NOW, "--since", "2026-05-25T11:00:00Z")
        self.assertEqual((result["from_ts"], result["cut"], len(result["buckets"])), (ts("2026-05-25T11:00:00Z"), None, 168))

    def test_since_on_a_baseline_state_starts_the_window_there(self):
        _, result, _ = self.window(make_state(at=None), NOW, "--since", "2026-06-01T05:00:00Z")
        self.assertEqual((result["from_ts"], result["explicit"]), (ts("2026-06-01T05:00:00Z"), True))

    def test_since_buckets_start_at_the_local_hour_containing_it(self):
        _, result, _ = self.window(make_state(), NOW, "--since", "2026-06-01T09:40:00Z")
        self.assertEqual(result["buckets"], ["Mon 11:00+02:00", "Mon 12:00+02:00"])

    def test_since_equal_to_now_gives_an_empty_explicit_window(self):
        code, result, _ = self.window(make_state(), NOW, "--since", NOW)
        self.assertEqual((code, result["buckets"], result["explicit"]), (0, [], True))

    def test_since_after_now_is_rejected_and_writes_nothing(self):
        code, err = self.run_window(make_state(), NOW, "--since", "2026-06-01T11:00:01Z")
        self.assertEqual(code, 3)
        self.assertIn("--since", err)
        self.assertFalse(os.path.exists(self.path("window.json")))

    def test_unparseable_since_is_a_usage_error(self):
        code, err = self.run_window(make_state(), NOW, "--since", "last week")
        self.assertEqual(code, 2)
        self.assertIn("--since", err)

    def test_window_file_is_canonical_json(self):
        self.window(make_state(), NOW)
        self.assert_canonical("window.json")

    def test_report_only_keeps_the_normal_start_and_marks_the_window_explicit(self):
        code, result, _ = self.window(make_state(), NOW, "--report-only")
        self.assertEqual((code, result["from_ts"], result["to_ts"], result["explicit"]), (0, ts(PREVIOUS), ts(NOW), True))

    def test_report_only_keeps_the_72_hour_cap(self):
        _, result, _ = self.window(make_state(at="2026-06-01T00:00:00Z"), "2026-06-05T00:00:00Z", "--report-only")
        self.assertEqual(result["cut"], {"from_ts": ts("2026-06-01T00:00:00Z"), "to_ts": ts("2026-06-02T00:00:00Z")})

    def test_report_only_on_a_baseline_state_covers_the_baseline_span(self):
        _, result, _ = self.window(make_state(at=None), NOW, "--report-only")
        self.assertEqual((result["from_ts"], result["explicit"]), (ts(NOW) - 3 * 3600, True))

    def test_report_only_with_since_is_a_usage_error_and_writes_nothing(self):
        code, _ = self.run_window(make_state(), NOW, "--report-only", "--since", "2026-06-01T08:30:00Z")
        self.assertEqual((code, os.path.exists(self.path("window.json"))), (2, False))


class ApplyCase(CliCase):
    def run_apply(self, previous_state, facts, window=None, tz=TZ):
        paths = [
            self.write("state.json", previous_state),
            self.write("facts.json", facts),
            self.write("window.json", window or make_window()),
        ]
        code, _, err = run_cli(
            "apply", "--state", paths[0], "--facts", paths[1], "--window", paths[2],
            "--tz", tz, "--out", self.path("next.json"), "--summary", self.path("summary.json"),
            "--record", self.path("record.json"),
        )
        return code, err

    def apply(self, previous_state, facts, window=None, tz=TZ):
        code, err = self.run_apply(previous_state, facts, window, tz)
        return code, self.read("next.json"), self.read("summary.json"), err

    def assert_rejected_without_output(self, code, err, key_path):
        self.assertEqual(code, 3)
        self.assertIn(key_path, err)
        self.assertFalse(os.path.exists(self.path("next.json")))
        self.assertFalse(os.path.exists(self.path("summary.json")))
        self.assertFalse(os.path.exists(self.path("record.json")))


class ApplyRunTest(ApplyCase):
    def test_run_time_is_the_window_end_and_previous_time_the_stored_run(self):
        _, next_state, _, _ = self.apply(make_state(), make_facts())
        self.assertEqual(next_state["run"]["at"], NOW)
        self.assertEqual(next_state["run"]["previous_at"], PREVIOUS)

    def test_run_window_comes_from_the_window_file(self):
        _, next_state, _, _ = self.apply(make_state(), make_facts())
        self.assertEqual(next_state["run"]["window"], {"from_ts": ts(PREVIOUS), "to_ts": ts(NOW)})

    def test_next_state_is_not_posted_yet(self):
        _, next_state, _, _ = self.apply(make_state(), make_facts())
        self.assertIs(next_state["run"]["posted"], False)

    def test_run_metadata_comes_from_the_facts(self):
        _, next_state, _, _ = self.apply(make_state(), make_facts())
        run = next_state["run"]
        self.assertEqual(
            (run["sources_last_edited"], run["daily_metrics_on"], run["models"], next_state["resolved_queries"]),
            ("2026-05-02", "2026-06-01", {"main": "model-b"}, {"query-a": "done"}),
        )

    def test_next_state_keeps_schema_and_digest(self):
        _, next_state, _, _ = self.apply(make_state(), make_facts())
        self.assertEqual((next_state["schema"], next_state["digest"]), (2, "Prod watch"))

    def test_baseline_state_has_a_null_previous_time(self):
        code, next_state, _, _ = self.apply(make_state(at=None), make_facts())
        self.assertEqual(code, 0)
        self.assertIsNone(next_state["run"]["previous_at"])

    def test_cursor_moves_forward_from_the_facts(self):
        _, next_state, _, _ = self.apply(make_state(), make_facts())
        self.assertEqual(
            next_state["cursors"]["observability"],
            {"events_ts_ms": 2000, "monitors": {"monitor-1001": "Alert"}, "metrics": {"metric-a": 12}},
        )

    def test_null_event_cursor_in_facts_keeps_the_stored_cursor(self):
        facts = make_facts()
        facts["cursors"]["events_ts_ms"] = None
        _, next_state, _, _ = self.apply(make_state(), facts)
        self.assertEqual(next_state["cursors"]["observability"]["events_ts_ms"], 1000)

    def test_failed_monitors_read_keeps_the_stored_monitor_states(self):
        _, next_state, _, _ = self.apply(make_state(), make_facts(monitors=False))
        cursors = next_state["cursors"]["observability"]
        self.assertEqual((cursors["monitors"], cursors["metrics"]), ({"monitor-1001": "OK"}, {"metric-a": 12}))

    def test_failed_metrics_read_keeps_the_stored_metric_values(self):
        _, next_state, _, _ = self.apply(make_state(), make_facts(metrics=False))
        cursors = next_state["cursors"]["observability"]
        self.assertEqual((cursors["monitors"], cursors["metrics"]), ({"monitor-1001": "Alert"}, {"metric-a": 5}))

    def test_first_numeric_cursor_after_a_null_stored_cursor_is_kept(self):
        _, next_state, _, _ = self.apply(make_state(events_ts_ms=None), make_facts())
        self.assertEqual(next_state["cursors"]["observability"]["events_ts_ms"], 2000)

    def test_cursor_equal_to_the_stored_cursor_is_accepted(self):
        facts = make_facts()
        facts["cursors"]["events_ts_ms"] = 1000
        code, next_state, _, _ = self.apply(make_state(), facts)
        self.assertEqual(code, 0)
        self.assertEqual(next_state["cursors"]["observability"]["events_ts_ms"], 1000)

    def test_cursor_older_than_the_stored_cursor_is_rejected(self):
        facts = make_facts()
        facts["cursors"]["events_ts_ms"] = 999
        code, err = self.run_apply(make_state(), facts)
        self.assert_rejected_without_output(code, err, "cursors.events_ts_ms")

    def test_window_ending_before_the_stored_run_is_rejected(self):
        window = make_window(start="2026-06-01T08:00:00Z", end="2026-06-01T09:00:00Z")
        code, err = self.run_apply(make_state(), make_facts(), window)
        self.assert_rejected_without_output(code, err, "to_ts")

    def test_window_file_missing_its_end_is_rejected(self):
        window = make_window()
        del window["to_ts"]
        code, err = self.run_apply(make_state(), make_facts(), window)
        self.assert_rejected_without_output(code, err, "missing key to_ts")

    def test_cut_span_is_reported_in_the_summary(self):
        cut = {"from_ts": ts("2026-05-28T10:00:00Z"), "to_ts": ts("2026-05-29T10:00:00Z")}
        _, _, summary, _ = self.apply(make_state(), make_facts(), make_window(cut=cut))
        self.assertEqual(summary["cut"], cut)

    def test_next_state_keeps_the_facts_mutes(self):
        mutes = [{"key": "metric-a", "until": "2026-06-10"}, {"key": "monitor-1001", "until": "2026-05-01"}]
        _, next_state, _, _ = self.apply(make_state(), make_facts(mutes=mutes))
        self.assertEqual(next_state["run"]["mutes"], mutes)

    def test_next_state_replaces_stale_stored_mutes_with_the_facts_mutes(self):
        previous_state = make_state()
        previous_state["run"]["mutes"] = [{"key": "metric-z", "until": "2026-05-01"}]
        mutes = [{"key": "metric-a", "until": "2026-06-10"}]
        _, next_state, _, _ = self.apply(previous_state, make_facts(mutes=mutes))
        self.assertEqual(next_state["run"]["mutes"], mutes)

    def test_state_without_stored_mutes_is_applied(self):
        code, _, _, _ = self.apply(make_state(), make_facts())
        self.assertEqual(code, 0)

    def test_same_inputs_give_byte_identical_outputs(self):
        previous_state = make_state(items={"metric-a": make_item()})
        facts = make_facts({"metric-a": obs(value=40)})
        outputs = ("next.json", "summary.json", "record.json")
        self.apply(previous_state, facts)
        first = [self.read_bytes(name) for name in outputs]
        self.apply(previous_state, facts)
        self.assertEqual(first, [self.read_bytes(name) for name in outputs])


class ApplyRejectionTest(ApplyCase):
    def test_state_with_wrong_schema_is_rejected_and_nothing_written(self):
        previous_state = make_state()
        previous_state["schema"] = 3
        code, err = self.run_apply(previous_state, make_facts())
        self.assert_rejected_without_output(code, err, "schema")

    def test_state_item_missing_a_field_is_rejected_with_its_key_path(self):
        item = make_item()
        del item["severity"]
        code, err = self.run_apply(make_state(items={"metric-a": item}), make_facts({"metric-a": obs()}))
        self.assert_rejected_without_output(code, err, "missing key items.metric-a.severity")

    def test_state_item_with_unknown_severity_is_rejected(self):
        code, err = self.run_apply(
            make_state(items={"metric-a": make_item(severity="Critical")}), make_facts({"metric-a": obs()})
        )
        self.assert_rejected_without_output(code, err, "items.metric-a.severity")

    def test_observation_missing_a_field_is_rejected_with_its_key_path(self):
        observation = obs()
        del observation["over"]
        code, err = self.run_apply(make_state(), make_facts({"metric-a": observation}))
        self.assert_rejected_without_output(code, err, "missing key observations.metric-a.over")

    def test_observation_with_unknown_urgency_is_rejected(self):
        code, err = self.run_apply(make_state(), make_facts({"metric-a": obs(when="later")}))
        self.assert_rejected_without_output(code, err, "observations.metric-a.when")

    def test_observation_with_text_value_is_rejected(self):
        code, err = self.run_apply(make_state(), make_facts({"metric-a": obs(value="12")}))
        self.assert_rejected_without_output(code, err, "observations.metric-a.value")

    def test_source_without_read_flag_is_rejected(self):
        facts = make_facts()
        del facts["sources"]["metrics"]["read"]
        code, err = self.run_apply(make_state(), facts)
        self.assert_rejected_without_output(code, err, "missing key sources.metrics.read")

    def test_observation_from_an_unknown_source_is_rejected(self):
        code, err = self.run_apply(make_state(), make_facts({"dlq-queue-a": obs(source="queues")}))
        self.assert_rejected_without_output(code, err, "observations.dlq-queue-a.source")

    def test_monitor_key_observed_from_metrics_is_rejected(self):
        code, err = self.run_apply(make_state(), make_facts({"monitor-1001": obs(source="metrics")}))
        self.assert_rejected_without_output(code, err, "observations.monitor-1001.source")

    def test_metric_key_observed_from_monitors_is_rejected(self):
        code, err = self.run_apply(make_state(), make_facts({"metric-a": obs(source="monitors")}))
        self.assert_rejected_without_output(code, err, "observations.metric-a.source")

    def test_untracked_key_over_threshold_from_an_unread_source_is_rejected(self):
        code, err = self.run_apply(make_state(), make_facts({"metric-a": obs()}, metrics=False))
        self.assert_rejected_without_output(code, err, "observations.metric-a")

    def test_window_starting_after_its_end_is_rejected(self):
        code, err = self.run_apply(make_state(), make_facts(), make_window(start=NOW, end=PREVIOUS))
        self.assert_rejected_without_output(code, err, "from_ts")

    def test_unwritable_summary_leaves_no_next_state_and_no_temp_file(self):
        paths = [
            self.write("state.json", make_state()),
            self.write("facts.json", make_facts({"metric-a": obs()})),
            self.write("window.json", make_window()),
        ]
        code, _, _ = run_cli(
            "apply", "--state", paths[0], "--facts", paths[1], "--window", paths[2],
            "--tz", TZ, "--out", self.path("next.json"), "--summary", self.path("missing/summary.json"),
            "--record", self.path("record.json"),
        )
        self.assertEqual(code, 2)
        self.assertEqual(sorted(os.listdir(self.dir)), ["facts.json", "state.json", "window.json"])

    def test_unwritable_record_leaves_no_output_and_no_temp_file(self):
        paths = [
            self.write("state.json", make_state()),
            self.write("facts.json", make_facts({"metric-a": obs()})),
            self.write("window.json", make_window()),
        ]
        code, _, _ = run_cli(
            "apply", "--state", paths[0], "--facts", paths[1], "--window", paths[2],
            "--tz", TZ, "--out", self.path("next.json"), "--summary", self.path("summary.json"),
            "--record", self.path("missing/record.json"),
        )
        self.assertEqual(code, 2)
        self.assertEqual(sorted(os.listdir(self.dir)), ["facts.json", "state.json", "window.json"])

    def test_failed_rename_of_the_record_leaves_no_next_state(self):
        os.mkdir(self.path("record.json"))
        code, _ = self.run_apply(make_state(), make_facts({"metric-a": obs()}))
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.path("next.json")))

    def test_failed_rename_of_the_summary_leaves_no_record(self):
        os.mkdir(self.path("summary.json"))
        code, _ = self.run_apply(make_state(), make_facts({"metric-a": obs()}))
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.path("record.json")))

    def test_window_file_without_its_explicit_flag_is_rejected(self):
        window = make_window()
        del window["explicit"]
        code, err = self.run_apply(make_state(), make_facts(), window)
        self.assert_rejected_without_output(code, err, "missing key explicit")

    def test_window_file_with_a_text_explicit_flag_is_rejected(self):
        code, err = self.run_apply(make_state(), make_facts(), make_window(explicit="yes"))
        self.assert_rejected_without_output(code, err, "explicit")

    def test_missing_record_flag_is_a_usage_error(self):
        paths = [self.write("state.json", make_state()), self.write("facts.json", make_facts()), self.write("window.json", make_window())]
        code, _, _ = run_cli(
            "apply", "--state", paths[0], "--facts", paths[1], "--window", paths[2],
            "--tz", TZ, "--out", self.path("next.json"), "--summary", self.path("summary.json"),
        )
        self.assertEqual(code, 2)

    def test_non_finite_cursor_is_rejected(self):
        facts = make_facts()
        facts["cursors"]["events_ts_ms"] = float("nan")
        code, err = self.run_apply(make_state(), facts)
        self.assert_rejected_without_output(code, err, "cursors.events_ts_ms")

    def test_infinite_observation_value_is_rejected(self):
        code, err = self.run_apply(make_state(), make_facts({"metric-a": obs(value=float("inf"))}))
        self.assert_rejected_without_output(code, err, "observations.metric-a.value")

    def test_non_finite_opened_value_in_state_is_rejected(self):
        previous_state = make_state(items={"metric-a": make_item(opened_value=float("nan"))})
        code, err = self.run_apply(previous_state, make_facts({"metric-a": obs()}))
        self.assert_rejected_without_output(code, err, "items.metric-a.opened_value")

    def test_failed_rename_of_the_summary_leaves_no_next_state(self):
        os.mkdir(self.path("summary.json"))
        code, _ = self.run_apply(make_state(), make_facts({"metric-a": obs()}))
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.path("next.json")))

    def test_failed_rename_of_the_next_state_leaves_no_temp_file(self):
        os.mkdir(self.path("next.json"))
        code, _ = self.run_apply(make_state(), make_facts({"metric-a": obs()}))
        self.assertEqual(code, 2)
        self.assertEqual([name for name in os.listdir(self.dir) if name.endswith(".tmp")], [])

    def test_facts_missing_retried_gaps_are_rejected(self):
        facts = make_facts()
        del facts["blind_spots_retried"]
        code, err = self.run_apply(make_state(), facts)
        self.assert_rejected_without_output(code, err, "missing key blind_spots_retried")

    def test_tracked_key_absent_while_its_source_was_read_is_rejected(self):
        code, err = self.run_apply(make_state(items={"metric-a": make_item()}), make_facts())
        self.assert_rejected_without_output(code, err, "observations.metric-a")

    def test_tracked_monitor_absent_while_monitors_were_read_is_rejected(self):
        code, err = self.run_apply(
            make_state(items={"monitor-1001": make_item(topic="monitors")}), make_facts(metrics=False)
        )
        self.assert_rejected_without_output(code, err, "observations.monitor-1001")

    def test_unreadable_facts_file_is_an_input_error(self):
        state_path = self.write("state.json", make_state())
        window_path = self.write("window.json", make_window())
        code, _, _ = run_cli(
            "apply", "--state", state_path, "--facts", self.path("absent.json"), "--window", window_path,
            "--tz", TZ, "--out", self.path("next.json"), "--summary", self.path("summary.json"),
            "--record", self.path("record.json"),
        )
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.path("next.json")))


class LifecycleTest(ApplyCase):
    def test_key_observed_over_threshold_opens_a_new_item(self):
        _, next_state, summary, _ = self.apply(make_state(), make_facts({"metric-a": obs(value=12)}))
        item = next_state["items"]["metric-a"]
        self.assertEqual(
            (item["opened_value"], item["since"], item["runs_under_threshold"], item["status"], item["topic"]),
            (12, NOW, 0, "open", "metrics"),
        )
        self.assertEqual([entry["key"] for entry in summary["new"]], ["metric-a"])

    def test_new_item_summary_entry_carries_the_message_fields(self):
        observation = obs(risk="queue grows", action="restart consumer")
        _, _, summary, _ = self.apply(make_state(), make_facts({"metric-a": observation}))
        self.assertEqual(summary["new"], [{
            "key": "metric-a", "title": "Metric A", "severity": "Medium", "when": "watch",
            "link": "https://example.test/metric-a", "last_value": "10",
            "risk": "queue grows", "action": "restart consumer", "rank": None,
        }])

    def test_key_observed_under_threshold_without_item_opens_nothing(self):
        _, next_state, summary, _ = self.apply(make_state(), make_facts({"metric-a": obs(over=False)}))
        self.assertEqual(next_state["items"], {})
        self.assertFalse(summary["post"])

    def test_item_still_over_without_change_stays_open(self):
        _, next_state, summary, _ = self.apply(
            make_state(items={"metric-a": make_item(runs=1)}), make_facts({"metric-a": obs(value=14)})
        )
        self.assertEqual(next_state["items"]["metric-a"]["runs_under_threshold"], 0)
        self.assertEqual(summary["still_open"], {"High": [], "Medium": [{"key": "metric-a", "title": "Metric A"}], "Low": []})
        self.assertFalse(summary["post"])

    def test_severity_moving_up_escalates(self):
        _, next_state, summary, _ = self.apply(
            make_state(items={"metric-a": make_item()}), make_facts({"metric-a": obs(severity="High")})
        )
        self.assertEqual([entry["key"] for entry in summary["escalated"]], ["metric-a"])
        self.assertEqual(next_state["items"]["metric-a"]["severity"], "High")

    def test_urgency_moving_up_escalates(self):
        _, _, summary, _ = self.apply(
            make_state(items={"metric-a": make_item()}), make_facts({"metric-a": obs(when="within months")})
        )
        self.assertEqual(len(summary["escalated"]), 1)

    def test_severity_moving_down_does_not_escalate(self):
        _, next_state, summary, _ = self.apply(
            make_state(items={"metric-a": make_item(severity="High")}), make_facts({"metric-a": obs(severity="Low")})
        )
        self.assertEqual(summary["escalated"], [])
        self.assertEqual(next_state["items"]["metric-a"]["severity"], "Low")

    def test_value_above_150_percent_of_opening_escalates_and_resets_opened_value(self):
        _, next_state, summary, _ = self.apply(
            make_state(items={"metric-a": make_item(opened_value=10)}), make_facts({"metric-a": obs(value=15.5)})
        )
        self.assertEqual(len(summary["escalated"]), 1)
        self.assertEqual(next_state["items"]["metric-a"]["opened_value"], 15.5)

    def test_value_at_exactly_150_percent_does_not_escalate(self):
        _, next_state, summary, _ = self.apply(
            make_state(items={"metric-a": make_item(opened_value=10)}), make_facts({"metric-a": obs(value=15)})
        )
        self.assertEqual(summary["escalated"], [])
        self.assertEqual(next_state["items"]["metric-a"]["opened_value"], 10)

    def test_null_value_skips_the_value_test(self):
        _, _, summary, _ = self.apply(
            make_state(items={"metric-a": make_item(opened_value=10)}), make_facts({"metric-a": obs(value=None)})
        )
        self.assertEqual(summary["escalated"], [])

    def test_zero_opened_value_skips_the_value_test(self):
        _, _, summary, _ = self.apply(
            make_state(items={"metric-a": make_item(opened_value=0)}), make_facts({"metric-a": obs(value=50)})
        )
        self.assertEqual(summary["escalated"], [])

    def test_item_without_opened_value_gets_its_current_value_without_escalating(self):
        item = make_item()
        del item["opened_value"]
        _, next_state, summary, _ = self.apply(make_state(items={"metric-a": item}), make_facts({"metric-a": obs(value=80)}))
        self.assertEqual(next_state["items"]["metric-a"]["opened_value"], 80)
        self.assertEqual(summary["escalated"], [])

    def test_legacy_item_gets_opened_value_only_from_an_over_threshold_observation(self):
        item = make_item()
        del item["opened_value"]
        self.apply(make_state(items={"metric-a": item}), make_facts({"metric-a": obs(over=False, value=40)}))
        under_state = self.read("next.json")
        window = make_window(start=NOW, end="2026-06-01T12:00:00Z")
        _, next_state, summary, _ = self.apply(under_state, make_facts({"metric-a": obs(value=70)}), window)
        self.assertEqual(summary["escalated"], [])
        self.assertEqual(next_state["items"]["metric-a"]["opened_value"], 70)

    def test_untracked_key_under_threshold_from_an_unread_source_opens_nothing(self):
        _, next_state, _, _ = self.apply(make_state(), make_facts({"metric-a": obs(over=False)}, metrics=False))
        self.assertEqual(next_state["items"], {})

    def test_tracked_key_absent_while_its_source_is_unread_stays_unchanged(self):
        previous_item = make_item(runs=1)
        _, next_state, _, _ = self.apply(make_state(items={"metric-a": previous_item}), make_facts(metrics=False))
        self.assertEqual(next_state["items"]["metric-a"], previous_item)

    def test_first_run_under_threshold_keeps_the_item_open(self):
        _, next_state, summary, _ = self.apply(
            make_state(items={"metric-a": make_item()}), make_facts({"metric-a": obs(over=False, value=3)})
        )
        item = next_state["items"]["metric-a"]
        self.assertEqual((item["runs_under_threshold"], item["last_value"]), (1, "3"))
        self.assertEqual(summary["resolved"], [])

    def test_numeric_last_value_is_stored_and_reported_as_a_number(self):
        _, next_state, summary, _ = self.apply(make_state(), make_facts({"metric-a": obs(value=12, last_value=12)}))
        self.assertEqual(next_state["items"]["metric-a"]["last_value"], 12)
        self.assertEqual(summary["new"][0]["last_value"], 12)

    def test_second_run_under_threshold_resolves_and_removes_the_item(self):
        _, next_state, summary, _ = self.apply(
            make_state(items={"metric-a": make_item(runs=1)}), make_facts({"metric-a": obs(over=False, value=3)})
        )
        self.assertNotIn("metric-a", next_state["items"])
        self.assertEqual([(entry["key"], entry["last_value"]) for entry in summary["resolved"]], [("metric-a", "3")])
        self.assertTrue(summary["post"])

    def test_resolved_item_is_not_reported_again_on_the_next_run(self):
        self.apply(make_state(items={"metric-a": make_item(runs=1)}), make_facts({"metric-a": obs(over=False)}))
        resolved_state = self.read("next.json")
        facts = make_facts({"metric-a": obs(over=False)}, cursors=resolved_state["cursors"]["observability"])
        window = make_window(start=NOW, end="2026-06-01T12:00:00Z")
        _, _, summary, _ = self.apply(resolved_state, facts, window)
        self.assertEqual(summary["resolved"], [])

    def test_unread_source_leaves_its_items_unchanged(self):
        previous_item = make_item(runs=1)
        _, next_state, summary, _ = self.apply(
            make_state(items={"metric-a": previous_item}), make_facts({"metric-a": obs(over=False)}, metrics=False)
        )
        self.assertEqual(next_state["items"]["metric-a"], previous_item)
        self.assertEqual(summary["still_open"]["Medium"], [{"key": "metric-a", "title": "Metric A"}])

    def test_all_sources_read_and_nothing_over_only_counts_runs_and_resolves_at_two(self):
        previous_state = make_state(items={
            "metric-a": make_item(title="Metric A", runs=0),
            "metric-b": make_item(title="Metric B", runs=1),
            "monitor-1001": make_item(title="Monitor 1001", severity="High", runs=0),
        })
        facts = make_facts({
            "metric-a": obs(over=False, title="Metric A"),
            "metric-b": obs(over=False, title="Metric B"),
            "monitor-1001": obs(over=False, source="monitors", severity="High", title="Monitor 1001"),
        })
        _, next_state, summary, _ = self.apply(previous_state, facts)
        self.assertEqual(
            {key: item["runs_under_threshold"] for key, item in next_state["items"].items()},
            {"metric-a": 1, "monitor-1001": 1},
        )
        self.assertEqual([entry["key"] for entry in summary["resolved"]], ["metric-b"])
        self.assertEqual((summary["new"], summary["escalated"]), ([], []))

    def test_still_open_items_are_grouped_by_severity(self):
        previous_state = make_state(items={
            "metric-a": make_item(title="Metric A", severity="High"),
            "metric-b": make_item(title="Metric B", severity="Low"),
            "metric-c": make_item(title="Metric C", severity="High"),
        })
        facts = make_facts({
            "metric-a": obs(severity="High", title="Metric A"),
            "metric-b": obs(severity="Low", title="Metric B"),
            "metric-c": obs(severity="High", title="Metric C"),
        })
        _, _, summary, _ = self.apply(previous_state, facts)
        self.assertEqual(summary["still_open"], {
            "High": [{"key": "metric-a", "title": "Metric A"}, {"key": "metric-c", "title": "Metric C"}],
            "Medium": [],
            "Low": [{"key": "metric-b", "title": "Metric B"}],
        })

    def test_summary_counts_each_list(self):
        previous_state = make_state(items={"metric-a": make_item(), "metric-b": make_item(title="Metric B", runs=1)})
        facts = make_facts({
            "metric-a": obs(),
            "metric-b": obs(over=False, title="Metric B"),
            "metric-c": obs(title="Metric C"),
        })
        _, _, summary, _ = self.apply(previous_state, facts)
        self.assertEqual(summary["counts"], {"new": 1, "escalated": 0, "resolved": 1, "still_open": 1, "tracked": 2})


class RankTest(ApplyCase):
    def new_keys(self, observations):
        _, _, summary, _ = self.apply(make_state(), make_facts(observations))
        return [entry["key"] for entry in summary["new"]]

    def test_new_items_are_listed_by_rank(self):
        self.assertEqual(self.new_keys({"metric-a": obs(rank=2), "metric-b": obs(rank=1)}), ["metric-b", "metric-a"])

    def test_new_items_of_equal_rank_are_listed_by_key(self):
        self.assertEqual(self.new_keys({"metric-b": obs(rank=1), "metric-a": obs(rank=1)}), ["metric-a", "metric-b"])

    def test_new_items_without_rank_are_listed_last_by_key(self):
        keys = self.new_keys({"metric-a": obs(), "metric-b": obs(rank=None), "metric-c": obs(rank=1)})
        self.assertEqual(keys, ["metric-c", "metric-a", "metric-b"])

    def test_escalated_items_are_listed_by_rank(self):
        previous_state = make_state(items={"metric-a": make_item(), "metric-b": make_item(title="Metric B")})
        facts = make_facts({
            "metric-a": obs(severity="High", rank=2),
            "metric-b": obs(severity="High", title="Metric B", rank=1),
        })
        _, _, summary, _ = self.apply(previous_state, facts)
        self.assertEqual([entry["key"] for entry in summary["escalated"]], ["metric-b", "metric-a"])

    def test_summary_entry_carries_its_rank(self):
        _, _, summary, _ = self.apply(make_state(), make_facts({"metric-a": obs(rank=3)}))
        self.assertEqual(summary["new"][0]["rank"], 3)

    def test_summary_entry_without_rank_carries_a_null_rank(self):
        _, _, summary, _ = self.apply(make_state(), make_facts({"metric-a": obs()}))
        self.assertIsNone(summary["new"][0]["rank"])

    def test_resolved_summary_entry_carries_a_null_rank(self):
        facts = make_facts({"metric-a": obs(over=False, rank=None)})
        _, _, summary, _ = self.apply(make_state(items={"metric-a": make_item(runs=1)}), facts)
        self.assertIsNone(summary["resolved"][0]["rank"])

    def test_item_does_not_store_the_rank(self):
        _, next_state, _, _ = self.apply(make_state(), make_facts({"metric-a": obs(rank=1)}))
        self.assertNotIn("rank", next_state["items"]["metric-a"])

    def test_rejects_a_rank_of_zero_naming_its_path(self):
        code, err = self.run_apply(make_state(), make_facts({"metric-a": obs(rank=0)}))
        self.assert_rejected_without_output(code, err, "observations.metric-a.rank")

    def test_rejects_a_fractional_rank_naming_its_path(self):
        code, err = self.run_apply(make_state(), make_facts({"metric-a": obs(rank=1.5)}))
        self.assert_rejected_without_output(code, err, "observations.metric-a.rank")

    def test_rejects_a_text_rank_naming_its_path(self):
        code, err = self.run_apply(make_state(), make_facts({"metric-a": obs(rank="1")}))
        self.assert_rejected_without_output(code, err, "observations.metric-a.rank")

    def test_rejects_a_boolean_rank_naming_its_path(self):
        code, err = self.run_apply(make_state(), make_facts({"metric-a": obs(rank=True)}))
        self.assert_rejected_without_output(code, err, "observations.metric-a.rank")


class AnalysisTest(ApplyCase):
    def test_new_item_stores_its_analysis(self):
        _, next_state, _, _ = self.apply(make_state(), make_facts({"metric-a": obs(**make_analysis())}))
        item = next_state["items"]["metric-a"]
        self.assertEqual(analysis_of(item, make_analysis()), make_analysis())

    def test_still_open_item_keeps_its_stored_analysis_when_the_observation_omits_it(self):
        previous_state = make_state(items={"metric-a": make_item(**make_analysis())})
        _, next_state, _, _ = self.apply(previous_state, make_facts({"metric-a": obs(value=12)}))
        item = next_state["items"]["metric-a"]
        self.assertEqual(analysis_of(item, make_analysis()), make_analysis())

    def test_escalated_item_takes_the_new_analysis(self):
        previous_state = make_state(items={"metric-a": make_item(**make_analysis())})
        analysis = make_analysis(risk="orders are lost", action="page the owner")
        analysis["mitigation"] = ["fail over the queue"]
        _, next_state, _, _ = self.apply(previous_state, make_facts({"metric-a": obs(severity="High", **analysis)}))
        item = next_state["items"]["metric-a"]
        self.assertEqual(analysis_of(item, analysis), analysis)


class MuteTest(ApplyCase):
    def test_muted_new_item_is_tracked_but_left_out_of_the_summary(self):
        facts = make_facts({"metric-a": obs()}, mutes=[{"key": "metric-a", "until": "2026-06-10"}])
        _, next_state, summary, _ = self.apply(make_state(), facts)
        self.assertIn("metric-a", next_state["items"])
        self.assertEqual((summary["new"], summary["muted_changes"], summary["post"]), ([], 1, False))

    def test_muted_escalation_is_counted_not_listed(self):
        facts = make_facts({"metric-a": obs(severity="High")}, mutes=[{"key": "metric-a", "until": "2026-06-10"}])
        _, next_state, summary, _ = self.apply(make_state(items={"metric-a": make_item()}), facts)
        self.assertEqual((summary["escalated"], summary["muted_changes"]), ([], 1))
        self.assertEqual(next_state["items"]["metric-a"]["severity"], "High")

    def test_muted_resolution_removes_the_item_and_is_counted(self):
        facts = make_facts({"metric-a": obs(over=False)}, mutes=[{"key": "metric-a", "until": "2026-06-10"}])
        _, next_state, summary, _ = self.apply(make_state(items={"metric-a": make_item(runs=1)}), facts)
        self.assertEqual((next_state["items"], summary["resolved"], summary["muted_changes"]), ({}, [], 1))

    def test_muted_open_item_is_left_out_of_still_open(self):
        facts = make_facts({"metric-a": obs()}, mutes=[{"key": "metric-a", "until": "2026-06-10"}])
        _, _, summary, _ = self.apply(make_state(items={"metric-a": make_item()}), facts)
        self.assertEqual((summary["still_open"]["Medium"], summary["muted_changes"]), ([], 0))

    def test_mute_ends_on_its_date_in_the_window_end_local_date(self):
        facts = make_facts({"metric-a": obs()}, mutes=[{"key": "metric-a", "until": "2026-06-02"}])
        window = make_window(start="2026-06-01T21:00:00Z", end="2026-06-01T22:30:00Z")
        previous_state = make_state(at="2026-06-01T21:00:00Z")
        _, _, summary, _ = self.apply(previous_state, facts, window)
        self.assertEqual([entry["key"] for entry in summary["new"]], ["metric-a"])

    def test_mute_with_invalid_date_is_rejected(self):
        facts = make_facts({"metric-a": obs()}, mutes=[{"key": "metric-a", "until": "next week"}])
        code, err = self.run_apply(make_state(), facts)
        self.assert_rejected_without_output(code, err, "mutes[0].until")


class DeferredTest(ApplyCase):
    def test_deferred_tracked_key_absent_while_its_source_was_read_is_accepted(self):
        code, _ = self.run_apply(make_state(items={"metric-a": make_item()}), make_facts(deferred=["metric-a"]))
        self.assertEqual(code, 0)

    def test_deferred_key_keeps_its_item_unchanged(self):
        _, next_state, _, _ = self.apply(make_state(items={"metric-a": make_item(runs=1)}), make_facts(deferred=["metric-a"]))
        self.assertEqual(next_state["items"]["metric-a"], make_item(runs=1))

    def test_deferred_item_is_reported_still_open(self):
        _, _, summary, _ = self.apply(make_state(items={"metric-a": make_item()}), make_facts(deferred=["metric-a"]))
        self.assertEqual((summary["still_open"]["Medium"], summary["resolved"]), ([{"key": "metric-a", "title": "Metric A"}], []))

    def test_deferred_key_without_item_opens_nothing(self):
        _, next_state, _, _ = self.apply(make_state(), make_facts(deferred=["metric-a"]))
        self.assertEqual(next_state["items"], {})

    def test_deferred_key_whose_source_was_not_read_keeps_its_item_unchanged(self):
        facts = make_facts(metrics=False, deferred=["metric-a"])
        _, next_state, _, _ = self.apply(make_state(items={"metric-a": make_item(runs=1)}), facts)
        self.assertEqual(next_state["items"]["metric-a"], make_item(runs=1))

    def test_deferred_key_that_is_a_blind_spot_is_held_and_its_gap_runs_are_counted(self):
        previous_state = make_state(
            items={"metric-a": make_item()}, blind_spots=[{"key": "metric-a", "gap": "no data", "runs": 1}],
        )
        facts = make_facts(deferred=["metric-a"], blind_spots=[{"key": "metric-a", "gap": "no data"}])
        _, next_state, _, _ = self.apply(previous_state, facts)
        self.assertEqual(
            (next_state["items"]["metric-a"], next_state["blind_spots"]),
            (make_item(), [{"key": "metric-a", "gap": "no data", "runs": 2}]),
        )

    def test_muted_deferred_key_is_left_out_of_still_open_and_not_counted_as_muted(self):
        facts = make_facts(deferred=["metric-a"], mutes=[{"key": "metric-a", "until": "2026-06-10"}])
        _, _, summary, _ = self.apply(make_state(items={"metric-a": make_item()}), facts)
        self.assertEqual((summary["still_open"]["Medium"], summary["muted_changes"]), ([], 0))

    def test_observation_for_a_deferred_key_is_rejected_with_its_key_path(self):
        facts = make_facts({"metric-a": obs()}, deferred=["metric-a"])
        code, err = self.run_apply(make_state(), facts)
        self.assert_rejected_without_output(code, err, "observations.metric-a")

    def test_deferred_that_is_not_a_list_is_rejected(self):
        code, err = self.run_apply(make_state(), make_facts(deferred="metric-a"))
        self.assert_rejected_without_output(code, err, "deferred")

    def test_deferred_key_that_is_not_text_is_rejected_with_its_index(self):
        code, err = self.run_apply(make_state(), make_facts(deferred=[7]))
        self.assert_rejected_without_output(code, err, "deferred[0]")


class OverrideTest(ApplyCase):
    def monitor_obs(self, state_name="Alert", title="API monitor", **extra):
        return obs(over=False, value=None, source="monitors", title=title, last_value=state_name, **extra)

    def override_facts(self, overrides, **mutes):
        observations = {"monitor-1": self.monitor_obs("Alert", "First"), "monitor-2": self.monitor_obs("Warn", "Second")}
        return make_facts(observations, overrides=overrides, **mutes)

    def test_summary_lists_each_override_with_the_title_and_the_state_of_its_observation(self):
        self.apply(make_state(), self.override_facts(["monitor-2", "monitor-1"]))

        self.assertEqual(
            self.read("summary.json")["overrides"],
            [{"key": "monitor-1", "title": "First", "state": "Alert"}, {"key": "monitor-2", "title": "Second", "state": "Warn"}],
        )

    def test_summary_lists_a_repeated_override_once(self):
        self.apply(make_state(), self.override_facts(["monitor-1", "monitor-1"]))

        self.assertEqual([entry["key"] for entry in self.read("summary.json")["overrides"]], ["monitor-1"])

    def test_summary_without_overrides_in_the_facts_lists_none(self):
        self.apply(make_state(), make_facts())

        self.assertEqual(self.read("summary.json")["overrides"], [])

    def test_record_copies_the_overrides_of_the_facts(self):
        self.apply(make_state(), self.override_facts(["monitor-1", "monitor-2"]))

        self.assertEqual(self.read("record.json")["overrides"], ["monitor-1", "monitor-2"])

    def test_record_without_overrides_in_the_facts_has_no_overrides_field(self):
        self.apply(make_state(), make_facts())

        self.assertNotIn("overrides", self.read("record.json"))

    def test_muted_override_is_left_out_of_the_summary_and_kept_in_the_record(self):
        facts = self.override_facts(["monitor-1", "monitor-2"], mutes=[{"key": "monitor-1", "until": "2026-06-10"}])

        self.apply(make_state(), facts)

        self.assertEqual([entry["key"] for entry in self.read("summary.json")["overrides"]], ["monitor-2"])
        self.assertEqual(self.read("record.json")["overrides"], ["monitor-1", "monitor-2"])

    def test_overrides_alone_do_not_ask_for_a_post(self):
        self.apply(make_state(), self.override_facts(["monitor-1"]))

        self.assertIs(self.read("summary.json")["post"], False)

    def test_override_of_a_key_that_is_not_observed_is_rejected_naming_its_path(self):
        code, err = self.run_apply(make_state(), self.override_facts(["monitor-9"]))

        self.assert_rejected_without_output(code, err, "overrides[0]")

    def test_overrides_that_are_not_a_list_of_keys_are_rejected_naming_the_path(self):
        code, err = self.run_apply(make_state(), self.override_facts("monitor-1"))

        self.assert_rejected_without_output(code, err, "overrides")

    def test_override_whose_observed_state_is_not_a_label_is_rejected_naming_its_path(self):
        facts = make_facts({"monitor-1": self.monitor_obs("Alert\nOK")}, overrides=["monitor-1"])

        code, err = self.run_apply(make_state(), facts)

        self.assert_rejected_without_output(code, err, "observations.monitor-1.last_value")


class StoredMutesTest(CliCase):
    def validate(self, mutes):
        previous_state = make_state()
        previous_state["run"]["mutes"] = mutes
        return run_cli("validate", "--state", self.write("state.json", previous_state))

    def test_state_without_stored_mutes_passes_validation(self):
        code, _, _ = run_cli("validate", "--state", self.write("state.json", make_state()))
        self.assertEqual(code, 0)

    def test_state_with_stored_mutes_passes_validation(self):
        code, _, _ = self.validate([{"key": "metric-a", "until": "2026-06-10"}])
        self.assertEqual(code, 0)

    def test_stored_mute_with_invalid_date_is_rejected_with_its_key_path(self):
        code, _, err = self.validate([{"key": "metric-a", "until": "next week"}])
        self.assertEqual((code, "run.mutes[0].until" in err), (3, True))

    def test_stored_mute_without_key_is_rejected_with_its_key_path(self):
        code, _, err = self.validate([{"until": "2026-06-10"}])
        self.assertEqual((code, "missing key run.mutes[0].key" in err), (3, True))


class RunContextTest(ApplyCase):
    def test_record_copies_the_run_context(self):
        self.apply(make_state(), make_facts(run_context=make_run_context()))
        record = self.read("record.json")
        fields = ("place", "runtime", "config", "config_dirty", "collected")
        self.assertEqual({name: record[name] for name in fields}, make_run_context())

    def test_record_copies_the_read_counts_of_a_source(self):
        run_context = make_run_context()
        run_context["collected"]["monitors"]["reads"] = {"fetched": 1, "reused": 4}
        self.apply(make_state(), make_facts(run_context=run_context))
        self.assertEqual(self.read("record.json")["collected"]["monitors"]["reads"], {"fetched": 1, "reused": 4})

    def test_next_state_never_stores_the_read_counts(self):
        self.apply(make_state(), make_facts())
        without_context = self.read_bytes("next.json")
        run_context = make_run_context()
        run_context["collected"]["monitors"]["reads"] = {"fetched": 1, "reused": 4}
        self.apply(make_state(), make_facts(run_context=run_context))
        self.assertEqual(self.read_bytes("next.json"), without_context)

    def test_negative_read_counts_are_rejected_with_their_key_path(self):
        run_context = make_run_context()
        run_context["collected"]["monitors"]["reads"] = {"fetched": -1, "reused": 0}
        code, err = self.run_apply(make_state(), make_facts(run_context=run_context))
        self.assert_rejected_without_output(code, err, "run_context.collected.monitors.reads.fetched")

    def test_read_counts_without_reused_are_rejected(self):
        run_context = make_run_context()
        run_context["collected"]["monitors"]["reads"] = {"fetched": 1}
        code, err = self.run_apply(make_state(), make_facts(run_context=run_context))
        self.assert_rejected_without_output(code, err, "missing key run_context.collected.monitors.reads.reused")

    def test_record_without_run_context_has_no_run_context_fields(self):
        self.apply(make_state(), make_facts())
        record = self.read("record.json")
        self.assertEqual(set(record) & {"place", "runtime", "config", "config_dirty", "collected"}, set())

    def test_explicit_run_record_copies_the_run_context(self):
        self.apply(make_state(), make_facts(run_context=make_run_context()), make_window(explicit=True))
        self.assertEqual(self.read("record.json")["place"], "local")

    def test_next_state_never_stores_the_run_context(self):
        self.apply(make_state(), make_facts())
        without_context = self.read_bytes("next.json")
        self.apply(make_state(), make_facts(run_context=make_run_context()))
        self.assertEqual(self.read_bytes("next.json"), without_context)

    def test_run_context_with_unknown_commits_is_accepted(self):
        code, _ = self.run_apply(make_state(), make_facts(run_context=make_run_context(runtime=None, config=None, config_dirty=None)))
        self.assertEqual(code, 0)

    def test_run_context_with_an_unknown_place_is_rejected(self):
        code, err = self.run_apply(make_state(), make_facts(run_context=make_run_context(place="laptop")))
        self.assert_rejected_without_output(code, err, "run_context.place")

    def test_run_context_with_text_config_dirty_is_rejected(self):
        code, err = self.run_apply(make_state(), make_facts(run_context=make_run_context(config_dirty="yes")))
        self.assert_rejected_without_output(code, err, "run_context.config_dirty")

    def test_run_context_missing_a_key_is_rejected_with_its_key_path(self):
        run_context = make_run_context()
        del run_context["runtime"]
        code, err = self.run_apply(make_state(), make_facts(run_context=run_context))
        self.assert_rejected_without_output(code, err, "missing key run_context.runtime")

    def test_collected_source_with_an_unknown_transport_is_rejected(self):
        run_context = make_run_context()
        run_context["collected"]["monitors"]["transport"] = "ftp"
        code, err = self.run_apply(make_state(), make_facts(run_context=run_context))
        self.assert_rejected_without_output(code, err, "run_context.collected.monitors.transport")

    def test_collected_source_without_reason_is_rejected_with_its_key_path(self):
        run_context = make_run_context()
        del run_context["collected"]["sources_page"]["reason"]
        code, err = self.run_apply(make_state(), make_facts(run_context=run_context))
        self.assert_rejected_without_output(code, err, "missing key run_context.collected.sources_page.reason")


class BlindSpotTest(ApplyCase):
    def spots(self, previous, seen, retried=()):
        facts = make_facts(blind_spots=seen, blind_spots_retried=list(retried))
        _, next_state, summary, _ = self.apply(make_state(blind_spots=previous), facts)
        return next_state["blind_spots"], summary

    def test_summary_lists_the_blind_spots_with_their_gap_and_runs(self):
        previous = [{"key": "metric-a", "gap": "no data", "runs": 2}]
        _, summary = self.spots(previous, [{"key": "metric-a", "gap": "no data"}])
        self.assertEqual(summary["blind_spots"], [{"key": "metric-a", "gap": "no data", "runs": 3}])

    def test_summary_lists_only_the_blind_spots_kept_by_the_cap(self):
        _, summary = self.spots([], [{"key": f"metric-{index}", "gap": "no data"} for index in range(9)])
        self.assertEqual((len(summary["blind_spots"]), summary["blind_spots_dropped"]), (8, 1))

    def test_new_gap_starts_at_one_run(self):
        spots, _ = self.spots([], [{"key": "metric-a", "gap": "no data"}])
        self.assertEqual(spots, [{"key": "metric-a", "gap": "no data", "runs": 1}])

    def test_gap_seen_again_keeps_counting_runs(self):
        spots, _ = self.spots([{"key": "metric-a", "gap": "no data", "runs": 2}], [{"key": "metric-a", "gap": "timeout"}])
        self.assertEqual(spots, [{"key": "metric-a", "gap": "timeout", "runs": 3}])

    def test_unknown_gap_absent_from_the_facts_is_dropped(self):
        spots, _ = self.spots([{"key": "metric-a", "gap": "no data", "runs": 2}], [])
        self.assertEqual(spots, [])

    def test_known_gap_not_retried_is_carried_unchanged(self):
        known = {"key": "metric-a", "gap": "no data", "runs": 3}
        spots, _ = self.spots([known], [])
        self.assertEqual(spots, [known])

    def test_known_gap_retried_and_read_is_removed(self):
        spots, _ = self.spots([{"key": "metric-a", "gap": "no data", "runs": 3}], [], retried=["metric-a"])
        self.assertEqual(spots, [])

    def test_known_gap_retried_and_still_failing_keeps_counting(self):
        spots, _ = self.spots(
            [{"key": "metric-a", "gap": "no data", "runs": 3}], [{"key": "metric-a", "gap": "no data"}], retried=["metric-a"]
        )
        self.assertEqual(spots, [{"key": "metric-a", "gap": "no data", "runs": 4}])

    def test_blind_spots_are_capped_at_eight_known_first_and_the_drop_is_counted(self):
        previous = [{"key": f"known-{index}", "gap": "no data", "runs": 3} for index in range(3)]
        seen = [{"key": f"metric-{index}", "gap": "no data"} for index in range(7)]
        spots, summary = self.spots(previous, seen)
        self.assertEqual([spot["key"] for spot in spots[:3]], ["known-0", "known-1", "known-2"])
        self.assertEqual((len(spots), summary["blind_spots_dropped"]), (8, 2))

    def test_exactly_eight_blind_spots_drop_nothing(self):
        spots, summary = self.spots([], [{"key": f"metric-{index}", "gap": "no data"} for index in range(8)])
        self.assertEqual((len(spots), summary["blind_spots_dropped"]), (8, 0))

    def test_nine_blind_spots_keep_the_known_gap_and_drop_the_last_one(self):
        previous = [{"key": "known-0", "gap": "no data", "runs": 3}]
        spots, summary = self.spots(previous, [{"key": f"metric-{index}", "gap": "no data"} for index in range(8)])
        self.assertEqual([spot["key"] for spot in spots], ["known-0"] + [f"metric-{index}" for index in range(7)])
        self.assertEqual(summary["blind_spots_dropped"], 1)

    def test_gap_seen_again_reaching_three_runs_becomes_known_and_sorts_first(self):
        previous = [{"key": "metric-a", "gap": "no data", "runs": 2}]
        spots, _ = self.spots(previous, [{"key": "metric-b", "gap": "no data"}, {"key": "metric-a", "gap": "no data"}])
        self.assertEqual([(spot["key"], spot["runs"]) for spot in spots], [("metric-a", 3), ("metric-b", 1)])

    def test_duplicate_gap_keys_in_the_facts_count_once(self):
        spots, _ = self.spots([], [{"key": "metric-a", "gap": "no data"}, {"key": "metric-a", "gap": "timeout"}])
        self.assertEqual(spots, [{"key": "metric-a", "gap": "no data", "runs": 1}])

    def test_blind_spot_without_key_is_rejected(self):
        code, err = self.run_apply(make_state(), make_facts(blind_spots=[{"gap": "no data"}]))
        self.assert_rejected_without_output(code, err, "missing key blind_spots[0].key")


class ValidateTest(CliCase):
    def test_valid_state_passes(self):
        code, _, _ = run_cli("validate", "--state", self.write("state.json", make_state(items={"metric-a": make_item()})))
        self.assertEqual(code, 0)

    def test_valid_facts_pass(self):
        code, _, _ = run_cli("validate", "--facts", self.write("facts.json", make_facts({"metric-a": obs()})))
        self.assertEqual(code, 0)

    def test_state_missing_a_nested_key_prints_its_path(self):
        previous_state = make_state()
        del previous_state["cursors"]["observability"]["events_ts_ms"]
        code, _, err = run_cli("validate", "--state", self.write("state.json", previous_state))
        self.assertEqual(code, 3)
        self.assertIn("missing key cursors.observability.events_ts_ms", err)

    def test_facts_observing_a_deferred_key_fail_validation(self):
        facts = make_facts({"metric-a": obs()}, deferred=["metric-a"])
        code, _, err = run_cli("validate", "--facts", self.write("facts.json", facts))
        self.assertEqual((code, "observations.metric-a" in err), (3, True))

    def test_facts_missing_a_key_prints_its_path(self):
        facts = make_facts()
        del facts["mutes"]
        code, _, err = run_cli("validate", "--facts", self.write("facts.json", facts))
        self.assertEqual(code, 3)
        self.assertIn("missing key mutes", err)

    def test_document_that_is_not_an_object_is_rejected(self):
        code, _, _ = run_cli("validate", "--state", self.write("state.json", [1, 2]))
        self.assertEqual(code, 3)

    def test_state_and_facts_together_are_a_usage_error(self):
        path = self.write("state.json", make_state())
        code, _, _ = run_cli("validate", "--state", path, "--facts", path)
        self.assertEqual(code, 2)

    def test_no_document_is_a_usage_error(self):
        code, _, _ = run_cli("validate")
        self.assertEqual(code, 2)


class RecordTest(ApplyCase):
    def lifecycle_inputs(self):
        previous_state = make_state(items={
            "metric-a": make_item(title="Metric A", runs=1),
            "metric-b": make_item(title="Metric B"),
            "metric-e": make_item(title="Metric E"),
        })
        facts = make_facts(
            {
                "metric-a": obs(over=False, title="Metric A"),
                "metric-b": obs(severity="High", title="Metric B"),
                "metric-c": obs(title="Metric C"),
                "metric-e": obs(title="Metric E"),
            },
            monitors=False,
            blind_spots=[{"key": "metric-d", "gap": "no data"}],
        )
        return previous_state, facts

    def test_record_of_a_normal_run(self):
        previous_state, facts = self.lifecycle_inputs()
        self.apply(previous_state, facts)
        self.assertEqual(self.read("record.json"), {
            "schema": 1,
            "digest": "Prod watch",
            "run_at": NOW,
            "window": {"from_ts": ts(PREVIOUS), "to_ts": ts(NOW), "explicit": False, "cut": None},
            "counts": {"new": 1, "escalated": 1, "resolved": 1, "still_open": 1, "tracked": 3, "muted_changes": 0},
            "new": ["metric-c"],
            "escalated": ["metric-b"],
            "resolved": ["metric-a"],
            "muted": [],
            "blind_spots": [{"key": "metric-d", "runs": 1}],
            "blind_spots_dropped": 0,
            "sources_read": ["metrics"],
        })

    def test_record_of_an_explicit_run_names_its_explicit_window(self):
        previous_state, facts = self.lifecycle_inputs()
        self.apply(previous_state, facts, make_window(start="2026-05-31T08:00:00Z", explicit=True))
        self.assertEqual(
            self.read("record.json")["window"],
            {"from_ts": ts("2026-05-31T08:00:00Z"), "to_ts": ts(NOW), "explicit": True, "cut": None},
        )

    def test_record_names_the_cut_span(self):
        cut = {"from_ts": ts("2026-05-28T10:00:00Z"), "to_ts": ts("2026-05-29T10:00:00Z")}
        self.apply(make_state(), make_facts(), make_window(cut=cut))
        self.assertEqual(self.read("record.json")["window"]["cut"], cut)

    def test_record_keeps_a_muted_new_key_and_counts_it(self):
        facts = make_facts({"metric-a": obs()}, mutes=[{"key": "metric-a", "until": "2026-06-10"}])
        self.apply(make_state(), facts)
        record = self.read("record.json")
        self.assertEqual(
            (record["new"], record["muted"], record["counts"]["new"], record["counts"]["muted_changes"]),
            (["metric-a"], ["metric-a"], 1, 1),
        )

    def test_muted_escalation_is_in_the_record_but_not_in_the_summary(self):
        facts = make_facts({"metric-a": obs(severity="High")}, mutes=[{"key": "metric-a", "until": "2026-06-10"}])
        _, _, summary, _ = self.apply(make_state(items={"metric-a": make_item()}), facts)
        record = self.read("record.json")
        self.assertEqual((record["escalated"], record["muted"], summary["escalated"]), (["metric-a"], ["metric-a"], []))

    def test_record_keeps_a_muted_resolution(self):
        facts = make_facts({"metric-a": obs(over=False)}, mutes=[{"key": "metric-a", "until": "2026-06-10"}])
        self.apply(make_state(items={"metric-a": make_item(runs=1)}), facts)
        record = self.read("record.json")
        self.assertEqual((record["resolved"], record["counts"]["resolved"]), (["metric-a"], 1))

    def test_record_marks_a_muted_resolution_as_muted(self):
        facts = make_facts({"metric-a": obs(over=False)}, mutes=[{"key": "metric-a", "until": "2026-06-10"}])
        self.apply(make_state(items={"metric-a": make_item(runs=1)}), facts)
        self.assertEqual(self.read("record.json")["muted"], ["metric-a"])

    def test_record_counts_a_muted_item_without_change_as_still_open_and_not_muted(self):
        facts = make_facts({"metric-a": obs()}, mutes=[{"key": "metric-a", "until": "2026-06-10"}])
        self.apply(make_state(items={"metric-a": make_item()}), facts)
        record = self.read("record.json")
        self.assertEqual((record["counts"]["still_open"], record["muted"]), (1, []))

    def test_record_counts_the_blind_spots_the_cap_dropped(self):
        facts = make_facts(blind_spots=[{"key": f"metric-{index}", "gap": "no data"} for index in range(9)])
        self.apply(make_state(), facts)
        record = self.read("record.json")
        self.assertEqual((len(record["blind_spots"]), record["blind_spots_dropped"]), (8, 1))

    def test_record_lists_every_source_read(self):
        self.apply(make_state(), make_facts())
        self.assertEqual(self.read("record.json")["sources_read"], ["monitors", "metrics"])


class ExplicitWindowTest(ApplyCase):
    def explicit_window(self):
        return make_window(start="2026-05-31T08:00:00Z", explicit=True)

    def test_explicit_window_leaves_the_next_state_byte_identical_to_the_previous(self):
        previous_state = make_state(items={"metric-a": make_item(title="Débit", runs=1)})
        facts = make_facts({"metric-a": obs(over=False, title="Débit"), "metric-b": obs(title="Metric B")})
        self.apply(previous_state, facts, self.explicit_window())
        self.assertEqual(self.read_bytes("next.json"), self.read_bytes("state.json"))

    def test_explicit_window_keeps_the_stored_cursors(self):
        self.apply(make_state(), make_facts(), self.explicit_window())
        self.assertEqual(self.read("next.json")["cursors"], make_state()["cursors"])

    def test_explicit_window_still_writes_the_change_summary(self):
        _, _, summary, _ = self.apply(make_state(), make_facts({"metric-a": obs()}), self.explicit_window())
        self.assertEqual([entry["key"] for entry in summary["new"]], ["metric-a"])

    def test_explicit_window_writing_onto_the_state_file_keeps_its_bytes(self):
        state_path = self.write("state.json", make_state())
        before = self.read_bytes("state.json")
        code, _, _ = run_cli(
            "apply", "--state", state_path, "--facts", self.write("facts.json", make_facts()),
            "--window", self.write("window.json", self.explicit_window()), "--tz", TZ, "--out", state_path,
            "--summary", self.path("summary.json"), "--record", self.path("record.json"),
        )
        self.assertEqual((code, self.read_bytes("state.json")), (0, before))

    def test_explicit_window_with_rejected_facts_writes_nothing(self):
        code, err = self.run_apply(make_state(items={"metric-a": make_item()}), make_facts(), self.explicit_window())
        self.assert_rejected_without_output(code, err, "observations.metric-a")

    def test_explicit_window_accepts_a_cursor_older_than_the_stored_cursor_and_keeps_the_state(self):
        facts = make_facts()
        facts["cursors"]["events_ts_ms"] = 999
        code, _ = self.run_apply(make_state(), facts, self.explicit_window())
        self.assertEqual((code, self.read_bytes("next.json")), (0, self.read_bytes("state.json")))

    def test_report_only_run_with_an_analysed_new_item_leaves_the_state_byte_identical(self):
        facts = make_facts({"metric-a": obs(rank=1, **make_analysis())})
        self.apply(make_state(), facts, make_window(explicit=True))
        self.assertEqual(self.read_bytes("next.json"), self.read_bytes("state.json"))

    def test_report_only_summary_carries_the_analysis_of_a_new_item(self):
        facts = make_facts({"metric-a": obs(rank=1, **make_analysis())})
        _, _, summary, _ = self.apply(make_state(), facts, make_window(explicit=True))
        entry = summary["new"][0]
        self.assertEqual(analysis_of(entry, make_analysis()), make_analysis())


class InitTest(CliCase):
    def init(self, *argv):
        return run_cli("init", "--digest", "Prod watch", "--out", self.path("state.json"), *argv)

    def test_initial_state_is_the_empty_baseline(self):
        self.init()
        self.assertEqual(self.read("state.json"), {
            "schema": 2,
            "digest": "Prod watch",
            "run": {
                "at": None,
                "previous_at": None,
                "sources_last_edited": None,
                "window": None,
                "daily_metrics_on": None,
                "models": {},
                "posted": False,
                "mutes": [],
            },
            "cursors": {"observability": {"events_ts_ms": None, "monitors": {}, "metrics": {}}},
            "items": {},
            "resolved_queries": {},
            "blind_spots": [],
        })

    def test_initial_state_passes_validation(self):
        self.init()
        self.assertEqual(run_cli("validate", "--state", self.path("state.json"))[0], 0)

    def test_initial_state_gives_a_baseline_window(self):
        self.init()
        run_cli("window", "--state", self.path("state.json"), "--now", NOW, "--tz", TZ, "--out", self.path("window.json"))
        self.assertEqual(self.read("window.json")["from_ts"], ts(NOW) - 3 * 3600)

    def test_initial_state_is_canonical_json(self):
        self.init()
        self.assert_canonical("state.json")

    def test_unwritable_out_exits_2_naming_the_path(self):
        out = os.path.join(self.dir, "absent", "state.json")
        code, _, err = run_cli("init", "--digest", "Prod watch", "--out", out)
        self.assertEqual((code, out in err), (2, True))

    def test_failed_write_leaves_no_temp_file(self):
        os.makedirs(self.path("state.json"))
        self.init()
        self.assertEqual(sorted(os.listdir(self.dir)), ["state.json"])


class CanonicalOutputTest(ApplyCase):
    def run_once(self):
        previous_state = make_state(items={"metric-a": make_item(title="Débit")})
        self.apply(previous_state, make_facts({"metric-a": obs(title="Débit", severity="High")}))

    def test_next_state_is_canonical_json(self):
        self.run_once()
        self.assert_canonical("next.json")

    def test_summary_is_canonical_json(self):
        self.run_once()
        self.assert_canonical("summary.json")

    def test_record_is_canonical_json(self):
        self.run_once()
        self.assert_canonical("record.json")

    def test_next_state_keeps_non_ascii_text(self):
        self.run_once()
        self.assertIn("Débit".encode("utf-8"), self.read_bytes("next.json"))


class TextRulesTest(unittest.TestCase):
    def test_blanks_control_format_and_separator_characters(self):
        text = "a\x00b\x1fc\x85d\u200be\u2028f\u2029g\u202eh"

        self.assertEqual(state.blank_controls(text), "a b c d e f g h")

    def test_blanks_lone_surrogates(self):
        self.assertEqual(state.blank_controls("a\ud800b\udfffc"), "a b c")

    def test_clean_text_blanks_lone_surrogates(self):
        self.assertEqual(state.clean_text("a\ud800b", 300), "a b")

    def test_keeps_a_valid_surrogate_pair_written_as_one_character(self):
        self.assertEqual(state.blank_controls("a\U0001f680b"), "a\U0001f680b")

    def test_label_rejects_a_lone_surrogate(self):
        self.assertEqual([text for text in ("\ud800", "\udbff", "\udc00", "\udfff") if state.is_label("a" + text)], [])

    def test_keeps_ordinary_text_when_blanking(self):
        self.assertEqual(state.blank_controls("Caf\u00e9 \U0001f680 ok"), "Caf\u00e9 \U0001f680 ok")

    def test_clean_text_replaces_mention_and_markup_characters(self):
        self.assertEqual(state.clean_text("@team <b>x</b>", 300), " team  b x /b ")

    def test_clean_text_replaces_the_fullwidth_forms_of_mention_characters(self):
        self.assertEqual(state.clean_text("\uff20team \uff1cb\uff1e", 300), " team  b ")

    def test_clean_text_blanks_separators_and_bidirectional_overrides(self):
        self.assertEqual(state.clean_text("a\u2028b\u202ec\nd", 300), "a b c d")

    def test_clean_text_normalises_compatibility_characters(self):
        self.assertEqual(state.clean_text("\ufb01x \u2460", 300), "fix 1")

    def test_clean_text_cuts_to_the_cap(self):
        self.assertEqual(state.clean_text("x" * 400, 300), "x" * 300)

    def test_clean_text_cuts_after_normalising(self):
        self.assertEqual(state.clean_text("\ufb01" * 10, 5), "fifif")

    def test_label_accepts_300_characters(self):
        self.assertTrue(state.is_label("x" * 300))

    def test_label_rejects_301_characters(self):
        self.assertFalse(state.is_label("x" * 301))

    def test_label_rejects_each_barred_category(self):
        barred = ["\x00", "\x1f", "\x7f", "\x9f", "\u200b", "\u2028", "\u2029", "\u202e", "\ufeff"]

        self.assertEqual([text for text in barred if state.is_label("a" + text + "b")], [])

    def test_tracked_monitor_key_is_the_prefix_and_ascii_digits(self):
        keys = ["monitor-1", "monitor-1000077", "monitor-", "monitor-x", "monitor-12a", "monitor-\u0661\u0662", "xmonitor-1", "monitor-1\n"]

        self.assertEqual([key for key in keys if state.is_tracked_monitor(key)], ["monitor-1", "monitor-1000077"])


class ParserTest(unittest.TestCase):
    def options(self):
        parser = state.build_parser()
        commands = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
        return {
            name: {flag for action in sub._actions for flag in action.option_strings if flag not in ("-h", "--help")}
            for name, sub in commands.choices.items()
        }

    def test_parser_exposes_the_documented_commands_and_flags(self):
        self.assertEqual(self.options(), {
            "window": {"--state", "--now", "--tz", "--since", "--report-only", "--out"},
            "apply": {"--state", "--facts", "--window", "--tz", "--out", "--summary", "--record"},
            "init": {"--digest", "--out"},
            "validate": {"--state", "--facts"},
        })


class ScriptTest(CliCase):
    def test_script_exits_3_when_now_is_before_the_previous_run(self):
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, "state.py"), "window", "--state", self.write("state.json", make_state()),
             "--now", "2026-06-01T09:00:00Z", "--tz", TZ, "--out", self.path("window.json")],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 3)


class LabelTest(CliCase):
    def validate_state(self, **item_fields):
        return run_cli("validate", "--state", self.write("state.json", make_state(items={"metric-a": make_item(**item_fields)})))

    def validate_facts(self, **fields):
        return run_cli("validate", "--facts", self.write("facts.json", make_facts({"metric-a": obs(**fields)})))

    def test_accepts_an_item_title_of_300_characters(self):
        self.assertEqual(self.validate_state(title="t" * 300)[0], 0)

    def test_rejects_an_item_title_over_300_characters_naming_its_path(self):
        code, _, err = self.validate_state(title="t" * 301)
        self.assertEqual((code, "items.metric-a.title" in err), (3, True))

    def test_rejects_an_item_title_with_a_line_break_naming_its_path(self):
        code, _, err = self.validate_state(title="Metric\nA")
        self.assertEqual((code, "items.metric-a.title" in err), (3, True))

    def test_rejects_an_item_title_with_a_line_separator_naming_its_path(self):
        code, _, err = self.validate_state(title="Metric\u2028A")
        self.assertEqual((code, "items.metric-a.title" in err), (3, True))

    def test_rejects_an_item_title_with_a_paragraph_separator_naming_its_path(self):
        code, _, err = self.validate_state(title="Metric\u2029A")
        self.assertEqual((code, "items.metric-a.title" in err), (3, True))

    def test_rejects_an_item_title_with_a_bidirectional_override_naming_its_path(self):
        code, _, err = self.validate_state(title="Metric\u202eA")
        self.assertEqual((code, "items.metric-a.title" in err), (3, True))

    def test_rejects_an_item_title_with_a_zero_width_character_naming_its_path(self):
        code, _, err = self.validate_state(title="Metric\u200bA")
        self.assertEqual((code, "items.metric-a.title" in err), (3, True))

    def test_rejects_a_c1_control_character_in_an_item_title_naming_its_path(self):
        code, _, err = self.validate_state(title="Metric\x85A")
        self.assertEqual((code, "items.metric-a.title" in err), (3, True))

    def test_accepts_an_item_title_with_accents_and_emoji(self):
        self.assertEqual(self.validate_state(title="M\u00e9trique \U0001f680")[0], 0)

    def test_rejects_an_item_link_with_a_control_character_naming_its_path(self):
        code, _, err = self.validate_state(link="https://example.test/\x1b[31m")
        self.assertEqual((code, "items.metric-a.link" in err), (3, True))

    def test_rejects_an_item_link_that_is_not_text_naming_its_path(self):
        code, _, err = self.validate_state(link=None)
        self.assertEqual((code, "items.metric-a.link" in err), (3, True))

    def test_rejects_an_observation_title_with_a_control_character_naming_its_path(self):
        code, _, err = self.validate_facts(title="Metric\tA")
        self.assertEqual((code, "observations.metric-a.title" in err), (3, True))

    def test_rejects_an_observation_title_with_a_lone_surrogate_naming_its_path(self):
        code, _, err = self.validate_facts(title="Metric\ud800A")
        self.assertEqual((code, "observations.metric-a.title" in err), (3, True))

    def test_rejects_an_observation_link_over_300_characters_naming_its_path(self):
        code, _, err = self.validate_facts(link="https://example.test/" + "x" * 300)
        self.assertEqual((code, "observations.metric-a.link" in err), (3, True))

    def test_rejects_a_stored_blind_spot_gap_with_a_control_character_naming_its_path(self):
        state = make_state(blind_spots=[{"key": "metric-a", "gap": "no\x1b[31m data", "runs": 1}])
        code, _, err = run_cli("validate", "--state", self.write("state.json", state))
        self.assertEqual((code, "blind_spots[0].gap" in err), (3, True))

    def test_rejects_a_blind_spot_gap_of_the_facts_that_is_not_text_naming_its_path(self):
        facts = make_facts(blind_spots=[{"key": "metric-a", "gap": 5}])
        code, _, err = run_cli("validate", "--facts", self.write("facts.json", facts))
        self.assertEqual((code, "blind_spots[0].gap" in err), (3, True))


class AnalysisFieldTest(CliCase):
    def validate_item(self, **fields):
        item = make_item(**dict(make_analysis(), **fields))
        return run_cli("validate", "--state", self.write("state.json", make_state(items={"metric-a": item})))

    def validate_observation(self, **fields):
        observation = obs(**dict(make_analysis(), **fields))
        return run_cli("validate", "--facts", self.write("facts.json", make_facts({"metric-a": observation})))

    def test_accepts_an_item_with_its_analysis(self):
        self.assertEqual(self.validate_item()[0], 0)

    def test_accepts_an_observation_with_its_analysis(self):
        self.assertEqual(self.validate_observation()[0], 0)

    def test_accepts_a_single_mitigation_lead(self):
        self.assertEqual(self.validate_item(mitigation=["roll back the consumer"])[0], 0)

    def test_rejects_an_item_risk_over_300_characters_naming_its_path(self):
        code, _, err = self.validate_item(risk="r" * 301)
        self.assertEqual((code, "items.metric-a.risk" in err), (3, True))

    def test_rejects_an_observation_action_with_a_line_break_naming_its_path(self):
        code, _, err = self.validate_observation(action="restart\nthe consumer")
        self.assertEqual((code, "observations.metric-a.action" in err), (3, True))

    def test_rejects_a_null_item_action_naming_its_path(self):
        code, _, err = self.validate_item(action=None)
        self.assertEqual((code, "items.metric-a.action" in err), (3, True))

    def test_rejects_a_text_reason_naming_its_path(self):
        code, _, err = self.validate_item(reason="a deploy changed the consumer")
        self.assertEqual((code, "items.metric-a.reason" in err), (3, True))

    def test_rejects_a_reason_tag_other_than_measured_or_inferred_naming_its_path(self):
        code, _, err = self.validate_observation(reason=[{"tag": "guessed", "claim": "a deploy changed the consumer"}])
        self.assertEqual((code, "observations.metric-a.reason[0].tag" in err), (3, True))

    def test_rejects_a_reason_claim_with_a_control_character_naming_its_path(self):
        code, _, err = self.validate_item(reason=[{"tag": "inferred", "claim": "a deploy\x1b[31m"}])
        self.assertEqual((code, "items.metric-a.reason[0].claim" in err), (3, True))

    def test_rejects_a_reason_entry_without_claim_naming_its_path(self):
        code, _, err = self.validate_observation(reason=[{"tag": "measured"}])
        self.assertEqual((code, "missing key observations.metric-a.reason[0].claim" in err), (3, True))

    def test_rejects_an_empty_mitigation_naming_its_path(self):
        code, _, err = self.validate_item(mitigation=[])
        self.assertEqual((code, "items.metric-a.mitigation" in err), (3, True))

    def test_rejects_four_mitigation_leads_naming_its_path(self):
        code, _, err = self.validate_observation(mitigation=["roll back", "scale", "pause", "drain"])
        self.assertEqual((code, "observations.metric-a.mitigation" in err), (3, True))

    def test_rejects_a_mitigation_lead_over_300_characters_naming_its_path(self):
        code, _, err = self.validate_item(mitigation=["roll back the consumer", "m" * 301])
        self.assertEqual((code, "items.metric-a.mitigation[1]" in err), (3, True))


class MessagePartsTest(unittest.TestCase):
    def test_keeps_a_message_that_fits_whole(self):
        self.assertEqual(state.message_parts("aaaa\n\nbb\n", 10), ["aaaa\n\nbb\n"])

    def test_cuts_at_the_blank_line_before_the_block_that_overflows(self):
        self.assertEqual(state.message_parts("aaaa\n\nbbbb\n\ncc\n", 10), ["aaaa\n\nbbbb\n", "cc\n"])

    def test_cuts_a_block_over_the_cap_at_its_lines(self):
        self.assertEqual(state.message_parts("l1-xxxx\nl2-xxxx\nl3-xxxx\n", 15), ["l1-xxxx\nl2-xxxx\n", "l3-xxxx\n"])

    def test_cuts_a_line_over_the_cap_at_the_cap(self):
        self.assertEqual(state.message_parts("x" * 25 + "\n", 10), ["x" * 10 + "\n", "x" * 10 + "\n", "x" * 5 + "\n"])

    def test_keeps_every_part_within_the_cap(self):
        text = "\n\n".join(f"**Item {index}**\n" + "detail " * (index % 9 + 1) for index in range(60)) + "\n"

        self.assertEqual([part for part in state.message_parts(text, 100) if len(part.rstrip("\n")) > 100], [])

    def test_drops_no_text(self):
        text = "\n\n".join(f"**Item {index}**\n" + "detail " * (index % 9 + 1) for index in range(60)) + "\n"

        self.assertEqual("".join("".join(state.message_parts(text, 100)).split()), "".join(text.split()))

    def test_names_the_next_parts_after_the_first_file(self):
        self.assertEqual([path for path, _ in state.message_files("/run/digest.md", "a\n\nb\n", 1)], ["/run/digest.md", "/run/digest.2.md"])


if __name__ == "__main__":
    unittest.main()
