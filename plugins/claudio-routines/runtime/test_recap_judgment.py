import argparse
import contextlib
import copy
import io
import json
import os
import tempfile
import unittest

import recap
import recap_judgment
import state

ASK_KEY = "dm-C0001"
OWN_KEY = "thread-C0002-1790000000.000100"
AUTHOR = "usr_8f3k2"
OWNER = "usr_owner"
STRANGER = "U" + "3" * 6
ASK_KIND = "waiting on you"
OWN_KIND = "promise"
DUE = "2026-06-05T17:00:00+02:00"


def make_message(user, ts):
    return {"user": user, "name": "Someone", "bot": False, "ts": ts, "root_ts": None, "text": "text", "mentions": [], "group_mentions": []}


def make_features():
    return {
        "owner": OWNER,
        "units": {
            ASK_KEY: {
                "kind": "dm",
                "channel": "C0001",
                "name": "DM",
                "messages": [make_message(AUTHOR, "1790000000.000100")],
                "facts": {},
                "allowed": [ASK_KIND, "noise"],
            },
            OWN_KEY: {
                "kind": "thread",
                "channel": "C0002",
                "name": "general",
                "messages": [make_message(OWNER, "1790000000.000100")],
                "facts": {},
                "allowed": ["you're waiting on", OWN_KIND, "already handled", "noise"],
            },
        },
    }


JUDGMENT = {
    "units": {
        ASK_KEY: {
            "kind": ASK_KIND,
            "title": "Review the rollout plan",
            "summary": "Ada asks for a review of the rollout plan before Friday.",
            "blocking": True,
            "due": None,
        },
        OWN_KEY: {
            "kind": OWN_KIND,
            "title": "Send the weekly report",
            "summary": "You promised to send the weekly report to the team.",
            "blocking": False,
            "due": DUE,
        },
    },
    "reading": [
        {"text": "The rollout plan review blocks the team this week.", "cites": [ASK_KEY]},
        {"text": "The weekly report is promised and still open.", "cites": [OWN_KEY, ASK_KEY]},
    ],
}


def make_judgment():
    return copy.deepcopy(JUDGMENT)


def changed(*path_and_value):
    *path, value = path_and_value
    document = make_judgment()
    target = document
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return document


def without(*path):
    document = make_judgment()
    target = document
    for step in path[:-1]:
        target = target[step]
    del target[path[-1]]
    return document


def unit_field(field, value, key=ASK_KEY):
    return changed("units", key, field, value)


def own_field(field, value):
    return unit_field(field, value, OWN_KEY)


class CheckTestCase(unittest.TestCase):
    def rejection(self, document, features_doc=None):
        with self.assertRaises(state.Rejected) as caught:
            recap_judgment.check_judgment(document, features_doc or make_features())
        return str(caught.exception)


class ValidJudgmentTest(CheckTestCase):
    def test_a_full_judgment_passes(self):
        self.assertIsNone(recap_judgment.check_judgment(make_judgment(), make_features()))

    def test_a_summary_with_a_trailing_terminator_passes(self):
        self.assertIsNone(recap_judgment.check_judgment(unit_field("summary", "Ada asks for a review."), make_features()))

    def test_a_version_number_in_a_summary_is_not_a_sentence_end(self):
        self.assertIsNone(recap_judgment.check_judgment(unit_field("summary", "Ada asks to ship v1.2 on Friday"), make_features()))

    def test_a_title_of_8_words_passes(self):
        self.assertIsNone(recap_judgment.check_judgment(unit_field("title", "one two three four five six seven eight"), make_features()))

    def test_a_summary_of_200_characters_passes(self):
        self.assertIsNone(recap_judgment.check_judgment(unit_field("summary", "a" * 200), make_features()))

    def test_a_due_time_in_utc_passes(self):
        self.assertIsNone(recap_judgment.check_judgment(own_field("due", "2026-06-05T15:00:00Z"), make_features()))

    def test_a_promise_without_a_due_time_passes(self):
        self.assertIsNone(recap_judgment.check_judgment(own_field("due", None), make_features()))

    def test_a_reading_of_4_bullets_passes(self):
        reading = [{"text": f"Point {number}", "cites": [ASK_KEY]} for number in range(4)]

        self.assertIsNone(recap_judgment.check_judgment(changed("reading", reading), make_features()))

    def test_a_unit_without_a_message_has_no_author_to_hold_back(self):
        features_doc = make_features()
        features_doc["units"][ASK_KEY]["messages"] = []

        self.assertIsNone(recap_judgment.check_judgment(make_judgment(), features_doc))


