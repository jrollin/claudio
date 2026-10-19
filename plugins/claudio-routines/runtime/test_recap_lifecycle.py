import os
import argparse
import contextlib
import copy
import io
import json
import unittest

import recap
import recap_features
import recap_lifecycle
import recap_state
import state
from recap_lifecycle import History
from support import ts
from test_recap_state import CHANNEL_A, CHANNEL_B, DM_A, NOW, PARIS, PREVIOUS, THREAD_B, TZ, FileCase, make_state, make_unit

OWNER = "U" + "1" * 6
PEER = "U" + "2" * 6
OTHER = "U" + "3" * 6
CHANNEL_C = "CHAN" + "3" * 6
CHANNEL_D = "CHAN" + "4" * 6
CHANNEL_E = "CHAN" + "5" * 6
ROOT_B = "1791990000.000100"
THREAD_C = f"thread-{CHANNEL_C}-{ROOT_B}"
THREAD_D = f"thread-{CHANNEL_D}-{ROOT_B}"
THREAD_E = f"thread-{CHANNEL_E}-{ROOT_B}"
NAMES = {OWNER: "Owner Name", PEER: "Peer Name", OTHER: "Other Name"}
HISTORY = History(3, 14)
THURSDAY = "2026-10-15T09:00:00Z"
SECRET_TEXT = "SECRET message text"
SECRET_SUMMARY = "SECRET summary text"
SECRET_READING = "SECRET reading text"
READING = [{"text": "Two asks wait on the owner", "cites": [DM_A]}, {"text": "Nothing else moved", "cites": [DM_A]}]


def at(text, fraction=100):
    return f"{ts(text)}.{fraction:06d}"


ASKED = at("2026-10-15T09:00:00Z")
ANSWERED = at("2026-10-15T10:00:00Z", 200)


def msg(user, stamp, text="hello", root=None, name=None):
    return {"user": user, "name": NAMES.get(user, "") if name is None else name, "bot": False, "ts": stamp, "root_ts": root, "mentions": [], "group_mentions": [], "text": text}


def facts_of(**fields):
    facts = {
        "last_author_is_owner": False,
        "unanswered_from": None,
        "groups": [],
        "announcement_channel": False,
        "direct_mention": False,
        "owner_answered": False,
        "owner_took_part": False,
        "age_working_days": None,
        "previous": None,
    }
    return {**facts, **fields}


def feature_unit(kind="dm", channel=CHANNEL_A, name="DM", messages=None, **facts):
    messages = messages or [msg(PEER, ASKED, text=SECRET_TEXT)]
    facts.setdefault("unanswered_from", messages[0]["ts"])
    facts.setdefault("last_author_is_owner", messages[-1]["user"] == OWNER)
    facts = facts_of(**facts)
    return {"kind": kind, "channel": channel, "name": name, "messages": messages, "facts": facts, "allowed": recap_features.allowed_kinds(kind, facts)}


def entry(kind="waiting on you", title="Review the export plan", summary="Peer asks for a review of the plan", blocking=False, due=None):
    return {"kind": kind, "title": title, "summary": summary, "blocking": blocking, "due": due}


def make_window(now=NOW, **fields):
    return {"from_ts": ts(now) - 86400, "to_ts": ts(now), "limited": None, "explicit": False, **fields}


def make_features(units, spots=()):
    return {"owner": OWNER, "window": make_window(), "units": units, "blind_spots": list(spots)}


def make_base(features_doc, participants=None):
    units = {}
    for key, unit in features_doc["units"].items():
        authors = {item["user"]: item["name"] for item in unit["messages"]}
        known = (participants or {}).get(key, [])
        units[key] = {
            "channel": unit["channel"],
            "name": unit["name"],
            "participants": [{"id": who, "name": NAMES[who]} for who in known],
            "authors": [{"id": who, "name": authors[who]} for who in sorted(authors)],
        }
    return {"sources": [], "units": units, "blind_spots": [], "models": {}}


def empty_state(**run):
    return make_state(units={}, blind_spots=[], **run)


STORED_KEYS = {"dm_a": DM_A, "thread_b": THREAD_B, "thread_e": THREAD_E}


def state_of(**units):
    return make_state(units={STORED_KEYS[name]: unit for name, unit in units.items()}, blind_spots=[])


def blind_spot(key="search-mentions", gap="search cut after 10 pages"):
    return {"key": key, "gap": gap}


class LifecycleCase(unittest.TestCase):
    def apply(self, units, entries, stored=None, spots=(), reading=None, window=None, now=NOW, history=HISTORY, participants=None):
        features_doc = make_features(units, spots)
        judged = {"units": entries, "reading": READING if reading is None else reading}
        window = window or make_window(now)
        previous = empty_state() if stored is None else stored
        result = recap_lifecycle.apply(previous, features_doc, make_base(features_doc, participants), judged, window, PARIS, history)
        recap_state.check_state(result[0])
        self.state, self.summary, self.record = result
        return result

    def unit(self, key=DM_A):
        return self.state["units"][key]

    def keys(self, section):
        return [line["key"] for line in self.summary[section]]

    def line(self, section, key=DM_A):
        return next(line for line in self.summary[section] if line["key"] == key)

    def run_one(self, kind, stored=None, **fields):
        self.apply({DM_A: feature_unit(**fields)}, {DM_A: entry(kind)}, stored)
        return self.unit()


class StatusMappingTest(LifecycleCase):
    def test_waiting_on_you_is_stored_as_waiting(self):
        self.assertEqual(self.run_one("waiting on you")["status"], "waiting")

    def test_promise_is_stored_as_promise(self):
        self.assertEqual(self.run_one("promise", messages=[msg(OWNER, ASKED)], unanswered_from=None)["status"], "promise")

    def test_youre_waiting_on_is_stored_as_waiting_on_others(self):
        self.assertEqual(self.run_one("you're waiting on", messages=[msg(OWNER, ASKED)], unanswered_from=None)["status"], "waiting_on_others")

    def test_team_ask_is_stored_as_team_ask(self):
        self.assertEqual(self.run_one("team ask")["status"], "team_ask")

    def test_already_handled_is_stored_as_handled(self):
        self.assertEqual(self.run_one("already handled", owner_answered=True, unanswered_from=None)["status"], "handled")

    def test_announcement_is_stored_as_announcement(self):
        self.assertEqual(self.run_one("announcement", announcement_channel=True)["status"], "announcement")

    def test_a_unit_is_stored_under_its_key_with_its_kind_and_channel(self):
        self.apply({THREAD_B: feature_unit("mention", CHANNEL_B, "#ops")}, {THREAD_B: entry()})

        self.assertEqual((self.unit(THREAD_B)["kind"], self.unit(THREAD_B)["channel"]), ("mention", CHANNEL_B))

    def test_a_unit_holds_exactly_the_state_fields(self):
        self.run_one("waiting on you")

        self.assertEqual(set(self.unit()), set(recap_state.UNIT_SPEC))

    def test_the_title_comes_from_the_judgment(self):
        self.apply({DM_A: feature_unit()}, {DM_A: entry(title="Export plan review")})

        self.assertEqual(self.unit()["title"], "Export plan review")

    def test_the_next_state_passes_the_state_check(self):
        self.run_one("waiting on you")

        self.assertIsNone(recap_state.check_state(self.state))


class NoiseTest(LifecycleCase):
    def test_a_noise_unit_is_not_stored(self):
        self.apply({DM_A: feature_unit()}, {DM_A: entry("noise")})

        self.assertEqual(self.state["units"], {})

    def test_a_noise_unit_is_in_no_section(self):
        self.apply({DM_A: feature_unit()}, {DM_A: entry("noise")})

        self.assertEqual([self.keys(name) for name in ("waiting", "good_to_know", "waiting_on_others", "handled")], [[], [], [], []])

    def test_a_noise_unit_leaves_the_state_when_it_was_stored_as_another_status(self):
        stored = state_of(dm_a=make_unit(status="team_ask", runs_waiting=0))
        self.apply({DM_A: feature_unit()}, {DM_A: entry("noise")}, stored)

        self.assertNotIn(DM_A, self.state["units"])

    def test_a_noise_unit_stored_as_waiting_is_kept_as_handled(self):
        stored = state_of(dm_a=make_unit(status="waiting"))
        self.apply({DM_A: feature_unit()}, {DM_A: entry("noise")}, stored)

        self.assertEqual(self.unit()["status"], "handled")

    def test_a_noise_unit_stored_as_promise_is_kept_as_handled(self):
        stored = state_of(dm_a=make_unit(status="promise"))
        self.apply({DM_A: feature_unit()}, {DM_A: entry("noise")}, stored)

        self.assertEqual(self.unit()["status"], "handled")


