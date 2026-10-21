import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import digest
import state
import support as fixtures

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "fixtures", "digest_golden.md")
ALL_READ = {"monitors": {"role": "observability", "transport": "api", "read": True, "reason": None}}
RUN_AT = "2026-10-19T11:32:00Z"
WINDOW_FROM = "2026-10-19T07:35:00Z"
PREVIOUS_AT = "2026-10-19T06:00:00Z"
TITLE_LINES = "**Prod watch, 19 Oct 13:32 Paris**\n(since Mon 09:35)"
EMPTY_SUMMARY = "**Summary**\n- 0 new, 0 escalated, 0 resolved, 0 still open"


def section(text, heading):
    start = text.index(f"**{heading}**\n")
    end = text.find("\n\n**", start)
    return text[start:end if end > 0 else None].rstrip("\n")


def gap_line(text, label):
    return next(line for line in text.splitlines() if line.startswith(f"**{label}:**"))


def entry(key, title="Metric A", severity="Medium", when="watch", link="https://example.test/metric-a", last_value="10", **extra):
    return {"key": key, "rank": None, "title": title, "severity": severity, "when": when, "link": link, "last_value": last_value, **extra}


def open_entries(*titles):
    return [{"key": f"open-{index}", "title": title} for index, title in enumerate(titles)]


def make_summary(**parts):
    summary = {
        "new": [], "escalated": [], "resolved": [], "still_open": {level: [] for level in digest.LEVELS}, "muted_changes": 0,
        "blind_spots": [], "blind_spots_dropped": 0, "overrides": [], "cut": None,
    }
    summary.update(parts)
    return summary


def make_next(items=None, previous_at=PREVIOUS_AT, window_from=WINDOW_FROM):
    document = fixtures.make_state(items=items)
    document["run"].update({"previous_at": previous_at, "window": {"from_ts": fixtures.ts(window_from), "to_ts": fixtures.ts(RUN_AT)}})
    return document


def state_of(summary, items=None):
    held = {entry["key"]: fixtures.make_item(title=entry["title"]) for level in digest.LEVELS for entry in summary["still_open"][level]}
    return make_next({**held, **(items or {})})


def make_record(run_at=RUN_AT):
    return {"run_at": run_at, **{name: [] for name in digest.RECORD_LISTS}}


def make_base(collected=ALL_READ):
    return {"run_context": {"collected": collected}}


def golden_documents():
    analysis = {
        "risk": "Jobs of service A fail above their availability budget and the sync reaches customers late.",
        "reason": [
            {"tag": "measured", "claim": "The monitor went to Alert at 13:12 Paris and is still in Alert."},
            {"tag": "inferred", "claim": "A failing job type is the likely cause, since the dead-letter queue holds 2350 messages."},
        ],
        "mitigation": ["Check the job error logs since 11:12Z", "Inspect the dead-letter queue for the failing message type"],
        "action": "Open the monitor and name the job that burns the budget.",
    }
    summary = make_summary(
        new=[entry("monitor-1001", "[P2][svc-a][prod] Jobs availability slow burn", when="now", rank=1, last_value="Alert", link="https://monitoring.example.test/monitors/1001", **analysis)],
        escalated=[
            entry(
                "monitor-1002", "Service B API latency fast burn", severity="High", when="within months", rank=2, last_value="Alert",
                link="https://monitoring.example.test/monitors/1002", risk="Screens of service B load slowly.",
                reason=[{"tag": "measured", "claim": "The monitor flipped 44 times between 09:35 and 13:41 Paris."}],
                mitigation=["Check p95 latency by endpoint"], action="Compare the monitor graph with the slow burn monitor.",
            ),
            entry(
                "metric-queue-depth", "Service C queue depth (top queue)", rank=3, last_value="412",
                link="https://monitoring.example.test/metric/explorer?query=max:queue.depth", action="Page the owner of the queue.",
            ),
        ],
        resolved=[
            entry(
                "metric-db-capacity", "Service D database writer at 80 capacity units two hours in a row", last_value="2.533",
                link="https://monitoring.example.test/metric/explorer?query=max:db.capacity{host:writer-1}.rollup(max, 3600)",
            ),
            entry("monitor-1003", "Service E API latency slow burn", last_value="OK", link="https://monitoring.example.test/monitors/1003"),
        ],
        still_open={
            "High": [],
            "Medium": open_entries("Queue depth on service F", "Service G write throttling", "Service H messages in DLQ", "Service I error rate", "Service J p95 latency"),
            "Low": open_entries("Service K job duration", "Service L cold start rate"),
        },
        muted_changes=3,
        blind_spots=[
            {"key": "monitor-1006", "gap": "no datapoints", "runs": 1},
            {"key": "gap-a", "gap": "no datapoints", "runs": 13},
            {"key": "chat", "gap": "no read", "runs": 2},
        ],
        blind_spots_dropped=1,
        overrides=[
            {"key": "monitor-1004", "title": "Service M gateway high 4xx rate", "state": "Warn"},
            {"key": "monitor-1005", "title": "Service N request latency", "state": "No Data"},
        ],
        cut={"from_ts": fixtures.ts("2026-10-16T07:00:00Z"), "to_ts": fixtures.ts("2026-10-17T07:00:00Z")},
    )
    items = {
        "monitor-1001": fixtures.make_item(since="2026-10-19T11:12:00Z"),
        "monitor-1002": fixtures.make_item(since="2026-10-16T07:32:00Z"),
        "metric-queue-depth": fixtures.make_item(since="not recorded"),
        "monitor-1006": fixtures.make_item(title="Service O replication lag"),
    }
    collected = {
        "chat": {"role": "chat_channel", "transport": "mcp", "read": False, "reason": "credentials missing: TOKEN"},
        "monitors": ALL_READ["monitors"],
        "sources-page": {"role": "document_store", "transport": "mcp", "read": False, "reason": None},
    }
    return {"summary": summary, "document": state_of(summary, items), "record": make_record(), "base": make_base(collected)}


