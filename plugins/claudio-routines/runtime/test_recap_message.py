import argparse
import contextlib
import io
import os
import sys
import unittest
from zoneinfo import ZoneInfo

import recap
import recap_message
import state
from support import ts
from test_recap_features import SLUG, make_config
from test_recap_state import FileCase

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "fixtures", "recap", "message_golden.md")
PARIS = ZoneInfo("Europe/Paris")
HOST = "example.test"
RUN_AT = "2026-10-16T07:45:00Z"
FROM = "2026-10-15T07:45:00Z"
PEER = "U" + "2" * 6
OTHER = "U" + "3" * 6
THIRD = "U" + "4" * 6
DM = "D" + "1" * 6
GROUP_DM = "G" + "1" * 6
OPS = "C" + "1" * 6
CORE = "C" + "2" * 6
RELEASES = "C" + "3" * 6
ROOT = "1791990000.000100"
REPLY = "1791990730.002679"


def at(text, fraction=100):
    return f"{ts(text)}.{fraction:06d}"


def make_line(**fields):
    line = {
        "key": f"dm-{DM}",
        "kind": "dm",
        "status": "waiting",
        "channel": DM,
        "channel_name": None,
        "ts": at("2026-10-15T07:45:00Z"),
        "root_ts": None,
        "person": {"id": PEER, "name": "Peer Name"},
        "title": "Review the export plan",
        "summary": "asks for a review of the export plan",
        "blocking": False,
        "due": None,
        "late": None,
        "first_seen": "2026-10-14T07:45:00Z",
        "unanswered_from": None,
        "is_new": False,
        "resolved": False,
    }
    return {**line, **fields}


def asked(stamp, **fields):
    return make_line(ts=stamp, unanswered_from=stamp, **fields)


def make_summary(**fields):
    summary = {
        "digest": "Chat recap",
        "run_at": RUN_AT,
        "window": {"from_ts": ts(FROM), "to_ts": ts(RUN_AT)},
        "report_only": False,
        "limited": None,
        "waiting": [],
        "good_to_know": [],
        "waiting_on_others": [],
        "handled": [],
        "resolved": [],
        "reading": [],
        "counts": {"waiting": 0, "late": 0, "new": 0, "resolved": 0, "waiting_on_others": 0},
        "blind_spots": [],
        "post": False,
    }
    return {**summary, **fields}


def person(who, name):
    return {"id": who, "name": name}


