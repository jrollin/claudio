import json
import os
import subprocess
import sys
import unittest

import recap_features
from support import ts
from test_recap_state import FileCase, make_unit, run_cli

HERE = os.path.dirname(os.path.abspath(__file__))
SLUG = "chat-recap"
TZ = "Europe/Paris"
OWNER = "U" + "1" * 6
PEER = "U" + "2" * 6
OTHER = "U" + "3" * 6
BOT = "B" + "4" * 6
GROUP_WAITING = "S" + "1" * 6
GROUP_GOOD = "S" + "2" * 6
DM = "D" + "1" * 6
GROUP_DM = "G" + "1" * 6
CHAN = "C" + "1" * 6
ANNOUNCE = "C" + "2" * 6
EXCLUDED = "C" + "3" * 6
FROM = "2026-10-15T07:45:00Z"
NOW = "2026-10-16T07:45:00Z"
NAMES = {OWNER: "Owner Name", PEER: "Peer Name", OTHER: "Other Name", BOT: "Bot App"}
CHAT_HOST = "chat.example.test"


def at(text, fraction=100):
    return f"{ts(text)}.{fraction:06d}"


def msg(user, stamp, text="hello", root=None, bot=False, mentions=(), groups=(), **extra):
    return {"user": user, "name": NAMES[user], "bot": bot, "ts": stamp, "root_ts": root, "mentions": list(mentions), "group_mentions": list(groups), "text": text, **extra}


def unit(channel, name, *messages, participants=()):
    return {"channel": channel, "name": name, "participants": [{"id": who, "name": NAMES[who]} for who in participants], "messages": list(messages)}


def threaded(*messages):
    root = messages[0]["ts"]
    return [{**item, "root_ts": item["root_ts"] or root} for item in messages]


def dm(*messages, channel=DM):
    return unit(channel, "DM", *messages, participants=(OWNER, PEER))


def make_routine():
    transport = {"cloud": "api", "local": "api"}
    return {
        "engine": "recap",
        "owner": OWNER,
        "workspace": CHAT_HOST,
        "window": {"lookback_working_days": 3},
        "groups": [
            {"id": GROUP_WAITING, "label": "Core team", "lands_in": "waiting"},
            {"id": GROUP_GOOD, "label": "Everyone", "lands_in": "good_to_know"},
        ],
        "announcement": {"channels": [ANNOUNCE], "topics": ["releases"]},
        "exclude": {"authors": [OTHER], "channels": [EXCLUDED], "keep_bots": []},
        "rules": ["An ask needs a reply from the owner."],
        "sources": {
            "chat": {
                "provider": "chat",
                "transport": transport,
                "owner": OWNER,
                "searches": [{"name": "dms", "filters": "is:dm", "since": "window"}],
                "reactions": True,
            }
        },
    }


def make_config(**changes):
    routine = {**make_routine(), **changes}
    return {
        "timezone": TZ,
        "places": {"cloud": {"runtime_dir": "/opt/runtime", "state_dir": "/opt/state"}, "local": {"runtime_dir": "/srv/runtime", "state_dir": "/srv/state"}},
        "providers": {
            "chat": {
                "adapter": "slack",
                "api": {"base_url": "https://" + CHAT_HOST, "credentials": {"token": "CHAT_TOKEN"}},
                "mcp": {"connectors": {"cloud": "chat-cloud", "local": "chat-local"}},
            }
        },
        "routines": {SLUG: routine},
    }


def make_stored(**units):
    document = {
        "schema": 1,
        "digest": SLUG,
        "run": {"at": FROM, "previous_at": None, "window": None},
        "units": units,
        "blind_spots": [],
    }
    return document


def make_window(now=NOW, **fields):
    return {"from_ts": ts(FROM), "to_ts": ts(now), "limited": None, "explicit": False, **fields}


def make_collection(window, units, entries=None, read=True, reason=None):
    return {
        "schema": 1,
        "source": "chat",
        "role": "chat",
        "provider": "chat",
        "transport": "api",
        "place": "cloud",
        "window": {"from_ts": window["from_ts"], "to_ts": window["to_ts"]},
        "read": read,
        "reason": reason,
        "cursor": {"ts": {}} if read else None,
        "records": {"messages": [], "units": units if read else []},
        "entries": entries or {},
    }


class FeaturesCase(FileCase):
    def run_features(self, *units, config=None, stored=None, window=None, entries=None, read=True, reason=None, extra=()):
        window = window or make_window()
        self.write("config.json", config or make_config())
        self.write("state.json", stored or make_stored())
        self.write("window.json", window)
        os.makedirs(self.path("collections"), exist_ok=True)
        self.write("collections/chat.json", make_collection(window, list(units), entries, read, reason))
        return run_cli(
            "features", "--config", self.path("config.json"), "--routine", SLUG, "--state", self.path("state.json"), "--window", self.path("window.json"),
            "--collections", self.path("collections"), "--place", "cloud", "--out", self.path("features.json"), "--base-out", self.path("base.json"),
            "--rules-out", self.path("rules.json"), *extra,
        )

    def computed(self, *units, **options):
        code, _, err = self.run_features(*units, **options)
        self.assertEqual((code, err), (0, ""))
        return self.read("features.json")

    def units_of(self, *units, **options):
        return self.computed(*units, **options)["units"]

    def one(self, *units, **options):
        found = self.units_of(*units, **options)
        self.assertEqual(len(found), 1)
        return next(iter(found.values()))

    def facts(self, *messages, channel=CHAN, name="#ops", **options):
        return self.one(unit(channel, name, *threaded(*messages)), **options)["facts"]


