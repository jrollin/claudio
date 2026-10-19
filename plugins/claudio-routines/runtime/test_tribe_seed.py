import json
import os
import unittest

import tribe_state
from support import ts
from tribe_support import (
    CHANNEL_A, CHANNEL_B, CHANNEL_C, EDITED_A, EDITED_B, LONG, NOTION_A, NOTION_B, NOW, PAGE_ID, PREVIOUS, SLACK_TS, SLUG, THREAD_TS, TZ,
    UPDATED_MAX, WRITTEN, FileCase, dashed, make_config, make_page, make_run_state, run_cli,
)

LINKS_BASE = "https://chat.example.test"
UNLISTED = "CHAN" + "9" * 6


def thread_link(channel, root_ts):
    return f"{LINKS_BASE}/archives/{channel}/p{root_ts.replace('.', '')}"


class SeedCase(FileCase):
    def seed(self, *pages, config=None, routine=SLUG):
        paths = [self.write(f"page-{index}.json", page) for index, page in enumerate(pages)]
        flags = [flag for path in paths for flag in ("--page", path)]
        return run_cli(
            "seed", *flags, "--routine", routine, "--config", self.write("config.json", config or make_config()),
            "--out", self.path("state.json"),
        )

    def seeded(self, run_state=None, config=None):
        code, _, err = self.seed(make_page(make_run_state() if run_state is None else run_state), config=config)
        self.assertEqual((code, err), (0, ""))
        return self.read("state.json")

    def with_warning(self, **fields):
        run_state = make_run_state()
        run_state["warnings"]["queue-depth"].update(fields)
        return run_state

    def without(self, section, key, field):
        run_state = make_run_state()
        del run_state[section][key][field]
        return run_state


class SeedStateTest(SeedCase):
    def test_exits_0_and_writes_a_valid_state(self):
        self.seeded()
        self.assertIsNone(tribe_state.check_state(self.read("state.json")))

    def test_writes_canonical_json(self):
        self.seeded()
        self.assert_canonical("state.json")

    def test_keeps_the_digest_of_the_run_state(self):
        self.assertEqual(self.seeded()["digest"], "example")

    def test_run_continues_from_the_seeded_run_time(self):
        run = self.seeded()["run"]
        self.assertEqual((run["at"], run["window"], run["daily_metrics_on"], run["layout_version"], run["models"]), (PREVIOUS, None, None, 1, {}))

    def test_previous_page_is_the_page_and_write_time_of_the_run_state(self):
        self.assertEqual(self.seeded()["run"]["previous_page"], {"id": PAGE_ID, "written_at": WRITTEN})

    def test_weekly_heading_week_is_the_iso_week_of_the_run_time(self):
        self.assertEqual(self.seeded()["run"]["weekly_heading_week"], "2026-W42")

    def test_weekly_heading_week_follows_the_config_time_zone(self):
        run_state = make_run_state()
        run_state["run"]["at"] = "2026-10-18T23:30:00Z"
        self.assertEqual(self.seeded(run_state)["run"]["weekly_heading_week"], "2026-W43")

    def test_the_seeded_digest_counts_as_posted(self):
        self.assertTrue(self.seeded()["run"]["posted"])

    def test_retired_keys_start_empty(self):
        self.assertEqual(self.seeded()["retired"], {})

    def test_blind_spots_start_empty_without_blind_spot_runs(self):
        self.assertEqual(self.seeded()["blind_spots"], [])

    def test_blind_spot_runs_carry_over(self):
        run_state = make_run_state()
        run_state["blind_spot_runs"] = [{"key": "channels", "gap": "no history", "runs": 2}]
        self.assertEqual(self.seeded(run_state)["blind_spots"], [{"key": "channels", "gap": "no history", "runs": 2}])

    def test_seeded_state_gives_a_window_from_the_run_time(self):
        self.seeded()
        run_cli("window", "--state", self.path("state.json"), "--now", NOW, "--tz", TZ, "--out", self.path("window.json"))
        self.assertEqual(self.read("window.json")["from_ts"], ts(PREVIOUS))


