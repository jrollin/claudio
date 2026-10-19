import os
import unittest

import tribe_page
from tribe_support import (
    FileCase, NEW_PAGE, NOW, TZ, fixture, fixture_json, run_cli,
)

SLUG = "tribe-digest"
PAGE_LINK = f"https://example.test/pages/{NEW_PAGE}"
SOURCES = ("channels", "issues", "pages", "monitors", "metrics")
PUBLISH_CALLS = ("publish-1", "publish-2", "publish-3")
NOTE_LINE = "- Mobile app: Not read, no connector is configured for it."


class PipelineCase(FileCase):
    def setUp(self):
        super().setUp()
        self.config = self.write("config.json", fixture_json("pipeline_config.json"))
        self.state = self.write("state.json", fixture_json("pipeline_state.json"))
        self.judgment = self.write("judgment.json", fixture_json("pipeline_judgment.json"))
        self.responses = self.path("responses")

    def tribe(self, *argv):
        code, _, err = run_cli(*argv)
        self.assertEqual((code, err), (0, ""), argv[0])

    def place(self, command, *flags):
        self.tribe(command, "--config", self.config, "--routine", SLUG, "--place", "cloud", *flags)

    def text(self, name):
        with open(self.path(name), encoding="utf-8") as handle:
            return handle.read()

    def raw(self, name):
        with open(self.path(name), "rb") as handle:
            return handle.read()

    def collect(self):
        os.mkdir(self.path("collections"))
        window = self.read("window.json")
        for name, document in fixture_json("pipeline_collections.json").items():
            document["window"] = {"from_ts": window["from_ts"], "to_ts": window["to_ts"]}
            self.write(os.path.join("collections", f"{name}.json"), document)

    def through_apply(self, *window_flags):
        self.tribe("window", "--state", self.state, "--now", NOW, "--tz", TZ, "--out", self.path("window.json"), *window_flags)
        self.collect()
        self.place(
            "features", "--state", self.state, "--window", self.path("window.json"), "--collections", self.path("collections"),
            "--out", self.path("features.json"), "--base-out", self.path("base.json"), "--rules-out", self.path("rules.json"),
        )
        self.tribe("judge", "--features", self.path("features.json"), "--judgment", self.judgment)
        self.tribe(
            "apply", "--state", self.state, "--features", self.path("features.json"), "--base", self.path("base.json"),
            "--judgment", self.judgment, "--window", self.path("window.json"), "--out", self.path("applied.json"),
            "--summary", self.path("summary.json"), "--record", self.path("record.json"),
        )
        self.place("render", "--summary", self.path("summary.json"), "--out", self.path("page.md"))

    def plan(self):
        self.place(
            "publish-plan", "--summary", self.path("summary.json"), "--state", self.path("applied.json"), "--page", self.path("page.md"),
            "--responses", self.responses, "--out", self.path("plan.json"),
        )
        return self.read("plan.json")

    def relay(self):
        os.makedirs(self.responses, exist_ok=True)
        saved = []
        plan = self.plan()
        while not plan["done"]:
            (call,) = plan["calls"]
            saved.append(call)
            with open(os.path.join(self.responses, f"{call['id']}.txt"), "w", encoding="utf-8") as handle:
                handle.write(fixture(f"pipeline_{call['id'].replace('-', '_')}.txt"))
            plan = self.plan()
        return saved, plan

    def through_message(self):
        self.place(
            "publish-parse", "--summary", self.path("summary.json"), "--state", self.path("applied.json"), "--responses", self.responses,
            "--now", NOW, "--out", self.path("next.json"), "--result", self.path("result.json"),
        )
        self.place("message", "--summary", self.path("summary.json"), "--result", self.path("result.json"), "--out", self.path("message.txt"))


