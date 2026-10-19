import copy
import unittest

import judgment
import state

LABEL_0 = "2026-06-02T00:00:00+02:00"
LABEL_1 = "2026-06-02T01:00:00+02:00"
MONITOR = "monitor-77"
TRACKED_DISK = {"severity": "Medium", "when": "within months", "since": "2026-05-30T08:00:00Z", "runs_under_threshold": 1, "has_analysis": False}


def doc(kind, source, title, values, **extra):
    return dict(
        {"kind": kind, "entry": None, "source": source, "title": title, "link": f"https://example.test/{title}", "values": values, "tracked": None},
        **extra,
    )


def auto_entry(reason="not found", title="Disk", severity="Medium", when="within months"):
    return {"reason": reason, "title": title, "link": f"https://example.test/{title}", "severity": severity, "when": when}


def make_features(auto=None, **extra_keys):
    keys = {
        MONITOR: doc(
            "monitor", "monitors", "API monitor",
            {"state": "Alert", "priority": 2, "transitions": 3, "first_transition": LABEL_0, "last_transition": LABEL_1, "transitions_per_hour": 3.0},
        ),
        "cpu": doc(
            "metric", "metrics", "Metric cpu",
            {"value": 90, "window_max": 90, "window_max_at": LABEL_1, "latest": 85.5, "previous": 70, "change": 20, "change_percent": 28.57},
            buckets=[95, 90], excluded=[0], days=[{"label": "2026-06-01", "value": 40, "partial": True}],
        ),
        "queue-a": doc(
            "group", "metrics", "Queue a",
            {"value": 5, "window_max": 5, "window_max_at": None, "latest": 5, "previous": None, "change": None, "change_percent": None, "groups_complete": True},
        ),
    }
    keys.update(extra_keys)
    return {"bucket_labels": [LABEL_0, LABEL_1], "keys": keys, "auto": auto or {}}


def make_base(deferred=()):
    return {
        "sources": {"monitors": {"read": True}, "metrics": {"read": True}},
        "cursors": {"events_ts_ms": 1, "monitors": {}, "metrics": {}},
        "blind_spots": [],
        "blind_spots_retried": [],
        "mutes": [],
        "deferred": list(deferred),
        "sources_last_edited": None,
        "daily_metrics_on": "2026-06-01",
        "resolved_queries": {},
        "models": {},
    }


def verdict(open=True, severity="High", urgency="now", rank=1, cites=None):
    return {"open": open, "severity": severity, "urgency": urgency, "rank": rank, "cites": {"state": "Alert"} if cites is None else cites}


def make_judgment(**overrides):
    verdicts = {
        MONITOR: verdict(),
        "cpu": verdict(severity="Medium", urgency="watch", rank=2, cites={"value": 90}),
        "queue-a": verdict(open=False, severity="Low", urgency="watch", rank=None, cites={"value": 5}),
    }
    verdicts.update(overrides)
    return {"schema": 1, "verdicts": verdicts}


def cpu_with(**fields):
    return make_judgment(cpu=dict(make_judgment()["verdicts"]["cpu"], **fields))


def cpu_citing(cites):
    return cpu_with(cites=cites)


def make_summary():
    return {"new": [{"key": MONITOR, "rank": 1}], "escalated": [{"key": "cpu", "rank": 2}]}


def make_analysis_item(cites, **overrides):
    item = {
        "risk": "the queue grows until the consumer stalls",
        "reason": [
            {"tag": "measured", "claim": "the value is above its previous one", "cites": cites},
            {"tag": "inferred", "claim": "a deploy changed the consumer", "cites": {}},
        ],
        "mitigation": ["roll back the consumer", "scale the workers"],
        "action": "restart the consumer",
    }
    item.update(overrides)
    return item


def make_analysis(**overrides):
    items = {MONITOR: make_analysis_item({"state": "Alert"}), "cpu": make_analysis_item({"value": 90})}
    items.update(overrides)
    return {"schema": 1, "items": items}


def cpu_item_with(**fields):
    return make_analysis(cpu=make_analysis_item({"value": 90}, **fields))


def cpu_claim(claim):
    return cpu_item_with(reason=[claim])


class JudgeTestCase(unittest.TestCase):
    def judged(self, document=None, features_doc=None, base=None):
        return judgment.judge(features_doc or make_features(), base or make_base(), make_judgment() if document is None else document)

    def rejection(self, document, features_doc=None, base=None):
        with self.assertRaises(state.Rejected) as caught:
            self.judged(document, features_doc, base)
        return str(caught.exception)


