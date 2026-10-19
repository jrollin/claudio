import copy
import unittest
from zoneinfo import ZoneInfo

import tribe_page
from tribe_support import (
    fixture, fixture_json, tick,
)

WRITTEN_AT = "2026-03-11T08:34:00Z"
EDITED_AT = "2026-03-11T09:10:00Z"
PARIS = ZoneInfo("Europe/Paris")
UTC = ZoneInfo("UTC")


def broken(page, old, new):
    assert page.count(old) >= 1, f"{old!r} is not in the page"
    return page.replace(old, new, 1)


def rules(failures):
    return [failure.split(":")[0] for failure in failures]


def focus_column(page, index):
    lines = page.split("\n")
    start = lines.index("### Focus")
    end = next(index for index in range(start + 1, len(lines)) if lines[index].startswith("### "))
    cells = [line[4:-5] for line in lines[start:end] if line.startswith("<td>")]
    return cells[4 + index::4]


def warning_headings(page):
    lines = page.split("\n")
    start = lines.index("## Warnings")
    end = lines.index("## What to check")
    return [line for line in lines[start:end] if line.startswith("### ")]


def section_lines(page, heading):
    lines = page.rstrip("\n").split("\n")
    start = next(index for index, line in enumerate(lines) if line.startswith(f"## {heading}"))
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
    return lines[start + 1:end]


class PageCase(unittest.TestCase):
    def setUp(self):
        self.summary = fixture_json("page_summary.json")
        self.values = fixture_json("page_values.json")
        self.golden = fixture("page_golden.md")
        self.stored = {"warnings": self.summary["warnings"], "checks": self.summary["checks"]}

    def render(self, **changes):
        summary = copy.deepcopy(self.summary)
        summary.update(changes)
        return tribe_page.render(summary, self.values, PARIS)

    def month_end_heading(self, run_at, zone=PARIS):
        page = tribe_page.render({**self.summary, "run_at": run_at}, self.values, zone)
        return [line for line in section_lines(page, "What to check") if line.startswith("### Before")]

    def parse(self, page, edited_at=EDITED_AT, written_at=WRITTEN_AT, page_id=None):
        return tribe_page.parse_edits(page, self.stored, written_at, edited_at, page_id)