class SeedWarningTest(SeedCase):
    def test_maps_the_stated_fields_and_fills_the_rest(self):
        self.assertEqual(self.seeded()["warnings"]["queue-depth"], {
            "title": "Queue depth rises",
            "topic": "Capacity",
            "severity": "High",
            "when": "now",
            "runway": "",
            "status": "open",
            "confidence": "measured",
            "risk": "",
            "impact": "",
            "mitigation": [],
            "cites": [],
            "metric": None,
            "runs_under": 0,
            "since": PREVIOUS,
        })

    def test_carries_every_warning_by_key(self):
        self.assertEqual(sorted(self.seeded()["warnings"]), ["disk-usage", "queue-depth"])

    def test_reads_the_months_spelling_as_within_months(self):
        self.assertEqual(self.seeded()["warnings"]["disk-usage"]["when"], "within months")

    def test_keeps_the_status_and_confidence_of_the_run_state(self):
        warning = self.seeded()["warnings"]["disk-usage"]
        self.assertEqual((warning["status"], warning["confidence"]), ("in progress", "reported"))

    def test_keeps_a_metric_key(self):
        self.assertEqual(self.seeded(self.with_warning(metric="queue-depth"))["warnings"]["queue-depth"]["metric"], "queue-depth")

    def test_carries_the_optional_labels_and_cites_when_present(self):
        run_state = self.with_warning(
            runway="two weeks", risk="late jobs", impact="late reports", mitigation=["add a worker"],
            cites=[{"source": "channels", "link": "https://example.test/c/1"}],
        )
        warning = self.seeded(run_state)["warnings"]["queue-depth"]
        self.assertEqual(
            (warning["runway"], warning["risk"], warning["impact"], warning["mitigation"], warning["cites"]),
            ("two weeks", "late jobs", "late reports", ["add a worker"], [{"source": "channels", "link": "https://example.test/c/1"}]),
        )


class SeedStatusTest(SeedCase):
    def read_status(self, status):
        code, _, err = self.seed(make_page(self.with_warning(status=status)))
        self.assertEqual(code, 0)
        return self.read("state.json")["warnings"]["queue-depth"]["status"], err

    def test_reads_a_status_that_starts_with_a_br_54_word_as_that_word(self):
        self.assertEqual(self.read_status("open, drained")[0], "open")

    def test_reads_a_multi_word_status_up_to_its_clause(self):
        self.assertEqual(self.read_status("in progress: waiting on the vendor")[0], "in progress")

    def test_reads_the_leading_word_without_regard_to_case(self):
        self.assertEqual(self.read_status("DECIDED by the team")[0], "decided")

    def test_reads_a_status_that_only_contains_a_br_54_word_as_open(self):
        self.assertEqual(self.read_status("fixed, restore open")[0], "open")

    def test_reads_a_word_that_merely_starts_with_a_br_54_word_as_open(self):
        self.assertEqual(self.read_status("decidedly late")[0], "open")

    def test_reads_an_empty_status_as_open(self):
        self.assertEqual(self.read_status("")[0], "open")

    def test_prints_one_line_for_a_status_read_as_a_br_54_word(self):
        self.assertEqual(self.read_status("open, drained")[1], 'seed: warnings.queue-depth.status "open, drained" read as open\n')

    def test_prints_one_line_for_a_status_read_as_open(self):
        self.assertEqual(self.read_status("fixed, restore open")[1], 'seed: warnings.queue-depth.status "fixed, restore open" read as open\n')

    def test_prints_a_line_for_a_status_that_differs_only_by_case(self):
        self.assertEqual(self.read_status("Open")[1], 'seed: warnings.queue-depth.status "Open" read as open\n')

    def test_prints_nothing_for_a_status_that_is_already_a_br_54_value(self):
        self.assertEqual(self.read_status("mitigated"), ("mitigated", ""))

    def test_prints_the_original_status_cut_to_60_characters(self):
        line = self.read_status("fixed " + "x" * 100)[1]
        self.assertEqual(line, 'seed: warnings.queue-depth.status "fixed ' + "x" * 54 + '" read as open\n')

    def test_prints_the_original_status_without_control_characters_or_mentions(self):
        line = self.read_status("fixed\n@here <b>")[1]
        self.assertEqual(line, 'seed: warnings.queue-depth.status "fixed  here  b " read as open\n')

    def test_prints_one_line_per_remapped_warning(self):
        run_state = self.with_warning(status="open, drained")
        run_state["warnings"]["disk-usage"]["status"] = "fixed, restore open"
        _, _, err = self.seed(make_page(run_state))
        self.assertEqual(sorted(err.splitlines()), [
            'seed: warnings.disk-usage.status "fixed, restore open" read as open',
            'seed: warnings.queue-depth.status "open, drained" read as open',
        ])


