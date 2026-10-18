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
ALL_READ = {"monitors": {"role": "observability", "transport": "api", "read": True, "reason": None}}


def section(text, heading):
    start = text.index(f"## {heading}\n")
    end = text.find("\n\n## ", start)
    return text[start:end if end > 0 else None].rstrip("\n")


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

    def run_digest(self, out="digest.md", **paths):
        flags = {"summary": "summary.json", "state": "next.json", "record": "record.json", "base": "base.json", **paths}
        argv = [item for name, value in flags.items() for item in (f"--{name}", self.path(value))]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = digest.main(argv + ["--out", self.path(out)])
        return code, err.getvalue()

    def render(self, previous_state=None, facts=None, window=None, collected=None):
        self.apply(previous_state or fixtures.make_state(), facts or fixtures.make_facts(), window)
        self.write_base(collected)
        self.assertEqual(self.run_digest(), (0, ""))
        with open(self.path("digest.md"), encoding="utf-8") as handle:
            return handle.read()


class TitleTest(DigestCase):
    def test_title_line_names_the_digest_and_the_run_time(self):
        text = self.render()
        self.assertEqual(text.splitlines()[0], "# Prod watch, 2026-06-01T11:00:00Z")

    def test_title_line_has_the_run_time_for_a_state_that_never_ran(self):
        text = self.render(fixtures.make_state(at=None), window=fixtures.make_window(explicit=True))
        self.assertEqual(text.splitlines()[0], "# Prod watch, 2026-06-01T11:00:00Z")

    def test_title_line_takes_the_digest_name_of_the_state(self):
        self.apply(fixtures.make_state(), fixtures.make_facts())
        document = self.read("next.json")
        document["digest"] = "Checkout watch"
        self.write("next.json", document)
        self.write_base()
        self.run_digest()
        self.assertEqual(self.read_bytes("digest.md").decode().splitlines()[0], "# Checkout watch, 2026-06-01T11:00:00Z")


class ChangeTest(DigestCase):
    def test_new_item_shows_severity_urgency_link_and_analysis(self):
        facts = fixtures.make_facts({"metric-a": fixtures.obs(severity="High", when="now", rank=1, **fixtures.make_analysis())})
        expected = (
            "## New\n\n"
            "- Metric A (High, now)\n"
            "  - Link: https://example.test/metric-a\n"
            "  - Risk: queue grows\n"
            "  - Reason:\n"
            "    - measured: error rate doubled\n"
            "    - inferred: a deploy changed the consumer\n"
            "  - Mitigation:\n"
            "    - roll back the consumer\n"
            "    - scale the workers\n"
            "    - pause the producer\n"
            "  - Action: restart the consumer"
        )
        self.assertEqual(section(self.render(facts=facts), "New"), expected)

    def test_new_items_keep_the_rank_order_of_the_summary(self):
        facts = fixtures.make_facts({
            "metric-a": fixtures.obs(title="Mid", rank=2),
            "metric-b": fixtures.obs(title="Zeta", rank=1),
            "metric-c": fixtures.obs(title="Alpha"),
        })
        lines = [line for line in section(self.render(facts=facts), "New").splitlines() if line.startswith("- ")]
        self.assertEqual(lines, ["- Zeta (Medium, watch)", "- Mid (Medium, watch)", "- Alpha (Medium, watch)"])

    def test_escalated_items_come_after_the_new_items_in_rank_order_with_their_analysis(self):
        previous = fixtures.make_state(items={"metric-a": fixtures.make_item(), "metric-b": fixtures.make_item(title="Metric B")})
        facts = fixtures.make_facts({
            "metric-a": fixtures.obs(severity="High", rank=2, **fixtures.make_analysis(risk="orders are lost")),
            "metric-b": fixtures.obs(severity="High", title="Metric B", rank=1, **fixtures.make_analysis(risk="users wait")),
            "metric-c": fixtures.obs(title="Metric C", rank=3),
        })
        text = self.render(previous, facts)
        titles = [line for line in text.splitlines() if line.startswith("- ")]
        self.assertEqual(titles[:3], ["- Metric C (Medium, watch)", "- Metric B (High, watch)", "- Metric A (High, watch)"])
        self.assertLess(text.index("## New"), text.index("## Escalated"))
        self.assertEqual(section(text, "Escalated").count("  - Risk: "), 2)

    def test_item_without_analysis_shows_no_analysis_line(self):
        text = self.render(facts=fixtures.make_facts({"metric-a": fixtures.obs(rank=1)}))
        self.assertEqual(
            section(text, "New"), "## New\n\n- Metric A (Medium, watch)\n  - Link: https://example.test/metric-a"
        )

    def test_item_with_a_partial_analysis_shows_only_its_fields(self):
        facts = fixtures.make_facts({"metric-a": fixtures.obs(rank=1, action="restart the consumer")})
        self.assertEqual(section(self.render(facts=facts), "New").splitlines()[-1], "  - Action: restart the consumer")

    def test_resolved_items_show_title_severity_urgency_and_link(self):
        previous = fixtures.make_state(items={"metric-a": fixtures.make_item(severity="High", when="now", runs=1)})
        text = self.render(previous, fixtures.make_facts({"metric-a": fixtures.obs(over=False)}))
        self.assertEqual(
            section(text, "Resolved"), "## Resolved\n\n- Metric A (High, now)\n  - Link: https://example.test/metric-a"
        )