class VerdictKeyTest(JudgeTestCase):
    def test_verdict_for_a_key_absent_from_the_features_is_rejected_with_its_key_path(self):
        self.assertIn("verdicts.ghost", self.rejection(make_judgment(ghost=verdict())))

    def test_verdict_for_a_deferred_key_is_rejected_with_its_key_path(self):
        message = self.rejection(make_judgment(disk=verdict()), base=make_base(deferred=["disk"]))

        self.assertIn("verdicts.disk", message)
        self.assertIn("deferred", message)

    def test_verdict_for_an_auto_key_is_rejected_with_its_key_path(self):
        message = self.rejection(make_judgment(disk=verdict()), features_doc=make_features(auto={"disk": auto_entry()}))

        self.assertIn("verdicts.disk", message)
        self.assertIn("needs no verdict (not found)", message)

    def test_key_with_no_verdict_is_rejected_with_its_key_path(self):
        document = make_judgment()
        del document["verdicts"]["cpu"]

        self.assertIn("verdicts.cpu", self.rejection(document))

    def test_auto_key_that_the_features_also_list_needs_no_verdict(self):
        features_doc = make_features(auto={"disk": auto_entry()}, disk=doc("metric", "metrics", "Disk", {"value": 1}, tracked=TRACKED_DISK))

        facts = self.judged(features_doc=features_doc)

        self.assertFalse(facts["observations"]["disk"]["over"])


class VerdictShapeTest(JudgeTestCase):
    def test_wrong_schema_is_rejected(self):
        self.assertIn("schema", self.rejection({"schema": 2, "verdicts": {}}))

    def test_verdicts_that_are_not_an_object_are_rejected(self):
        self.assertIn("verdicts", self.rejection({"schema": 1, "verdicts": []}))

    def test_severity_outside_the_allowed_values_is_rejected_with_its_key_path(self):
        self.assertIn("verdicts.cpu.severity", self.rejection(cpu_with(severity="Critical")))

    def test_urgency_outside_the_allowed_values_is_rejected_with_its_key_path(self):
        self.assertIn("verdicts.cpu.urgency", self.rejection(cpu_with(urgency="soon")))

    def test_open_that_is_not_a_boolean_is_rejected_with_its_key_path(self):
        self.assertIn("verdicts.cpu.open", self.rejection(cpu_with(open="yes")))

    def test_verdict_without_cites_is_rejected_with_its_key_path(self):
        document = cpu_with()
        del document["verdicts"]["cpu"]["cites"]

        self.assertIn("verdicts.cpu.cites", self.rejection(document))

    def test_empty_cites_are_rejected_with_their_key_path(self):
        self.assertIn("verdicts.cpu.cites", self.rejection(cpu_citing({})))

    def test_monitor_verdict_that_does_not_cite_the_state_is_rejected(self):
        message = self.rejection(make_judgment(**{MONITOR: verdict(cites={"transitions": 3})}))

        self.assertIn(f"verdicts.{MONITOR}.cites", message)
        self.assertIn("state", message)