class SeedCheckTest(SeedCase):
    def test_maps_text_and_topic_and_adds_group_and_since(self):
        self.assertEqual(
            self.seeded()["checks"]["ask-export"],
            {"text": "Ask for the export", "topic": "Capacity", "group": "Investigate", "since": PREVIOUS},
        )

    def test_drops_a_ticked_check(self):
        self.assertEqual(sorted(self.seeded()["checks"]), ["ask-export"])

    def test_keeps_the_group_of_a_check_that_has_one(self):
        run_state = make_run_state()
        run_state["checks"]["ask-export"]["group"] = "This week"
        self.assertEqual(self.seeded(run_state)["checks"]["ask-export"]["group"], "This week")


class SeedCursorTest(SeedCase):
    def cursors(self, run_state=None, config=None):
        return self.seeded(run_state, config)["cursors"]

    def test_maps_every_cursor(self):
        self.assertEqual(self.cursors(), {
            "channels": {"ts": {CHANNEL_A: SLACK_TS}},
            "issues": {"updated": UPDATED_MAX},
            "pages": {"pages": {dashed(NOTION_A): EDITED_A, NOTION_B: EDITED_B}},
            "observability": {"events_ts_ms": None, "monitors": {"1001": "OK, cannot fire", "1002": "Alert"}, "metrics": {}},
        })

    def test_gives_a_chat_source_the_stamps_of_its_own_channels(self):
        self.assertNotIn(CHANNEL_B, self.cursors()["channels"]["ts"])

    def test_gives_a_chat_source_without_a_stamped_channel_no_cursor(self):
        self.assertNotIn("other-channels", self.cursors())

    def test_gives_an_issue_source_of_another_filter_no_cursor(self):
        self.assertNotIn("other-issues", self.cursors())

    def test_gives_no_issue_source_a_cursor_when_the_run_state_has_no_filter_and_several_sources_exist(self):
        run_state = make_run_state()
        del run_state["cursors"]["jira"]["filter"]
        cursors = self.cursors(run_state)
        self.assertEqual(("issues" in cursors, "other-issues" in cursors), (False, False))

    def test_gives_the_only_issue_source_the_cursor_of_a_run_state_without_a_filter(self):
        run_state = make_run_state()
        del run_state["cursors"]["jira"]["filter"]
        config = make_config()
        del config["routines"][SLUG]["sources"]["other-issues"]
        self.assertEqual(self.cursors(run_state, config)["issues"], {"updated": UPDATED_MAX})

    def test_matches_a_page_id_with_dashes_to_the_run_state_id_without(self):
        self.assertEqual(self.cursors()["pages"]["pages"][dashed(NOTION_A)], EDITED_A)

    def test_leaves_a_page_the_source_does_not_list_out(self):
        self.assertEqual(sorted(self.cursors()["pages"]["pages"]), sorted([dashed(NOTION_A), NOTION_B]))

    def test_maps_a_single_page_source(self):
        config = make_config()
        config["routines"][SLUG]["sources"]["pages"] = {"provider": "document-store", "page_id": NOTION_B}
        self.assertEqual(self.cursors(config=config)["pages"], {"pages": {NOTION_B: EDITED_B}})

    def test_gives_a_source_whose_pages_are_all_unseen_no_cursor(self):
        run_state = make_run_state()
        run_state["cursors"]["notion"] = {}
        self.assertNotIn("pages", self.cursors(run_state))

    def test_starts_observability_empty_when_the_run_state_has_no_monitor_cursor(self):
        run_state = make_run_state()
        del run_state["cursors"]["datadog"]
        self.assertEqual(self.cursors(run_state)["observability"], {"events_ts_ms": None, "monitors": {}, "metrics": {}})

    def test_ignores_a_run_state_section_no_source_reads(self):
        self.assertNotIn("github", self.cursors())

    def test_accepts_a_run_state_without_any_source_cursor(self):
        run_state = make_run_state()
        run_state["cursors"] = {}
        self.assertEqual(list(self.cursors(run_state)), ["observability"])


