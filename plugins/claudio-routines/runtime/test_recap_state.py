import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import recap
import recap_state
import recap_window
import state
from support import ts

HERE = os.path.dirname(os.path.abspath(__file__))
TZ = "Europe/Paris"
PARIS = ZoneInfo(TZ)
LOS_ANGELES = ZoneInfo("America/Los_Angeles")
PREVIOUS = "2026-10-15T07:45:00Z"
NOW = "2026-10-16T07:45:00Z"
CHANNEL_A = "CHAN" + "1" * 6
CHANNEL_B = "CHAN" + "2" * 6
ROOT_TS = "1791990000.000100"
LAST_TS = "1791990730.002679"
DM_A = f"dm-{CHANNEL_A}"
THREAD_B = f"thread-{CHANNEL_B}-{ROOT_TS}"
LONG = "x" * (state.LABEL_CAP + 1)
REJECTION = r"^(?:expected .+ at |missing key |unexpected key |){path}(?:: |$)"


def make_unit(**fields):
    unit = {
        "kind": "dm",
        "channel": CHANNEL_A,
        "title": "Review the export plan",
        "first_seen": "2026-10-14T07:45:00Z",
        "last_ts": LAST_TS,
        "status": "waiting",
        "runs_waiting": 2,
        "late": None,
        "due": None,
    }
    return {**unit, **fields}


def make_state(at=PREVIOUS, units=None, blind_spots=None, **run):
    document = {
        "schema": 1,
        "digest": "chat-recap",
        "run": {"at": at, "previous_at": "2026-10-14T07:45:00Z", "window": {"from_ts": ts("2026-10-14T07:45:00Z"), "to_ts": ts(PREVIOUS)}},
        "units": {
            DM_A: make_unit(),
            THREAD_B: make_unit(kind="thread", channel=CHANNEL_B, status="promise", late=1, due="2026-10-16T12:00:00Z"),
        }
        if units is None
        else units,
        "blind_spots": [{"key": "search-mentions", "gap": "search cut after 10 pages", "runs": 1}] if blind_spots is None else blind_spots,
    }
    document["run"].update(run)
    return document


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = recap.main(list(argv))
        except SystemExit as error:
            code = error.code
    return code, out.getvalue(), err.getvalue()


class FileCase(unittest.TestCase):
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

    def assert_canonical(self, name):
        with open(self.path(name), "rb") as handle:
            raw = handle.read()
        self.assertEqual(raw, state.dump(json.loads(raw)))

    def window_of(self, state_path, now=NOW, *flags, tz=TZ, lookback="3"):
        lookback_flags = [] if lookback is None else ["--lookback-working-days", lookback]
        code, _, err = run_cli("window", "--state", state_path, "--now", now, "--tz", tz, "--out", self.path("window.json"), *lookback_flags, *flags)
        return code, err

    def window(self, document, now=NOW, *flags, tz=TZ, lookback="3"):
        return self.window_of(self.write("state.json", document), now, *flags, tz=tz, lookback=lookback)


class CheckStateCase(unittest.TestCase):
    def message(self, document):
        with self.assertRaises(state.Rejected) as caught:
            recap_state.check_state(document)
        return str(caught.exception)

    def rejects(self, path, mutate):
        document = make_state()
        mutate(document)
        self.assertRegex(self.message(document), REJECTION.format(path=re.escape(path)))

    def rejects_unit(self, field, **fields):
        self.rejects(f"units.{DM_A}.{field}", lambda document: document["units"][DM_A].update(fields))


class AcceptedStateTest(CheckStateCase):
    def test_accepts_a_full_state(self):
        self.assertIsNone(recap_state.check_state(make_state()))

    def test_accepts_the_baseline_state(self):
        self.assertIsNone(recap_state.check_state(recap_state.initial_state("chat-recap")))

    def test_accepts_every_status(self):
        units = {f"dm-CHAN{index}": make_unit(channel=f"CHAN{index}", status=status) for index, status in enumerate(recap_state.STATUSES)}
        self.assertIsNone(recap_state.check_state(make_state(units=units)))

    def test_accepts_every_unit_kind_under_its_key_prefix(self):
        direct = {recap_state.dm_key(f"D{index}"): make_unit(channel=f"D{index}", kind=kind) for index, kind in enumerate(recap_state.DM_KINDS)}
        threads = {recap_state.thread_key(f"T{index}", ROOT_TS): make_unit(channel=f"T{index}", kind=kind) for index, kind in enumerate(recap_state.THREAD_KINDS)}
        self.assertIsNone(recap_state.check_state(make_state(units={**direct, **threads})))

    def test_accepts_a_digest_name_with_a_space(self):
        document = make_state()
        document["digest"] = "Chat recap"
        self.assertIsNone(recap_state.check_state(document))

    def test_accepts_a_blind_spot_key_with_a_channel_and_a_ts(self):
        self.assertIsNone(recap_state.check_state(make_state(blind_spots=[{"key": f"{CHANNEL_A}:{ROOT_TS}", "gap": "not readable", "runs": 1}])))

    def test_accepts_a_title_of_exactly_8_words(self):
        self.assertIsNone(recap_state.check_state(make_state(units={DM_A: make_unit(title="one two three four five six seven eight")})))

    def test_accepts_a_state_without_units_or_blind_spots(self):
        self.assertIsNone(recap_state.check_state(make_state(units={}, blind_spots=[])))