class UnitKeyTest(FeaturesCase):
    def test_a_direct_conversation_is_one_dm_unit(self):
        found = self.units_of(dm(msg(PEER, at("2026-10-15T09:00:00Z"))))

        self.assertEqual({key: item["kind"] for key, item in found.items()}, {f"dm-{DM}": "dm"})

    def test_a_group_conversation_is_one_dm_unit_of_kind_group_dm(self):
        found = self.units_of(unit(GROUP_DM, "group DM", msg(PEER, at("2026-10-15T09:00:00Z")), participants=(OWNER, PEER, OTHER)))

        self.assertEqual({key: item["kind"] for key, item in found.items()}, {f"dm-{GROUP_DM}": "group_dm"})

    def test_a_thread_is_one_unit_keyed_by_its_root(self):
        root, reply = at("2026-10-15T09:00:00Z", 1), at("2026-10-15T09:05:00Z", 2)
        found = self.units_of(unit(CHAN, "#ops", msg(OWNER, root, root=root), msg(PEER, reply, root=root)))

        self.assertEqual({key: len(item["messages"]) for key, item in found.items()}, {f"thread-{CHAN}-{root}": 2})

    def test_a_single_channel_message_is_a_unit_keyed_by_its_own_ts(self):
        stamp = at("2026-10-15T09:00:00Z")

        self.assertEqual(list(self.units_of(unit(CHAN, "#ops", msg(PEER, stamp)))), [f"thread-{CHAN}-{stamp}"])

    def test_a_thread_found_by_two_records_is_one_unit_without_a_repeated_message(self):
        root, reply = at("2026-10-15T09:00:00Z", 1), at("2026-10-15T09:05:00Z", 2)
        first = unit(CHAN, "#ops", msg(PEER, reply, root=root))
        second = unit(CHAN, "#ops", msg(OWNER, root, root=root), msg(PEER, reply, root=root))

        found = self.units_of(first, second)

        self.assertEqual({key: [item["ts"] for item in value["messages"]] for key, value in found.items()}, {f"thread-{CHAN}-{root}": [root, reply]})

    def test_a_reaction_read_on_one_copy_of_a_message_is_kept(self):
        root, reply = at("2026-10-15T09:00:00Z", 1), at("2026-10-15T09:05:00Z", 2)
        first = unit(CHAN, "#ops", msg(PEER, reply, root=root))
        second = unit(CHAN, "#ops", msg(PEER, reply, root=root, owner_reacted=True))

        self.assertIs(self.one(first, second)["messages"][0]["owner_reacted"], True)

    def test_a_channel_record_with_two_roots_gives_two_units(self):
        first, second = at("2026-10-15T09:00:00Z", 1), at("2026-10-15T10:00:00Z", 2)
        found = self.units_of(unit(CHAN, "#ops", msg(PEER, first), msg(PEER, second)))

        self.assertEqual(sorted(found), [f"thread-{CHAN}-{first}", f"thread-{CHAN}-{second}"])

    def test_a_conversation_keeps_the_messages_of_its_threads_in_one_unit(self):
        root, reply = at("2026-10-15T09:00:00Z", 1), at("2026-10-15T09:05:00Z", 2)
        found = self.units_of(dm(msg(PEER, root, root=root), msg(OWNER, reply, root=root)))

        self.assertEqual({key: len(item["messages"]) for key, item in found.items()}, {f"dm-{DM}": 2})

    def test_messages_come_oldest_first(self):
        early, late = at("2026-10-15T09:00:00Z"), at("2026-10-15T09:30:00Z")

        stamps = [item["ts"] for item in self.one(dm(msg(PEER, late), msg(OWNER, early)))["messages"]]

        self.assertEqual(stamps, [early, late])


class ExclusionTest(FeaturesCase):
    def test_drops_the_messages_of_an_excluded_author(self):
        record = dm(msg(PEER, at("2026-10-15T09:00:00Z")), msg(OTHER, at("2026-10-15T09:10:00Z")))

        self.assertEqual([item["user"] for item in self.one(record)["messages"]], [PEER])

    def test_drops_a_bot_message_by_default(self):
        record = dm(msg(PEER, at("2026-10-15T09:00:00Z")), msg(BOT, at("2026-10-15T09:10:00Z"), bot=True))

        self.assertEqual([item["user"] for item in self.one(record)["messages"]], [PEER])

    def test_keeps_the_messages_of_a_bot_the_routine_keeps(self):
        config = make_config(exclude={"authors": [], "channels": [], "keep_bots": [BOT]})
        record = dm(msg(PEER, at("2026-10-15T09:00:00Z")), msg(BOT, at("2026-10-15T09:10:00Z"), bot=True))

        self.assertEqual([item["user"] for item in self.one(record, config=config)["messages"]], [PEER, BOT])

    def test_drops_a_unit_left_without_a_message(self):
        self.assertEqual(self.units_of(dm(msg(OTHER, at("2026-10-15T09:00:00Z")))), {})

    def test_drops_the_units_of_an_excluded_channel(self):
        self.assertEqual(self.units_of(unit(EXCLUDED, "#noise", msg(PEER, at("2026-10-15T09:00:00Z")))), {})

    def test_a_message_of_an_excluded_author_counts_as_nobodys(self):
        record = dm(msg(OWNER, at("2026-10-15T09:00:00Z")), msg(OTHER, at("2026-10-15T09:10:00Z")))

        facts = self.one(record)["facts"]

        self.assertEqual((facts["last_author_is_owner"], facts["unanswered_from"]), (True, None))

    def test_keeps_the_other_units(self):
        found = self.units_of(unit(EXCLUDED, "#noise", msg(PEER, at("2026-10-15T09:00:00Z"))), dm(msg(PEER, at("2026-10-15T09:00:00Z"))))

        self.assertEqual(list(found), [f"dm-{DM}"])