class SeedThreadTest(SeedCase):
    def seed_threads(self, entries, config=None):
        run_state = make_run_state()
        run_state["cursors"]["slack"]["threads"] = entries
        config = config or make_config()
        config["providers"]["chat"]["links_base"] = LINKS_BASE
        code, _, err = self.seed(make_page(run_state), config=config)
        self.assertEqual(code, 0)
        return self.read("state.json")["threads"], err

    def test_maps_a_tracked_thread_to_the_chat_source_that_lists_its_channel(self):
        threads, _ = self.seed_threads([f"{CHANNEL_A}/{THREAD_TS}"])
        self.assertEqual(threads, {"channels": [{"channel": CHANNEL_A, "root_ts": THREAD_TS, "links": [thread_link(CHANNEL_A, THREAD_TS)]}]})

    def test_maps_a_tracked_thread_to_every_chat_source_that_lists_its_channel(self):
        config = make_config()
        config["routines"][SLUG]["sources"]["other-channels"]["channels"].append(CHANNEL_A)
        threads, _ = self.seed_threads([f"{CHANNEL_A}/{THREAD_TS}"], config)
        self.assertEqual(sorted(threads), ["channels", "other-channels"])

    def test_keeps_the_order_of_the_tracked_threads(self):
        entries = [f"{CHANNEL_B}/{THREAD_TS}", f"{CHANNEL_A}/{THREAD_TS}"]
        threads, _ = self.seed_threads(entries)
        self.assertEqual([thread["channel"] for thread in threads["channels"]], [CHANNEL_B, CHANNEL_A])

    def test_keeps_a_thread_listed_twice_once(self):
        threads, _ = self.seed_threads([f"{CHANNEL_A}/{THREAD_TS}"] * 2)
        self.assertEqual(len(threads["channels"]), 1)

    def test_builds_the_link_from_the_links_base_of_the_provider(self):
        threads, _ = self.seed_threads([f"{CHANNEL_A}/{THREAD_TS}"])
        self.assertEqual(threads["channels"][0]["links"], [thread_link(CHANNEL_A, THREAD_TS)])

    def test_seeds_no_threads_when_the_run_state_tracks_none(self):
        threads, err = self.seed_threads([])
        self.assertEqual((threads, err), ({}, ""))

    def test_seeds_no_threads_when_the_run_state_has_no_thread_list(self):
        run_state = make_run_state()
        del run_state["cursors"]["slack"]["threads"]
        self.assertEqual(self.seeded(run_state)["threads"], {})

    def test_skips_and_notes_a_thread_whose_channel_no_chat_source_lists(self):
        threads, err = self.seed_threads([f"{UNLISTED}/{THREAD_TS}"])
        self.assertEqual(
            (threads, err),
            ({}, f'seed: cursors.slack.threads[0] "{UNLISTED}/{THREAD_TS}" skipped: channel not listed by a chat source\n'),
        )

    def test_skips_and_notes_an_entry_without_a_channel_separator(self):
        threads, err = self.seed_threads([THREAD_TS])
        self.assertEqual((threads, err), ({}, f'seed: cursors.slack.threads[0] "{THREAD_TS}" skipped: not <channel>/<root ts>\n'))

    def test_skips_and_notes_an_entry_with_two_separators(self):
        threads, err = self.seed_threads([f"{CHANNEL_A}/{THREAD_TS}/x"])
        self.assertEqual((threads, "not <channel>/<root ts>" in err), ({}, True))

    def test_skips_and_notes_an_entry_that_is_not_text(self):
        threads, err = self.seed_threads([5])
        self.assertEqual((threads, err), ({}, 'seed: cursors.slack.threads[0] "5" skipped: not <channel>/<root ts>\n'))

    def test_skips_and_notes_an_entry_with_an_invalid_root_ts(self):
        threads, err = self.seed_threads([f"{CHANNEL_A}/yesterday"])
        self.assertEqual((threads, "skipped: invalid root ts" in err), ({}, True))

    def test_keeps_the_valid_entries_next_to_a_skipped_one(self):
        threads, err = self.seed_threads([f"{UNLISTED}/{THREAD_TS}", f"{CHANNEL_A}/{THREAD_TS}"])
        self.assertEqual((len(threads["channels"]), err.count("skipped")), (1, 1))

    def test_numbers_the_skipped_entry_by_its_place_in_the_list(self):
        _, err = self.seed_threads([f"{CHANNEL_A}/{THREAD_TS}", f"{UNLISTED}/{THREAD_TS}"])
        self.assertIn("cursors.slack.threads[1]", err)

    def test_cuts_a_noted_entry_to_60_characters_without_control_characters(self):
        _, err = self.seed_threads(["a\nb" + "x" * 100])
        self.assertEqual(err, 'seed: cursors.slack.threads[0] "a b' + "x" * 57 + '" skipped: not <channel>/<root ts>\n')

    def test_rejects_a_thread_list_that_is_not_a_list(self):
        run_state = make_run_state()
        run_state["cursors"]["slack"]["threads"] = {}
        code, _, err = self.seed(make_page(run_state))
        self.assertEqual((code, "cursors.slack.threads" in err), (3, True))

    def test_seeded_threads_pass_the_state_check(self):
        threads, _ = self.seed_threads([f"{CHANNEL_A}/{THREAD_TS}", f"{CHANNEL_C}/{THREAD_TS}"])
        self.assertIsNone(tribe_state.check_state(self.read("state.json")))