class RunsWaitingTest(LifecycleCase):
    def test_a_new_waiting_unit_has_run_once(self):
        self.apply({DM_A: feature_unit()}, {DM_A: entry()})

        self.assertEqual(self.unit()["runs_waiting"], 1)

    def test_a_waiting_unit_counts_one_more_run_each_time(self):
        self.apply({DM_A: feature_unit()}, {DM_A: entry()})
        self.apply({DM_A: feature_unit()}, {DM_A: entry()}, self.state)
        self.apply({DM_A: feature_unit()}, {DM_A: entry()}, self.state)

        self.assertEqual(self.unit()["runs_waiting"], 3)

    def test_a_promise_counts_its_runs(self):
        stored = state_of(dm_a=make_unit(status="promise", runs_waiting=4))
        self.apply({DM_A: feature_unit(messages=[msg(OWNER, ASKED)], unanswered_from=None)}, {DM_A: entry("promise")}, stored)

        self.assertEqual(self.unit()["runs_waiting"], 5)

    def test_a_waiting_unit_stored_with_a_count_adds_one(self):
        self.apply({DM_A: feature_unit()}, {DM_A: entry()}, state_of(dm_a=make_unit(runs_waiting=2)))

        self.assertEqual(self.unit()["runs_waiting"], 3)

    def test_a_unit_waiting_on_others_has_no_run_count(self):
        stored = state_of(dm_a=make_unit(status="waiting", runs_waiting=2))
        self.apply({DM_A: feature_unit(messages=[msg(OWNER, ASKED)], unanswered_from=None)}, {DM_A: entry("you're waiting on")}, stored)

        self.assertEqual(self.unit()["runs_waiting"], 0)

    def test_a_handled_unit_resets_its_count(self):
        stored = state_of(dm_a=make_unit(status="waiting", runs_waiting=2))
        self.apply({DM_A: feature_unit(owner_answered=True, unanswered_from=None)}, {DM_A: entry("already handled")}, stored)

        self.assertEqual(self.unit()["runs_waiting"], 0)

    def test_a_unit_that_waits_again_after_being_handled_starts_over(self):
        stored = state_of(dm_a=make_unit(status="handled", runs_waiting=0))
        self.apply({DM_A: feature_unit()}, {DM_A: entry()}, stored)

        self.assertEqual(self.unit()["runs_waiting"], 1)


class WaitingLateTest(LifecycleCase):
    MONDAY = at("2026-10-12T09:00:00Z")

    def late(self, now, asked=None, history=HISTORY):
        stamp = asked or self.MONDAY
        self.apply({DM_A: feature_unit(messages=[msg(PEER, stamp)])}, {DM_A: entry()}, now=now, history=history)
        return self.unit()["late"]

    def test_a_waiting_unit_is_not_late_at_the_configured_working_days(self):
        self.assertIsNone(self.late(THURSDAY))

    def test_a_waiting_unit_is_late_after_the_configured_working_days(self):
        self.assertEqual(self.late(NOW), 4)

    def test_a_waiting_unit_asked_today_is_not_late(self):
        self.assertIsNone(self.late(NOW, asked=at("2026-10-16T06:00:00Z")))

    def test_the_weekend_does_not_count(self):
        self.assertIsNone(self.late("2026-10-19T09:00:00Z", asked=at("2026-10-15T09:00:00Z")))

    def test_the_configured_threshold_drives_the_age(self):
        self.assertEqual(self.late(THURSDAY, history=History(2, 14)), 3)

    def test_the_age_counts_from_the_unanswered_message_not_the_first_one(self):
        messages = [msg(PEER, self.MONDAY), msg(OWNER, at("2026-10-12T10:00:00Z")), msg(PEER, at("2026-10-15T08:00:00Z"))]
        self.apply({DM_A: feature_unit(messages=messages, unanswered_from=messages[2]["ts"])}, {DM_A: entry()}, now=NOW)

        self.assertIsNone(self.unit()["late"])

    def test_a_team_ask_is_never_late(self):
        self.apply({DM_A: feature_unit(messages=[msg(PEER, self.MONDAY)])}, {DM_A: entry("team ask")}, now=NOW)

        self.assertIsNone(self.unit()["late"])

    def test_the_age_counts_local_days_across_the_autumn_clock_change(self):
        asked = at("2026-10-24T22:30:00Z")

        self.assertEqual(self.late("2026-10-29T23:30:00Z", asked=asked), 5)

    def test_the_age_counts_local_days_across_the_spring_clock_change(self):
        asked = at("2027-03-27T23:30:00Z")

        self.assertEqual(self.late("2027-04-01T22:30:00Z", asked=asked), 5)


class PromiseLateTest(LifecycleCase):
    def promise(self, due=None, first_seen="2026-10-15T07:45:00Z", stored=True, rejudged_due=...):
        previous = state_of(dm_a=make_unit(status="promise", first_seen=first_seen, due=due)) if stored else None
        unit = feature_unit(messages=[msg(OWNER, ASKED)], unanswered_from=None, last_author_is_owner=True)
        self.apply({DM_A: unit}, {DM_A: entry("promise", due=due if rejudged_due is ... else rejudged_due)}, previous)
        return self.unit()

    def test_a_promise_is_not_late_before_its_due_time(self):
        self.assertIsNone(self.promise(due="2026-10-16T12:00:00Z")["late"])

    def test_a_promise_is_late_once_its_due_time_has_passed(self):
        self.assertEqual(self.promise(due="2026-10-16T05:45:00Z")["late"], 0)

    def test_a_promise_counts_the_working_days_since_its_due_time(self):
        self.assertEqual(self.promise(due="2026-10-12T09:00:00Z")["late"], 4)

    def test_a_promise_without_a_due_time_is_late_from_the_working_day_after_it_was_first_seen(self):
        self.assertEqual(self.promise(first_seen="2026-10-15T07:45:00Z")["late"], 1)

    def test_a_promise_without_a_due_time_counts_the_working_days_since_it_was_first_seen(self):
        self.assertEqual(self.promise(first_seen="2026-10-14T07:45:00Z")["late"], 2)

    def test_a_promise_without_a_due_time_is_not_late_the_day_it_was_first_seen(self):
        self.assertIsNone(self.promise(first_seen="2026-10-16T06:00:00Z")["late"])

    def test_a_new_promise_without_a_due_time_is_not_late(self):
        self.assertIsNone(self.promise(stored=False)["late"])

    def test_the_weekend_does_not_make_a_promise_late(self):
        previous = state_of(dm_a=make_unit(status="promise", first_seen="2026-10-16T07:45:00Z"))
        unit = feature_unit(messages=[msg(OWNER, ASKED)], unanswered_from=None)
        self.apply({DM_A: unit}, {DM_A: entry("promise")}, previous, now="2026-10-18T07:45:00Z")

        self.assertIsNone(self.unit()["late"])

    def test_the_next_working_day_after_a_weekend_makes_a_promise_late(self):
        previous = state_of(dm_a=make_unit(status="promise", first_seen="2026-10-16T07:45:00Z"))
        unit = feature_unit(messages=[msg(OWNER, ASKED)], unanswered_from=None)
        self.apply({DM_A: unit}, {DM_A: entry("promise")}, previous, now="2026-10-19T07:45:00Z")

        self.assertEqual(self.unit()["late"], 1)

    def test_a_promise_re_judged_without_a_due_time_is_late_from_its_stored_due_time(self):
        self.assertEqual(self.promise(due="2026-10-12T09:00:00Z", rejudged_due=None)["late"], 4)


class DueTest(LifecycleCase):
    def due_of(self, due, stored=None):
        unit = feature_unit(messages=[msg(OWNER, ASKED)], unanswered_from=None)
        self.apply({DM_A: unit}, {DM_A: entry("promise", due=due)}, stored)
        return self.unit()["due"]

    def test_a_due_time_with_an_offset_is_stored_as_utc(self):
        self.assertEqual(self.due_of("2026-10-16T14:00:00+02:00"), "2026-10-16T12:00:00Z")

    def test_a_due_time_with_a_negative_offset_is_stored_as_utc(self):
        self.assertEqual(self.due_of("2026-10-16T08:30:00-05:00"), "2026-10-16T13:30:00Z")

    def test_a_due_time_in_utc_is_kept(self):
        self.assertEqual(self.due_of("2026-10-16T12:00:00Z"), "2026-10-16T12:00:00Z")

    def test_a_promise_without_a_due_time_stores_none(self):
        self.assertIsNone(self.due_of(None))

    def test_the_due_time_comes_from_the_judgment_not_the_stored_unit(self):
        stored = state_of(dm_a=make_unit(status="promise", due="2026-10-17T12:00:00Z"))

        self.assertEqual(self.due_of("2026-10-18T09:00:00+02:00", stored), "2026-10-18T07:00:00Z")

    def test_an_offset_due_time_makes_the_promise_late_at_its_utc_instant(self):
        self.due_of("2026-10-16T09:00:00+02:00")

        self.assertEqual(self.unit()["late"], 0)

    def test_a_promise_re_judged_without_a_due_time_keeps_its_stored_due_time(self):
        stored = state_of(dm_a=make_unit(status="promise", due="2026-10-17T12:00:00Z"))

        self.assertEqual(self.due_of(None, stored), "2026-10-17T12:00:00Z")

    def test_a_promise_that_was_not_one_before_takes_no_stored_due_time(self):
        stored = state_of(dm_a=make_unit(status="handled", runs_waiting=0, due="2026-10-17T12:00:00Z"))

        self.assertIsNone(self.due_of(None, stored))

    def test_a_promise_settled_as_handled_keeps_no_due_time(self):
        stored = state_of(dm_a=make_unit(status="promise", due="2026-10-17T12:00:00Z"))
        self.apply({DM_A: feature_unit(owner_answered=True, unanswered_from=None)}, {DM_A: entry("already handled")}, stored)

        self.assertIsNone(self.unit()["due"])


