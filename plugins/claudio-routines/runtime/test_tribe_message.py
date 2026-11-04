import copy
import os
import unittest

import state
import tribe_message
from tribe_support import (
    NEW_PAGE, PublishCase, SLUG, run_cli,
)

LINK = "https://example.test/pages/"
RUN = "Run: regular run, window 2026-03-11 08:30 UTC to 2026-03-12 08:30 UTC, 2 of 3 sources read."
COUNTS = "2 urgent (1 High), 1 new, 1 moved, 1 resolved, 1 ticked."
EXPECTED_SECTIONS = {
    "": ["# Sample digest : 2026-03-12", RUN, COUNTS],
    "## Do now": [
        "- High: Worker pool near its ceiling. Next: add a second pool for batch jobs; cap the concurrency of nightly imports; alert at 85 percent of the pool.",
        "- Medium: Queue latency above target. Next: move long jobs to their own queue; spread out the nightly burst.",
    ],
    "## This week": [
        "- Decision: Second worker pool for batch jobs, before the month-end.",
        "- Decision: Freeze window for the spring release, 2026-03-20.",
        "- Check: Find what moved the queue latency.",
        "- Check: Read the worker pool quota.",
    ],
    "## Later": [
        "- 2 within months, 1 watch.",
        "- Checks: 2 before the month-end, 1 to investigate.",
        "- Resolved: Cache hit ratio below target.",
    ],
    "tail": [
        "Blind spots: alerts-feed (alerts feed returned no data since 2026-03-09), metrics-trend (metrics trend read failed), Mobile app, Issue tracker, 1 more not listed.",
        f"Page: {LINK}{NEW_PAGE}",
    ],
}


def sections(text):
    found = {}
    for block in text.rstrip("\n").split("\n\n"):
        lines = block.split("\n")
        if lines[0].startswith("## "):
            found[lines[0]] = lines[1:]
        else:
            found["" if lines[0].startswith("# ") else "tail"] = lines
    return found


class MessageCase(PublishCase):
    def message(self, *extra):
        code, _, err = run_cli("message", "--out", self.path("message.txt"), *extra)
        return code, err

    def message_text(self):
        with open(self.path("message.txt"), encoding="utf-8") as handle:
            return handle.read()

    def sent(self, result=None):
        code, err = self.message(
            "--summary", self.summary, "--result", result or self.result(), "--config", self.config, "--routine", SLUG, "--place", "cloud"
        )
        self.assertEqual((code, err), (0, ""))
        return self.message_text()

    def failed_result(self, reason="publish-1: no result saved"):
        return self.result(status="failed", page=None, reason=reason, heading="skipped")


class PeriodTests(MessageCase):
    def test_a_lead_a_decision_deadline_and_a_check_ending_with_a_period_keep_one_period(self):
        warnings = copy.deepcopy(self.summary_doc["warnings"])
        for warning in warnings.values():
            warning["mitigation"] = ["add a worker.", "cap the imports."]
        checks = {"read-quota": {"group": "This week", "since": "2026-03-06T08:30:00Z", "text": "Read the quota.", "topic": "Capacity"}}
        self.use_summary(
            warnings=warnings,
            checks=checks,
            decisions=[{"decision": "Freeze the release", "deadline": "Friday.", "options": "none", "topic": "Release"}],
        )
        text = self.sent()
        self.assertNotIn("..", text)
        self.assertNotIn(".;", text)


