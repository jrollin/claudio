import copy
import json
import os
import unittest

import features
import state
import tribe_features
import tribe_judgment
import tribe_page
from providers import notion
from tribe_support import (
    CHANNEL_A, FileCase, LINK_ISSUE, LINK_PAGE, LINK_REPLY, LINK_ROOT, NOW, PACK_ENTRY, PAGE_ID, PAGE_TWO, ROUTINE, SOURCES,
    THREAD_TS, TZ, WINDOW, WRITTEN, ZONE, block, collection, collections_for, compute, fixture, fixture_json, issue, make_config,
    make_state, make_warning, message, metric_record, page, run_cli, tick, trend_points, unread,
)

PRIVATE_NAMES = {"over", "threshold", "severity", "when", "urgency", "rank", "tracked"}
RECORD_FIELDS = ("kind", "link", "source", "text", "title", "values")
WINDOW_FIELDS = ("kind", "link", "source", "title", "values")


def features_of(**kwargs):
    return compute(**kwargs)[0]


def overview(blocks=(), last_edited="2026-10-15T09:00:00Z"):
    return collection("previous-digest", {"pages": [page(PAGE_ID, "Digest", list(blocks), last_edited)]})


def digest_blocks(status="open", ticked=False, topic="Capacity"):
    row = [f"Queue depth rises\nstatus: {status}\nkey: queue-depth", "Medium\nwatch\nrunway: about two weeks", "jobs start late", "reports arrive late", "add a worker", "confidence: measured"]
    return [
        block("heading", "Since last run"),
        block("heading", "Decisions this week"),
        block("heading", "Warnings"),
        block("heading", "Focus"),
        block("table", "", rows=[list(tribe_page.FOCUS_COLUMNS), ["Capacity", "Medium", "watch", "1"]]),
        block("heading", topic),
        block("table", "", rows=[list(tribe_page.TOPIC_COLUMNS), row]),
        block("heading", "What to check"),
        block("heading", "This week"),
        block("list", "Capacity Ask for the export ask-export", checked=ticked),
        block("list", "A plain bullet"),
    ]


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.keys = features_of()["keys"]

    def test_a_chat_message_is_a_record_with_its_source_link_and_thread(self):
        doc = self.keys[f"record:channels:{CHANNEL_A}:1791990730.002679"]
        self.assertEqual((doc["kind"], doc["source"], doc["link"]), ("record", "channels", LINK_ROOT))
        self.assertEqual(doc["values"], {"channel": CHANNEL_A, "ts": "1791990730.002679", "thread": "1791990730.002679", "reply": False})

    def test_a_reply_is_its_own_record_pointing_at_its_thread_root(self):
        doc = self.keys[f"record:channels:{CHANNEL_A}:1791990731.000100"]
        self.assertEqual((doc["link"], doc["values"]["thread"], doc["values"]["reply"]), (LINK_REPLY, "1791990730.002679", True))

    def test_message_text_is_cleaned_of_mentions_and_markup(self):
        doc = self.keys[f"record:channels:{CHANNEL_A}:1791990730.002679"]
        self.assertEqual(doc["text"], "Queue is slow   usr_aaa01 ")

    def test_an_issue_is_a_record_with_key_type_status_priority_update_and_sprint_flag(self):
        doc = self.keys["record:issues:ABC-1"]
        self.assertEqual(
            doc["values"],
            {"key": "ABC-1", "type": "Task", "status": "In Progress", "priority": "High", "updated": "2026-10-15T09:00:00Z", "in_open_sprint": True},
        )
        self.assertEqual((doc["link"], doc["title"]), (LINK_ISSUE, "Upgrade the queue"))

    def test_a_changed_page_is_a_record_with_its_blocks_as_plain_text(self):
        doc = self.keys[f"record:pages:{PAGE_TWO}"]
        self.assertEqual((doc["link"], doc["text"]), (LINK_PAGE, "Queue Drain first a | b"))

    def test_the_previous_digest_page_is_no_record(self):
        keys = features_of(collections=collections_for(**{"previous-digest": overview(digest_blocks())}))["keys"]
        self.assertEqual([key for key in keys if PAGE_ID in key], [])

    def test_authors_carry_the_chat_author_ids_only(self):
        self.assertEqual(features_of()["authors"], ["usr_aaa01", "usr_bbb02"])

    def test_an_unread_source_adds_no_record_and_no_author(self):
        chat = unread("channels", {"messages": []})
        doc = features_of(collections=collections_for(channels=chat))
        self.assertEqual((doc["authors"], [key for key in doc["keys"] if key.startswith("record:channels")]), ([], []))

    def test_every_record_link_pairs_with_its_source(self):
        pairs = {(doc["source"], doc["link"]) for doc in self.keys.values() if doc["kind"] == "record"}
        self.assertEqual(pairs, {("channels", LINK_ROOT), ("channels", LINK_REPLY), ("issues", LINK_ISSUE), ("pages", LINK_PAGE)})


