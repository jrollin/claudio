import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import evaluate
import state
from evaluate_support import (
    COMMIT, EvaluateCase, FROM_TS, KEY, MON, NEW_EVENTS_MS, ROUTINE, STORED_EVENTS_MS, STORED_MUTES, TO_TS, alerts,
    analysis_item, analysis_of, collection, collections, cpu_verdict, failed, gauges, git_answers, judgment_of,
    make_config, make_item, make_state, make_window, metric, metric_entry, metrics_collection, missing, monitor,
    monitor_entry, monitor_verdict, notes, ok, skipped, source, ts, unread_alerts, unread_gauges, write_json, write_text,
)

FEATURES_FLAGS = [
    "--base-out", "--collections", "--config", "--out", "--place", "--routine", "--rules-out", "--runtime", "--state", "--window",
]
BEFORE_LOCAL_MIDNIGHT = ts("2026-06-01T21:30:00Z")


def failing_git(directory, args):
    return None


def unread_notes():
    return collection("notes", "document_store", {"pages": []}, None, {}, read=False, reason="HTTP 404 GET /pages")


def table(*rows):
    return {"type": "table", "text": "", "rows": [list(row) for row in rows]}


def heading(text):
    return {"type": "heading", "text": text, "rows": None}


def monitors_collection(name, events_ts_ms, cursor_monitors):
    cursor = {"events_ts_ms": events_ts_ms, "monitors": cursor_monitors}
    records = {"monitors": [], "events": [], "discovered": [], "discovery": {"read": True, "reason": None}}
    return collection(name, "observability", records, cursor, {})


def unread_metrics_collection(name):
    return collection(name, "observability", {"metrics": []}, None, {}, read=False, reason="HTTP 503 GET /spare")


def relocated(documents, place, transport):
    return {name: dict(document, place=place, transport=transport) for name, document in documents.items()}


def mcp_config():
    return make_config(
        alerts=source("observer", cloud="mcp", kind="monitors", scope_filter=""),
        gauges=source("observer", cloud="mcp", kind="metrics", scope_filter=""),
    )


class DeferredEntryTest(EvaluateCase):
    def test_monitor_absent_from_the_records_is_deferred_and_a_blind_spot(self):
        base = self.base(docs=collections(alerts=alerts(monitors=[])))

        self.assertEqual((base["deferred"], base["blind_spots"]), ([KEY], [{"key": KEY, "gap": "monitor absent"}]))

    def test_metric_without_datapoints_is_deferred_and_a_blind_spot(self):
        base = self.base(docs=collections(gauges=gauges(metrics=[metric(value=None)])))

        self.assertEqual((base["deferred"], base["blind_spots"]), (["cpu"], [{"key": "cpu", "gap": "no datapoints"}]))

    def test_metric_without_datapoints_has_no_key(self):
        self.assertEqual(self.keys(docs=collections(gauges=gauges(metrics=[metric(value=None)]))), [KEY])

    def test_metric_absent_from_the_records_is_a_blind_spot(self):
        base = self.base(docs=collections(gauges=gauges(metrics=[])))

        self.assertEqual(base["blind_spots"], [{"key": "cpu", "gap": "no datapoints"}])

    def test_failed_entry_is_deferred_with_its_reason(self):
        base = self.base(docs=collections(gauges=gauges(metrics=[], entries={"cpu": failed("HTTP 400 POST /query")})))

        self.assertEqual((base["deferred"], base["blind_spots"]), (["cpu"], [{"key": "cpu", "gap": "HTTP 400 POST /query"}]))

    def test_failed_entry_keeps_its_source_read(self):
        base = self.base(docs=collections(gauges=gauges(metrics=[], entries={"cpu": failed("HTTP 400 POST /query")})))

        self.assertTrue(base["sources"]["metrics"]["read"])

    def test_entry_not_due_is_deferred_without_blind_spot(self):
        base = self.base(docs=collections(gauges=gauges(metrics=[], entries={"cpu": skipped("not due")})))

        self.assertEqual((base["deferred"], base["blind_spots"]), (["cpu"], []))

    def test_entry_missing_from_the_collection_entries_is_a_blind_spot(self):
        base = self.base(docs=collections(gauges=gauges(entries={})))

        self.assertEqual(base["blind_spots"], [{"key": "cpu", "gap": "no entry in the collection"}])


class UnreadSourceTest(EvaluateCase):
    def test_unread_source_gives_no_key_for_its_entries(self):
        self.assertEqual(self.keys(docs=collections(gauges=unread_gauges())), [KEY])

    def test_sources_read_come_from_the_collections(self):
        base = self.base(docs=collections(gauges=unread_gauges()))

        self.assertEqual(base["sources"], {"monitors": {"read": True}, "metrics": {"read": False}})

    def test_unread_source_is_a_blind_spot_keyed_by_its_name_and_defers_nothing(self):
        base = self.base(docs=collections(gauges=unread_gauges()))

        self.assertEqual((base["blind_spots"], base["deferred"]), ([{"key": "gauges", "gap": "HTTP 503 GET /query"}], []))

    def test_missing_collection_is_collected_unread_with_reason_no_collection(self):
        base = self.base(docs={"alerts": alerts(), "notes": notes()})

        expected = {"role": "observability", "transport": "api", "read": False, "reason": "no collection"}
        self.assertEqual((base["run_context"]["collected"]["gauges"], base["sources"]["metrics"]["read"]), (expected, False))


class CursorTest(EvaluateCase):
    def test_cursors_come_from_the_collections(self):
        expected = {"events_ts_ms": NEW_EVENTS_MS, "monitors": {MON: "Alert"}, "metrics": {"cpu": 90}}

        self.assertEqual(self.base()["cursors"], expected)

    def test_unread_monitors_source_keeps_the_stored_monitors_cursor(self):
        base = self.base(docs=collections(alerts=unread_alerts()))

        expected = {"events_ts_ms": STORED_EVENTS_MS, "monitors": {MON: "OK"}, "metrics": {"cpu": 90}}
        self.assertEqual(base["cursors"], expected)

    def test_unread_metrics_source_keeps_the_stored_metrics_cursor(self):
        self.assertEqual(self.base(docs=collections(gauges=unread_gauges()))["cursors"]["metrics"], {"cpu": 10})