class RootRejectionTest(CheckStateCase):
    def test_rejects_a_state_that_is_not_an_object(self):
        self.assertEqual(self.message([]), "expected an object at <root>")

    def test_rejects_another_schema_number(self):
        self.rejects("schema", lambda document: document.update(schema=2))

    def test_rejects_a_schema_that_is_a_boolean(self):
        self.rejects("schema", lambda document: document.update(schema=True))

    def test_rejects_a_schema_name_of_another_engine(self):
        self.rejects("schema", lambda document: document.update(schema="tribe-1"))

    def test_rejects_an_empty_digest(self):
        self.rejects("digest", lambda document: document.update(digest=""))

    def test_rejects_a_digest_that_is_a_number(self):
        self.rejects("digest", lambda document: document.update(digest=3))

    def test_rejects_a_digest_over_300_characters(self):
        self.rejects("digest", lambda document: document.update(digest=LONG))

    def test_rejects_a_digest_with_a_control_character(self):
        self.rejects("digest", lambda document: document.update(digest="chat\nrecap"))

    def test_rejects_units_that_are_not_an_object(self):
        self.rejects("units", lambda document: document.update(units=[]))

    def test_rejects_blind_spots_that_are_not_a_list(self):
        self.rejects("blind_spots", lambda document: document.update(blind_spots={}))

    def test_rejects_a_run_that_is_not_an_object(self):
        self.rejects("run", lambda document: document.update(run=[]))


class RunRejectionTest(CheckStateCase):
    def test_rejects_a_run_time_with_an_offset(self):
        self.rejects("run.at", lambda document: document["run"].update(at="2026-10-15T09:45:00+02:00"))

    def test_rejects_a_run_time_that_is_not_a_date(self):
        self.rejects("run.at", lambda document: document["run"].update(at="yesterday"))

    def test_rejects_a_run_time_that_is_a_number(self):
        self.rejects("run.at", lambda document: document["run"].update(at=1791990730))

    def test_rejects_a_previous_run_time_that_is_not_utc(self):
        self.rejects("run.previous_at", lambda document: document["run"].update(previous_at="2026-10-14"))

    def test_rejects_a_window_that_ends_before_it_starts(self):
        self.rejects("run.window", lambda document: document["run"].update(window={"from_ts": 20, "to_ts": 10}))

    def test_rejects_a_window_bound_that_is_a_boolean(self):
        self.rejects("run.window.from_ts", lambda document: document["run"]["window"].update(from_ts=True))

    def test_rejects_a_window_bound_that_is_text(self):
        self.rejects("run.window.to_ts", lambda document: document["run"]["window"].update(to_ts="10"))

    def test_rejects_a_window_that_is_not_an_object(self):
        self.rejects("run.window", lambda document: document["run"].update(window=[1, 2]))


class UnitKeyRejectionTest(CheckStateCase):
    def test_rejects_a_key_with_capitals_outside_the_prefixes(self):
        key = f"Chat-{CHANNEL_A}"
        self.rejects(f"units.{key}", lambda document: document["units"].update({key: make_unit()}))

    def test_rejects_a_direct_key_without_a_channel(self):
        self.rejects("units.dm-", lambda document: document["units"].update({"dm-": make_unit()}))

    def test_rejects_a_thread_key_without_a_root_ts(self):
        key = f"thread-{CHANNEL_B}"
        self.rejects(f"units.{key}", lambda document: document["units"].update({key: make_unit()}))

    def test_rejects_a_thread_key_whose_root_ts_has_no_dot(self):
        key = f"thread-{CHANNEL_B}-1791990000"
        self.rejects(f"units.{key}", lambda document: document["units"].update({key: make_unit(channel=CHANNEL_B)}))

    def test_rejects_a_key_whose_channel_differs_from_the_unit_channel(self):
        self.rejects(f"units.{DM_A}.channel", lambda document: document["units"][DM_A].update(channel=CHANNEL_B))

    def test_names_the_channel_the_key_holds(self):
        document = make_state()
        document["units"][DM_A]["channel"] = CHANNEL_B
        self.assertEqual(self.message(document), f"expected channel {CHANNEL_A} of the unit key at units.{DM_A}.channel")

    def test_rejects_a_direct_key_with_a_channel_over_32_characters(self):
        key = "dm-" + "A" * 33
        self.rejects(f"units.{key}", lambda document: document["units"].update({key: make_unit()}))

    def test_rejects_a_key_over_the_cap_with_a_capped_key_path(self):
        key = "dm_" + "A" * 200
        message = self.message(make_state(units={key: make_unit()}))
        self.assertEqual(message, f"expected a unit key dm-<channel> or thread-<channel>-<root ts> at units.{key[:recap_state.KEY_CAP]}")

    def test_reports_a_malformed_key_before_a_field_error_so_the_key_is_never_echoed_raw(self):
        message = self.message(make_state(units={"dm-A\nB": make_unit(status="open")}))
        self.assertEqual(message, "expected a unit key dm-<channel> or thread-<channel>-<root ts> at units.dm-A B")

    def test_rejects_a_unit_that_is_not_an_object(self):
        self.rejects(f"units.{DM_A}", lambda document: document["units"].update({DM_A: "waiting"}))