class FactTest(FeaturesCase):
    EARLY, MID, LATE = at("2026-10-15T09:00:00Z", 1), at("2026-10-15T10:00:00Z", 2), at("2026-10-15T11:00:00Z", 3)

    def test_the_owner_wrote_last(self):
        self.assertIs(self.facts(msg(PEER, self.EARLY), msg(OWNER, self.MID))["last_author_is_owner"], True)

    def test_someone_else_wrote_last(self):
        self.assertIs(self.facts(msg(OWNER, self.EARLY), msg(PEER, self.MID))["last_author_is_owner"], False)

    def test_unanswered_from_is_the_first_message_of_someone_else_after_the_owner_last_message(self):
        facts = self.facts(msg(OWNER, self.EARLY), msg(PEER, self.MID), msg(PEER, self.LATE))

        self.assertEqual(facts["unanswered_from"], self.MID)

    def test_unanswered_from_is_the_first_message_when_the_owner_never_wrote(self):
        self.assertEqual(self.facts(msg(PEER, self.EARLY), msg(PEER, self.MID))["unanswered_from"], self.EARLY)

    def test_a_reply_of_the_owner_answers(self):
        self.assertIsNone(self.facts(msg(PEER, self.EARLY), msg(OWNER, self.MID))["unanswered_from"])

    def test_a_reaction_of_the_owner_answers_the_message_it_is_on(self):
        self.assertIsNone(self.facts(msg(PEER, self.EARLY, owner_reacted=True))["unanswered_from"])

    def test_a_reaction_leaves_the_later_messages_unanswered(self):
        facts = self.facts(msg(PEER, self.EARLY, owner_reacted=True), msg(PEER, self.MID, owner_reacted=False))

        self.assertEqual(facts["unanswered_from"], self.MID)

    def test_a_reaction_after_the_owner_last_message_moves_the_start_past_it(self):
        facts = self.facts(msg(OWNER, self.EARLY), msg(PEER, self.MID, owner_reacted=True), msg(PEER, self.LATE))

        self.assertEqual(facts["unanswered_from"], self.LATE)

    def test_the_owner_answered_by_a_reply(self):
        self.assertIs(self.facts(msg(PEER, self.EARLY), msg(OWNER, self.MID))["owner_answered"], True)

    def test_the_owner_answered_by_a_reaction_on_the_last_message(self):
        self.assertIs(self.facts(msg(PEER, self.EARLY), msg(PEER, self.MID, owner_reacted=True))["owner_answered"], True)

    def test_the_owner_did_not_answer_a_message_left_unanswered(self):
        self.assertIs(self.facts(msg(PEER, self.EARLY, owner_reacted=False))["owner_answered"], False)

    def test_the_owner_did_not_answer_when_a_newer_message_is_unanswered(self):
        facts = self.facts(msg(PEER, self.EARLY, owner_reacted=True), msg(PEER, self.MID))

        self.assertIs(facts["owner_answered"], False)

    def test_the_owner_answered_nothing_in_a_unit_he_alone_wrote_in(self):
        self.assertIs(self.facts(msg(OWNER, self.EARLY))["owner_answered"], False)

    def test_a_group_mention_is_listed_with_its_landing(self):
        facts = self.facts(msg(PEER, self.EARLY, groups=[GROUP_GOOD]))

        self.assertEqual([(item["id"], item["label"], item["lands_in"]) for item in facts["groups"]], [(GROUP_GOOD, "Everyone", "good_to_know")])

    def test_lists_the_groups_in_the_routine_order(self):
        facts = self.facts(msg(PEER, self.EARLY, groups=[GROUP_GOOD, GROUP_WAITING]))

        self.assertEqual([item["id"] for item in facts["groups"]], [GROUP_WAITING, GROUP_GOOD])

    def test_a_group_id_written_as_plain_text_is_no_group_mention(self):
        self.assertEqual(self.facts(msg(PEER, self.EARLY, text=f"ask {GROUP_WAITING} and subteam^{GROUP_GOOD}"))["groups"], [])

    def test_an_owner_id_written_as_plain_text_is_no_direct_mention(self):
        self.assertIs(self.facts(msg(PEER, self.EARLY, text=f"see {OWNER} and @{OWNER}"))["direct_mention"], False)

    def test_the_mentions_of_two_copies_of_a_message_are_joined(self):
        stamp = self.EARLY
        first = unit(CHAN, "#ops", msg(PEER, stamp, mentions=[OWNER], groups=[GROUP_GOOD]))
        second = unit(CHAN, "#ops", msg(PEER, stamp, mentions=[OTHER], groups=[GROUP_WAITING]))

        found = self.one(first, second)["messages"][0]

        self.assertEqual((found["mentions"], found["group_mentions"]), (sorted([OWNER, OTHER]), sorted([GROUP_WAITING, GROUP_GOOD])))

    def test_a_group_the_routine_does_not_list_is_ignored(self):
        self.assertEqual(self.facts(msg(PEER, self.EARLY, groups=["S999999"]))["groups"], [])

    def test_a_group_mention_of_the_owner_is_not_an_ask(self):
        facts = self.facts(msg(OWNER, self.EARLY, groups=[GROUP_WAITING]))

        self.assertEqual(facts["groups"], [])

    def test_a_group_ask_with_only_an_excluded_reply_is_unanswered(self):
        facts = self.facts(msg(PEER, self.EARLY, groups=[GROUP_GOOD]), msg(OTHER, self.MID))

        self.assertIs(facts["groups"][0]["answered"], False)

    def test_a_group_ask_with_only_a_follow_up_of_its_author_is_unanswered(self):
        facts = self.facts(msg(PEER, self.EARLY, groups=[GROUP_GOOD]), msg(PEER, self.MID, text="anyone?"))

        self.assertIs(facts["groups"][0]["answered"], False)

    def test_a_group_ask_with_a_reply_from_another_author_is_answered(self):
        config = make_config(exclude={"authors": [], "channels": [], "keep_bots": []})

        facts = self.facts(msg(PEER, self.EARLY, groups=[GROUP_GOOD]), msg(OTHER, self.MID), config=config)

        self.assertIs(facts["groups"][0]["answered"], True)

    def test_a_direct_mention_of_the_owner_in_a_message_of_someone_else(self):
        self.assertIs(self.facts(msg(PEER, self.EARLY, mentions=[OWNER]))["direct_mention"], True)

    def test_a_mention_in_a_message_of_the_owner_is_no_direct_mention(self):
        self.assertIs(self.facts(msg(OWNER, self.EARLY, mentions=[OWNER]))["direct_mention"], False)

    def test_another_user_mention_is_no_direct_mention(self):
        self.assertIs(self.facts(msg(PEER, self.EARLY, mentions=[OTHER]))["direct_mention"], False)

    def test_a_unit_of_an_announcement_channel(self):
        found = self.facts(msg(PEER, self.EARLY), channel=ANNOUNCE)

        self.assertEqual((found["announcement_channel"], self.facts(msg(PEER, self.EARLY))["announcement_channel"]), (True, False))

    def test_the_owner_took_part_when_he_wrote(self):
        self.assertEqual(
            (self.facts(msg(PEER, self.EARLY), msg(OWNER, self.MID))["owner_took_part"], self.facts(msg(PEER, self.EARLY))["owner_took_part"]),
            (True, False),
        )

    def test_the_owner_last_ts_is_the_latest_owner_message_read(self):
        facts = self.facts(msg(OWNER, self.EARLY), msg(PEER, self.MID), msg(OWNER, self.LATE))

        self.assertEqual(facts["owner_last_ts"], self.LATE)

    def test_the_owner_last_ts_is_the_latest_owner_reaction_read(self):
        facts = self.facts(msg(PEER, self.EARLY), msg(PEER, self.MID, owner_reacted=True), msg(PEER, self.LATE, owner_reacted=False))

        self.assertEqual(facts["owner_last_ts"], self.MID)

    def test_the_owner_last_ts_is_null_without_an_owner_message_or_reaction(self):
        self.assertIsNone(self.facts(msg(PEER, self.EARLY), msg(PEER, self.MID, owner_reacted=False))["owner_last_ts"])

    def stored_thread(self, owner_last_ts):
        fields = {} if owner_last_ts == "absent" else {"owner_last_ts": owner_last_ts}
        return make_stored(**{f"thread-{CHAN}-{self.EARLY}": make_unit(channel=CHAN, kind="thread", last_ts=self.MID, **fields)})

    def test_a_peer_message_after_the_stored_owner_activity_asks_again(self):
        facts = self.facts(msg(PEER, self.EARLY), msg(PEER, self.LATE), stored=self.stored_thread(self.MID), config=make_config(thread_reads="since"))

        self.assertEqual((facts["unanswered_from"], facts["owner_answered"]), (self.LATE, False))

    def test_peer_messages_before_the_stored_owner_activity_leave_nothing_waiting(self):
        facts = self.facts(msg(PEER, self.EARLY), msg(PEER, self.MID), stored=self.stored_thread(self.LATE), config=make_config(thread_reads="since"))

        self.assertEqual((facts["unanswered_from"], facts["owner_answered"]), (None, True))

    def test_the_owner_took_part_from_the_stored_activity_alone(self):
        facts = self.facts(msg(PEER, self.EARLY), stored=self.stored_thread(self.MID), config=make_config(thread_reads="since"))

        self.assertIs(facts["owner_took_part"], True)

    def test_full_reads_leave_out_the_stored_owner_activity(self):
        facts = self.facts(msg(PEER, self.EARLY), msg(PEER, self.MID), stored=self.stored_thread(self.LATE), config=make_config(thread_reads="full"))

        self.assertEqual((facts["unanswered_from"], facts["owner_took_part"]), (self.EARLY, False))

    def test_a_routine_without_thread_reads_leaves_out_the_stored_owner_activity(self):
        facts = self.facts(msg(PEER, self.EARLY), msg(PEER, self.MID), stored=self.stored_thread(self.LATE))

        self.assertEqual((facts["unanswered_from"], facts["owner_took_part"]), (self.EARLY, False))

    def test_a_stored_null_owner_activity_leaves_the_facts_unchanged(self):
        facts = self.facts(msg(PEER, self.EARLY), msg(PEER, self.MID), stored=self.stored_thread(None))

        self.assertEqual((facts["unanswered_from"], facts["owner_took_part"]), (self.EARLY, False))

    def test_a_stored_unit_without_the_owner_last_ts_leaves_the_facts_unchanged(self):
        facts = self.facts(msg(PEER, self.EARLY), msg(PEER, self.MID), stored=self.stored_thread("absent"))

        self.assertEqual((facts["unanswered_from"], facts["owner_took_part"]), (self.EARLY, False))

    def test_the_owner_last_ts_fact_leaves_out_the_stored_activity(self):
        facts = self.facts(msg(PEER, self.EARLY), msg(PEER, self.LATE), stored=self.stored_thread(self.MID))

        self.assertIsNone(facts["owner_last_ts"])

    def test_the_previous_unit_is_the_stored_one(self):
        stamp = self.EARLY
        previous = make_unit(channel=CHAN, kind="thread", last_ts=stamp)

        facts = self.facts(msg(PEER, stamp), stored=make_stored(**{f"thread-{CHAN}-{stamp}": previous}))

        self.assertEqual(facts["previous"], previous)

    def test_the_previous_unit_is_null_for_a_new_unit(self):
        self.assertIsNone(self.facts(msg(PEER, self.EARLY))["previous"])

    def test_a_mention_before_the_owner_last_message_still_counts_as_a_fact(self):
        facts = self.facts(msg(PEER, self.EARLY, mentions=[OWNER]), msg(OWNER, self.MID))

        self.assertEqual((facts["direct_mention"], facts["unanswered_from"]), (True, None))


