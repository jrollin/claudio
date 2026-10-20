import json
import os
import unittest

import relay_capture
import tribe_publish
from state import InputError, dump
from support import RELAY_START_NS
from tribe_support import (
    CONNECTOR, NEW_PAGE, NOW, PARENT, PublishCase, RUN_WEEK, TZ, fixture,
)

TASK = "task-7"
CREATED = json.dumps({"task": {"id": TASK, "status": "pending"}})
RUNNING = json.dumps({"task": {"id": TASK, "status": "running"}})
FINISHED = json.dumps({"task": {"id": TASK, "status": "completed", "page": {"id": NEW_PAGE}}})
FAILED = json.dumps({"task": {"id": TASK, "status": "failed"}})
APPENDED = json.dumps({"block": {"id": "b-1"}})


class RenderTests(PublishCase):
    def test_writes_the_page_of_the_summary(self):
        self.assertEqual(self.render(), (0, ""))
        self.assertEqual(self.page(), fixture("page_golden.md"))

    def test_the_month_end_group_takes_the_last_day_of_the_month_of_the_run_in_the_config_zone(self):
        self.use_summary(run_at="2026-10-31T23:30:00Z")
        self.assertEqual(self.render(), (0, ""))
        self.assertIn("### Before the 2026-11-30 month-end\n", self.page())

    def test_a_failed_structure_check_exits_3_and_writes_no_page(self):
        decision = self.summary_doc["decisions"][0]
        self.use_summary(decisions=[decision] * 4)
        code, err = self.render()
        self.assertEqual(code, 3)
        self.assertIn("structure check failed", err)
        self.assertIn("decisions: 4 rows", err)
        self.assertFalse(os.path.exists(self.path("page.md")))

    def test_a_routine_without_page_values_exits_2_naming_the_key_path(self):
        self.use_config(lambda routine: routine.pop("page"))
        code, err = self.render()
        self.assertEqual((code, "routines.tribe-digest.page" in err), (2, True))

    def test_a_window_timestamp_out_of_the_platform_range_exits_2(self):
        self.use_summary(window={"from_ts": 0, "to_ts": 10**20})
        self.assertEqual(self.render()[0], 2)

    def test_a_summary_that_cannot_be_rendered_exits_2(self):
        self.write("summary.json", {"title": "x"})
        code, err = self.render()
        self.assertEqual((code, "summary" in err), (2, True))

    def test_a_routine_of_the_default_engine_exits_2(self):
        self.use_config(lambda routine: routine.pop("engine"))
        code, err = self.render()
        self.assertEqual((code, "not a tribe routine" in err), (2, True))


    def test_the_previous_page_mention_uses_the_link_of_the_page_values(self):
        self.use_config(lambda routine: routine["page"].update({"link": "https://docs.example.com/p/{{id}}/view"}))
        self.assertEqual(self.render(), (0, ""))
        self.assertIn('<mention-page url="https://docs.example.com/p/previous-page-id/view"/>', self.page())