class KindPrefixRejectionTest(CheckStateCase):
    def test_rejects_a_thread_kind_under_a_direct_key(self):
        self.rejects_unit("kind", kind="thread")

    def test_rejects_a_mention_kind_under_a_direct_key(self):
        self.rejects_unit("kind", kind="mention")

    def test_rejects_a_direct_kind_under_a_thread_key(self):
        self.rejects(f"units.{THREAD_B}.kind", lambda document: document["units"][THREAD_B].update(kind="dm"))

    def test_rejects_a_group_direct_kind_under_a_thread_key(self):
        self.rejects(f"units.{THREAD_B}.kind", lambda document: document["units"][THREAD_B].update(kind="group_dm"))

    def test_names_the_kinds_of_the_key_prefix(self):
        document = make_state()
        document["units"][DM_A]["kind"] = "group"
        self.assertEqual(self.message(document), f"expected one of dm, group_dm under a dm- key at units.{DM_A}.kind")


class UnitFieldRejectionTest(CheckStateCase):
    def test_rejects_an_unknown_kind(self):
        self.rejects_unit("kind", kind="channel")

    def test_rejects_a_kind_that_is_not_text(self):
        self.rejects_unit("kind", kind=1)

    def test_rejects_an_empty_channel(self):
        self.rejects(f"units.{DM_A}.channel", lambda document: document["units"][DM_A].update(channel=""))

    def test_rejects_an_empty_title(self):
        self.rejects_unit("title", title="")

    def test_rejects_a_title_of_spaces(self):
        self.rejects_unit("title", title="   ")

    def test_rejects_a_title_of_9_words(self):
        self.rejects_unit("title", title="one two three four five six seven eight nine")

    def test_names_the_title_bounds(self):
        document = make_state()
        document["units"][DM_A]["title"] = "one two three four five six seven eight nine"
        self.assertIn("at most 8 words", self.message(document))

    def test_rejects_a_title_over_300_characters(self):
        self.rejects_unit("title", title=LONG)

    def test_rejects_a_title_with_a_control_character(self):
        self.rejects_unit("title", title="Review\nthe plan")

    def test_rejects_a_title_that_is_not_text(self):
        self.rejects_unit("title", title=["Review"])

    def test_rejects_a_first_seen_that_is_not_utc(self):
        self.rejects_unit("first_seen", first_seen="2026-10-14T09:45:00+02:00")

    def test_rejects_a_last_ts_that_is_a_number(self):
        self.rejects_unit("last_ts", last_ts=1791990730.002679)

    def test_rejects_a_last_ts_without_a_dot(self):
        self.rejects_unit("last_ts", last_ts="1791990730")

    def test_rejects_a_last_ts_with_text(self):
        self.rejects_unit("last_ts", last_ts="yesterday.1")

    def test_rejects_a_status_outside_the_fixed_set(self):
        self.rejects_unit("status", status="open")

    def test_rejects_a_judged_kind_as_a_status(self):
        self.rejects_unit("status", status="waiting on you")

    def test_rejects_the_noise_kind_as_a_status(self):
        self.rejects_unit("status", status="noise")

    def test_rejects_a_negative_run_count(self):
        self.rejects_unit("runs_waiting", runs_waiting=-1)

    def test_rejects_a_run_count_that_is_a_boolean(self):
        self.rejects_unit("runs_waiting", runs_waiting=True)

    def test_rejects_a_run_count_that_is_text(self):
        self.rejects_unit("runs_waiting", runs_waiting="2")

    def test_rejects_a_late_age_that_is_negative(self):
        self.rejects_unit("late", late=-1)

    def test_rejects_a_late_flag_that_is_a_boolean(self):
        self.rejects_unit("late", late=True)

    def test_rejects_a_due_time_with_an_offset(self):
        self.rejects_unit("due", due="2026-10-16T14:00:00+02:00")

    def test_rejects_a_due_time_that_is_text(self):
        self.rejects_unit("due", due="tomorrow")


class UnknownKeyRejectionTest(CheckStateCase):
    def test_rejects_an_unknown_top_level_key(self):
        self.rejects("extra", lambda document: document.update(extra=1))

    def test_rejects_an_unknown_run_key(self):
        self.rejects("run.extra", lambda document: document["run"].update(extra=1))

    def test_rejects_an_unknown_window_key(self):
        self.rejects("run.window.extra", lambda document: document["run"]["window"].update(extra=1))

    def test_rejects_an_unknown_blind_spot_key(self):
        self.rejects("blind_spots[0].extra", lambda document: document["blind_spots"][0].update(extra=1))

    def test_rejects_an_unknown_key_in_a_thread_unit(self):
        self.rejects(f"units.{THREAD_B}.extra", lambda document: document["units"][THREAD_B].update(extra=1))

    def test_names_what_the_state_holds(self):
        document = make_state()
        document["extra"] = 1
        self.assertEqual(self.message(document), "unexpected key extra: the state holds ids, times, titles and counts only")


