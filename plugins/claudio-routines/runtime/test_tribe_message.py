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
EXPECTED_SECTIONS = {
    "": ["# Sample digest : 2026-03-12", RUN],
    "## Since last run": [
        "- New: Queue latency above target, Medium, now.",
        "- Resolved: Cache hit ratio below target, under every threshold for 2 runs.",
        "- Ticked: Check the retry policy of the importer.",
    ],
    "## Important": [
        "- Urgent: Queue latency above target, Medium, now, runway none, 140 s of 120 s.",
        "- Urgent: Worker pool near its ceiling, High, now, runway none at peak, 94 of 100 slots.",
        "- Moved: Primary volume filling up, severity from Low to Medium.",
        "- Decision: Second worker pool for batch jobs, before the month-end.",
        "- Decision: Freeze window for the spring release, 2026-03-20.",
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
    def test_a_runway_a_decision_deadline_and_a_ticked_check_ending_with_a_period_keep_one_period(self):
        warnings = copy.deepcopy(self.summary_doc["warnings"])
        for warning in warnings.values():
            warning["runway"] = "none yet."
        self.use_summary(
            warnings=warnings,
            decisions=[{"decision": "Freeze the release", "deadline": "Friday.", "options": "none", "topic": "Release"}],
            done=[{"key": "retry-policy", "text": "Check the retry policy."}],
        )
        self.assertNotIn("..", self.sent())


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

    def test_a_baseline_run_names_no_comparison(self):
        self.use_summary(baseline=True)
        text = self.sent()
        self.assertIn("Run: baseline run, window", text)
        self.assertEqual(sections(text)["## Since last run"], ["- Baseline run: no earlier digest to compare with."])

    def test_a_run_without_important_points_has_no_important_section(self):
        self.use_summary(warnings={}, moved=[], decisions=[], resolved=[], done=[])
        text = self.sent()
        self.assertNotIn("## Important", text)
        self.assertNotIn("## Since last run", text)

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


class ImportantPointTests(MessageCase):
    def important(self, **fields):
        self.use_summary(**fields)
        return sections(self.sent()).get("## Important", [])

    def warnings_with(self, key, **fields):
        warnings = copy.deepcopy(self.summary_doc["warnings"])
        warnings[key].update(fields)
        return warnings

    def test_a_monitor_warning_that_is_new_is_an_important_point(self):
        lines = self.important(warnings=self.warnings_with("queue-latency", metric="monitor-1001"), moved=[], decisions=[])
        self.assertIn("- Monitor: Queue latency above target, new.", lines)

    def test_a_monitor_warning_that_moved_is_an_important_point(self):
        warnings = self.warnings_with("disk-growth", metric="monitor-1001")
        self.assertIn("- Monitor: Primary volume filling up, moved.", self.important(warnings=warnings))

    def test_a_monitor_warning_with_no_change_is_not_an_important_point(self):
        warnings = self.warnings_with("restore-untested", metric="monitor-1001")
        self.assertNotIn("- Monitor: Backup restore never tested, same.", self.important(warnings=warnings))

    def test_a_metric_warning_that_is_not_a_monitor_is_not_a_monitor_point(self):
        lines = self.important(warnings=self.warnings_with("queue-latency", metric="queue"))
        self.assertEqual([line for line in lines if line.startswith("- Monitor:")], [])

    def test_a_severity_move_is_an_important_point(self):
        self.assertIn("- Moved: Primary volume filling up, severity from Low to Medium.", self.important())

    def test_a_when_move_is_an_important_point(self):
        moved = [{"key": "disk-growth", "field": "when", "from": "watch", "to": "within months"}]
        self.assertIn("- Moved: Primary volume filling up, when from watch to within months.", self.important(moved=moved))

    def test_a_status_move_is_not_an_important_point(self):
        moved = [{"key": "disk-growth", "field": "status", "from": "open", "to": "in progress"}]
        self.assertEqual([line for line in self.important(moved=moved) if line.startswith("- Moved:")], [])

    def test_a_runway_under_14_days_is_an_urgent_point(self):
        lines = self.important(warnings=self.warnings_with("restore-untested", runway="about 10 days"), moved=[], decisions=[])
        self.assertIn("- Urgent: Backup restore never tested, Low, watch, runway about 10 days.", lines)

    def test_a_runway_of_14_days_is_not_an_urgent_point(self):
        lines = self.important(warnings=self.warnings_with("freeze-overlap", runway="2 weeks"), moved=[], decisions=[])
        self.assertEqual([line for line in lines if "Release freeze" in line], [])

    def test_a_runway_of_months_is_not_an_urgent_point(self):
        warnings = self.warnings_with("disk-growth", runway="about 5 months at +9 percent a month")
        self.assertEqual([line for line in self.important(warnings=warnings) if "Primary volume" in line and "Urgent" in line], [])


class CleaningTests(MessageCase):
    def test_a_mention_and_control_characters_are_cleaned_in_the_message(self):
        resolved = [{"key": "cache", "title": "Cache", "reason": "gone <@usr_aaa01> now\x07done"}]
        decisions = [{"decision": "Pool\x1b[31m", "deadline": "@team soon", "options": "x", "topic": "Capacity"}]
        self.use_summary(resolved=resolved, decisions=decisions)
        text = self.sent()
        self.assertEqual(sections(text)["## Since last run"][1], "- Resolved: Cache, gone   usr_aaa01  now done.")
        self.assertEqual([line for line in sections(text)["## Important"] if "Decision" in line], ["- Decision: Pool [31m,  team soon."])
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