def golden_summary():
    return make_summary(
        waiting=[
            asked(at("2026-10-12T08:00:00Z", 1), kind="thread", channel=OPS, channel_name="#ops", root_ts=at("2026-10-12T07:00:00Z", 1), person=person(THIRD, "Third Name"), summary="wants a decision on the rollout order"),
            asked(at("2026-10-14T09:00:00Z", 2), kind="group", channel=CORE, channel_name="#core", person=person(OTHER, "Other Name"), summary="asks for the quarterly numbers", is_new=True),
            asked(at("2026-10-09T12:10:00Z", 3), blocking=True, late=4, person=person(PEER, "Peer Name"), summary="asks for sign-off on the export plan"),
            asked(at("2026-10-13T07:30:00Z", 4), kind="group_dm", channel=GROUP_DM, person=person(OTHER, "Other Name"), summary="needs the contract numbers before noon"),
            make_line(ts=at("2026-10-14T13:00:00Z", 5), status="promise", person=None, due="2026-10-19T08:00:00Z", summary="the revised planning to the team"),
            asked(at("2026-10-15T14:20:00Z", 6), kind="mention", channel=OPS, channel_name="#ops", person=person(PEER, "Peer Name"), summary="mentions you on the incident review", is_new=True),
            make_line(ts=at("2026-10-13T12:00:00Z", 7), kind="thread", channel=OPS, channel_name="#ops", root_ts=at("2026-10-13T11:00:00Z", 7), status="promise", person=None, late=2, summary="the retry policy check"),
        ],
        good_to_know=[
            make_line(ts=at("2026-10-15T10:00:00Z", 8), kind="thread", status="announcement", channel=RELEASES, channel_name="#releases", root_ts=at("2026-10-15T10:00:00Z", 8), person=None, summary="Release 4 ships on Tuesday"),
            asked(at("2026-10-15T11:00:00Z", 9), kind="group", status="team_ask", channel=CORE, channel_name="#core", person=person(OTHER, "Other Name"), summary="Who owns the on-call handover", is_new=True),
        ],
        waiting_on_others=[
            make_line(ts=at("2026-10-14T15:00:00Z", 10), status="waiting_on_others", person=person(PEER, "Peer Name"), summary="the updated budget sheet"),
            make_line(ts=at("2026-10-08T10:00:00Z", 11), kind="thread", status="waiting_on_others", channel=OPS, channel_name="#ops", root_ts=at("2026-10-08T09:00:00Z", 11), person=None, summary="a reply on the vendor question"),
        ],
        handled=[
            make_line(ts=at("2026-10-15T08:00:00Z", 12), status="handled", title="Vendor invoice answered"),
            make_line(ts=at("2026-10-15T08:10:00Z", 13), status="handled", title="Badge request answered"),
            make_line(ts=at("2026-10-15T08:20:00Z", 14), status="handled", title="Offsite poll answered"),
            make_line(ts=at("2026-10-15T08:30:00Z", 15), status="handled", title="Travel form answered"),
            make_line(ts=at("2026-10-15T08:40:00Z", 16), status="handled", title="Survey answered"),
            make_line(ts=at("2026-10-15T08:50:00Z", 17), status="handled", title="Export plan reviewed", resolved=True),
            make_line(ts=at("2026-10-15T09:00:00Z", 18), kind="thread", channel=OPS, channel_name="#ops", root_ts=at("2026-10-15T08:00:00Z", 18), status="handled", title="Rollout thread settled", resolved=True),
        ],
        reading=[
            {"text": "Sign-off on the export plan is the one blocker, four days old.", "cites": ["dm-x"]},
            {"text": "Two promises are open, one of them late.", "cites": ["dm-x"]},
        ],
        counts={"waiting": 7, "late": 2, "new": 3, "resolved": 2, "waiting_on_others": 2},
        blind_spots=[
            {"key": "search-mentions", "gap": "search mentions cut: 10 page(s) read", "runs": 1},
            {"key": "thread-read", "gap": "one thread could not be read", "runs": 2},
        ],
        post=True,
    )


def sections_of(text):
    return {block.split("\n")[0]: block.split("\n")[1:] for block in text.rstrip("\n").split("\n\n")}


class RenderCase(unittest.TestCase):
    def render(self, summary, workspace=HOST, lookback=3, zone=PARIS):
        return recap_message.render(summary, workspace, zone, lookback)

    def lines(self, heading, summary):
        return sections_of(self.render(summary))[f"**{heading}**"]

    def waiting(self, *lines, **fields):
        return self.lines("Waiting on you", make_summary(waiting=list(lines), **fields))

    def one(self, line, workspace=HOST, section="waiting", **fields):
        return self.render(make_summary(**{section: [line]}, **fields), workspace)


class TitleTest(RenderCase):
    def head(self, **fields):
        return self.render(make_summary(**fields)).split("\n")[:2]

    def test_names_the_digest_the_run_time_in_the_zone_and_the_window_start(self):
        self.assertEqual(self.head(), ["**Chat recap, 16 Oct 09:45 Paris**", "(since Thu 09:45)"])

    def test_a_baseline_run_names_the_lookback(self):
        self.assertEqual(self.head(limited="baseline")[1], "(baseline, last 3 working days)")

    def test_a_run_after_a_gap_names_the_window_start_and_the_limit(self):
        self.assertEqual(self.head(limited="gap")[1], "(since Thu 09:45, limited to the last 3 working days)")

    def test_a_lookback_of_one_is_singular(self):
        text = self.render(make_summary(limited="baseline"), lookback=1)
        self.assertEqual(text.split("\n")[1], "(baseline, last 1 working day)")

    def test_the_city_is_the_last_segment_of_the_zone_without_underscores(self):
        text = self.render(make_summary(), zone=ZoneInfo("America/Los_Angeles"))
        self.assertEqual(text.split("\n")[:2], ["**Chat recap, 16 Oct 00:45 Los Angeles**", "(since Thu 00:45)"])