class AgeTest(FeaturesCase):
    def age(self, asked, now, tz=TZ):
        stamp = at(asked)
        config = make_config()
        config["timezone"] = tz
        window = make_window(now)
        return self.facts(msg(PEER, stamp), config=config, window=window)["age_working_days"]

    def test_is_null_without_an_unanswered_message(self):
        self.assertIsNone(self.facts(msg(OWNER, at("2026-10-15T09:00:00Z")))["age_working_days"])

    def test_counts_the_working_days_after_the_ask_up_to_the_window_end(self):
        self.assertEqual(self.age("2026-10-13T09:00:00Z", "2026-10-16T07:45:00Z"), 3)

    def test_is_zero_on_the_day_of_the_ask(self):
        self.assertEqual(self.age("2026-10-16T05:00:00Z", "2026-10-16T07:45:00Z"), 0)

    def test_does_not_count_a_weekend(self):
        self.assertEqual(self.age("2026-10-16T15:00:00Z", "2026-10-19T08:00:00Z"), 1)

    def test_counts_the_same_days_across_the_daylight_saving_change(self):
        self.assertEqual(self.age("2026-10-22T10:00:00Z", "2026-10-27T10:00:00Z"), 3)

    def test_counts_the_same_days_for_an_ask_sent_late_on_the_eve_of_the_daylight_saving_change(self):
        self.assertEqual(self.age("2026-10-24T22:30:00Z", "2026-10-27T10:00:00Z"), 2)

    def test_reads_the_local_date_of_an_ask_sent_late_in_utc(self):
        self.assertEqual(self.age("2026-10-15T22:30:00Z", "2026-10-16T07:45:00Z"), 0)

    def test_reads_the_local_date_in_the_config_timezone(self):
        self.assertEqual(self.age("2026-10-15T22:30:00Z", "2026-10-16T07:45:00Z", tz="America/Los_Angeles"), 1)