class CitedValueTest(JudgeTestCase):
    def test_cited_name_that_the_key_lacks_is_rejected_with_its_path(self):
        self.assertIn("verdicts.cpu.cites.state", self.rejection(cpu_citing({"state": "Alert"})))

    def test_cited_value_that_differs_is_rejected_with_its_path(self):
        self.assertIn("verdicts.cpu.cites.value", self.rejection(cpu_citing({"value": 91})))

    def test_cited_text_differing_in_case_is_rejected(self):
        self.assertIn(f"verdicts.{MONITOR}.cites.state", self.rejection(make_judgment(**{MONITOR: verdict(cites={"state": "alert"})})))

    def test_cited_boolean_against_a_number_is_rejected(self):
        self.assertIn("verdicts.cpu.cites.change", self.rejection(cpu_citing({"change": True})))

    def test_cited_number_against_a_boolean_is_rejected(self):
        self.assertIn("verdicts.queue-a.cites.groups_complete", self.rejection(make_judgment(**{"queue-a": verdict(open=False, rank=None, cites={"groups_complete": 1})})))

    def test_cited_null_against_a_number_is_rejected(self):
        self.assertIn(f"verdicts.{MONITOR}.cites.priority", self.rejection(make_judgment(**{MONITOR: verdict(cites={"state": "Alert", "priority": None})})))

    def test_cited_number_against_a_null_is_rejected(self):
        self.assertIn("verdicts.queue-a.cites.previous", self.rejection(make_judgment(**{"queue-a": verdict(open=False, rank=None, cites={"previous": 0})})))

    def test_cited_null_matches_a_null_feature(self):
        facts = self.judged(make_judgment(**{"queue-a": verdict(open=False, rank=None, cites={"previous": None})}))

        self.assertEqual((facts["observations"]["queue-a"]["over"], facts["observations"]["queue-a"]["rank"]), (False, None))

    def test_cited_boolean_matches_a_boolean_feature(self):
        facts = self.judged(make_judgment(**{"queue-a": verdict(open=False, rank=None, cites={"groups_complete": True})}))

        self.assertEqual((facts["observations"]["queue-a"]["over"], facts["observations"]["queue-a"]["rank"]), (False, None))

    def test_cited_float_equal_to_an_integer_feature_matches(self):
        facts = self.judged(cpu_citing({"value": 90.0}))

        self.assertEqual((facts["observations"]["cpu"]["over"], facts["observations"]["cpu"]["rank"]), (True, 2))

    def test_cited_number_matches_after_rounding_to_four_significant_digits(self):
        facts = self.judged(cpu_citing({"change_percent": 28.5714}))

        self.assertEqual((facts["observations"]["cpu"]["over"], facts["observations"]["cpu"]["rank"]), (True, 2))

    def test_cited_number_that_rounds_to_another_value_is_rejected(self):
        self.assertIn("verdicts.cpu.cites.change_percent", self.rejection(cpu_citing({"change_percent": 28.6})))

    def test_cites_that_are_not_an_object_are_rejected_with_their_key_path(self):
        self.assertIn("verdicts.cpu.cites", self.rejection(cpu_citing([["value", 90]])))

    def test_cited_bucket_matches_its_value(self):
        facts = self.judged(cpu_citing({f"bucket:{LABEL_1}": 90}))

        self.assertEqual((facts["observations"]["cpu"]["over"], facts["observations"]["cpu"]["rank"]), (True, 2))

    def test_cited_bucket_with_another_value_is_rejected(self):
        self.assertIn(f"verdicts.cpu.cites.bucket:{LABEL_1}", self.rejection(cpu_citing({f"bucket:{LABEL_1}": 95})))

    def test_cited_excluded_bucket_is_rejected(self):
        message = self.rejection(cpu_citing({f"bucket:{LABEL_0}": 95}))

        self.assertIn(f"verdicts.cpu.cites.bucket:{LABEL_0}", message)
        self.assertIn("excluded", message)

    def test_cited_bucket_label_that_the_window_lacks_is_rejected(self):
        self.assertIn("cites.bucket:2026-06-02T09:00:00+02:00", self.rejection(cpu_citing({"bucket:2026-06-02T09:00:00+02:00": 1})))

    def test_cited_bucket_of_a_key_without_buckets_is_rejected(self):
        message = self.rejection(make_judgment(**{"queue-a": verdict(open=False, rank=None, cites={f"bucket:{LABEL_1}": 5})}))

        self.assertIn(f"verdicts.queue-a.cites.bucket:{LABEL_1}", message)

    def test_cited_day_matches_its_value(self):
        facts = self.judged(cpu_citing({"day:2026-06-01": 40}))

        self.assertEqual((facts["observations"]["cpu"]["over"], facts["observations"]["cpu"]["rank"]), (True, 2))

    def test_cited_day_with_another_value_is_rejected(self):
        self.assertIn("verdicts.cpu.cites.day:2026-06-01", self.rejection(cpu_citing({"day:2026-06-01": 41})))

    def test_cited_day_that_the_key_lacks_is_rejected(self):
        self.assertIn("verdicts.cpu.cites.day:2026-05-01", self.rejection(cpu_citing({"day:2026-05-01": 40})))


class RankTest(JudgeTestCase):
    def test_ranks_over_the_open_keys_must_be_one_to_n(self):
        self.assertIn("verdicts.cpu.rank", self.rejection(cpu_with(rank=3)))

    def test_rank_used_twice_is_rejected_with_the_later_key_path(self):
        self.assertIn(f"verdicts.{MONITOR}.rank", self.rejection(cpu_with(rank=1)))

    def test_open_key_without_a_rank_is_rejected(self):
        self.assertIn("verdicts.cpu.rank", self.rejection(cpu_with(rank=None)))

    def test_rank_of_a_key_that_is_not_open_is_rejected(self):
        self.assertIn("verdicts.queue-a.rank", self.rejection(make_judgment(**{"queue-a": verdict(open=False, rank=3, cites={"value": 5})})))

    def test_rank_zero_is_rejected(self):
        self.assertIn("verdicts.cpu.rank", self.rejection(cpu_with(rank=0)))

    def test_rank_that_is_a_boolean_is_rejected(self):
        self.assertIn("verdicts.cpu.rank", self.rejection(cpu_with(rank=True)))

    def test_no_open_key_needs_no_rank(self):
        document = make_judgment(**{MONITOR: verdict(open=False, rank=None), "cpu": verdict(open=False, rank=None, cites={"value": 90})})

        facts = self.judged(document)

        self.assertEqual({observation["rank"] for observation in facts["observations"].values()}, {None})