class StillOpenTest(DigestCase):
    def test_still_open_items_are_grouped_by_severity_with_since_last_value_and_link(self):
        previous = fixtures.make_state(items={
            "metric-a": fixtures.make_item(title="Low one", severity="Low"),
            "metric-b": fixtures.make_item(title="High one", severity="High"),
        })
        facts = fixtures.make_facts({
            "metric-a": fixtures.obs(title="Low one", severity="Low", value=7),
            "metric-b": fixtures.obs(title="High one", severity="High", value=9),
        })
        expected = (
            "## Still open\n\n"
            "### High\n\n"
            "- High one: since 2026-05-30T08:00:00Z, last value 9, https://example.test/metric-a\n\n"
            "### Low\n\n"
            "- Low one: since 2026-05-30T08:00:00Z, last value 7, https://example.test/metric-a"
        )
        self.assertEqual(section(self.render(previous, facts), "Still open"), expected)

    def test_still_open_item_shows_only_the_action_of_its_stored_analysis(self):
        previous = fixtures.make_state(items={"metric-a": fixtures.make_item(**fixtures.make_analysis())})
        text = self.render(previous, fixtures.make_facts({"metric-a": fixtures.obs()}))
        block = section(text, "Still open")
        self.assertEqual((block.splitlines()[-1], "queue grows" in block, "roll back" in block), ("  - Action: restart the consumer", False, False))

    def test_still_open_item_without_a_stored_action_has_no_action_line(self):
        previous = fixtures.make_state(items={"metric-a": fixtures.make_item()})
        text = self.render(previous, fixtures.make_facts({"metric-a": fixtures.obs()}))
        self.assertNotIn("Action", section(text, "Still open"))

    def test_changed_items_are_not_listed_as_still_open(self):
        previous = fixtures.make_state(items={"metric-a": fixtures.make_item(runs=1)})
        facts = fixtures.make_facts({"metric-a": fixtures.obs(over=False), "metric-b": fixtures.obs(title="Metric B")})
        self.assertNotIn("## Still open", self.render(previous, facts))

    def test_changed_item_sharing_a_title_with_a_still_open_item_does_not_lend_its_details(self):
        previous = fixtures.make_state(items={
            "metric-a": fixtures.make_item(title="Same", link="https://example.test/a"),
            "metric-b": fixtures.make_item(title="Same", link="https://example.test/b"),
        })
        facts = fixtures.make_facts({
            "metric-a": fixtures.obs(title="Same", severity="High", link="https://example.test/a"),
            "metric-b": fixtures.obs(title="Same", link="https://example.test/b"),
        })
        line = section(self.render(previous, facts), "Still open").splitlines()[-1]
        self.assertEqual(line, "- Same: since 2026-05-30T08:00:00Z, last value 10, https://example.test/b")

    def test_held_item_of_a_source_not_read_is_still_open(self):
        previous = fixtures.make_state(items={"metric-a": fixtures.make_item(title="Held")})
        text = self.render(previous, fixtures.make_facts(metrics=False))
        self.assertIn("- Held: since 2026-05-30T08:00:00Z, last value 10, https://example.test/metric-a", section(text, "Still open"))

    def test_muted_change_is_not_listed_as_still_open(self):
        facts = fixtures.make_facts({"metric-a": fixtures.obs()}, mutes=[{"key": "metric-a", "until": "2026-12-31"}])
        self.assertNotIn("## Still open", self.render(facts=facts))

    def test_still_open_items_of_the_same_severity_follow_the_order_of_their_keys(self):
        previous = fixtures.make_state(items={
            "metric-b": fixtures.make_item(title="Second"),
            "metric-a": fixtures.make_item(title="First"),
        })
        facts = fixtures.make_facts({"metric-a": fixtures.obs(title="First"), "metric-b": fixtures.obs(title="Second")})
        lines = [line for line in section(self.render(previous, facts), "Still open").splitlines() if line.startswith("- ")]
        self.assertEqual([line.split(":")[0] for line in lines], ["- First", "- Second"])

    def test_muted_unchanged_item_is_not_listed_as_still_open(self):
        previous = fixtures.make_state(items={"metric-a": fixtures.make_item()})
        facts = fixtures.make_facts({"metric-a": fixtures.obs()}, mutes=[{"key": "metric-a", "until": "2026-12-31"}])
        self.assertNotIn("## Still open", self.render(previous, facts))

    def test_still_open_items_are_the_summary_keys_with_their_details_taken_from_the_state(self):
        previous = fixtures.make_state(items={
            "metric-a": fixtures.make_item(title="Kept"),
            "metric-b": fixtures.make_item(title="Left out"),
        })
        self.apply(previous, fixtures.make_facts({"metric-a": fixtures.obs(title="Kept"), "metric-b": fixtures.obs(title="Left out")}))
        summary = self.read("summary.json")
        summary["still_open"]["Medium"] = [{"key": "metric-a", "title": "Kept"}]
        self.write("summary.json", summary)
        document = self.read("next.json")
        document["items"]["metric-a"].update({"since": "2026-05-01T08:00:00Z", "last_value": 3, "link": "https://example.test/stored", "action": "page the owner"})
        self.write("next.json", document)
        self.write_base()
        self.run_digest()
        expected = (
            "## Still open\n\n"
            "### Medium\n\n"
            "- Kept: since 2026-05-01T08:00:00Z, last value 3, https://example.test/stored\n"
            "  - Action: page the owner"
        )
        self.assertEqual(section(self.read_bytes("digest.md").decode(), "Still open"), expected)

    def test_summary_key_missing_from_the_state_is_rejected_with_its_key(self):
        self.apply(fixtures.make_state(), fixtures.make_facts())
        summary = self.read("summary.json")
        summary["still_open"]["High"] = [{"key": "metric-z", "title": "Gone"}]
        self.write("summary.json", summary)
        self.write_base()
        code, err = self.run_digest()
        self.assertEqual((code, "metric-z" in err, os.path.exists(self.path("digest.md"))), (2, True, False))

    def test_summary_without_still_open_is_rejected(self):
        self.apply(fixtures.make_state(), fixtures.make_facts())
        summary = self.read("summary.json")
        del summary["still_open"]
        self.write("summary.json", summary)
        self.write_base()
        code, err = self.run_digest()
        self.assertEqual((code, "still_open" in err), (2, True))