class ThreadKindTest(FeaturesCase):
    STAMP = at("2026-10-15T09:00:00Z")

    def kind(self, **fields):
        return self.one(unit(CHAN, "#ops", msg(PEER, self.STAMP, **fields)))["kind"]

    def test_a_direct_mention_makes_a_mention(self):
        self.assertEqual(self.kind(mentions=[OWNER]), "mention")

    def test_a_group_mention_makes_a_group(self):
        self.assertEqual(self.kind(groups=[GROUP_GOOD]), "group")

    def test_neither_makes_a_thread(self):
        self.assertEqual(self.kind(), "thread")

    def test_a_direct_mention_wins_over_a_group(self):
        self.assertEqual(self.kind(mentions=[OWNER], groups=[GROUP_GOOD]), "mention")


class AllowedTest(FeaturesCase):
    EARLY, MID, LATE = at("2026-10-15T09:00:00Z", 1), at("2026-10-15T10:00:00Z", 2), at("2026-10-15T11:00:00Z", 3)

    def allowed(self, *messages, channel=CHAN, name="#ops", **options):
        return self.one(unit(channel, name, *threaded(*messages)), **options)["allowed"]

    def test_noise_is_always_allowed_and_alone_for_a_thread_the_owner_has_no_part_in(self):
        self.assertEqual(self.allowed(msg(PEER, self.EARLY, text="fyi")), ["noise"])

    def test_an_unanswered_direct_conversation_allows_waiting_on_you(self):
        self.assertEqual(self.one(dm(msg(PEER, self.EARLY)))["allowed"], ["waiting on you", "noise"])

    def test_an_unanswered_group_conversation_allows_waiting_on_you(self):
        record = unit(GROUP_DM, "group DM", msg(PEER, self.EARLY), participants=(OWNER, PEER))

        self.assertEqual(self.one(record)["allowed"], ["waiting on you", "noise"])

    def test_a_direct_mention_allows_waiting_on_you(self):
        self.assertEqual(self.allowed(msg(PEER, self.EARLY, mentions=[OWNER])), ["waiting on you", "noise"])

    def test_a_group_landing_in_waiting_allows_waiting_on_you(self):
        self.assertEqual(self.allowed(msg(PEER, self.EARLY, groups=[GROUP_WAITING])), ["waiting on you", "noise"])

    def test_a_thread_the_owner_took_part_in_allows_waiting_on_you(self):
        root = self.EARLY
        allowed = self.allowed(msg(OWNER, root, root=root), msg(PEER, self.MID, root=root))

        self.assertEqual(allowed, ["waiting on you", "noise"])

    def test_an_answered_direct_conversation_forbids_waiting_on_you(self):
        self.assertNotIn("waiting on you", self.one(dm(msg(PEER, self.EARLY), msg(OWNER, self.MID)))["allowed"])

    def test_an_ask_to_a_good_to_know_group_nobody_answered_allows_team_ask_only(self):
        self.assertEqual(self.allowed(msg(PEER, self.EARLY, groups=[GROUP_GOOD])), ["team ask", "noise"])

    def test_a_good_to_know_ask_someone_answered_forbids_team_ask(self):
        config = make_config(exclude={"authors": [], "channels": [], "keep_bots": []})
        allowed = self.allowed(msg(PEER, self.EARLY, groups=[GROUP_GOOD]), msg(OTHER, self.MID), config=config)

        self.assertEqual(allowed, ["noise"])

    def test_a_good_to_know_ask_the_owner_answered_forbids_team_ask(self):
        allowed = self.allowed(msg(PEER, self.EARLY, groups=[GROUP_GOOD]), msg(OWNER, self.MID))

        self.assertNotIn("team ask", allowed)

    def test_an_owner_last_message_allows_waiting_on_others_promise_and_handled(self):
        self.assertEqual(self.one(dm(msg(PEER, self.EARLY), msg(OWNER, self.MID)))["allowed"], ["you're waiting on", "promise", "already handled", "noise"])

    def stored_dm(self, status):
        return make_stored(**{f"dm-{DM}": make_unit(channel=DM, status=status)})

    def test_a_stored_waiting_unit_still_unanswered_allows_already_handled(self):
        allowed = self.one(dm(msg(PEER, self.EARLY)), stored=self.stored_dm("waiting"))["allowed"]

        self.assertEqual(allowed, ["waiting on you", "already handled", "noise"])

    def test_a_stored_promise_unit_still_unanswered_allows_already_handled(self):
        self.assertIn("already handled", self.one(dm(msg(PEER, self.EARLY)), stored=self.stored_dm("promise"))["allowed"])

    def handled_with_stored(self, status):
        return "already handled" in self.one(dm(msg(PEER, self.EARLY)), stored=self.stored_dm(status))["allowed"]

    def test_a_stored_waiting_on_others_unit_still_unanswered_forbids_already_handled(self):
        self.assertFalse(self.handled_with_stored("waiting_on_others"))

    def test_a_stored_team_ask_unit_still_unanswered_forbids_already_handled(self):
        self.assertFalse(self.handled_with_stored("team_ask"))

    def test_a_stored_handled_unit_still_unanswered_forbids_already_handled(self):
        self.assertFalse(self.handled_with_stored("handled"))

    def test_a_stored_announcement_unit_still_unanswered_forbids_already_handled(self):
        self.assertFalse(self.handled_with_stored("announcement"))

    def test_a_new_unit_the_owner_answered_by_a_reply_allows_already_handled(self):
        self.assertIn("already handled", self.one(dm(msg(PEER, self.EARLY), msg(OWNER, self.MID)))["allowed"])

    def test_a_new_unit_the_owner_answered_by_a_reaction_allows_already_handled(self):
        self.assertEqual(self.one(dm(msg(PEER, self.EARLY, owner_reacted=True)))["allowed"], ["already handled", "noise"])

    def test_a_reaction_on_an_older_message_while_a_newer_one_is_unanswered_forbids_already_handled(self):
        allowed = self.one(dm(msg(PEER, self.EARLY, owner_reacted=True), msg(PEER, self.MID, owner_reacted=False)))["allowed"]

        self.assertEqual(allowed, ["waiting on you", "noise"])

    def test_a_message_the_owner_did_not_react_to_forbids_already_handled(self):
        self.assertNotIn("already handled", self.one(dm(msg(PEER, self.EARLY, owner_reacted=False)))["allowed"])

    def test_a_unit_holding_only_messages_of_the_owner_forbids_already_handled(self):
        self.assertNotIn("already handled", self.one(dm(msg(OWNER, self.EARLY)))["allowed"])

    def test_an_announcement_channel_allows_announcement(self):
        self.assertEqual(self.allowed(msg(PEER, self.EARLY, text="release"), channel=ANNOUNCE), ["announcement", "noise"])

    def test_an_announcement_unit_holding_only_the_owner_message_allows_no_handled_kind(self):
        allowed = self.allowed(msg(OWNER, self.EARLY, text="release"), channel=ANNOUNCE)

        self.assertEqual(allowed, ["you're waiting on", "promise", "announcement", "noise"])