class SectionTests(MessageCase):
    def test_the_message_sections(self):
        self.assertEqual(sections(self.sent()), EXPECTED_SECTIONS)

    def test_the_message_ends_with_one_newline(self):
        text = self.sent()
        self.assertEqual((text.endswith("\n"), text.endswith("\n\n")), (True, False))

    def test_the_title_is_the_page_title_template_of_the_config_with_the_run_date(self):
        self.use_config(lambda routine: routine["page"].update({"title": "Digest of {{date}}"}))
        self.assertEqual(self.sent().split("\n")[0], "# Digest of 2026-03-12")

    def test_the_page_link_comes_from_the_page_values_of_the_config(self):
        self.use_config(lambda routine: routine["page"].update({"link": "https://docs.example.com/p/{{id}}/view"}))
        self.assertIn(f"\nPage: https://docs.example.com/p/{NEW_PAGE}/view\n", self.sent())

    def test_a_baseline_run_names_no_comparison_and_no_change(self):
        self.use_summary(baseline=True)
        text = self.sent()
        self.assertIn("Run: baseline run, window", text)
        self.assertEqual(
            sections(text)[""][2], "2 urgent (1 High). Baseline run: no earlier digest to compare with."
        )
        self.assertNotIn("Resolved:", text)

    def test_a_run_with_nothing_to_act_on_has_no_action_section(self):
        self.use_summary(warnings={}, checks={}, moved=[], decisions=[], resolved=[], done=[])
        text = self.sent()
        for heading in ("## Do now", "## This week", "## Later"):
            self.assertNotIn(heading, text)
        self.assertEqual(sections(text)[""][2], "0 urgent, 0 new, 0 moved, 0 resolved.")

    def test_no_blind_spot_is_said_in_one_line(self):
        self.use_summary(blind_spots=[], blind_spots_dropped=0, coverage_notes=[])
        self.assertIn("\nBlind spots: none.\n", self.sent())

    def test_coverage_notes_alone_are_named_by_their_sources(self):
        self.use_summary(blind_spots=[], blind_spots_dropped=0)
        self.assertIn("\nBlind spots: Mobile app, Issue tracker.\n", self.sent())

    def test_a_note_text_never_reaches_the_message(self):
        self.assertNotIn("no connector is configured", self.sent())

    def test_no_note_leaves_the_gap_line_as_before(self):
        self.use_summary(coverage_notes=[])
        self.assertIn("metrics-trend (metrics trend read failed), 1 more not listed.\n", self.sent())

    def test_the_line_names_at_most_the_blind_spot_cap_and_counts_the_rest_as_not_listed(self):
        gaps = [{"key": f"gap-{index}", "gap": "no data", "runs": 1} for index in range(state.BLIND_SPOT_CAP - 1)]
        self.use_summary(blind_spots=gaps, blind_spots_dropped=1)
        line = next(line for line in self.sent().split("\n") if line.startswith("Blind spots:"))
        self.assertEqual(line.count(", ") + 1, state.BLIND_SPOT_CAP + 1)
        self.assertTrue(line.endswith("Mobile app, 2 more not listed."))

    def test_a_note_source_is_cleaned_like_a_gap_key(self):
        self.use_summary(blind_spots=[], blind_spots_dropped=0, coverage_notes=[{"source": "Mobile <app>\n@team", "text": "Not read"}])
        self.assertIn("\nBlind spots: Mobile  app   team.\n", self.sent())

    def test_a_report_only_message_has_no_page_link(self):
        self.use_summary(report_only=True)
        text = self.sent(self.result(status="report-only", page=None, heading="skipped"))
        self.assertIn("Run: report-only run, window", text)
        self.assertIn("\nPage: not written, report-only run.\n", text)

    def test_a_failed_heading_is_reported(self):
        text = self.sent(self.result(heading="failed", heading_reason="publish-3: no result saved"))
        self.assertIn("\nWeekly heading: not written, tried again on the next run.\n", text)


class ActionCase(MessageCase):
    def section(self, heading, **fields):
        self.use_summary(**fields)
        return sections(self.sent()).get(heading, [])

    def warnings_with(self, key, **fields):
        warnings = copy.deepcopy(self.summary_doc["warnings"])
        warnings[key].update(fields)
        return warnings

    def urgent_warnings(self, count, change="same"):
        template = self.summary_doc["warnings"]["queue-latency"]
        return {f"urgent-{index:02d}": {**template, "title": f"Urgent {index:02d}", "change": change} for index in range(count)}

    def checks(self, count, group="This week"):
        return {
            f"check-{index:02d}": {"group": group, "since": f"2026-03-{index + 1:02d}T08:30:00Z", "text": f"Check {index:02d}", "topic": "Capacity"}
            for index in range(count)
        }


class CountsLineTests(ActionCase):
    def counts(self, **fields):
        self.use_summary(**fields)
        return sections(self.sent())[""][2]

    def test_the_counts_line_names_the_urgent_new_moved_resolved_and_ticked_counts(self):
        self.assertEqual(self.counts(), COUNTS)

    def test_a_warning_that_moved_in_two_fields_counts_once(self):
        moved = [
            {"key": "disk-growth", "field": "severity", "from": "Low", "to": "Medium"},
            {"key": "disk-growth", "field": "status", "from": "open", "to": "in progress"},
        ]
        self.assertIn(", 1 moved,", self.counts(moved=moved))

    def test_no_ticked_check_leaves_the_ticked_count_out(self):
        self.assertEqual(self.counts(done=[]), "2 urgent (1 High), 1 new, 1 moved, 1 resolved.")

    def test_no_high_urgent_warning_leaves_the_high_count_out(self):
        warnings = self.warnings_with("worker-pool-ceiling", severity="Medium")
        self.assertTrue(self.counts(warnings=warnings).startswith("2 urgent, 1 new"))