class RenderTests(PageCase):
    def test_renders_the_golden_page_from_the_summary(self):
        self.assertEqual(self.render(), self.golden)

    def test_golden_page_passes_the_structure_check(self):
        self.assertEqual(tribe_page.check(self.golden), [])

    def test_sections_follow_the_layout_order(self):
        headings = [line[3:] for line in self.render().split("\n") if line.startswith("## ")]
        self.assertEqual(
            headings,
            [
                "Since last run",
                "Decisions this week",
                "Warnings",
                "What to check",
                "Details",
                "Blind spots",
                "Corrections to earlier numbers",
                "Sources",
                'How this digest is built {toggle="true"}',
                'Run state {toggle="true"}',
            ],
        )

    def test_focus_sorts_by_highest_severity_then_soonest_when(self):
        warnings = copy.deepcopy(self.summary["warnings"])
        warnings["queue-latency"]["severity"] = "Low"
        warnings["restore-untested"]["when"] = "now"
        page = self.render(warnings=warnings)
        self.assertEqual(focus_column(page, 0), ["Capacity", "Release", "Reliability"])

    def test_focus_ranks_a_sooner_topic_above_a_later_one_of_the_same_severity(self):
        warnings = copy.deepcopy(self.summary["warnings"])
        warnings["freeze-overlap"]["severity"] = "Medium"
        warnings["queue-latency"]["when"] = "within months"
        warnings["restore-untested"]["when"] = "watch"
        warnings["disk-growth"]["when"] = "watch"
        warnings["worker-pool-ceiling"]["severity"] = "Medium"
        warnings["worker-pool-ceiling"]["when"] = "watch"
        page = self.render(warnings=warnings)
        self.assertEqual(focus_column(page, 0), ["Release", "Reliability", "Capacity"])

    def test_topic_headings_follow_the_focus_order(self):
        self.assertEqual(
            warning_headings(self.render()),
            ["### Focus", "### Capacity", "### Release", "### Reliability"],
        )

    def test_warnings_sort_by_severity_then_soonest_when_inside_a_topic(self):
        page = self.render()
        self.assertLess(page.index("key: worker-pool-ceiling"), page.index("key: disk-growth"))

    def test_warning_row_carries_the_key_marker_and_the_three_markers(self):
        row = [line for line in self.golden.split("\n") if "key: worker-pool-ceiling" in line]
        self.assertEqual(
            row,
            ['<td>Worker pool near its ceiling<br>status: open<br><span color="gray">key: worker-pool-ceiling</span></td>'],
        )

    def test_severity_cell_holds_the_when_and_the_runway(self):
        self.assertIn("<td>High<br>🔴 now<br>runway: none at peak, 94 of 100 slots</td>", self.golden)

    def test_evidence_cell_starts_with_the_confidence(self):
        self.assertIn("<td>confidence: inferred<br>  • the volume grows 9 percent a month</td>", self.golden)

    def test_several_items_sit_one_per_line_with_a_bullet(self):
        self.assertIn(
            "<td>  • batch exports finish late<br>  • interactive requests wait for a free slot</td>", self.golden
        )

    def test_a_single_item_has_no_bullet(self):
        self.assertIn("<td>plan a resize before the 80 percent mark</td>", self.golden)

    def test_when_values_carry_their_emoji(self):
        chosen = [("worker-pool-ceiling", "watch"), ("disk-growth", "now"), ("freeze-overlap", "within months")]
        warnings = {
            key: {**self.summary["warnings"][key], "severity": "High", "topic": key, "when": when} for key, when in chosen
        }
        page = self.render(warnings=warnings, checks={}, details={})
        self.assertEqual(focus_column(page, 2), ["🔴 now", "🟠 within months", "🟡 watch"])

    def test_record_cites_become_links_and_feature_cites_stay_out_of_the_cell(self):
        self.assertEqual(
            [line for line in self.golden.split("\n") if line.startswith("<td>confidence: measured<br>  • 94")],
            [
                "<td>confidence: measured<br>  • 94 of 100 worker slots busy at the daily peak"
                "<br>  • 3 pool-full alerts fired in 7 days [alerts](https://example.com/monitors/pool-full)</td>"
            ],
        )

    def test_todos_start_with_a_gray_bg_topic_tag_and_end_with_the_key_marker(self):
        self.assertIn(
            '- [ ] <span color="gray_bg">Capacity</span> Read the worker pool quota'
            ' <span color="gray">read-pool-quota</span>',
            self.golden,
        )

    def test_checks_group_under_the_three_headings_in_order(self):
        lines = section_lines(self.golden, "What to check")
        self.assertEqual(
            [line for line in lines if line.startswith("### ")],
            ["### This week", "### Before the 2026-03-31 month-end", "### Investigate"],
        )

    def test_the_month_end_group_names_the_last_day_of_the_run_month(self):
        self.assertEqual(self.month_end_heading("2026-10-19T08:30:00Z"), ["### Before the 2026-10-31 month-end"])

    def test_a_run_late_on_the_last_day_in_utc_that_is_the_next_month_in_the_zone_names_the_next_month_end(self):
        self.assertEqual(self.month_end_heading("2026-10-31T23:30:00Z"), ["### Before the 2026-11-30 month-end"])

    def test_the_same_run_in_utc_names_the_month_end_of_its_own_month(self):
        self.assertEqual(self.month_end_heading("2026-10-31T23:30:00Z", UTC), ["### Before the 2026-10-31 month-end"])

    def test_a_february_of_a_leap_year_ends_on_the_29th(self):
        self.assertEqual(self.month_end_heading("2028-02-10T08:30:00Z"), ["### Before the 2028-02-29 month-end"])

    def test_a_february_of_a_common_year_ends_on_the_28th(self):
        self.assertEqual(self.month_end_heading("2027-02-10T08:30:00Z"), ["### Before the 2027-02-28 month-end"])

    def test_the_other_groups_keep_their_stored_name(self):
        lines = section_lines(self.render(), "What to check")
        self.assertEqual([line for line in lines if line.startswith("### ") and "month-end" not in line], ["### This week", "### Investigate"])

    def test_checks_inside_a_group_follow_the_focus_order_of_their_topics(self):
        lines = section_lines(self.golden, "What to check")
        self.assertEqual(
            [line.split("</span>")[0].split(">")[-1] for line in lines if line.startswith("- [ ]")],
            ["Capacity", "Reliability", "Capacity", "Release", "Reliability"],
        )

    def test_a_group_without_checks_is_left_out(self):
        checks = {key: check for key, check in self.summary["checks"].items() if check["group"] == "This week"}
        lines = section_lines(self.render(checks=checks), "What to check")
        self.assertEqual([line for line in lines if line.startswith("### ")], ["### This week"])

    def test_a_check_in_a_group_outside_the_layout_raises_with_its_key_and_group(self):
        stored = self.summary["checks"]
        checks = {**stored, "plan-resize": {**stored["plan-resize"], "group": "Someday"}}
        with self.assertRaises(ValueError) as raised:
            self.render(checks=checks)
        self.assertEqual(
            str(raised.exception),
            "check plan-resize: group Someday is not one of This week, Before the month-end, Investigate",
        )

    def test_header_callout_names_the_run_window_and_the_previous_run(self):
        callout = self.golden.split("</callout>")[0]
        self.assertEqual(
            callout.split("\n")[1:-1],
            [
                "\t- Run: 2026-03-12 08:30 UTC, window 2026-03-11 08:30 UTC to 2026-03-12 08:30 UTC.",
                '\t- Previous run: <mention-page url="https://example.test/pages/previous-page-id"/>,'
                " written 2026-03-11 08:34 UTC.",
                "\t- Format: layout version 1. Run state: the last toggle of this page, never the state itself.",
            ],
        )

    def test_a_source_reason_is_cleaned_and_capped_in_the_sources_table(self):
        sources = copy.deepcopy(self.summary["sources"])
        sources[0].update(read=False, reason="down\x07" + "y" * 400)
        cells = [line for line in section_lines(self.render(sources=sources), "Sources") if line.startswith("<td>no, ")]
        self.assertEqual(cells[0], "<td>no, down " + "y" * 295 + "</td>")

    def test_the_previous_page_mention_fills_the_id_into_the_link_of_the_values(self):
        self.values["link"] = "https://docs.example.com/p/{{id}}/view"
        self.assertIn('<mention-page url="https://docs.example.com/p/previous-page-id/view"/>', self.render())

    def test_page_link_replaces_the_id_placeholder(self):
        self.assertEqual(tribe_page.page_link("https://example.test/{{id}}/{{id}}", "abc"), "https://example.test/abc/abc")

    def test_a_first_digest_has_no_previous_run(self):
        page = self.render(previous_page=None, baseline=True)
        self.assertIn("- Previous run: none, this is the first digest.", page)

    def test_a_baseline_run_says_baseline(self):
        page = self.render(previous_page=None, baseline=True)
        self.assertIn("- Baseline run: no earlier digest to compare with.", page)

    def test_a_baseline_run_lists_no_new_warning(self):
        page = self.render(previous_page=None, baseline=True)
        self.assertNotIn("- New: ", page)

    def test_since_last_run_lists_new_resolved_moved_and_ticked(self):
        self.assertEqual(
            section_lines(self.golden, "Since last run")[:4],
            [
                "- New: Queue latency above target, Medium, now.",
                "- Resolved: Cache hit ratio below target, under every threshold for 2 runs.",
                "- Moved: Primary volume filling up, severity from Low to Medium.",
                "- Ticked: Check the retry policy of the importer.",
            ],
        )

    def test_since_last_run_lists_the_ignored_page_edits(self):
        self.assertIn("- Page edit ignored: warning row 4, no key marker.", section_lines(self.golden, "Since last run"))

    def test_blind_spots_list_each_gap_the_count_the_cap_dropped_and_each_coverage_note(self):
        self.assertEqual(
            section_lines(self.golden, "Blind spots"),
            [
                "- alerts-feed: alerts feed returned no data since 2026-03-09 (runs: 3).",
                "- metrics-trend: metrics trend read failed (runs: 1).",
                "- More gaps not listed: 1.",
                "- Mobile app: Not read, no connector is configured for it.",
                "- Issue tracker: A rule names it and the features hold no record of it.",
            ],
        )

    def test_a_coverage_note_ending_with_a_period_keeps_one_period(self):
        notes = [{"source": "Mobile app", "text": "Not read."}]
        self.assertIn("- Mobile app: Not read.", section_lines(self.render(coverage_notes=notes), "Blind spots"))

    def test_coverage_notes_follow_the_collector_gaps_in_the_order_given(self):
        lines = section_lines(self.render(blind_spots_dropped=0), "Blind spots")
        self.assertEqual([line.split(":")[0] for line in lines], ["- alerts-feed", "- metrics-trend", "- Mobile app", "- Issue tracker"])

    def test_coverage_notes_alone_fill_the_blind_spots_section(self):
        lines = section_lines(self.render(blind_spots=[], blind_spots_dropped=0), "Blind spots")
        self.assertEqual(lines, ["- Mobile app: Not read, no connector is configured for it.", "- Issue tracker: A rule names it and the features hold no record of it."])

    def test_the_page_with_coverage_notes_only_passes_the_structure_check(self):
        self.assertEqual(tribe_page.check(self.render(blind_spots=[], blind_spots_dropped=0)), [])

    def test_gaps_without_coverage_notes_render_as_before(self):
        lines = section_lines(self.render(coverage_notes=[]), "Blind spots")
        self.assertEqual(lines[:3], section_lines(self.golden, "Blind spots")[:3])
        self.assertEqual(len(lines), 3)

    def test_blind_spots_say_none_only_when_no_gap_and_no_note_exist(self):
        self.assertEqual(section_lines(self.render(blind_spots=[], blind_spots_dropped=0, coverage_notes=[]), "Blind spots"), ["- None."])

    def test_the_section_is_not_none_when_only_the_dropped_count_is_left(self):
        lines = section_lines(self.render(blind_spots=[], coverage_notes=[]), "Blind spots")
        self.assertEqual(lines, ["- More gaps not listed: 1."])

    def test_a_coverage_note_is_cleaned_of_markup_and_control_characters(self):
        notes = [{"source": "Mobile <app>", "text": "Not\nread @team"}]
        self.assertIn("- Mobile  app : Not read  team.", section_lines(self.render(coverage_notes=notes), "Blind spots"))

    def test_a_coverage_note_text_is_cut_at_the_label_cap(self):
        notes = [{"source": "Mobile app", "text": "x" * 500}]
        line = section_lines(self.render(coverage_notes=notes), "Blind spots")[-1]
        self.assertEqual(line, "- Mobile app: " + "x" * 300 + ".")

    def test_a_coverage_note_source_is_cut_at_the_source_cap(self):
        notes = [{"source": "s" * 100, "text": "Not read"}]
        line = section_lines(self.render(coverage_notes=notes), "Blind spots")[-1]
        self.assertEqual(line, "- " + "s" * 60 + ": Not read.")

    def test_the_page_with_coverage_notes_passes_the_structure_check(self):
        self.assertEqual(tribe_page.check(self.render()), [])

    def test_a_correction_ending_with_a_period_keeps_one_period(self):
        corrections = [{"was": "21 failed imports.", "now": "19 failed imports.", "cites": []}]
        self.assertEqual(
            section_lines(self.render(corrections=corrections), "Corrections to earlier numbers"),
            ["- Was: 21 failed imports. Now: 19 failed imports."],
        )

    def test_a_ticked_check_ending_with_a_period_keeps_one_period(self):
        lines = section_lines(self.render(done=[{"key": "retry-policy", "text": "Check the retry policy."}]), "Since last run")
        self.assertEqual([line for line in lines if line.startswith("- Ticked")], ["- Ticked: Check the retry policy."])

    def test_a_resolved_reason_ending_with_a_period_keeps_one_period(self):
        resolved = [{"key": "cache-hit", "title": "Cache hit ratio below target", "reason": "replaced by the new cache warning."}]
        lines = section_lines(self.render(resolved=resolved), "Since last run")
        self.assertEqual(
            [line for line in lines if line.startswith("- Resolved")],
            ["- Resolved: Cache hit ratio below target, replaced by the new cache warning."],
        )

    def test_sources_table_lists_a_read_source_with_its_window(self):
        cells = [line[4:-5] for line in section_lines(self.golden, "Sources") if line.startswith("<td>")]
        self.assertEqual(cells[4:8], ["alerts", "observability", "yes", "2026-03-11 08:30 UTC to 2026-03-12 08:30 UTC"])

    def test_sources_table_lists_an_unread_source_with_its_reason(self):
        cells = [line[4:-5] for line in section_lines(self.golden, "Sources") if line.startswith("<td>")]
        self.assertEqual(cells[12:16], ["pages", "document store", "no, connector signed out", "none"])

    def test_how_this_digest_is_built_holds_the_routine_pointer_lines(self):
        self.assertEqual(
            section_lines(self.golden, "How this digest is built"),
            ["\t" + line for line in self.values["how_built"]],
        )

    def test_run_state_names_window_page_ids_and_state_path_without_json(self):
        lines = section_lines(self.golden, "Run state")
        self.assertEqual(
            lines,
            [
                "\t- Window: 2026-03-11 08:30 UTC to 2026-03-12 08:30 UTC.",
                "\t- Pages: previous previous-page-id; the id of this page is saved in the state once it is created.",
                "\t- State: state/sample.json on the claude/state branch, read by the next run instead of this page.",
            ],
        )

    def test_key_callout_lines_come_from_the_routine_values(self):
        callout = self.golden.split('<callout icon="📏" color="gray_bg">\n')[1].split("</callout>")[0]
        self.assertEqual(callout.split("\n")[:-1], ["\t" + line for line in self.values["key_callout"]])

    def test_empty_warnings_render_still_passes_the_check(self):
        page = self.render(warnings={}, checks={}, decisions=[], details={}, moved=[], resolved=[], done=[])
        self.assertEqual(tribe_page.check(page), [])

    def test_empty_warnings_render_keeps_focus_first_under_warnings(self):
        page = self.render(warnings={}, checks={}, decisions=[], details={})
        self.assertEqual(warning_headings(page), ["### Focus"])


