import json
import os

from support import ts
from test_recap_features import (
    ANNOUNCE, CHAN, CHAT_HOST, DM, GROUP_GOOD, NOW, OWNER, PEER, SLUG, TZ, at, dm, make_collection, make_config, make_stored, msg, threaded, unit,
)
from test_recap_state import FileCase, make_unit, run_cli

TEAM_CHAN = "C" + "4" * 6
PROMISE_CHAN = "C" + "5" * 6
OWES_DM = "D" + "2" * 6
ANSWERED_DM = "D" + "3" * 6

ASK_TEXT = "Can you sign off on the export plan before Monday"
MENTION_TEXT = "Please look at the incident review when you can"
TEAM_TEXT = "Does anybody own the on-call handover"
ANNOUNCE_TEXT = "Release four ships on Tuesday"
PROMISE_TEXT = "I will send the revised planning to the team"
OWES_TEXT = "Could you send the updated budget sheet"
STORED_ASK_TEXT = "Which vendor did we pick for the audit"
ANSWER_TEXT = "We picked the second vendor for the audit"

SUMMARIES = {
    "ask": "asks for sign-off on the export plan",
    "mention": "mentions you on the incident review",
    "team": "Who owns the on-call handover",
    "announce": "Release four ships on Tuesday",
    "promise": "the revised planning to the team",
    "owes": "the updated budget sheet",
    "answered": "the vendor question",
}
READING = "Sign-off on the export plan is the one blocker."


def collection_units():
    team_thread = threaded(msg(PEER, at("2026-10-15T11:00:00Z", 2), text=TEAM_TEXT, groups=[GROUP_GOOD]))
    return {
        "ask": dm(msg(PEER, at("2026-10-15T09:00:00Z", 1), text=ASK_TEXT)),
        "mention": unit(CHAN, "#ops", *threaded(msg(PEER, at("2026-10-15T10:00:00Z", 2), text=MENTION_TEXT, mentions=[OWNER]))),
        "team": unit(TEAM_CHAN, "#core", *team_thread),
        "announce": unit(ANNOUNCE, "#releases", *threaded(msg(PEER, at("2026-10-15T12:00:00Z", 3), text=ANNOUNCE_TEXT))),
        "promise": unit(PROMISE_CHAN, "#ops", *threaded(msg(OWNER, at("2026-10-15T13:00:00Z", 4), text=PROMISE_TEXT))),
        "owes": dm(msg(OWNER, at("2026-10-15T14:00:00Z", 5), text=OWES_TEXT), channel=OWES_DM),
        "answered": dm(
            msg(PEER, at("2026-10-14T10:00:00Z", 6), text=STORED_ASK_TEXT),
            msg(OWNER, at("2026-10-15T10:30:00Z", 7), text=ANSWER_TEXT),
            channel=ANSWERED_DM,
        ),
    }


KEYS = {
    "ask": f"dm-{DM}",
    "mention": f"thread-{CHAN}-{at('2026-10-15T10:00:00Z', 2)}",
    "team": f"thread-{TEAM_CHAN}-{at('2026-10-15T11:00:00Z', 2)}",
    "announce": f"thread-{ANNOUNCE}-{at('2026-10-15T12:00:00Z', 3)}",
    "promise": f"thread-{PROMISE_CHAN}-{at('2026-10-15T13:00:00Z', 4)}",
    "owes": f"dm-{OWES_DM}",
    "answered": f"dm-{ANSWERED_DM}",
}
KINDS = {
    "ask": "waiting on you",
    "mention": "waiting on you",
    "team": "team ask",
    "announce": "announcement",
    "promise": "promise",
    "owes": "you're waiting on",
    "answered": "already handled",
}
TITLES = {
    "ask": "Export plan sign-off",
    "mention": "Incident review mention",
    "team": "On-call handover owner",
    "announce": "Release four announcement",
    "promise": "Revised planning promise",
    "owes": "Budget sheet owed",
    "answered": "Vendor question answered",
}
TEXTS = (ASK_TEXT, MENTION_TEXT, TEAM_TEXT, ANNOUNCE_TEXT, PROMISE_TEXT, OWES_TEXT, STORED_ASK_TEXT, ANSWER_TEXT, *SUMMARIES.values(), READING)