class DigestCase(unittest.TestCase):
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

    def apply(self, previous_state, facts, window=None):
        code, _, err = fixtures.run_cli(
            "apply", "--state", self.write("state.json", previous_state), "--facts", self.write("facts.json", facts),
            "--window", self.write("window.json", window or fixtures.make_window()), "--tz", fixtures.TZ,
            "--out", self.path("next.json"), "--summary", self.path("summary.json"), "--record", self.path("record.json"),
        )
        self.assertEqual((code, err), (0, ""))

    def write_base(self, collected=None):
        base = {name: value for name, value in fixtures.make_facts().items() if name != "observations"}
        context = fixtures.make_run_context()
        if collected is not None:
            context["collected"] = collected
        base["run_context"] = context
        state.check_facts({**base, "observations": {}})
        self.write("base.json", base)

    def run_digest(self, out="digest.md", tz=fixtures.TZ, **paths):
        flags = {"summary": "summary.json", "state": "next.json", "record": "record.json", "base": "base.json", **paths}
        argv = [item for name, value in flags.items() for item in (f"--{name}", self.path(value))]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = digest.main(argv + ["--tz", tz, "--out", self.path(out)])
        return code, err.getvalue()

    def render(self, previous_state=None, facts=None, window=None, collected=None):
        self.apply(previous_state or fixtures.make_state(), facts or fixtures.make_facts(), window)
        self.write_base(collected)
        self.assertEqual(self.run_digest(), (0, ""))
        return self.read_bytes("digest.md").decode()

    def write_documents(self, summary=None, document=None, record=None, base=None):
        summary = summary or make_summary()
        self.write("summary.json", summary)
        self.write("next.json", document or state_of(summary))
        self.write("record.json", record or make_record())
        self.write("base.json", base or make_base())

    def render_documents(self, summary=None, document=None, record=None, base=None, tz=fixtures.TZ):
        self.write_documents(summary, document, record, base)
        self.assertEqual(self.run_digest(tz=tz), (0, ""))
        return self.read_bytes("digest.md").decode()

    def render_new(self, *entries, items=None):
        return self.render_documents(make_summary(new=list(entries)), make_next(items))


class GoldenTest(DigestCase):
    def test_renders_the_golden_message(self):
        with open(GOLDEN, encoding="utf-8") as handle:
            golden = handle.read()
        self.assertEqual(self.render_documents(**golden_documents()), golden)


class TitleTest(DigestCase):
    def test_title_names_the_digest_the_run_time_and_the_window_start(self):
        text = self.render()
        self.assertEqual(text.splitlines()[:2], ["**Prod watch, 01 Jun 13:00 Paris**", "(since Mon 12:00)"])

    def test_title_of_a_first_run_is_a_baseline(self):
        text = self.render(fixtures.make_state(at=None))
        self.assertEqual(text.splitlines()[:2], ["**Prod watch, 01 Jun 13:00 Paris**", "(baseline)"])

    def test_title_of_a_state_without_a_window_is_a_baseline(self):
        document = make_next(previous_at=None)
        document["run"]["window"] = None
        self.assertEqual(self.render_documents(document=document).splitlines()[1], "(baseline)")

    def test_report_only_title_shows_the_run_time_of_the_record_and_the_window_of_the_stored_state(self):
        text = self.render(facts=fixtures.make_facts({"metric-a": fixtures.obs()}), window=fixtures.make_window(explicit=True))
        self.assertEqual(text.splitlines()[:2], ["**Prod watch, 01 Jun 13:00 Paris**", "(since Mon 11:00)"])

    def test_title_takes_the_digest_name_of_the_state(self):
        document = make_next()
        document["digest"] = "Checkout watch"
        self.assertEqual(self.render_documents(document=document).splitlines()[0], "**Checkout watch, 19 Oct 13:32 Paris**")

    def test_run_in_winter_time_is_one_hour_from_utc(self):
        document = make_next(window_from="2026-01-15T08:30:00Z")
        text = self.render_documents(document=document, record=make_record("2026-01-15T12:00:00Z"))
        self.assertEqual(text.splitlines()[:2], ["**Prod watch, 15 Jan 13:00 Paris**", "(since Thu 09:30)"])

    def test_run_in_summer_time_is_two_hours_from_utc(self):
        document = make_next(window_from="2026-07-15T08:30:00Z")
        text = self.render_documents(document=document, record=make_record("2026-07-15T12:00:00Z"))
        self.assertEqual(text.splitlines()[:2], ["**Prod watch, 15 Jul 14:00 Paris**", "(since Wed 10:30)"])

    def test_city_is_the_last_segment_of_the_zone_with_spaces_for_underscores(self):
        text = self.render_documents(record=make_record("2026-01-15T12:00:00Z"), tz="America/New_York")
        self.assertEqual(text.splitlines()[0], "**Prod watch, 15 Jan 07:00 New York**")


