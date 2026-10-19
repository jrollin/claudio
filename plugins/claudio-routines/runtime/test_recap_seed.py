import json
import os
import subprocess
import sys
import unittest

import recap
import recap_state
from support import ts
from test_recap_state import FileCase, run_cli

HERE = os.path.dirname(os.path.abspath(__file__))
CHANNEL_A = "C" + "1" * 6
CHANNEL_B = "C" + "2" * 6
CHANNEL_C = "C" + "3" * 6
CHANNEL_D = "C" + "4" * 6
CHANNEL_E = "D" + "5" * 6
ROOT_B = "1791990000.000100"
ROOT_C = "1791990100.000200"
ROOT_D = "1791990200.000300"
ROOT_E = "1791990300.000400"
DM_A = f"dm-{CHANNEL_A}"
THREAD_B = f"thread-{CHANNEL_B}-{ROOT_B}"
MENTION_C = f"thread-{CHANNEL_C}-{ROOT_C}"
GROUP_D = f"thread-{CHANNEL_D}-{ROOT_D}"
HANDLED_E = f"thread-{CHANNEL_E}-{ROOT_E}"
PREVIOUS = "2026-10-15T07:45:00Z"
LONG_TITLE = "one two three four five six seven eight nine ten eleven twelve"
BLIND_SPOT_TEXT = "mentions search cut after 10 pages"
PERMALINK_HOST = "chat.example.test"


def permalink(channel):
    return f"https://{PERMALINK_HOST}/archives/{channel}/p1791990730"


def make_source_unit(channel=CHANNEL_A, **fields):
    unit = {
        "kind": "dm",
        "channel": channel,
        "title": "Review the export plan",
        "permalink": permalink(channel),
        "first_seen": ts("2026-10-14T07:45:00Z"),
        "last_ts": ts("2026-10-15T06:12:10Z"),
        "status": "waiting",
        "runs_waiting": 2,
        "late": None,
    }
    return {**unit, **fields}


def make_source_units():
    return {
        DM_A: make_source_unit(late="3 working days"),
        THREAD_B: make_source_unit(CHANNEL_B, kind="thread", title=LONG_TITLE, status="promise", runs_waiting=1),
        MENTION_C: make_source_unit(CHANNEL_C, kind="mention", status="team_ask", runs_waiting=0, late="1 working day"),
        GROUP_D: make_source_unit(CHANNEL_D, kind="group", status="waiting_on_others", runs_waiting=0),
        HANDLED_E: make_source_unit(CHANNEL_E, kind="thread", status="handled", runs_waiting=0),
    }


def make_source(units=None, **top):
    source = {
        "schema": 1,
        "digest": "recap",
        "run": {
            "at": PREVIOUS,
            "previous_at": "2026-10-14T07:45:00Z",
            "sources_last_edited": "2026-10-01",
            "window": {"from_ts": ts("2026-10-14T07:45:00Z"), "to_ts": ts(PREVIOUS)},
            "models": {"main": "model-a"},
            "posted": True,
        },
        "units": make_source_units() if units is None else units,
        "blind_spots": [BLIND_SPOT_TEXT],
    }
    return {**source, **top}


class SeedCase(FileCase):
    def seed_file(self, source_path, digest="chat-recap"):
        return run_cli("seed", "--from", source_path, "--digest", digest, "--out", self.path("state.json"))

    def seed(self, source, digest="chat-recap"):
        return self.seed_file(self.write("source.json", source), digest)

    def seeded(self, source=None):
        code, _, err = self.seed(make_source() if source is None else source)
        self.assertEqual((code, err), (0, ""))
        return self.read("state.json")

    def with_unit(self, key=DM_A, **fields):
        source = make_source()
        source["units"][key].update(fields)
        return source

    def assert_rejected(self, source, where):
        code, out, err = self.seed(source)
        self.assertEqual((code, out, err.startswith("recap.py: rejected: seed: "), where in err), (3, "", True, True), err)
        self.assertFalse(os.path.exists(self.path("state.json")))