class MergeTest(JudgeTestCase):
    def test_observation_takes_the_verdict_and_the_features(self):
        facts = self.judged()

        self.assertEqual(
            facts["observations"][MONITOR],
            {
                "source": "monitors", "over": True, "value": None, "severity": "High", "when": "now",
                "title": "API monitor", "link": "https://example.test/API monitor", "last_value": "Alert", "rank": 1,
            },
        )
        self.assertEqual(
            facts["observations"]["cpu"],
            {
                "source": "metrics", "over": True, "value": 90, "severity": "Medium", "when": "watch",
                "title": "Metric cpu", "link": "https://example.test/Metric cpu", "last_value": 90, "rank": 2,
            },
        )

    def test_group_observation_is_not_over_with_a_null_rank(self):
        observation = self.judged()["observations"]["queue-a"]

        self.assertEqual((observation["over"], observation["value"], observation["last_value"], observation["rank"]), (False, 5, 5, None))

    def test_metric_without_a_value_has_a_null_value_and_last_value(self):
        features_doc = make_features(cpu=doc("metric", "metrics", "Metric cpu", {"value": None, "latest": None}, days=[{"label": "2026-06-01", "value": 4, "partial": True}]))

        observation = self.judged(make_judgment(cpu=verdict(rank=2, cites={"value": None})), features_doc)["observations"]["cpu"]

        self.assertEqual((observation["value"], observation["last_value"]), (None, None))

    def test_float_value_stays_a_number_in_last_value(self):
        features_doc = make_features(cpu=doc("metric", "metrics", "Metric cpu", {"value": 85.5, "latest": 85.5}))

        observation = self.judged(make_judgment(cpu=verdict(rank=2, cites={"value": 85.5})), features_doc)["observations"]["cpu"]

        self.assertEqual((observation["value"], observation["last_value"]), (85.5, 85.5))

    def test_facts_hold_the_base_unchanged_apart_from_the_observations(self):
        base = make_base(deferred=["disk"])

        facts = self.judged(base=base)

        self.assertEqual({name: value for name, value in facts.items() if name not in ("observations", "overrides")}, base)

    def test_facts_pass_the_state_check(self):
        state.check_facts(self.judged())

    def test_same_inputs_give_the_same_bytes_whatever_the_verdict_order(self):
        reordered = {"schema": 1, "verdicts": dict(reversed(list(make_judgment()["verdicts"].items())))}

        self.assertEqual(state.dump(self.judged()), state.dump(self.judged(reordered)))

    def test_inputs_are_not_modified(self):
        features_doc, base, document = make_features(), make_base(), make_judgment()
        before = copy.deepcopy((features_doc, base, document))

        judgment.judge(features_doc, base, document)

        self.assertEqual((features_doc, base, document), before)

    def test_judgment_with_a_rejected_key_gives_no_facts(self):
        with self.assertRaises(state.Rejected):
            self.judged(cpu_with(severity="Critical"))


class OverrideTest(JudgeTestCase):
    OTHER = "monitor-5"

    def features_with_two_monitors(self, state_name="Warn"):
        other = doc("monitor", "monitors", "Other monitor", {"state": state_name, "priority": None, "transitions": 0})
        return make_features(**{self.OTHER: other})

    def closed(self, cites):
        return verdict(open=False, severity="Low", urgency="watch", rank=None, cites=cites)

    def overrides(self, document, features_doc=None):
        return self.judged(document, features_doc)["overrides"]

    def test_monitor_not_ok_with_a_verdict_that_is_not_open_is_an_override(self):
        document = make_judgment(**{MONITOR: self.closed({"state": "Alert"}), "cpu": verdict(rank=1, cites={"value": 90})})

        self.assertEqual(self.overrides(document), [MONITOR])

    def test_monitor_not_ok_with_an_open_verdict_is_not_an_override(self):
        self.assertEqual(self.overrides(make_judgment()), [])

    def test_monitor_in_the_ok_state_with_a_verdict_that_is_not_open_is_not_an_override(self):
        features_doc = make_features(**{MONITOR: doc("monitor", "monitors", "API monitor", {"state": "OK", "priority": None})})
        document = make_judgment(**{MONITOR: self.closed({"state": "OK"}), "cpu": verdict(rank=1, cites={"value": 90})})

        self.assertEqual(self.overrides(document, features_doc), [])

    def test_every_state_but_ok_counts_as_not_ok(self):
        features_doc = self.features_with_two_monitors("No Data")
        document = make_judgment(**{self.OTHER: self.closed({"state": "No Data"})})

        self.assertEqual(self.overrides(document, features_doc), [self.OTHER])

    def test_metric_and_group_verdicts_that_are_not_open_are_not_overrides(self):
        document = make_judgment(cpu=verdict(open=False, severity="Low", urgency="watch", rank=None, cites={"value": 90}))

        self.assertEqual(self.overrides(document), [])

    def test_overrides_are_sorted_whatever_the_verdict_order(self):
        features_doc = self.features_with_two_monitors()
        document = make_judgment(**{
            self.OTHER: self.closed({"state": "Warn"}),
            MONITOR: self.closed({"state": "Alert"}),
            "cpu": verdict(rank=1, cites={"value": 90}),
        })

        self.assertEqual(self.overrides(document, features_doc), [self.OTHER, MONITOR])

    def test_facts_with_overrides_pass_the_state_check(self):
        document = make_judgment(**{MONITOR: self.closed({"state": "Alert"}), "cpu": verdict(rank=1, cites={"value": 90})})

        state.check_facts(self.judged(document))