class ChangeTest(DigestCase):
    def test_new_item_is_a_block_with_mark_details_and_analysis(self):
        facts = fixtures.make_facts({"metric-a": fixtures.obs(severity="High", when="now", rank=1, **fixtures.make_analysis())})
        expected = (
            "**New**\n"
            "🔴 **Metric A**\n"
            "High · now · since 13:00 · [metric](https://example.test/metric-a)\n"
            "- **Risk:** queue grows\n"
            "- **Reason:** error rate doubled (measured); a deploy changed the consumer (inferred)\n"
            "- **Mitigation:** roll back the consumer; scale the workers; pause the producer\n"
            "- **Action:** restart the consumer"
        )
        self.assertEqual(section(self.render(facts=facts), "New"), expected)

    def test_new_items_keep_the_rank_order_of_the_summary_and_are_separated_by_a_blank_line(self):
        facts = fixtures.make_facts({
            "metric-a": fixtures.obs(title="Mid", rank=2),
            "metric-b": fixtures.obs(title="Zeta", rank=1),
            "metric-c": fixtures.obs(title="Alpha"),
        })
        expected = "\n\n".join(
            f"🟡 **{title}**\nMedium · watch · since 13:00 · [metric](https://example.test/metric-a)" for title in ("Zeta", "Mid", "Alpha")
        )
        self.assertEqual(section(self.render(facts=facts), "New"), "**New**\n" + expected)

    def test_escalated_item_is_a_block_with_the_arrow_before_the_mark_and_its_stored_since(self):
        previous = fixtures.make_state(items={"metric-a": fixtures.make_item()})
        facts = fixtures.make_facts({"metric-a": fixtures.obs(severity="High", rank=1, **fixtures.make_analysis(risk="orders are lost"))})
        text = section(self.render(previous, facts), "Escalated")
        self.assertEqual(
            text.splitlines()[:4],
            [
                "**Escalated**",
                "⬆️🟡 **Metric A**",
                "High · watch · since 30 May 10:00 · [metric](https://example.test/metric-a)",
                "- **Risk:** orders are lost",
            ],
        )

    def test_escalated_items_come_after_the_new_items_in_rank_order(self):
        previous = fixtures.make_state(items={"metric-a": fixtures.make_item(), "metric-b": fixtures.make_item(title="Metric B")})
        facts = fixtures.make_facts({
            "metric-a": fixtures.obs(severity="High", rank=2),
            "metric-b": fixtures.obs(severity="High", title="Metric B", rank=1),
            "metric-c": fixtures.obs(title="Metric C", rank=3),
        })
        heads = [line for line in self.render(previous, facts).splitlines() if line.endswith(("**Metric A**", "**Metric B**", "**Metric C**"))]
        self.assertEqual(heads, ["🟡 **Metric C**", "⬆️🟡 **Metric B**", "⬆️🟡 **Metric A**"])

    def test_each_urgency_has_its_mark(self):
        text = self.render_new(entry("a", "Now one", when="now"), entry("b", "Months one", when="within months"), entry("c", "Watch one"))
        heads = [line for line in text.splitlines() if line.endswith(("**Now one**", "**Months one**", "**Watch one**"))]
        self.assertEqual(heads, ["🔴 **Now one**", "🟠 **Months one**", "🟡 **Watch one**"])

    def test_escalated_item_keeps_the_arrow_before_each_mark(self):
        summary = make_summary(escalated=[entry("a", "Now one", when="now"), entry("b", "Months one", when="within months")])
        heads = [line for line in self.render_documents(summary).splitlines() if line.endswith(("**Now one**", "**Months one**"))]
        self.assertEqual(heads, ["⬆️🔴 **Now one**", "⬆️🟠 **Months one**"])

    def test_item_without_analysis_has_no_bullet(self):
        text = self.render(facts=fixtures.make_facts({"metric-a": fixtures.obs(rank=1)}))
        self.assertEqual(
            section(text, "New"), "**New**\n🟡 **Metric A**\nMedium · watch · since 13:00 · [metric](https://example.test/metric-a)"
        )

    def test_item_with_a_partial_analysis_shows_only_its_fields(self):
        facts = fixtures.make_facts({"metric-a": fixtures.obs(rank=1, action="restart the consumer")})
        self.assertEqual(section(self.render(facts=facts), "New").splitlines()[3:], ["- **Action:** restart the consumer"])

    def test_claim_ending_in_a_period_drops_it_before_its_tag(self):
        reason = [{"tag": "measured", "claim": "Error rate doubled.", "cites": {"value": 2}}]
        text = self.render_new(entry("a", reason=reason))
        self.assertEqual(section(text, "New").splitlines()[3:], ["- **Reason:** Error rate doubled (measured)"])

    def test_empty_reason_list_has_no_bullet(self):
        text = self.render_new(entry("a", risk="queue grows", reason=[]))
        self.assertEqual(section(text, "New").splitlines()[3:], ["- **Risk:** queue grows"])

    def test_resolved_item_is_one_line_with_label_link_and_last_value(self):
        previous = fixtures.make_state(items={"metric-a": fixtures.make_item(severity="High", when="now", runs=1)})
        text = self.render(previous, fixtures.make_facts({"metric-a": fixtures.obs(over=False)}))
        self.assertEqual(section(text, "Resolved"), "**Resolved**\n✅ **Metric A** · [metric](https://example.test/metric-a) · last value 10")

    def test_resolved_last_value_is_shown_as_json_and_null_as_not_available(self):
        summary = make_summary(resolved=[entry("a", "Number", last_value=1.5), entry("b", "Missing", last_value=None)])
        lines = section(self.render_documents(summary), "Resolved").splitlines()[1:]
        self.assertEqual([line.rsplit(" · ", 1)[1] for line in lines], ["last value 1.5", "last value n/a"])


class LinkTest(DigestCase):
    def label_and_destination(self, link):
        line = section(self.render_documents(make_summary(resolved=[entry("a", link=link)])), "Resolved").splitlines()[1]
        return line.split(" · ")[1]

    def test_monitor_link_is_labelled_with_the_monitor_id(self):
        self.assertEqual(self.label_and_destination("https://example.test/monitors/4242"), "[monitor 4242](https://example.test/monitors/4242)")

    def test_monitor_link_with_a_query_is_labelled_with_the_monitor_id(self):
        link = "https://example.test/monitors/4242?view=graph"
        self.assertEqual(self.label_and_destination(link), f"[monitor 4242]({link})")

    def test_other_link_is_labelled_metric(self):
        link = "https://example.test/metric/explorer?query=avg:cpu"
        self.assertEqual(self.label_and_destination(link), f"[metric]({link})")

    def test_monitor_path_inside_a_query_does_not_make_a_monitor_link(self):
        link = "https://example.test/metric/explorer?from=/monitors/42"
        self.assertEqual(self.label_and_destination(link), f"[metric]({link})")

    def test_monitor_path_with_a_non_numeric_id_is_labelled_metric(self):
        link = "https://example.test/monitors/create"
        self.assertEqual(self.label_and_destination(link), f"[metric]({link})")

    def test_backslash_of_the_destination_is_percent_encoded(self):
        link = "https://example.test/a\\b?query=c\\d"
        self.assertEqual(self.label_and_destination(link), "[metric](https://example.test/a%5Cb?query=c%5Cd)")

    def test_link_that_is_not_http_or_https_shows_the_label_alone(self):
        self.assertEqual(self.label_and_destination("javascript:alert(1)"), "metric")

    def test_relative_link_shows_the_label_alone(self):
        self.assertEqual(self.label_and_destination("/monitors/4242"), "monitor 4242")

    def test_empty_link_shows_the_label_alone(self):
        self.assertEqual(self.label_and_destination(""), "metric")

    def test_http_link_is_a_link(self):
        self.assertEqual(self.label_and_destination("http://example.test/monitors/4242"), "[monitor 4242](http://example.test/monitors/4242)")

    def test_parentheses_and_spaces_of_the_destination_are_percent_encoded(self):
        link = "https://example.test/explorer?query=max:a{b}.rollup(max, 3600)&live=false"
        expected = "[metric](https://example.test/explorer?query=max:a{b}.rollup%28max,%203600%29&live=false)"
        self.assertEqual(self.label_and_destination(link), expected)