class DailyMetricsTest(EvaluateCase):
    def pack(self):
        return [monitor_entry(), metric_entry(schedule="daily")]

    def test_daily_entries_read_set_the_local_date_of_the_window_end(self):
        self.assertEqual(self.base(config=make_config(pack=self.pack()))["daily_metrics_on"], "2026-06-02")

    def test_daily_entries_not_due_keep_the_stored_date(self):
        docs = collections(gauges=gauges(metrics=[], entries={"cpu": skipped("not due")}))

        self.assertEqual(self.base(config=make_config(pack=self.pack()), docs=docs)["daily_metrics_on"], "2026-06-01")

    def test_daily_entries_of_an_unread_source_keep_the_stored_date(self):
        base = self.base(config=make_config(pack=self.pack()), docs=collections(gauges=unread_gauges()))

        self.assertEqual(base["daily_metrics_on"], "2026-06-01")

    def test_window_crossing_local_midnight_sets_the_local_date_of_its_end(self):
        span = {"from_ts": BEFORE_LOCAL_MIDNIGHT, "to_ts": TO_TS}
        docs = {name: dict(document, window=span) for name, document in collections().items()}

        base = self.base(config=make_config(pack=self.pack()), window=dict(make_window(), **span), docs=docs)

        self.assertEqual(base["daily_metrics_on"], "2026-06-02")

    def test_no_daily_entry_keeps_the_stored_date(self):
        self.assertEqual(self.base()["daily_metrics_on"], "2026-06-01")


class KnownGapTest(EvaluateCase):
    GAPS = [
        {"key": "cpu", "gap": "no datapoints", "runs": 3},
        {"key": KEY, "gap": "monitor absent", "runs": 1},
        {"key": "notes", "gap": "HTTP 404 GET /pages", "runs": 4},
    ]

    def test_retry_run_lists_the_known_gaps_attempted(self):
        base = self.base(stored=make_state(blind_spots=self.GAPS), window=make_window(retry_known_gaps=True))

        self.assertEqual(base["blind_spots_retried"], ["cpu", "notes"])

    def test_run_without_retry_lists_no_retried_gap(self):
        base = self.base(stored=make_state(blind_spots=self.GAPS), window=make_window(retry_known_gaps=False))

        self.assertEqual(base["blind_spots_retried"], [])

    def test_known_gaps_of_unread_sources_are_not_retried(self):
        docs = collections(gauges=unread_gauges(), notes=unread_notes())

        base = self.base(stored=make_state(blind_spots=self.GAPS), window=make_window(retry_known_gaps=True), docs=docs)

        self.assertEqual(base["blind_spots_retried"], [])

    def test_known_group_key_gap_counts_as_attempted_when_featured(self):
        pack = [metric_entry(read="top", top=3)]
        groups = [{"group": "alpha", "value": 5}]
        spots = [{"key": "cpu-alpha", "gap": "outside the top 3", "runs": 3}]

        base = self.base(
            config=make_config(pack=pack), stored=make_state(blind_spots=spots), window=make_window(retry_known_gaps=True),
            docs=collections(gauges=gauges(metrics=[metric(groups=groups)])),
        )

        self.assertEqual(base["blind_spots_retried"], ["cpu-alpha"])


class OrphanKeyTest(EvaluateCase):
    def stored(self, key="disk"):
        return make_state(items={key: make_item()})

    def test_tracked_metric_key_out_of_the_pack_is_deferred_and_a_blind_spot(self):
        base = self.base(stored=self.stored())

        self.assertEqual((base["deferred"], base["blind_spots"]), (["disk"], [{"key": "disk", "gap": "not in the query pack"}]))

    def test_tracked_key_out_of_the_pack_of_an_unread_kind_is_not_deferred(self):
        self.assertEqual(self.base(stored=self.stored(), docs=collections(gauges=unread_gauges()))["deferred"], [])

    def test_tracked_monitor_key_out_of_the_pack_is_not_an_orphan(self):
        other = state.MONITOR_PREFIX + str(10**6 + 78)
        docs = collections(alerts=alerts(entries={KEY: ok(), other: ok()}, monitors=[monitor(), monitor("Alert", str(10**6 + 78))]))

        base = self.base(stored=self.stored(other), docs=docs)

        self.assertEqual(base["blind_spots"], [])

    def test_tracked_group_key_of_a_top_entry_is_not_an_orphan(self):
        base = self.base(
            config=make_config(pack=[metric_entry(read="top", top=3)]), stored=self.stored("cpu-alpha"),
            docs=collections(gauges=gauges(metrics=[metric(groups=[{"group": "alpha", "value": 1}])])),
        )

        self.assertEqual((base["deferred"], base["blind_spots"]), ([], []))