class CheckTests(PageCase):
    def test_an_h2_out_of_order_fails_the_h2_rule(self):
        page = broken(self.golden, "## Details\n", "## Blind spots\n")
        self.assertIn("h2 order", rules(tribe_page.check(page)))

    def test_a_missing_run_state_fails_the_h2_rule_with_state(self):
        page = self.golden.split('## Run state {toggle="true"}')[0]
        self.assertEqual(rules(tribe_page.check(page)), ["h2 order"])

    def test_a_missing_run_state_passes_without_state(self):
        page = self.golden.split('## Run state {toggle="true"}')[0]
        self.assertEqual(tribe_page.check(page, with_state=False), [])

    def test_a_first_h3_other_than_focus_fails_the_focus_rule(self):
        page = broken(self.golden, "### Focus", "### Overview\n### Focus")
        self.assertEqual(rules(tribe_page.check(page)), ["first h3 under Warnings"])

    def test_a_topic_table_with_other_columns_fails_the_header_rule(self):
        page = broken(self.golden, "<td>Impact</td>", "<td>Effect</td>")
        self.assertEqual(rules(tribe_page.check(page)), ["topic table headers"])

    def test_a_row_without_its_status_marker_fails_the_marker_rule(self):
        page = broken(self.golden, "<br>status: in progress", "<br>state: in progress")
        self.assertEqual(tribe_page.check(page), ["row markers: 1 of 5 rows"])

    def test_a_status_marker_outside_the_first_cell_fails_the_marker_rule(self):
        page = broken(self.golden, "<br>status: in progress", "")
        page = broken(
            page,
            "<td>the primary volume fills before the next resize</td>",
            "<td>the primary volume fills before the next resize<br>status: in progress</td>",
        )
        self.assertEqual(tribe_page.check(page), ["row markers: 1 of 5 rows"])

    def test_a_row_without_its_runway_marker_fails_the_marker_rule(self):
        page = broken(self.golden, "<br>runway: unknown", "<br>margin: unknown")
        self.assertEqual(tribe_page.check(page), ["row markers: 1 of 5 rows"])

    def test_a_runway_marker_outside_the_second_cell_fails_the_marker_rule(self):
        page = broken(self.golden, "<br>runway: unknown", "")
        page = broken(
            page, "<td>a backup that cannot be restored</td>", "<td>a backup that cannot be restored<br>runway: unknown</td>"
        )
        self.assertEqual(tribe_page.check(page), ["row markers: 1 of 5 rows"])

    def test_a_row_without_its_confidence_marker_fails_the_marker_rule(self):
        page = broken(self.golden, "<td>confidence: reported<br>", "<td>reported<br>")
        self.assertEqual(tribe_page.check(page), ["row markers: 1 of 5 rows"])

    def test_a_confidence_marker_that_does_not_open_the_last_cell_fails_the_marker_rule(self):
        page = broken(self.golden, "<td>confidence: inferred<br>", "<td>evidence<br>confidence: inferred<br>")
        self.assertEqual(tribe_page.check(page), ["row markers: 1 of 5 rows"])

    def test_a_topic_row_with_a_seventh_cell_fails_the_cell_rule(self):
        link = "[pages](https://example.com/pages/backups)</td>\n"
        page = broken(self.golden, link, link + "<td>extra</td>\n")
        self.assertEqual(tribe_page.check(page), ["row cells: 1 of 5 rows"])

    def test_a_row_without_its_key_marker_fails_the_key_rule_alone(self):
        page = broken(self.golden, '<br><span color="gray">key: disk-growth</span>', "")
        self.assertEqual(tribe_page.check(page), ["key markers: 1 of 5 rows"])

    def test_a_key_marker_over_the_key_cap_fails_the_key_rule(self):
        page = broken(self.golden, "key: disk-growth", "key: " + "a" * 61)
        self.assertEqual(tribe_page.check(page), ["key markers: 1 of 5 rows"])

    def test_a_key_marker_that_is_not_at_the_cell_end_fails_the_key_rule(self):
        marker = '<span color="gray">key: disk-growth</span>'
        page = broken(self.golden, marker, marker + " done")
        self.assertEqual(rules(tribe_page.check(page)), ["key markers"])

    def test_a_focus_table_with_other_columns_fails_the_focus_header_rule(self):
        page = broken(self.golden, "<td>When</td>", "<td>Timing</td>")
        self.assertEqual(tribe_page.check(page), ["Focus table header: Topic|Severity|Timing|Warnings"])

    def test_focus_counts_that_miss_a_row_fail_the_count_rule(self):
        page = broken(self.golden, "<td>🟠 within months</td>\n<td>1</td>", "<td>🟠 within months</td>\n<td>2</td>")
        self.assertEqual(
            tribe_page.check(page),
            ["Focus counts: Capacity=2, Release=2, Reliability=2 vs tables Capacity=2, Release=1, Reliability=2"],
        )

    def test_focus_counts_that_swap_between_topics_fail_although_their_sum_holds(self):
        page = broken(self.golden, "<td>🟠 within months</td>\n<td>1</td>", "<td>🟠 within months</td>\n<td>2</td>")
        page = broken(page, "<td>Medium</td>\n<td>🔴 now</td>\n<td>2</td>", "<td>Medium</td>\n<td>🔴 now</td>\n<td>1</td>")
        self.assertEqual(
            tribe_page.check(page),
            ["Focus counts: Capacity=2, Release=2, Reliability=1 vs tables Capacity=2, Release=1, Reliability=2"],
        )

    def test_a_focus_topic_that_has_no_h3_fails_the_count_rule(self):
        page = broken(self.golden, "<td>Release</td>\n<td>High</td>", "<td>Releases</td>\n<td>High</td>")
        self.assertEqual(
            tribe_page.check(page),
            ["Focus counts: Capacity=2, Releases=1, Reliability=2 vs tables Capacity=2, Release=1, Reliability=2"],
        )

    def test_more_than_three_decisions_fail_the_decision_rule(self):
        decisions = self.summary["decisions"] * 2
        self.assertEqual(tribe_page.check(self.render(decisions=decisions)), ["decisions: 4 rows"])

    def test_three_decisions_pass(self):
        decisions = [*self.summary["decisions"], self.summary["decisions"][0]]
        self.assertEqual(tribe_page.check(self.render(decisions=decisions)), [])

    def test_a_decision_table_with_other_columns_fails_the_decision_header_rule(self):
        page = broken(self.golden, "<td>Options, from the leads</td>", "<td>Options</td>")
        self.assertEqual(tribe_page.check(page), ["decisions header: Decision|Deadline|Options|Topic"])

    def test_a_check_group_with_another_name_fails_the_group_rule(self):
        page = broken(self.golden, "### Investigate", "### Whenever")
        self.assertEqual(tribe_page.check(page), ["check groups: Whenever"])

    def test_a_check_group_that_extends_before_the_fails_the_group_rule(self):
        page = broken(self.golden, "### Before the 2026-03-31 month-end", "### Before the anything")
        self.assertEqual(tribe_page.check(page), ["check groups: Before the anything"])

    def test_the_undated_month_end_group_of_a_written_page_passes_the_group_rule(self):
        page = broken(self.golden, "### Before the 2026-03-31 month-end", "### Before the month-end")
        self.assertEqual(tribe_page.check(page), [])

    def test_a_dated_month_end_group_on_the_last_day_of_a_leap_february_passes_the_group_rule(self):
        page = broken(self.golden, "### Before the 2026-03-31 month-end", "### Before the 2028-02-29 month-end")
        self.assertEqual(tribe_page.check(page), [])

    def test_a_dated_group_on_a_day_that_is_not_a_month_end_fails_the_group_rule(self):
        page = broken(self.golden, "### Before the 2026-03-31 month-end", "### Before the 2026-10-30 month-end")
        self.assertEqual(tribe_page.check(page), ["check groups: Before the 2026-10-30 month-end"])

    def test_a_dated_group_on_a_day_that_does_not_exist_fails_the_group_rule(self):
        page = broken(self.golden, "### Before the 2026-03-31 month-end", "### Before the 2027-02-29 month-end")
        self.assertEqual(tribe_page.check(page), ["check groups: Before the 2027-02-29 month-end"])

    def test_a_dated_group_with_another_ending_fails_the_group_rule(self):
        page = broken(self.golden, "### Before the 2026-03-31 month-end", "### Before the 2026-03-31 week-end")
        self.assertEqual(tribe_page.check(page), ["check groups: Before the 2026-03-31 week-end"])

    def test_a_dated_group_with_a_malformed_date_fails_the_group_rule(self):
        page = broken(self.golden, "### Before the 2026-03-31 month-end", "### Before the 2026-3-31 month-end")
        self.assertEqual(tribe_page.check(page), ["check groups: Before the 2026-3-31 month-end"])

    def test_a_check_group_that_extends_this_week_fails_the_group_rule(self):
        page = broken(self.golden, "### This week", "### This weekend")
        self.assertEqual(tribe_page.check(page), ["check groups: This weekend"])

    def test_a_todo_without_the_gray_bg_tag_fails_the_tag_rule(self):
        page = broken(self.golden, '<span color="gray_bg">Capacity</span>', '<span color="blue">Capacity</span>')
        self.assertEqual(tribe_page.check(page), ["untagged checks: 1"])

    def test_a_ticked_todo_without_the_tag_fails_the_tag_rule(self):
        page = tick(self.golden, "Read the worker pool quota")
        page = broken(page, '<span color="gray_bg">Capacity</span> Read', "Read")
        self.assertEqual(tribe_page.check(page), ["untagged checks: 1"])