class HostileTextTests(unittest.TestCase):
    def keys(self, **overrides):
        return features_of(collections=collections_for(**overrides))["keys"]

    def hostile_issue(self):
        return issue(key="AB<1>@x", type="Ta\u200bsk", status="In @Progress", priority="<High>", title="Fix <b>this</b> @all")

    def test_issue_fields_are_cleaned_in_the_values_the_key_and_the_text(self):
        keys = self.keys(issues=collection("issues", {"issues": [self.hostile_issue()]}, cursor={"updated": None}))
        self.assertEqual(
            {key: doc["values"] for key, doc in keys.items() if key.startswith("record:issues")},
            {"record:issues:AB 1  x": {"key": "AB 1  x", "type": "Ta sk", "status": "In  Progress", "priority": " High ", "updated": "2026-10-15T09:00:00Z", "in_open_sprint": True}},
        )

    def test_issue_title_and_text_hold_no_mention_or_markup_character(self):
        doc = self.keys(issues=collection("issues", {"issues": [self.hostile_issue()]}, cursor={"updated": None}))["record:issues:AB 1  x"]
        self.assertEqual((doc["title"], doc["text"]), ("Fix  b this /b   all", "Fix  b this /b   all"))

    def test_an_issue_without_a_priority_keeps_null(self):
        keys = self.keys(issues=collection("issues", {"issues": [issue(priority=None)]}, cursor={"updated": None}))
        self.assertIsNone(keys["record:issues:ABC-1"]["values"]["priority"])

    def test_page_id_title_and_text_are_cleaned(self):
        pages = [page("p<1>", "<img> @here", [block("paragraph", "<script>x</script> @here")])]
        keys = self.keys(pages=collection("pages", {"pages": pages}, cursor={"pages": {}}))
        doc = keys["record:pages:p 1 "]
        self.assertEqual((doc["title"], doc["text"]), (" img   here", " script x /script   here"))

    def test_message_channel_and_stamp_are_cleaned_in_the_key_and_the_values(self):
        messages = [{**message("17.1", "hi"), "channel": "C<1>"}]
        keys = self.keys(channels=collection("channels", {"messages": messages}, cursor={"ts": {}}))
        self.assertEqual(
            {key: doc["values"] for key, doc in keys.items() if key.startswith("record:channels")},
            {"record:channels:C 1 :17.1": {"channel": "C 1 ", "ts": "17.1", "thread": "17.1", "reply": False}},
        )


class WindowDocumentTests(unittest.TestCase):
    def setUp(self):
        self.keys = features_of()["keys"]

    def test_a_monitor_document_names_its_source_and_values(self):
        doc = self.keys["monitor-1001"]
        self.assertEqual((doc["kind"], doc["source"], doc["title"]), ("monitor", "monitors", "Queue alert"))
        self.assertEqual((doc["values"]["state"], doc["values"]["transitions"]), ("Alert", 1))

    def test_a_metric_document_holds_the_window_value_and_the_change_from_the_stored_cursor(self):
        doc = self.keys["metric:queue-depth"]
        self.assertEqual((doc["kind"], doc["source"], doc["link"]), ("metric", "metrics", PACK_ENTRY["link"]))
        self.assertEqual((doc["values"]["value"], doc["values"]["previous"], doc["values"]["change"]), (12, 5, 7))

    def test_documents_hold_no_threshold_severity_or_stored_state(self):
        names = {name for doc in self.keys.values() for name in doc["values"]} | {name for doc in self.keys.values() for name in doc}
        self.assertEqual(names & PRIVATE_NAMES, set())

    def test_each_kind_of_document_has_exactly_its_documented_fields(self):
        fields = {}
        for doc in self.keys.values():
            fields.setdefault(doc["kind"], set()).add(tuple(sorted(doc)))
        self.assertEqual(
            fields,
            {"record": {RECORD_FIELDS}, "monitor": {WINDOW_FIELDS}, "metric": {WINDOW_FIELDS}, "trend": {WINDOW_FIELDS}},
        )