class FooterTest(DigestCase):
    def test_muted_changes_are_a_count(self):
        facts = fixtures.make_facts({"metric-a": fixtures.obs()}, mutes=[{"key": "metric-a", "until": "2026-12-31"}])
        self.assertEqual(section(self.render(facts=facts), "Not shown"), "## Not shown\n\n- Muted changes: 1")

    def test_dropped_blind_spots_are_a_count(self):
        facts = fixtures.make_facts(blind_spots=[{"key": f"gap-{index}", "gap": "no data"} for index in range(10)])
        self.assertEqual(section(self.render(facts=facts), "Not shown"), "## Not shown\n\n- Blind spots dropped: 2")

    def test_both_counts_share_one_section(self):
        facts = fixtures.make_facts(
            {"metric-a": fixtures.obs()},
            mutes=[{"key": "metric-a", "until": "2026-12-31"}],
            blind_spots=[{"key": f"gap-{index}", "gap": "no data"} for index in range(9)],
        )
        self.assertEqual(
            section(self.render(facts=facts), "Not shown"), "## Not shown\n\n- Muted changes: 1\n- Blind spots dropped: 1"
        )

    def test_zero_counts_have_no_section(self):
        self.assertNotIn("## Not shown", self.render())

    def test_blind_spots_show_their_gap_and_runs(self):
        previous = fixtures.make_state(blind_spots=[{"key": "metric-a", "gap": "no datapoints", "runs": 1}])
        facts = fixtures.make_facts(blind_spots=[{"key": "metric-a", "gap": "no datapoints"}, {"key": "metric-b", "gap": "not found"}])
        expected = "## Blind spots\n\n- metric-a: no datapoints (runs: 2)\n- metric-b: not found (runs: 1)"
        self.assertEqual(section(self.render(previous, facts), "Blind spots"), expected)

    def test_blind_spot_of_an_unread_source_is_shown_once_under_unread_sources(self):
        collected = {"chat": {"role": "chat_channel", "transport": "mcp", "read": False, "reason": "credentials missing: TOKEN"}}
        facts = fixtures.make_facts(blind_spots=[{"key": "chat", "gap": "no read"}, {"key": "metric-b", "gap": "not found"}])
        text = self.render(facts=facts, collected=collected)
        self.assertEqual(
            (section(text, "Blind spots"), section(text, "Unread sources"), text.count("chat")),
            ("## Blind spots\n\n- metric-b: not found (runs: 1)", "## Unread sources\n\n- chat: credentials missing: TOKEN", 1),
        )

    def test_blind_spots_have_no_section_when_every_gap_is_an_unread_source(self):
        collected = {"chat": {"role": "chat_channel", "transport": "mcp", "read": False, "reason": "no collection"}}
        facts = fixtures.make_facts(blind_spots=[{"key": "chat", "gap": "no read"}])
        self.assertNotIn("## Blind spots", self.render(facts=facts, collected=collected))

    def test_blind_spot_of_a_source_that_was_read_stays_listed(self):
        facts = fixtures.make_facts(blind_spots=[{"key": "monitors", "gap": "discovery incomplete"}])
        self.assertIn("- monitors: discovery incomplete (runs: 1)", self.render(facts=facts, collected=ALL_READ))

    def test_cut_span_shows_the_unread_range_in_utc(self):
        cut = {"from_ts": fixtures.ts("2026-05-28T08:00:00Z"), "to_ts": fixtures.ts("2026-05-29T10:00:00Z")}
        text = self.render(window=fixtures.make_window(cut=cut))
        self.assertEqual(section(text, "Cut"), "## Cut\n\n- Not read: 2026-05-28T08:00:00Z to 2026-05-29T10:00:00Z")

    def test_no_cut_has_no_section(self):
        self.assertNotIn("## Cut", self.render())

    def test_unread_sources_show_their_reasons_and_skip_the_sources_read(self):
        collected = dict(fixtures.make_run_context()["collected"])
        collected["chat"] = {"role": "chat_channel", "transport": "mcp", "read": False, "reason": "credentials missing: TOKEN"}
        expected = "## Unread sources\n\n- chat: credentials missing: TOKEN\n- sources_page: no collection"
        self.assertEqual(section(self.render(collected=collected), "Unread sources"), expected)

    def test_unread_sources_have_no_section_when_every_source_was_read(self):
        self.assertNotIn("## Unread sources", self.render(collected=ALL_READ))

    def test_unread_sources_keep_the_order_of_their_names(self):
        collected = {
            "zeta": {"role": "chat_channel", "transport": "api", "read": False, "reason": "z"},
            "alpha": {"role": "chat_channel", "transport": "api", "read": False, "reason": "a"},
        }
        self.assertEqual(section(self.render(collected=collected), "Unread sources").splitlines()[2:], ["- alpha: a", "- zeta: z"])

    def test_overrides_show_key_title_and_state(self):
        facts = fixtures.make_facts({"metric-a": fixtures.obs(over=False, last_value="Alert")}, overrides=["metric-a"])
        self.assertEqual(section(self.render(facts=facts), "Overrides"), "## Overrides\n\n- metric-a: Metric A, state Alert")

    def test_no_overrides_has_no_section(self):
        self.assertNotIn("## Overrides", self.render())