class ResolvedTest(LifecycleCase):
    def settle(self, kind="already handled", stored_status="waiting", **facts):
        stored = state_of(dm_a=make_unit(status=stored_status))
        facts.setdefault("unanswered_from", None)
        self.apply({DM_A: feature_unit(**facts)}, {DM_A: entry(kind)}, stored)

    def test_a_stored_waiting_unit_judged_handled_is_resolved(self):
        self.settle()

        self.assertEqual(self.summary["resolved"], [DM_A])

    def test_a_resolved_unit_is_stored_as_handled(self):
        self.settle()

        self.assertEqual(self.unit()["status"], "handled")

    def test_a_stored_promise_judged_handled_is_resolved(self):
        self.settle(stored_status="promise")

        self.assertEqual(self.summary["resolved"], [DM_A])

    def test_a_stored_waiting_unit_judged_noise_is_resolved(self):
        self.settle("noise")

        self.assertEqual(self.summary["resolved"], [DM_A])

    def test_a_stored_waiting_unit_the_owner_answered_is_resolved_even_when_judged_youre_waiting_on(self):
        self.settle("you're waiting on", owner_answered=True)

        self.assertEqual((self.summary["resolved"], self.unit()["status"]), ([DM_A], "handled"))

    def test_a_stored_promise_judged_noise_is_resolved(self):
        self.settle("noise", stored_status="promise")

        self.assertEqual(self.summary["resolved"], [DM_A])

    def test_a_stored_promise_the_owner_answered_and_re_judged_promise_stays_a_promise(self):
        stored = state_of(dm_a=make_unit(status="promise"))
        messages = [msg(PEER, ASKED), msg(OWNER, ANSWERED)]
        self.apply({DM_A: feature_unit(messages=messages, unanswered_from=None, owner_answered=True)}, {DM_A: entry("promise")}, stored)

        self.assertEqual((self.unit()["status"], self.summary["resolved"], self.keys("waiting")), ("promise", [], [DM_A]))

    def test_a_stored_promise_the_owner_answered_and_judged_youre_waiting_on_is_not_resolved(self):
        self.settle("you're waiting on", stored_status="promise", owner_answered=True)

        self.assertEqual((self.unit()["status"], self.summary["resolved"]), ("waiting_on_others", []))

    def test_a_stored_waiting_unit_the_owner_answered_and_re_judged_promise_is_resolved(self):
        self.settle("promise", owner_answered=True)

        self.assertEqual((self.unit()["status"], self.summary["resolved"]), ("handled", [DM_A]))

    def test_a_resolved_unit_is_listed_once_under_handled_and_flagged(self):
        self.settle()

        self.assertEqual([(line["key"], line["resolved"]) for line in self.summary["handled"]], [(DM_A, True)])

    def test_a_resolved_unit_is_not_listed_again_on_the_next_run(self):
        self.settle()
        self.apply({DM_A: feature_unit(owner_answered=True, unanswered_from=None)}, {DM_A: entry("already handled")}, self.state)

        self.assertEqual((self.summary["resolved"], self.keys("handled")), ([], []))

    def test_a_resolved_unit_stays_handled_on_the_next_run(self):
        self.settle()
        self.apply({DM_A: feature_unit(owner_answered=True, unanswered_from=None)}, {DM_A: entry("already handled")}, self.state)

        self.assertEqual(self.unit()["status"], "handled")

    def test_a_stored_team_ask_judged_handled_is_not_resolved(self):
        self.settle(stored_status="team_ask")

        self.assertEqual(self.summary["resolved"], [])

    def test_a_stored_team_ask_judged_handled_is_stored_as_handled(self):
        self.settle(stored_status="team_ask")

        self.assertEqual(self.unit()["status"], "handled")

    def test_a_new_unit_judged_handled_is_listed_under_handled_without_the_flag(self):
        self.apply({DM_A: feature_unit(owner_answered=True, unanswered_from=None)}, {DM_A: entry("already handled")})

        self.assertEqual([(line["key"], line["resolved"]) for line in self.summary["handled"]], [(DM_A, False)])

    def test_a_stored_waiting_unit_still_waiting_is_not_resolved(self):
        self.settle("waiting on you", unanswered_from=ASKED)

        self.assertEqual(self.summary["resolved"], [])


class DropTest(LifecycleCase):
    CUTOFF = ts(NOW) - 14 * 86400
    STALE = f"{CUTOFF - 1}.999999"
    OLD = f"{CUTOFF - 60}.000100"

    def test_a_stored_unit_absent_from_the_run_and_older_than_the_drop_days_leaves_the_state(self):
        stored = state_of(dm_a=make_unit(last_ts=self.STALE))
        self.apply({}, {}, stored)

        self.assertEqual(self.state["units"], {})

    def test_a_stored_unit_at_exactly_the_drop_days_stays(self):
        stored = state_of(dm_a=make_unit(last_ts=f"{self.CUTOFF}.000000"))
        self.apply({}, {}, stored)

        self.assertIn(DM_A, self.state["units"])

    def test_a_stored_unit_absent_from_the_run_is_kept_unchanged(self):
        stored = state_of(dm_a=make_unit(runs_waiting=2, late=1), thread_b=make_unit(kind="thread", channel=CHANNEL_B, status="team_ask", runs_waiting=0))
        self.apply({DM_A: feature_unit(channel=CHANNEL_A)}, {DM_A: entry("noise")}, stored)

        self.assertEqual(self.state["units"][THREAD_B], stored["units"][THREAD_B])

    def test_a_unit_read_in_the_run_with_old_messages_stays_in_the_state(self):
        self.apply({DM_A: feature_unit(messages=[msg(PEER, self.OLD)])}, {DM_A: entry()})

        self.assertIn(DM_A, self.state["units"])

    def test_a_unit_read_in_the_run_with_old_messages_stays_in_the_summary(self):
        self.apply({DM_A: feature_unit(messages=[msg(PEER, self.OLD)])}, {DM_A: entry()})

        self.assertEqual((self.keys("waiting"), self.summary["counts"]["waiting"]), ([DM_A], 1))

    def test_a_stored_unit_read_in_the_run_with_old_messages_stays(self):
        stored = state_of(dm_a=make_unit(last_ts=self.OLD))
        self.apply({DM_A: feature_unit(messages=[msg(PEER, self.OLD)])}, {DM_A: entry()}, stored)

        self.assertEqual((DM_A in self.state["units"], self.record["dropped"]), (True, []))

    def test_a_dropped_unit_is_left_out_of_the_summary(self):
        stored = state_of(dm_a=make_unit(last_ts=self.STALE))
        self.apply({}, {}, stored)

        self.assertEqual((self.summary["counts"]["waiting"], self.keys("waiting")), (0, []))

    def test_a_dropped_unit_is_listed_in_the_record(self):
        stored = state_of(dm_a=make_unit(last_ts=self.STALE))
        self.apply({}, {}, stored)

        self.assertEqual(self.record["dropped"], [DM_A])

    def test_the_record_lists_only_the_stored_units_it_dropped(self):
        stored = state_of(dm_a=make_unit(last_ts=self.STALE))
        self.apply({THREAD_B: feature_unit("thread", CHANNEL_B, "#ops", messages=[msg(PEER, self.OLD)])}, {THREAD_B: entry()}, stored)

        self.assertEqual((self.record["dropped"], sorted(self.state["units"])), ([DM_A], [THREAD_B]))

    def test_the_drop_days_are_configurable(self):
        stored = state_of(dm_a=make_unit(last_ts=f"{ts(NOW) - 3 * 86400}.000000"))
        self.apply({}, {}, stored, history=History(3, 2))

        self.assertEqual(self.state["units"], {})

    def test_a_unit_read_again_with_a_recent_message_stays(self):
        stored = state_of(dm_a=make_unit(last_ts=f"{self.CUTOFF - 60}.000100"))
        self.apply({DM_A: feature_unit()}, {DM_A: entry()}, stored)

        self.assertIn(DM_A, self.state["units"])