class TrendTests(unittest.TestCase):
    def trend(self, trend, routine=ROUTINE, stored=None, **extra):
        records = {"metrics": [metric_record(**({"trend": trend} if trend is not None else {}), **extra)]}
        metrics = collection("metrics", records, cursor={"metrics": {}}, entries={"queue-depth": {"status": "ok", "reason": None}})
        return compute(collections=collections_for(metrics=metrics), routine=routine, stored=stored)

    def values(self, trend, **kwargs):
        return self.trend(trend, **kwargs)[0]["keys"]["trend:queue-depth"]["values"]

    def test_growth_compounds_the_half_means_to_a_month(self):
        values = self.values(trend_points(10, 20))
        self.assertEqual(
            values,
            {"value": 12, "max_7d": 20, "mean_7d": 20, "max_span": 20, "mean_span": 15, "growth_monthly": 300},
        )

    def test_a_falling_series_has_negative_growth(self):
        self.assertEqual(self.values(trend_points(20, 10))["growth_monthly"], -75)

    def test_the_seven_day_max_covers_the_oldest_of_the_last_seven_local_days(self):
        points = trend_points(10, 10)
        points[-7]["value"] = 40
        self.assertEqual(self.values(points)["max_7d"], 40)

    def test_a_value_eight_days_back_is_outside_the_seven_day_values(self):
        points = trend_points(10, 10)
        points[-8]["value"] = 99
        values = self.values(points)
        self.assertEqual((values["max_7d"], values["max_span"]), (10, 99))

    def test_an_odd_span_splits_at_half_a_span_and_raises_to_30_over_it(self):
        routine = {**ROUTINE, "query_pack": [{**PACK_ENTRY, "trend_days": 7}]}
        expected = features.rounded(((20 / 10) ** (30 / 3.5) - 1) * 100)
        self.assertEqual(self.values(trend_points(10, 20, 7), routine=routine)["growth_monthly"], expected)

    def test_a_first_half_with_fewer_than_two_points_has_no_growth(self):
        points = [point for point in trend_points(10, 20) if point["day"] >= "2026-10-02" or point["day"] == "2026-09-20"]
        self.assertIsNone(self.values(points)["growth_monthly"])

    def test_a_second_half_with_fewer_than_two_points_has_no_growth(self):
        points = [point for point in trend_points(10, 20) if point["day"] <= "2026-10-02"]
        self.assertIsNone(self.values(points)["growth_monthly"])

    def test_a_first_half_mean_of_zero_has_no_growth(self):
        self.assertIsNone(self.values(trend_points(0, 20))["growth_monthly"])

    def test_a_negative_first_half_mean_has_no_growth(self):
        self.assertIsNone(self.values(trend_points(-5, 20))["growth_monthly"])

    def test_a_growth_too_large_for_a_float_has_no_growth(self):
        self.assertIsNone(self.values(trend_points(1, 1e200))["growth_monthly"])

    def test_a_negative_second_half_mean_has_no_growth(self):
        self.assertIsNone(self.values(trend_points(10, -2))["growth_monthly"])

    def test_a_failed_trend_keeps_the_window_value_and_nulls_the_rest(self):
        values = self.values(None, trend_reason="provider error")
        self.assertEqual(values, {"value": 12, **dict.fromkeys(tribe_features.TREND_NAMES)})

    def test_a_failed_trend_is_a_blind_spot_keyed_by_its_trend_document_not_the_entry(self):
        base = self.trend(None, trend_reason="provider error")[1]
        self.assertEqual([spot for spot in base["blind_spots"] if "queue-depth" in spot["key"]], [{"key": "trend:queue-depth", "gap": "provider error"}])

    ZERO = {**ROUTINE, "query_pack": [{**PACK_ENTRY, "empty": "zero"}]}
    NO_DATAPOINTS = {"value": None, "trend_reason": "no datapoints"}

    def spots(self, base):
        return [spot for spot in base["blind_spots"] if "queue-depth" in spot["key"]]

    def test_an_empty_trend_of_a_zero_entry_reads_as_zeros_with_a_null_growth(self):
        values = self.values(None, routine=self.ZERO, **self.NO_DATAPOINTS)
        self.assertEqual(values, {"value": 0, "max_7d": 0, "mean_7d": 0, "max_span": 0, "mean_span": 0, "growth_monthly": None})

    def test_an_empty_trend_of_a_zero_entry_is_no_blind_spot(self):
        found, base = self.trend(None, routine=self.ZERO, **self.NO_DATAPOINTS)[:2]
        self.assertEqual((self.spots(base), found["keys"]["metric:queue-depth"]["values"]["value"]), ([], 0))

    def test_an_empty_trend_of_an_entry_without_the_option_stays_a_blind_spot(self):
        found, base = self.trend(None, **self.NO_DATAPOINTS)[:2]
        self.assertEqual(found["keys"]["trend:queue-depth"]["values"], {"value": None, **dict.fromkeys(tribe_features.TREND_NAMES)})
        self.assertIn({"key": "trend:queue-depth", "gap": "no datapoints"}, base["blind_spots"])

    def test_an_empty_trend_of_an_entry_set_to_gap_stays_a_blind_spot(self):
        routine = {**ROUTINE, "query_pack": [{**PACK_ENTRY, "empty": "gap"}]}
        base = self.trend(None, routine=routine, **self.NO_DATAPOINTS)[1]
        self.assertIn({"key": "trend:queue-depth", "gap": "no datapoints"}, base["blind_spots"])

    def test_a_failed_trend_of_a_zero_entry_stays_a_blind_spot(self):
        found, base = self.trend(None, routine=self.ZERO, value=None, trend_reason="provider error")[:2]
        self.assertEqual(found["keys"]["trend:queue-depth"]["values"], {"value": 0, **dict.fromkeys(tribe_features.TREND_NAMES)})
        self.assertEqual(self.spots(base), [{"key": "trend:queue-depth", "gap": "provider error"}])

    def test_an_empty_read_of_a_zero_entry_after_a_stored_value_writes_zero_to_the_cursor(self):
        stored = make_state()
        stored["cursors"]["observability"]["metrics"]["queue-depth"] = 10
        base = self.trend(None, routine=self.ZERO, stored=stored, **self.NO_DATAPOINTS)[1]
        self.assertEqual(base["cursors"]["observability"]["metrics"]["queue-depth"], 0)

    def test_a_trend_with_points_of_a_zero_entry_reads_its_points(self):
        values = self.values(trend_points(10, 20), routine=self.ZERO)
        self.assertEqual((values["max_span"], values["growth_monthly"]), (20, 300))

    def test_an_entry_without_trend_days_has_no_trend_document(self):
        routine = {**ROUTINE, "query_pack": [{key: value for key, value in PACK_ENTRY.items() if key != "trend_days"}]}
        self.assertNotIn("trend:queue-depth", self.trend(trend_points(10, 20), routine=routine)[0]["keys"])

    def test_a_deferred_entry_has_no_trend_document(self):
        metrics = collection("metrics", {"metrics": []}, cursor={"metrics": {}}, entries={"queue-depth": {"status": "deferred", "reason": "not due"}})
        keys = features_of(collections=collections_for(metrics=metrics))["keys"]
        self.assertEqual([key for key in keys if "queue-depth" in key], [])