class StructureTest(CheckTestCase):
    def test_a_judgment_that_is_not_an_object_is_rejected(self):
        self.assertEqual(self.rejection([]), "<root>: expected an object")

    def test_a_judgment_without_units_is_rejected_with_the_key_path(self):
        self.assertEqual(self.rejection(without("units")), "units: missing")

    def test_a_judgment_without_reading_is_rejected_with_the_key_path(self):
        self.assertEqual(self.rejection(without("reading")), "reading: missing")

    def test_an_unknown_top_level_field_is_rejected_with_its_name(self):
        self.assertEqual(self.rejection(changed("extra", [])), "extra: unknown field")

    def test_units_that_are_not_an_object_are_rejected(self):
        self.assertEqual(self.rejection(changed("units", [])), "units: expected an object")

    def test_a_unit_that_is_not_an_object_is_rejected_with_its_key_path(self):
        self.assertEqual(self.rejection(changed("units", ASK_KEY, "noise")), f"units.{ASK_KEY}: expected an object")

    def test_a_missing_unit_is_rejected_with_its_key_path(self):
        self.assertIn(f"units.{OWN_KEY}: missing", self.rejection(without("units", OWN_KEY)))

    def test_an_unknown_unit_is_rejected_with_its_key_path(self):
        document = changed("units", "dm-C9999", copy.deepcopy(JUDGMENT["units"][ASK_KEY]))

        self.assertIn("units.dm-C9999: not a unit of the features", self.rejection(document))

    def test_an_unknown_unit_key_is_cleaned_before_it_is_reported(self):
        document = changed("units", "dm-C9999\n<@evil>", copy.deepcopy(JUDGMENT["units"][ASK_KEY]))

        self.assertNotRegex(self.rejection(document), r"[\n<>@]")

    def test_a_missing_unit_field_is_rejected_with_its_key_path(self):
        self.assertEqual(self.rejection(without("units", ASK_KEY, "due")), f"units.{ASK_KEY}.due: missing")

    def test_an_unknown_unit_field_is_rejected_with_its_key_path(self):
        self.assertEqual(self.rejection(changed("units", ASK_KEY, "person", "Ada")), f"units.{ASK_KEY}.person: unknown field")

    def test_a_missing_unit_is_reported_before_a_bad_field(self):
        document = without("units", OWN_KEY)
        document["units"][ASK_KEY]["title"] = ""

        self.assertIn(f"units.{OWN_KEY}: missing", self.rejection(document))


class KindTest(CheckTestCase):
    def test_a_kind_outside_allowed_is_rejected_with_its_key_path(self):
        message = self.rejection(unit_field("kind", "promise"))

        self.assertIn(f"units.{ASK_KEY}.kind: promise is not allowed for this unit", message)

    def test_the_rejection_names_the_allowed_kinds(self):
        self.assertIn("the facts allow waiting on you, noise", self.rejection(unit_field("kind", "promise")))

    def test_an_unknown_kind_is_rejected_with_the_kinds(self):
        message = self.rejection(unit_field("kind", "urgent"))

        self.assertIn(f"units.{ASK_KEY}.kind: expected one of waiting on you, team ask", message)

    def test_a_kind_that_is_not_a_string_is_rejected(self):
        self.assertIn(f"units.{ASK_KEY}.kind: expected one of", self.rejection(unit_field("kind", ["noise"])))

    def test_noise_passes_on_a_unit_that_is_not_blocking(self):
        document = unit_field("kind", "noise")
        document["units"][ASK_KEY]["blocking"] = False

        self.assertIsNone(recap_judgment.check_judgment(document, make_features()))