class MessageTextRejectionTest(CheckStateCase):
    def test_rejects_a_text_field_in_a_unit(self):
        self.rejects(f"units.{DM_A}.text", lambda document: document["units"][DM_A].update(text="can you review the plan"))

    def test_rejects_a_summary_field_in_a_unit(self):
        self.rejects(f"units.{DM_A}.summary", lambda document: document["units"][DM_A].update(summary="asks for a review"))

    def test_rejects_a_permalink_field_in_a_unit(self):
        self.rejects(f"units.{DM_A}.permalink", lambda document: document["units"][DM_A].update(permalink="https://example.test/p1"))

    def test_names_what_a_unit_holds(self):
        document = make_state()
        document["units"][DM_A]["text"] = "hello"
        self.assertEqual(self.message(document), f"unexpected key units.{DM_A}.text: the state holds ids, times, titles and counts only")

    def test_caps_an_unknown_key_in_the_key_path(self):
        document = make_state()
        document["units"][DM_A]["k" * 200] = 1
        self.assertNotIn("k" * 100, self.message(document))


class BlindSpotRejectionTest(CheckStateCase):
    def test_rejects_a_run_count_that_is_text(self):
        self.rejects("blind_spots[0].runs", lambda document: document["blind_spots"][0].update(runs="1"))

    def test_rejects_a_gap_over_300_characters(self):
        self.rejects("blind_spots[0].gap", lambda document: document["blind_spots"][0].update(gap=LONG))

    def test_rejects_an_empty_blind_spot_key(self):
        self.rejects("blind_spots[0].key", lambda document: document["blind_spots"][0].update(key=""))

    def test_rejects_a_blind_spot_key_with_a_space(self):
        self.rejects("blind_spots[0].key", lambda document: document["blind_spots"][0].update(key="search mentions"))

    def test_rejects_a_blind_spot_key_over_80_characters(self):
        self.rejects("blind_spots[0].key", lambda document: document["blind_spots"][0].update(key="k" * 81))

    def test_rejects_a_blind_spot_without_a_key(self):
        self.rejects("blind_spots[0].key", lambda document: document["blind_spots"][0].pop("key"))


class MissingKeyTest(CheckStateCase):
    pass


def missing_key_test(path):
    def test(self):
        document = make_state()
        parent = document
        names = path.split(".")
        for name in names[:-1]:
            parent = parent[name]
        del parent[names[-1]]
        self.assertEqual(self.message(document), "missing key " + path)

    return test


MISSING_KEYS = (
    "schema", "digest", "run", "units", "blind_spots",
    "run.at", "run.previous_at", "run.window",
    "run.window.from_ts", "run.window.to_ts",
    *(f"units.{DM_A}.{field}" for field in ("kind", "channel", "title", "first_seen", "last_ts", "status", "runs_waiting", "late", "due")),
)
for key_path in MISSING_KEYS:
    setattr(MissingKeyTest, "test_rejects_missing_" + re.sub(r"[^a-zA-Z0-9]", "_", key_path), missing_key_test(key_path))


class UnitKeyHelperTest(unittest.TestCase):
    def test_builds_a_direct_key(self):
        self.assertEqual(recap_state.dm_key(CHANNEL_A), DM_A)

    def test_builds_a_thread_key(self):
        self.assertEqual(recap_state.thread_key(CHANNEL_B, ROOT_TS), THREAD_B)

    def test_reads_the_channel_of_a_direct_key(self):
        self.assertEqual(recap_state.key_channel(DM_A), CHANNEL_A)

    def test_reads_the_channel_of_a_thread_key(self):
        self.assertEqual(recap_state.key_channel(THREAD_B), CHANNEL_B)

    def test_reads_no_channel_from_another_shape(self):
        self.assertEqual([recap_state.key_channel(key) for key in ("", "dm", "dm-A-B", "thread-A", "thread-A-1", "mention-A")], [None] * 6)

    def test_counts_the_words_of_a_title(self):
        self.assertEqual(recap_state.word_count("  Review   the export plan "), 4)


class WorkingDaysBetweenTest(unittest.TestCase):
    def between(self, start, end):
        return recap_window.working_days_between(ts(start), ts(end), PARIS)

    def test_counts_no_day_within_the_same_day(self):
        self.assertEqual(self.between("2026-10-15T06:00:00Z", "2026-10-15T20:00:00Z"), 0)

    def test_counts_the_next_weekday(self):
        self.assertEqual(self.between("2026-10-15T07:45:00Z", "2026-10-16T07:45:00Z"), 1)

    def test_counts_monday_once_from_friday(self):
        self.assertEqual(self.between("2026-10-16T07:45:00Z", "2026-10-19T07:45:00Z"), 1)

    def test_counts_no_day_from_friday_to_saturday(self):
        self.assertEqual(self.between("2026-10-16T07:45:00Z", "2026-10-17T07:45:00Z"), 0)

    def test_counts_monday_from_saturday(self):
        self.assertEqual(self.between("2026-10-17T07:45:00Z", "2026-10-19T07:45:00Z"), 1)

    def test_counts_two_days_from_thursday_to_monday(self):
        self.assertEqual(self.between("2026-10-15T07:45:00Z", "2026-10-19T07:45:00Z"), 2)

    def test_counts_five_days_over_a_week(self):
        self.assertEqual(self.between("2026-10-12T07:45:00Z", "2026-10-19T07:45:00Z"), 5)

    def test_counts_no_day_when_the_end_is_before_the_start(self):
        self.assertEqual(self.between("2026-10-19T07:45:00Z", "2026-10-12T07:45:00Z"), 0)

    def test_counts_local_days_not_utc_days(self):
        self.assertEqual(self.between("2026-10-16T22:30:00Z", "2026-10-18T22:30:00Z"), 1)

    def test_counts_five_days_over_a_week_with_the_spring_change(self):
        self.assertEqual(self.between("2026-03-25T12:00:00Z", "2026-04-01T12:00:00Z"), 5)

    def test_counts_five_days_over_a_week_with_the_autumn_change(self):
        self.assertEqual(self.between("2026-10-21T12:00:00Z", "2026-10-28T12:00:00Z"), 5)

    def test_counts_monday_over_the_23_hour_day_of_the_spring_change(self):
        self.assertEqual(self.between("2026-03-27T22:30:00Z", "2026-03-29T22:30:00Z"), 1)

    def test_counts_monday_over_the_25_hour_day_of_the_autumn_change(self):
        self.assertEqual(self.between("2026-10-23T21:30:00Z", "2026-10-25T23:10:00Z"), 1)