def detail_line(text):
    return next(line for line in text.splitlines() if " · since " in line)


class SinceTest(DigestCase):
    def since_of(self, stored, run_at=RUN_AT):
        items = {"item-a": fixtures.make_item(since=stored)}
        text = self.render_documents(make_summary(new=[entry("item-a")]), make_next(items), make_record(run_at))
        return detail_line(text).split(" · ")[2]

    def test_since_on_the_day_of_the_run_shows_the_time_only(self):
        self.assertEqual(self.since_of("2026-10-19T09:00:00Z"), "since 11:00")

    def test_since_on_the_local_day_of_the_run_shows_the_time_only_even_when_the_utc_day_differs(self):
        self.assertEqual(self.since_of("2026-10-18T22:30:00Z"), "since 00:30")

    def test_since_on_another_day_shows_the_date_and_time(self):
        self.assertEqual(self.since_of("2026-10-16T07:32:00Z"), "since 16 Oct 09:32")

    def test_since_in_winter_time_is_one_hour_from_utc(self):
        self.assertEqual(self.since_of("2026-01-14T08:30:00Z", "2026-01-15T12:00:00Z"), "since 14 Jan 09:30")

    def test_since_in_winter_time_keeps_its_own_offset_when_the_run_is_in_summer_time(self):
        self.assertEqual(self.since_of("2026-01-15T09:00:00Z"), "since 15 Jan 10:00")

    def test_since_in_summer_time_keeps_its_own_offset_when_the_run_is_in_winter_time(self):
        self.assertEqual(self.since_of("2026-07-01T07:00:00Z", "2026-01-15T12:00:00Z"), "since 01 Jul 09:00")

    def test_since_that_is_not_a_utc_time_shows_as_stored(self):
        self.assertEqual(self.since_of("last Tuesday"), "since last Tuesday")

    def test_since_without_an_offset_shows_as_stored(self):
        self.assertEqual(self.since_of("2026-10-16 09:32"), "since 2026-10-16 09:32")

    def test_since_that_is_not_text_shows_as_json(self):
        self.assertEqual(self.since_of(1760000000), "since 1760000000")

    def test_since_of_a_key_missing_from_the_state_is_not_available(self):
        text = self.render_new(entry("item-a"), items={})
        self.assertEqual(detail_line(text).split(" · ")[2], "since n/a")

    def test_since_is_cleaned_like_any_text(self):
        self.assertEqual(self.since_of("see <@U123>"), "since see   U123 ")


class StillOpenTest(DigestCase):
    def test_still_open_items_are_one_bullet_per_severity_high_first(self):
        previous = fixtures.make_state(items={
            "metric-a": fixtures.make_item(title="Low one", severity="Low"),
            "metric-b": fixtures.make_item(title="High one", severity="High"),
        })
        facts = fixtures.make_facts({
            "metric-a": fixtures.obs(title="Low one", severity="Low", value=7),
            "metric-b": fixtures.obs(title="High one", severity="High", value=9),
        })
        self.assertEqual(section(self.render(previous, facts), "Still open (2)"), "**Still open (2)**\n- High: High one\n- Low: Low one")

    def test_more_than_three_items_of_a_severity_show_three_titles_then_the_rest_as_a_count(self):
        summary = make_summary(still_open={"High": [], "Medium": open_entries("A", "B", "C", "D", "E"), "Low": open_entries("F", "G")})
        expected = "**Still open (7)**\n- Medium: A, B, C, +2\n- Low: F, G"
        self.assertEqual(section(self.render_documents(summary), "Still open (7)"), expected)

    def test_exactly_three_items_have_no_count(self):
        summary = make_summary(still_open={"High": open_entries("A", "B", "C"), "Medium": [], "Low": []})
        self.assertEqual(section(self.render_documents(summary), "Still open (3)"), "**Still open (3)**\n- High: A, B, C")

    def test_still_open_total_counts_every_severity_in_the_summary_line(self):
        summary = make_summary(still_open={"High": open_entries("A"), "Medium": open_entries("B", "C", "D", "E"), "Low": open_entries("F")})
        self.assertEqual(section(self.render_documents(summary), "Summary"), "**Summary**\n- 0 new, 0 escalated, 0 resolved, 6 still open")

    def test_changed_items_are_not_listed_as_still_open(self):
        previous = fixtures.make_state(items={"metric-a": fixtures.make_item(runs=1)})
        facts = fixtures.make_facts({"metric-a": fixtures.obs(over=False), "metric-b": fixtures.obs(title="Metric B")})
        self.assertNotIn("Still open", self.render(previous, facts))

    def test_held_item_of_a_source_not_read_is_still_open(self):
        previous = fixtures.make_state(items={"metric-a": fixtures.make_item(title="Held")})
        text = self.render(previous, fixtures.make_facts(metrics=False))
        self.assertEqual(section(text, "Still open (1)"), "**Still open (1)**\n- Medium: Held")

    def test_muted_change_is_not_listed_as_still_open(self):
        facts = fixtures.make_facts({"metric-a": fixtures.obs()}, mutes=[{"key": "metric-a", "until": "2026-12-31"}])
        self.assertNotIn("Still open", self.render(facts=facts))

    def test_muted_unchanged_item_is_not_listed_as_still_open(self):
        previous = fixtures.make_state(items={"metric-a": fixtures.make_item()})
        facts = fixtures.make_facts({"metric-a": fixtures.obs()}, mutes=[{"key": "metric-a", "until": "2026-12-31"}])
        self.assertNotIn("Still open", self.render(previous, facts))

    def test_still_open_items_of_the_same_severity_follow_the_order_of_their_keys(self):
        previous = fixtures.make_state(items={
            "metric-b": fixtures.make_item(title="Second"),
            "metric-a": fixtures.make_item(title="First"),
        })
        facts = fixtures.make_facts({"metric-a": fixtures.obs(title="First"), "metric-b": fixtures.obs(title="Second")})
        self.assertEqual(section(self.render(previous, facts), "Still open (2)"), "**Still open (2)**\n- Medium: First, Second")

    def assert_still_open_key_refused(self):
        code, err = self.run_digest()
        self.assertEqual((code, "ghost-key" in err, os.path.exists(self.path("digest.md"))), (2, True, False))

    def test_still_open_key_missing_from_the_state_items_exits_2_naming_the_key(self):
        summary = make_summary(still_open={"High": [], "Medium": [{"key": "ghost-key", "title": "Ghost"}], "Low": []})
        self.write_documents(summary, make_next())
        self.assert_still_open_key_refused()

    def test_still_open_key_missing_from_the_state_items_exits_2_on_a_report_only_run(self):
        self.apply(fixtures.make_state(), fixtures.make_facts({"metric-a": fixtures.obs(rank=1)}), fixtures.make_window(explicit=True))
        self.write_base()
        summary = self.read("summary.json")
        summary["still_open"]["Low"] = [{"key": "ghost-key", "title": "Ghost"}]
        self.write("summary.json", summary)
        self.assert_still_open_key_refused()

    def test_summary_without_still_open_is_rejected(self):
        self.apply(fixtures.make_state(), fixtures.make_facts())
        summary = self.read("summary.json")
        del summary["still_open"]
        self.write("summary.json", summary)
        self.write_base()
        code, err = self.run_digest()
        self.assertEqual((code, "still_open" in err), (2, True))