class BlindSpotTest(FeaturesCase):
    STAMP = at("2026-10-15T09:00:00Z")

    def spots(self, *units, **options):
        return self.computed(*units, **options)["blind_spots"]

    def test_a_search_cut_by_the_page_cap_keeps_its_units_and_reports_the_cut(self):
        entries = {"search:dms": {"status": "failed", "reason": "page cap: 3 page(s) read"}}

        doc = self.computed(dm(msg(PEER, self.STAMP)), entries=entries)

        self.assertEqual((list(doc["units"]), doc["blind_spots"]), ([f"dm-{DM}"], [{"key": "search:dms", "gap": "search dms cut: 3 page(s) read"}]))

    def test_another_failed_entry_names_its_key_and_reason(self):
        entries = {DM: {"status": "failed", "reason": "channel_not_found"}}

        self.assertEqual(self.spots(entries=entries), [{"key": DM, "gap": f"{DM}: channel_not_found"}])

    def test_a_failed_reactions_read_is_a_blind_spot(self):
        key = f"reactions:{DM}:{self.STAMP}"
        entries = {key: {"status": "failed", "reason": "message_not_found"}}

        self.assertEqual(self.spots(entries=entries), [{"key": key, "gap": f"{key}: message_not_found"}])

    def test_a_search_failure_that_is_not_a_cut_keeps_its_reason(self):
        entries = {"search:dms": {"status": "failed", "reason": "boom"}}

        self.assertEqual(self.spots(entries=entries), [{"key": "search:dms", "gap": "search:dms: boom"}])

    def test_an_unread_source_is_a_blind_spot_with_its_reason(self):
        self.assertEqual(self.spots(read=False, reason="provider unreachable"), [{"key": "chat", "gap": "provider unreachable"}])

    def test_an_unread_source_adds_no_unit(self):
        self.assertEqual(self.units_of(read=False, reason="provider unreachable"), {})

    def test_a_deferred_or_ok_entry_is_no_blind_spot(self):
        entries = {"a": {"status": "ok", "reason": None}, "b": {"status": "deferred", "reason": "known gap"}}

        self.assertEqual(self.spots(entries=entries), [])

    def test_sorts_the_blind_spots_by_key(self):
        entries = {"search:b": {"status": "failed", "reason": "page cap: 2 page(s) read"}, "search:a": {"status": "failed", "reason": "page cap: 1 page(s) read"}}

        self.assertEqual([item["key"] for item in self.spots(entries=entries)], ["search:a", "search:b"])

    def test_a_missing_collection_is_an_unread_source(self):
        self.write("config.json", make_config())
        self.write("state.json", make_stored())
        self.write("window.json", make_window())
        os.makedirs(self.path("collections"))

        code, _, err = run_cli(
            "features", "--config", self.path("config.json"), "--routine", SLUG, "--state", self.path("state.json"), "--window", self.path("window.json"),
            "--collections", self.path("collections"), "--place", "cloud", "--out", self.path("features.json"), "--base-out", self.path("base.json"),
            "--rules-out", self.path("rules.json"),
        )

        self.assertEqual((code, err, self.read("features.json")["blind_spots"]), (0, "", [{"key": "chat", "gap": "no collection"}]))