class ParseTests(PageCase):
    def test_a_ticked_todo_is_reported_by_key(self):
        page = tick(self.golden, "Read the worker pool quota")
        self.assertEqual(self.parse(page)["ticked"], ["read-pool-quota"])

    def test_a_todo_under_the_dated_month_end_group_is_reported_by_key(self):
        page = tick(self.golden, "Plan the volume resize")
        self.assertEqual(self.parse(page)["ticked"], ["plan-resize"])

    def test_a_todo_under_the_undated_month_end_group_is_reported_by_key(self):
        page = broken(tick(self.golden, "Plan the volume resize"), "### Before the 2026-03-31 month-end", "### Before the month-end")
        self.assertEqual(self.parse(page)["ticked"], ["plan-resize"])

    def test_unticked_todos_are_reported_by_key(self):
        page = tick(self.golden, "Read the worker pool quota")
        self.assertEqual(
            self.parse(page)["unticked"],
            ["confirm-freeze-dates", "plan-resize", "run-restore-drill", "trace-latency-step"],
        )

    def test_a_status_edit_is_reported_by_key(self):
        page = broken(self.golden, "<br>status: in progress", "<br>status: mitigated")
        self.assertEqual(self.parse(page)["statuses"], {"disk-growth": "mitigated"})

    def test_a_status_equal_to_the_stored_one_is_no_edit(self):
        page = broken(self.golden, "<br>status: in progress", "<br>status: in progress ")
        edits = self.parse(page)
        self.assertEqual((edits["statuses"], edits["ignored"]), ({}, []))

    def test_each_status_of_the_closed_list_is_accepted(self):
        statuses = ["open", "mitigated", "decided", "dropped"]
        pages = [broken(self.golden, "<br>status: in progress", f"<br>status: {status}") for status in statuses]
        self.assertEqual(
            [self.parse(page)["statuses"] for page in pages], [{"disk-growth": status} for status in statuses]
        )

    def test_a_status_outside_the_closed_list_is_ignored(self):
        page = broken(self.golden, "<br>status: in progress", "<br>status: maybe later")
        edits = self.parse(page)
        self.assertEqual(
            (edits["statuses"], edits["ignored"]),
            ({}, [{"where": "warning disk-growth", "why": "status outside the allowed values"}]),
        )

    def test_a_removed_status_line_is_ignored(self):
        page = broken(self.golden, "<br>status: in progress", "")
        self.assertEqual(self.parse(page)["ignored"], [{"where": "warning disk-growth", "why": "no status line"}])

    def test_a_warning_row_matching_no_stored_key_is_ignored_by_position(self):
        page = broken(self.golden, "key: disk-growth", "key: unknown-warning")
        page = broken(page, "<br>status: in progress", "<br>status: dropped")
        edits = self.parse(page)
        self.assertEqual(
            (edits["statuses"], edits["ignored"]),
            ({}, [{"where": "warning row 2", "why": "key matches no stored warning"}]),
        )

    def test_a_warning_row_without_a_key_marker_is_ignored_by_position(self):
        page = broken(self.golden, '<br><span color="gray">key: disk-growth</span>', "")
        self.assertEqual(self.parse(page)["ignored"], [{"where": "warning row 2", "why": "no key marker"}])

    def test_a_key_marker_that_is_not_kebab_case_is_ignored(self):
        page = broken(self.golden, "key: disk-growth", "key: Disk Growth")
        self.assertEqual(self.parse(page)["ignored"], [{"where": "warning row 2", "why": "no key marker"}])

    def test_a_warning_key_marker_over_the_key_cap_is_ignored_by_position(self):
        page = broken(self.golden, "key: disk-growth", "key: " + "a" * 61)
        self.assertEqual(self.parse(page)["ignored"], [{"where": "warning row 2", "why": "no key marker"}])

    def test_a_todo_key_marker_over_the_key_cap_is_ignored_by_position(self):
        page = broken(tick(self.golden, "Plan the volume resize"), 'gray">plan-resize<', 'gray">' + "a" * 61 + "<")
        edits = self.parse(page)
        self.assertEqual(
            (edits["ticked"], edits["ignored"]), ([], [{"where": "check 3", "why": "no key marker"}])
        )

    def test_an_edited_title_is_ignored_while_its_status_still_merges(self):
        page = broken(self.golden, "<td>Primary volume filling up<br>", "<td>Primary disk filling up<br>")
        page = broken(page, "<br>status: in progress", "<br>status: dropped")
        edits = self.parse(page)
        self.assertEqual(
            (edits["statuses"], edits["ignored"]),
            ({"disk-growth": "dropped"}, [{"where": "warning disk-growth", "why": "title edited"}]),
        )

    def test_a_repeated_warning_key_merges_only_its_first_row(self):
        page = broken(self.golden, "key: restore-untested", "key: disk-growth")
        marker = '<br><span color="gray">key: disk-growth'
        page = broken(page, "<br>status: open" + marker, "<br>status: dropped" + marker)
        edits = self.parse(page)
        self.assertEqual(
            (edits["statuses"], edits["ignored"]),
            ({}, [{"where": "warning disk-growth", "why": "key repeated"}]),
        )

    def test_a_todo_matching_no_stored_key_is_ignored_by_position(self):
        page = broken(tick(self.golden, "Plan the volume resize"), 'gray">plan-resize<', 'gray">other-check<')
        edits = self.parse(page)
        self.assertEqual(
            (edits["ticked"], edits["ignored"]),
            ([], [{"where": "check 3", "why": "key matches no stored check"}]),
        )

    def test_a_todo_without_a_key_marker_is_ignored_by_position(self):
        page = broken(tick(self.golden, "Plan the volume resize"), ' <span color="gray">plan-resize</span>', "")
        edits = self.parse(page)
        self.assertEqual(
            (edits["ticked"], edits["ignored"]),
            ([], [{"where": "check 3", "why": "no key marker"}]),
        )

    def test_an_edited_todo_text_is_ignored_while_its_tick_still_merges(self):
        page = broken(tick(self.golden, "Plan the volume resize"), "Plan the volume resize <span", "Plan the volume resize now <span")
        edits = self.parse(page)
        self.assertEqual(
            (edits["ticked"], edits["ignored"]),
            (["plan-resize"], [{"where": "check plan-resize", "why": "text edited"}]),
        )

    def test_a_todo_without_a_tag_still_parses_its_marker(self):
        page = broken(tick(self.golden, "Plan the volume resize"), '<span color="gray_bg">Capacity</span> Plan', "Plan")
        self.assertEqual(self.parse(page)["ticked"], ["plan-resize"])

    def test_the_page_wrapper_of_a_fetch_does_not_matter(self):
        head = '<page url="https://example.com/p/1">\n<properties>\n{"title":"Sample"}\n</properties>\n<content>\n'
        wrapped = head + self.golden + "</content>\n</page>\n"
        page = broken(wrapped, "<br>status: in progress", "<br>status: decided")
        self.assertEqual(self.parse(page)["statuses"], {"disk-growth": "decided"})

    def test_text_outside_the_warning_tables_and_checks_is_never_read(self):
        stray = '- [x] <span color="gray_bg">Capacity</span> Plan the volume resize <span color="gray">plan-resize</span>'
        self.assertEqual(self.parse(self.golden + "\n" + stray + "\n")["ticked"], [])

    def test_the_edits_carry_the_page_id_and_the_edit_time(self):
        edits = self.parse(self.golden, page_id="previous-page-id")
        self.assertEqual(
            (edits["page_id"], edits["edited_at"], edits["after_written"]),
            ("previous-page-id", EDITED_AT, True),
        )