class InputValidationTest(EvaluateCase):
    def test_invalid_config_exits_2_naming_the_key_path(self):
        config = make_config(gauges={"provider": "missing", "transport": {"cloud": "api", "local": "api"}})

        code, error = self.run_evaluate(config=config)

        self.assertEqual(code, 2)
        self.assertIn("routines.prod-watch.sources.gauges.provider", error)

    def test_unknown_timezone_exits_2(self):
        self.assertEqual(self.run_evaluate(config=make_config(timezone="Mars/Olympus"))[0], 2)

    def test_invalid_query_pack_exits_3_naming_the_key_path(self):
        code, error = self.run_evaluate(config=make_config(pack=[metric_entry(read="median")]))

        self.assertEqual(code, 3)
        self.assertIn("routines.prod-watch.query_pack[0].read", error)

    def test_query_pack_title_over_300_characters_exits_3_naming_the_key_path(self):
        code, error = self.run_evaluate(config=make_config(pack=[dict(monitor_entry(), title="t" * 301)]))

        self.assertEqual(code, 3)
        self.assertIn("routines.prod-watch.query_pack[0].title", error)

    def test_query_pack_link_with_a_line_separator_exits_3_naming_the_key_path(self):
        code, error = self.run_evaluate(config=make_config(pack=[dict(metric_entry(), link="https://example.test/\u2028")]))

        self.assertEqual(code, 3)
        self.assertIn("routines.prod-watch.query_pack[0].link", error)

    def test_pack_entry_with_a_threshold_exits_3(self):
        pack = [metric_entry(threshold={"op": ">", "value": 80})]

        self.assertEqual(self.run_evaluate(config=make_config(pack=pack))[0], 3)

    def test_routine_rules_over_the_cap_exit_3(self):
        self.assertEqual(self.run_evaluate(config=make_config(rules=["x" * 501]))[0], 3)

    def test_query_pack_is_checked_before_the_collections_are_read(self):
        config = make_config(pack=[metric_entry(read="median")])

        self.assertEqual(self.run_evaluate(config=config, docs=collections(gauges={"schema": 1}))[0], 3)

    def test_invalid_collection_exits_2_naming_the_file(self):
        code, error = self.run_evaluate(docs=collections(gauges={"schema": 1}))

        self.assertEqual(code, 2)
        self.assertIn("gauges.json", error)

    def test_collection_of_another_source_exits_2(self):
        self.assertEqual(self.run_evaluate(docs=collections(gauges=gauges() | {"source": "alerts"}))[0], 2)

    def test_collection_of_another_kind_exits_2(self):
        self.assertEqual(self.run_evaluate(docs=collections(gauges=alerts() | {"source": "gauges"}))[0], 2)

    def test_collection_of_another_window_place_or_transport_exits_2(self):
        other_window = gauges() | {"window": {"from_ts": FROM_TS - 60, "to_ts": TO_TS}}
        codes = [
            self.run_evaluate(docs=collections(gauges=other_window))[0],
            self.run_evaluate(docs=collections(gauges=gauges() | {"place": "local"}))[0],
            self.run_evaluate(docs=collections(gauges=gauges(transport="mcp")))[0],
        ]

        self.assertEqual(codes, [2, 2, 2])

    def test_window_without_boolean_retry_known_gaps_exits_3(self):
        self.assertEqual(self.run_evaluate(window=dict(make_window(), retry_known_gaps="yes"))[0], 3)

    def test_adapter_module_without_role_exits_2(self):
        config = make_config()
        config["providers"]["observer"]["adapter"] = "norole"

        with mock.patch.dict(sys.modules, {"providers.norole": types.ModuleType("providers.norole")}):
            code = self.run_evaluate(config=config, role_of=None)[0]

        self.assertEqual(code, 2)

    def test_source_name_equal_to_a_pack_key_exits_3(self):
        self.assertEqual(self.run_evaluate(config=make_config(cpu=source("observer", kind="metrics", scope_filter="")))[0], 3)

    def test_base_failing_the_facts_check_exits_2_without_any_output(self):
        code = self.run_evaluate(docs=collections(gauges=unread_gauges("x" * 301)))[0]

        self.assertEqual((code, [os.path.exists(self.path(name)) for name in ("features.json", "base.json", "rules.json")]), (2, [False] * 3))

    def test_missing_subcommand_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
            evaluate.main([])

        self.assertEqual(stop.exception.code, 2)


class RoutineFileTest(EvaluateCase):
    FILE = f"config/routines/{ROUTINE}.json"

    def write_routine_file(self, slug, text):
        os.makedirs(self.path("config/routines"), exist_ok=True)
        write_text(self.path(f"config/routines/{slug}.json"), text)

    def kept_in_file(self, config=None):
        config = make_config() if config is None else config
        routine = config["routines"].pop(ROUTINE)
        for provider in config["providers"].values():
            provider["transport"] = {"cloud": "api", "local": "mcp"}
        for configured in routine["sources"].values():
            del configured["transport"]
        self.write_routine_file(ROUTINE, json.dumps(routine))
        return config

    def test_features_of_a_routine_kept_in_a_file_equal_those_of_the_inline_form(self):
        inline = self.raw("features")

        self.assertEqual(self.raw("features", tag="-file", config=self.kept_in_file()), inline)

    def test_base_of_a_routine_kept_in_a_file_equals_that_of_the_inline_form(self):
        inline = self.raw("base")

        self.assertEqual(self.raw("base", tag="-file", config=self.kept_in_file()), inline)

    def test_another_routines_broken_file_does_not_stop_features(self):
        config = self.kept_in_file()
        self.write_routine_file("other-routine", "{not json")

        self.assertEqual(self.run_evaluate(config=config), (0, ""))

    def test_pack_error_exits_3(self):
        config = self.kept_in_file(make_config(pack=[metric_entry(read="median")]))

        self.assertEqual(self.run_evaluate(config=config)[0], 3)

    def test_pack_error_names_the_routine_file_and_the_key_path_inside_it(self):
        config = self.kept_in_file(make_config(pack=[metric_entry(read="median")]))

        error = self.run_evaluate(config=config)[1]

        self.assertTrue(error.startswith(f"evaluate.py: rejected: config: {self.FILE}: query_pack[0].read: "), error)

    def test_source_config_error_exits_2(self):
        config = self.kept_in_file(make_config(gauges=source("observer", kind="metrics")))

        self.assertEqual(self.run_evaluate(config=config)[0], 2)

    def test_source_config_error_names_the_routine_file_and_the_key_path_inside_it(self):
        config = self.kept_in_file(make_config(gauges=source("observer", kind="metrics")))

        error = self.run_evaluate(config=config)[1]

        self.assertEqual(error, f"evaluate.py: config: {self.FILE}: sources.gauges.scope_filter: missing\n")

    def test_transport_left_unresolved_exits_2_naming_the_routine_file(self):
        config = self.kept_in_file()
        del config["providers"]["observer"]["transport"]

        code, error = self.run_evaluate(config=config)

        self.assertEqual((code, f"config: {self.FILE}: sources.alerts.transport.cloud: " in error), (2, True))