class SummaryTest(RenderCase):
    def test_counts_the_waiting_late_new_resolved_and_awaited_units(self):
        counts = {"waiting": 3, "late": 1, "new": 2, "resolved": 4, "waiting_on_others": 5}
        self.assertEqual(self.lines("Summary", make_summary(counts=counts)), ["- 3 waiting on you (1 late), 2 new, 4 resolved, 5 you're waiting on"])

    def test_adds_the_blind_spot_gaps_joined_by_semicolons(self):
        spots = [{"key": "one", "gap": "first gap", "runs": 1}, {"key": "two", "gap": "second gap", "runs": 3}]
        self.assertEqual(self.lines("Summary", make_summary(blind_spots=spots))[1:], ["- Limits: first gap; second gap"])

    def test_has_no_limits_line_without_a_blind_spot(self):
        self.assertEqual(len(self.lines("Summary", make_summary())), 1)

    def test_an_empty_recap_is_the_title_and_the_summary_only(self):
        text = self.render(make_summary())
        self.assertEqual(list(sections_of(text)), ["**Chat recap, 16 Oct 09:45 Paris**", "**Summary**"])


class SectionsTest(RenderCase):
    def test_skips_every_empty_section_but_the_summary(self):
        summary = make_summary(reading=[{"text": "One thing moved", "cites": ["x"]}])
        self.assertEqual(list(sections_of(self.render(summary)))[1:], ["**Summary**", "**Reading**"])

    def test_orders_the_sections(self):
        headings = list(sections_of(self.render(golden_summary())))
        self.assertEqual(
            headings[1:], ["**Summary**", "**Waiting on you**", "**Good to know**", "**You're waiting on**", "**Already handled**", "**Reading**"]
        )

    def test_separates_the_sections_by_one_blank_line_and_ends_with_a_newline(self):
        text = self.render(golden_summary())
        self.assertNotIn("\n\n\n", text)
        self.assertTrue(text.endswith("\n") and not text.endswith("\n\n"))

    def test_the_reading_is_one_bullet_per_entry(self):
        reading = [{"text": "First point", "cites": ["x"]}, {"text": "Second point", "cites": ["x"]}]
        self.assertEqual(self.lines("Reading", make_summary(reading=reading)), ["- First point", "- Second point"])


class WaitingOrderTest(RenderCase):
    def names(self, *lines):
        return [text.split("**")[1] if "**" in text else text for text in self.waiting(*lines)]

    def line(self, name, day, **fields):
        return asked(at(f"2026-10-{day:02d}T08:00:00Z"), person=person(PEER, name), **fields)

    def test_a_blocking_unit_comes_first_whatever_its_kind_and_age(self):
        lines = [self.line("Plain", 10), self.line("Blocking", 15, kind="thread", blocking=True)]
        self.assertEqual(self.names(*lines), ["Blocking", "Plain"])

    def test_orders_the_kinds_direct_conversations_mention_group_thread(self):
        lines = [self.line(kind, 12, kind=kind) for kind in ("thread", "group", "mention", "group_dm", "dm")]
        self.assertEqual(sorted(self.names(*lines)[:2]), ["dm", "group_dm"])
        self.assertEqual(self.names(*lines)[2:], ["mention", "group", "thread"])

    def test_a_group_conversation_and_a_direct_one_share_a_rank_and_sort_by_age(self):
        lines = [self.line("Direct", 14, kind="dm"), self.line("Group", 13, kind="group_dm")]
        self.assertEqual(self.names(*lines), ["Group", "Direct"])

    def test_the_oldest_unit_comes_first_within_a_kind(self):
        lines = [self.line("Newer", 14), self.line("Older", 12), self.line("Middle", 13)]
        self.assertEqual(self.names(*lines), ["Older", "Middle", "Newer"])

    def test_the_age_is_the_unanswered_ts_before_the_message_ts(self):
        newer = asked(at("2026-10-13T08:00:00Z"), person=person(PEER, "Second"))
        older = asked(at("2026-10-12T08:00:00Z"), person=person(PEER, "First"))
        older["ts"] = at("2026-10-15T08:00:00Z")
        self.assertEqual(self.names(newer, older), ["First", "Second"])

    def test_a_promise_without_an_unanswered_ts_is_aged_by_its_message_ts(self):
        promise = make_line(ts=at("2026-10-12T08:00:00Z"), status="promise")
        self.assertEqual(self.names(self.line("Later", 13), promise), ["You", "Later"])