class EditTimeTests(PageCase):
    def edited_page(self):
        page = broken(self.golden, "<br>status: in progress", "<br>status: dropped")
        return tick(page, "Plan the volume resize")

    def test_an_edit_before_the_write_time_reports_nothing(self):
        edits = self.parse(self.edited_page(), edited_at="2026-03-11T08:33:59Z")
        self.assertEqual(
            (edits["after_written"], edits["statuses"], edits["ticked"], edits["unticked"], edits["ignored"]),
            (False, {}, [], [], []),
        )

    def test_an_edit_in_the_minute_of_the_write_time_reports_nothing(self):
        edits = self.parse(self.edited_page(), edited_at="2026-03-11T08:34:59Z")
        self.assertEqual((edits["after_written"], edits["statuses"], edits["ticked"]), (False, {}, []))

    def test_an_edit_at_the_write_time_reports_nothing(self):
        edits = self.parse(self.edited_page(), edited_at=WRITTEN_AT)
        self.assertEqual((edits["after_written"], edits["statuses"], edits["ticked"]), (False, {}, []))

    def test_an_edit_in_the_next_minute_is_after_the_write_time(self):
        edits = self.parse(self.edited_page(), edited_at="2026-03-11T08:35:00Z", written_at="2026-03-11T08:34:59Z")
        self.assertEqual(
            (edits["after_written"], edits["statuses"], edits["ticked"]),
            (True, {"disk-growth": "dropped"}, ["plan-resize"]),
        )

    def test_a_search_time_with_milliseconds_compares_at_minute_precision(self):
        edits = self.parse(self.edited_page(), edited_at="2026-03-11T08:34:30.000Z", written_at="2026-03-11T08:34:10Z")
        self.assertFalse(edits["after_written"])

    def test_offsets_compare_as_the_same_instant(self):
        edits = self.parse(self.edited_page(), edited_at="2026-03-11T10:35:00+02:00", written_at="2026-03-11T08:34:00Z")
        self.assertTrue(edits["after_written"])


class RoundTripTests(PageCase):
    def test_a_rendered_page_parses_to_no_edits(self):
        edits = self.parse(self.render())
        self.assertEqual((edits["statuses"], edits["ticked"], edits["ignored"]), ({}, [], []))

    def test_a_rendered_page_reports_every_stored_check_as_unticked(self):
        edits = self.parse(self.render())
        self.assertEqual(edits["unticked"], sorted(self.summary["checks"]))

    def test_a_rendered_page_with_no_warning_parses_to_no_edits(self):
        page = self.render(warnings={}, checks={}, decisions=[], details={})
        edits = tribe_page.parse_edits(page, {"warnings": {}, "checks": {}}, WRITTEN_AT, EDITED_AT)
        self.assertEqual((edits["statuses"], edits["ticked"], edits["unticked"], edits["ignored"]), ({}, [], [], []))


if __name__ == "__main__":
    unittest.main()