class OutputTest(EvaluateCase):
    def test_base_holds_every_facts_field_but_the_observations(self):
        expected = [
            "blind_spots", "blind_spots_retried", "cursors", "daily_metrics_on", "deferred", "models", "mutes",
            "resolved_queries", "run_context", "sources", "sources_last_edited",
        ]

        self.assertEqual(sorted(self.base()), expected)

    def test_base_passes_the_engine_facts_validation_once_given_empty_observations(self):
        base = self.base(docs=collections(alerts=alerts(monitors=[]), notes=unread_notes()))

        state.check_facts({**base, "observations": {}})

    def test_features_and_rules_are_compact_sorted_json(self):
        raw = self.raw("features")

        self.assertEqual(raw, (json.dumps(json.loads(raw.decode("utf-8")), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))

    def test_base_is_canonical_json(self):
        raw = self.raw("base")

        self.assertEqual(raw, state.dump(json.loads(raw.decode("utf-8"))))

    def test_same_inputs_give_byte_identical_files(self):
        first = [self.raw(name, tag="1") for name in ("features", "base", "rules")]

        self.assertEqual([self.raw(name, tag="2") for name in ("features", "base", "rules")], first)

    def test_transports_change_only_the_run_context(self):
        api = self.base(tag="1")
        docs = collections(alerts=alerts(transport="mcp"), gauges=gauges(transport="mcp"))
        mcp = self.base(tag="2", config=mcp_config(), docs=docs)
        del api["run_context"], mcp["run_context"]

        self.assertEqual(api, mcp)

    def test_transport_shows_in_the_run_context(self):
        base = self.base(config=mcp_config(), docs=collections(alerts=alerts(transport="mcp"), gauges=gauges(transport="mcp")))

        self.assertEqual(base["run_context"]["collected"]["gauges"]["transport"], "mcp")

    def test_features_command_exposes_the_contract_flags(self):
        parser = evaluate.build_parser()
        command = next(action for action in parser._actions if action.dest == "command").choices["features"]
        flags = sorted(option for action in command._actions for option in action.option_strings if option.startswith("--"))

        self.assertEqual(flags, sorted(FEATURES_FLAGS + ["--help"]))

    def test_rules_hold_the_routine_rules_and_one_rule_per_entry(self):
        rules = self.rules(config=make_config(rules=["Flapping monitors are Low"]))

        self.assertEqual(rules, {"routine": ["Flapping monitors are Low"], "entries": {KEY: "Alert is High and now", "cpu": "Open above 80"}})


class SeveralSourcesPerKindTest(EvaluateCase):
    PACK = [monitor_entry(), metric_entry(), metric_entry(key="mem", source="spare")]

    def config(self, pack=None):
        return make_config(
            pack=self.PACK if pack is None else pack,
            spare=source("observer", kind="metrics", scope_filter=""),
            pager=source("observer", kind="monitors", scope_filter=""),
        )

    def docs(self, **overrides):
        documents = collections(
            spare=metrics_collection("spare", [metric(key="mem", value=40)], {"mem": 40}, {"mem": ok()}),
            pager=monitors_collection("pager", NEW_EVENTS_MS + 5, {"mon-2": "OK"}),
        )
        documents.update(overrides)
        return documents

    def test_newest_events_cursor_of_the_kind_wins(self):
        self.assertEqual(self.base(config=self.config(), docs=self.docs())["cursors"]["events_ts_ms"], NEW_EVENTS_MS + 5)

    def test_cursors_of_the_kind_merge(self):
        cursors = self.base(config=self.config(), docs=self.docs())["cursors"]

        self.assertEqual((cursors["monitors"], cursors["metrics"]), ({MON: "Alert", "mon-2": "OK"}, {"cpu": 90, "mem": 40}))

    def test_kind_is_read_only_when_every_source_of_it_is_read(self):
        base = self.base(config=self.config(), docs=self.docs(spare=unread_metrics_collection("spare")))

        self.assertFalse(base["sources"]["metrics"]["read"])

    def test_entry_of_a_read_source_in_an_unread_kind_has_no_key(self):
        self.assertEqual(self.keys(config=self.config(), docs=self.docs(spare=unread_metrics_collection("spare"))), [KEY])

    def test_daily_entry_of_a_read_source_in_an_unread_kind_keeps_the_stored_date(self):
        pack = [monitor_entry(), metric_entry(schedule="daily"), metric_entry(key="mem", source="spare")]

        base = self.base(config=self.config(pack), docs=self.docs(spare=unread_metrics_collection("spare")))

        self.assertEqual(base["daily_metrics_on"], "2026-06-01")


class RoutineShapeTest(EvaluateCase):
    def monitors_only(self):
        config = make_config(pack=[monitor_entry()])
        del config["routines"][ROUTINE]["sources"]["gauges"]
        docs = collections()
        del docs["gauges"]
        return self.base(config=config, docs=docs), self.keys(config=config, docs=docs, tag="2")

    def test_monitors_only_routine_features_its_monitor_and_marks_metrics_not_read(self):
        base, keys = self.monitors_only()

        self.assertEqual((keys, base["sources"]), ([KEY], {"monitors": {"read": True}, "metrics": {"read": False}}))

    def test_mixed_schedules_in_one_source_feature_the_due_entry_and_defer_the_other(self):
        pack = [monitor_entry(), metric_entry(), metric_entry(key="mem", schedule="daily")]
        docs = collections(gauges=gauges(entries={"cpu": ok(), "mem": skipped("not due")}))

        base = self.base(config=make_config(pack=pack), docs=docs)

        self.assertEqual((base["deferred"], base["daily_metrics_on"]), (["mem"], "2026-06-01"))


class SourcesPageTest(EvaluateCase):
    def test_mutes_come_from_the_table_under_the_mutes_heading(self):
        self.assertEqual(self.base()["mutes"], [{"key": "cpu", "until": "2026-06-10"}])

    def test_mutes_skip_rows_with_an_empty_key(self):
        blocks = [heading("Mutes"), table(["key", "until"], ["", "2026-06-11"], ["cpu", "2026-06-10"])]

        base = self.base(docs=collections(notes=notes(blocks)))

        self.assertEqual(base["mutes"], [{"key": "cpu", "until": "2026-06-10"}])

    def test_mutes_skip_rows_without_a_valid_until_date(self):
        blocks = [heading("Mutes"), table(["key", "until"], ["io", "next week"], ["cpu", "2026-06-10"])]

        base = self.base(docs=collections(notes=notes(blocks)))

        self.assertEqual(base["mutes"], [{"key": "cpu", "until": "2026-06-10"}])

    def test_mutes_ignore_tables_before_the_mutes_heading(self):
        blocks = [table(["key", "until"], ["io", "2026-06-11"]), heading("Mutes"), table(["key", "until"], ["cpu", "2026-06-10"])]

        base = self.base(docs=collections(notes=notes(blocks)))

        self.assertEqual(base["mutes"], [{"key": "cpu", "until": "2026-06-10"}])

    def test_mutes_read_their_columns_by_header_name(self):
        blocks = [heading("Mutes"), table(["until", "note", "key"], ["2026-06-10", "noisy", "cpu"])]

        base = self.base(docs=collections(notes=notes(blocks)))

        self.assertEqual(base["mutes"], [{"key": "cpu", "until": "2026-06-10"}])

    def test_page_without_mutes_heading_has_no_mutes(self):
        base = self.base(docs=collections(notes=notes([heading("Sources"), table(["key", "until"], ["cpu", "2026-06-10"])])))

        self.assertEqual(base["mutes"], [])

    def test_sources_last_edited_comes_from_the_page(self):
        self.assertEqual(self.base()["sources_last_edited"], "2026-06-01T20:00:00Z")

    def test_unread_page_keeps_the_stored_mutes(self):
        base = self.base(docs=collections(notes=unread_notes()))

        self.assertEqual(base["mutes"], STORED_MUTES)

    def test_unread_page_keeps_the_stored_sources_last_edited(self):
        base = self.base(docs=collections(notes=unread_notes()))

        self.assertEqual(base["sources_last_edited"], "2026-05-01T08:00:00Z")

    def test_unread_page_with_no_stored_mutes_has_no_mutes(self):
        stored = make_state()
        del stored["run"]["mutes"]

        base = self.base(stored=stored, docs=collections(notes=unread_notes()))

        self.assertEqual(base["mutes"], [])


class CopiedValuesTest(EvaluateCase):
    def test_resolved_queries_come_from_the_state(self):
        self.assertEqual(self.base()["resolved_queries"], {"cpu": "avg:cpu"})

    def test_models_come_from_the_routine_config(self):
        self.assertEqual(self.base()["models"], {"main": "model-a"})


class RunContextTest(EvaluateCase):
    def test_run_context_names_the_place_runtime_and_config_commit(self):
        context = self.base(place="local", docs=relocated(collections(), "local", "mcp"))["run_context"]
        del context["collected"]

        self.assertEqual(context, {"place": "local", "runtime": "runtime-a", "config": COMMIT, "config_dirty": False})

    def test_config_with_uncommitted_changes_is_dirty(self):
        base = self.base(git=git_answers(status=" M config.json\n"))

        self.assertTrue(base["run_context"]["config_dirty"])

    def test_failing_git_gives_null_config_and_dirty_flag(self):
        context = self.base(git=failing_git)["run_context"]

        self.assertEqual((context["config"], context["config_dirty"]), (None, None))

    def test_git_is_asked_about_the_config_file_and_the_routine_file_in_its_directory(self):
        calls = []

        def recording_git(directory, args):
            calls.append((directory, list(args)))
            return ""

        self.base(git=recording_git)

        status = ["status", "--porcelain", "--", "config.json", f"config/routines/{ROUTINE}.json"]
        self.assertEqual(calls, [(self.dir, ["rev-parse", "HEAD"]), (self.dir, status)])

    def test_collected_names_role_transport_and_read_per_source(self):
        base = self.base(docs=collections(notes=unread_notes()))

        expected = {
            "alerts": {"role": "observability", "transport": "api", "read": True, "reason": None},
            "gauges": {"role": "observability", "transport": "api", "read": True, "reason": None},
            "notes": {"role": "document_store", "transport": "api", "read": False, "reason": "HTTP 404 GET /pages"},
        }
        self.assertEqual(base["run_context"]["collected"], expected)


class MoreSourcesPageTest(EvaluateCase):
    def test_read_document_store_without_pages_keeps_the_stored_page_values(self):
        empty = collection("notes", "document_store", {"pages": []}, {"last_edited": None}, {})

        base = self.base(docs=collections(notes=empty))

        self.assertEqual((base["mutes"], base["sources_last_edited"]), (STORED_MUTES, "2026-05-01T08:00:00Z"))

    def test_mutes_header_cells_match_case_insensitively(self):
        base = self.base(docs=collections(notes=notes([heading("Mutes"), table(["Key", "Until"], ["cpu", "2026-06-10"])])))

        self.assertEqual(base["mutes"], [{"key": "cpu", "until": "2026-06-10"}])

    def test_mutes_read_a_silence_until_column(self):
        blocks = [heading("Mutes"), table(["Key", "Silence until", "Reason"], ["cpu", "2026-06-10", "noisy"])]

        base = self.base(docs=collections(notes=notes(blocks)))

        self.assertEqual((base["mutes"], base["blind_spots"]), ([{"key": "cpu", "until": "2026-06-10"}], []))

    def test_mutes_table_with_both_until_columns_is_unreadable(self):
        blocks = [heading("Mutes"), table(["key", "until", "silence until"], ["cpu", "", "2026-06-10"])]

        base = self.base(docs=collections(notes=notes(blocks)))

        self.assertEqual(
            (base["mutes"], base["blind_spots"]),
            (STORED_MUTES, [{"key": "notes", "gap": "mutes table unreadable"}]),
        )

    def test_mutes_table_stops_at_the_next_heading(self):
        blocks = [heading("Mutes"), heading("Thresholds"), table(["key", "until"], ["cpu", "2026-06-10"])]

        base = self.base(docs=collections(notes=notes(blocks)))

        self.assertEqual(base["mutes"], [])

    def test_malformed_mutes_header_keeps_the_stored_mutes(self):
        blocks = [heading("Mutes"), table(["name", "date"], ["cpu", "2026-06-10"])]

        base = self.base(docs=collections(notes=notes(blocks)))

        self.assertEqual(base["mutes"], STORED_MUTES)

    def test_malformed_mutes_header_is_a_blind_spot_of_the_page_source(self):
        blocks = [heading("Mutes"), table(["name", "date"], ["cpu", "2026-06-10"])]

        base = self.base(docs=collections(notes=notes(blocks)))

        self.assertEqual(base["blind_spots"], [{"key": "notes", "gap": "mutes table unreadable"}])


class GitRepoCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        clean = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
        clean.update({
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CEILING_DIRECTORIES": os.path.dirname(self.dir),
        })
        patcher = mock.patch.dict(os.environ, clean, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def git(self, *args):
        identity = ["-c", "user.name=tester", "-c", "user.email=tester@example.test", "-c", "commit.gpgsign=false"]
        subprocess.run(["git", "-C", self.dir, *identity, *args], capture_output=True, check=True)

    def commit_config(self):
        write_json(os.path.join(self.dir, "config.json"), {"timezone": "UTC"})
        self.git("init", "-q")
        self.git("add", "config.json")
        self.git("commit", "-q", "-m", "config")


class RunGitTest(GitRepoCase):
    def test_reads_the_commit_of_a_repository(self):
        self.commit_config()

        self.assertRegex(evaluate.run_git(self.dir, ["rev-parse", "HEAD"]), r"^[0-9a-f]{40,64}\n$")

    def test_committed_config_has_no_status_line(self):
        self.commit_config()

        self.assertEqual(evaluate.run_git(self.dir, ["status", "--porcelain", "--", "config.json"]), "")

    def test_changed_config_has_a_status_line(self):
        self.commit_config()
        write_json(os.path.join(self.dir, "config.json"), {"timezone": "Europe/Paris"})

        self.assertRegex(evaluate.run_git(self.dir, ["status", "--porcelain", "--", "config.json"]), r"config\.json")

    def test_directory_outside_a_repository_gives_none(self):
        self.assertIsNone(evaluate.run_git(self.dir, ["rev-parse", "HEAD"]))


class RoutineFileDirtyTest(GitRepoCase):
    ROUTINE_FILE = os.path.join("config", "routines", f"{ROUTINE}.json")

    def write_routine_file(self, document):
        os.makedirs(os.path.join(self.dir, "config", "routines"), exist_ok=True)
        write_json(os.path.join(self.dir, self.ROUTINE_FILE), document)

    def commit_routine_file(self):
        self.write_routine_file({"sources": {}})
        self.git("add", self.ROUTINE_FILE)
        self.git("commit", "-q", "-m", "routine")

    def config_dirty(self, routine=ROUTINE):
        args = types.SimpleNamespace(config=os.path.join(self.dir, "config.json"), routine=routine, place="cloud", runtime="runtime-a")
        return evaluate.run_context(args, {}, evaluate.run_git)["config_dirty"]

    def commit_sibling_and_modify_it(self):
        sibling = os.path.join("config", "routines", "other.json")
        os.makedirs(os.path.join(self.dir, "config", "routines"), exist_ok=True)
        write_json(os.path.join(self.dir, sibling), {"sources": {}})
        self.git("add", sibling)
        self.git("commit", "-q", "-m", "sibling")
        write_json(os.path.join(self.dir, sibling), {"sources": {"changed": {}}})

    def test_committed_config_and_routine_file_are_not_dirty(self):
        self.commit_config()
        self.commit_routine_file()

        self.assertIs(self.config_dirty(), False)

    def test_modified_routine_file_is_dirty(self):
        self.commit_config()
        self.commit_routine_file()
        self.write_routine_file({"sources": {"changed": {}}})

        self.assertIs(self.config_dirty(), True)

    def test_untracked_routine_file_is_dirty(self):
        self.commit_config()
        self.write_routine_file({"sources": {}})

        self.assertIs(self.config_dirty(), True)

    def test_absent_routine_file_is_not_dirty(self):
        self.commit_config()

        self.assertIs(self.config_dirty(), False)

    def test_modified_sibling_routine_file_is_not_dirty(self):
        self.commit_config()
        self.commit_sibling_and_modify_it()

        self.assertIs(self.config_dirty(), False)

    def test_glob_slug_never_widens_the_dirty_check(self):
        self.commit_config()
        self.commit_sibling_and_modify_it()

        self.assertIs(self.config_dirty("*"), False)

    def test_parent_directory_slug_keeps_the_dirty_check(self):
        self.commit_config()

        self.assertIs(self.config_dirty("../../x"), False)


PREVIEW = {"new": [{"key": KEY}, {"key": "cpu"}], "escalated": []}


def judge_argv(features, base, judgment, out):
    return ["judge", "--features", features, "--base", base, "--judgment", judgment, "--out", out]


def annotate_argv(features, facts, analysis, preview, out):
    return ["annotate", "--features", features, "--facts", facts, "--analysis", analysis, "--preview", preview, "--out", out]


class JudgmentTest(EvaluateCase):
    def ready(self, **kwargs):
        code, error = self.run_evaluate(**kwargs)
        self.assertEqual((code, error), (0, ""))

    def command(self, *argv):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = evaluate.main(list(argv))
        return code, stderr.getvalue()

    def run_judge(self, judgment="judgment.json", out="facts.json"):
        return self.command(*judge_argv(self.path("features.json"), self.path("base.json"), self.path(judgment), self.path(out)))

    def run_annotate(self, analysis="analysis.json", preview="preview.json", facts="facts.json", out="annotated.json"):
        return self.command(
            *annotate_argv(self.path("features.json"), self.path(facts), self.path(analysis), self.path(preview), self.path(out))
        )

    def judge(self, document=None, out="facts.json"):
        write_json(self.path("judgment.json"), judgment_of() if document is None else document)
        return self.run_judge(out=out)

    def annotate(self, analysis=None, summary=None, facts="facts.json", out="annotated.json"):
        write_json(self.path("analysis.json"), analysis_of() if analysis is None else analysis)
        write_json(self.path("preview.json"), PREVIEW if summary is None else summary)
        return self.run_annotate(facts=facts, out=out)

    def validated(self, name):
        with contextlib.redirect_stdout(io.StringIO()):
            return state.main(["validate", "--facts", self.path(name)])

    def read(self, name):
        with open(self.path(name), "rb") as handle:
            return handle.read()

    def read_json(self, name):
        return json.loads(self.read(name).decode("utf-8"))

    def apply(self, facts, tag, stored="state.json"):
        argv = [
            "apply", "--state", self.path(stored), "--facts", self.path(facts), "--window", self.path("window.json"),
            "--tz", "Europe/Paris", "--out", self.path(f"next{tag}.json"), "--summary", self.path(f"summary{tag}.json"),
            "--record", self.path(f"record{tag}.json"),
        ]
        self.assertEqual(state.main(argv), 0)
        return self.read_json(f"summary{tag}.json")


class JudgeCommandTest(JudgmentTest):
    def test_facts_hold_the_observations_of_the_judgment_and_the_base(self):
        self.ready()
        self.assertEqual(self.judge(), (0, ""))

        facts = self.read_json("facts.json")

        self.assertEqual({key: (item["over"], item["rank"]) for key, item in facts["observations"].items()}, {KEY: (True, 1), "cpu": (True, 2)})
        self.assertEqual({name: value for name, value in facts.items() if name not in ("observations", "overrides")}, self.read_json("base.json"))

    def test_facts_are_accepted_by_the_state_engine(self):
        self.ready()
        self.judge()

        self.assertEqual(self.validated("facts.json"), 0)

    def test_facts_are_written_with_the_dump_of_the_base(self):
        self.ready()
        self.judge()

        facts = self.read_json("facts.json")

        self.assertEqual(self.read("facts.json"), state.dump(facts))

    def test_same_inputs_give_byte_identical_facts(self):
        self.ready()
        self.judge(out="first.json")
        self.judge(out="second.json")

        self.assertEqual(self.read("first.json"), self.read("second.json"))

    def test_rejection_exits_3_with_the_key_path_and_writes_nothing(self):
        self.ready()
        document = judgment_of(**{KEY: monitor_verdict(severity="Critical"), "cpu": cpu_verdict()})

        code, error = self.judge(document)

        self.assertEqual(code, 3)
        self.assertIn("judgment: ", error)
        self.assertIn(f"verdicts.{KEY}.severity", error)
        self.assertFalse(os.path.exists(self.path("facts.json")))

    def test_rejection_leaves_the_existing_facts_unchanged(self):
        self.ready()
        self.judge()
        before = self.read("facts.json")

        code, _ = self.judge(judgment_of(cpu=cpu_verdict(rank=1)))

        self.assertEqual((code, self.read("facts.json")), (3, before))

    def test_missing_judgment_file_exits_2(self):
        self.ready()

        code, error = self.run_judge(judgment="absent.json")

        self.assertEqual(code, 2)
        self.assertIn("judgment: cannot read", error)

    def test_invalid_json_judgment_exits_3_naming_the_file_and_writes_nothing(self):
        self.ready()
        write_text(self.path("judgment.json"), "{not json")

        code, error = self.run_judge()

        self.assertEqual(code, 3)
        self.assertIn("rejected: judgment: invalid JSON in " + self.path("judgment.json"), error)
        self.assertFalse(os.path.exists(self.path("facts.json")))

    def test_judgment_that_is_not_utf8_exits_3(self):
        self.ready()
        with open(self.path("judgment.json"), "wb") as handle:
            handle.write(b"\xff\xfe")

        code, error = self.run_judge()

        self.assertEqual(code, 3)
        self.assertIn("judgment: invalid JSON", error)

    def test_invalid_json_judgment_leaves_the_existing_facts_unchanged(self):
        self.ready()
        self.judge()
        before = self.read("facts.json")
        write_text(self.path("judgment.json"), "{not json")

        self.assertEqual((self.run_judge()[0], self.read("facts.json")), (3, before))

    def test_invalid_json_features_exits_2(self):
        self.ready()
        write_text(self.path("features.json"), "{not json")

        code, error = self.judge()

        self.assertEqual(code, 2)
        self.assertIn("features: invalid JSON", error)

    def test_invalid_json_base_exits_2(self):
        self.ready()
        write_text(self.path("base.json"), "{not json")

        code, error = self.judge()

        self.assertEqual(code, 2)
        self.assertIn("base: invalid JSON", error)

    def test_missing_features_file_exits_2(self):
        self.ready()
        os.remove(self.path("features.json"))

        code, error = self.judge()

        self.assertEqual(code, 2)
        self.assertIn("features: cannot read", error)

    def test_base_that_fails_the_facts_shape_exits_2(self):
        self.ready()
        write_json(self.path("base.json"), {"sources": {}})

        code, error = self.judge()

        self.assertEqual(code, 2)
        self.assertIn("base:", error)

    def test_tracked_monitor_reported_missing_is_merged_as_an_auto_observation(self):
        stored = make_state(items={KEY: make_item(severity="High", when="now")})
        self.ready(stored=stored, docs=collections(alerts=alerts(monitors=[], entries={KEY: missing()})))
        self.assertEqual(
            self.read_json("features.json")["auto"],
            {KEY: {"reason": "not found", "title": "Disk", "link": "https://example.test/disk", "severity": "High", "when": "now"}},
        )

        self.assertEqual(self.judge(judgment_of(cpu=cpu_verdict(rank=1))), (0, ""))

        self.assertEqual(
            self.read_json("facts.json")["observations"][KEY],
            {
                "source": "monitors", "over": False, "value": None, "severity": "High", "when": "now",
                "title": "Disk", "link": "https://example.test/disk", "last_value": "not found", "rank": None,
            },
        )
        self.assertEqual(self.validated("facts.json"), 0)


class AnnotateCommandTest(JudgmentTest):
    def setUp(self):
        super().setUp()
        self.ready()
        self.judge()

    def test_analysis_joins_the_observations_and_nothing_else_changes(self):
        self.assertEqual(self.annotate(), (0, ""))

        annotated, merged = self.read_json("annotated.json"), self.read_json("facts.json")

        for key in (KEY, "cpu"):
            fields = {name: annotated["observations"][key].pop(name) for name in state.OPTIONAL_FIELDS}
            self.assertEqual(fields["reason"], [{"tag": "measured", "claim": "the value is above its limit"}])
            self.assertEqual((fields["risk"], fields["action"]), ("the service degrades for every caller", "page the owner"))
        self.assertEqual(annotated, merged)

    def test_annotated_facts_are_accepted_by_the_state_engine(self):
        self.annotate()

        self.assertEqual(self.validated("annotated.json"), 0)

    def test_annotated_facts_are_written_with_the_state_dump(self):
        self.annotate()

        self.assertEqual(self.read("annotated.json"), state.dump(self.read_json("annotated.json")))

    def test_analysis_for_a_key_the_preview_does_not_list_exits_3_and_writes_nothing(self):
        code, error = self.annotate(summary={"new": [{"key": "cpu"}], "escalated": []})

        self.assertEqual(code, 3)
        self.assertIn(f"analysis: items.{KEY}", error)
        self.assertFalse(os.path.exists(self.path("annotated.json")))

    def test_invalid_json_analysis_exits_3_naming_the_file_and_writes_nothing(self):
        write_text(self.path("analysis.json"), "{not json")
        write_json(self.path("preview.json"), PREVIEW)

        code, error = self.run_annotate()

        self.assertEqual(code, 3)
        self.assertIn("rejected: analysis: invalid JSON in " + self.path("analysis.json"), error)
        self.assertFalse(os.path.exists(self.path("annotated.json")))

    def test_invalid_json_preview_exits_2(self):
        write_json(self.path("analysis.json"), analysis_of())
        write_text(self.path("preview.json"), "{not json")

        code, error = self.run_annotate()

        self.assertEqual(code, 2)
        self.assertIn("preview: invalid JSON", error)

    def test_invalid_json_facts_exits_2(self):
        write_text(self.path("facts.json"), "{not json")

        code, error = self.annotate()

        self.assertEqual(code, 2)
        self.assertIn("facts: invalid JSON", error)

    def test_missing_preview_file_exits_2(self):
        write_json(self.path("analysis.json"), analysis_of())

        code, error = self.run_annotate(preview="absent.json")

        self.assertEqual(code, 2)
        self.assertIn("preview: cannot read", error)

    def test_preview_without_the_new_list_exits_2(self):
        code, error = self.annotate(summary={"escalated": []})

        self.assertEqual(code, 2)
        self.assertIn("preview:", error)

    def test_facts_that_fail_the_state_check_exit_2(self):
        write_json(self.path("facts.json"), {"observations": {}})

        code, error = self.annotate()

        self.assertEqual(code, 2)
        self.assertIn("facts:", error)

    def test_listed_key_missing_from_the_facts_exits_2(self):
        merged = self.read_json("facts.json")
        del merged["observations"]["cpu"]
        write_json(self.path("facts.json"), merged)

        code, error = self.annotate()

        self.assertEqual(code, 2)
        self.assertIn("observations.cpu", error)


class JudgmentPipelineTest(JudgmentTest):
    def test_preview_lists_the_changes_in_rank_order_and_the_real_apply_stores_the_analysis(self):
        self.ready(docs=collections(notes=notes([])))
        self.judge(judgment_of(**{KEY: monitor_verdict(rank=1), "cpu": cpu_verdict(rank=2)}))

        preview = self.apply("facts.json", "-preview")

        self.assertEqual([entry["key"] for entry in preview["new"]], [KEY, "cpu"])
        self.assertEqual(self.annotate(summary={"new": [{"key": entry["key"]} for entry in preview["new"]], "escalated": []}), (0, ""))
        summary = self.apply("annotated.json", "-final")
        items = self.read_json("next-final.json")["items"]

        self.assertEqual([entry["key"] for entry in summary["new"]], [KEY, "cpu"])
        self.assertEqual((items["cpu"]["risk"], items["cpu"]["mitigation"]), ("the service degrades for every caller", ["roll back the last deploy"]))
        self.assertEqual(summary["new"][0]["action"], "page the owner")

    def test_swapped_ranks_swap_the_summary_order(self):
        self.ready(docs=collections(notes=notes([])))
        self.judge(judgment_of(**{KEY: monitor_verdict(rank=2), "cpu": cpu_verdict(rank=1)}))

        self.assertEqual([entry["key"] for entry in self.apply("facts.json", "-swapped")["new"]], ["cpu", KEY])


if __name__ == "__main__":
    unittest.main()