class PreviousTests(unittest.TestCase):
    def test_previous_holds_the_stored_warnings_checks_and_retired_titles(self):
        stored = make_state()
        previous = features_of(stored=stored)["previous"]
        self.assertEqual(previous, {"warnings": stored["warnings"], "checks": stored["checks"], "retired": stored["retired"]})

    def test_the_pack_lists_every_entry_key(self):
        self.assertEqual(features_of()["pack"], ["queue-depth"])

    def test_rule_prose_never_reaches_the_features(self):
        raw = features.compact_dump(features_of())
        prose = [*ROUTINE["rules"], PACK_ENTRY["rule"]]
        self.assertEqual([text for text in prose if text.encode() in raw], [])

    def test_rules_hold_the_routine_prose_and_each_entry_rule(self):
        rules = compute()[2]
        self.assertEqual(rules, {"routine": ROUTINE["rules"], "entries": {"queue-depth": PACK_ENTRY["rule"]}})


class DeferredTests(unittest.TestCase):
    def deferred(self, collections=None, **warning):
        stored = make_state(warnings={"queue-depth": make_warning(**warning)})
        return features_of(collections=collections, stored=stored)["deferred"]

    def test_a_warning_whose_sources_and_entry_were_read_is_not_deferred(self):
        self.assertEqual(self.deferred(), [])

    def test_a_warning_citing_an_unread_source_is_deferred(self):
        chat = unread("channels", {"messages": []})
        self.assertEqual(self.deferred(collections_for(channels=chat)), ["queue-depth"])

    def test_an_unread_source_that_the_warning_does_not_cite_defers_nothing(self):
        issues = unread("issues", {"issues": []})
        self.assertEqual(self.deferred(collections_for(issues=issues)), [])

    def test_a_warning_whose_metric_entry_was_deferred_is_deferred(self):
        metrics = collection("metrics", {"metrics": []}, cursor={"metrics": {}}, entries={"queue-depth": {"status": "deferred", "reason": "not due"}})
        self.assertEqual(self.deferred(collections_for(metrics=metrics), cites=[make_warning()["cites"][0]]), ["queue-depth"])

    def test_a_warning_citing_a_feature_of_an_unread_metric_entry_is_deferred(self):
        metrics = unread("metrics", {"metrics": []})
        cites = [{"feature": "trend:queue-depth", "name": "growth_monthly"}]
        self.assertEqual(self.deferred(collections_for(metrics=metrics), cites=cites, metric=None), ["queue-depth"])

    def test_a_warning_whose_metric_entry_left_the_pack_is_deferred(self):
        stored = make_state(warnings={"queue-depth": make_warning(metric="gone-entry", cites=[])})
        self.assertEqual(features_of(stored=stored)["deferred"], ["queue-depth"])

    def test_a_warning_with_no_metric_and_a_read_record_source_is_not_deferred(self):
        self.assertEqual(self.deferred(metric=None, cites=[make_warning()["cites"][0]]), [])

    def test_a_warning_citing_a_feature_of_a_record_of_an_unread_source_is_deferred(self):
        cites = [{"feature": f"record:channels:{CHANNEL_A}:1791990730.002679", "name": "ts"}]
        chat = unread("channels", {"messages": []})
        self.assertEqual(self.deferred(collections_for(channels=chat), cites=cites, metric=None), ["queue-depth"])

    def test_a_warning_citing_a_feature_of_a_record_of_a_read_source_is_not_deferred(self):
        cites = [{"feature": f"record:channels:{CHANNEL_A}:1791990730.002679", "name": "ts"}]
        self.assertEqual(self.deferred(cites=cites, metric=None), [])

    def top_collections(self, status):
        record = {"key": "errors", "value": None, "hourly": [], "groups": [{"group": "eu", "value": 3}]}
        metrics = collection("metrics", {"metrics": [record]}, cursor={"metrics": {}}, entries={"errors": status})
        return collections_for(metrics=metrics)

    def top_deferred(self, status):
        entry = {**PACK_ENTRY, "key": "errors", "read": "top", "top": 5, "aggregator": "sum"}
        del entry["trend_days"]
        stored = make_state(warnings={"queue-depth": make_warning(metric=None, cites=[{"feature": "metric:errors-eu", "name": "value"}])})
        return features_of(collections=self.top_collections(status), stored=stored, routine={**ROUTINE, "query_pack": [entry]})["deferred"]

    def test_a_warning_citing_a_group_of_a_read_top_entry_is_not_deferred(self):
        self.assertEqual(self.top_deferred({"status": "ok", "reason": None}), [])

    def test_a_warning_citing_a_group_of_a_deferred_top_entry_is_deferred(self):
        self.assertEqual(self.top_deferred({"status": "deferred", "reason": "not due"}), ["queue-depth"])

    def test_a_failed_trend_does_not_defer_a_warning_citing_the_window_value(self):
        records = {"metrics": [metric_record(trend=None, trend_reason="provider error")]}
        metrics = collection("metrics", records, cursor={"metrics": {}}, entries={"queue-depth": {"status": "ok", "reason": None}})
        self.assertEqual(self.deferred(collections_for(metrics=metrics)), [])

    def test_the_base_lists_the_same_deferred_keys(self):
        stored = make_state(warnings={"queue-depth": make_warning()})
        chat = unread("channels", {"messages": []})
        self.assertEqual(compute(collections=collections_for(channels=chat), stored=stored)[1]["deferred"], ["queue-depth"])