class WaitingLineTest(RenderCase):
    def test_a_waiting_unit_reads_name_summary_since_and_link(self):
        line = asked(at("2026-10-14T09:00:00Z"))
        self.assertEqual(
            self.waiting(line), [f"- **Peer Name** asks for a review of the export plan · since Wed 11:00 · [DM](https://example.test/archives/{DM}/p{line['ts'].replace('.', '')})"]
        )

    def test_a_waiting_unit_without_a_person_starts_with_its_summary(self):
        text = self.waiting(asked(at("2026-10-14T09:00:00Z"), person=None))[0]
        self.assertTrue(text.startswith("- asks for a review of the export plan · since Wed 11:00 · [DM]("))

    def test_a_late_waiting_unit_has_the_clock_before_the_name(self):
        text = self.waiting(asked(at("2026-10-14T09:00:00Z"), late=4))[0]
        self.assertTrue(text.startswith("- ⏰ **Peer Name** asks for"))

    def test_a_late_waiting_unit_without_a_person_has_the_clock_before_the_summary(self):
        text = self.waiting(asked(at("2026-10-14T09:00:00Z"), late=4, person=None))[0]
        self.assertTrue(text.startswith("- ⏰ asks for"))

    def test_a_unit_late_by_zero_days_is_still_late(self):
        text = self.waiting(make_line(status="promise", late=0, due="2026-10-16T05:00:00Z"))[0]
        self.assertTrue(text.startswith("- ⏰ **You** promised"))

    def test_a_promise_reads_you_promised_with_its_due_time(self):
        line = make_line(ts=at("2026-10-14T09:00:00Z"), status="promise", person=None, summary="the revised planning", due="2026-10-16T14:30:00Z")
        self.assertTrue(self.waiting(line)[0].startswith("- **You** promised the revised planning, by Fri 16:30 · since Wed 11:00 · [DM]("))

    def test_a_promise_without_a_due_time_says_no_date_given(self):
        line = make_line(ts=at("2026-10-14T09:00:00Z"), status="promise", person=None, summary="the revised planning")
        self.assertTrue(self.waiting(line)[0].startswith("- **You** promised the revised planning, no date given · since Wed 11:00 · "))

    def test_a_late_promise_has_the_clock_before_you(self):
        line = make_line(status="promise", late=2, due="2026-10-14T08:00:00Z")
        self.assertTrue(self.waiting(line)[0].startswith("- ⏰ **You** promised"))

    def test_a_summary_ending_in_a_period_drops_it_before_the_text_that_follows(self):
        promise = make_line(ts=at("2026-10-14T09:00:00Z"), status="promise", person=None, summary="the revised planning.")
        waiting = asked(at("2026-10-14T09:00:00Z"), summary="asks for a review.")
        owed = make_line(ts=at("2026-10-14T15:00:00Z"), status="waiting_on_others", summary="the updated budget sheet.")
        got = (
            self.waiting(promise)[0],
            self.waiting(waiting)[0],
            self.lines("You're waiting on", make_summary(waiting_on_others=[owed]))[0],
        )
        self.assertEqual(
            [text.split(" · ")[0] for text in got],
            ["- **You** promised the revised planning, no date given", "- **Peer Name** asks for a review", "- **Peer Name** owes the updated budget sheet since Wed 17:00"],
        )

    def test_a_promise_does_not_name_the_person(self):
        self.assertNotIn("Peer Name", self.waiting(make_line(status="promise"))[0])


class OtherSectionsTest(RenderCase):
    def test_a_team_ask_reads_team_ask_no_answer(self):
        line = asked(at("2026-10-14T09:00:00Z"), kind="group", status="team_ask", channel=CORE, channel_name="#core", summary="Who owns the handover")
        got = self.lines("Good to know", make_summary(good_to_know=[line]))
        self.assertEqual(got, [f"- Team ask, no answer: Who owns the handover · [group in #core](https://example.test/archives/{CORE}/p{line['ts'].replace('.', '')})"])

    def test_an_announcement_is_its_summary_and_link(self):
        line = make_line(status="announcement", kind="thread", channel=RELEASES, channel_name="#releases", summary="Release 4 ships on Tuesday")
        got = self.lines("Good to know", make_summary(good_to_know=[line]))
        self.assertTrue(got[0].startswith("- Release 4 ships on Tuesday · [thread in #releases]("))

    def test_team_asks_come_before_announcements(self):
        announcement = make_line(status="announcement", summary="An announcement")
        ask = make_line(status="team_ask", summary="An ask")
        got = self.lines("Good to know", make_summary(good_to_know=[announcement, ask]))
        self.assertEqual([text.split(" · ")[0] for text in got], ["- Team ask, no answer: An ask", "- An announcement"])

    def test_a_unit_you_wait_on_reads_the_person_owes_the_summary_since(self):
        line = make_line(ts=at("2026-10-14T15:00:00Z"), status="waiting_on_others", summary="the updated budget sheet")
        got = self.lines("You're waiting on", make_summary(waiting_on_others=[line]))
        self.assertTrue(got[0].startswith("- **Peer Name** owes the updated budget sheet since Wed 17:00 · [DM]("))

    def test_a_unit_you_wait_on_without_a_person_starts_with_the_summary(self):
        line = make_line(ts=at("2026-10-14T15:00:00Z"), status="waiting_on_others", person=None, summary="a reply on the vendor question")
        got = self.lines("You're waiting on", make_summary(waiting_on_others=[line]))
        self.assertTrue(got[0].startswith("- a reply on the vendor question since Wed 17:00 · [DM]("))