class AutoKeyTest(JudgeTestCase):
    def observation_of(self, key, entry):
        return self.judged(features_doc=make_features(auto={key: entry}))["observations"][key]

    def test_not_found_monitor_key_becomes_an_observation_that_is_not_open(self):
        entry = auto_entry("not found", title="API monitor", severity="High", when="now")

        self.assertEqual(
            self.observation_of("monitor-9", entry),
            {
                "source": "monitors", "over": False, "value": None, "severity": "High", "when": "now",
                "title": "API monitor", "link": "https://example.test/API monitor", "last_value": "not found", "rank": None,
            },
        )

    def test_group_missing_key_becomes_an_observation_that_is_not_open(self):
        entry = auto_entry("group missing", title="Queue: a")

        self.assertEqual(
            self.observation_of("queue-b", entry),
            {
                "source": "metrics", "over": False, "value": None, "severity": "Medium", "when": "within months",
                "title": "Queue: a", "link": "https://example.test/Queue: a", "last_value": "group missing", "rank": None,
            },
        )

    def test_replaced_by_groups_key_becomes_an_observation_that_is_not_open(self):
        entry = auto_entry("replaced by groups", title="Queue", severity="Low", when="watch")

        self.assertEqual(
            self.observation_of("queue", entry),
            {
                "source": "metrics", "over": False, "value": None, "severity": "Low", "when": "watch",
                "title": "Queue", "link": "https://example.test/Queue", "last_value": "replaced by groups", "rank": None,
            },
        )

    def test_auto_key_needs_no_entry_in_the_keys(self):
        facts = self.judged(features_doc=make_features(auto={"disk": auto_entry()}))

        self.assertEqual(sorted(facts["observations"]), ["cpu", "disk", MONITOR, "queue-a"])

    def test_auto_key_takes_its_fields_from_the_auto_entry_not_from_the_keys(self):
        features_doc = make_features(
            auto={"disk": auto_entry(title="Stored disk", severity="High", when="now")},
            disk=doc("metric", "metrics", "Listed disk", {"value": 1}, tracked=TRACKED_DISK),
        )

        observation = self.judged(features_doc=features_doc)["observations"]["disk"]

        self.assertEqual((observation["title"], observation["severity"], observation["when"]), ("Stored disk", "High", "now"))

    def test_auto_keys_do_not_count_in_the_ranks(self):
        facts = self.judged(features_doc=make_features(auto={"disk": auto_entry()}))

        self.assertEqual(sorted(observation["rank"] for observation in facts["observations"].values() if observation["over"]), [1, 2])

    def test_auto_key_that_is_also_deferred_gives_an_input_error(self):
        with self.assertRaises(state.InputError):
            self.judged(features_doc=make_features(auto={"disk": auto_entry()}), base=make_base(deferred=["disk"]))


class AnalysisTestCase(unittest.TestCase):
    def annotated(self, analysis=None, facts=None, summary=None):
        merged = judgment.judge(make_features(), make_base(), make_judgment()) if facts is None else facts
        return judgment.annotate(make_features(), merged, make_analysis() if analysis is None else analysis, summary or make_summary())

    def rejection(self, analysis, summary=None):
        with self.assertRaises(state.Rejected) as caught:
            self.annotated(analysis, summary=summary)
        return str(caught.exception)