class SummaryTest(DigestCase):
    def test_summary_counts_the_changes_and_the_open_items(self):
        previous = fixtures.make_state(items={
            "metric-a": fixtures.make_item(),
            "metric-b": fixtures.make_item(title="Metric B", runs=1),
            "metric-c": fixtures.make_item(title="Metric C"),
        })
        facts = fixtures.make_facts({
            "metric-a": fixtures.obs(severity="High", rank=1),
            "metric-b": fixtures.obs(title="Metric B", over=False),
            "metric-c": fixtures.obs(title="Metric C"),
            "metric-d": fixtures.obs(title="Metric D", rank=2),
            "metric-e": fixtures.obs(title="Metric E", rank=3),
        })
        self.assertEqual(
            section(self.render(previous, facts), "Summary"), "**Summary**\n- 2 new, 1 escalated, 1 resolved, 1 still open"
        )


class GapLineTest(DigestCase):
    def test_muted_changes_are_a_count(self):
        facts = fixtures.make_facts({"metric-a": fixtures.obs()}, mutes=[{"key": "metric-a", "until": "2026-12-31"}])
        self.assertEqual(gap_line(self.render(facts=facts), "Not shown"), "**Not shown:** 1 muted change")

    def test_several_muted_changes_are_plural(self):
        text = self.render_documents(make_summary(muted_changes=3))
        self.assertEqual(gap_line(text, "Not shown"), "**Not shown:** 3 muted changes")

    def test_dropped_blind_spots_are_a_count(self):
        facts = fixtures.make_facts(blind_spots=[{"key": f"gap-{index}", "gap": "no data"} for index in range(10)])
        self.assertEqual(gap_line(self.render(facts=facts), "Not shown"), "**Not shown:** 2 blind spots dropped")

    def test_both_counts_share_one_line(self):
        facts = fixtures.make_facts(
            {"metric-a": fixtures.obs()},
            mutes=[{"key": "metric-a", "until": "2026-12-31"}],
            blind_spots=[{"key": f"gap-{index}", "gap": "no data"} for index in range(9)],
        )
        self.assertEqual(gap_line(self.render(facts=facts), "Not shown"), "**Not shown:** 1 muted change, 1 blind spot dropped")

    def test_zero_counts_have_no_line(self):
        self.assertNotIn("Not shown", self.render())

    def test_blind_spots_show_their_gap_and_runs(self):
        previous = fixtures.make_state(blind_spots=[{"key": "metric-a", "gap": "no datapoints", "runs": 1}])
        facts = fixtures.make_facts(blind_spots=[{"key": "metric-a", "gap": "no datapoints"}, {"key": "metric-b", "gap": "not found"}])
        expected = "**Blind spots:** metric-a no datapoints (2 runs); metric-b not found (1 run)"
        self.assertEqual(gap_line(self.render(previous, facts, collected=ALL_READ), "Blind spots"), expected)

    def test_blind_spot_of_an_unread_source_is_shown_once_as_a_source_not_read(self):
        collected = {"chat": {"role": "chat_channel", "transport": "mcp", "read": False, "reason": "credentials missing: TOKEN"}}
        facts = fixtures.make_facts(blind_spots=[{"key": "chat", "gap": "no read"}, {"key": "metric-b", "gap": "not found"}])
        text = self.render(facts=facts, collected=collected)
        self.assertEqual(
            (gap_line(text, "Blind spots"), text.count("chat")),
            ("**Blind spots:** metric-b not found (1 run); chat not read (credentials missing: TOKEN)", 1),
        )

    def test_blind_spot_of_a_source_that_was_read_stays_listed(self):
        facts = fixtures.make_facts(blind_spots=[{"key": "monitors", "gap": "discovery incomplete"}])
        self.assertEqual(
            gap_line(self.render(facts=facts, collected=ALL_READ), "Blind spots"), "**Blind spots:** monitors discovery incomplete (1 run)"
        )

    def test_cut_is_the_weekday_and_time_of_its_end_in_the_zone(self):
        cut = {"from_ts": fixtures.ts("2026-05-28T08:00:00Z"), "to_ts": fixtures.ts("2026-05-29T10:00:00Z")}
        text = self.render(window=fixtures.make_window(cut=cut), collected=ALL_READ)
        self.assertEqual(gap_line(text, "Blind spots"), "**Blind spots:** metrics before Fri 12:00 not read")

    def test_cut_in_winter_time_is_one_hour_from_utc(self):
        cut = {"from_ts": fixtures.ts("2026-01-15T08:00:00Z"), "to_ts": fixtures.ts("2026-01-16T10:00:00Z")}
        text = self.render_documents(make_summary(cut=cut))
        self.assertEqual(gap_line(text, "Blind spots"), "**Blind spots:** metrics before Fri 11:00 not read")

    def test_unread_sources_show_their_reasons_and_skip_the_sources_read(self):
        collected = dict(fixtures.make_run_context()["collected"])
        collected["chat"] = {"role": "chat_channel", "transport": "mcp", "read": False, "reason": "credentials missing: TOKEN"}
        expected = "**Blind spots:** chat not read (credentials missing: TOKEN); sources_page not read (no collection)"
        self.assertEqual(gap_line(self.render(collected=collected), "Blind spots"), expected)

    def test_unread_source_without_a_reason_says_so(self):
        collected = {"chat": {"role": "chat_channel", "transport": "api", "read": False, "reason": None}}
        text = self.render_documents(base=make_base(collected))
        self.assertEqual(gap_line(text, "Blind spots"), "**Blind spots:** chat not read (no reason recorded)")

    def test_unread_sources_keep_the_order_of_their_names(self):
        collected = {
            "zeta": {"role": "chat_channel", "transport": "api", "read": False, "reason": "z"},
            "alpha": {"role": "chat_channel", "transport": "api", "read": False, "reason": "a"},
        }
        text = self.render_documents(base=make_base(collected))
        self.assertEqual(gap_line(text, "Blind spots"), "**Blind spots:** alpha not read (a); zeta not read (z)")

    def test_blind_spots_unread_sources_and_the_cut_share_one_line(self):
        summary = make_summary(
            blind_spots=[{"key": "gap-a", "gap": "no data", "runs": 13}],
            cut={"from_ts": fixtures.ts("2026-10-16T07:00:00Z"), "to_ts": fixtures.ts("2026-10-17T07:00:00Z")},
        )
        collected = {"chat": {"role": "chat_channel", "transport": "mcp", "read": False, "reason": "no token"}}
        text = self.render_documents(summary, base=make_base(collected))
        expected = "**Blind spots:** gap-a no data (13 runs); chat not read (no token); metrics before Sat 09:00 not read"
        self.assertEqual((gap_line(text, "Blind spots"), text.count("Blind spots")), (expected, 1))

    def test_no_gap_has_no_blind_spots_line(self):
        self.assertNotIn("Blind spots", self.render(collected=ALL_READ))

    def test_overrides_list_title_and_state_without_the_key(self):
        facts = fixtures.make_facts({"metric-a": fixtures.obs(over=False, last_value="Alert")}, overrides=["metric-a"])
        text = self.render(facts=facts)
        self.assertEqual((gap_line(text, "Overrides"), "metric-a" in text), ("**Overrides:** Metric A (Alert)", False))

    def test_overrides_are_joined_with_semicolons(self):
        overrides = [{"key": "k1", "title": "One", "state": "Warn"}, {"key": "k2", "title": "Two", "state": "No Data"}]
        text = self.render_documents(make_summary(overrides=overrides))
        self.assertEqual(gap_line(text, "Overrides"), "**Overrides:** One (Warn); Two (No Data)")

    def test_no_overrides_has_no_line(self):
        self.assertNotIn("Overrides", self.render())