class RegularRunTests(PipelineCase):
    def setUp(self):
        super().setUp()
        self.through_apply()
        self.calls, self.plan_done = self.relay()
        self.through_message()

    def test_the_rendered_page_passes_the_structure_check(self):
        self.assertEqual(tribe_page.check(self.text("page.md")), [])

    def test_the_connector_calls_are_the_weekly_heading_then_the_create_and_its_poll(self):
        self.assertEqual([call["id"] for call in self.calls], list(PUBLISH_CALLS))

    def test_the_created_page_takes_the_configured_title_with_the_run_day(self):
        create = self.calls[1]["arguments"]
        self.assertEqual(create["title"], "Sample digest : 2026-10-16")

    def test_a_finished_plan_holds_no_call_and_no_failure(self):
        self.assertEqual((self.plan_done["calls"], self.plan_done["partial"]), ([], None))

    def test_the_state_gains_the_page_id_and_the_run_week(self):
        run = self.read("next.json")["run"]
        self.assertEqual((run["previous_page"], run["weekly_heading_week"]), ({"id": NEW_PAGE, "written_at": NOW}, "2026-W42"))

    def test_the_state_keeps_the_applied_warnings(self):
        self.assertEqual(self.read("next.json")["warnings"]["queue-depth"]["title"], "Queue depth rises")

    def test_the_result_records_the_created_page_and_the_written_heading(self):
        result = self.read("result.json")
        self.assertEqual((result["status"], result["page"], result["heading"]), ("created", NEW_PAGE, "written"))

    def test_the_message_holds_the_page_link(self):
        self.assertIn(f"Page: {PAGE_LINK}", self.text("message.txt"))

    def test_the_record_names_the_sources_read(self):
        self.assertEqual(sorted(self.read("record.json")["sources_read"]), sorted(SOURCES))

    def test_the_summary_holds_the_judged_coverage_note(self):
        self.assertEqual(self.read("summary.json")["coverage_notes"], [{"source": "Mobile app", "text": "Not read, no connector is configured for it"}])

    def test_the_page_lists_the_coverage_note_under_blind_spots(self):
        lines = self.text("page.md").split("\n")
        start = lines.index("## Blind spots")
        end = next(index for index in range(start + 1, len(lines)) if lines[index].startswith("## "))
        self.assertIn(NOTE_LINE, lines[start:end])

    def test_the_message_names_the_coverage_note_source_in_the_blind_spots_line(self):
        line = next(line for line in self.text("message.txt").split("\n") if line.startswith("Blind spots:"))
        self.assertIn("Mobile app", line)

    def test_the_note_is_absent_from_the_applied_and_the_next_state(self):
        self.assertEqual(["Mobile app" in self.text(name) for name in ("applied.json", "next.json")], [False, False])

    def test_the_note_is_absent_from_the_run_record(self):
        self.assertNotIn("Mobile app", self.text("record.json"))


class ReportOnlyRunTests(PipelineCase):
    def setUp(self):
        super().setUp()
        self.through_apply("--report-only")
        self.calls, self.plan_done = self.relay()
        self.through_message()

    def test_the_applied_state_is_byte_identical_to_the_stored_state(self):
        self.assertEqual(self.raw("applied.json"), self.raw("state.json"))

    def test_the_next_state_is_byte_identical_to_the_stored_state(self):
        self.assertEqual(self.raw("next.json"), self.raw("state.json"))

    def test_the_page_is_rendered_and_passes_the_structure_check(self):
        self.assertEqual(tribe_page.check(self.text("page.md")), [])

    def test_the_page_keeps_the_coverage_note(self):
        self.assertIn(NOTE_LINE, self.text("page.md").split("\n"))

    def test_no_connector_call_is_planned(self):
        self.assertEqual((self.calls, self.plan_done["done"]), ([], True))

    def test_the_result_is_report_only_with_no_page(self):
        result = self.read("result.json")
        self.assertEqual((result["status"], result["page"]), ("report-only", None))

    def test_the_message_says_the_page_is_not_written(self):
        self.assertIn("Page: not written, report-only run.", self.text("message.txt"))


if __name__ == "__main__":
    unittest.main()