class KeptStateTest(LifecycleCase):
    def test_first_seen_is_the_run_time_of_a_new_unit(self):
        self.apply({DM_A: feature_unit()}, {DM_A: entry()})

        self.assertEqual(self.unit()["first_seen"], NOW)

    def test_first_seen_is_kept_from_the_stored_unit(self):
        self.apply({DM_A: feature_unit()}, {DM_A: entry()}, state_of(dm_a=make_unit(first_seen="2026-10-10T08:00:00Z")))

        self.assertEqual(self.unit()["first_seen"], "2026-10-10T08:00:00Z")

    def test_last_ts_is_the_newest_message_of_the_run(self):
        messages = [msg(PEER, ANSWERED), msg(OWNER, ASKED)]
        self.apply({DM_A: feature_unit(messages=messages, unanswered_from=None)}, {DM_A: entry("already handled")})

        self.assertEqual(self.unit()["last_ts"], ANSWERED)

    def test_last_ts_of_an_absent_unit_is_the_stored_one(self):
        self.apply({}, {}, state_of(dm_a=make_unit()))

        self.assertEqual(self.unit()["last_ts"], make_unit()["last_ts"])

    def test_a_stored_handled_unit_that_turns_waiting_gets_a_fresh_first_seen(self):
        self.apply({DM_A: feature_unit()}, {DM_A: entry()}, state_of(dm_a=make_unit(status="handled", runs_waiting=0)))

        self.assertEqual(self.unit()["first_seen"], NOW)

    def test_a_stored_handled_unit_that_turns_waiting_is_new(self):
        self.apply({DM_A: feature_unit()}, {DM_A: entry()}, state_of(dm_a=make_unit(status="handled", runs_waiting=0)))

        self.assertEqual((self.line("waiting")["is_new"], self.keys("waiting"), self.record["new"]), (True, [DM_A], [DM_A]))

    def test_a_stored_unit_waited_on_that_turns_promise_gets_a_fresh_first_seen_and_is_new(self):
        stored = state_of(dm_a=make_unit(status="waiting_on_others", runs_waiting=0))
        self.apply({DM_A: feature_unit(messages=[msg(OWNER, ASKED)], unanswered_from=None)}, {DM_A: entry("promise")}, stored)

        self.assertEqual((self.unit()["first_seen"], self.line("waiting")["is_new"]), (NOW, True))

    def test_a_stored_waiting_unit_keeps_its_first_seen_and_is_not_new_when_it_turns_promise(self):
        stored = state_of(dm_a=make_unit(status="waiting", first_seen="2026-10-10T08:00:00Z"))
        self.apply({DM_A: feature_unit(messages=[msg(OWNER, ASKED)], unanswered_from=None)}, {DM_A: entry("promise")}, stored)

        self.assertEqual((self.unit()["first_seen"], self.line("waiting")["is_new"]), ("2026-10-10T08:00:00Z", False))

    def test_a_stored_team_ask_that_turns_handled_keeps_its_first_seen(self):
        stored = state_of(dm_a=make_unit(status="team_ask", runs_waiting=0, first_seen="2026-10-10T08:00:00Z"))
        self.apply({DM_A: feature_unit(owner_answered=True, unanswered_from=None)}, {DM_A: entry("already handled")}, stored)

        self.assertEqual(self.unit()["first_seen"], "2026-10-10T08:00:00Z")

    def test_a_stored_promise_absent_from_the_run_has_its_late_age_recomputed_from_its_due_time(self):
        stored = state_of(dm_a=make_unit(status="promise", due="2026-10-12T09:00:00Z", late=None))
        self.apply({}, {}, stored)

        self.assertEqual(self.unit()["late"], 4)

    def test_a_stored_promise_absent_from_the_run_is_no_longer_late_before_its_due_time(self):
        stored = state_of(dm_a=make_unit(status="promise", due="2026-10-17T09:00:00Z", late=3))
        self.apply({}, {}, stored)

        self.assertIsNone(self.unit()["late"])

    def test_a_stored_promise_without_a_due_time_absent_from_the_run_is_late_from_the_next_working_day(self):
        stored = state_of(dm_a=make_unit(status="promise", first_seen="2026-10-15T07:45:00Z", late=None))
        self.apply({}, {}, stored)

        self.assertEqual(self.unit()["late"], 1)

    def test_a_stored_waiting_unit_absent_from_the_run_keeps_its_late_age(self):
        stored = state_of(dm_a=make_unit(status="waiting", late=5))
        self.apply({}, {}, stored)

        self.assertEqual(self.unit()["late"], 5)


class ChannelNameTest(LifecycleCase):
    def name_of(self, name, kind="thread", channel=CHANNEL_B, stored=None, key=THREAD_B):
        previous = None if stored is None else state_of(thread_b=make_unit(kind="thread", channel=CHANNEL_B, channel_name=stored))
        self.apply({key: feature_unit(kind, channel, name)}, {key: entry()}, previous)
        return self.unit(key)["channel_name"]

    def test_a_real_channel_name_is_stored(self):
        self.assertEqual(self.name_of("#ops"), "#ops")

    def test_a_new_real_name_replaces_the_stored_one(self):
        self.assertEqual(self.name_of("#platform", stored="#ops"), "#platform")

    def test_a_name_that_is_the_channel_id_keeps_the_stored_name(self):
        self.assertEqual(self.name_of(CHANNEL_B, stored="#ops"), "#ops")

    def test_a_name_that_is_the_channel_id_stores_none_when_nothing_is_stored(self):
        self.assertIsNone(self.name_of(CHANNEL_B))

    def test_a_channel_with_no_name_keeps_the_stored_name(self):
        self.assertEqual(self.name_of("#", stored="#ops"), "#ops")

    def test_a_direct_conversation_has_no_channel_name(self):
        self.assertIsNone(self.name_of("DM", kind="dm", channel=CHANNEL_A, key=DM_A))

    def test_a_group_conversation_has_no_channel_name(self):
        self.assertIsNone(self.name_of("group DM", kind="group_dm", channel=CHANNEL_A, key=DM_A))

    def test_a_name_is_cut_to_80_characters(self):
        self.assertEqual(len(self.name_of("#" + "n" * 100)), 80)

    def test_a_name_holds_no_mention_character(self):
        self.assertEqual(self.name_of("#ops <team> @all"), "#ops  team   all")

    def test_an_absent_unit_keeps_its_stored_name(self):
        stored = state_of(thread_b=make_unit(kind="thread", channel=CHANNEL_B, channel_name="#ops"))
        self.apply({}, {}, stored)

        self.assertEqual(self.unit(THREAD_B)["channel_name"], "#ops")

    def test_a_unit_that_is_not_waiting_keeps_the_name_it_reads(self):
        self.apply({THREAD_B: feature_unit("thread", CHANNEL_B, "#ops")}, {THREAD_B: entry("announcement")})

        self.assertEqual(self.unit(THREAD_B)["channel_name"], "#ops")