class EmptyTest(DigestCase):
    def test_empty_inputs_render_the_title_and_the_summary_only(self):
        self.assertEqual(self.render_documents(), f"{TITLE_LINES}\n\n{EMPTY_SUMMARY}\n")

    def test_every_section_but_the_summary_is_skipped_when_empty(self):
        summary = make_summary(resolved=[entry("a", "Done")])
        text = self.render_documents(summary)
        self.assertEqual([line for line in text.splitlines() if line.startswith("**")], [
            "**Prod watch, 19 Oct 13:32 Paris**", "**Summary**", "**Resolved**",
        ])

    def test_summary_lists_zero_counts(self):
        self.assertEqual(section(self.render_documents(), "Summary"), EMPTY_SUMMARY)


class ItemKeyTest(DigestCase):
    def test_no_item_key_appears_in_the_message(self):
        summary = make_summary(
            new=[entry("key-new", "New one")],
            escalated=[entry("key-escalated", "Escalated one")],
            resolved=[entry("key-resolved", "Resolved one")],
            still_open={"High": [{"key": "key-open", "title": "Open one"}], "Medium": [], "Low": []},
            blind_spots=[{"key": "key-blind", "gap": "no data", "runs": 2}],
            overrides=[{"key": "key-override", "title": "Override one", "state": "Warn"}],
        )
        items = {"key-new": fixtures.make_item(), "key-escalated": fixtures.make_item(), "key-blind": fixtures.make_item(title="Blind one")}
        text = self.render_documents(summary, state_of(summary, items))
        keys = ("key-new", "key-escalated", "key-resolved", "key-open", "key-blind", "key-override")
        self.assertEqual([key for key in keys if key in text], [])

    def test_blind_spot_of_an_item_shows_its_title(self):
        summary = make_summary(blind_spots=[{"key": "monitor-7", "gap": "no datapoints", "runs": 3}])
        text = self.render_documents(summary, make_next({"monitor-7": fixtures.make_item(title="Service P latency")}))
        self.assertEqual(gap_line(text, "Blind spots"), "**Blind spots:** Service P latency no datapoints (3 runs)")

    def test_blind_spot_of_a_key_that_is_not_an_item_shows_the_key(self):
        text = self.render_documents(make_summary(blind_spots=[{"key": "gap-a", "gap": "no datapoints", "runs": 3}]))
        self.assertEqual(gap_line(text, "Blind spots"), "**Blind spots:** gap-a no datapoints (3 runs)")


class ReportOnlyTest(DigestCase):
    def test_report_only_run_lists_its_changes_over_the_unchanged_state(self):
        previous = fixtures.make_state(items={
            "metric-b": fixtures.make_item(title="Metric B", runs=1),
            "metric-c": fixtures.make_item(title="Metric C"),
        })
        facts = fixtures.make_facts({
            "metric-a": fixtures.obs(rank=1),
            "metric-b": fixtures.obs(title="Metric B", over=False),
            "metric-c": fixtures.obs(title="Metric C", value=11),
        })
        text = self.render(previous, facts, fixtures.make_window(explicit=True))
        self.assertEqual(self.read_bytes("next.json"), self.read_bytes("state.json"))
        self.assertEqual(section(text, "New").splitlines()[1:3], [
            "🟡 **Metric A**", "Medium · watch · since n/a · [metric](https://example.test/metric-a)",
        ])
        self.assertEqual(section(text, "Resolved").splitlines()[1], "✅ **Metric B** · [metric](https://example.test/metric-a) · last value 10")
        self.assertEqual(section(text, "Still open (1)"), "**Still open (1)**\n- Medium: Metric C")