class SeedBlindSpotTest(SeedCase):
    def seed_runs(self, runs, where="top"):
        run_state = make_run_state()
        if where == "top":
            run_state["blind_spot_runs"] = runs
        else:
            run_state["run"]["blind_spot_runs"] = runs
        code, _, err = self.seed(make_page(run_state))
        return code, err, self.read("state.json")["blind_spots"] if code == 0 else None

    def test_reads_a_map_of_runs_at_the_top_level(self):
        code, err, spots = self.seed_runs({"gap-a": 2, "gap-b": 1})
        self.assertEqual((code, err, spots), (0, "", [{"key": "gap-a", "gap": "gap-a", "runs": 2}, {"key": "gap-b", "gap": "gap-b", "runs": 1}]))

    def test_reads_a_map_of_runs_under_the_run(self):
        code, err, spots = self.seed_runs({"gap-a": 3}, where="run")
        self.assertEqual((code, err, spots), (0, "", [{"key": "gap-a", "gap": "gap-a", "runs": 3}]))

    def test_reads_a_list_of_runs_under_the_run(self):
        code, err, spots = self.seed_runs([{"key": "channels", "gap": "no history", "runs": 2}], where="run")
        self.assertEqual((code, err, spots), (0, "", [{"key": "channels", "gap": "no history", "runs": 2}]))

    def test_prefers_the_top_level_runs_to_those_under_the_run(self):
        run_state = make_run_state()
        run_state["blind_spot_runs"] = {"gap-a": 1}
        run_state["run"]["blind_spot_runs"] = {"gap-b": 4}
        self.assertEqual(self.seeded(run_state)["blind_spots"], [{"key": "gap-a", "gap": "gap-a", "runs": 1}])

    def test_prefers_an_empty_top_level_list_to_the_runs_under_the_run(self):
        run_state = make_run_state()
        run_state["blind_spot_runs"] = []
        run_state["run"]["blind_spot_runs"] = {"gap-b": 4}
        self.assertEqual(self.seeded(run_state)["blind_spots"], [])

    def test_seeds_an_empty_map_as_no_blind_spots(self):
        self.assertEqual(self.seed_runs({}), (0, "", []))

    def test_cuts_a_map_key_to_60_characters_without_control_characters_or_mentions(self):
        _, _, spots = self.seed_runs({"a\nb@c" + "x" * 100: 1})
        key = "a b c" + "x" * 55
        self.assertEqual(spots, [{"key": key, "gap": key, "runs": 1}])

    def test_skips_and_notes_an_entry_whose_runs_is_not_an_integer_of_at_least_1(self):
        for runs in (0, -1, 1.5, "2", True, None):
            with self.subTest(runs=runs):
                code, err, spots = self.seed_runs({"gap-a": runs})
                self.assertEqual((code, spots, err), (0, [], "seed: blind_spot_runs.gap-a skipped: runs is not an integer of at least 1\n"))

    def test_skips_and_notes_an_entry_with_an_empty_key(self):
        code, err, spots = self.seed_runs({"": 1, "gap-a": 1})
        self.assertEqual((code, spots, err), (0, [{"key": "gap-a", "gap": "gap-a", "runs": 1}], "seed: blind_spot_runs. skipped: key is empty\n"))

    def test_keeps_the_valid_entries_next_to_a_skipped_one(self):
        _, err, spots = self.seed_runs({"gap-a": 0, "gap-b": 2})
        self.assertEqual((spots, err.count("skipped")), ([{"key": "gap-b", "gap": "gap-b", "runs": 2}], 1))

    def test_cuts_a_noted_key_to_60_characters_without_control_characters(self):
        _, err, _ = self.seed_runs({"a\nb" + "x" * 100: 0})
        self.assertEqual(err, "seed: blind_spot_runs.a b" + "x" * 57 + " skipped: runs is not an integer of at least 1\n")

    def test_rejects_runs_that_are_neither_a_list_nor_a_map(self):
        for where, path in (("top", "blind_spot_runs"), ("run", "run.blind_spot_runs")):
            with self.subTest(where=where):
                code, err, _ = self.seed_runs("none", where=where)
                self.assertEqual((code, f"expected a list or an object at {path}" in err), (3, True))

    def test_rejects_a_list_entry_without_a_count_under_the_run(self):
        code, err, _ = self.seed_runs([{"key": "channels", "gap": "no history"}], where="run")
        self.assertEqual((code, "run.blind_spot_runs[0].runs" in err), (3, True))

    def test_seeded_blind_spots_pass_the_state_check(self):
        self.seed_runs({"gap-a": 2, "a\nb@c" + "x" * 100: 1, "gap-c": 0})
        self.assertIsNone(tribe_state.check_state(self.read("state.json")))