class PersonTest(LifecycleCase):
    PEER_PERSON = {"id": PEER, "name": "Peer Name"}

    def person_of(self, kind, units=None, stored=None, participants=None, key=DM_A):
        self.apply(units or {key: feature_unit()}, {key: entry(kind)}, stored, participants=participants)
        return self.unit(key)["person"]

    def test_a_waiting_unit_names_the_author_of_the_unanswered_message(self):
        messages = [msg(OWNER, at("2026-10-15T08:00:00Z")), msg(PEER, ASKED), msg(OTHER, at("2026-10-15T11:00:00Z"))]
        units = {DM_A: feature_unit(messages=messages, unanswered_from=ASKED)}

        self.assertEqual(self.person_of("waiting on you", units), self.PEER_PERSON)

    def test_a_team_ask_names_the_author_of_the_unanswered_message(self):
        self.assertEqual(self.person_of("team ask"), self.PEER_PERSON)

    def test_a_direct_conversation_waited_on_names_the_other_participant(self):
        units = {DM_A: feature_unit(messages=[msg(PEER, ASKED), msg(OWNER, ANSWERED)], unanswered_from=None)}
        participants = {DM_A: [OWNER, PEER]}

        self.assertEqual(self.person_of("you're waiting on", units, participants=participants), self.PEER_PERSON)

    def test_a_direct_conversation_without_a_message_of_the_other_names_the_participant(self):
        units = {DM_A: feature_unit(messages=[msg(OWNER, ASKED)], unanswered_from=None)}
        participants = {DM_A: [OWNER, PEER]}

        self.assertEqual(self.person_of("you're waiting on", units, participants=participants), self.PEER_PERSON)

    def test_a_thread_waited_on_names_the_last_other_author(self):
        messages = [msg(OWNER, ASKED), msg(PEER, at("2026-10-15T09:30:00Z")), msg(OTHER, at("2026-10-15T09:45:00Z")), msg(OWNER, ANSWERED)]
        units = {THREAD_B: feature_unit("thread", CHANNEL_B, "#ops", messages=messages, unanswered_from=None)}

        self.assertEqual(self.person_of("you're waiting on", units, key=THREAD_B), {"id": OTHER, "name": "Other Name"})

    def test_a_group_conversation_waited_on_names_the_last_other_author(self):
        messages = [msg(PEER, ASKED), msg(OTHER, at("2026-10-15T09:45:00Z")), msg(OWNER, ANSWERED)]
        units = {DM_A: feature_unit("group_dm", CHANNEL_A, "group DM", messages=messages, unanswered_from=None)}
        participants = {DM_A: [OWNER, PEER, OTHER]}

        self.assertEqual(self.person_of("you're waiting on", units, participants=participants), {"id": OTHER, "name": "Other Name"})

    def test_a_promise_names_no_person(self):
        stored = state_of(dm_a=make_unit(status="promise", person={"id": OTHER, "name": "Other Name"}))
        units = {DM_A: feature_unit(messages=[msg(OWNER, ASKED)], unanswered_from=None)}

        self.assertIsNone(self.person_of("promise", units, stored))

    def test_a_handled_unit_names_no_person(self):
        stored = state_of(dm_a=make_unit(person={"id": OTHER, "name": "Other Name"}))
        units = {DM_A: feature_unit(owner_answered=True, unanswered_from=None)}

        self.assertIsNone(self.person_of("already handled", units, stored))

    def test_a_waiting_unit_replaces_the_stored_person_with_the_asker(self):
        stored = state_of(dm_a=make_unit(person={"id": OTHER, "name": "Other Name"}))

        self.assertEqual(self.person_of("waiting on you", stored=stored), self.PEER_PERSON)

    def test_a_unit_waited_on_without_another_author_names_no_person(self):
        stored = state_of(thread_b=make_unit(kind="thread", channel=CHANNEL_B, person=self.PEER_PERSON))
        units = {THREAD_B: feature_unit("thread", CHANNEL_B, "#ops", messages=[msg(OWNER, ASKED)], unanswered_from=None)}

        self.assertIsNone(self.person_of("you're waiting on", units, stored, key=THREAD_B))

    def test_an_asker_without_a_display_name_keeps_the_stored_person_of_that_asker(self):
        stored = state_of(dm_a=make_unit(person=self.PEER_PERSON))
        units = {DM_A: feature_unit(messages=[msg(PEER, ASKED, name="")])}

        self.assertEqual(self.person_of("waiting on you", units, stored), self.PEER_PERSON)

    def test_an_asker_without_a_display_name_does_not_inherit_the_stored_person_of_another(self):
        stored = state_of(dm_a=make_unit(person={"id": OTHER, "name": "Other Name"}))
        units = {DM_A: feature_unit(messages=[msg(PEER, ASKED, name="")])}

        self.assertIsNone(self.person_of("waiting on you", units, stored))

    def test_a_counterpart_without_a_display_name_keeps_the_stored_person_of_that_counterpart(self):
        stored = state_of(dm_a=make_unit(status="waiting_on_others", runs_waiting=0, person=self.PEER_PERSON))
        units = {DM_A: feature_unit(messages=[msg(PEER, ASKED, name=""), msg(OWNER, ANSWERED)], unanswered_from=None)}

        self.assertEqual(self.person_of("you're waiting on", units, stored), self.PEER_PERSON)

    def test_a_person_is_null_when_nothing_names_one(self):
        units = {DM_A: feature_unit(messages=[msg(OWNER, ASKED)], unanswered_from=None)}

        self.assertIsNone(self.person_of("announcement", units))

    def test_a_person_without_a_display_name_is_not_stored(self):
        units = {DM_A: feature_unit(messages=[msg(PEER, ASKED, name="")])}

        self.assertIsNone(self.person_of("waiting on you", units))

    def test_a_display_name_is_read_from_the_base_when_the_message_has_none(self):
        features_doc = make_features({DM_A: feature_unit(messages=[msg(PEER, ASKED, name="")])})
        base = make_base(features_doc)
        base["units"][DM_A]["participants"] = [{"id": PEER, "name": "Peer Base"}]
        judged = {"units": {DM_A: entry()}, "reading": READING}

        next_state = recap_lifecycle.apply(empty_state(), features_doc, base, judged, make_window(), PARIS, HISTORY)[0]

        self.assertEqual(next_state["units"][DM_A]["person"], {"id": PEER, "name": "Peer Base"})

    def test_a_display_name_holds_no_mention_character_and_at_most_80_characters(self):
        units = {DM_A: feature_unit(messages=[msg(PEER, ASKED, name="<Peer> @" + "n" * 100)])}

        name = self.person_of("waiting on you", units)["name"]

        self.assertEqual((len(name), set("<>@") & set(name)), (80, set()))

    def test_an_author_whose_id_is_not_a_chat_id_is_not_stored_as_a_person(self):
        units = {DM_A: feature_unit(messages=[msg("not an id", ASKED, name="Peer Name")])}

        self.assertIsNone(self.person_of("waiting on you", units))

    def test_a_person_holds_an_id_and_a_name_only(self):
        self.assertEqual(set(self.person_of("waiting on you")), {"id", "name"})


class RunBlockTest(LifecycleCase):
    def test_the_run_time_is_the_window_end_in_utc(self):
        self.apply({}, {})

        self.assertEqual(self.state["run"]["at"], NOW)

    def test_the_previous_run_time_is_the_stored_one(self):
        self.apply({}, {})

        self.assertEqual(self.state["run"]["previous_at"], PREVIOUS)

    def test_the_window_is_recorded_as_from_and_to(self):
        self.apply({}, {})

        self.assertEqual(self.state["run"]["window"], {"from_ts": ts(NOW) - 86400, "to_ts": ts(NOW)})

    def test_the_first_run_has_no_previous_run_time(self):
        self.apply({}, {}, recap_state.initial_state("chat-recap"))

        self.assertIsNone(self.state["run"]["previous_at"])

    def test_the_digest_is_kept(self):
        self.apply({}, {})

        self.assertEqual(self.state["digest"], "chat-recap")

    def test_a_window_that_ends_before_the_stored_run_is_rejected(self):
        with self.assertRaisesRegex(state.Rejected, r"^window: to_ts \d+ is before the state run.at"):
            self.apply({}, {}, now="2026-10-14T07:45:00Z")


class BlindSpotTest(LifecycleCase):
    def test_a_new_gap_is_stored_for_one_run(self):
        self.apply({}, {}, spots=[blind_spot()])

        self.assertEqual(self.state["blind_spots"], [{"key": "search-mentions", "gap": "search cut after 10 pages", "runs": 1}])

    def test_a_gap_seen_again_counts_one_more_run(self):
        stored = empty_state()
        stored["blind_spots"] = [{"key": "search-mentions", "gap": "old", "runs": 2}]
        self.apply({}, {}, stored, spots=[blind_spot()])

        self.assertEqual(self.state["blind_spots"][0]["runs"], 3)

    def test_a_gap_that_is_gone_leaves_the_state(self):
        stored = empty_state()
        stored["blind_spots"] = [{"key": "search-mentions", "gap": "old", "runs": 2}]
        self.apply({}, {}, stored)

        self.assertEqual(self.state["blind_spots"], [])

    def test_the_summary_lists_the_gaps_with_their_runs(self):
        self.apply({}, {}, spots=[blind_spot()])

        self.assertEqual(self.summary["blind_spots"], self.state["blind_spots"])

    def test_the_record_lists_the_gap_keys_and_runs_without_the_text(self):
        self.apply({}, {}, spots=[blind_spot()])

        self.assertEqual(self.record["blind_spots"], [{"key": "search-mentions", "runs": 1}])