class FilesTest(FeaturesCase):
    FIRST, SECOND = at("2026-10-15T09:00:00Z", 1), at("2026-10-15T09:30:00Z", 2)
    SECRET = "quarterly figures are due"

    def setUp(self):
        super().setUp()
        self.record = dm(msg(PEER, self.FIRST, text=self.SECRET), msg(OWNER, self.SECOND, text="on it"))
        self.features = self.computed(self.record)

    def test_features_hold_the_owner_the_window_and_the_message_text(self):
        found = self.features["units"][f"dm-{DM}"]

        self.assertEqual(
            (self.features["owner"], self.features["window"], [item["text"] for item in found["messages"]]),
            (OWNER, make_window(), [self.SECRET, "on it"]),
        )

    def test_features_hold_the_facts_and_the_allowed_kinds_of_a_unit(self):
        found = self.features["units"][f"dm-{DM}"]

        self.assertEqual(
            (found["kind"], found["channel"], found["name"], sorted(found["facts"]), found["allowed"]),
            (
                "dm", DM, "DM",
                ["age_working_days", "announcement_channel", "direct_mention", "groups", "last_author_is_owner", "owner_answered", "owner_last_ts", "owner_took_part", "previous", "unanswered_from"],
                ["you're waiting on", "promise", "already handled", "noise"],
            ),
        )

    def test_base_holds_the_unit_channel_name_participants_and_authors(self):
        base = self.read("base.json")["units"]

        self.assertEqual(
            base,
            {
                f"dm-{DM}": {
                    "channel": DM,
                    "name": "DM",
                    "participants": [{"id": OWNER, "name": "Owner Name"}, {"id": PEER, "name": "Peer Name"}],
                    "authors": [{"id": OWNER, "name": "Owner Name"}, {"id": PEER, "name": "Peer Name"}],
                }
            },
        )

    def test_base_holds_no_message_text(self):
        with open(self.path("base.json"), encoding="utf-8") as handle:
            text = handle.read()

        self.assertEqual((self.SECRET in text, "on it" in text), (False, False))

    def test_base_holds_the_source_rows_models_and_blind_spots(self):
        base = self.read("base.json")

        self.assertEqual(
            (base["sources"], base["models"], base["blind_spots"]),
            ([{"source": "chat", "role": "chat", "read": True, "reason": None, "from_ts": ts(FROM), "to_ts": ts(NOW)}], {}, []),
        )

    def test_rules_hold_the_ask_rules_and_the_kind_definitions(self):
        rules = self.read("rules.json")

        self.assertEqual(
            (rules["rules"], sorted(rules["kinds"]), rules["announcement_topics"]),
            (["An ask needs a reply from the owner."], sorted(["waiting on you", "team ask", "you're waiting on", "promise", "already handled", "announcement", "noise"]), ["releases"]),
        )

    def test_writes_canonical_base_and_compact_features(self):
        self.assert_canonical("base.json")
        with open(self.path("features.json"), "rb") as handle:
            raw = handle.read()
        self.assertEqual(raw, (json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8"))

    def test_the_same_run_writes_the_same_bytes(self):
        with open(self.path("features.json"), "rb") as handle:
            first = handle.read()
        self.run_features(self.record)
        with open(self.path("features.json"), "rb") as handle:
            self.assertEqual(handle.read(), first)


class RoutineKeyTest(FeaturesCase):
    def test_an_invalid_routine_key_exits_2_naming_its_key_path(self):
        config = make_config(owner="")

        code, _, err = self.run_features(config=config)

        self.assertEqual((code, "routines.chat-recap.owner: must be a non-empty string" in err), (2, True))

    def test_exclude_lists_left_out_read_as_empty(self):
        config = make_config(exclude={})

        self.assertEqual(self.run_features(config=config)[0], 0)

    def test_an_announcement_without_channels_or_topics_reads_as_empty(self):
        config = make_config(announcement={})

        self.assertEqual(self.run_features(config=config)[0], 0)


class CommandTest(FeaturesCase):
    def test_exits_0_and_writes_the_three_files(self):
        self.assertEqual(self.run_features(dm(msg(PEER, at("2026-10-15T09:00:00Z"))))[0], 0)
        self.assertEqual([os.path.exists(self.path(name)) for name in ("features.json", "base.json", "rules.json")], [True, True, True])

    def test_a_routine_of_another_engine_exits_2(self):
        config = make_config()
        del config["routines"][SLUG]["engine"]

        code, _, err = self.run_features(config=config)

        self.assertEqual((code, f"config: routine {SLUG} is not a recap routine" in err), (2, True))

    def test_an_unknown_routine_exits_2(self):
        self.run_features()
        code, _, err = run_cli(
            "features", "--config", self.path("config.json"), "--routine", "other", "--state", self.path("state.json"), "--window", self.path("window.json"),
            "--collections", self.path("collections"), "--place", "cloud", "--out", self.path("f.json"), "--base-out", self.path("b.json"), "--rules-out", self.path("r.json"),
        )

        self.assertEqual(code, 2)

    def test_a_missing_state_file_exits_2(self):
        self.run_features()
        os.remove(self.path("state.json"))

        code, _, err = run_cli(*self.arguments())

        self.assertEqual((code, "state: cannot read" in err), (2, True))

    def test_an_invalid_state_exits_3_naming_the_key_path(self):
        stored = make_stored(**{f"dm-{DM}": make_unit(channel=DM, status="done")})

        code, _, err = self.run_features(stored=stored)

        self.assertEqual((code, f"units.dm-{DM}.status" in err), (3, True))

    def test_an_invalid_window_exits_3(self):
        window = make_window()
        del window["limited"]

        code, _, err = self.run_features(window=window)

        self.assertEqual((code, "window: " in err), (3, True))

    def test_a_collection_of_another_window_exits_2(self):
        self.run_features()
        collection = make_collection(make_window("2026-10-16T08:45:00Z"), [])
        self.write("collections/chat.json", collection)

        code, _, err = run_cli(*self.arguments())

        self.assertEqual((code, "collection " in err), (2, True))

    def test_a_missing_flag_exits_2(self):
        code, _, _ = run_cli("features", "--config", "c")

        self.assertEqual(code, 2)

    def test_an_unknown_place_exits_2(self):
        self.run_features()
        arguments = self.arguments()
        arguments[arguments.index("--place") + 1] = "mars"

        self.assertEqual(run_cli(*arguments)[0], 2)

    def test_the_script_exits_0(self):
        self.run_features(dm(msg(PEER, at("2026-10-15T09:00:00Z"))))
        os.remove(self.path("features.json"))

        result = subprocess.run([sys.executable, os.path.join(HERE, "recap.py"), *self.arguments()], capture_output=True, text=True, check=False)

        self.assertEqual((result.returncode, os.path.exists(self.path("features.json"))), (0, True))

    def arguments(self):
        return [
            "features", "--config", self.path("config.json"), "--routine", SLUG, "--state", self.path("state.json"), "--window", self.path("window.json"),
            "--collections", self.path("collections"), "--place", "cloud", "--out", self.path("features.json"), "--base-out", self.path("base.json"),
            "--rules-out", self.path("rules.json"),
        ]


class ContractTest(unittest.TestCase):
    def test_a_unit_with_every_fact_allows_every_kind_of_the_definitions_in_order(self):
        facts = {
            "last_author_is_owner": True,
            "unanswered_from": "1.000001",
            "groups": [{"lands_in": "good_to_know", "answered": False}],
            "direct_mention": True,
            "announcement_channel": True,
            "owner_took_part": True,
            "owner_answered": True,
            "previous": {"status": "waiting"},
        }

        self.assertEqual(recap_features.allowed_kinds("dm", facts), list(recap_features.KIND_DEFINITIONS))


if __name__ == "__main__":
    unittest.main()