class WorkingDaysBackTest(unittest.TestCase):
    def back(self, now, count=3, zone=PARIS):
        return recap_window.working_days_back(ts(now), count, zone)

    def test_goes_back_to_monday_midnight_from_thursday(self):
        self.assertEqual(self.back("2026-10-15T07:45:00Z"), ts("2026-10-11T22:00:00Z"))

    def test_skips_the_weekend_from_monday(self):
        self.assertEqual(self.back("2026-10-19T07:45:00Z"), ts("2026-10-13T22:00:00Z"))

    def test_goes_back_from_a_saturday_to_the_wednesday(self):
        self.assertEqual(self.back("2026-10-17T10:00:00Z"), ts("2026-10-13T22:00:00Z"))

    def test_goes_back_from_a_sunday_to_the_wednesday(self):
        self.assertEqual(self.back("2026-10-18T10:00:00Z"), ts("2026-10-13T22:00:00Z"))

    def test_goes_back_one_working_day_over_the_weekend(self):
        self.assertEqual(self.back("2026-10-19T07:45:00Z", 1), ts("2026-10-15T22:00:00Z"))

    def test_goes_back_one_working_day_midweek(self):
        self.assertEqual(self.back("2026-10-21T07:45:00Z", 1), ts("2026-10-19T22:00:00Z"))

    def test_reads_the_local_day_of_the_time(self):
        self.assertEqual(self.back("2026-10-19T22:30:00Z", 1), ts("2026-10-18T22:00:00Z"))

    def test_uses_the_zone_given(self):
        self.assertEqual(self.back("2026-10-19T07:45:00Z", 1, ZoneInfo("UTC")), ts("2026-10-16T00:00:00Z"))

    def test_uses_the_summer_offset_after_the_spring_change(self):
        self.assertEqual(self.back("2026-04-01T10:00:00Z", 2), ts("2026-03-29T22:00:00Z"))

    def test_uses_the_winter_offset_before_the_spring_change(self):
        self.assertEqual(self.back("2026-03-31T10:00:00Z", 2), ts("2026-03-26T23:00:00Z"))

    def test_uses_the_winter_offset_after_the_autumn_change(self):
        self.assertEqual(self.back("2026-10-28T10:00:00Z", 2), ts("2026-10-25T23:00:00Z"))

    def test_uses_the_summer_offset_before_the_autumn_change(self):
        self.assertEqual(self.back("2026-10-27T10:00:00Z", 2), ts("2026-10-22T22:00:00Z"))

    def test_returns_midnight_of_the_start_day_in_the_zone(self):
        local = datetime.fromtimestamp(self.back("2026-10-21T07:45:00Z", 1), PARIS)
        self.assertEqual((local.hour, local.minute, local.second, local.weekday()), (0, 0, 0, 1))

    def test_starts_on_the_working_day_before_the_day_of_the_time_on_every_weekday(self):
        days = [f"2026-10-{day}T10:00:00Z" for day in range(12, 19)]
        starts = [datetime.fromtimestamp(self.back(day), PARIS).date().isoformat() for day in days]
        self.assertEqual(starts, ["2026-10-07", "2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13", "2026-10-14", "2026-10-14"])

    def test_start_is_never_a_gap_on_any_weekday(self):
        days = [f"2026-10-{day}T10:00:00Z" for day in range(12, 19)]
        counts = [recap_window.working_days_between(self.back(day), ts(day), PARIS) for day in days]
        self.assertEqual(counts, [3, 3, 3, 3, 3, 2, 2])