class DoNowTests(ActionCase):
    def do_now(self, **fields):
        return self.section("## Do now", **fields)

    def test_an_urgent_warning_is_a_line_with_its_severity_and_all_its_leads(self):
        self.assertEqual(self.do_now(), EXPECTED_SECTIONS["## Do now"])

    def test_the_most_severe_warning_comes_first(self):
        lines = self.do_now(warnings=self.warnings_with("queue-latency", severity="Low"))
        self.assertEqual([line.split(".")[0] for line in lines], ["- High: Worker pool near its ceiling", "- Low: Queue latency above target"])

    def test_a_new_warning_comes_before_an_unchanged_one_of_the_same_severity(self):
        lines = self.do_now(warnings=self.warnings_with("queue-latency", severity="High"))
        self.assertEqual([line.split(".")[0] for line in lines], ["- High: Queue latency above target", "- High: Worker pool near its ceiling"])

    def test_a_moved_warning_comes_before_an_unchanged_one_of_the_same_severity(self):
        warnings = {**self.urgent_warnings(1), "urgent-zz": {**self.urgent_warnings(1)["urgent-00"], "title": "Moved one", "change": "moved"}}
        self.assertEqual([line.split(".")[0] for line in self.do_now(warnings=warnings)], ["- Medium: Moved one", "- Medium: Urgent 00"])

    def test_a_warning_without_leads_has_no_next_step(self):
        warnings = self.warnings_with("queue-latency", mitigation=[])
        self.assertIn("- Medium: Queue latency above target.", self.do_now(warnings=warnings))

    def test_a_runway_under_14_days_is_urgent(self):
        warnings = self.warnings_with("restore-untested", runway="about 10 days")
        self.assertIn("- Low: Backup restore never tested. Next: run one drill on a copy of last night's backup.", self.do_now(warnings=warnings))

    def test_a_runway_of_14_days_is_not_urgent(self):
        lines = self.do_now(warnings=self.warnings_with("freeze-overlap", runway="2 weeks"))
        self.assertEqual([line for line in lines if "Release freeze" in line], [])

    def test_a_runway_of_months_is_not_urgent(self):
        lines = self.do_now(warnings=self.warnings_with("disk-growth", runway="about 5 months at +9 percent a month"))
        self.assertEqual([line for line in lines if "Primary volume" in line], [])

    def test_urgent_warnings_past_the_cap_are_counted_not_listed(self):
        lines = self.do_now(warnings=self.urgent_warnings(7))
        self.assertEqual((len(lines), lines[-1]), (6, "- +2 more urgent, see the page."))

    def test_urgent_warnings_up_to_the_cap_have_no_overflow_line(self):
        lines = self.do_now(warnings=self.urgent_warnings(5))
        self.assertEqual((len(lines), any("more urgent" in line for line in lines)), (5, False))

    def test_no_urgent_warning_has_no_do_now_section(self):
        warnings = copy.deepcopy(self.summary_doc["warnings"])
        for key in ("queue-latency", "worker-pool-ceiling"):
            warnings[key]["when"] = "watch"
        self.assertEqual(self.do_now(warnings=warnings), [])