class AnalysisKeysTest(AnalysisTestCase):
    def test_analysis_for_a_key_the_summary_does_not_list_is_rejected_with_its_key_path(self):
        self.assertIn("items.queue-a", self.rejection(make_analysis(**{"queue-a": make_analysis_item({"value": 5})})))

    def test_listed_key_with_no_analysis_is_rejected_with_its_key_path(self):
        analysis = make_analysis()
        del analysis["items"]["cpu"]

        self.assertIn("items.cpu", self.rejection(analysis))

    def test_keys_are_the_new_and_escalated_keys_only(self):
        summary = dict(make_summary(), resolved=[{"key": "queue-a"}], new=[])

        self.assertIn(f"items.{MONITOR}", self.rejection(make_analysis(), summary))

    def test_wrong_schema_is_rejected(self):
        self.assertIn("schema", self.rejection({"schema": 2, "items": {}}))

    def test_items_that_are_not_an_object_are_rejected(self):
        self.assertIn("items", self.rejection({"schema": 1, "items": []}))

    def test_item_that_is_not_an_object_is_rejected_with_its_key_path(self):
        self.assertIn("items.cpu", self.rejection(make_analysis(cpu="restart")))


class AnalysisTextTest(AnalysisTestCase):
    def test_risk_over_300_characters_is_rejected_with_its_path(self):
        self.assertIn("items.cpu.risk", self.rejection(cpu_item_with(risk="x" * 301)))

    def test_text_of_300_characters_is_accepted(self):
        facts = self.annotated(cpu_item_with(action="x" * 300))

        self.assertEqual(facts["observations"]["cpu"]["action"], "x" * 300)

    def test_action_with_a_control_character_is_rejected_with_its_path(self):
        self.assertIn("items.cpu.action", self.rejection(cpu_item_with(action="restart\nnow")))

    def test_claim_with_a_control_character_is_rejected_with_its_path(self):
        claim = {"tag": "inferred", "claim": "a\tb", "cites": {}}

        self.assertIn("items.cpu.reason[0].claim", self.rejection(cpu_claim(claim)))

    def test_action_with_a_line_separator_is_rejected_with_its_path(self):
        self.assertIn("items.cpu.action", self.rejection(cpu_item_with(action="restart\u2028now")))

    def test_risk_with_a_bidirectional_override_is_rejected_with_its_path(self):
        self.assertIn("items.cpu.risk", self.rejection(cpu_item_with(risk="the \u202eservice degrades")))

    def test_each_text_field_with_a_mention_or_markup_character_is_rejected_with_its_path(self):
        for name in ("risk", "action"):
            for barred in ("<", ">", "@"):
                with self.subTest(field=name, character=barred):
                    self.assertIn(f"items.cpu.{name}", self.rejection(cpu_item_with(**{name: f"ping {barred}here"})))

    def test_each_text_field_with_a_link_is_rejected_with_its_path(self):
        for name in ("risk", "action"):
            with self.subTest(field=name):
                self.assertIn(f"items.cpu.{name}", self.rejection(cpu_item_with(**{name: "see https://example.test/x"})))

    def test_mitigation_lead_with_a_mention_is_rejected_with_its_path(self):
        self.assertIn("items.cpu.mitigation[1]", self.rejection(cpu_item_with(mitigation=["a", "ask @owner"])))

    def test_mitigation_lead_with_a_link_is_rejected_with_its_path(self):
        self.assertIn("items.cpu.mitigation[0]", self.rejection(cpu_item_with(mitigation=["open ftp://host/x"])))

    def test_claim_with_markup_is_rejected_with_its_path(self):
        claim = {"tag": "inferred", "claim": "a <b>deploy</b>", "cites": {}}

        self.assertIn("items.cpu.reason[0].claim", self.rejection(cpu_claim(claim)))

    def test_claim_with_a_mention_is_rejected_with_its_path(self):
        claim = {"tag": "inferred", "claim": "ask @owner", "cites": {}}

        self.assertIn("items.cpu.reason[0].claim", self.rejection(cpu_claim(claim)))

    def test_claim_with_a_link_is_rejected_with_its_path(self):
        claim = {"tag": "inferred", "claim": "see https://example.test", "cites": {}}

        self.assertIn("items.cpu.reason[0].claim", self.rejection(cpu_claim(claim)))

    def test_each_text_field_with_a_fullwidth_markdown_link_is_rejected_with_its_path(self):
        link = "see \uff3bx\uff3d\uff08https\uff1a\uff0f\uff0fexample.test\uff09"
        for name in ("risk", "action"):
            with self.subTest(field=name):
                self.assertIn(f"items.cpu.{name}", self.rejection(cpu_item_with(**{name: link})))

    def test_each_text_field_with_a_fullwidth_mention_or_markup_character_is_rejected_with_its_path(self):
        for name in ("risk", "action"):
            for barred in ("\uff20", "\uff1c", "\uff1e"):
                with self.subTest(field=name, character=barred):
                    self.assertIn(f"items.cpu.{name}", self.rejection(cpu_item_with(**{name: f"ping {barred}here"})))

    def test_mitigation_lead_with_a_fullwidth_mention_is_rejected_with_its_path(self):
        self.assertIn("items.cpu.mitigation[1]", self.rejection(cpu_item_with(mitigation=["a", "ask \uff20owner"])))

    def test_claim_with_a_fullwidth_link_is_rejected_with_its_path(self):
        claim = {"tag": "inferred", "claim": "\uff3bx\uff3d\uff08https\uff1a\uff0f\uff0fexample.test\uff09", "cites": {}}

        self.assertIn("items.cpu.reason[0].claim", self.rejection(cpu_claim(claim)))

    def test_claim_with_a_fullwidth_mention_is_rejected_with_its_path(self):
        claim = {"tag": "inferred", "claim": "ask \uff20owner", "cites": {}}

        self.assertIn("items.cpu.reason[0].claim", self.rejection(cpu_claim(claim)))

    def test_plain_text_with_fullwidth_letters_and_digits_is_accepted(self):
        facts = self.annotated(cpu_item_with(action="restart \uff23\uff30\uff35 \uff11\uff10"))

        self.assertEqual(facts["observations"]["cpu"]["action"], "restart \uff23\uff30\uff35 \uff11\uff10")

    def test_text_with_a_colon_and_slashes_but_no_scheme_is_accepted(self):
        facts = self.annotated(cpu_item_with(action="restart 3:4 of /var/log"))

        self.assertEqual(facts["observations"]["cpu"]["action"], "restart 3:4 of /var/log")

    def test_mitigation_lead_over_300_characters_is_rejected_with_its_path(self):
        self.assertIn("items.cpu.mitigation[1]", self.rejection(cpu_item_with(mitigation=["a", "x" * 301])))

    def test_risk_that_is_not_text_is_rejected_with_its_path(self):
        self.assertIn("items.cpu.risk", self.rejection(cpu_item_with(risk=3)))

    def test_item_without_an_action_is_rejected_with_its_path(self):
        analysis = cpu_item_with()
        del analysis["items"]["cpu"]["action"]

        self.assertIn("items.cpu.action", self.rejection(analysis))

    def test_no_mitigation_lead_is_rejected(self):
        self.assertIn("items.cpu.mitigation", self.rejection(cpu_item_with(mitigation=[])))

    def test_four_mitigation_leads_are_rejected(self):
        self.assertIn("items.cpu.mitigation", self.rejection(cpu_item_with(mitigation=["a", "b", "c", "d"])))

    def test_three_mitigation_leads_are_accepted(self):
        facts = self.annotated(cpu_item_with(mitigation=["a", "b", "c"]))

        self.assertEqual(facts["observations"]["cpu"]["mitigation"], ["a", "b", "c"])