class ZoneNearMidnightTest(FileCase):
    def test_between_reads_the_start_day_in_the_zone_given(self):
        self.assertEqual(recap_window.working_days_between(ts("2026-10-16T05:00:00Z"), ts("2026-10-17T20:00:00Z"), LOS_ANGELES), 1)

    def test_between_reads_the_end_day_in_the_zone_given(self):
        self.assertEqual(recap_window.working_days_between(ts("2026-10-16T20:00:00Z"), ts("2026-10-19T05:00:00Z"), LOS_ANGELES), 0)

    def test_back_reads_the_day_of_the_time_in_the_zone_given(self):
        self.assertEqual(recap_window.working_days_back(ts("2026-10-22T05:00:00Z"), 1, LOS_ANGELES), ts("2026-10-20T07:00:00Z"))

    def test_window_counts_the_gap_in_the_zone_given(self):
        self.window(make_state(at="2026-10-14T20:00:00Z"), "2026-10-19T05:00:00Z", tz="America/Los_Angeles", lookback="2")
        self.assertEqual(self.read("window.json")["limited"], None)

    def test_window_counts_the_same_gap_as_limited_in_another_zone(self):
        self.window(make_state(at="2026-10-14T20:00:00Z"), "2026-10-19T05:00:00Z", tz=TZ, lookback="2")
        self.assertEqual(self.read("window.json")["limited"], "gap")


class InitTest(FileCase):
    def init(self, digest="chat-recap"):
        return run_cli("init", "--digest", digest, "--out", self.path("state.json"))

    def test_writes_the_empty_baseline(self):
        self.init()
        self.assertEqual(self.read("state.json"), {
            "schema": 1,
            "digest": "chat-recap",
            "run": {"at": None, "previous_at": None, "window": None},
            "units": {},
            "blind_spots": [],
        })

    def test_exits_0(self):
        self.assertEqual(self.init()[0], 0)

    def test_baseline_passes_the_check(self):
        self.init()
        self.assertIsNone(recap_state.check_state(self.read("state.json")))

    def test_baseline_is_canonical_json(self):
        self.init()
        self.assert_canonical("state.json")

    def test_initial_state_holds_the_keys_of_the_design(self):
        self.assertEqual(sorted(recap_state.initial_state("x")), ["blind_spots", "digest", "run", "schema", "units"])

    def test_empty_digest_exits_3_naming_the_key(self):
        code, _, err = self.init(digest="")
        self.assertEqual((code, "digest" in err), (3, True))

    def test_empty_digest_writes_nothing(self):
        self.init(digest="")
        self.assertEqual(os.listdir(self.dir), [])

    def test_unwritable_out_exits_2_naming_the_path(self):
        out = self.path(os.path.join("absent", "state.json"))
        code, _, err = run_cli("init", "--digest", "chat-recap", "--out", out)
        self.assertEqual((code, out in err), (2, True))


class StateFileTest(FileCase):
    def test_loads_a_valid_state(self):
        self.assertEqual(recap_state.load(self.write("state.json", make_state())), make_state())

    def test_load_names_the_state_and_the_key_path_of_a_rejection(self):
        document = make_state()
        document["units"][DM_A]["status"] = "open"
        with self.assertRaises(state.Rejected) as caught:
            recap_state.load(self.write("state.json", document))
        self.assertTrue(str(caught.exception).startswith(f"state: expected one of {', '.join(recap_state.STATUSES)} at units.{DM_A}.status"))

    def test_load_rejects_a_missing_file_as_an_input_error(self):
        with self.assertRaises(state.InputError):
            recap_state.load(self.path("absent.json"))

    def test_write_stores_canonical_json(self):
        recap_state.write(self.path("state.json"), make_state())
        self.assert_canonical("state.json")

    def test_write_round_trips(self):
        recap_state.write(self.path("state.json"), make_state())
        self.assertEqual(self.read("state.json"), make_state())

    def test_write_of_an_invalid_state_leaves_the_file_unchanged(self):
        path = self.write("state.json", make_state())
        with open(path, "rb") as handle:
            before = handle.read()
        with self.assertRaises(state.Rejected):
            recap_state.write(path, make_state(units={"bad": make_unit()}))
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), before)


