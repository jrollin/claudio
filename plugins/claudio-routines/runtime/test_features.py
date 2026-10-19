import unittest
from zoneinfo import ZoneInfo

import features
import state
from evaluate_support import (
    EvaluateCase, FROM_TS, HOUR_0, HOUR_1, KEY, MON, TO_TS, alerts, collections, failed, gauges, make_config, make_item,
    make_state, make_window, metric, metric_entry, metrics_collection, missing, monitor, ok, skipped, source,
    unread_alerts, unread_gauges,
)

from providers.datadog_support import MONITORS, FRESH, event, events_page, run, status

OTHER = str(10**6 + 78)
OTHER_KEY = state.MONITOR_PREFIX + OTHER
LABEL_0 = "2026-06-02T00:00:00+02:00"
LABEL_1 = "2026-06-02T01:00:00+02:00"
DAY_0 = 1780272000


def moment(offset):
    return (FROM_TS + offset) * 1000


def transition(first, last=None, count=1, monitor_id=MON):
    last = first if last is None else last
    return {"monitor": monitor_id, "count": count, "first_ts_ms": (FROM_TS + first) * 1000, "last_ts_ms": (FROM_TS + last) * 1000}


def top_entry(top=3, **extra):
    return metric_entry(read="top", top=top, **extra)


def auto(reason, **item):
    stored = make_item(**item)
    return {"reason": reason, "title": stored["title"], "link": stored["link"], "severity": stored["severity"], "when": stored["when"]}


def group_docs(*names, **entries):
    groups = [{"group": name, "value": 5 - index} for index, name in enumerate(names)]
    return collections(gauges=gauges(metrics=[metric(groups=groups)], **entries))


class FnvTest(unittest.TestCase):
    def test_matches_the_published_vectors(self):
        self.assertEqual([features.fnv1a32(text) for text in ("", "a", "foobar")], ["811c9dc5", "e40c292c", "bf9cf968"])

    def test_hashes_the_utf8_bytes_of_non_ascii_text(self):
        self.assertEqual(features.fnv1a32("é"), "1e9de8c1")