class AnalysisClaimTest(AnalysisTestCase):
    def test_tag_other_than_measured_or_inferred_is_rejected_with_its_path(self):
        claim = {"tag": "guessed", "claim": "a deploy", "cites": {}}

        self.assertIn("items.cpu.reason[0].tag", self.rejection(cpu_claim(claim)))

    def test_measured_claim_with_empty_cites_is_rejected_with_its_path(self):
        claim = {"tag": "measured", "claim": "the value rose", "cites": {}}

        self.assertIn("items.cpu.reason[0].cites", self.rejection(cpu_claim(claim)))

    def test_measured_claim_without_cites_is_rejected_with_its_path(self):
        claim = {"tag": "measured", "claim": "the value rose"}

        self.assertIn("items.cpu.reason[0].cites", self.rejection(cpu_claim(claim)))

    def test_measured_claim_citing_a_value_that_differs_is_rejected_with_its_path(self):
        claim = {"tag": "measured", "claim": "the value rose", "cites": {"value": 12}}

        self.assertIn("items.cpu.reason[0].cites.value", self.rejection(cpu_claim(claim)))

    def test_measured_claim_citing_an_excluded_bucket_is_rejected(self):
        claim = {"tag": "measured", "claim": "the spike", "cites": {f"bucket:{LABEL_0}": 95}}

        self.assertIn(f"items.cpu.reason[0].cites.bucket:{LABEL_0}", self.rejection(cpu_claim(claim)))

    def test_inferred_claim_without_cites_is_accepted(self):
        facts = self.annotated(cpu_claim({"tag": "inferred", "claim": "a deploy"}))

        self.assertEqual(facts["observations"]["cpu"]["reason"], [{"tag": "inferred", "claim": "a deploy"}])

    def test_inferred_claim_citing_a_value_that_differs_is_rejected(self):
        claim = {"tag": "inferred", "claim": "a deploy", "cites": {"value": 12}}

        self.assertIn("items.cpu.reason[0].cites.value", self.rejection(cpu_claim(claim)))

    def test_five_claims_are_accepted(self):
        claims = [{"tag": "inferred", "claim": f"cause {index}"} for index in range(5)]

        facts = self.annotated(cpu_item_with(reason=claims))

        self.assertEqual(facts["observations"]["cpu"]["reason"], claims)

    def test_six_claims_are_rejected_with_the_reason_path(self):
        claims = [{"tag": "inferred", "claim": f"cause {index}"} for index in range(6)]

        self.assertIn("items.cpu.reason: expected at most 5 claims", self.rejection(cpu_item_with(reason=claims)))

    def test_claim_that_is_not_an_object_is_rejected_with_its_path(self):
        self.assertIn("items.cpu.reason[0]", self.rejection(cpu_claim("a deploy")))

    def test_reason_that_is_not_a_list_is_rejected_with_its_path(self):
        self.assertIn("items.cpu.reason", self.rejection(cpu_item_with(reason="a deploy")))