class SeedSkippedPageTest(SeedCase):
    def test_skips_a_newer_page_without_a_run_state_and_names_it(self):
        code, _, err = self.seed(make_page(None), make_page(make_run_state()))
        self.assertEqual((code, "page-0.json" in err, "no Run state section" in err), (0, True, True))

    def test_takes_the_state_of_the_older_page_after_a_skip(self):
        self.seed(make_page(None), make_page(make_run_state()))
        self.assertEqual(self.read("state.json")["run"]["previous_page"]["id"], PAGE_ID)

    def test_takes_the_first_valid_page(self):
        older = make_run_state()
        older["run"]["page"] = "cd" * 16
        self.seed(make_page(make_run_state()), make_page(older))
        self.assertEqual(self.read("state.json")["run"]["previous_page"]["id"], PAGE_ID)

    def test_skips_a_run_state_with_another_schema(self):
        run_state = make_run_state()
        run_state["schema"] = 2
        code, _, err = self.seed(make_page(run_state), make_page(make_run_state()))
        self.assertEqual((code, "has no schema 1" in err), (0, True))

    def test_skips_a_run_state_that_is_not_json(self):
        page = make_page(None)
        page["text"] = page["text"].replace("</content>", '## Run state {toggle="true"}\n\t```json\n{oops\n\t```\n</content>')
        code, _, err = self.seed(page, make_page(make_run_state()))
        self.assertEqual((code, "not valid JSON" in err), (0, True))

    def test_skips_a_run_state_that_is_not_an_object(self):
        code, _, err = self.seed(make_page([1]), make_page(make_run_state()))
        self.assertEqual((code, "has no schema 1" in err), (0, True))

    def test_skips_a_run_state_section_without_a_json_block(self):
        page = make_page(None)
        page["text"] = page["text"].replace("</content>", '## Run state {toggle="true"}\n\t- Nothing here.\n</content>')
        code, _, err = self.seed(page, make_page(make_run_state()))
        self.assertEqual((code, "holds no json block" in err), (0, True))

    def test_ignores_a_json_block_outside_the_run_state_section(self):
        page = make_page(None)
        page["text"] = page["text"].replace("## Warnings", '## Details\n```json\n{"schema": 1}\n```\n## Warnings')
        code, _, err = self.seed(page, make_page(make_run_state()))
        self.assertEqual((code, "no Run state section" in err), (0, True))

    def test_stops_a_run_state_section_at_the_next_heading(self):
        page = make_page(make_run_state())
        page["text"] = page["text"].replace('## Run state {toggle="true"}', '## Run state {toggle="true"}\n## Other\n', 1)
        code, _, err = self.seed(page, make_page(make_run_state()))
        self.assertEqual((code, "page-0.json" in err), (0, True))

    def test_skips_a_file_that_is_not_json(self):
        path = self.path("junk.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not json")
        code, _, err = run_cli(
            "seed", "--page", path, "--page", self.write("good.json", make_page(make_run_state())), "--routine", SLUG,
            "--config", self.write("config.json", make_config()), "--out", self.path("state.json"),
        )
        self.assertEqual((code, "junk.json" in err, "not a saved fetch result" in err), (0, True, True))

    def test_skips_a_fetch_result_without_text(self):
        code, _, err = self.seed({"title": "Digest"}, make_page(make_run_state()))
        self.assertEqual((code, "no text" in err), (0, True))

    def test_skips_a_missing_file(self):
        code, _, err = run_cli(
            "seed", "--page", self.path("absent.json"), "--page", self.write("good.json", make_page(make_run_state())),
            "--routine", SLUG, "--config", self.write("config.json", make_config()), "--out", self.path("state.json"),
        )
        self.assertEqual((code, "absent.json" in err, "cannot read the file" in err), (0, True, True))

    def test_reads_a_page_saved_in_the_harness_wrapper(self):
        wrapped = [{"type": "text", "text": json.dumps(make_page(make_run_state()))}]
        self.assertEqual(self.seed(wrapped)[0], 0)

    def test_exits_2_naming_every_page_read_when_none_qualifies(self):
        code, _, err = self.seed(make_page(None), {"title": "Digest"})
        self.assertEqual((code, "page-0.json" in err.splitlines()[-1], "page-1.json" in err.splitlines()[-1]), (2, True, True))

    def test_writes_nothing_when_no_page_qualifies(self):
        self.seed(make_page(None))
        self.assertNotIn("state.json", os.listdir(self.dir))