class EditTests(unittest.TestCase):
    def edits(self, previous, **overrides):
        return features_of(collections=collections_for(**{"previous-digest": previous}), **overrides)["edits"]

    def test_edits_from_a_page_edited_after_it_was_written_merge_statuses_and_ticks(self):
        edits = self.edits(overview(digest_blocks("mitigated", ticked=True)))
        self.assertEqual((edits["after_written"], edits["statuses"], edits["ticked"], edits["unticked"]), (True, {"queue-depth": "mitigated"}, ["ask-export"], []))
        self.assertEqual((edits["page_id"], edits["edited_at"]), (PAGE_ID, "2026-10-15T09:00:00Z"))

    def test_a_page_missing_a_section_gives_no_edits_and_the_previous_digest_blind_spot(self):
        blocks = [item for item in digest_blocks("mitigated", ticked=True) if item["text"] != "Decisions this week"]
        doc, base, _ = compute(collections=collections_for(**{"previous-digest": overview(blocks)}))
        self.assertEqual(doc["edits"], tribe_features.empty_edits(PAGE_ID))
        self.assertIn({"key": "previous-digest", "gap": tribe_features.PREVIOUS_UNREADABLE}, base["blind_spots"])

    def test_a_page_missing_a_section_but_not_edited_since_it_was_written_gives_no_blind_spot(self):
        blocks = [item for item in digest_blocks() if item["text"] != "Decisions this week"]
        previous = overview(blocks, last_edited="2026-10-15T07:53:42Z")
        base = compute(collections=collections_for(**{"previous-digest": previous}))[1]
        self.assertEqual([spot for spot in base["blind_spots"] if spot["key"] == "previous-digest"], [])

    def test_a_page_with_every_section_gives_no_blind_spot(self):
        base = compute(collections=collections_for(**{"previous-digest": overview(digest_blocks("mitigated"))}))[1]
        self.assertEqual([spot for spot in base["blind_spots"] if spot["key"] == "previous-digest"], [])

    def test_a_topic_named_like_a_later_section_does_not_end_the_warnings_section(self):
        edits = self.edits(overview(digest_blocks("mitigated", topic="Sources")))
        self.assertEqual(edits["statuses"], {"queue-depth": "mitigated"})

    def test_a_to_do_text_with_trailing_spaces_still_finds_its_key(self):
        blocks = digest_blocks(ticked=True)
        blocks[-2] = block("list", "Capacity Ask for the export ask-export  ", checked=True)
        self.assertEqual(self.edits(overview(blocks))["ticked"], ["ask-export"])

    def test_a_failed_page_of_the_previous_digest_source_is_reported_once(self):
        failed = collection("previous-digest", {"pages": []}, entries={PAGE_ID: {"status": "failed", "reason": "not found or not shared"}})
        base = compute(collections=collections_for(**{"previous-digest": failed}))[1]
        self.assertEqual([spot for spot in base["blind_spots"] if PAGE_ID in spot["key"] or spot["key"] == "previous-digest"], [{"key": "previous-digest", "gap": tribe_features.PREVIOUS_UNREADABLE}])

    def test_an_unticked_to_do_is_listed_as_unticked(self):
        self.assertEqual(self.edits(overview(digest_blocks()))["unticked"], ["ask-export"])

    def test_a_page_edited_in_the_minute_it_was_written_gives_no_edit(self):
        edits = self.edits(overview(digest_blocks("mitigated", ticked=True), last_edited="2026-10-15T07:53:42Z"))
        self.assertEqual((edits["after_written"], edits["statuses"], edits["ticked"], edits["unticked"]), (False, {}, [], []))

    def test_a_page_edited_before_it_was_written_gives_no_edit(self):
        edits = self.edits(overview(digest_blocks("mitigated"), last_edited="2026-10-15T07:40:00Z"))
        self.assertEqual((edits["after_written"], edits["statuses"]), (False, {}))

    def test_an_edit_that_matches_no_key_is_ignored_and_listed(self):
        blocks = digest_blocks()
        blocks[-2] = block("list", "Capacity Other task other-task", checked=True)
        edits = self.edits(overview(blocks))
        self.assertEqual((edits["ticked"], edits["ignored"]), ([], [{"where": "check 1", "why": "key matches no stored check"}]))

    def test_a_status_outside_the_allowed_values_is_ignored_and_listed(self):
        edits = self.edits(overview(digest_blocks("finished")))
        self.assertEqual((edits["statuses"], [item["why"] for item in edits["ignored"]]), ({}, ["status outside the allowed values"]))

    def test_a_state_without_a_previous_page_has_empty_edits(self):
        stored = make_state()
        stored["run"]["previous_page"] = None
        edits = self.edits(overview(digest_blocks("mitigated")), stored=stored)
        self.assertEqual(edits, tribe_features.empty_edits(None))

    def test_the_rendered_golden_page_round_trips_through_the_collection_blocks(self):
        summary = fixture_json("page_summary.json")
        golden = tick(fixture("page_golden.md"), "Read the worker pool quota").replace("status: in progress<br>", "status: mitigated<br>", 1)
        blocks = notion._markdown_blocks(notion._content_lines(f"<content>\n{golden}</content>"))
        stored = {
            "run": {"previous_page": {"id": PAGE_ID, "written_at": WRITTEN}},
            "warnings": summary["warnings"],
            "checks": summary["checks"],
        }
        previous = collection("previous-digest", {"pages": [page(PAGE_ID, "Digest", blocks, "2026-10-15T09:00:00Z")]})
        edits, gap = tribe_features.previous_edits(SOURCES, {"previous-digest": previous}, stored)
        self.assertEqual((edits["statuses"], edits["ticked"], edits["ignored"], gap), ({"disk-growth": "mitigated"}, ["read-pool-quota"], [], None))
        self.assertIn("trace-latency-step", edits["unticked"])

    def test_an_unreadable_previous_page_is_a_blind_spot_and_leaves_the_stored_values(self):
        previous = unread("previous-digest", {"pages": []}, "provider unreachable")
        doc, base, _ = compute(collections=collections_for(**{"previous-digest": previous}))
        self.assertIn({"key": "previous-digest", "gap": tribe_features.PREVIOUS_UNREADABLE}, base["blind_spots"])
        self.assertEqual((doc["edits"]["statuses"], doc["edits"]["ticked"]), ({}, []))

    def test_a_previous_page_missing_from_a_read_collection_is_a_blind_spot(self):
        base = compute()[1]
        self.assertIn({"key": "previous-digest", "gap": tribe_features.PREVIOUS_UNREADABLE}, base["blind_spots"])

    def test_an_unchanged_previous_page_is_no_blind_spot(self):
        unchanged = collection("previous-digest", {"pages": []}, entries={PAGE_ID: {"status": "deferred", "reason": "unchanged"}})
        base = compute(collections=collections_for(**{"previous-digest": unchanged}))[1]
        self.assertEqual([spot for spot in base["blind_spots"] if spot["key"] == "previous-digest"], [])

    def test_a_first_run_without_a_previous_page_is_no_blind_spot(self):
        stored = make_state()
        stored["run"]["previous_page"] = None
        unread_previous = unread("previous-digest", {"pages": []}, "no previous page")
        base = compute(collections=collections_for(**{"previous-digest": unread_previous}), stored=stored)[1]
        self.assertEqual([spot for spot in base["blind_spots"] if spot["key"] == "previous-digest"], [])