class HandledTest(RenderCase):
    def handled(self, count, resolved=()):
        return [make_line(status="handled", title=f"Title {number}", resolved=number in resolved) for number in range(1, count + 1)]

    def titles(self, lines):
        return [text.split(" · ")[0] for text in self.lines("Already handled", make_summary(handled=lines))]

    def test_shows_every_line_up_to_five(self):
        self.assertEqual(self.titles(self.handled(5)), [f"- Title {number}" for number in range(1, 6)])

    def test_cuts_at_five_and_counts_the_rest(self):
        self.assertEqual(self.titles(self.handled(8)), [f"- Title {number}" for number in range(1, 6)] + ["- +3"])

    def test_resolved_lines_come_first(self):
        self.assertEqual(self.titles(self.handled(7, resolved=(6, 7)))[:3], ["- Title 6", "- Title 7", "- Title 1"])

    def test_a_resolved_line_survives_the_cut(self):
        shown = self.titles(self.handled(7, resolved=(7,)))
        self.assertIn("- Title 7", shown[:5])
        self.assertEqual(shown[5], "- +2")

    def test_a_handled_line_is_its_title_and_link(self):
        line = make_line(status="handled", title="Vendor invoice answered")
        got = self.lines("Already handled", make_summary(handled=[line]))
        self.assertTrue(got[0].startswith("- Vendor invoice answered · [DM](https://example.test/archives/"))


class LinkTest(RenderCase):
    def link_of(self, line):
        return self.waiting(line)[0].split(" · ")[-1]

    def label(self, **fields):
        text = self.link_of(asked(REPLY, **fields))
        return text[1 : text.index("]")]

    def test_a_direct_conversation_is_labelled_dm(self):
        self.assertEqual(self.label(kind="dm", channel_name="#ignored"), "DM")

    def test_a_group_conversation_is_labelled_group_dm(self):
        self.assertEqual(self.label(kind="group_dm"), "group DM")

    def test_a_thread_names_its_channel(self):
        self.assertEqual(self.label(kind="thread", channel_name="#ops"), "thread in #ops")

    def test_a_mention_names_its_channel(self):
        self.assertEqual(self.label(kind="mention", channel_name="#ops"), "mention in #ops")

    def test_a_group_ask_names_its_channel(self):
        self.assertEqual(self.label(kind="group", channel_name="#ops"), "group in #ops")

    def test_a_channel_name_without_a_hash_is_shown_with_one(self):
        self.assertEqual(self.label(kind="thread", channel_name="ops"), "thread in #ops")

    def test_a_null_channel_name_leaves_the_kind_alone(self):
        self.assertEqual([self.label(kind=kind, channel_name=None) for kind in ("thread", "mention", "group")], ["thread", "mention", "group"])

    def test_a_channel_name_of_a_hash_alone_leaves_the_kind_alone(self):
        self.assertEqual(self.label(kind="thread", channel_name="#"), "thread")

    def test_a_root_message_links_to_its_own_timestamp(self):
        link = self.link_of(asked(REPLY, kind="thread", channel=OPS, root_ts=REPLY))
        self.assertEqual(link, f"[thread](https://example.test/archives/{OPS}/p1791990730002679)")

    def test_a_message_without_a_root_links_to_its_own_timestamp(self):
        link = self.link_of(asked(REPLY, kind="mention", channel=OPS))
        self.assertEqual(link, f"[mention](https://example.test/archives/{OPS}/p1791990730002679)")

    def test_a_reply_links_with_its_thread_and_channel(self):
        link = self.link_of(asked(REPLY, kind="thread", channel=OPS, channel_name="#ops", root_ts=ROOT))
        self.assertEqual(link, f"[thread in #ops](https://example.test/archives/{OPS}/p1791990730002679?thread_ts={ROOT}&cid={OPS})")

    def test_percent_encodes_a_channel_that_is_not_plain(self):
        link = self.link_of(asked(REPLY, channel="C1 )x"))
        self.assertEqual(link, "[DM](https://example.test/archives/C1%20%29x/p1791990730002679)")

    def test_a_workspace_that_is_not_a_plain_host_name_leaves_the_label_alone(self):
        for workspace in ("example.test/path", "https://example.test", "example.test?x=1", "exam ple.test", "evil.test)", ""):
            with self.subTest(workspace=workspace):
                text = self.render(make_summary(waiting=[asked(REPLY)]), workspace)
                self.assertNotIn("](", text)
                self.assertNotIn("archives", text)
                self.assertIn(" · DM\n", text)