class PlanTests(PublishCase):
    def test_the_first_step_creates_the_page_under_the_main_page(self):
        plan = self.planned()
        page = self.page()
        call = {
            "id": "publish-1",
            "connector": CONNECTOR,
            "tool": "page_create",
            "arguments": {"parent": PARENT, "title": "Sample digest : 2026-03-12", "content": page, "day": "2026-03-12", "background": True},
        }
        self.assertEqual(plan, {"done": False, "partial": None, "calls": [call]})

    def test_the_plan_file_is_canonical_json(self):
        self.planned()
        self.assert_canonical("plan.json")

    def test_a_placeholder_inside_the_page_is_not_substituted(self):
        self.use_summary(highlights=[{"text": "uses {{task}} markers", "cites": []}])
        self.assertIn("{{task}}", self.planned()["calls"][0]["arguments"]["content"])

    def test_the_second_step_polls_the_task_of_the_create_result(self):
        self.save(1, CREATED)
        call = {"id": "publish-2", "connector": CONNECTOR, "tool": "task_poll", "arguments": {"task": TASK}}
        self.assertEqual(self.planned(), {"done": False, "partial": None, "calls": [call]})

    def test_a_harness_wrapped_result_is_unwrapped(self):
        self.save(1, json.dumps([{"type": "text", "text": CREATED}]))
        self.assertEqual(self.planned()["calls"][0]["id"], "publish-2")

    def test_a_running_task_is_polled_again(self):
        self.save(1, CREATED)
        self.save(2, RUNNING)
        call = {"id": "publish-3", "connector": CONNECTOR, "tool": "task_poll", "arguments": {"task": TASK}}
        self.assertEqual(self.planned()["calls"], [call])

    def test_polling_stops_after_20_polls(self):
        self.save(1, CREATED)
        for number in range(2, 21):
            self.save(number, RUNNING)
        self.assertEqual(self.planned()["calls"][0]["id"], "publish-21")
        self.save(21, RUNNING)
        plan = self.planned()
        self.assertEqual((plan["done"], plan["calls"]), (True, []))
        self.assertIn("20 polls", plan["partial"])

    def test_a_due_heading_is_planned_before_the_create(self):
        self.due_heading()
        call = {
            "id": "publish-1",
            "connector": CONNECTOR,
            "tool": "page_append",
            "arguments": {"parent": PARENT, "content": f"## {RUN_WEEK} from 2026-03-09"},
        }
        self.assertEqual(self.planned(), {"done": False, "partial": None, "calls": [call]})

    def test_the_create_follows_a_written_heading(self):
        self.due_heading()
        self.save(1, APPENDED)
        plan = self.planned()
        self.assertEqual((plan["calls"][0]["id"], plan["calls"][0]["tool"]), ("publish-2", "page_create"))

    def test_the_create_still_follows_a_failed_heading(self):
        self.due_heading()
        self.save(1, "tool error")
        plan = self.planned()
        self.assertEqual((plan["done"], plan["calls"][0]["id"], plan["calls"][0]["tool"]), (False, "publish-2", "page_create"))

    def test_the_polls_follow_a_create_that_follows_the_heading(self):
        self.due_heading()
        self.save(1, APPENDED)
        self.save(2, CREATED)
        self.assertEqual(self.planned()["calls"][0]["id"], "publish-3")

    def test_the_plan_ends_once_the_task_finished_after_the_heading(self):
        self.due_heading()
        self.save(1, APPENDED)
        self.save(2, CREATED)
        self.save(3, FINISHED)
        self.assertEqual(self.planned(), {"done": True, "partial": None, "calls": []})

    def test_polling_after_a_heading_stops_after_20_polls(self):
        self.due_heading()
        self.save(1, APPENDED)
        self.save(2, CREATED)
        for number in range(3, 23):
            self.save(number, RUNNING)
        plan = self.planned()
        self.assertEqual((plan["done"], plan["calls"]), (True, []))
        self.assertIn("20 polls", plan["partial"])

    def test_no_heading_is_planned_when_the_week_was_written(self):
        self.save(1, CREATED)
        self.save(2, FINISHED)
        self.assertEqual(self.planned(), {"done": True, "partial": None, "calls": []})

    def test_the_run_week_is_read_in_the_configured_timezone(self):
        self.use_summary(run_at="2026-10-18T22:30:00Z", window={"from_ts": 1792000000, "to_ts": 1792362600})
        self.use_state(weekly_heading_week="2026-W42")
        self.assertEqual(TZ, "Europe/Paris")
        self.assertEqual(self.planned()["calls"][0]["arguments"]["content"], "## 2026-W43 from 2026-10-19")

    def test_the_heading_week_of_a_late_sunday_is_not_due_again_on_the_next_run(self):
        self.use_summary(run_at="2026-10-18T22:30:00Z", window={"from_ts": 1792000000, "to_ts": 1792362600})
        self.use_state(weekly_heading_week="2026-W43")
        self.assertEqual(self.planned()["calls"][0]["tool"], "page_create")

    def test_the_date_is_the_local_date_of_the_run(self):
        self.use_summary(run_at="2026-10-18T22:30:00Z", window={"from_ts": 1792000000, "to_ts": 1792362600})
        self.use_state(weekly_heading_week="2026-W43")
        arguments = self.planned()["calls"][0]["arguments"]
        self.assertEqual((arguments["day"], arguments["title"]), ("2026-10-19", "Sample digest : 2026-10-19"))

    def test_the_week_start_uses_the_configured_format(self):
        self.use_config(lambda routine: routine["publish"].update({"week_start_format": "%d %b %Y"}))
        self.due_heading()
        self.assertEqual(self.planned()["calls"][0]["arguments"]["content"], f"## {RUN_WEEK} from 09 Mar 2026")

    def test_the_title_is_the_rendered_page_title_template(self):
        self.use_config(lambda routine: routine["page"].update({"title": "Digest of {{date}}"}))
        self.assertEqual(self.planned()["calls"][0]["arguments"]["title"], "Digest of 2026-03-12")

    def test_a_result_path_can_index_a_list(self):
        self.use_config(lambda routine: routine["publish"]["results"].update({"page": "task.pages.0.id"}))
        self.save(1, CREATED)
        self.save(2, json.dumps({"task": {"id": TASK, "status": "completed", "pages": [{"id": NEW_PAGE}]}}))
        self.assertEqual(self.planned(), {"done": True, "partial": None, "calls": []})

    def test_a_result_path_past_the_end_of_a_list_finds_nothing(self):
        self.use_config(lambda routine: routine["publish"]["results"].update({"page": "task.pages.1.id"}))
        self.save(1, CREATED)
        self.save(2, json.dumps({"task": {"id": TASK, "status": "completed", "pages": [{"id": NEW_PAGE}]}}))
        self.assertIn("no page id at task.pages.1.id", self.planned()["partial"])

    def test_a_report_only_run_plans_no_write(self):
        self.use_summary(report_only=True)
        self.assertEqual(self.planned(), {"done": True, "partial": None, "calls": []})

    def test_a_create_result_without_a_task_id_ends_the_plan_with_the_reason(self):
        self.save(1, json.dumps({"error": "denied"}))
        plan = self.planned()
        self.assertEqual((plan["done"], plan["calls"]), (True, []))
        self.assertIn("task.id", plan["partial"])

    def test_a_create_result_that_is_not_json_ends_the_plan(self):
        self.save(1, "connector signed out")
        plan = self.planned()
        self.assertEqual((plan["done"], plan["calls"]), (True, []))
        self.assertIn("publish-1", plan["partial"])

    def test_a_failed_task_ends_the_plan_with_the_reason(self):
        self.save(1, CREATED)
        self.save(2, FAILED)
        plan = self.planned()
        self.assertEqual((plan["done"], plan["calls"]), (True, []))
        self.assertIn("failed", plan["partial"])

    def test_a_task_id_with_unsafe_characters_is_refused(self):
        self.save(1, json.dumps({"task": {"id": "x; rm -rf /"}}))
        plan = self.planned()
        self.assertEqual(plan["calls"], [])
        self.assertIn("task.id", plan["partial"])

    def test_a_page_that_fails_the_structure_check_is_refused_before_any_call(self):
        self.assertEqual(self.render(), (0, ""))
        with open(self.path("page.md"), "w", encoding="utf-8") as handle:
            handle.write(self.page().replace("## Warnings", "## Risks"))
        code, err = self.plan()
        self.assertEqual((code, "structure check failed" in err), (3, True))

    def test_an_unknown_placeholder_exits_2_naming_the_key_path(self):
        self.rendered_then(lambda routine: routine["publish"]["poll"]["arguments"].update({"extra": "{{missing}}"}))
        self.save(1, CREATED)
        code, err = self.plan()
        self.assertEqual(code, 2)
        self.assertIn("routines.tribe-digest.publish.poll.arguments.extra", err)

    def test_a_publish_provider_without_a_connector_exits_2(self):
        self.use_config(lambda routine: routine["publish"].update({"provider": "chat"}))
        code, err = self.plan()
        self.assertEqual((code, "routines.tribe-digest.publish.provider" in err), (2, True))

    def test_a_routine_without_publish_values_exits_2(self):
        self.assertEqual(self.render(), (0, ""))
        self.use_config(lambda routine: routine.pop("publish"))
        code, err = self.plan()
        self.assertEqual((code, "routines.tribe-digest.publish" in err), (2, True))

    def test_an_empty_done_list_exits_2_naming_the_key_path(self):
        self.rendered_then(lambda routine: routine["publish"]["results"].update({"done": []}))
        code, err = self.plan()
        self.assertEqual((code, "routines.tribe-digest.publish.results.done" in err), (2, True))


    def rendered_then(self, change):
        self.assertEqual(self.render(), (0, ""))
        self.use_config(change)

    def test_a_bad_heading_template_exits_2_before_any_call(self):
        self.rendered_then(lambda routine: routine["publish"]["heading"]["arguments"].update({"content": "## {{ week }}"}))
        code, err = self.plan()
        self.assertEqual(code, 2)
        self.assertIn("routines.tribe-digest.publish.heading.arguments.content", err)
        self.assertFalse(os.path.exists(self.path("plan.json")))

    def test_a_bad_template_exits_2_on_a_report_only_run_too(self):
        self.use_summary(report_only=True)
        self.rendered_then(lambda routine: routine["publish"]["create"]["arguments"].update({"title": "{{ title }}"}))
        code, err = self.plan()
        self.assertEqual((code, "publish.create.arguments.title" in err), (2, True))
        self.assertFalse(os.path.exists(self.path("plan.json")))

    def test_a_task_placeholder_outside_the_poll_exits_2(self):
        self.rendered_then(lambda routine: routine["publish"]["heading"]["arguments"].update({"content": "{{task}}"}))
        self.assertEqual(self.plan()[0], 2)

    def test_a_dotted_path_into_a_value_that_is_not_an_object_finds_nothing(self):
        self.save(1, json.dumps({"task": "plain"}))
        plan = self.planned()
        self.assertEqual(plan["calls"], [])
        self.assertIn("task.id", plan["partial"])

    def test_a_poll_result_without_a_status_ends_the_plan_with_the_reason(self):
        self.save(1, CREATED)
        self.save(2, json.dumps({"task": {"id": TASK}}))
        plan = self.planned()
        self.assertEqual(plan["calls"], [])
        self.assertIn("no status at task.status", plan["partial"])

    def test_a_cancelled_task_ends_the_plan_with_the_reason(self):
        self.save(1, CREATED)
        self.save(2, json.dumps({"task": {"id": TASK, "status": "cancelled"}}))
        plan = self.planned()
        self.assertEqual((plan["done"], plan["calls"]), (True, []))
        self.assertIn("cancelled", plan["partial"])