class BaseTests(unittest.TestCase):
    def test_sources_list_each_source_with_its_read_flag_and_window(self):
        chat = unread("channels", {"messages": []})
        rows = compute(collections=collections_for(channels=chat))[1]["sources"]
        row = next(item for item in rows if item["source"] == "channels")
        self.assertEqual(row, {"source": "channels", "role": "chat", "read": False, "reason": "provider unreachable", "from_ts": None, "to_ts": None})

    def test_cursors_come_from_the_read_collections_and_leave_unread_ones_out(self):
        chat = unread("channels", {"messages": []})
        cursors = compute(collections=collections_for(channels=chat))[1]["cursors"]
        self.assertEqual(sorted(cursors), ["issues", "observability", "pages"])
        self.assertEqual(cursors["issues"], {"updated": "2026-10-15T09:00:00Z"})

    def test_observability_cursors_fold_in_the_window_value(self):
        self.assertEqual(compute()[1]["cursors"]["observability"]["metrics"], {"queue-depth": 12})

    def test_an_unread_source_is_a_blind_spot_with_its_reason(self):
        chat = unread("channels", {"messages": []})
        self.assertIn({"key": "channels", "gap": "provider unreachable"}, compute(collections=collections_for(channels=chat))[1]["blind_spots"])

    def test_a_failed_entry_of_a_read_source_is_a_blind_spot(self):
        entries = {f"{CHANNEL_A}:{THREAD_TS}": {"status": "failed", "reason": "thread not found"}}
        chat = collection("channels", {"messages": []}, cursor={"ts": {}}, entries=entries)
        self.assertIn({"key": f"{CHANNEL_A}:{THREAD_TS}", "gap": "thread not found"}, compute(collections=collections_for(channels=chat))[1]["blind_spots"])

    def test_models_come_from_the_routine(self):
        self.assertEqual(compute()[1]["models"], {"judge": "model-a"})

    def test_a_known_gap_of_a_read_source_is_retried_on_a_retry_window(self):
        stored = make_state(blind_spots=[{"key": "channels", "gap": "no history", "runs": 3}])
        base = tribe_features.compute(ROUTINE, SOURCES, collections_for(), stored, {**WINDOW, "retry_known_gaps": True}, ZONE)[1]
        self.assertEqual(base["blind_spots_retried"], ["channels"])

    def test_no_known_gap_is_retried_outside_a_retry_window(self):
        stored = make_state(blind_spots=[{"key": "channels", "gap": "no history", "runs": 3}])
        self.assertEqual(compute(stored=stored)[1]["blind_spots_retried"], [])