def sections_of(message):
    found = {}
    for block in message.rstrip("\n").split("\n\n")[1:]:
        heading, *lines = block.split("\n")
        found[heading.strip("*")] = lines
    return found


def fragments(text, size=4):
    words = text.lower().split()
    return [" ".join(words[start:start + size]) for start in range(max(len(words) - size + 1, 1))]


def leaked(saved):
    lowered = saved.lower()
    return [text for text in TEXTS if any(fragment in lowered for fragment in fragments(text))]


class PipelineCase(FileCase):
    def setUp(self):
        super().setUp()
        self.write("config.json", make_config())
        stored = make_stored(**{KEYS["answered"]: make_unit(channel=ANSWERED_DM, status="waiting", last_ts=at("2026-10-14T10:00:00Z", 6))})
        self.write("state.json", stored)
        self.through_window()
        self.write_collection()
        self.recap("features", "--config", self.path("config.json"), "--routine", SLUG, "--state", self.path("state.json"), "--window", self.path("window.json"), "--collections", self.path("collections"), "--place", "cloud", "--out", self.path("features.json"), "--base-out", self.path("base.json"), "--rules-out", self.path("rules.json"))
        self.write("judgment.json", self.judgment())

    def recap(self, *argv, expect=0):
        code, _, err = run_cli(*argv)
        self.assertEqual(code, expect, f"{argv[0]}: {err}")
        return err

    def through_window(self):
        self.recap("window", "--state", self.path("state.json"), "--now", NOW, "--tz", TZ, "--lookback-working-days", "3", "--out", self.path("window.json"))

    def write_collection(self):
        os.makedirs(self.path("collections"))
        self.write("collections/chat.json", make_collection(self.read("window.json"), list(collection_units().values())))

    def judgment(self):
        features = self.read("features.json")
        names = {key: name for name, key in KEYS.items()}
        units = {
            key: {"kind": KINDS[names[key]], "title": TITLES[names[key]], "summary": SUMMARIES[names[key]], "blocking": names[key] == "ask", "due": None}
            for key in features["units"]
        }
        return {"units": units, "reading": [{"text": READING, "cites": [KEYS["ask"]]}]}

    def judge(self):
        return self.recap("judge", "--features", self.path("features.json"), "--judgment", self.path("judgment.json"))

    def apply(self):
        return self.recap(
            "apply", "--state", self.path("state.json"), "--features", self.path("features.json"), "--base", self.path("base.json"), "--judgment", self.path("judgment.json"),
            "--window", self.path("window.json"), "--tz", TZ, "--out", self.path("next.json"), "--summary", self.path("summary.json"), "--record", self.path("record.json"),
        )

    def message(self):
        self.recap("message", "--summary", self.path("summary.json"), "--config", self.path("config.json"), "--routine", SLUG, "--place", "cloud", "--tz", TZ, "--out", self.path("message.md"))
        with open(self.path("message.md"), encoding="utf-8") as handle:
            return handle.read()

    def raw(self, name):
        with open(self.path(name), encoding="utf-8") as handle:
            return handle.read()


class FeaturesTest(PipelineCase):
    def test_the_window_runs_from_the_stored_run_to_now(self):
        window = self.read("window.json")

        self.assertEqual((window["from_ts"], window["to_ts"], window["limited"]), (ts("2026-10-15T07:45:00Z"), ts(NOW), None))

    def test_each_unit_of_the_collection_becomes_a_unit_of_the_features(self):
        self.assertEqual(sorted(self.read("features.json")["units"]), sorted(KEYS.values()))

    def test_the_judged_kinds_are_allowed_by_the_facts(self):
        units = self.read("features.json")["units"]

        self.assertEqual([name for name, key in KEYS.items() if KINDS[name] not in units[key]["allowed"]], [])


class JudgeTest(PipelineCase):
    def test_a_judgment_built_from_the_features_passes_the_check(self):
        self.judge()

    def test_a_kind_outside_the_allowed_kinds_exits_3_naming_the_unit(self):
        judgment = self.judgment()
        judgment["units"][KEYS["announce"]]["kind"] = "waiting on you"
        self.write("judgment.json", judgment)

        err = self.recap("judge", "--features", self.path("features.json"), "--judgment", self.path("judgment.json"), expect=3)

        self.assertIn(f"units.{KEYS['announce']}.kind", err)