class DeterminismTest(DigestCase):
    def test_same_inputs_give_byte_identical_output(self):
        facts = fixtures.make_facts(
            {"metric-a": fixtures.obs(rank=1, **fixtures.make_analysis()), "metric-b": fixtures.obs(title="Metric B")},
            blind_spots=[{"key": "gap", "gap": "no data"}],
        )
        self.render(facts=facts)
        first = self.read_bytes("digest.md")
        self.run_digest(out="again.md")
        self.assertEqual(self.read_bytes("again.md"), first)

    def test_output_does_not_depend_on_the_key_order_of_the_inputs(self):
        self.render(facts=fixtures.make_facts({"metric-a": fixtures.obs(rank=1)}))
        first = self.read_bytes("digest.md")
        base = self.read("base.json")
        base["run_context"]["collected"] = dict(reversed(list(base["run_context"]["collected"].items())))
        self.write("base.json", base)
        self.run_digest(out="again.md")
        self.assertEqual(self.read_bytes("again.md"), first)

    def test_output_is_utf8_with_a_final_newline_and_no_carriage_return(self):
        facts = fixtures.make_facts({"metric-a": fixtures.obs(title="Débit élevé", rank=1)})
        self.render(facts=facts)
        data = self.read_bytes("digest.md")
        self.assertEqual((data.endswith(b"\n"), b"\r" in data, "Débit élevé" in data.decode("utf-8")), (True, False, True))


class TextSourceTest(DigestCase):
    def test_text_outside_the_rendered_fields_never_reaches_the_output(self):
        self.apply(fixtures.make_state(), fixtures.make_facts({"metric-a": fixtures.obs(rank=1)}))
        summary = self.read("summary.json")
        summary["note"] = "CANARY-SUMMARY"
        summary["new"][0]["extra"] = "CANARY-ENTRY"
        document = self.read("next.json")
        document["note"] = "CANARY-STATE"
        document["items"]["metric-a"]["notes"] = "CANARY-ITEM"
        record = self.read("record.json")
        record["note"] = "CANARY-RECORD"
        record["digest"] = "CANARY-RECORD-NAME"
        self.write("summary.json", summary)
        self.write("next.json", document)
        self.write("record.json", record)
        base = {"run_context": {"collected": ALL_READ, "place": "local", "note": "CANARY-BASE"}, "stray": "CANARY-STRAY"}
        self.write("base.json", base)
        self.run_digest()
        text = self.read_bytes("digest.md").decode()
        self.assertEqual([word for word in ("SUMMARY", "ENTRY", "STATE", "ITEM", "RECORD", "BASE", "STRAY") if f"CANARY-{word}" in text], [])

    def test_unread_reason_is_cleaned_of_mentions_markup_and_line_breaks(self):
        collected = {"chat": {"role": "chat_channel", "transport": "api", "read": False, "reason": "see <@U123> now\nrun x y"}}
        text = self.render(collected=collected)
        self.assertEqual(gap_line(text, "Blind spots"), "**Blind spots:** chat not read (see   U123  now run x y)")

    def test_title_mention_is_neutralised(self):
        facts = fixtures.make_facts({"metric-a": fixtures.obs(title="Page @here now", rank=1)})
        self.assertNotIn("@", self.render(facts=facts))

    def test_link_markup_is_neutralised(self):
        text = self.render_documents(make_summary(resolved=[entry("a", link="https://example.test/<@U123>")]))
        self.assertEqual(section(text, "Resolved").count("<"), 0)

    def test_link_opener_in_a_title_cannot_start_a_destination(self):
        text = self.render_new(entry("a", "Open [here](https://evil.example.test)"))
        self.assertEqual(section(text, "New").splitlines()[1], "🟡 **Open [here] (https://evil.example.test)**")

    def test_link_opener_in_the_risk_cannot_start_a_destination(self):
        text = self.render_new(entry("a", risk="See [here](https://evil.example.test)"))
        self.assertEqual(section(text, "New").splitlines()[3], "- **Risk:** See [here] (https://evil.example.test)")

    def test_bold_marker_in_a_title_cannot_close_the_bold_span(self):
        text = self.render_new(entry("a", "Done** and [click]"))
        self.assertEqual(section(text, "New").splitlines()[1], "🟡 **Done* * and [click]**")

    def test_brackets_of_a_title_stay_readable(self):
        text = self.render_new(entry("a", "[P2][svc-a] Slow"))
        self.assertEqual(section(text, "New").splitlines()[1], "🟡 **[P2][svc-a] Slow**")

    def test_unread_reason_is_capped(self):
        collected = {"chat": {"role": "chat_channel", "transport": "api", "read": False, "reason": "x" * 1000}}
        line = gap_line(self.render(collected=collected), "Blind spots")
        self.assertEqual(line, "**Blind spots:** chat not read (" + "x" * state.LABEL_CAP + ")")