class SeedRejectionTest(SeedCase):
    def rejected(self, run_state, path):
        code, _, err = self.seed(make_page(run_state))
        self.assertEqual((code, path in err, "state.json" in os.listdir(self.dir)), (3, True, False))

    def test_rejects_a_severity_outside_br_54(self):
        self.rejected(self.with_warning(severity="Critical"), "warnings.queue-depth.severity")

    def test_rejects_a_when_outside_br_54(self):
        self.rejected(self.with_warning(when="someday"), "warnings.queue-depth.when")

    def test_rejects_a_confidence_outside_br_54(self):
        self.rejected(self.with_warning(confidence="high"), "warnings.queue-depth.confidence")

    def test_rejects_a_status_that_is_not_text(self):
        self.rejected(self.with_warning(status=5), "warnings.queue-depth.status")

    def test_rejects_a_warning_without_a_title(self):
        self.rejected(self.without("warnings", "queue-depth", "title"), "missing key warnings.queue-depth.title")

    def test_rejects_a_warning_without_a_topic(self):
        self.rejected(self.without("warnings", "queue-depth", "topic"), "missing key warnings.queue-depth.topic")

    def test_rejects_a_warning_without_a_severity(self):
        self.rejected(self.without("warnings", "queue-depth", "severity"), "missing key warnings.queue-depth.severity")

    def test_rejects_a_warning_without_a_metric(self):
        self.rejected(self.without("warnings", "queue-depth", "metric"), "missing key warnings.queue-depth.metric")

    def test_rejects_a_warning_whose_metric_is_a_number(self):
        self.rejected(self.with_warning(metric=5), "warnings.queue-depth.metric")

    def test_rejects_a_warning_with_a_malformed_optional_field(self):
        self.rejected(self.with_warning(risk=LONG), "warnings.queue-depth.risk")

    def test_rejects_a_check_without_a_text(self):
        self.rejected(self.without("checks", "ask-export", "text"), "missing key checks.ask-export.text")

    def test_rejects_a_check_without_a_done_flag(self):
        self.rejected(self.without("checks", "ask-export", "done"), "missing key checks.ask-export.done")

    def test_rejects_a_check_group_outside_the_fixed_set(self):
        run_state = make_run_state()
        run_state["checks"]["ask-export"]["group"] = "Later"
        self.rejected(run_state, "checks.ask-export.group")

    def test_rejects_a_warning_key_that_is_not_kebab_case(self):
        run_state = make_run_state()
        run_state["warnings"]["Queue_Depth"] = run_state["warnings"].pop("queue-depth")
        self.rejected(run_state, "warnings.Queue_Depth")

    def test_rejects_a_run_state_without_a_page(self):
        run_state = make_run_state()
        del run_state["run"]["page"]
        self.rejected(run_state, "missing key run.page")

    def test_rejects_a_run_state_without_cursors(self):
        run_state = make_run_state()
        del run_state["cursors"]
        self.rejected(run_state, "missing key cursors")

    def test_rejects_a_chat_stamp_that_is_not_text(self):
        run_state = make_run_state()
        run_state["cursors"]["slack"][CHANNEL_A]["ts"] = 5
        self.rejected(run_state, f"cursors.slack.{CHANNEL_A}.ts")

    def test_rejects_a_page_edit_time_that_is_not_utc(self):
        run_state = make_run_state()
        run_state["cursors"]["notion"][NOTION_B] = "last week"
        self.rejected(run_state, f"cursors.notion.{NOTION_B}")

    def test_rejects_an_issue_cursor_that_is_not_utc(self):
        run_state = make_run_state()
        run_state["cursors"]["jira"]["updated_max"] = "10 minutes ago"
        self.rejected(run_state, "cursors.jira.updated_max")

    def test_rejects_a_monitor_state_that_is_not_text(self):
        run_state = make_run_state()
        run_state["cursors"]["datadog"]["monitors"]["1001"] = 1
        self.rejected(run_state, "cursors.datadog.monitors.1001")

    def test_rejects_a_blind_spot_run_without_a_count(self):
        run_state = make_run_state()
        run_state["blind_spot_runs"] = [{"key": "channels", "gap": "no history"}]
        self.rejected(run_state, "blind_spot_runs[0].runs")

    def test_does_not_fall_back_to_an_older_page_after_a_rejection(self):
        code, _, _ = self.seed(make_page(self.with_warning(severity="Critical")), make_page(make_run_state()))
        self.assertEqual(code, 3)

    def test_names_the_page_of_the_rejection(self):
        _, _, err = self.seed(make_page(self.with_warning(severity="Critical")))
        self.assertIn("page-0.json", err)