class SummaryTest(LifecycleCase):
    def test_a_waiting_line_holds_the_fields_of_the_message(self):
        self.apply({DM_A: feature_unit(name="DM")}, {DM_A: entry(blocking=True)})

        expected = {
            "key": DM_A,
            "kind": "dm",
            "status": "waiting",
            "channel": CHANNEL_A,
            "channel_name": None,
            "ts": ASKED,
            "root_ts": None,
            "person": {"id": PEER, "name": "Peer Name"},
            "title": "Review the export plan",
            "summary": "Peer asks for a review of the plan",
            "blocking": True,
            "due": None,
            "late": None,
            "first_seen": NOW,
            "unanswered_from": ASKED,
            "is_new": True,
            "resolved": False,
        }
        self.assertEqual(self.line("waiting"), expected)

    def test_a_line_links_the_unanswered_message(self):
        messages = [msg(PEER, at("2026-10-15T08:00:00Z")), msg(OWNER, at("2026-10-15T08:30:00Z")), msg(PEER, ASKED)]
        self.apply({DM_A: feature_unit(messages=messages, unanswered_from=ASKED)}, {DM_A: entry()})

        self.assertEqual(self.line("waiting")["ts"], ASKED)

    def test_a_line_links_the_newest_message_when_nothing_is_unanswered(self):
        messages = [msg(PEER, ASKED), msg(OWNER, ANSWERED)]
        self.apply({DM_A: feature_unit(messages=messages, unanswered_from=None)}, {DM_A: entry("already handled")})

        self.assertEqual(self.line("handled")["ts"], ANSWERED)

    def test_a_line_of_a_reply_holds_the_thread_root(self):
        messages = [msg(PEER, ASKED, root=ROOT_B)]
        self.apply({THREAD_B: feature_unit("thread", CHANNEL_B, "#ops", messages=messages)}, {THREAD_B: entry()})

        self.assertEqual((self.line("waiting", THREAD_B)["ts"], self.line("waiting", THREAD_B)["root_ts"]), (ASKED, ROOT_B))

    def test_a_promise_is_listed_under_waiting(self):
        unit = feature_unit(messages=[msg(OWNER, ASKED)], unanswered_from=None)
        self.apply({DM_A: unit}, {DM_A: entry("promise")})

        self.assertEqual((self.keys("waiting"), self.line("waiting")["status"]), ([DM_A], "promise"))

    def test_team_asks_and_announcements_are_listed_under_good_to_know(self):
        units = {DM_A: feature_unit(), THREAD_B: feature_unit("thread", CHANNEL_B, "#ops")}
        self.apply(units, {DM_A: entry("team ask"), THREAD_B: entry("announcement")})

        self.assertEqual(self.keys("good_to_know"), [DM_A, THREAD_B])

    def test_a_unit_waited_on_is_listed_under_waiting_on_others(self):
        unit = feature_unit(messages=[msg(OWNER, ASKED)], unanswered_from=None)
        self.apply({DM_A: unit}, {DM_A: entry("you're waiting on")})

        self.assertEqual(self.keys("waiting_on_others"), [DM_A])

    def test_the_lines_of_a_section_come_in_key_order(self):
        units = {THREAD_C: feature_unit("thread", CHANNEL_C, "#c"), THREAD_B: feature_unit("thread", CHANNEL_B, "#b"), DM_A: feature_unit()}
        self.apply(units, {key: entry() for key in units})

        self.assertEqual(self.keys("waiting"), [DM_A, THREAD_B, THREAD_C])

    def test_a_stored_unit_is_not_new(self):
        self.apply({DM_A: feature_unit()}, {DM_A: entry()}, state_of(dm_a=make_unit()))

        self.assertIs(self.line("waiting")["is_new"], False)

    def test_the_reading_is_carried_as_judged(self):
        self.apply({}, {}, reading=[{"text": SECRET_READING, "cites": [DM_A]}])

        self.assertEqual(self.summary["reading"], [{"text": SECRET_READING, "cites": [DM_A]}])

    def test_the_summary_text_of_the_judgment_is_carried(self):
        self.apply({DM_A: feature_unit()}, {DM_A: entry(summary=SECRET_SUMMARY)})

        self.assertEqual(self.line("waiting")["summary"], SECRET_SUMMARY)

    def test_the_limited_window_is_carried(self):
        self.apply({}, {}, window=make_window(limited="gap"))

        self.assertEqual(self.summary["limited"], "gap")

    def test_a_normal_window_has_no_limit(self):
        self.apply({}, {})

        self.assertIsNone(self.summary["limited"])

    def test_the_summary_holds_the_run_time_and_window(self):
        self.apply({}, {})

        self.assertEqual((self.summary["run_at"], self.summary["window"]), (NOW, {"from_ts": ts(NOW) - 86400, "to_ts": ts(NOW)}))

    def test_the_summary_sections_are_these(self):
        self.apply({}, {})

        expected = {
            "digest", "run_at", "window", "report_only", "limited", "waiting", "good_to_know", "waiting_on_others", "handled",
            "resolved", "reading", "counts", "blind_spots", "post",
        }
        self.assertEqual(set(self.summary), expected)


class CountsAndPostTest(LifecycleCase):
    def test_counts_cover_each_section(self):
        old = at("2026-10-09T09:00:00Z")
        stored = state_of(
            dm_a=make_unit(status="waiting"),
            thread_b=make_unit(kind="thread", channel=CHANNEL_B, status="promise", first_seen=NOW),
            thread_e=make_unit(kind="thread", channel=CHANNEL_E, status="waiting"),
        )
        units = {
            DM_A: feature_unit(messages=[msg(PEER, old)]),
            THREAD_B: feature_unit("thread", CHANNEL_B, "#b", messages=[msg(OWNER, ASKED)], unanswered_from=None),
            THREAD_C: feature_unit("thread", CHANNEL_C, "#c", messages=[msg(OWNER, ASKED)], unanswered_from=None),
            THREAD_D: feature_unit("thread", CHANNEL_D, "#d"),
            THREAD_E: feature_unit("thread", CHANNEL_E, "#e", owner_answered=True, unanswered_from=None),
        }
        entries = {
            DM_A: entry(),
            THREAD_B: entry("promise"),
            THREAD_C: entry("you're waiting on"),
            THREAD_D: entry("team ask"),
            THREAD_E: entry("already handled"),
        }
        self.apply(units, entries, stored)

        self.assertEqual(self.summary["counts"], {"waiting": 2, "late": 1, "new": 2, "resolved": 1, "waiting_on_others": 1})

    def test_the_post_flag_is_true_when_a_unit_is_waiting(self):
        self.apply({DM_A: feature_unit()}, {DM_A: entry()}, state_of(dm_a=make_unit()))

        self.assertIs(self.summary["post"], True)

    def test_the_post_flag_is_true_when_a_unit_is_new(self):
        self.apply({DM_A: feature_unit()}, {DM_A: entry("team ask")})

        self.assertIs(self.summary["post"], True)

    def test_the_post_flag_is_true_when_a_unit_is_resolved(self):
        self.apply({DM_A: feature_unit(owner_answered=True, unanswered_from=None)}, {DM_A: entry("already handled")}, state_of(dm_a=make_unit()))

        self.assertIs(self.summary["post"], True)

    def test_the_post_flag_is_false_when_nothing_is_waiting_new_or_resolved(self):
        stored = state_of(dm_a=make_unit(status="team_ask", runs_waiting=0))
        self.apply({DM_A: feature_unit()}, {DM_A: entry("team ask")}, stored)

        self.assertIs(self.summary["post"], False)

    def test_the_post_flag_is_false_for_a_new_unit_already_handled(self):
        self.apply({DM_A: feature_unit(owner_answered=True, unanswered_from=None)}, {DM_A: entry("already handled")})

        self.assertIs(self.summary["post"], False)

    def test_the_post_flag_is_false_on_an_empty_run(self):
        self.apply({}, {})

        self.assertIs(self.summary["post"], False)

    def test_a_new_handled_unit_is_not_counted_as_new(self):
        self.apply({DM_A: feature_unit(owner_answered=True, unanswered_from=None)}, {DM_A: entry("already handled")})

        self.assertEqual(self.summary["counts"]["new"], 0)


class ReportOnlyTest(LifecycleCase):
    def report(self):
        stored = state_of(dm_a=make_unit(status="waiting"))
        self.stored = copy.deepcopy(stored)
        units = {DM_A: feature_unit(owner_answered=True, unanswered_from=None), THREAD_B: feature_unit("thread", CHANNEL_B, "#ops")}
        self.apply(units, {DM_A: entry("already handled"), THREAD_B: entry()}, stored, window=make_window(explicit=True))

    def test_a_report_only_run_leaves_the_state_as_it_was(self):
        self.report()

        self.assertEqual(self.state, self.stored)

    def test_a_report_only_run_still_builds_the_summary(self):
        self.report()

        self.assertEqual((self.summary["resolved"], self.keys("waiting"), self.summary["report_only"]), ([DM_A], [THREAD_B], True))

    def test_a_report_only_run_still_builds_the_record(self):
        self.report()

        self.assertEqual((self.record["resolved"], self.record["window"]["explicit"]), ([DM_A], True))

    def test_a_report_only_run_does_not_alias_the_stored_state(self):
        self.report()
        self.state["units"][DM_A]["title"] = "Changed"

        self.assertNotEqual(self.stored["units"][DM_A]["title"], "Changed")