class ThisWeekTests(ActionCase):
    def this_week(self, **fields):
        return self.section("## This week", **fields)

    def test_the_decisions_with_their_deadlines_come_before_the_checks_of_the_week(self):
        self.assertEqual(self.this_week(), EXPECTED_SECTIONS["## This week"])

    def test_the_newest_check_comes_first(self):
        checks = {
            "a-old": {"group": "This week", "since": "2026-03-02T08:30:00Z", "text": "Older one", "topic": "Capacity"},
            "b-new": {"group": "This week", "since": "2026-03-11T08:30:00Z", "text": "Newer one", "topic": "Capacity"},
        }
        self.assertEqual(self.this_week(decisions=[], checks=checks), ["- Check: Newer one.", "- Check: Older one."])

    def test_checks_of_the_same_age_come_in_key_order(self):
        same = {"group": "This week", "since": "2026-03-02T08:30:00Z", "topic": "Capacity"}
        checks = {"b-key": {**same, "text": "Second"}, "a-key": {**same, "text": "First"}}
        self.assertEqual(self.this_week(decisions=[], checks=checks), ["- Check: First.", "- Check: Second."])

    def test_checks_past_the_cap_are_counted_not_listed(self):
        lines = self.this_week(decisions=[], checks=self.checks(7))
        self.assertEqual((len(lines), lines[-1]), (6, "- +2 more checks, see the page."))

    def test_checks_up_to_the_cap_have_no_overflow_line(self):
        lines = self.this_week(decisions=[], checks=self.checks(5))
        self.assertEqual((len(lines), any("more checks" in line for line in lines)), (5, False))

    def test_a_check_of_another_group_is_not_listed_this_week(self):
        self.assertEqual(self.this_week(decisions=[], checks=self.checks(2, group="Investigate")), [])

    def test_no_decision_and_no_check_has_no_this_week_section(self):
        self.assertEqual(self.this_week(decisions=[], checks={}), [])


class LaterTests(ActionCase):
    def later(self, **fields):
        return self.section("## Later", **fields)

    def test_the_later_section_counts_what_is_not_urgent_and_names_the_changes(self):
        self.assertEqual(self.later(), EXPECTED_SECTIONS["## Later"])

    def test_a_zero_count_is_not_listed(self):
        warnings = self.warnings_with("disk-growth", when="watch")
        warnings["freeze-overlap"]["when"] = "watch"
        self.assertEqual(self.later(warnings=warnings)[0], "- 3 watch.")

    def test_a_new_warning_that_is_not_urgent_is_named_before_the_resolved_ones(self):
        lines = self.later(warnings=self.warnings_with("restore-untested", change="new"))
        self.assertIn("- New: Backup restore never tested. Resolved: Cache hit ratio below target.", lines)

    def test_names_past_the_cap_are_counted(self):
        resolved = [{"key": f"r{index}", "title": f"Resolved {index}", "reason": "gone"} for index in range(5)]
        lines = self.later(resolved=resolved)
        self.assertIn("- Resolved: Resolved 0, Resolved 1, Resolved 2, +2.", lines)

    def test_a_baseline_run_names_no_change(self):
        lines = self.later(baseline=True, warnings=self.warnings_with("restore-untested", change="new"))
        self.assertEqual([line for line in lines if "New:" in line or "Resolved:" in line], [])

    def test_no_later_item_has_no_later_section(self):
        self.assertEqual(self.later(warnings=self.urgent_warnings(2), checks={}, resolved=[]), [])


class CleaningTests(MessageCase):
    def test_a_mention_and_control_characters_are_cleaned_in_the_message(self):
        warnings = copy.deepcopy(self.summary_doc["warnings"])
        warnings["queue-latency"]["mitigation"] = ["ask <@usr_bbb02>\x07now"]
        resolved = [{"key": "cache", "title": "Cache <@usr_aaa01>\x07done", "reason": "gone"}]
        decisions = [{"decision": "Pool\x1b[31m", "deadline": "@team soon", "options": "x", "topic": "Capacity"}]
        checks = {"read-quota": {"group": "This week", "since": "2026-03-06T08:30:00Z", "text": "Read <@usr_ccc03>\x07quota", "topic": "Capacity"}}
        self.use_summary(warnings=warnings, resolved=resolved, decisions=decisions, checks=checks)
        text = self.sent()
        found = sections(text)
        self.assertEqual(found["## Do now"][1], "- Medium: Queue latency above target. Next: ask   usr_bbb02  now.")
        self.assertEqual(found["## This week"], ["- Decision: Pool [31m,  team soon.", "- Check: Read   usr_ccc03  quota."])
        self.assertEqual(found["## Later"][-1], "- Resolved: Cache   usr_aaa01  done.")
        self.assertEqual([character for character in text if character in "\x07\x1b<>@"], [])