class DeterminismTests(unittest.TestCase):
    def dump(self, collections):
        return features.compact_dump(features_of(collections=collections))

    def test_the_same_input_gives_byte_identical_features(self):
        self.assertEqual(self.dump(collections_for()), self.dump(collections_for()))

    def test_record_order_in_the_collections_does_not_change_the_features(self):
        reordered = collections_for()
        reordered["channels"]["records"]["messages"].reverse()
        self.assertEqual(self.dump(collections_for()), self.dump(reordered))

    def test_the_features_are_compact_sorted_json_ending_in_a_newline(self):
        raw = self.dump(collections_for())
        self.assertEqual((raw.endswith(b"\n"), raw), (True, features.compact_dump(json.loads(raw))))


class CommandTests(FileCase):
    def setUp(self):
        super().setUp()
        config = make_config()
        for provider in config["providers"].values():
            provider["api"] = {"base_url": "https://api.example.com", "credentials": {"token": "EXAMPLE_TOKEN"}}
        routine = config["routines"]["tribe-digest"]
        routine["sources"]["metrics"] = {"provider": "observability", "kind": "metrics", "scope_filter": ""}
        routine["query_pack"] = [PACK_ENTRY]
        routine["rules"] = ROUTINE["rules"]
        self.config = self.write("config.json", config)
        self.state = self.write("state.json", make_state())
        os.mkdir(self.path("collections"))
        code, _, _ = run_cli("window", "--state", self.state, "--now", NOW, "--tz", TZ, "--out", self.path("window.json"))
        assert code == 0
        self.window = self.read("window.json")

    def write_collections(self, **overrides):
        parts = collections_for(**overrides)
        for name in ("channels", "issues", "pages", "monitors", "metrics"):
            doc = copy.deepcopy(parts[name])
            doc["window"] = {"from_ts": self.window["from_ts"], "to_ts": self.window["to_ts"]}
            doc["provider"] = {"channels": "chat"}.get(name, doc["provider"])
            self.write(os.path.join("collections", f"{name}.json"), doc)

    def raw(self, *names):
        contents = []
        for name in names:
            with open(self.path(name), "rb") as handle:
                contents.append(handle.read())
        return contents

    def features(self, *extra, config=None):
        return run_cli(
            "features", "--config", config or self.config, "--routine", "tribe-digest", "--state", self.state,
            "--window", self.path("window.json"), "--collections", self.path("collections"), "--place", "cloud",
            "--out", self.path("features.json"), "--base-out", self.path("base.json"), "--rules-out", self.path("rules.json"), *extra,
        )

    def test_writes_features_base_and_rules(self):
        self.write_collections()
        code, _, err = self.features()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(sorted(self.read("features.json")), ["authors", "deferred", "edits", "keys", "pack", "previous"])
        self.assertEqual(sorted(self.read("base.json")), ["blind_spots", "blind_spots_retried", "cursors", "daily_metrics_on", "deferred", "models", "sources"])
        self.assertEqual(self.read("rules.json")["routine"], ROUTINE["rules"])

    def test_a_source_with_no_collection_file_is_unread_and_a_blind_spot(self):
        self.write_collections()
        os.remove(self.path(os.path.join("collections", "issues.json")))
        self.features()
        self.assertIn({"key": "issues", "gap": "no collection"}, self.read("base.json")["blind_spots"])

    def test_rerunning_gives_byte_identical_files(self):
        self.write_collections()
        self.features()
        first = self.raw("features.json", "base.json", "rules.json")
        self.features()
        self.assertEqual(first, self.raw("features.json", "base.json", "rules.json"))

    def test_the_features_pass_the_judgment_check_for_a_valid_judgment(self):
        self.write_collections()
        self.features()
        doc = self.read("features.json")
        measured = make_warning(cites=[])
        valid = {
            "warnings": {
                "queue-depth": {
                    **{name: measured[name] for name in tribe_judgment.WARNING_FIELDS if name != "verdict"},
                    "verdict": "open",
                    "evidence": [
                        {"claim": "The queue keeps growing", "cites": [{"feature": "trend:queue-depth", "name": "growth_monthly", "value": 300}]},
                        {"claim": "Users report slowness", "cites": [{"source": "channels", "link": LINK_ROOT}]},
                    ],
                }
            },
            "checks": {},
            "decisions": [],
            "details": {},
            "corrections": [],
            "highlights": [],
        }
        checked = tribe_judgment.checked_judgment(doc, valid)
        self.assertEqual(
            checked["warnings"]["queue-depth"]["cites"],
            [{"feature": "trend:queue-depth", "name": "growth_monthly"}, {"source": "channels", "link": LINK_ROOT}],
        )

    def test_a_cite_of_a_value_the_features_lack_is_rejected_by_the_judgment_check(self):
        self.write_collections()
        self.features()
        doc = self.read("features.json")
        measured = make_warning()
        invalid = {
            "warnings": {"queue-depth": {**{name: measured[name] for name in tribe_judgment.WARNING_FIELDS if name != "verdict"}, "verdict": "open", "evidence": [{"claim": "Growth", "cites": [{"feature": "trend:queue-depth", "name": "growth_monthly", "value": 301}]}]}},
            "checks": {},
            "decisions": [],
            "details": {},
            "corrections": [],
            "highlights": [],
        }
        with self.assertRaises(state.Rejected) as caught:
            tribe_judgment.checked_judgment(doc, invalid)
        self.assertIn("warnings.queue-depth.evidence[0].cites[0].value", str(caught.exception))

    def test_a_watch_routine_exits_2_naming_the_routine(self):
        self.write_collections()
        config = self.read("config.json")
        config["routines"]["tribe-digest"]["engine"] = "watch"
        code, _, err = self.features(config=self.write("watch.json", config))
        self.assertEqual((code, "tribe-digest" in err and "not a tribe routine" in err), (2, True))

    def test_a_collection_of_another_window_exits_2_naming_the_file(self):
        self.write_collections()
        doc = self.read(os.path.join("collections", "channels.json"))
        doc["window"]["from_ts"] -= 1
        self.write(os.path.join("collections", "channels.json"), doc)
        code, _, err = self.features()
        self.assertEqual((code, "channels.json" in err and "window" in err), (2, True))

    def test_a_state_of_another_schema_exits_3(self):
        self.write_collections()
        document = make_state()
        document["schema"] = "tribe-2"
        self.state = self.write("state.json", document)
        code, _, err = self.features()
        self.assertEqual((code, "schema" in err), (3, True))

    def test_a_missing_window_file_exits_2(self):
        self.write_collections()
        os.remove(self.path("window.json"))
        self.assertEqual(self.features()[0], 2)

    def test_missing_flags_exit_2_through_the_parser(self):
        self.assertEqual(run_cli("features", "--routine", "tribe-digest")[0], 2)


class PreviousDigestCursorTest(unittest.TestCase):
    def test_the_previous_digest_source_keeps_no_cursor_in_the_base(self):
        previous = collection("previous-digest", {"pages": []}, cursor={"pages": {PAGE_ID: "2026-10-15T07:51:34.487Z"}})
        base = compute(collections=collections_for(**{"previous-digest": previous}))[1]
        self.assertNotIn("previous-digest", base["cursors"])


if __name__ == "__main__":
    unittest.main()