class NoMessageTextTest(LifecycleCase):
    def run_with_text(self):
        stored = state_of(dm_a=make_unit(status="waiting"))
        messages = [msg(PEER, ASKED, text=SECRET_TEXT)]
        units = {DM_A: feature_unit(messages=messages), THREAD_B: feature_unit("thread", CHANNEL_B, "#ops", messages=[msg(PEER, ASKED, text=SECRET_TEXT)])}
        entries = {DM_A: entry(summary=SECRET_SUMMARY), THREAD_B: entry("team ask", summary=SECRET_SUMMARY)}
        self.apply(units, entries, stored, reading=[{"text": SECRET_READING, "cites": [DM_A]}, {"text": SECRET_READING, "cites": [THREAD_B]}])

    def test_the_state_holds_no_message_text_summary_or_reading(self):
        self.run_with_text()

        self.assertNotIn("SECRET", json.dumps(self.state))

    def test_the_record_holds_no_message_text_summary_or_reading(self):
        self.run_with_text()

        self.assertNotIn("SECRET", json.dumps(self.record))

    def test_the_record_holds_no_title(self):
        self.run_with_text()

        self.assertNotIn("Review the export plan", json.dumps(self.record))

    def test_the_record_holds_no_summary_or_reading_field(self):
        self.run_with_text()

        self.assertTrue({"summary", "reading", "text"}.isdisjoint(self.record))

    def test_the_summary_is_the_place_that_holds_the_checked_text(self):
        self.run_with_text()

        self.assertIn(SECRET_SUMMARY, json.dumps(self.summary))


class RecordTest(LifecycleCase):
    def record_run(self):
        stored = state_of(dm_a=make_unit(status="waiting"), thread_e=make_unit(kind="thread", channel=CHANNEL_E, last_ts="1000000000.000000"))
        units = {
            DM_A: feature_unit(owner_answered=True, unanswered_from=None),
            THREAD_B: feature_unit("thread", CHANNEL_B, "#b"),
            THREAD_C: feature_unit("thread", CHANNEL_C, "#c"),
        }
        self.apply(units, {DM_A: entry("already handled"), THREAD_B: entry(), THREAD_C: entry("team ask")}, stored, spots=[blind_spot()])

    def test_the_record_holds_the_unit_keys_per_section(self):
        self.record_run()

        found = {name: self.record[name] for name in ("waiting", "good_to_know", "waiting_on_others", "handled", "resolved", "new", "dropped")}
        expected = {
            "waiting": [THREAD_B],
            "good_to_know": [THREAD_C],
            "waiting_on_others": [],
            "handled": [DM_A],
            "resolved": [DM_A],
            "new": [THREAD_B, THREAD_C],
            "dropped": [THREAD_E],
        }
        self.assertEqual(found, expected)

    def test_the_record_counts_each_list(self):
        self.record_run()

        self.assertEqual(self.record["counts"], {"waiting": 1, "good_to_know": 1, "waiting_on_others": 0, "handled": 1, "resolved": 1, "new": 2, "late": 0, "dropped": 1})

    def test_the_record_holds_the_run_time_and_window(self):
        self.record_run()

        window = {"from_ts": ts(NOW) - 86400, "to_ts": ts(NOW), "explicit": False, "limited": None}
        self.assertEqual((self.record["run_at"], self.record["window"], self.record["digest"]), (NOW, window, "chat-recap"))

    def test_the_record_carries_the_record_schema(self):
        self.record_run()

        self.assertEqual(self.record["schema"], state.RECORD_SCHEMA_VERSION)

    def test_the_record_lists_the_late_keys(self):
        old = at("2026-10-09T09:00:00Z")
        self.apply({DM_A: feature_unit(messages=[msg(PEER, old)])}, {DM_A: entry()})

        self.assertEqual((self.record["late"], self.record["counts"]["late"]), ([DM_A], 1))


class InputsUntouchedTest(LifecycleCase):
    def test_the_inputs_are_not_changed(self):
        stored = state_of(dm_a=make_unit(status="waiting"))
        units = {DM_A: feature_unit(owner_answered=True, unanswered_from=None)}
        features_doc = make_features(units)
        judged = {"units": {DM_A: entry("already handled")}, "reading": READING}
        before = copy.deepcopy((stored, features_doc, judged))

        recap_lifecycle.apply(stored, features_doc, make_base(features_doc), judged, make_window(), PARIS, HISTORY)

        self.assertEqual((stored, features_doc, judged), before)


def cli(*argv):
    parser = argparse.ArgumentParser()
    recap_lifecycle.add_apply_arguments(parser)
    err = io.StringIO()
    message = ""
    with contextlib.redirect_stderr(err):
        try:
            code = recap_lifecycle.run_apply(parser.parse_args(list(argv)))
        except state.InputError as error:
            code, message = 2, str(error)
        except state.Rejected as error:
            code, message = 3, str(error)
        except SystemExit as error:
            code, message = error.code, err.getvalue()
    return code, message