class WhenTest(RenderCase):
    def since(self, stamp, run_at=RUN_AT):
        text = self.waiting_at(run_at, asked(stamp))[0]
        return text.split("since ")[1].split(" · ")[0]

    def test_a_time_in_the_week_of_the_run_shows_the_weekday_and_time(self):
        self.assertEqual(self.since(at("2026-10-12T08:30:00Z")), "Mon 10:30")

    def test_a_time_before_the_week_of_the_run_adds_the_date(self):
        self.assertEqual(self.since(at("2026-10-09T12:10:00Z")), "Fri 09 Oct 14:10")

    def test_the_sunday_before_the_run_week_is_outside_it(self):
        self.assertEqual(self.since(at("2026-10-11T12:00:00Z")), "Sun 11 Oct 14:00")

    def test_the_sunday_of_the_run_week_is_inside_it(self):
        self.assertEqual(self.since(at("2026-10-18T12:00:00Z"), run_at="2026-10-18T20:00:00Z"), "Sun 14:00")

    def test_a_week_that_spans_two_calendar_years_is_one_week(self):
        self.assertEqual(self.since(at("2026-12-30T09:00:00Z"), run_at="2027-01-01T09:00:00Z"), "Wed 10:00")

    def test_a_local_time_on_another_day_than_the_utc_one_follows_the_zone(self):
        self.assertEqual(self.since(at("2026-10-14T22:30:00Z")), "Thu 00:30")

    def test_uses_the_offset_in_force_then_across_the_autumn_change(self):
        self.assertEqual(self.since(at("2026-10-23T08:00:00Z"), run_at="2026-10-25T12:00:00Z"), "Fri 10:00")

    def test_uses_the_offset_in_force_then_across_the_spring_change(self):
        self.assertEqual(self.since(at("2026-03-27T08:00:00Z"), run_at="2026-03-29T12:00:00Z"), "Fri 09:00")

    def test_a_due_time_follows_the_same_format(self):
        inside = make_line(status="promise", due="2026-10-16T14:30:00Z")
        outside = make_line(status="promise", due="2026-10-19T08:00:00Z")
        got = [text.split(", by ")[1].split(" · ")[0] for text in self.waiting_at(RUN_AT, inside, outside)]
        self.assertEqual(got, ["Fri 16:30", "Mon 19 Oct 10:00"])

    def waiting_at(self, run_at, *lines):
        return self.waiting(*lines, run_at=run_at)