class RelayCaptureTests(PublishCase):
    def plan_at(self, offset):
        self.relay_clock.now_ns = RELAY_START_NS + offset
        return self.planned()

    def capture(self, call, text, offset, tool=None, arguments=None):
        at = RELAY_START_NS + offset
        document = {
            "tool_name": tool or f"mcp__{call['connector']}__{call['tool']}",
            "arguments": call["arguments"] if arguments is None else arguments,
            "text": text,
            "captured_at_ns": at,
        }
        relay_capture.write_capture(self.relay_dir, f"{at}-toolu_{call['id']}.json", document)

    def saved(self, number):
        with open(os.path.join(self.responses, f"publish-{number}.txt"), "rb") as handle:
            return handle.read()

    def planned_doc(self):
        with open(os.path.join(self.responses, "planned.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def test_a_captured_create_is_saved_and_the_poll_is_asked(self):
        (create,) = self.plan_at(0)["calls"]
        self.capture(create, CREATED, 1)
        plan = self.plan_at(2)
        self.assertEqual((self.saved(1), plan["calls"][0]["id"], plan["calls"][0]["arguments"]), (CREATED.encode(), "publish-2", {"task": TASK}))

    def test_walks_to_done_through_captures_only(self):
        for offset, text in ((0, CREATED), (10, RUNNING), (20, FINISHED)):
            (call,) = self.plan_at(offset)["calls"]
            self.capture(call, text, offset + 1)
        self.assertEqual(self.plan_at(30), {"done": True, "partial": None, "calls": []})

    def test_chains_the_pick_ups_of_calls_planned_in_earlier_runs(self):
        (create,) = self.plan_at(0)["calls"]
        poll = {"id": "publish-2", "connector": CONNECTOR, "tool": "task_poll", "arguments": {"task": TASK}}
        with open(os.path.join(self.responses, "planned.json"), "wb") as handle:
            handle.write(dump({"planned": {"publish-1": RELAY_START_NS, "publish-2": RELAY_START_NS}}))
        self.capture(create, CREATED, 1)
        self.capture(poll, FINISHED, 1)
        self.assertEqual(self.plan_at(2), {"done": True, "partial": None, "calls": []})

    def test_the_results_walked_through_captures_give_a_created_page(self):
        for offset, text in ((0, CREATED), (10, FINISHED)):
            (call,) = self.plan_at(offset)["calls"]
            self.capture(call, text, offset + 1)
        self.plan_at(20)
        _, result = self.parsed()
        self.assertEqual((result["status"], result["page"] is not None), ("created", True))

    def test_a_captured_heading_is_saved_and_the_create_is_asked(self):
        self.due_heading()
        (heading,) = self.plan_at(0)["calls"]
        self.capture(heading, APPENDED, 1)
        plan = self.plan_at(2)
        self.assertEqual((self.saved(1), plan["calls"][0]["tool"]), (APPENDED.encode(), "page_create"))

    def test_the_captured_text_is_saved_unchanged(self):
        text = json.dumps({"task": {"id": TASK, "status": "pending", "note": "caf\u00e9 " + chr(0x1F600)}}, ensure_ascii=False) + "\r\n"
        (create,) = self.plan_at(0)["calls"]
        self.capture(create, text, 1)
        self.plan_at(2)
        self.assertEqual(self.saved(1), text.encode("utf-8"))

    def test_records_the_time_each_call_was_first_planned(self):
        (create,) = self.plan_at(0)["calls"]
        self.capture(create, CREATED, 1)
        self.plan_at(5)
        self.assertEqual(self.planned_doc(), {"planned": {"publish-1": RELAY_START_NS, "publish-2": RELAY_START_NS + 5}})

    def test_ignores_a_capture_taken_before_the_call_was_planned(self):
        (create,) = self.plan_at(0)["calls"]
        self.capture(create, CREATED, -1)
        plan = self.plan_at(5)
        self.assertEqual((plan["calls"][0]["id"], os.path.exists(os.path.join(self.responses, "publish-1.txt"))), ("publish-1", False))

    def test_lists_the_same_call_again_without_a_capture(self):
        first = self.plan_at(0)
        self.assertEqual(self.plan_at(5), first)

    def test_keeps_the_first_planned_time_when_a_call_is_listed_again(self):
        self.plan_at(0)
        self.plan_at(5)
        self.assertEqual(self.planned_doc(), {"planned": {"publish-1": RELAY_START_NS}})

    def test_a_result_saved_by_hand_still_moves_the_plan_on(self):
        self.plan_at(0)
        self.plan_at(5)
        self.save(1, CREATED)
        self.assertEqual(self.plan_at(6)["calls"][0]["id"], "publish-2")

    def test_ignores_a_capture_with_other_arguments(self):
        (create,) = self.plan_at(0)["calls"]
        self.capture(create, CREATED, 1, arguments={**create["arguments"], "title": "another"})
        self.assertEqual(self.plan_at(2)["calls"][0]["id"], "publish-1")

    def test_ignores_a_capture_of_another_connector(self):
        (create,) = self.plan_at(0)["calls"]
        self.capture(create, CREATED, 1, tool="mcp__other__page_create")
        self.assertEqual(self.plan_at(2)["calls"][0]["id"], "publish-1")

    def test_ignores_a_capture_of_another_tool(self):
        (create,) = self.plan_at(0)["calls"]
        self.capture(create, CREATED, 1, tool=f"mcp__{CONNECTOR}__task_poll")
        self.assertEqual(self.plan_at(2)["calls"][0]["id"], "publish-1")

    def test_a_poll_is_matched_by_its_task(self):
        self.save(1, CREATED)
        (poll,) = self.plan_at(0)["calls"]
        self.capture(poll, RUNNING, 1, arguments={"task": "task-8"})
        self.assertEqual(self.plan_at(2)["calls"][0]["id"], "publish-2")

    def test_a_report_only_run_writes_no_planned_file(self):
        self.use_summary(report_only=True)
        self.plan_at(0)
        self.assertEqual(os.listdir(self.responses), [])

    def test_the_planned_file_is_canonical_json(self):
        self.plan_at(0)
        with open(os.path.join(self.responses, "planned.json"), "rb") as handle:
            raw = handle.read()
        self.assertEqual(raw, dump(json.loads(raw)))


class ParseTests(PublishCase):
    def finish(self):
        self.save(1, CREATED)
        self.save(2, RUNNING)
        self.save(3, FINISHED)

    def finish_after_heading(self, heading=APPENDED):
        self.due_heading()
        if heading is not None:
            self.save(1, heading)
        self.save(2, CREATED)
        self.save(3, RUNNING)
        self.save(4, FINISHED)

    def test_a_created_page_becomes_the_previous_page_and_the_heading_week_moves(self):
        self.finish_after_heading()
        document, result = self.parsed()
        expected = self.stored(previous_page={"id": NEW_PAGE, "written_at": NOW}, weekly_heading_week=RUN_WEEK)
        self.assertEqual(document, expected)
        self.assertEqual(result, {"status": "created", "page": NEW_PAGE, "reason": None, "heading": "written", "heading_reason": None})
        self.assert_canonical("next.json")
        self.assert_canonical("result.json")

    def test_a_page_id_is_stored_lowercase_without_dashes(self):
        self.save(1, CREATED)
        self.save(2, json.dumps({"task": {"id": TASK, "status": "completed", "page": {"id": "AbCd-12-34"}}}))
        document, result = self.parsed()
        self.assertEqual((document["run"]["previous_page"]["id"], result["page"]), ("abcd1234", "abcd1234"))

    def test_a_page_id_of_dashes_only_is_a_failed_create(self):
        self.save(1, CREATED)
        self.save(2, json.dumps({"task": {"id": TASK, "status": "completed", "page": {"id": "---"}}}))
        self.assertEqual(self.parse(), (0, ""))
        self.assertEqual(self.read("result.json")["status"], "failed")

    def test_a_page_id_read_from_a_list_index(self):
        self.use_config(lambda routine: routine["publish"]["results"].update({"page": "task.pages.0.id"}))
        self.save(1, CREATED)
        self.save(2, json.dumps({"task": {"id": TASK, "status": "completed", "pages": [{"id": NEW_PAGE}]}}))
        self.assertEqual(self.parsed()[1]["page"], NEW_PAGE)

    def test_a_failed_heading_keeps_the_week_and_the_page_is_still_created(self):
        self.finish_after_heading(heading="tool error")
        document, result = self.parsed()
        self.assertEqual(document["run"]["previous_page"], {"id": NEW_PAGE, "written_at": NOW})
        self.assertEqual(document["run"]["weekly_heading_week"], "2026-W10")
        self.assertEqual((result["status"], result["heading"]), ("created", "failed"))
        self.assertIn("block.id", result["heading_reason"])

    def test_a_heading_without_a_saved_result_fails_the_run_before_the_create(self):
        self.due_heading()
        self.assertEqual(self.parse(), (0, ""))
        self.assertEqual(self.raw("next.json"), self.raw("state.json"))
        result = self.read("result.json")
        self.assertEqual((result["status"], result["heading"], result["reason"]), ("failed", "skipped", "publish-1: no result saved"))

    def test_a_failed_create_after_a_written_heading_leaves_the_state_unchanged_and_reports_the_heading(self):
        self.due_heading()
        self.save(1, APPENDED)
        self.save(2, "connector signed out")
        self.assertEqual(self.parse(), (0, ""))
        self.assertEqual(self.raw("next.json"), self.raw("state.json"))
        result = self.read("result.json")
        self.assertEqual((result["status"], result["heading"]), ("failed", "written"))

    def test_a_heading_not_due_leaves_the_week(self):
        self.finish()
        document, result = self.parsed()
        self.assertEqual((document["run"]["weekly_heading_week"], result["heading"]), (RUN_WEEK, "skipped"))
        self.assertEqual(document["run"]["previous_page"]["id"], NEW_PAGE)

    def test_the_week_follows_the_configured_timezone(self):
        self.use_summary(run_at="2026-10-18T22:30:00Z", window={"from_ts": 1792000000, "to_ts": 1792362600})
        self.use_state(weekly_heading_week="2026-W42")
        self.save(1, APPENDED)
        self.save(2, CREATED)
        self.save(3, FINISHED)
        document, _ = self.parsed()
        self.assertEqual(document["run"]["weekly_heading_week"], "2026-W43")

    def test_written_at_is_the_now_flag(self):
        self.finish()
        self.assertEqual(self.parse("2026-10-16T09:10:11+02:00"), (0, ""))
        self.assertEqual(self.read("next.json")["run"]["previous_page"]["written_at"], "2026-10-16T07:10:11Z")

    def test_a_failed_create_leaves_the_state_unchanged_and_reports_the_reason(self):
        self.save(1, "connector signed out")
        code, err = self.parse()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.raw("next.json"), self.raw("state.json"))
        result = self.read("result.json")
        self.assertEqual((result["status"], result["page"], result["heading"]), ("failed", None, "skipped"))
        self.assertIn("publish-1", result["reason"])

    def test_a_failed_task_leaves_the_state_unchanged(self):
        self.save(1, CREATED)
        self.save(2, FAILED)
        self.assertEqual(self.parse(), (0, ""))
        self.assertEqual(self.raw("next.json"), self.raw("state.json"))
        self.assertIn("failed", self.read("result.json")["reason"])

    def test_a_task_still_running_after_20_polls_is_a_failed_create(self):
        self.save(1, CREATED)
        for number in range(2, 22):
            self.save(number, RUNNING)
        self.assertEqual(self.parse(), (0, ""))
        self.assertEqual(self.raw("next.json"), self.raw("state.json"))
        self.assertIn("20 polls", self.read("result.json")["reason"])

    def test_a_create_without_any_saved_result_is_a_failed_create(self):
        self.assertEqual(self.parse(), (0, ""))
        result = self.read("result.json")
        self.assertEqual(result["status"], "failed")
        self.assertIn("publish-1: no result saved", result["reason"])

    def test_a_poll_without_a_saved_result_is_a_failed_create(self):
        self.save(1, CREATED)
        self.assertEqual(self.parse(), (0, ""))
        self.assertIn("publish-2: no result saved", self.read("result.json")["reason"])

    def test_a_page_id_that_is_not_an_id_is_a_failed_create(self):
        self.save(1, CREATED)
        self.save(2, json.dumps({"task": {"id": TASK, "status": "completed", "page": {"id": "a/b"}}}))
        self.assertEqual(self.parse(), (0, ""))
        result = self.read("result.json")
        self.assertEqual(result["status"], "failed")
        self.assertIn("task.page.id", result["reason"])

    def test_a_report_only_run_leaves_the_state_unchanged(self):
        self.use_summary(report_only=True)
        self.assertEqual(self.parse(), (0, ""))
        self.assertEqual(self.raw("next.json"), self.raw("state.json"))
        self.assertEqual(self.read("result.json")["status"], "report-only")

    def test_a_now_without_an_offset_exits_2(self):
        self.finish()
        code, err = self.parse("2026-10-16T07:45:00")
        self.assertEqual((code, "--now" in err), (2, True))
        self.assertFalse(os.path.exists(self.path("next.json")))

    def test_the_other_state_sections_are_untouched(self):
        self.finish()
        document, _ = self.parsed()
        expected = self.stored()
        for section in ("warnings", "checks", "cursors", "threads", "blind_spots", "retired"):
            self.assertEqual(document[section], expected[section])

    def test_a_missing_responses_directory_is_an_empty_one(self):
        os.rmdir(self.responses)
        self.assertEqual(self.parse(), (0, ""))
        self.assertEqual(self.raw("next.json"), self.raw("state.json"))
        result = self.read("result.json")
        self.assertEqual((result["status"], result["reason"]), ("failed", "publish-1: no result saved"))

    def test_a_cancelled_task_is_a_failed_create(self):
        self.save(1, CREATED)
        self.save(2, json.dumps({"task": {"id": TASK, "status": "cancelled"}}))
        self.assertEqual(self.parse(), (0, ""))
        self.assertEqual(self.raw("next.json"), self.raw("state.json"))
        self.assertEqual(self.read("result.json")["reason"], f"publish-2: task {TASK} cancelled")

    def test_a_poll_result_without_a_status_is_a_failed_create(self):
        self.save(1, CREATED)
        self.save(2, json.dumps({"task": {"id": TASK}}))
        self.assertEqual(self.parse(), (0, ""))
        self.assertIn("no status at task.status", self.read("result.json")["reason"])

    def test_a_dotted_path_into_a_value_that_is_not_an_object_is_a_failed_create(self):
        self.save(1, json.dumps({"task": "plain"}))
        self.assertEqual(self.parse(), (0, ""))
        self.assertIn("no task id at task.id", self.read("result.json")["reason"])

    def test_a_bad_template_exits_2_and_writes_nothing(self):
        self.use_config(lambda routine: routine["publish"]["heading"]["arguments"].update({"content": "## {{ week }}"}))
        self.finish()
        code, err = self.parse()
        self.assertEqual((code, "publish.heading.arguments.content" in err), (2, True))
        self.assertEqual([os.path.exists(self.path(name)) for name in ("next.json", "result.json")], [False, False])


class UnitTests(unittest.TestCase):
    def test_the_week_uses_the_iso_year_at_the_year_boundary(self):
        zone = tribe_publish.state.load_zone("Europe/Paris")
        self.assertEqual(tribe_publish.run_values("2026-12-31T23:30:00Z", zone)["week"], "2026-W53")
        self.assertEqual(tribe_publish.run_values("2027-01-03T12:00:00Z", zone)["week"], "2026-W53")

    def test_the_week_start_is_the_monday_of_the_iso_week(self):
        zone = tribe_publish.state.load_zone("Europe/Paris")
        self.assertEqual(tribe_publish.run_values("2027-01-03T12:00:00Z", zone)["week_start"], "2026-12-28")

    def test_the_week_start_follows_the_given_format(self):
        zone = tribe_publish.state.load_zone("Europe/Paris")
        self.assertEqual(tribe_publish.run_values("2026-03-12T08:30:00Z", zone, "%d/%m/%y")["week_start"], "09/03/26")

    def test_the_date_is_the_local_date(self):
        zone = tribe_publish.state.load_zone("Europe/Paris")
        self.assertEqual(tribe_publish.run_values("2026-10-18T22:30:00Z", zone)["date"], "2026-10-19")

    def test_a_path_into_a_list_needs_a_digit_segment_in_range(self):
        document = {"a": [{"b": "x"}]}
        found = {path: tribe_publish.at_path(document, path) for path in ("a.0.b", "a.1.b", "a.b", "a.0.b.c")}
        self.assertEqual(found, {"a.0.b": "x", "a.1.b": None, "a.b": None, "a.0.b.c": None})

    def test_fill_rejects_a_placeholder_with_spaces(self):
        with self.assertRaises(InputError) as caught:
            tribe_publish.fill({"a": "{{ title }}"}, {"title": "x"}, "routines.r.publish.create.arguments")
        self.assertIn("routines.r.publish.create.arguments.a: unknown placeholder", str(caught.exception))

    def test_fill_rejects_a_value_the_call_does_not_know(self):
        with self.assertRaises(InputError):
            tribe_publish.fill(["{{task}}"], {"title": "x"}, "p")

    def test_fill_replaces_placeholders_in_nested_strings_only_once(self):
        template = {"a": ["x {{one}}", {"b": "{{two}}"}], "c": 3, "d": True}
        values = {"one": "{{two}}", "two": "2"}
        self.assertEqual(tribe_publish.fill(template, values, "p"), {"a": ["x {{two}}", {"b": "2"}], "c": 3, "d": True})


if __name__ == "__main__":
    unittest.main()