class MonitorValuesTest(EvaluateCase):
    def values(self, **kwargs):
        return self.features(**kwargs)["keys"][KEY]["values"]

    def test_monitor_lists_its_state_and_priority(self):
        docs = collections(alerts=alerts(monitors=[monitor("Warn", priority=2)]))

        values = self.values(docs=docs)

        self.assertEqual((values["state"], values["priority"]), ("Warn", 2))

    def test_monitor_without_priority_has_a_null_one(self):
        self.assertIsNone(self.values()["priority"])

    def test_transitions_come_from_the_aggregate_of_the_monitor(self):
        transitions = [transition(600, 1800, 2), transition(900, 900, 1, OTHER)]

        values = self.values(docs=collections(alerts=alerts(transitions=transitions)))

        self.assertEqual(values["transitions"], 2)
        self.assertEqual((values["first_transition"], values["last_transition"]), ("2026-06-02T00:40:00+02:00", LABEL_1))
        self.assertEqual(values["transitions_per_hour"], 6.0)

    def aggregated(self, events):
        page = events_page(*(event(f"e{number}", timestamp=ts_ms, attributes={"monitor_id": monitor}) for number, (ts_ms, monitor) in enumerate(events)))
        window = {"from_ts": FROM_TS, "to_ts": TO_TS}
        named = len({monitor for ts_ms, monitor in events if FROM_TS * 1000 <= ts_ms <= TO_TS * 1000})
        _, result = run(MONITORS, [], FRESH, page, *(status(404) for _ in range(named)), window=window)
        return result["records"]["transitions"]

    def reference(self, events, monitor_id):
        low, high = FROM_TS * 1000, TO_TS * 1000
        stamps = sorted(ts_ms for ts_ms, monitor in events if monitor == monitor_id and low <= ts_ms <= high)
        hours = (stamps[-1] - stamps[0]) / (state.HOUR * 1000) if stamps else None
        zone = ZoneInfo("Europe/Paris")
        return {
            "transitions": len(stamps),
            "first_transition": features.local_iso(stamps[0] // 1000, zone) if stamps else None,
            "last_transition": features.local_iso(stamps[-1] // 1000, zone) if stamps else None,
            "transitions_per_hour": len(stamps) / hours if len(stamps) >= 2 and hours else None,
        }

    def assert_same_as_the_raw_events(self, events):
        values = self.values(docs=collections(alerts=alerts(transitions=self.aggregated(events))))

        expected = self.reference(events, MON)
        self.assertEqual({field: values[field] for field in expected}, expected)

    def test_values_from_the_aggregate_equal_those_of_the_raw_event_list(self):
        events = [
            (moment(600), MON), (moment(1800), MON), (moment(1800), MON), (moment(900), OTHER), (moment(-7200), MON), (moment(7200), MON),
            (moment(0), MON), (moment(TO_TS - FROM_TS), MON), (moment(-1), MON), (moment(TO_TS - FROM_TS + 1), MON), (moment(4000) + 7, MON),
        ]

        self.assert_same_as_the_raw_events(events)

    def test_values_from_the_aggregate_equal_those_of_a_single_raw_event(self):
        self.assert_same_as_the_raw_events([((FROM_TS + 600) * 1000, MON), ((FROM_TS + 900) * 1000, OTHER)])

    def test_values_from_the_aggregate_equal_those_of_raw_events_at_one_time(self):
        self.assert_same_as_the_raw_events([((FROM_TS + 600) * 1000, MON), ((FROM_TS + 600) * 1000, MON)])

    def test_values_from_the_aggregate_equal_those_of_raw_events_all_outside_the_window(self):
        self.assert_same_as_the_raw_events([((FROM_TS - 60) * 1000, MON), ((TO_TS + 60) * 1000, MON), ((FROM_TS + 60) * 1000, OTHER)])

    def test_no_event_gives_a_null_rate_and_null_times(self):
        values = self.values()

        self.assertEqual(
            (values["transitions"], values["first_transition"], values["last_transition"], values["transitions_per_hour"]),
            (0, None, None, None),
        )

    def test_one_event_gives_a_null_rate(self):
        values = self.values(docs=collections(alerts=alerts(transitions=[transition(600)])))

        self.assertEqual((values["transitions"], values["transitions_per_hour"]), (1, None))

    def test_events_at_the_same_time_give_a_null_rate(self):
        values = self.values(docs=collections(alerts=alerts(transitions=[transition(600, 600, 2)])))

        self.assertEqual((values["transitions"], values["transitions_per_hour"]), (2, None))

    def test_pack_monitor_takes_its_title_and_link_from_the_pack(self):
        key = self.features()["keys"][KEY]

        self.assertEqual((key["kind"], key["entry"], key["source"], key["title"]), ("monitor", KEY, "monitors", "API monitor"))

    def test_pack_monitor_state_outside_the_allow_list_fails_its_entry(self):
        base = self.base(docs=collections(alerts=alerts(monitors=[monitor("Weird")])))

        self.assertEqual(base["blind_spots"], [{"key": KEY, "gap": "monitor state not recognised: Weird"}])
        self.assertEqual(base["deferred"], [KEY])

    def test_unrecognised_state_in_the_gap_is_cleaned_of_mentions(self):
        base = self.base(docs=collections(alerts=alerts(monitors=[monitor("Wei@rd <b>")])))

        self.assertEqual(base["blind_spots"], [{"key": KEY, "gap": "monitor state not recognised: Wei rd  b "}])

    def test_pack_monitor_missing_and_untracked_is_a_blind_spot_without_auto_key(self):
        docs = collections(alerts=alerts(monitors=[], entries={KEY: missing()}))

        base, found = self.base(docs=docs), self.features(docs=docs, tag="2")

        self.assertEqual(base["blind_spots"], [{"key": KEY, "gap": "not found"}])
        self.assertEqual((found["auto"], KEY in found["keys"]), ({}, False))

    def test_tracked_pack_monitor_missing_becomes_an_auto_key_without_blind_spot(self):
        docs = collections(alerts=alerts(monitors=[], entries={KEY: missing()}))

        base = self.base(stored=make_state(items={KEY: make_item()}), docs=docs)
        found = self.features(stored=make_state(items={KEY: make_item()}), docs=docs, tag="2")

        self.assertEqual((found["auto"], base["blind_spots"], base["deferred"]), ({KEY: auto("not found")}, [], []))

    def test_auto_key_takes_its_title_link_severity_and_when_from_the_stored_item(self):
        docs = collections(alerts=alerts(monitors=[], entries={KEY: missing()}))
        item = make_item("High", "now", title="Disk full", link="https://example.test/full")

        found = self.features(stored=make_state(items={KEY: item}), docs=docs)

        self.assertEqual(
            found["auto"][KEY],
            {"reason": "not found", "title": "Disk full", "link": "https://example.test/full", "severity": "High", "when": "now"},
        )

    def test_tracked_key_shows_its_stored_anchors(self):
        item = make_item("High", "now", risk="Outage", runs_under_threshold=1)

        tracked = self.features(stored=make_state(items={KEY: item}))["keys"][KEY]["tracked"]

        self.assertEqual(
            tracked,
            {"severity": "High", "when": "now", "since": "2026-05-30T08:00:00Z", "runs_under_threshold": 1, "has_analysis": True},
        )

    def test_tracked_key_without_analysis_reports_no_analysis(self):
        tracked = self.features(stored=make_state(items={KEY: make_item()}))["keys"][KEY]["tracked"]

        self.assertFalse(tracked["has_analysis"])

    def test_transitions_at_the_window_bounds_keep_their_first_and_last_times(self):
        transitions = [transition(0, TO_TS - FROM_TS, 2)]

        values = self.values(docs=collections(alerts=alerts(transitions=transitions)))

        self.assertEqual(values["transitions"], 2)
        self.assertEqual((values["first_transition"], values["last_transition"]), ("2026-06-02T00:30:00+02:00", "2026-06-02T01:30:00+02:00"))

    def test_untracked_key_has_null_tracked(self):
        self.assertIsNone(self.features()["keys"][KEY]["tracked"])


class DiscoveryTest(EvaluateCase):
    def discovered(self, *monitors, **extra):
        return collections(alerts=alerts(discovered=[dict(found, priority=None) for found in monitors], **extra))

    def test_discovered_monitor_is_featured_under_its_key_with_no_entry(self):
        key = self.features(docs=self.discovered(monitor("Alert", OTHER)))["keys"][OTHER_KEY]

        self.assertEqual((key["kind"], key["entry"], key["source"], key["link"]), ("monitor", None, "monitors", "https://example.test/mon"))

    def test_discovered_name_is_cleaned_of_control_characters_and_mentions(self):
        name = "Bad @team <b>\nname"

        key = self.features(docs=self.discovered(monitor("Alert", OTHER, name=name)))["keys"][OTHER_KEY]

        self.assertEqual(key["title"], "Bad  team  b  name")

    def test_discovered_name_is_cleaned_of_separators_bidirectional_overrides_and_zero_width_characters(self):
        name = "Bad\u2028name\u202eend\u200bhere"

        key = self.features(docs=self.discovered(monitor("Alert", OTHER, name=name)))["keys"][OTHER_KEY]

        self.assertEqual(key["title"], "Bad name end here")

    def test_discovered_name_is_normalised_before_mentions_are_replaced(self):
        name = "\uff20team \uff1cb\uff1e \ufb01x"

        key = self.features(docs=self.discovered(monitor("Alert", OTHER, name=name)))["keys"][OTHER_KEY]

        self.assertEqual(key["title"], " team  b  fix")

    def test_discovered_name_is_cut_to_300_characters(self):
        key = self.features(docs=self.discovered(monitor("Alert", OTHER, name="n" * 400)))["keys"][OTHER_KEY]

        self.assertEqual(len(key["title"]), 300)

    def test_discovered_monitor_in_the_ok_state_gets_no_key_and_no_blind_spot(self):
        docs = self.discovered(monitor("OK", OTHER))

        base, keys = self.base(docs=docs), self.keys(docs=docs, tag="2")

        self.assertEqual((keys, base["blind_spots"]), (["cpu", KEY], []))

    def test_discovered_monitor_in_the_ok_state_named_by_events_of_the_window_gets_a_key_with_its_transitions(self):
        docs = self.discovered(monitor("OK", OTHER), transitions=[transition(60, 120, 2, OTHER)])

        values = self.features(docs=docs)["keys"][OTHER_KEY]["values"]

        self.assertEqual((values["state"], values["transitions"]), ("OK", 2))

    def test_discovered_monitor_in_the_ok_state_without_a_transition_gets_no_key(self):
        docs = self.discovered(monitor("OK", OTHER), transitions=[transition(60)])

        self.assertNotIn(OTHER_KEY, self.features(docs=docs)["keys"])

    def test_event_named_ok_monitor_adds_no_blind_spot(self):
        docs = self.discovered(monitor("OK", OTHER), transitions=[transition(60, 60, 1, OTHER)])

        self.assertEqual(self.base(docs=docs)["blind_spots"], [])

    def test_event_monitors_beyond_the_cap_are_the_blind_spot_of_the_source(self):
        docs = self.discovered(monitor("Alert", OTHER), discovery={"read": True, "reason": None, "event_monitors_capped": True})

        self.assertEqual(self.base(docs=docs)["blind_spots"], [{"key": "alerts", "gap": "event monitors capped at 50"}])

    def test_event_monitors_cap_joins_the_other_parts_of_the_blind_spot_in_order(self):
        discovery = {"read": False, "reason": "page cap", "event_monitors_capped": True}
        docs = self.discovered(monitor("Weird", OTHER), *(monitor("Alert", str(number)) for number in range(1, 102)), discovery=discovery)

        gap = self.base(docs=docs)["blind_spots"][0]["gap"]

        self.assertEqual(
            gap, f"discovery incomplete; event monitors capped at 50; discovery capped at 100 monitors; monitor state not recognised: {OTHER}"
        )

    def test_event_monitors_cap_flag_left_false_adds_no_blind_spot(self):
        docs = self.discovered(monitor("Alert", OTHER), discovery={"read": True, "reason": None, "event_monitors_capped": False})

        self.assertEqual(self.base(docs=docs)["blind_spots"], [])

    def test_tracked_monitor_in_the_ok_state_found_by_discovery_is_still_featured(self):
        stored = make_state(items={OTHER_KEY: make_item()})
        docs = collections(alerts=alerts(discovered=[monitor("OK", OTHER)], entries={KEY: ok(), OTHER_KEY: ok()}))

        key = self.features(stored=stored, docs=docs)["keys"][OTHER_KEY]

        self.assertEqual(key["values"]["state"], "OK")

    def test_monitor_found_by_id_and_by_discovery_is_featured_once_under_the_pack_entry(self):
        keys = self.features(docs=self.discovered(monitor()))["keys"]

        self.assertEqual((sorted(keys), keys[KEY]["entry"]), (["cpu", KEY], KEY))

    def test_discovered_monitor_with_an_unrecognised_state_is_left_out_and_named_on_the_source(self):
        docs = self.discovered(monitor("Weird", OTHER))

        base, keys = self.base(docs=docs), self.keys(docs=docs, tag="2")

        self.assertEqual(keys, ["cpu", KEY])
        self.assertEqual(base["blind_spots"], [{"key": "alerts", "gap": f"monitor state not recognised: {OTHER}"}])

    def test_incomplete_discovery_is_a_blind_spot_of_the_source_and_still_features_what_it_found(self):
        docs = self.discovered(monitor("Alert", OTHER), discovery={"read": False, "reason": "page cap"})

        base, keys = self.base(docs=docs), self.keys(docs=docs, tag="2")

        self.assertEqual(base["blind_spots"], [{"key": "alerts", "gap": "discovery incomplete"}])
        self.assertEqual((keys, base["sources"]["monitors"]["read"]), (["cpu", KEY, OTHER_KEY], True))

    def test_discovery_and_unrecognised_states_share_one_blind_spot_of_the_source(self):
        docs = self.discovered(monitor("Weird", OTHER), discovery={"read": False, "reason": "page cap"})

        base = self.base(docs=docs)

        self.assertEqual(base["blind_spots"], [{"key": "alerts", "gap": f"discovery incomplete; monitor state not recognised: {OTHER}"}])

    def test_blind_spot_keys_stay_unique_when_a_source_has_several_gaps(self):
        docs = self.discovered(monitor("Weird", OTHER), discovery={"read": False, "reason": "page cap"})
        docs["gauges"] = gauges(entries={"cpu": failed("HTTP 400 POST /query")})

        keys = [spot["key"] for spot in self.base(docs=docs)["blind_spots"]]

        self.assertEqual(keys, ["alerts", "cpu"])

    def test_blind_spot_of_a_source_is_cut_to_300_characters(self):
        weird = [monitor("Weird", str(2 * 10**6 + index)) for index in range(60)]
        docs = self.discovered(*weird, discovery={"read": False, "reason": "page cap"})

        gap = self.base(docs=docs)["blind_spots"][0]["gap"]

        self.assertEqual((len(gap), gap.startswith("discovery incomplete; monitor state not recognised: ")), (300, True))

    def test_discovered_keys_are_capped_at_the_100_lowest_ids(self):
        docs = self.discovered(*(monitor("Alert", str(number)) for number in range(1, 121)))

        keys = [key for key in self.keys(docs=docs) if key != "cpu"]

        self.assertEqual(sorted(keys), sorted([KEY, *(state.MONITOR_PREFIX + str(number) for number in range(1, 101))]))

    def test_discovery_beyond_the_cap_is_the_blind_spot_of_the_source(self):
        docs = self.discovered(*(monitor("Alert", str(number)) for number in range(1, 102)))

        self.assertEqual(self.base(docs=docs)["blind_spots"], [{"key": "alerts", "gap": "discovery capped at 100 monitors"}])

    def test_discovery_at_the_cap_adds_no_blind_spot(self):
        docs = self.discovered(*(monitor("Alert", str(number)) for number in range(1, 101)))

        self.assertEqual(self.base(docs=docs)["blind_spots"], [])

    def test_ok_monitors_do_not_count_toward_the_cap(self):
        docs = self.discovered(*(monitor("OK", str(number)) for number in range(1, 150)), monitor("Alert", OTHER))

        base, keys = self.base(docs=docs), self.keys(docs=docs, tag="2")

        self.assertEqual((OTHER_KEY in keys, base["blind_spots"]), (True, []))

    def test_cap_joins_the_other_parts_of_the_blind_spot_before_the_unrecognised_states(self):
        weird = monitor("Weird", OTHER)
        docs = self.discovered(weird, *(monitor("Alert", str(number)) for number in range(1, 102)), discovery={"read": False, "reason": "page cap"})

        gap = self.base(docs=docs)["blind_spots"][0]["gap"]

        self.assertEqual(gap, f"discovery incomplete; discovery capped at 100 monitors; monitor state not recognised: {OTHER}")

    def test_missing_monitors_collection_is_a_blind_spot_of_the_source_without_a_discovery_lookup(self):
        docs = collections()
        del docs["alerts"]

        base = self.base(docs=docs)

        self.assertEqual((base["blind_spots"], base["sources"]["monitors"]["read"]), ([{"key": "alerts", "gap": "no collection"}], False))

    def test_complete_discovery_adds_no_blind_spot(self):
        docs = self.discovered(monitor("Alert", OTHER), discovery={"read": True, "reason": None})

        self.assertEqual(self.base(docs=docs)["blind_spots"], [])

    def test_tracked_monitor_outside_the_pack_is_read_by_id_and_featured(self):
        stored = make_state(items={OTHER_KEY: make_item()})
        docs = collections(alerts=alerts(monitors=[monitor(), monitor("Warn", OTHER)], entries={KEY: ok(), OTHER_KEY: ok()}))

        key = self.features(stored=stored, docs=docs)["keys"][OTHER_KEY]

        self.assertEqual((key["entry"], key["values"]["state"], key["tracked"]["severity"]), (None, "Warn", "Low"))

    def test_state_key_with_the_monitor_prefix_and_no_numeric_id_is_deferred_with_a_blind_spot(self):
        stored = make_state(items={"monitor-abc": make_item()})

        found, base = self.features(stored=stored), self.base(stored=stored, tag="2")

        self.assertEqual("monitor-abc" in found["keys"], False)
        self.assertEqual((base["blind_spots"], base["deferred"]), ([{"key": "monitor-abc", "gap": "not a monitor id"}], ["monitor-abc"]))

    def test_state_key_with_the_monitor_prefix_and_no_numeric_id_gives_no_blind_spot_while_monitors_are_unread(self):
        stored = make_state(items={"monitor-abc": make_item()})

        base = self.base(stored=stored, docs=collections(alerts=unread_alerts()))

        self.assertEqual([spot["key"] for spot in base["blind_spots"]], ["alerts"])

    def test_tracked_monitor_outside_the_pack_that_is_not_found_becomes_an_auto_key(self):
        stored = make_state(items={OTHER_KEY: make_item()})
        docs = collections(alerts=alerts(entries={KEY: ok(), OTHER_KEY: missing()}))

        self.assertEqual(self.features(stored=stored, docs=docs)["auto"], {OTHER_KEY: auto("not found")})

    def test_tracked_monitor_outside_the_pack_with_a_failed_read_is_deferred(self):
        stored = make_state(items={OTHER_KEY: make_item()})
        docs = collections(alerts=alerts(entries={KEY: ok(), OTHER_KEY: failed("HTTP 500 GET /monitor")}))

        base = self.base(stored=stored, docs=docs)

        self.assertEqual((base["deferred"], base["blind_spots"]), ([OTHER_KEY], [{"key": OTHER_KEY, "gap": "HTTP 500 GET /monitor"}]))


class MetricValuesTest(EvaluateCase):
    def values(self, record, entry=None, **kwargs):
        config = make_config(pack=[entry or metric_entry()])
        docs = collections(gauges=gauges(metrics=[record]))
        return self.features(config=config, docs=docs, **kwargs)["keys"]["cpu"]["values"]

    def test_scalar_metric_compares_with_the_stored_cursor_value(self):
        self.assertEqual(
            self.values(metric(value=90)),
            {
                "value": 90, "window_max": 90, "window_max_at": None, "latest": 90, "previous": 10, "change": 80,
                "change_percent": 800.0,
            },
        )

    def test_no_stored_value_gives_null_previous_change_and_percent(self):
        values = self.values(metric(value=90), stored=make_state(metrics={}))

        self.assertEqual((values["previous"], values["change"], values["change_percent"]), (None, None, None))

    def test_stored_value_of_zero_gives_a_null_percent_and_a_defined_change(self):
        values = self.values(metric(value=90), stored=make_state(metrics={"cpu": 0}))

        self.assertEqual((values["change"], values["change_percent"]), (90, None))

    def test_floats_are_rounded_to_4_significant_digits(self):
        values = self.values(metric(value=1234.5678), stored=make_state(metrics={"cpu": 0.123456}))

        self.assertEqual((values["value"], values["previous"]), (1235.0, 0.1235))

    def test_features_carry_no_threshold_rule_or_pack_severity(self):
        key = self.features()["keys"]["cpu"]

        self.assertEqual(sorted(key), ["entry", "kind", "link", "source", "title", "tracked", "values"])

    def test_metric_entry_not_found_is_a_deferred_blind_spot(self):
        base = self.base(docs=collections(gauges=gauges(metrics=[], entries={"cpu": missing()})))

        self.assertEqual((base["blind_spots"], base["deferred"]), ([{"key": "cpu", "gap": "not found"}], ["cpu"]))

    def test_metric_entry_is_a_metric_key_of_its_entry(self):
        key = self.features()["keys"]["cpu"]

        self.assertEqual((key["kind"], key["entry"], key["source"], key["title"]), ("metric", "cpu", "metrics", "Metric cpu"))


class EmptyReadTest(EvaluateCase):
    GAP = [{"key": "cpu", "gap": "no datapoints"}]
    TRACKED = make_state(items={"cpu-gone": make_item()})

    def read(self, entry, metrics, entries=None, stored=None):
        config = make_config(pack=[entry])
        docs = collections(gauges=gauges(metrics=metrics, **({} if entries is None else {"entries": entries})))
        stored = make_state() if stored is None else stored
        return self.features(config=config, docs=docs, stored=stored), self.base(config=config, docs=docs, stored=stored)

    def test_a_scalar_entry_reads_an_empty_value_as_zero_without_a_blind_spot(self):
        found, base = self.read(metric_entry(empty="zero"), [metric(value=None)])

        self.assertEqual((found["keys"]["cpu"]["values"]["value"], base["blind_spots"], base["deferred"]), (0, [], []))

    def test_a_zero_scalar_compares_with_the_stored_cursor_value(self):
        values = self.read(metric_entry(empty="zero"), [metric(value=None)])[0]["keys"]["cpu"]["values"]

        self.assertEqual((values["latest"], values["previous"], values["change"], values["change_percent"]), (0, 10, -10, -100.0))

    def test_a_zero_read_after_a_stored_value_writes_zero_to_the_cursor_and_the_next_run_compares_with_it(self):
        entry = metric_entry(empty="zero")
        cursors = self.read(entry, [metric(value=None)], stored=make_state(metrics={"cpu": 10}))[1]["cursors"]["metrics"]
        values = self.read(entry, [metric(value=None)], stored=make_state(metrics=cursors))[0]["keys"]["cpu"]["values"]

        self.assertEqual((cursors, values["previous"], values["change"]), ({"cpu": 0}, 0, 0))

    def test_a_scalar_entry_with_a_value_keeps_it_whatever_empty_says(self):
        found, base = self.read(metric_entry(empty="zero"), [metric(value=90)])

        self.assertEqual((found["keys"]["cpu"]["values"]["value"], base["blind_spots"]), (90, []))

    def test_a_scalar_entry_without_the_option_keeps_an_empty_value_as_a_blind_spot(self):
        found, base = self.read(metric_entry(), [metric(value=None)])

        self.assertEqual((base["blind_spots"], base["deferred"], "cpu" in found["keys"]), (self.GAP, ["cpu"], False))

    def test_a_scalar_entry_with_gap_keeps_an_empty_value_as_a_blind_spot(self):
        base = self.read(metric_entry(empty="gap"), [metric(value=None)])[1]

        self.assertEqual(base["blind_spots"], self.GAP)

    def test_a_zero_scalar_entry_without_a_record_is_a_blind_spot(self):
        base = self.read(metric_entry(empty="zero"), [])[1]

        self.assertEqual(base["blind_spots"], self.GAP)

    def test_a_zero_scalar_entry_that_failed_is_a_blind_spot_with_the_failure(self):
        found, base = self.read(metric_entry(empty="zero"), [], entries={"cpu": failed("HTTP 400 POST /query")})

        self.assertEqual((base["blind_spots"], "cpu" in found["keys"]), ([{"key": "cpu", "gap": "HTTP 400 POST /query"}], False))

    def test_a_zero_scalar_entry_not_found_is_a_blind_spot(self):
        base = self.read(metric_entry(empty="zero"), [], entries={"cpu": missing()})[1]

        self.assertEqual(base["blind_spots"], [{"key": "cpu", "gap": "not found"}])

    def test_a_zero_top_entry_reads_no_group_without_a_blind_spot(self):
        found, base = self.read(top_entry(empty="zero"), [metric(groups=[])], stored=self.TRACKED)

        self.assertEqual((base["blind_spots"], base["deferred"], sorted(found["keys"])), ([], [], []))

    def test_a_zero_top_entry_resolves_its_tracked_groups_as_missing(self):
        found = self.read(top_entry(empty="zero"), [metric(groups=[])], stored=self.TRACKED)[0]

        self.assertEqual(found["auto"], {"cpu-gone": auto("group missing")})

    def test_a_top_entry_without_the_option_keeps_no_group_as_a_blind_spot(self):
        base = self.read(top_entry(), [metric(groups=[])], stored=self.TRACKED)[1]

        self.assertEqual((base["blind_spots"], base["deferred"]), (self.GAP, ["cpu", "cpu-gone"]))

    def test_a_zero_top_entry_that_failed_is_a_blind_spot_with_the_failure(self):
        base = self.read(top_entry(empty="zero"), [], entries={"cpu": failed("HTTP 400 POST /query")})[1]

        self.assertEqual(base["blind_spots"], [{"key": "cpu", "gap": "HTTP 400 POST /query"}])

    def test_a_zero_top_entry_resolves_a_tracked_entry_key_as_group_missing(self):
        stored = make_state(items={"cpu": make_item()})
        found = self.read(top_entry(empty="zero"), [metric(groups=[])], stored=stored)[0]

        self.assertEqual(found["auto"], {"cpu": auto("group missing")})

    def test_a_top_entry_with_groups_still_marks_the_tracked_entry_key_as_replaced_by_groups(self):
        stored = make_state(items={"cpu": make_item()})
        found = self.read(top_entry(empty="zero"), [metric(groups=[{"group": "a", "value": 3}])], stored=stored)[0]

        self.assertEqual(found["auto"], {"cpu": auto("replaced by groups")})

    def test_a_zero_top_entry_without_a_record_is_a_blind_spot(self):
        found, base = self.read(top_entry(empty="zero"), [], stored=self.TRACKED)

        self.assertEqual((base["blind_spots"], base["deferred"], found["auto"]), (self.GAP, ["cpu", "cpu-gone"], {}))

    def test_a_zero_top_entry_not_found_is_a_blind_spot(self):
        found, base = self.read(top_entry(empty="zero"), [], entries={"cpu": missing()}, stored=self.TRACKED)

        self.assertEqual((base["blind_spots"], found["auto"]), ([{"key": "cpu", "gap": "not found"}], {}))

    def test_a_zero_top_entry_with_groups_keeps_them(self):
        found = self.read(top_entry(empty="zero"), [metric(groups=[{"group": "a", "value": 3}])])[0]

        self.assertEqual(sorted(found["keys"]), ["cpu-a"])


class HourlyTest(EvaluateCase):
    HOURLY = [{"ts": HOUR_0, "value": 70}, {"ts": HOUR_1, "value": 85}]

    def key(self, hourly=None, **extra):
        config = make_config(pack=[metric_entry(read="hourly", **extra)])
        docs = collections(gauges=gauges(metrics=[metric(value=85, hourly=self.HOURLY if hourly is None else hourly)]))
        found = self.features(config=config, docs=docs)
        return found, found["keys"]["cpu"]

    def test_bucket_labels_are_local_iso_times_with_date_and_offset(self):
        found, _ = self.key()

        self.assertEqual(found["bucket_labels"], [LABEL_0, LABEL_1])

    def test_buckets_align_with_the_labels(self):
        _, key = self.key()

        self.assertEqual((key["buckets"], key["excluded"]), ([70, 85], []))

    def test_missing_hour_is_a_null_bucket(self):
        _, key = self.key(hourly=[{"ts": HOUR_1, "value": 85}])

        self.assertEqual(key["buckets"], [None, 85])

    def test_value_is_the_highest_bucket_with_its_label_and_the_latest_is_the_last(self):
        _, key = self.key()

        values = key["values"]
        self.assertEqual((values["value"], values["window_max"], values["window_max_at"], values["latest"]), (85, 85, LABEL_1, 85))

    def test_excluded_hours_are_marked_and_skipped_by_value_and_window_max(self):
        _, key = self.key(excluded_hours=[1])

        values = key["values"]
        self.assertEqual(key["excluded"], [1])
        self.assertEqual((values["value"], values["window_max"], values["window_max_at"], values["latest"]), (70, 70, LABEL_0, 85))

    def test_every_bucket_excluded_gives_null_value_and_window_max(self):
        _, key = self.key(excluded_hours=[0, 1])

        self.assertEqual((key["values"]["value"], key["values"]["window_max"]), (None, None))

    def test_datapoints_outside_the_window_hours_are_ignored(self):
        outside = [{"ts": HOUR_0 - 3600, "value": 999}, {"ts": HOUR_1 + 3600, "value": 999}]

        _, key = self.key(hourly=[outside[0], *self.HOURLY, outside[1]])

        self.assertEqual((key["buckets"], key["values"]["value"]), ([70, 85], 85))

    def test_hourly_without_any_point_is_a_no_datapoints_gap(self):
        config = make_config(pack=[metric_entry(read="hourly")])

        base = self.base(config=config, docs=collections(gauges=gauges(metrics=[metric(value=None)])))

        self.assertEqual(base["blind_spots"], [{"key": "cpu", "gap": "no datapoints"}])


class CursorValueTest(EvaluateCase):
    SPIKE = [{"ts": HOUR_0, "value": 70}, {"ts": HOUR_1, "value": 400}]

    def cursor(self, excluded_hours, **kwargs):
        config = make_config(pack=[metric_entry(read="hourly", excluded_hours=excluded_hours)])
        docs = collections(gauges=gauges(metrics=[metric(value=400, hourly=self.SPIKE)], cursor={"metrics": {"cpu": 400}}))
        return self.base(config=config, docs=docs, **kwargs)["cursors"]["metrics"]

    def test_hourly_cursor_holds_the_value_that_skips_excluded_hours(self):
        self.assertEqual(self.cursor([1]), {"cpu": 70})

    def test_hourly_cursor_keeps_the_stored_value_when_every_bucket_is_excluded(self):
        self.assertEqual(self.cursor([0, 1]), {"cpu": 10})

    def test_hourly_cursor_drops_the_key_when_every_bucket_is_excluded_and_none_is_stored(self):
        self.assertEqual(self.cursor([0, 1], stored=make_state(metrics={})), {})


class HourlyLookbackTest(EvaluateCase):
    DAY = DAY_0

    def key(self, *values):
        daily = [{"ts": self.DAY + index * 86400, "value": value} for index, value in enumerate(values)]
        entry = metric_entry(read="hourly", schedule="daily", lookback_days=len(values))
        docs = collections(gauges=gauges(metrics=[metric(value=None, hourly=[], daily=daily)]))
        return self.features(config=make_config(pack=[entry]), docs=docs)["keys"]["cpu"]

    def test_daily_buckets_replace_the_hourly_buckets(self):
        key = self.key(3, 9, 5)

        self.assertEqual((sorted(key), len(key["days"])), (["days", "entry", "kind", "link", "source", "title", "tracked", "values"], 3))

    def test_value_is_the_largest_daily_value_with_its_day_and_the_latest_is_the_last_day(self):
        values = self.key(3, 9, 5)["values"]

        self.assertEqual((values["value"], values["window_max"], values["window_max_at"], values["latest"]), (9, 9, "2026-06-02", 5))

    def test_partial_last_day_counts_in_the_largest_value(self):
        values = self.key(3, 4, 9)["values"]

        self.assertEqual((values["value"], values["window_max_at"], values["latest"]), (9, "2026-06-03", 9))

    def test_latest_is_the_last_day_with_a_value(self):
        values = self.key(3, 4, None)["values"]

        self.assertEqual((values["value"], values["latest"]), (4, 4))

    def test_days_without_any_value_are_a_no_datapoints_gap(self):
        entry = metric_entry(read="hourly", schedule="daily", lookback_days=2)
        daily = [{"ts": self.DAY, "value": None}, {"ts": self.DAY + 86400, "value": None}]
        docs = collections(gauges=gauges(metrics=[metric(value=None, hourly=[], daily=daily)]))

        base = self.base(config=make_config(pack=[entry]), docs=docs)

        self.assertEqual(base["blind_spots"], [{"key": "cpu", "gap": "no datapoints"}])


class LookbackTest(EvaluateCase):
    DAILY = [
        {"ts": DAY_0 + 86400, "value": 4},
        {"ts": DAY_0, "value": 3},
        {"ts": DAY_0 + 2 * 86400, "value": None},
    ]

    def days(self):
        entry = metric_entry(schedule="daily", lookback_days=3)
        docs = collections(gauges=gauges(metrics=[metric(value=5, daily=self.DAILY)]))
        return self.features(config=make_config(pack=[entry]), docs=docs)["keys"]["cpu"]["days"]

    def test_days_are_labelled_with_their_utc_date_in_order(self):
        self.assertEqual([day["label"] for day in self.days()], ["2026-06-01", "2026-06-02", "2026-06-03"])

    def test_only_the_last_day_is_marked_partial(self):
        self.assertEqual([day.get("partial") for day in self.days()], [None, None, True])

    def test_entry_without_lookback_has_no_days(self):
        docs = collections(gauges=gauges(metrics=[metric(value=5, daily=self.DAILY)]))

        self.assertNotIn("days", self.features(docs=docs)["keys"]["cpu"])


class GroupKeyTest(unittest.TestCase):
    def keys(self, *names, entry="cpu"):
        return features.group_keys(entry, [{"group": name, "value": 1} for name in names])

    def test_slug_is_lowercased_with_runs_of_other_characters_turned_into_one_dash(self):
        self.assertEqual(self.keys("Alpha,  Queue/1"), ["cpu-alpha-queue-1"])

    def test_slug_is_trimmed(self):
        self.assertEqual(self.keys("--Alpha--"), ["cpu-alpha"])

    def test_empty_slug_takes_the_hash_of_the_raw_text(self):
        self.assertEqual(self.keys("!!!"), ["cpu-" + features.fnv1a32("!!!")])

    def test_slugs_equal_in_the_run_all_take_the_hash_of_their_raw_text(self):
        expected = [f"cpu-a-b-{features.fnv1a32('A b')}", f"cpu-a-b-{features.fnv1a32('a-B')}"]

        self.assertEqual(self.keys("A b", "a-B"), expected)

    def test_slug_cut_to_fit_takes_the_hash_and_the_key_stays_within_120_characters(self):
        key = self.keys("x" * 200)[0]

        self.assertEqual((len(key) <= 120, key.endswith("-" + features.fnv1a32("x" * 200))), (True, True))

    def test_slug_that_fits_exactly_is_kept(self):
        room = 120 - len("cpu-")

        self.assertEqual(self.keys("x" * room), ["cpu-" + "x" * room])

    def test_non_ascii_text_hashes_without_error(self):
        self.assertEqual(self.keys("éè"), ["cpu-" + features.fnv1a32("éè")])


class GroupsTest(EvaluateCase):
    CONFIG = make_config(pack=[top_entry()])

    def found(self, *names, **kwargs):
        return self.features(config=kwargs.pop("config", self.CONFIG), docs=group_docs(*names), **kwargs)

    def test_top_entry_gives_only_its_groups(self):
        self.assertEqual(sorted(self.found("Alpha", "beta")["keys"]), ["cpu-alpha", "cpu-beta"])

    def test_group_key_names_its_entry_and_carries_its_value(self):
        key = self.found("Alpha")["keys"]["cpu-alpha"]

        self.assertEqual((key["kind"], key["entry"], key["title"], key["link"]), ("group", "cpu", "Metric cpu: Alpha", "https://example.test/cpu"))
        self.assertEqual(key["values"]["value"], 5)

    def test_group_title_is_cleaned_of_mentions(self):
        key = self.found("@Alpha")["keys"]["cpu-alpha"]

        self.assertEqual(key["title"], "Metric cpu:  Alpha")

    def test_group_title_is_cleaned_of_separators_and_normalised(self):
        key = self.found("A\u2028\uff20b")["keys"]["cpu-a-b"]

        self.assertEqual(key["title"], "Metric cpu: A  b")

    def test_read_with_fewer_groups_than_the_limit_is_complete(self):
        self.assertTrue(self.found("a", "b")["keys"]["cpu-a"]["values"]["groups_complete"])

    def test_read_that_reaches_the_limit_is_not_complete(self):
        found = self.found("a", "b", "c")

        self.assertFalse(found["keys"]["cpu-a"]["values"]["groups_complete"])

    def test_group_compares_with_its_own_stored_value(self):
        values = self.found("a", stored=make_state(metrics={"cpu-a": 4}))["keys"]["cpu-a"]["values"]

        self.assertEqual((values["previous"], values["change"], values["change_percent"]), (4, 1, 25.0))

    def test_group_key_equal_to_a_source_name_fails_the_entry(self):
        config = make_config(pack=[top_entry()], **{"cpu-a": source("observer", kind="metrics", scope_filter="")})
        docs = group_docs("a")
        docs["cpu-a"] = metrics_collection("cpu-a", [], {}, {})

        base, found = self.base(config=config, docs=docs), self.features(config=config, docs=docs, tag="2")

        self.assertEqual(base["blind_spots"], [{"key": "cpu", "gap": "group key collision: cpu-a"}])
        self.assertEqual((base["deferred"], list(found["keys"])), (["cpu"], []))

    def test_duplicate_group_text_fails_the_entry_naming_the_key(self):
        base = self.base(config=self.CONFIG, docs=group_docs("a", "a"))

        self.assertEqual(base["blind_spots"], [{"key": "cpu", "gap": f"group key collision: cpu-a-{features.fnv1a32('a')}"}])


class CollisionTest(unittest.TestCase):
    def test_equal_group_keys_across_entries_fail_both_entries(self):
        pack = [top_entry(key="cpu"), top_entry(key="cpu-b")]
        reading = features.Reading({"query_pack": pack}, {}, {}, make_state(), make_window(), ZoneInfo("UTC"))
        outcomes = {
            "cpu": features.Outcome(features.GROUPS, groups=[{"group": "b-x", "value": 1}]),
            "cpu-b": features.Outcome(features.GROUPS, groups=[{"group": "x", "value": 1}]),
        }

        resolved, _ = reading.resolve_collisions(outcomes)

        self.assertEqual(resolved, {key: features.Outcome(features.GAP, "group key collision: cpu-b-x") for key in outcomes})

    def test_group_key_equal_to_a_pack_key_fails_the_entry(self):
        # Unreachable from a valid pack; kept for AC-18.8
        pack = [top_entry(key="cpu"), metric_entry(key="cpu-a")]
        reading = features.Reading({"query_pack": pack}, {}, {}, make_state(), make_window(), ZoneInfo("UTC"))
        outcomes = {"cpu": features.Outcome(features.GROUPS, groups=[{"group": "a", "value": 1}])}

        resolved, _ = reading.resolve_collisions(outcomes)

        self.assertEqual(resolved, {"cpu": features.Outcome(features.GAP, "group key collision: cpu-a")})

    def test_entries_without_a_collision_keep_their_groups(self):
        reading = features.Reading({"query_pack": [top_entry()]}, {}, {}, make_state(), make_window(), ZoneInfo("UTC"))
        outcomes = {"cpu": features.Outcome(features.GROUPS, groups=[{"group": "a", "value": 1}])}

        resolved, named = reading.resolve_collisions(outcomes)

        self.assertEqual((resolved, named), (outcomes, {"cpu": ["cpu-a"]}))


class TopEntryLifecycleTest(EvaluateCase):
    CONFIG = make_config(pack=[top_entry(top=2)])

    def run_top(self, names, items, entries=None):
        docs = collections(gauges=gauges(metrics=[metric(groups=[{"group": name, "value": 3} for name in names])], **({} if entries is None else {"entries": entries})))
        return docs, make_state(items=items)

    def test_tracked_group_missing_from_a_complete_read_becomes_an_auto_key(self):
        docs, stored = self.run_top(["a"], {"cpu-gone": make_item()})

        found, base = self.features(config=self.CONFIG, docs=docs, stored=stored), self.base(config=self.CONFIG, docs=docs, stored=stored, tag="2")

        self.assertEqual((found["auto"], base["deferred"], base["blind_spots"]), ({"cpu-gone": auto("group missing")}, [], []))

    def test_tracked_group_missing_from_a_capped_read_is_deferred_with_one_blind_spot_for_the_entry(self):
        docs, stored = self.run_top(["a", "b"], {"cpu-gone": make_item(), "cpu-lost": make_item()})

        base, found = self.base(config=self.CONFIG, docs=docs, stored=stored), self.features(config=self.CONFIG, docs=docs, stored=stored, tag="2")

        self.assertEqual(base["deferred"], ["cpu-gone", "cpu-lost"])
        self.assertEqual(base["blind_spots"], [{"key": "cpu", "gap": "outside the top 2"}])
        self.assertEqual(found["auto"], {})

    def test_tracked_group_present_in_a_capped_read_is_featured_not_deferred(self):
        docs, stored = self.run_top(["a", "b"], {"cpu-a": make_item()})

        base = self.base(config=self.CONFIG, docs=docs, stored=stored)

        self.assertEqual((base["deferred"], base["blind_spots"]), ([], []))

    def test_tracked_entry_key_becomes_the_auto_key_replaced_by_groups(self):
        docs, stored = self.run_top(["a"], {"cpu": make_item()})

        found, base = self.features(config=self.CONFIG, docs=docs, stored=stored), self.base(config=self.CONFIG, docs=docs, stored=stored, tag="2")

        self.assertEqual((found["auto"], base["deferred"]), ({"cpu": auto("replaced by groups")}, []))

    def test_tracked_group_keys_of_a_deferred_top_entry_are_deferred_with_it(self):
        docs, stored = self.run_top(["a"], {"cpu-gone": make_item()}, entries={"cpu": skipped("not due")})

        self.assertEqual(self.base(config=self.CONFIG, docs=docs, stored=stored)["deferred"], ["cpu", "cpu-gone"])

    def test_tracked_group_keys_of_a_failed_top_entry_are_deferred_with_it(self):
        docs, stored = self.run_top(["a"], {"cpu-gone": make_item()}, entries={"cpu": failed("HTTP 400 POST /query")})

        self.assertEqual(self.base(config=self.CONFIG, docs=docs, stored=stored)["deferred"], ["cpu", "cpu-gone"])

    def test_auto_keys_and_deferred_group_keys_need_a_read_source(self):
        stored = make_state(items={"cpu-gone": make_item(), "cpu": make_item()})
        docs = collections(gauges=unread_gauges())

        found, base = self.features(config=self.CONFIG, docs=docs, stored=stored), self.base(config=self.CONFIG, docs=docs, stored=stored, tag="2")

        self.assertEqual((found["auto"], base["deferred"]), ({}, []))

    def test_group_values_enter_the_cursors_and_stale_untracked_group_keys_leave_them(self):
        docs = collections(gauges=gauges(metrics=[metric(groups=[{"group": "a", "value": 3}])], cursor={"metrics": {"cpu": 9, "cpu-old": 1}}))

        cursors = self.base(config=self.CONFIG, docs=docs, stored=make_state(metrics={"cpu-old": 2}))["cursors"]

        self.assertEqual(cursors["metrics"], {"cpu": 9, "cpu-a": 3})

    def test_tracked_group_absent_from_this_read_keeps_its_stored_cursor_value(self):
        docs, stored = self.run_top(["a", "b"], {"cpu-gone": make_item()})
        stored["cursors"]["observability"]["metrics"]["cpu-gone"] = 7

        cursors = self.base(config=self.CONFIG, docs=docs, stored=stored)["cursors"]

        self.assertEqual(cursors["metrics"]["cpu-gone"], 7)

    def test_stored_untracked_group_cursors_survive_a_run_where_the_daily_top_entry_is_not_due(self):
        config = make_config(pack=[top_entry(schedule="daily")])
        docs = collections(gauges=gauges(metrics=[], entries={"cpu": skipped("not due")}, cursor={"metrics": {"cpu-a": 4, "cpu-b": 2}}))

        cursors = self.base(config=config, docs=docs, stored=make_state(metrics={"cpu-a": 4, "cpu-b": 2}))["cursors"]

        self.assertEqual(cursors["metrics"], {"cpu-a": 4, "cpu-b": 2})

    def test_stored_untracked_group_cursors_survive_a_failed_top_entry(self):
        docs = collections(gauges=gauges(metrics=[], entries={"cpu": failed("HTTP 400 POST /query")}, cursor={"metrics": {"cpu-a": 4}}))

        cursors = self.base(config=self.CONFIG, docs=docs, stored=make_state(metrics={"cpu-a": 4}))["cursors"]

        self.assertEqual(cursors["metrics"], {"cpu-a": 4})

    def test_cursor_of_two_top_entries_prunes_the_observed_one_and_keeps_the_stored_groups_of_the_failed_one(self):
        config = make_config(pack=[top_entry(key="cpu"), top_entry(key="mem")])
        docs = collections(gauges=gauges(
            metrics=[metric(groups=[{"group": "a", "value": 3}])],
            entries={"cpu": ok(), "mem": failed("HTTP 400 POST /query")},
            cursor={"metrics": {"cpu": 9, "cpu-old": 1}},
        ))
        stored = make_state(items={"mem-b": make_item()}, metrics={"cpu-old": 2, "mem-b": 7})

        cursors = self.base(config=config, docs=docs, stored=stored)["cursors"]

        self.assertEqual(cursors["metrics"], {"cpu": 9, "cpu-a": 3, "mem-b": 7})

    def test_top_read_without_any_group_is_a_no_datapoints_gap_that_defers_the_entry_and_its_tracked_groups(self):
        docs, stored = self.run_top([], {"cpu-gone": make_item()})

        base, found = self.base(config=self.CONFIG, docs=docs, stored=stored), self.features(config=self.CONFIG, docs=docs, stored=stored, tag="2")

        self.assertEqual(base["blind_spots"], [{"key": "cpu", "gap": "no datapoints"}])
        self.assertEqual((base["deferred"], found["auto"]), (["cpu", "cpu-gone"], {}))

    def test_mute_on_a_top_entry_key_covers_its_group_keys_from_the_features_and_the_state(self):
        docs, stored = self.run_top(["a"], {"cpu-gone": make_item()})

        mutes = self.base(config=self.CONFIG, docs=docs, stored=stored)["mutes"]

        self.assertEqual([mute["key"] for mute in mutes], ["cpu", "cpu-a", "cpu-gone"])

    def test_stored_mute_on_a_top_entry_key_is_expanded_when_the_page_is_unread(self):
        docs, stored = self.run_top(["a"], {})
        stored["run"]["mutes"] = [{"key": "cpu", "until": "2026-07-01"}]
        docs["notes"] = collections()["notes"] | {"read": False, "reason": "HTTP 404 GET /pages", "records": {"pages": []}, "cursor": None}

        mutes = self.base(config=self.CONFIG, docs=docs, stored=stored)["mutes"]

        self.assertEqual(mutes, [{"key": "cpu", "until": "2026-07-01"}, {"key": "cpu-a", "until": "2026-07-01"}])

    def test_mute_on_a_plain_key_is_not_expanded(self):
        self.assertEqual(self.base()["mutes"], [{"key": "cpu", "until": "2026-06-10"}])


class PlainKeyPrefixTest(EvaluateCase):
    CONFIG = make_config(pack=[metric_entry(key="cpu"), metric_entry(key="cpu-b")])

    def docs(self, entries):
        return collections(gauges=gauges(
            metrics=[metric(key="cpu"), metric(key="cpu-b")], entries=entries, cursor={"metrics": {"cpu": 90, "cpu-b": 90}},
        ))

    def test_mute_on_a_plain_key_does_not_cover_a_pack_key_sharing_its_prefix(self):
        mutes = self.base(config=self.CONFIG, docs=self.docs({"cpu": ok(), "cpu-b": ok()}))["mutes"]

        self.assertEqual(mutes, [{"key": "cpu", "until": "2026-06-10"}])

    def test_failed_plain_entry_does_not_defer_a_tracked_pack_key_sharing_its_prefix(self):
        docs = self.docs({"cpu": failed("HTTP 400 POST /query"), "cpu-b": ok()})

        base = self.base(config=self.CONFIG, docs=docs, stored=make_state(items={"cpu-b": make_item()}))

        self.assertEqual(base["deferred"], ["cpu"])


class SizeTest(EvaluateCase):
    def worst_case(self):
        start = DAY_0
        names = [f"m{index:02d}" for index in range(50)]
        pack = [
            metric_entry(read="hourly", key=name, rule="r" * 500, title="t" * 100, link="https://example.test/" + "l" * 79)
            for name in names
        ]
        records = [
            metric(
                key=name,
                value=1,
                hourly=[{"ts": start + hour * 3600, "value": 10**14 + (position * 7919 + hour * 104729) * 98765432109 % (9 * 10**14)} for hour in range(72)],
            )
            for position, name in enumerate(names)
        ]
        span = {"from_ts": start, "to_ts": start + 72 * 3600}
        docs = collections(gauges=dict(gauges(metrics=records, entries={name: ok() for name in names}), window=span))
        for name in ("alerts", "notes"):
            docs[name] = dict(docs[name], window=span)
        items = {name: make_item("Medium", "within months", runs_under_threshold=10) for name in names}
        return {
            "config": make_config(pack=pack, rules=["x" * 500] * 10),
            "docs": docs,
            "stored": make_state(items=items, metrics={name: 10**15 - 1 for name in names}),
            "window": dict(make_window(), **span),
        }

    def sizes(self):
        features_size = len(self.raw("features", tag="1", **self.worst_case()))
        rules_size = len(self.raw("rules", tag="2", **self.worst_case()))
        return features_size, rules_size

    def test_worst_case_keys_are_tracked_and_hold_values_of_15_digits(self):
        found = self.features(**self.worst_case())

        self.assertEqual((len(found["keys"]), len(found["bucket_labels"])), (50, 72))
        self.assertTrue(all(doc["tracked"] is not None for doc in found["keys"].values()))
        self.assertEqual({len(str(value)) for doc in found["keys"].values() for value in doc["buckets"]}, {15})

    def test_fifty_worst_case_keys_of_72_buckets_stay_under_150_kb_with_the_rules(self):
        self.assertLess(sum(self.sizes()), 150_000)


if __name__ == "__main__":
    unittest.main()