class TextSafetyTest(RenderCase):
    def test_neutralises_a_link_and_a_bold_span_in_a_summary(self):
        text = self.waiting(asked(at("2026-10-14T09:00:00Z"), summary="see [here](http://evil.example) and **this**"))[0]
        self.assertIn("see [here] (http://evil.example) and * *this* *", text)

    def test_neutralises_a_link_and_a_bold_span_in_a_name(self):
        text = self.waiting(asked(at("2026-10-14T09:00:00Z"), person=person(PEER, "[x](http://evil.example) **Boss**")))[0]
        self.assertIn("[x] (http://evil.example) * *Boss* *", text)
        self.assertEqual(text.count("]("), 1)

    def test_neutralises_a_title_a_reading_a_gap_and_a_channel_name(self):
        summary = make_summary(
            handled=[make_line(status="handled", title="a](b) **c**", kind="thread", channel_name="x](y)")],
            reading=[{"text": "d](e) **f**", "cites": ["x"]}],
            blind_spots=[{"key": "k", "gap": "g](h) **i**", "runs": 1}],
        )
        text = self.render(summary)
        self.assertIn("- a] (b) * *c* * · [thread in #x] (y)](", text)
        self.assertIn("- d] (e) * *f* *", text)
        self.assertIn("- Limits: g] (h) * *i* *", text)

    def test_blanks_mentions_markup_and_controls_in_a_summary(self):
        text = self.waiting(asked(at("2026-10-14T09:00:00Z"), summary="ping @here <b>now</b>\nplease"))[0]
        self.assertIn("ping  here  b now /b  please", text)

    def test_the_text_never_holds_json_keys_ids_or_unit_keys(self):
        text = self.render(golden_summary())
        for leaked in ("{", '"', "dm-", "thread-", PEER, OTHER, THIRD, "key", "cites"):
            with self.subTest(leaked=leaked):
                self.assertNotIn(leaked, text)

    def test_an_unreadable_time_is_left_to_the_caller(self):
        with self.assertRaises((OverflowError, OSError, ValueError)):
            self.render(make_summary(window={"from_ts": 10**18, "to_ts": 10**18}))


class GoldenTest(RenderCase):
    def test_renders_the_golden_message(self):
        with open(GOLDEN, encoding="utf-8") as handle:
            golden = handle.read()
        self.assertEqual(self.render(golden_summary()), golden)


class DegradedTest(unittest.TestCase):
    def test_a_rejected_judgment_says_so(self):
        self.assertEqual(recap_message.degraded("judgment"), "degraded: judgment rejected twice, no recap this run\n")

    def test_a_failed_structure_check_says_so(self):
        self.assertEqual(recap_message.degraded("structure"), "degraded: structure check failed, no recap this run\n")

    def test_any_other_cause_is_an_input_error(self):
        with self.assertRaisesRegex(state.InputError, "unknown degraded cause other"):
            recap_message.degraded("other")


def run_cli(*argv):
    parser = argparse.ArgumentParser(prog="recap.py")
    recap_message.add_message_arguments(parser)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = recap_message.run_message(parser.parse_args(list(argv)))
        except SystemExit as error:
            code = error.code
        except state.InputError as error:
            print(f"recap.py: {error}", file=sys.stderr)
            code = 2
    return code, out.getvalue(), err.getvalue()