class InputErrorTest(DigestCase):
    def ready(self):
        self.apply(fixtures.make_state(), fixtures.make_facts({"metric-a": fixtures.obs(rank=1)}))
        self.write_base()

    def assert_refused(self, name):
        code, err = self.run_digest()
        self.assertEqual((code, self.path(name) in err, os.path.exists(self.path("digest.md"))), (2, True, False))

    def test_missing_summary_exits_2_naming_the_file(self):
        self.ready()
        os.remove(self.path("summary.json"))
        self.assert_refused("summary.json")

    def test_missing_state_exits_2_naming_the_file(self):
        self.ready()
        os.remove(self.path("next.json"))
        self.assert_refused("next.json")

    def test_missing_record_exits_2_naming_the_file(self):
        self.ready()
        os.remove(self.path("record.json"))
        self.assert_refused("record.json")

    def test_record_without_a_run_time_exits_2_naming_the_file_and_the_key(self):
        self.ready()
        record = self.read("record.json")
        del record["run_at"]
        self.write("record.json", record)
        code, err = self.run_digest()
        self.assertEqual((code, self.path("record.json") in err, "run_at" in err), (2, True, True))

    def test_record_with_a_run_time_that_is_not_a_time_exits_2_naming_the_file(self):
        self.ready()
        record = self.read("record.json")
        record["run_at"] = "yesterday"
        self.write("record.json", record)
        self.assert_refused("record.json")

    def test_record_without_a_list_of_keys_exits_2_naming_the_file_and_the_key(self):
        self.ready()
        record = self.read("record.json")
        del record["muted"]
        self.write("record.json", record)
        code, err = self.run_digest()
        self.assertEqual((code, self.path("record.json") in err, "muted" in err), (2, True, True))

    def test_missing_base_exits_2_naming_the_file(self):
        self.ready()
        os.remove(self.path("base.json"))
        self.assert_refused("base.json")

    def test_invalid_json_exits_2_naming_the_file(self):
        self.ready()
        with open(self.path("summary.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assert_refused("summary.json")

    def test_summary_without_a_list_exits_2_naming_the_file_and_the_key(self):
        self.ready()
        summary = self.read("summary.json")
        del summary["blind_spots"]
        self.write("summary.json", summary)
        code, err = self.run_digest()
        self.assertEqual((code, self.path("summary.json") in err, "blind_spots" in err), (2, True, True))

    def test_summary_entry_with_a_bad_severity_exits_2_naming_the_file(self):
        self.ready()
        summary = self.read("summary.json")
        summary["new"][0]["severity"] = "Critical"
        self.write("summary.json", summary)
        self.assert_refused("summary.json")

    def test_cut_with_an_unrepresentable_time_exits_2_naming_the_file(self):
        self.ready()
        summary = self.read("summary.json")
        summary["cut"] = {"from_ts": 10**30, "to_ts": 10**30 + 1}
        self.write("summary.json", summary)
        self.assert_refused("summary.json")

    def test_state_of_another_schema_exits_2_naming_the_file(self):
        self.ready()
        document = self.read("next.json")
        document["schema"] = 1
        self.write("next.json", document)
        self.assert_refused("next.json")

    def test_state_with_a_digest_name_that_is_not_text_exits_2_naming_the_file(self):
        self.ready()
        document = self.read("next.json")
        document["digest"] = 7
        self.write("next.json", document)
        self.assert_refused("next.json")

    def test_base_without_the_run_context_exits_2_naming_the_file(self):
        self.ready()
        self.write("base.json", {})
        self.assert_refused("base.json")

    def test_unwritable_output_exits_2_naming_the_path(self):
        self.ready()
        out = os.path.join("missing-dir", "digest.md")
        code, err = self.run_digest(out=out)
        self.assertEqual((code, self.path(out) in err), (2, True))

    def test_refused_input_leaves_an_existing_output_untouched(self):
        self.ready()
        with open(self.path("digest.md"), "w", encoding="utf-8") as handle:
            handle.write("previous")
        os.remove(self.path("base.json"))
        self.run_digest()
        self.assertEqual(self.read_bytes("digest.md"), b"previous")

    def test_run_time_out_of_range_in_the_zone_exits_2_naming_the_flag(self):
        self.write_documents(record=make_record("9999-12-31T23:30:00Z"))
        code, err = self.run_digest()
        self.assertEqual((code, "--tz" in err, fixtures.TZ in err, os.path.exists(self.path("digest.md"))), (2, True, True, False))

    def test_cut_out_of_range_in_the_zone_exits_2_naming_the_flag(self):
        cut = {"from_ts": fixtures.ts("9999-12-31T22:00:00Z"), "to_ts": fixtures.ts("9999-12-31T23:30:00Z")}
        self.write_documents(make_summary(cut=cut))
        code, err = self.run_digest()
        self.assertEqual((code, "--tz" in err, os.path.exists(self.path("digest.md"))), (2, True, False))

    def test_missing_time_zone_flag_exits_2(self):
        self.ready()
        argv = [item for name in ("summary", "state", "record", "base") for item in (f"--{name}", self.path(f"{name}.json"))]
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
            digest.main(argv + ["--out", self.path("digest.md")])
        self.assertEqual(stop.exception.code, 2)

    def test_unknown_time_zone_exits_2_naming_the_flag(self):
        self.ready()
        code, err = self.run_digest(tz="Mars/Olympus")
        self.assertEqual((code, "--tz" in err, "Mars/Olympus" in err, os.path.exists(self.path("digest.md"))), (2, True, True, False))

    def test_state_window_start_that_is_not_a_time_exits_2_naming_the_file(self):
        self.ready()
        document = self.read("next.json")
        document["run"]["window"]["from_ts"] = "monday"
        self.write("next.json", document)
        self.assert_refused("next.json")


class ParserTest(unittest.TestCase):
    def test_parser_takes_the_six_documented_flags(self):
        options = {option for action in digest.build_parser()._actions for option in action.option_strings}
        self.assertEqual(options, {"-h", "--help", "--summary", "--state", "--record", "--base", "--tz", "--out"})


class ScriptTest(DigestCase):
    def test_script_renders_the_digest_with_exit_0(self):
        self.apply(fixtures.make_state(), fixtures.make_facts({"metric-a": fixtures.obs(rank=1)}))
        self.write_base()
        result = subprocess.run(
            [
                sys.executable, "-B", os.path.join(HERE, "digest.py"), "--summary", self.path("summary.json"),
                "--state", self.path("next.json"), "--record", self.path("record.json"), "--base", self.path("base.json"),
                "--tz", fixtures.TZ, "--out", self.path("digest.md"),
            ],
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual((result.returncode, result.stderr, result.stdout), (0, "", ""))
        self.assertIn("🟡 **Metric A**", self.read_bytes("digest.md").decode())


LONG = "Risk text that runs long enough to fill a chat message quickly " * 4


def long_entry(index):
    return entry(
        f"metric-{index}", title=f"Metric {index}", risk=LONG.strip(), reason=[{"claim": LONG.strip(), "tag": "measured"}],
        mitigation=["Review the threshold of the monitor"], action="Check the source of the change",
    )


class PartsTest(DigestCase):
    def parts(self):
        names = [f"digest.md", *(f"digest.{number}.md" for number in range(2, 100) if os.path.exists(self.path(f"digest.{number}.md")))]
        return [self.read_bytes(name).decode() for name in names]

    def test_writes_a_digest_that_fits_in_one_file(self):
        self.render_new(entry("metric-a"))

        self.assertFalse(os.path.exists(self.path("digest.2.md")))

    def test_writes_a_long_digest_in_parts_within_the_cap(self):
        self.render_new(*[long_entry(index) for index in range(14)])

        parts = self.parts()
        self.assertEqual((len(parts) > 1, [len(part) for part in parts if len(part.rstrip("\n")) > state.MESSAGE_PART_CAP]), (True, []))

    def test_cuts_a_long_digest_between_its_blocks(self):
        summary = make_summary(new=[long_entry(index) for index in range(14)])
        self.render_documents(summary, make_next())

        whole = digest.render(summary, make_next(), make_record(), make_base(), state.load_zone(fixtures.TZ))
        self.assertEqual("\n\n".join(part.rstrip("\n") for part in self.parts()) + "\n", whole)


if __name__ == "__main__":
    unittest.main()