class MessageTest(PipelineCase):
    def setUp(self):
        super().setUp()
        self.judge()
        self.apply()
        self.text = self.message()
        self.sections = sections_of(self.text)

    def test_the_message_lists_its_sections_in_order(self):
        self.assertEqual(list(self.sections), ["Summary", "Waiting on you", "Good to know", "You're waiting on", "Already handled", "Reading"])

    def test_the_title_names_the_digest_and_the_window(self):
        self.assertEqual(self.text.split("\n\n")[0], "**chat-recap, 16 Oct 09:45 Paris**\n(since Thu 09:45)")

    def test_the_summary_counts_each_section(self):
        self.assertEqual(self.sections["Summary"][0], "- 3 waiting on you (0 late), 6 new, 1 resolved, 1 you're waiting on")

    def test_waiting_on_you_puts_the_blocking_ask_first_and_keeps_the_promise(self):
        heads = [line.split(" · ")[0] for line in self.sections["Waiting on you"]]

        self.assertEqual(
            heads,
            [
                f"- **Peer Name** {SUMMARIES['ask']}",
                f"- **Peer Name** {SUMMARIES['mention']}",
                f"- **You** promised {SUMMARIES['promise']}, no date given",
            ],
        )

    def test_a_waiting_line_links_to_the_asking_message_of_the_workspace(self):
        link = f"[DM](https://{CHAT_HOST}/archives/{DM}/p{at('2026-10-15T09:00:00Z', 1).replace('.', '')})"

        self.assertTrue(self.sections["Waiting on you"][0].endswith(link))

    def test_good_to_know_holds_the_team_ask_then_the_announcement(self):
        heads = [line.split(" · ")[0] for line in self.sections["Good to know"]]

        self.assertEqual(heads, [f"- Team ask, no answer: {SUMMARIES['team']}", f"- {SUMMARIES['announce']}"])

    def test_youre_waiting_on_names_the_counterpart(self):
        self.assertTrue(self.sections["You're waiting on"][0].startswith(f"- **Peer Name** owes {SUMMARIES['owes']} since "))

    def test_an_answered_stored_ask_is_listed_as_handled(self):
        self.assertEqual([line.split(" · ")[0] for line in self.sections["Already handled"]], [f"- {TITLES['answered']}"])

    def test_the_reading_is_the_judged_bullet(self):
        self.assertEqual(self.sections["Reading"], [f"- {READING}"])

    def test_the_message_holds_no_unit_key_and_no_json(self):
        self.assertEqual([key for key in KEYS.values() if key in self.text] + [mark for mark in ('{"', '"units"') if mark in self.text], [])

    def test_the_summary_asks_for_a_post(self):
        self.assertIs(self.read("summary.json")["post"], True)


class SavedFilesTest(PipelineCase):
    def setUp(self):
        super().setUp()
        self.judge()
        self.apply()

    def test_the_next_state_holds_no_message_text_summary_or_reading(self):
        self.assertEqual(leaked(self.raw("next.json")), [])

    def test_the_run_record_holds_no_message_text_summary_or_reading(self):
        self.assertEqual(leaked(self.raw("record.json")), [])

    def test_the_leak_check_catches_a_truncated_message_text(self):
        self.assertEqual(leaked(json.dumps({"title": ASK_TEXT[:30]})), [ASK_TEXT])

    def test_the_next_state_stores_the_answered_ask_as_handled(self):
        self.assertEqual(self.read("next.json")["units"][KEYS["answered"]]["status"], "handled")

    def test_the_next_state_stores_the_held_units_with_their_statuses(self):
        units = self.read("next.json")["units"]

        self.assertEqual({name: units[KEYS[name]]["status"] for name in ("ask", "promise", "owes")}, {"ask": "waiting", "promise": "promise", "owes": "waiting_on_others"})

    def test_the_record_lists_the_resolved_unit(self):
        self.assertEqual(self.read("record.json")["resolved"], [KEYS["answered"]])