class TitleTest(CheckTestCase):
    def test_a_title_of_9_words_is_rejected_with_its_key_path(self):
        message = self.rejection(unit_field("title", "one two three four five six seven eight nine"))

        self.assertEqual(message, f"units.{ASK_KEY}.title: must be at most 8 words")

    def test_a_title_whose_words_multiply_when_folded_is_rejected(self):
        title = "one two three four five six seven \ufdfa"

        self.assertIn(f"units.{ASK_KEY}.title: must be at most 8 words", self.rejection(unit_field("title", title)))

    def test_an_empty_title_is_rejected(self):
        self.assertEqual(self.rejection(unit_field("title", "")), f"units.{ASK_KEY}.title: must not be empty")

    def test_a_blank_title_is_rejected(self):
        self.assertEqual(self.rejection(unit_field("title", "   ")), f"units.{ASK_KEY}.title: must not be empty")

    def test_a_title_that_is_not_a_string_is_rejected(self):
        self.assertEqual(self.rejection(unit_field("title", 3)), f"units.{ASK_KEY}.title: expected a string")

    def test_a_title_with_a_control_character_is_rejected(self):
        self.assertIn("control, format or separator", self.rejection(unit_field("title", "Review\nplan")))

    def test_a_title_with_a_zero_width_character_is_rejected(self):
        self.assertIn("control, format or separator", self.rejection(unit_field("title", "Review\u200bplan")))

    def test_a_title_with_a_line_separator_is_rejected(self):
        self.assertIn("control, format or separator", self.rejection(unit_field("title", "Review\u2028plan")))

    def test_a_title_with_an_inert_marker_is_rejected(self):
        for marker in ("<b>", ">", "@here", "see https://chat.example.test/x", "\uff20here"):
            with self.subTest(marker=marker):
                self.assertEqual(
                    self.rejection(unit_field("title", f"Review {marker}")), f"units.{ASK_KEY}.title: must not contain <, >, @ or ://"
                )

    def test_a_title_holding_the_author_id_of_the_unit_is_rejected(self):
        self.assertEqual(self.rejection(unit_field("title", f"Reply to {AUTHOR}")), f"units.{ASK_KEY}.title: must not hold a chat author id")

    def test_a_title_holding_a_chat_id_shape_is_rejected(self):
        self.assertEqual(self.rejection(unit_field("title", f"Reply to {STRANGER}")), f"units.{ASK_KEY}.title: must not hold a chat author id")