class WindowTest(FileCase):
    def run_window(self, at, now, lookback="3"):
        self.window(make_state(at=at), now, lookback=lookback)
        return self.read("window.json")

    def test_window_starts_at_the_run_time_of_the_state(self):
        self.assertEqual(self.run_window(PREVIOUS, NOW), {"from_ts": ts(PREVIOUS), "to_ts": ts(NOW), "limited": None, "explicit": False})

    def test_window_over_a_weekend_starts_at_the_run_time(self):
        window = self.run_window("2026-10-16T07:45:00Z", "2026-10-19T07:45:00Z")
        self.assertEqual((window["from_ts"], window["limited"]), (ts("2026-10-16T07:45:00Z"), None))

    def test_a_gap_of_exactly_the_working_days_is_not_limited(self):
        window = self.run_window("2026-10-14T07:45:00Z", "2026-10-19T07:45:00Z")
        self.assertEqual((window["from_ts"], window["limited"]), (ts("2026-10-14T07:45:00Z"), None))

    def test_baseline_state_reads_the_last_working_days_from_local_midnight(self):
        self.window(recap_state.initial_state("chat-recap"), "2026-10-19T07:45:00Z")
        self.assertEqual(self.read("window.json"), {"from_ts": ts("2026-10-13T22:00:00Z"), "to_ts": ts("2026-10-19T07:45:00Z"), "limited": "baseline", "explicit": False})

    def test_baseline_reads_one_working_day_back_over_a_weekend(self):
        self.window(recap_state.initial_state("chat-recap"), "2026-10-19T07:45:00Z", lookback="1")
        self.assertEqual(self.read("window.json")["from_ts"], ts("2026-10-15T22:00:00Z"))

    def test_a_gap_over_a_weekend_is_limited_to_the_last_working_days(self):
        window = self.run_window("2026-10-14T07:45:00Z", "2026-10-20T07:45:00Z")
        self.assertEqual(window, {"from_ts": ts("2026-10-14T22:00:00Z"), "to_ts": ts("2026-10-20T07:45:00Z"), "limited": "gap", "explicit": False})

    def test_a_gap_on_a_saturday_starts_on_the_wednesday(self):
        window = self.run_window("2026-10-07T07:45:00Z", "2026-10-17T10:00:00Z")
        self.assertEqual((window["from_ts"], window["limited"]), (ts("2026-10-13T22:00:00Z"), "gap"))

    def test_a_long_gap_starts_where_a_baseline_does(self):
        gap = self.run_window("2026-09-01T07:45:00Z", "2026-10-19T07:45:00Z")
        self.window(recap_state.initial_state("chat-recap"), "2026-10-19T07:45:00Z")
        baseline = self.read("window.json")
        self.assertEqual((gap["from_ts"], gap["limited"], baseline["limited"]), (baseline["from_ts"], "gap", "baseline"))

    def test_a_limited_window_starts_after_the_previous_run(self):
        window = self.run_window("2026-10-14T07:45:00Z", "2026-10-20T07:45:00Z")
        self.assertGreater(window["from_ts"], ts("2026-10-14T07:45:00Z"))

    def test_a_gap_over_the_spring_change_starts_at_the_summer_midnight(self):
        window = self.run_window("2026-03-23T08:00:00Z", "2026-04-01T10:00:00Z", lookback="2")
        self.assertEqual((window["from_ts"], window["limited"]), (ts("2026-03-29T22:00:00Z"), "gap"))

    def test_a_gap_over_the_autumn_change_starts_at_the_winter_midnight(self):
        window = self.run_window("2026-10-19T08:00:00Z", "2026-10-28T10:00:00Z", lookback="2")
        self.assertEqual((window["from_ts"], window["limited"]), (ts("2026-10-25T23:00:00Z"), "gap"))

    def test_a_gap_is_counted_in_the_given_zone(self):
        self.window(make_state(at="2026-10-14T07:45:00Z"), "2026-10-19T22:30:00Z")
        self.assertEqual(self.read("window.json")["limited"], "gap")

    def test_the_same_gap_is_not_limited_in_another_zone(self):
        self.window(make_state(at="2026-10-14T07:45:00Z"), "2026-10-19T22:30:00Z", tz="UTC")
        self.assertIsNone(self.read("window.json")["limited"])

    def test_since_makes_an_explicit_window_without_limit(self):
        self.window(make_state(), NOW, "--since", "2026-09-01T00:00:00Z")
        self.assertEqual(self.read("window.json"), {"from_ts": ts("2026-09-01T00:00:00Z"), "to_ts": ts(NOW), "limited": None, "explicit": True})

    def test_since_on_a_baseline_state_is_not_limited(self):
        self.window(recap_state.initial_state("chat-recap"), NOW, "--since", "2026-09-01T00:00:00Z")
        self.assertEqual(self.read("window.json")["limited"], None)

    def test_report_only_keeps_the_normal_start_and_marks_the_window_explicit(self):
        self.window(make_state(), NOW, "--report-only")
        window = self.read("window.json")
        self.assertEqual((window["from_ts"], window["explicit"]), (ts(PREVIOUS), True))

    def test_report_only_keeps_the_limit_of_a_baseline(self):
        self.window(recap_state.initial_state("chat-recap"), "2026-10-19T07:45:00Z", "--report-only")
        window = self.read("window.json")
        self.assertEqual((window["limited"], window["explicit"]), ("baseline", True))

    def test_window_file_is_canonical_json(self):
        self.window(make_state())
        self.assert_canonical("window.json")

    def test_window_exits_0(self):
        self.assertEqual(self.window(make_state())[0], 0)

    def test_window_holds_no_state_key(self):
        self.window(make_state())
        self.assertEqual(sorted(self.read("window.json")), ["explicit", "from_ts", "limited", "to_ts"])

    def test_a_lookback_of_365_days_is_accepted(self):
        self.assertEqual(self.window(make_state(), lookback="365")[0], 0)