class ApplyCommandTest(FileCase):
    def setUp(self):
        super().setUp()
        self.stored = state_of(dm_a=make_unit(status="waiting"))
        self.units = {DM_A: feature_unit(owner_answered=True, unanswered_from=None), THREAD_B: feature_unit("thread", CHANNEL_B, "#ops", owner_took_part=True)}
        self.entries = {DM_A: entry("already handled"), THREAD_B: entry()}

    def prepare(self, stored=None, features=None, judgment=None, window=None, base=None):
        features_doc = make_features(self.units) if features is None else features
        self.write("state.json", self.stored if stored is None else stored)
        self.write("features.json", features_doc)
        self.write("base.json", make_base(features_doc) if base is None else base)
        self.write("judgment.json", {"units": self.entries, "reading": READING} if judgment is None else judgment)
        self.write("window.json", make_window() if window is None else window)

    def apply(self, *flags, tz=TZ):
        return cli(
            "--state", self.path("state.json"), "--features", self.path("features.json"), "--base", self.path("base.json"),
            "--judgment", self.path("judgment.json"), "--window", self.path("window.json"), "--tz", tz, "--out", self.path("next.json"),
            "--summary", self.path("summary.json"), "--record", self.path("record.json"), *flags,
        )

    def test_recap_main_runs_apply(self):
        self.prepare()
        code = recap.main([
            "apply", "--state", self.path("state.json"), "--features", self.path("features.json"), "--base", self.path("base.json"),
            "--judgment", self.path("judgment.json"), "--window", self.path("window.json"), "--tz", TZ, "--out", self.path("next.json"),
            "--summary", self.path("summary.json"), "--record", self.path("record.json"),
        ])

        self.assertEqual((code, os.path.exists(self.path("record.json"))), (0, True))

    def test_a_run_exits_0_and_writes_the_three_files(self):
        self.prepare()

        self.assertEqual(self.apply(), (0, ""))
        self.assertEqual(self.read("next.json")["run"]["at"], NOW)
        self.assertEqual(self.read("summary.json")["resolved"], [DM_A])
        self.assertEqual(self.read("record.json")["resolved"], [DM_A])

    def test_the_written_files_are_canonical_json(self):
        self.prepare()
        self.apply()

        for name in ("next.json", "summary.json", "record.json"):
            self.assert_canonical(name)

    def test_the_written_state_passes_the_state_check(self):
        self.prepare()
        self.apply()

        self.assertIsNone(recap_state.check_state(self.read("next.json")))

    def test_the_default_thresholds_are_3_working_days_and_14_days(self):
        parser = argparse.ArgumentParser()
        recap_lifecycle.add_apply_arguments(parser)
        required = ("--state", "a", "--features", "b", "--base", "c", "--judgment", "d", "--window", "e", "--tz", "f", "--out", "g", "--summary", "h", "--record", "i")

        args = parser.parse_args(list(required))

        self.assertEqual((args.late_after_working_days, args.drop_after_days), (3, 14))

    def test_the_late_threshold_flag_drives_the_late_age(self):
        self.units = {DM_A: feature_unit(messages=[msg(PEER, at("2026-10-14T09:00:00Z"))])}
        self.entries = {DM_A: entry()}
        self.prepare()
        self.apply("--late-after-working-days", "1")

        self.assertEqual(self.read("next.json")["units"][DM_A]["late"], 2)

    def test_the_late_threshold_defaults_to_3(self):
        self.units = {DM_A: feature_unit(messages=[msg(PEER, at("2026-10-14T09:00:00Z"))])}
        self.entries = {DM_A: entry()}
        self.prepare()
        self.apply()

        self.assertIsNone(self.read("next.json")["units"][DM_A]["late"])

    def test_the_drop_flag_drives_the_drop(self):
        self.stored = state_of(dm_a=make_unit(last_ts=f"{ts(NOW) - 3 * 86400}.000000"))
        self.units, self.entries = {}, {}
        self.prepare(judgment={"units": {}, "reading": []})
        self.apply("--drop-after-days", "2")

        self.assertEqual(self.read("next.json")["units"], {})

    def test_a_drop_flag_below_1_is_a_usage_error(self):
        self.prepare()

        self.assertEqual(self.apply("--drop-after-days", "0")[0], 2)

    def test_a_drop_flag_above_a_year_is_a_usage_error(self):
        self.prepare()

        self.assertEqual(self.apply("--drop-after-days", "366")[0], 2)

    def test_a_drop_flag_of_a_year_is_accepted(self):
        self.prepare()

        self.assertEqual(self.apply("--drop-after-days", "365")[0], 0)

    def test_a_late_flag_that_is_not_a_number_is_a_usage_error(self):
        self.prepare()

        self.assertEqual(self.apply("--late-after-working-days", "soon")[0], 2)

    def test_a_missing_flag_is_a_usage_error(self):
        self.assertEqual(cli("--state", self.path("state.json"))[0], 2)

    def test_a_report_only_run_writes_the_stored_state_unchanged(self):
        self.prepare(window=make_window(explicit=True))
        self.apply()

        with open(self.path("state.json"), "rb") as stored, open(self.path("next.json"), "rb") as written:
            self.assertEqual(written.read(), stored.read())

    def test_a_report_only_run_still_writes_the_summary_and_the_record(self):
        self.prepare(window=make_window(explicit=True))
        self.apply()

        self.assertEqual((self.read("summary.json")["resolved"], self.read("record.json")["resolved"]), ([DM_A], [DM_A]))

    def test_a_missing_state_file_exits_2(self):
        self.prepare()
        code, message = cli(
            "--state", self.path("absent.json"), "--features", self.path("features.json"), "--base", self.path("base.json"),
            "--judgment", self.path("judgment.json"), "--window", self.path("window.json"), "--tz", TZ, "--out", self.path("next.json"),
            "--summary", self.path("summary.json"), "--record", self.path("record.json"),
        )

        self.assertEqual(code, 2)
        self.assertIn("state: cannot read", message)

    def test_an_unknown_time_zone_exits_2(self):
        self.prepare()

        self.assertEqual(self.apply(tz="Nowhere/Land")[0], 2)

    def test_features_without_their_facts_exit_2_with_the_key_path(self):
        features_doc = make_features(self.units)
        del features_doc["units"][DM_A]["facts"]
        self.prepare(features=features_doc)

        code, message = self.apply()

        self.assertEqual(code, 2)
        self.assertEqual(message, f"features: missing key units.{DM_A}.facts")

    def test_a_unit_without_a_message_exits_2(self):
        features_doc = make_features(self.units)
        features_doc["units"][DM_A]["messages"] = []
        self.prepare(features=features_doc)

        code, message = self.apply()

        self.assertEqual((code, message), (2, f"features: units.{DM_A}.messages: expected at least one message"))

    def test_a_base_without_participants_exits_2(self):
        base = make_base(make_features(self.units))
        del base["units"][DM_A]["participants"]
        self.prepare(base=base)

        self.assertEqual(self.apply()[0], 2)

    def test_a_state_that_fails_its_check_exits_3(self):
        self.prepare(stored={**self.stored, "schema": 2})

        code, message = self.apply()

        self.assertEqual((code, message), (3, "state: expected schema 1 at schema"))

    def test_a_window_that_ends_before_the_stored_run_exits_3(self):
        self.prepare(window=make_window("2026-10-14T07:45:00Z"))

        code, message = self.apply()

        self.assertEqual(code, 3)
        self.assertIn("is before the state run.at", message)

    def test_a_judgment_missing_a_unit_exits_3_with_the_key_path(self):
        self.prepare(judgment={"units": {DM_A: entry("already handled")}, "reading": READING})

        code, message = self.apply()

        self.assertEqual((code, message), (3, f"judgment: units.{THREAD_B}: missing, every unit of the features needs one entry"))

    def test_a_judgment_with_an_unknown_unit_exits_3(self):
        self.prepare(judgment={"units": {**self.entries, "dm-X": entry()}, "reading": READING})

        code, message = self.apply()

        self.assertEqual((code, message), (3, "judgment: units.dm-X: not a unit of the features"))

    def test_a_judgment_with_an_unknown_kind_exits_3_with_the_key_path(self):
        self.prepare(judgment={"units": {**self.entries, DM_A: entry("urgent")}, "reading": READING})

        code, message = self.apply()

        self.assertEqual(code, 3)
        self.assertRegex(message, rf"^judgment: units\.{DM_A}\.kind: expected one of ")

    def test_a_judgment_with_a_due_that_has_no_offset_exits_3(self):
        self.prepare(judgment={"units": {**self.entries, THREAD_B: entry("promise", due="2026-10-16T14:00:00")}, "reading": READING})

        self.assertEqual(self.apply()[0], 3)

    def test_a_judgment_with_a_kind_the_facts_forbid_exits_3_with_the_key_path(self):
        self.prepare(judgment={"units": {**self.entries, DM_A: entry("promise")}, "reading": READING})

        code, message = self.apply()

        self.assertEqual(code, 3)
        self.assertRegex(message, rf"^judgment: units\.{DM_A}\.kind: promise is not allowed for this unit, the facts allow ")

    def test_a_judgment_with_a_summary_of_two_sentences_exits_3(self):
        summary = "Peer asks for a review. Today it is urgent"
        self.prepare(judgment={"units": {**self.entries, THREAD_B: entry(summary=summary)}, "reading": READING})

        self.assertEqual(self.apply(), (3, f"judgment: units.{THREAD_B}.summary: must be one sentence"))

    def test_a_judgment_title_holding_an_author_id_exits_3(self):
        self.prepare(judgment={"units": {**self.entries, THREAD_B: entry(title=f"Reply to {PEER}")}, "reading": READING})

        self.assertEqual(self.apply(), (3, f"judgment: units.{THREAD_B}.title: must not hold a chat author id"))

    def test_a_judgment_with_a_promise_due_in_year_9999_exits_3(self):
        self.units[THREAD_B] = feature_unit("thread", CHANNEL_B, "#ops", messages=[msg(OWNER, ASKED)], unanswered_from=None)
        self.prepare(judgment={"units": {**self.entries, THREAD_B: entry("promise", due="9999-12-31T23:59:59-12:00")}, "reading": READING})

        self.assertEqual(self.apply(), (3, f"judgment: units.{THREAD_B}.due: must lie within 400 days of the window end"))

    def test_a_judgment_with_a_reading_of_5_bullets_exits_3(self):
        reading = [{"text": f"Point {number}", "cites": [DM_A]} for number in range(5)]
        self.prepare(judgment={"units": self.entries, "reading": reading})

        self.assertEqual(self.apply(), (3, "judgment: reading: expected at most 4 entries, got 5"))

    def test_a_judgment_with_no_reading_bullet_passes(self):
        self.prepare(judgment={"units": self.entries, "reading": []})

        self.assertEqual(self.apply(), (0, ""))

    def test_features_without_a_window_exit_2_with_the_key_path(self):
        features_doc = make_features(self.units)
        del features_doc["window"]
        self.prepare(features=features_doc)

        self.assertEqual(self.apply(), (2, "features: missing key window"))

    def test_a_judgment_title_over_8_words_exits_3(self):
        title = "one two three four five six seven eight nine"
        self.prepare(judgment={"units": {**self.entries, DM_A: entry("already handled", title=title)}, "reading": READING})

        self.assertEqual(self.apply()[0], 3)

    def test_a_judgment_that_is_not_json_exits_3(self):
        self.prepare()
        with open(self.path("judgment.json"), "w", encoding="utf-8") as handle:
            handle.write("{")

        self.assertEqual(self.apply()[0], 3)

    def test_a_missing_judgment_file_exits_2(self):
        self.prepare()
        code, _ = cli(
            "--state", self.path("state.json"), "--features", self.path("features.json"), "--base", self.path("base.json"),
            "--judgment", self.path("absent.json"), "--window", self.path("window.json"), "--tz", TZ, "--out", self.path("next.json"),
            "--summary", self.path("summary.json"), "--record", self.path("record.json"),
        )

        self.assertEqual(code, 2)

    def test_a_rejected_run_writes_nothing(self):
        self.prepare(judgment={"units": {DM_A: entry("already handled")}, "reading": READING})
        self.apply()

        self.assertEqual([name for name in ("next.json", "summary.json", "record.json") if self.exists(name)], [])

    def test_a_blind_spot_key_that_is_not_a_key_exits_2(self):
        self.prepare(features=make_features(self.units, spots=[blind_spot(key="bad key!")]))

        self.assertEqual(self.apply()[0], 2)

    def test_a_next_state_that_fails_its_check_exits_3(self):
        self.units = {DM_A: feature_unit("thread", owner_took_part=True)}
        self.entries = {DM_A: entry()}
        self.prepare()

        code, message = self.apply()

        self.assertEqual(code, 3)
        self.assertTrue(message.startswith("next state: "))

    def exists(self, name):
        try:
            self.read(name)
        except FileNotFoundError:
            return False
        return True


if __name__ == "__main__":
    unittest.main()