class SummaryTest(CheckTestCase):
    def test_a_summary_of_two_sentences_is_rejected_with_its_key_path(self):
        message = self.rejection(unit_field("summary", "Ada asks for a review. She needs it Friday."))

        self.assertEqual(message, f"units.{ASK_KEY}.summary: must be one sentence")

    def test_a_summary_of_two_questions_is_rejected(self):
        self.assertIn("must be one sentence", self.rejection(unit_field("summary", "Is it ready? Ada waits")))

    def test_a_summary_of_two_exclamations_is_rejected(self):
        self.assertIn("must be one sentence", self.rejection(unit_field("summary", "Ship it! Ada waits")))

    def test_a_summary_with_a_fullwidth_terminator_is_rejected(self):
        self.assertIn("must be one sentence", self.rejection(unit_field("summary", "Is it ready\uff1f Ada waits")))

    def test_a_summary_of_201_characters_is_rejected(self):
        message = self.rejection(unit_field("summary", "a" * 201))

        self.assertEqual(message, f"units.{ASK_KEY}.summary: must be at most 200 characters")

    def test_a_summary_that_grows_past_200_characters_when_folded_is_rejected(self):
        self.assertIn("must be at most 200 characters", self.rejection(unit_field("summary", "\ufb03" * 100)))

    def test_an_empty_summary_is_rejected(self):
        self.assertEqual(self.rejection(unit_field("summary", "")), f"units.{ASK_KEY}.summary: must not be empty")

    def test_a_summary_with_an_inert_marker_is_rejected(self):
        for marker in ("<b>", ">", "@here", "https://chat.example.test/x", "\uff20here"):
            with self.subTest(marker=marker):
                self.assertEqual(
                    self.rejection(unit_field("summary", f"Ada asks {marker} today")),
                    f"units.{ASK_KEY}.summary: must not contain <, >, @ or ://",
                )

    def test_a_summary_with_a_control_character_is_rejected(self):
        self.assertIn("control, format or separator", self.rejection(unit_field("summary", "Ada asks\tfor a review")))

    def test_a_summary_holding_the_author_id_of_the_unit_is_rejected(self):
        message = self.rejection(unit_field("summary", f"{AUTHOR} asks for a review"))

        self.assertEqual(message, f"units.{ASK_KEY}.summary: must not hold a chat author id")

    def test_a_summary_holding_the_author_id_in_fullwidth_form_is_rejected(self):
        self.assertIn("must not hold a chat author id", self.rejection(unit_field("summary", "\uff55\uff53\uff52_8f3k2 asks")))

    def test_a_summary_holding_a_chat_id_shape_is_rejected(self):
        self.assertIn("must not hold a chat author id", self.rejection(unit_field("summary", f"{STRANGER} asks for a review")))

    def test_a_summary_with_an_all_caps_word_is_accepted(self):
        for word in ("UPDATED", "WARNING"):
            with self.subTest(word=word):
                self.assertIsNone(recap_judgment.check_judgment(unit_field("summary", f"Ada says the doc is {word} now"), make_features()))

    def test_a_summary_holding_a_workspace_id_shape_is_rejected(self):
        self.assertIn("must not hold a chat author id", self.rejection(unit_field("summary", "W" + "4" * 6 + " asks for a review")))


class DueTest(CheckTestCase):
    def test_due_on_a_kind_other_than_promise_is_rejected_with_its_key_path(self):
        message = self.rejection(unit_field("due", DUE))

        self.assertEqual(message, f"units.{ASK_KEY}.due: is allowed only on promise")

    def test_a_due_time_without_an_offset_is_rejected(self):
        self.assertEqual(self.rejection(own_field("due", "2026-06-05T17:00:00")), f"units.{OWN_KEY}.due: expected null or an ISO 8601 time with a UTC offset")

    def test_a_due_date_without_a_time_is_rejected(self):
        self.assertIn("expected null or an ISO 8601 time", self.rejection(own_field("due", "2026-06-05")))

    def test_a_due_text_that_is_not_a_time_is_rejected(self):
        self.assertIn("expected null or an ISO 8601 time", self.rejection(own_field("due", "Friday afternoon")))

    def test_a_due_that_is_not_a_string_is_rejected(self):
        self.assertIn("expected null or an ISO 8601 time", self.rejection(own_field("due", 1790000000)))

    def test_a_malformed_due_on_another_kind_is_reported_as_malformed(self):
        self.assertIn("expected null or an ISO 8601 time", self.rejection(unit_field("due", "soon")))


class BlockingTest(CheckTestCase):
    def test_blocking_true_on_another_kind_is_rejected_with_its_key_path(self):
        message = self.rejection(own_field("blocking", True))

        self.assertEqual(message, f"units.{OWN_KEY}.blocking: may be true only on waiting on you")

    def test_blocking_false_on_waiting_on_you_passes(self):
        self.assertIsNone(recap_judgment.check_judgment(unit_field("blocking", False), make_features()))

    def test_blocking_that_is_not_a_boolean_is_rejected(self):
        self.assertEqual(self.rejection(unit_field("blocking", "yes")), f"units.{ASK_KEY}.blocking: expected a boolean")

    def test_blocking_as_a_number_is_rejected(self):
        self.assertEqual(self.rejection(unit_field("blocking", 1)), f"units.{ASK_KEY}.blocking: expected a boolean")

    def test_blocking_as_null_is_rejected(self):
        self.assertEqual(self.rejection(unit_field("blocking", None)), f"units.{ASK_KEY}.blocking: expected a boolean")