class WindowExitCodeTest(FileCase):
    def test_now_before_the_run_time_exits_3(self):
        code, err = self.window(make_state(), "2026-10-15T07:00:00Z")
        self.assertEqual((code, "--now" in err), (3, True))

    def test_since_after_now_exits_3(self):
        code, err = self.window(make_state(), NOW, "--since", "2026-10-17T00:00:00Z")
        self.assertEqual((code, "--since" in err), (3, True))

    def test_invalid_state_exits_3_naming_the_key_path(self):
        document = make_state()
        document["units"][DM_A]["status"] = "open"
        code, err = self.window(document)
        self.assertEqual((code, f"units.{DM_A}.status" in err), (3, True))

    def test_a_unit_with_message_text_exits_3(self):
        document = make_state()
        document["units"][DM_A]["text"] = "can you review"
        code, err = self.window(document)
        self.assertEqual((code, f"units.{DM_A}.text" in err), (3, True))

    def test_a_watch_state_exits_3_naming_the_schema(self):
        code, err = self.window({**make_state(), "schema": 2})
        self.assertEqual((code, "schema" in err), (3, True))

    def test_a_tribe_state_exits_3(self):
        self.assertEqual(self.window({**make_state(), "schema": "tribe-1"})[0], 3)

    def test_a_rejection_writes_no_window(self):
        self.window(make_state(), "2026-10-15T07:00:00Z")
        self.assertEqual(os.listdir(self.dir), ["state.json"])

    def test_missing_state_exits_2(self):
        self.assertEqual(self.window_of(self.path("absent.json"))[0], 2)

    def test_state_that_is_not_json_exits_2(self):
        with open(self.path("state.json"), "w", encoding="utf-8") as handle:
            handle.write("{")
        code, err = self.window_of(self.path("state.json"))
        self.assertEqual((code, "invalid JSON" in err), (2, True))

    def test_unknown_time_zone_exits_2_naming_the_flag(self):
        code, err = self.window(make_state(), tz="Nowhere/Land")
        self.assertEqual((code, "--tz" in err), (2, True))

    def test_invalid_now_exits_2(self):
        self.assertEqual(self.window(make_state(), "noon")[0], 2)

    def test_now_without_an_offset_exits_2(self):
        self.assertEqual(self.window(make_state(), "2026-10-16T07:45:00")[0], 2)

    def test_invalid_since_exits_2(self):
        self.assertEqual(self.window(make_state(), NOW, "--since", "monday")[0], 2)

    def test_since_and_report_only_together_exit_2(self):
        self.assertEqual(self.window(make_state(), NOW, "--since", PREVIOUS, "--report-only")[0], 2)

    def test_a_lookback_of_zero_exits_2(self):
        self.assertEqual(self.window(make_state(), lookback="0")[0], 2)

    def test_a_lookback_above_365_days_exits_2(self):
        self.assertEqual(self.window(make_state(), lookback="366")[0], 2)

    def test_a_lookback_that_is_not_a_number_exits_2(self):
        self.assertEqual(self.window(make_state(), lookback="three")[0], 2)

    def test_a_missing_lookback_exits_2(self):
        self.assertEqual(self.window(make_state(), lookback=None)[0], 2)

    def test_an_unknown_flag_exits_2(self):
        self.assertEqual(self.window(make_state(), NOW, "--bogus")[0], 2)


class WindowCheckTest(unittest.TestCase):
    WINDOW = {"from_ts": ts(PREVIOUS), "to_ts": ts(NOW), "limited": None, "explicit": False}

    def rejection(self, document):
        with self.assertRaises(state.Rejected) as caught:
            recap_window.check_window(document)
        return str(caught.exception)

    def test_accepts_the_window_file_of_the_window_command(self):
        self.assertIsNone(recap_window.check_window({**self.WINDOW, "limited": "gap"}))

    def test_rejects_an_unknown_limit_naming_the_key_path(self):
        self.assertIn("limited", self.rejection({**self.WINDOW, "limited": "other"}))

    def test_rejects_a_missing_explicit_flag(self):
        window = {key: value for key, value in self.WINDOW.items() if key != "explicit"}

        self.assertIn("explicit", self.rejection(window))

    def test_rejects_a_start_after_the_end(self):
        self.assertIn("is after to_ts", self.rejection({**self.WINDOW, "from_ts": ts(NOW) + 1}))


class StubTest(unittest.TestCase):
    def test_registers_every_subcommand_of_the_design(self):
        self.assertEqual(set(recap.COMMANDS), {"init", "seed", "window", "features", "judge", "apply", "message"})


def stub_test(name):
    def test(self):
        code, _, err = run_cli(name)
        self.assertEqual((code, f"{name}: not implemented yet" in err), (2, True))

    return test


for stub_name in recap.STUBS:
    setattr(StubTest, f"test_{stub_name}_exits_2_as_not_implemented", stub_test(stub_name))


class ScriptTest(FileCase):
    def run_script(self, *argv):
        return subprocess.run([sys.executable, os.path.join(HERE, "recap.py"), *argv], capture_output=True, text=True, check=False)

    def test_script_init_exits_0_and_writes_the_state(self):
        result = self.run_script("init", "--digest", "chat-recap", "--out", self.path("state.json"))
        self.assertEqual((result.returncode, self.read("state.json")["schema"]), (0, 1))

    def test_script_window_exits_0_and_writes_the_window(self):
        result = self.run_script("window", "--state", self.write("state.json", make_state()), "--now", NOW, "--tz", TZ,
                                 "--lookback-working-days", "3", "--out", self.path("window.json"))
        self.assertEqual((result.returncode, self.read("window.json")["from_ts"]), (0, ts(PREVIOUS)))

    def test_script_exits_3_when_now_is_before_the_run_time(self):
        result = self.run_script("window", "--state", self.write("state.json", make_state()), "--now", "2026-10-15T07:00:00Z",
                                 "--tz", TZ, "--lookback-working-days", "3", "--out", self.path("window.json"))
        self.assertEqual(result.returncode, 3)

    def test_script_exits_2_for_a_stub(self):
        self.assertEqual(self.run_script(recap.STUBS[0]).returncode, 2)


if __name__ == "__main__":
    unittest.main()