class AnnotateTest(AnalysisTestCase):
    def test_analysis_fields_join_the_listed_observations(self):
        facts = self.annotated()

        self.assertEqual(
            {name: facts["observations"]["cpu"][name] for name in ("risk", "reason", "mitigation", "action")},
            {
                "risk": "the queue grows until the consumer stalls",
                "reason": [
                    {"tag": "measured", "claim": "the value is above its previous one"},
                    {"tag": "inferred", "claim": "a deploy changed the consumer"},
                ],
                "mitigation": ["roll back the consumer", "scale the workers"],
                "action": "restart the consumer",
            },
        )

    def test_nothing_else_changes(self):
        merged = judgment.judge(make_features(), make_base(), make_judgment())
        facts = self.annotated(facts=merged)

        stripped = copy.deepcopy(facts)
        for key in (MONITOR, "cpu"):
            for name in state.OPTIONAL_FIELDS:
                del stripped["observations"][key][name]
        self.assertEqual(stripped, merged)

    def test_unlisted_observations_are_untouched(self):
        merged = judgment.judge(make_features(), make_base(), make_judgment())

        self.assertEqual(self.annotated(facts=merged)["observations"]["queue-a"], merged["observations"]["queue-a"])

    def test_input_facts_are_not_modified(self):
        merged = judgment.judge(make_features(), make_base(), make_judgment())
        before = copy.deepcopy(merged)

        self.annotated(facts=merged)

        self.assertEqual(merged, before)

    def test_annotated_facts_pass_the_state_check(self):
        state.check_facts(self.annotated())

    def test_listed_key_missing_from_the_facts_is_an_input_error(self):
        merged = judgment.judge(make_features(), make_base(), make_judgment())
        del merged["observations"]["cpu"]

        with self.assertRaises(state.InputError) as caught:
            self.annotated(facts=merged)

        self.assertIn("observations.cpu", str(caught.exception))

    def test_summary_without_changes_needs_an_empty_analysis(self):
        facts = self.annotated({"schema": 1, "items": {}}, summary={"new": [], "escalated": []})

        self.assertEqual(facts, judgment.judge(make_features(), make_base(), make_judgment()))


class ShapeCheckTest(unittest.TestCase):
    def test_features_without_keys_are_rejected(self):
        with self.assertRaises(state.Rejected) as caught:
            judgment.check_features({"bucket_labels": [], "auto": {}})

        self.assertIn("keys", str(caught.exception))

    def test_features_of_the_fixture_pass(self):
        judgment.check_features(make_features())

    def test_features_with_an_auto_entry_pass(self):
        judgment.check_features(make_features(auto={"disk": auto_entry()}))

    def test_auto_entry_that_is_a_text_is_rejected_with_its_key_path(self):
        with self.assertRaises(state.Rejected) as caught:
            judgment.check_features(make_features(auto={"disk": "not found"}))

        self.assertIn("auto.disk", str(caught.exception))

    def test_auto_entry_without_a_severity_is_rejected_with_its_field_path(self):
        entry = auto_entry()
        del entry["severity"]

        with self.assertRaises(state.Rejected) as caught:
            judgment.check_features(make_features(auto={"disk": entry}))

        self.assertIn("auto.disk.severity", str(caught.exception))

    def test_auto_entry_with_an_unknown_urgency_is_rejected_with_its_field_path(self):
        with self.assertRaises(state.Rejected) as caught:
            judgment.check_features(make_features(auto={"disk": auto_entry(when="soon")}))

        self.assertIn("auto.disk.when", str(caught.exception))

    def test_base_that_is_not_an_object_is_rejected(self):
        with self.assertRaises(state.Rejected):
            judgment.check_base([])

    def test_base_of_the_fixture_passes(self):
        judgment.check_base(make_base())

    def test_summary_without_new_is_rejected(self):
        with self.assertRaises(state.Rejected):
            judgment.check_summary({"escalated": []})


if __name__ == "__main__":
    unittest.main()