class EmptyTest(DigestCase):
    def test_empty_inputs_render_only_the_title(self):
        self.assertEqual(self.render(collected=ALL_READ), "# Prod watch, 2026-06-01T11:00:00Z\n")

    def test_every_section_is_skipped_when_empty(self):
        text = self.render(collected=ALL_READ)
        self.assertEqual([line for line in text.splitlines() if line.startswith("##")], [])


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
        self.assertEqual(section(text, "New").splitlines()[2], "- Metric A (Medium, watch)")
        self.assertEqual(section(text, "Resolved").splitlines()[2], "- Metric B (Medium, watch)")
        self.assertEqual(
            section(text, "Still open").splitlines()[4:],
            ["- Metric C: since 2026-05-30T08:00:00Z, last value 10, https://example.test/metric-a"],
        )

    def test_report_only_title_shows_the_run_time_of_the_record(self):
        text = self.render(facts=fixtures.make_facts({"metric-a": fixtures.obs()}), window=fixtures.make_window(explicit=True))
        self.assertEqual(text.splitlines()[0], "# Prod watch, 2026-06-01T11:00:00Z")


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
        collected = {"chat": {"role": "chat_channel", "transport": "api", "read": False, "reason": "see <@U123> now\nrun x y"}}
        block = section(self.render(collected=collected), "Unread sources")
        self.assertEqual((block.count("\n"), any(mark in block for mark in "<>@ ")), (2, False))

    def test_title_mention_is_neutralised(self):
        facts = fixtures.make_facts({"metric-a": fixtures.obs(title="Page @here now", rank=1)})
        self.assertNotIn("@", self.render(facts=facts))

    def test_unread_reason_is_capped(self):
        collected = {"chat": {"role": "chat_channel", "transport": "api", "read": False, "reason": "x" * 1000}}
        line = section(self.render(collected=collected), "Unread sources").splitlines()[-1]
        self.assertEqual(len(line), len("- chat: ") + state.LABEL_CAP)

    def test_non_text_last_value_is_shown_as_json_and_null_as_not_available(self):
        previous = fixtures.make_state(items={
            "metric-a": fixtures.make_item(title="Number"),
            "metric-b": fixtures.make_item(title="Missing"),
        })
        facts = fixtures.make_facts({"metric-a": fixtures.obs(title="Number", value=1.5), "metric-b": fixtures.obs(title="Missing")})
        self.apply(previous, facts)
        document = self.read("next.json")
        document["items"]["metric-a"]["last_value"] = 1.5
        document["items"]["metric-b"]["last_value"] = None
        self.write("next.json", document)
        self.write_base()
        self.run_digest()
        lines = section(self.read_bytes("digest.md").decode(), "Still open").splitlines()
        self.assertEqual([line.split(", last value ")[1].split(",")[0] for line in lines if ", last value " in line], ["1.5", "n/a"])


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


class ParserTest(unittest.TestCase):
    def test_parser_takes_the_five_documented_flags(self):
        options = {option for action in digest.build_parser()._actions for option in action.option_strings}
        self.assertEqual(options, {"-h", "--help", "--summary", "--state", "--record", "--base", "--out"})


class ScriptTest(DigestCase):
    def test_script_renders_the_digest_with_exit_0(self):
        self.apply(fixtures.make_state(), fixtures.make_facts({"metric-a": fixtures.obs(rank=1)}))
        self.write_base()
        result = subprocess.run(
            [
                sys.executable, "-B", os.path.join(HERE, "digest.py"), "--summary", self.path("summary.json"),
                "--state", self.path("next.json"), "--record", self.path("record.json"), "--base", self.path("base.json"),
                "--out", self.path("digest.md"),
            ],
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual((result.returncode, result.stderr, result.stdout), (0, "", ""))
        self.assertIn("- Metric A (Medium, watch)", self.read_bytes("digest.md").decode())


if __name__ == "__main__":
    unittest.main()