class CliTest(FileCase):
    def setUp(self):
        super().setUp()
        self.config = self.write("config.json", self.make_config())
        self.summary = self.write("summary.json", golden_summary())

    def make_config(self, **changes):
        config = make_config(workspace=HOST, window={"lookback_working_days": 3})
        config["routines"][SLUG].update(changes)
        return config

    def use_config(self, mutate):
        config = self.make_config()
        mutate(config["routines"][SLUG])
        self.write("config.json", config)

    def message(self, *extra, place="cloud", summary=None):
        return run_cli(
            "--summary", summary or self.summary, "--config", self.config, "--routine", SLUG, "--place", place, "--tz", "Europe/Paris",
            "--out", self.path("message.md"), *extra,
        )

    def written(self):
        with open(self.path("message.md"), encoding="utf-8") as handle:
            return handle.read()

    def test_writes_the_golden_message_from_the_summary_and_the_routine(self):
        self.assertEqual(self.message()[0], 0)
        with open(GOLDEN, encoding="utf-8") as handle:
            self.assertEqual(self.written(), handle.read())

    def test_writes_the_same_message_for_the_other_place(self):
        self.assertEqual(self.message(place="local")[0], 0)
        self.assertEqual(self.written(), recap_message.render(golden_summary(), HOST, PARIS, 3))

    def test_the_lookback_comes_from_the_routine(self):
        self.write("summary.json", make_summary(limited="baseline"))
        self.use_config(lambda routine: routine.update({"window": {"lookback_working_days": 5}}))
        self.assertEqual(self.message()[0], 0)
        self.assertIn("(baseline, last 5 working days)", self.written())

    def test_the_workspace_comes_from_the_routine(self):
        self.use_config(lambda routine: routine.update({"workspace": "chat.example.test"}))
        self.assertEqual(self.message()[0], 0)
        self.assertIn("https://chat.example.test/archives/", self.written())

    def test_writes_a_degraded_message_without_any_other_input(self):
        code, _, err = run_cli("--degraded", "judgment", "--out", self.path("message.md"))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.written(), "degraded: judgment rejected twice, no recap this run\n")

    def test_writes_the_structure_degraded_message(self):
        self.assertEqual(run_cli("--degraded", "structure", "--out", self.path("message.md"))[0], 0)
        self.assertEqual(self.written(), "degraded: structure check failed, no recap this run\n")

    def test_an_unknown_degraded_cause_exits_2(self):
        code, _, err = run_cli("--degraded", "other", "--out", self.path("message.md"))
        self.assertEqual(code, 2)
        self.assertIn("--degraded", err)
        self.assertFalse(os.path.exists(self.path("message.md")))

    def test_a_degraded_message_refuses_the_summary_flags(self):
        code, _, err = self.message("--degraded", "judgment")
        self.assertEqual(code, 2)
        self.assertIn("--degraded excludes --summary, --config, --routine, --place, --tz", err)

    def test_a_message_without_the_summary_flags_or_a_cause_exits_2(self):
        code, _, err = run_cli("--summary", self.summary, "--out", self.path("message.md"))
        self.assertEqual(code, 2)
        self.assertIn("message: needs --config, --routine, --place, --tz, or --degraded", err)

    def fails_on(self, path, mutate):
        self.use_config(mutate)
        code, _, err = self.message()
        self.assertEqual(code, 2)
        self.assertIn(f"routines.{SLUG}.{path}", err)
        self.assertFalse(os.path.exists(self.path("message.md")))

    def test_a_routine_without_a_workspace_exits_2_with_the_key_path(self):
        self.fails_on("workspace", lambda routine: routine.pop("workspace"))

    def test_a_routine_with_an_empty_workspace_exits_2_with_the_key_path(self):
        self.fails_on("workspace", lambda routine: routine.update({"workspace": ""}))

    def test_a_routine_without_a_window_exits_2_with_the_key_path(self):
        self.fails_on("window", lambda routine: routine.pop("window"))

    def test_a_routine_without_a_lookback_exits_2_with_the_key_path(self):
        self.fails_on("window.lookback_working_days", lambda routine: routine.update({"window": {}}))

    def test_a_lookback_out_of_range_exits_2_with_the_key_path(self):
        for value in (0, 366, "3", True, 2.5):
            with self.subTest(value=value):
                self.fails_on("window.lookback_working_days", lambda routine: routine.update({"window": {"lookback_working_days": value}}))

    def test_a_routine_of_another_engine_exits_2(self):
        self.use_config(lambda routine: routine.update({"engine": "watch"}))
        code, _, err = self.message()
        self.assertEqual(code, 2)
        self.assertIn(f"routine {SLUG} is not a recap routine", err)

    def test_an_unknown_zone_exits_2(self):
        code, _, err = run_cli(
            "--summary", self.summary, "--config", self.config, "--routine", SLUG, "--place", "cloud", "--tz", "Nowhere/City", "--out", self.path("message.md")
        )
        self.assertEqual(code, 2)
        self.assertIn("--tz: unknown time zone Nowhere/City", err)

    def test_a_summary_missing_a_key_exits_2_with_the_key_path(self):
        broken = golden_summary()
        del broken["waiting"][0]["channel"]
        self.write("summary.json", broken)
        code, _, err = self.message()
        self.assertEqual(code, 2)
        self.assertIn("summary: missing key waiting[0].channel", err)

    def test_a_summary_that_is_not_json_exits_2(self):
        with open(self.path("summary.json"), "w", encoding="utf-8") as handle:
            handle.write("{")
        code, _, err = self.message()
        self.assertEqual(code, 2)
        self.assertIn("summary: invalid JSON", err)

    def test_a_summary_with_a_time_out_of_range_exits_2(self):
        broken = golden_summary()
        broken["window"]["from_ts"] = 10**18
        self.write("summary.json", broken)
        code, _, err = self.message()
        self.assertEqual(code, 2)
        self.assertIn("cannot render the message", err)
        self.assertFalse(os.path.exists(self.path("message.md")))


class RecapMainMessageTest(FileCase):
    def test_recap_main_renders_the_degraded_message(self):
        out = self.path("message.txt")

        code = recap.main(["message", "--degraded", "judgment", "--out", out])

        with open(out, encoding="utf-8") as handle:
            self.assertEqual((code, handle.read().startswith("degraded: judgment")), (0, True))


if __name__ == "__main__":
    unittest.main()