class ReadingTest(CheckTestCase):
    def test_a_reading_of_1_bullet_is_rejected_with_the_count(self):
        document = changed("reading", [{"text": "One point", "cites": [ASK_KEY]}])

        self.assertEqual(self.rejection(document), "reading: expected 2 to 4 entries, got 1")

    def test_a_reading_of_5_bullets_is_rejected_with_the_count(self):
        document = changed("reading", [{"text": f"Point {number}", "cites": [ASK_KEY]} for number in range(5)])

        self.assertEqual(self.rejection(document), "reading: expected 2 to 4 entries, got 5")

    def test_an_empty_reading_is_rejected(self):
        self.assertEqual(self.rejection(changed("reading", [])), "reading: expected 2 to 4 entries, got 0")

    def test_a_reading_that_is_not_a_list_is_rejected(self):
        self.assertEqual(self.rejection(changed("reading", "text")), "reading: expected a list")

    def test_a_bullet_citing_an_unknown_unit_is_rejected_with_its_key_path(self):
        message = self.rejection(changed("reading", 1, "cites", [OWN_KEY, "dm-C9999"]))

        self.assertEqual(message, "reading[1].cites[1]: dm-C9999 is not a unit of the run")

    def test_a_bullet_with_no_cite_is_rejected_with_its_key_path(self):
        self.assertEqual(self.rejection(changed("reading", 0, "cites", [])), "reading[0].cites: expected at least 1 unit key")

    def test_a_bullet_whose_cites_are_not_a_list_is_rejected(self):
        self.assertEqual(self.rejection(changed("reading", 0, "cites", ASK_KEY)), "reading[0].cites: expected at least 1 unit key")

    def test_a_bullet_citing_something_that_is_not_a_string_is_rejected(self):
        self.assertIn("reading[0].cites[0]:", self.rejection(changed("reading", 0, "cites", [["x"]])))

    def test_a_bullet_without_cites_is_rejected(self):
        self.assertEqual(self.rejection(without("reading", 0, "cites")), "reading[0].cites: missing")

    def test_a_bullet_with_an_unknown_field_is_rejected(self):
        self.assertEqual(self.rejection(changed("reading", 0, "extra", 1)), "reading[0].extra: unknown field")

    def test_a_bullet_of_301_characters_is_rejected(self):
        self.assertEqual(self.rejection(changed("reading", 0, "text", "a" * 301)), "reading[0].text: must be at most 300 characters")

    def test_a_bullet_of_two_sentences_passes(self):
        document = changed("reading", 0, "text", "The plan review is late. It blocks the team.")

        self.assertIsNone(recap_judgment.check_judgment(document, make_features()))

    def test_a_bullet_with_an_inert_marker_is_rejected(self):
        for marker in ("<b>", ">", "@here", "https://chat.example.test/x", "\uff20here"):
            with self.subTest(marker=marker):
                self.assertEqual(
                    self.rejection(changed("reading", 0, "text", f"See {marker} today")),
                    "reading[0].text: must not contain <, >, @ or ://",
                )

    def test_a_bullet_with_a_control_character_is_rejected(self):
        self.assertIn("control, format or separator", self.rejection(changed("reading", 1, "text", "Two\nlines")))

    def test_a_bullet_holding_the_author_id_of_any_unit_is_rejected(self):
        self.assertEqual(self.rejection(changed("reading", 1, "text", f"{OWNER} is waiting")), "reading[1].text: must not hold a chat author id")

    def test_a_bullet_holding_a_chat_id_shape_is_rejected(self):
        self.assertIn("must not hold a chat author id", self.rejection(changed("reading", 0, "text", f"{STRANGER} is waiting")))

    def test_an_empty_bullet_is_rejected(self):
        self.assertEqual(self.rejection(changed("reading", 0, "text", " ")), "reading[0].text: must not be empty")

    def test_a_bullet_that_is_not_an_object_is_rejected(self):
        self.assertEqual(self.rejection(changed("reading", 0, "text only")), "reading[0]: expected an object")

    def test_a_unit_failure_is_reported_before_a_reading_failure(self):
        document = changed("reading", [])
        document["units"][ASK_KEY]["title"] = ""

        self.assertIn(f"units.{ASK_KEY}.title", self.rejection(document))


class FileCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def write(self, name, document):
        path = os.path.join(self.directory.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(document if isinstance(document, str) else json.dumps(document))
        return path

    def run_judge(self, judgment_document=None, features_document=None, features_path=None, judgment_path=None):
        parser = argparse.ArgumentParser()
        recap_judgment.add_judge_arguments(parser)
        args = parser.parse_args(
            [
                "--features", features_path or self.write("features.json", make_features() if features_document is None else features_document),
                "--judgment", judgment_path or self.write("judgment.json", make_judgment() if judgment_document is None else judgment_document),
            ]
        )
        err = io.StringIO()
        try:
            code = recap_judgment.run_judge(args)
        except state.InputError as error:
            print(f"recap.py: {error}", file=err)
            code = 2
        except state.Rejected as error:
            print(f"recap.py: rejected: {error}", file=err)
            code = 3
        return code, err.getvalue()


class RecapMainJudgeTest(FileCase):
    def test_recap_main_runs_judge_and_exits_3_on_a_rejected_judgment(self):
        features = self.write("features.json", make_features())
        judgment = self.write("judgment.json", unit_field("blocking", "yes"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = recap.main(["judge", "--features", features, "--judgment", judgment])

        self.assertEqual(code, 3)
        self.assertIn(f"units.{ASK_KEY}.blocking", err.getvalue())

    def test_recap_main_runs_judge_and_exits_0_on_a_valid_judgment(self):
        self.assertEqual(recap.main(["judge", "--features", self.write("features.json", make_features()), "--judgment", self.write("judgment.json", make_judgment())]), 0)


class JudgeCommandTest(FileCase):
    def test_a_valid_judgment_exits_0_and_prints_nothing(self):
        self.assertEqual(self.run_judge(), (0, ""))

    def test_a_rejected_judgment_exits_3_with_the_key_path(self):
        code, err = self.run_judge(unit_field("title", "one two three four five six seven eight nine"))

        self.assertEqual(code, 3)
        self.assertIn(f"rejected: judgment: units.{ASK_KEY}.title: must be at most 8 words", err)

    def test_invalid_json_exits_3_with_a_clear_message(self):
        code, err = self.run_judge("{not json")

        self.assertEqual(code, 3)
        self.assertIn("rejected: judgment: invalid JSON", err)

    def test_a_judgment_that_is_not_an_object_exits_3(self):
        code, err = self.run_judge("[]")

        self.assertEqual(code, 3)
        self.assertIn("rejected: judgment: <root>: expected an object", err)

    def test_an_unreadable_judgment_exits_2(self):
        code, err = self.run_judge(judgment_path=os.path.join(self.directory.name, "absent.json"))

        self.assertEqual(code, 2)
        self.assertIn("judgment: cannot read", err)

    def test_an_unreadable_features_file_exits_2(self):
        code, err = self.run_judge(features_path=os.path.join(self.directory.name, "absent.json"))

        self.assertEqual(code, 2)
        self.assertIn("features: cannot read", err)

    def test_features_that_are_not_json_exit_2(self):
        code, err = self.run_judge(features_path=self.write("features.json", "{not json"))

        self.assertEqual(code, 2)
        self.assertIn("features: invalid JSON", err)

    def test_features_without_a_units_object_exit_2_with_the_key_path(self):
        code, err = self.run_judge(features_document={"owner": OWNER})

        self.assertEqual(code, 2)
        self.assertIn("features: missing key units", err)

    def test_features_with_a_unit_without_allowed_exit_2_with_the_key_path(self):
        features_document = make_features()
        del features_document["units"][ASK_KEY]["allowed"]

        code, err = self.run_judge(features_document=features_document)

        self.assertEqual(code, 2)
        self.assertIn(f"features: missing key units.{ASK_KEY}.allowed", err)

    def test_the_command_needs_both_files(self):
        parser = argparse.ArgumentParser()
        recap_judgment.add_judge_arguments(parser)

        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["--features", "features.json"])


if __name__ == "__main__":
    unittest.main()