class ConvertedStateTest(SeedCase):
    def setUp(self):
        super().setUp()
        self.state = self.seeded()

    def test_passes_the_state_check(self):
        self.assertIsNone(recap_state.check_state(self.state))

    def test_writes_canonical_json(self):
        self.assert_canonical("state.json")

    def test_keeps_only_the_state_sections(self):
        self.assertEqual(sorted(self.state), ["blind_spots", "digest", "run", "schema", "units"])

    def test_takes_the_digest_from_the_flag(self):
        self.assertEqual(self.state["digest"], "chat-recap")

    def test_keeps_the_run_times_and_window(self):
        expected = {"at": PREVIOUS, "previous_at": "2026-10-14T07:45:00Z", "window": {"from_ts": ts("2026-10-14T07:45:00Z"), "to_ts": ts(PREVIOUS)}}
        self.assertEqual(self.state["run"], expected)

    def test_keeps_every_unit_key(self):
        self.assertEqual(sorted(self.state["units"]), sorted([DM_A, THREAD_B, MENTION_C, GROUP_D, HANDLED_E]))

    def test_converts_a_unit_in_full(self):
        expected = {
            "kind": "dm",
            "channel": CHANNEL_A,
            "title": "Review the export plan",
            "first_seen": "2026-10-14T07:45:00Z",
            "last_ts": f"{ts('2026-10-15T06:12:10Z')}.000000",
            "status": "waiting",
            "runs_waiting": 2,
            "late": 3,
            "due": None,
        }
        self.assertEqual(self.state["units"][DM_A], expected)

    def test_keeps_the_statuses(self):
        statuses = {key: unit["status"] for key, unit in self.state["units"].items()}
        self.assertEqual(statuses, {DM_A: "waiting", THREAD_B: "promise", MENTION_C: "team_ask", GROUP_D: "waiting_on_others", HANDLED_E: "handled"})

    def test_keeps_the_kinds_and_channels(self):
        kinds = {key: (unit["kind"], unit["channel"]) for key, unit in self.state["units"].items()}
        self.assertEqual(
            kinds,
            {DM_A: ("dm", CHANNEL_A), THREAD_B: ("thread", CHANNEL_B), MENTION_C: ("mention", CHANNEL_C), GROUP_D: ("group", CHANNEL_D), HANDLED_E: ("thread", CHANNEL_E)},
        )

    def test_keeps_the_waiting_run_counts(self):
        self.assertEqual({key: unit["runs_waiting"] for key, unit in self.state["units"].items()}, {DM_A: 2, THREAD_B: 1, MENTION_C: 0, GROUP_D: 0, HANDLED_E: 0})

    def test_converts_first_seen_to_utc_text(self):
        self.assertEqual(self.state["units"][THREAD_B]["first_seen"], "2026-10-14T07:45:00Z")

    def test_converts_last_ts_to_a_slack_ts_with_microseconds(self):
        self.assertEqual(self.state["units"][THREAD_B]["last_ts"], f"{ts('2026-10-15T06:12:10Z')}.000000")

    def test_reads_late_as_its_leading_integer(self):
        self.assertEqual((self.state["units"][DM_A]["late"], self.state["units"][MENTION_C]["late"]), (3, 1))

    def test_keeps_a_null_late(self):
        self.assertIsNone(self.state["units"][THREAD_B]["late"])

    def test_sets_every_due_to_null(self):
        self.assertEqual([unit["due"] for unit in self.state["units"].values()], [None] * 5)

    def test_cuts_a_twelve_word_title_to_eight(self):
        self.assertEqual(self.state["units"][THREAD_B]["title"], "one two three four five six seven eight")

    def test_keeps_a_short_title(self):
        self.assertEqual(self.state["units"][DM_A]["title"], "Review the export plan")

    def test_drops_the_permalink(self):
        self.assertEqual(["permalink" in unit for unit in self.state["units"].values()], [False] * 5)

    def test_drops_the_blind_spots(self):
        self.assertEqual(self.state["blind_spots"], [])

    def test_holds_no_dropped_text(self):
        text = json.dumps(self.state)
        dropped = ("nine", "ten", "eleven", "twelve", BLIND_SPOT_TEXT, PERMALINK_HOST, "model-a", "sources_last_edited", "posted")
        self.assertEqual([word for word in dropped if word in text], [])

    def test_unit_fields_are_the_state_fields(self):
        self.assertEqual({tuple(sorted(unit)) for unit in self.state["units"].values()}, {tuple(sorted(recap_state.UNIT_SPEC))})