class SeedConfigTest(SeedCase):
    def test_unknown_routine_exits_2(self):
        self.assertEqual(self.seed(make_page(make_run_state()), routine="absent")[0], 2)

    def test_unknown_time_zone_exits_2(self):
        config = make_config()
        config["timezone"] = "Nowhere/Land"
        self.assertEqual(self.seed(make_page(make_run_state()), config=config)[0], 2)

    def test_a_provider_that_is_not_configured_exits_2_naming_the_source(self):
        config = make_config()
        config["routines"][SLUG]["sources"]["channels"]["provider"] = "absent"
        code, _, err = self.seed(make_page(make_run_state()), config=config)
        self.assertEqual((code, "routines.tribe-digest.sources.channels.provider" in err), (2, True))

    def test_a_provider_name_that_is_not_text_exits_2_naming_the_source(self):
        config = make_config()
        config["routines"][SLUG]["sources"]["channels"]["provider"] = ["chat"]
        code, _, err = self.seed(make_page(make_run_state()), config=config)
        self.assertEqual((code, "routines.tribe-digest.sources.channels.provider" in err), (2, True))

    def test_a_missing_config_exits_2(self):
        code, _, _ = run_cli("seed", "--page", self.write("p.json", make_page(make_run_state())), "--routine", SLUG,
                             "--config", self.path("absent.json"), "--out", self.path("state.json"))
        self.assertEqual(code, 2)

    def test_a_seed_without_pages_exits_2(self):
        code, _, _ = run_cli("seed", "--routine", SLUG, "--config", self.write("config.json", make_config()), "--out", self.path("state.json"))
        self.assertEqual(code, 2)


class SeedPreviousPageTest(SeedCase):
    def test_the_previous_page_id_is_the_undashed_lowercase_page_key(self):
        run_state = make_run_state()
        run_state["run"]["page"] = dashed(PAGE_ID).upper()
        self.assertEqual(self.seeded(run_state)["run"]["previous_page"]["id"], PAGE_ID)


class SeedObservabilityTest(SeedCase):
    def test_monitors_of_the_run_state_are_not_carried_without_an_observability_source(self):
        config = make_config()
        del config["routines"][SLUG]["sources"]["monitors"]
        self.assertEqual(self.seeded(config=config)["cursors"]["observability"], {"events_ts_ms": None, "monitors": {}, "metrics": {}})


if __name__ == "__main__":
    unittest.main()