class DegradedTests(MessageCase):
    def test_the_degraded_message_for_a_rejected_judgment(self):
        self.assertEqual(self.message("--degraded", "judgment"), (0, ""))
        self.assertEqual(self.message_text(), "degraded: judgment rejected, no page written\n")

    def test_the_degraded_message_for_a_failed_structure_check(self):
        self.assertEqual(self.message("--degraded", "structure"), (0, ""))
        self.assertEqual(self.message_text(), "degraded: structure check failed, no page written\n")

    def test_the_degraded_message_for_a_failed_create_names_the_reason(self):
        self.assertEqual(self.message("--result", self.failed_result()), (0, ""))
        self.assertEqual(self.message_text(), "degraded: page create failed, publish-1: no result saved\n")

    def test_a_failed_create_needs_no_summary_nor_config(self):
        self.write("summary.json", {"title": "x"})
        self.assertEqual(self.message("--summary", self.summary, "--result", self.failed_result()), (0, ""))
        self.assertTrue(self.message_text().startswith("degraded: page create failed"))

    def test_a_failed_create_gives_the_degraded_message_even_with_a_full_summary(self):
        self.assertEqual(self.sent(self.failed_result()), "degraded: page create failed, publish-1: no result saved\n")

    def test_a_degraded_message_is_one_line_without_control_characters(self):
        text = self.sent(self.failed_result("line one\nline two\x1b[31m @team"))
        self.assertEqual((text.count("\n"), [c for c in text if c in "\x1b@"]), (1, []))
        self.assertTrue(text.startswith("degraded: page create failed, "))

    def test_a_failed_result_without_a_reason_still_names_the_cause(self):
        self.assertEqual(self.message("--result", self.failed_result(None)), (0, ""))
        self.assertEqual(self.message_text(), "degraded: page create failed, no reason recorded\n")


class InputTests(MessageCase):
    def test_a_message_needs_a_result_or_a_degraded_cause(self):
        code, err = self.message("--summary", self.summary)
        self.assertEqual((code, "--result" in err), (2, True))
        self.assertFalse(os.path.exists(self.path("message.txt")))

    def test_a_created_result_needs_the_summary_and_the_config_flags(self):
        code, err = self.message("--result", self.result())
        self.assertEqual(code, 2)
        for flag in ("--summary", "--config", "--routine", "--place"):
            self.assertIn(flag, err)

    def test_a_degraded_cause_excludes_the_other_inputs(self):
        code, err = self.message("--degraded", "judgment", "--result", self.result())
        self.assertEqual((code, "--result" in err), (2, True))

    def test_an_unknown_degraded_cause_exits_2(self):
        self.assertEqual(self.message("--degraded", "other")[0], 2)

    def test_a_result_with_an_unknown_status_exits_2(self):
        code, err = self.message("--result", self.result(status="done"))
        self.assertEqual((code, "status" in err), (2, True))

    def test_a_created_result_without_a_page_exits_2(self):
        code, err = self.message("--result", self.result(page=None))
        self.assertEqual((code, "without a page" in err), (2, True))

    def test_a_window_time_out_of_range_exits_2(self):
        self.use_summary(window={**self.summary_doc["window"], "to_ts": 10**20})
        code, _ = self.message(
            "--summary", self.summary, "--result", self.result(), "--config", self.config, "--routine", SLUG, "--place", "cloud"
        )
        self.assertEqual(code, 2)


class RunwayTests(unittest.TestCase):
    def test_minutes_are_a_fraction_of_a_day(self):
        self.assertEqual(tribe_message.runway_days("about 36 minutes"), 36 / 1440)

    def test_hours_are_a_fraction_of_a_day(self):
        self.assertEqual(tribe_message.runway_days("6 hours"), 0.25)

    def test_days(self):
        self.assertEqual(tribe_message.runway_days("about 10 days"), 10)

    def test_weeks(self):
        self.assertEqual(tribe_message.runway_days("2 weeks"), 14)

    def test_months(self):
        self.assertEqual(tribe_message.runway_days("about 5 months at +9 percent a month"), 150)

    def test_a_singular_unit(self):
        self.assertEqual(tribe_message.runway_days("1 day"), 1)

    def test_the_unit_is_read_without_regard_to_case(self):
        self.assertEqual(tribe_message.runway_days("3 DAYS"), 3)

    def test_a_decimal_quantity(self):
        self.assertEqual(tribe_message.runway_days("1.5 weeks"), 10.5)

    def test_a_label_without_a_quantity_has_no_runway(self):
        self.assertIsNone(tribe_message.runway_days("unknown"))

    def test_a_number_word_is_not_read(self):
        self.assertIsNone(tribe_message.runway_days("about two weeks"))

    def test_a_unit_inside_a_word_is_not_read(self):
        self.assertIsNone(tribe_message.runway_days("5 dayshift"))


if __name__ == "__main__":
    unittest.main()