class SourceVariantTest(SeedCase):
    def test_keeps_a_null_window_and_run_times(self):
        source = make_source()
        source["run"].update(at=None, previous_at=None, window=None)
        self.assertEqual(self.seeded(source)["run"], {"at": None, "previous_at": None, "window": None})

    def test_seeds_a_state_without_units(self):
        self.assertEqual(self.seeded(make_source(units={}))["units"], {})

    def test_cuts_a_title_spread_over_lines(self):
        source = self.with_unit(THREAD_B, title="one\ntwo  three\tfour five six seven eight nine")
        self.assertEqual(self.seeded(source)["units"][THREAD_B]["title"], "one two three four five six seven eight")

    def test_reads_late_without_a_unit_word(self):
        self.assertEqual(self.seeded(self.with_unit(late="12"))["units"][DM_A]["late"], 12)

    def test_ignores_fields_the_state_does_not_hold(self):
        source = self.with_unit(summary="free text the state must not keep")
        self.assertNotIn("summary", self.seeded(source)["units"][DM_A])

    def test_takes_the_digest_from_the_flag_not_the_source(self):
        self.seed(make_source(digest="recap"), digest="other-recap")
        self.assertEqual(self.read("state.json")["digest"], "other-recap")


class UnmappableUnitTest(SeedCase):
    def test_unknown_kind_names_its_path(self):
        self.assert_rejected(self.with_unit(kind="channel"), f"units.{DM_A}.kind")

    def test_a_state_only_kind_is_unknown_to_the_source(self):
        self.assert_rejected(self.with_unit(kind="group_dm"), f"units.{DM_A}.kind")

    def test_unknown_status_names_its_path(self):
        self.assert_rejected(self.with_unit(THREAD_B, status="announcement"), f"units.{THREAD_B}.status")

    def test_kind_not_matching_a_dm_key_names_its_path(self):
        self.assert_rejected(self.with_unit(DM_A, kind="mention"), f"units.{DM_A}.kind")

    def test_kind_not_matching_a_thread_key_names_its_path(self):
        self.assert_rejected(self.with_unit(THREAD_B, kind="dm"), f"units.{THREAD_B}.kind")

    def test_channel_not_matching_its_key_names_its_path(self):
        self.assert_rejected(self.with_unit(DM_A, channel=CHANNEL_B), f"units.{DM_A}.channel")

    def test_malformed_key_names_its_path(self):
        source = make_source(units={"channel-C111111": make_source_unit()})
        self.assert_rejected(source, "units.channel-C111111")

    def test_thread_key_without_a_root_ts_names_its_path(self):
        source = make_source(units={f"thread-{CHANNEL_B}": make_source_unit(CHANNEL_B, kind="thread")})
        self.assert_rejected(source, f"units.thread-{CHANNEL_B}")

    def test_text_first_seen_names_its_path(self):
        self.assert_rejected(self.with_unit(first_seen="2026-10-14T07:45:00Z"), f"units.{DM_A}.first_seen")

    def test_float_last_ts_names_its_path(self):
        self.assert_rejected(self.with_unit(THREAD_B, last_ts=1791990730.5), f"units.{THREAD_B}.last_ts")

    def test_boolean_last_ts_names_its_path(self):
        self.assert_rejected(self.with_unit(last_ts=True), f"units.{DM_A}.last_ts")

    def test_negative_first_seen_names_its_path(self):
        self.assert_rejected(self.with_unit(first_seen=-1), f"units.{DM_A}.first_seen")

    def test_first_seen_beyond_year_9999_names_its_path(self):
        self.assert_rejected(self.with_unit(first_seen=2**40), f"units.{DM_A}.first_seen")

    def test_late_without_a_leading_integer_names_its_path(self):
        self.assert_rejected(self.with_unit(late="working days"), f"units.{DM_A}.late")

    def test_late_that_is_a_number_names_its_path(self):
        self.assert_rejected(self.with_unit(late=3), f"units.{DM_A}.late")

    def test_negative_runs_waiting_names_its_path(self):
        self.assert_rejected(self.with_unit(runs_waiting=-1), f"units.{DM_A}.runs_waiting")

    def test_missing_field_names_its_path(self):
        source = make_source()
        del source["units"][THREAD_B]["status"]
        self.assert_rejected(source, f"units.{THREAD_B}.status")

    def test_empty_title_names_its_path(self):
        self.assert_rejected(self.with_unit(title="  "), f"units.{DM_A}.title")

    def test_title_with_a_control_character_names_its_path(self):
        self.assert_rejected(self.with_unit(title="Review\x00 the plan"), f"units.{DM_A}.title")

    def test_unit_that_is_not_an_object_names_its_path(self):
        source = make_source()
        source["units"][DM_A] = "waiting"
        self.assert_rejected(source, f"units.{DM_A}")

    def test_writes_nothing_when_one_unit_among_valid_ones_fails(self):
        self.assert_rejected(self.with_unit(HANDLED_E, status="done"), f"units.{HANDLED_E}.status")

    def test_the_message_holds_no_unit_text(self):
        source = self.with_unit(kind="channel", title="Please send the figures to the client")
        self.assertNotIn("figures", self.seed(source)[2])


class InvalidSourceTest(SeedCase):
    def test_unsupported_schema_names_its_path(self):
        self.assert_rejected(make_source(schema=2), "at schema")

    def test_missing_units_names_its_path(self):
        source = make_source()
        del source["units"]
        self.assert_rejected(source, "missing key units")

    def test_units_that_are_a_list_name_their_path(self):
        self.assert_rejected(make_source(units=[]), "at units")

    def test_missing_run_names_its_path(self):
        source = make_source()
        del source["run"]
        self.assert_rejected(source, "missing key run")

    def test_run_time_without_utc_text_names_its_path(self):
        source = make_source()
        source["run"]["at"] = "yesterday"
        self.assert_rejected(source, "at run.at")

    def test_window_with_text_bounds_names_its_path(self):
        source = make_source()
        source["run"]["window"] = {"from_ts": "a", "to_ts": "b"}
        self.assert_rejected(source, "at run.window.from_ts")

    def test_window_ending_before_it_starts_is_rejected(self):
        source = make_source()
        source["run"]["window"] = {"from_ts": 20, "to_ts": 10}
        self.assert_rejected(source, "run.window")

    def test_blind_spots_that_are_not_a_list_name_their_path(self):
        self.assert_rejected(make_source(blind_spots="none"), "at blind_spots")

    def test_empty_digest_is_rejected(self):
        code, _, err = self.seed(make_source(), digest="")
        self.assertEqual((code, "at digest" in err, os.path.exists(self.path("state.json"))), (3, True, False))

    def test_source_that_is_not_json_exits_2(self):
        path = self.path("source.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{")
        code, _, err = self.seed_file(path)
        self.assertEqual((code, "invalid JSON" in err, os.path.exists(self.path("state.json"))), (2, True, False))

    def test_missing_source_exits_2(self):
        code, _, err = self.seed_file(self.path("absent.json"))
        self.assertEqual((code, "cannot read" in err), (2, True))

    def test_source_that_is_a_list_is_rejected(self):
        self.assert_rejected([], "expected an object at <root>")


class SeedCommandTest(SeedCase):
    def test_is_not_a_stub(self):
        self.assertNotIn("seed", recap.STUBS)

    def test_requires_from(self):
        self.assertEqual(run_cli("seed", "--digest", "chat-recap", "--out", self.path("state.json"))[0], 2)

    def test_requires_digest(self):
        self.assertEqual(run_cli("seed", "--from", self.write("source.json", make_source()), "--out", self.path("state.json"))[0], 2)

    def test_requires_out(self):
        self.assertEqual(run_cli("seed", "--from", self.write("source.json", make_source()), "--digest", "chat-recap")[0], 2)

    def test_state_it_writes_gives_a_window(self):
        self.seeded()
        code, _, err = run_cli(
            "window", "--state", self.path("state.json"), "--now", "2026-10-16T07:45:00Z", "--tz", "Europe/Paris",
            "--lookback-working-days", "3", "--out", self.path("window.json"),
        )
        self.assertEqual((code, err, self.read("window.json")["from_ts"]), (0, "", ts(PREVIOUS)))

    def test_script_exits_0_and_writes_the_state(self):
        source = self.write("source.json", make_source())
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, "recap.py"), "seed", "--from", source, "--digest", "chat-recap", "--out", self.path("state.json")],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual((result.returncode, result.stderr, self.read("state.json")["schema"]), (0, "", 1))

    def test_script_exits_3_for_a_unit_it_cannot_map(self):
        source = self.write("source.json", self.with_unit(kind="channel"))
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, "recap.py"), "seed", "--from", source, "--digest", "chat-recap", "--out", self.path("state.json")],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual((result.returncode, os.path.exists(self.path("state.json"))), (3, False))


if __name__ == "__main__":
    unittest.main()
