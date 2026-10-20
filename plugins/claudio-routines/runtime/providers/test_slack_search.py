import collections
import json
import os
import tempfile
import unittest
import urllib.parse

import roles
import state
import store
from providers import _http, slack
from providers.slack_support import (
    RUN,
    live,
    ordered,
    relay_through,
    store_session,
    BASE,
    CONNECTOR,
    HISTORY_PATH,
    REPLIES_PATH,
    ROOT_TS,
    SOURCE,
    THREAD_TOOL,
    TOOL,
    WINDOW,
    FakeOpener,
    body,
    client,
    collection,
    failed,
    query,
    relay_message,
    relay_one,
    relay_page,
    relay_text,
    reply_item,
    requests_to,
    root_item,
    saved,
    thread_page,
    thread_parent,
    thread_reply,
)

SEARCH_TOOL = "slack_search_public_and_private"
REACTIONS_TOOL = "slack_get_reactions"
SEARCH_PATH = "/api/search.messages"
REACTIONS_PATH = "/api/reactions.get"
USERS_PATH = "/api/users.info"
SEARCH_WINDOW = {"from_ts": 1792390000, "to_ts": 1792400000, "first_read_from_ts": 1792390000}
OWNER = "U000001"
PEER = "U000002"
BOT = "U000009"
THREAD_ROOT = "1792398000.000050"
DMS = {"name": "dms", "filters": "is:dm", "since": "window"}
SEARCH_CURSOR = "Q1VSUkVOVF9QQUdFOjI="
THREAD_CURSOR = "bmV4dF90czoxNzkyMzk4MjAwLjAwMDEwMA=="
THREAD_MORE = "There are more messages in this thread. To view the next page, use cursor: `{}`"


def search_source(*searches, **options):
    kept = {key: value for key, value in SOURCE.items() if key != "channels"}
    return {**kept, "owner": OWNER, "searches": list(searches) or [DMS], **options}


def hit(channel, name, user, ts, reply=None, thread=None, bot=False, participants=None, text="hello", sender="Peer Name"):
    link = f"https://example.slack.test/archives/{channel}/p{ts.replace('.', '')}" + (f"?thread_ts={thread}&cid={channel}" if thread else "")
    sender = f"Bot App (ID: {user})  [BOT]" if bot else f"{sender} <peer@example.test> (ID: {user}) "
    lines = [f"Channel: {name} (ID: {channel})"]
    if participants:
        lines.append("Participants: " + ", ".join(f"{who} (ID: {ident})" for who, ident in participants))
    lines += [f"From: {sender}", "Time: 2026-10-19 10:04:13 CEST", f"Message_ts: {ts}"]
    if reply:
        lines.append(f"Reply count: {reply}")
    return "\n".join([*lines, f"Permalink: [link]({link})", "Text: ", text])


def search_text(*hits, cursor=None):
    blocks = [f"### Result {number} of {len(hits)}\n{block}" for number, block in enumerate(hits, 1)]
    results = f"# Search Results for: \n\n## Messages ({len(hits)} results)\n" + "".join(block + "\n\n---\n\n" for block in blocks)
    return json.dumps({"results": results, "pagination_info": f"For the next page of results use cursor `{cursor}`\n" if cursor else ""})


def named_message(name, user, ts, *lines):
    header = f"=== Message from {name} {name.split()[0].lower()}@example.test ({user}) at 2026-10-19 10:04:13 UTC === "
    return "\n".join((header, f"Message TS: {ts}", *lines))


def conversation_page(channel, *entries, names=None):
    names = names or {OWNER: "Owner Name", BOT: "Bot App"}
    return relay_page(channel, *(named_message(names.get(user, "Peer Name"), user, ts, text) for user, ts, text in entries))


def empty_response(call):
    tool, arguments = call["tool"], call["arguments"]
    if tool == TOOL:
        return relay_page(arguments["channel_id"])
    if tool == THREAD_TOOL:
        return relay_text("No thread messsages")
    if tool == REACTIONS_TOOL:
        return saved("reactions_none.json")
    raise AssertionError(tool)


def drive(source, responses, answer=empty_response):
    responses, seen = dict(responses), []
    for _ in range(40):
        step = slack.plan(source, SEARCH_WINDOW, {}, [], ordered(responses), CONNECTOR)
        if step["done"]:
            return seen, step, responses
        call = step["calls"][0]
        expected = f"team-chat-{len(responses) + 1}"
        if call["id"] != expected:
            raise AssertionError(f"call id {call['id']} is not {expected}")
        seen.append((call["tool"], call["arguments"]))
        responses[call["id"]] = answer(call)
    raise AssertionError("plan did not end")


def search_parse(source, responses):
    return slack.parse(source, SEARCH_WINDOW, {}, [], ordered(responses), {})


def unit_message(user, name, ts, text, root=None, bot=False, **extra):
    return {"user": user, "name": name, "bot": bot, "ts": ts, "root_ts": root, "mentions": [], "group_mentions": [], "text": text, **extra}


def full_responses():
    return {
        "team-chat-1": saved("search_page_1.json"),
        "team-chat-2": saved("search_page_2.json"),
        "team-chat-3": conversation_page("D000001", (OWNER, "1792398000.000200", "On it"), (BOT, "1792397053.514349", "multi\nline text")),
        "team-chat-4": thread_page(thread_reply(PEER, "1792398500.000100", "Can you review?", index=1, total=1), root=THREAD_ROOT, total=1),
    }


class SearchRelayPlanTest(unittest.TestCase):
    def first_call(self, search=DMS, **options):
        return slack.plan(search_source(search, **options), SEARCH_WINDOW, {}, [], ordered({}), CONNECTOR)["calls"][0]

    def test_plans_one_search_call_with_the_search_arguments(self):
        search = {**DMS, "channel_types": "im,mpim", "keywords": ["deploy"]}

        self.assertEqual(
            self.first_call(search),
            {
                "id": "team-chat-1",
                "connector": CONNECTOR,
                "tool": SEARCH_TOOL,
                "arguments": {
                    "filters": "is:dm",
                    "channel_types": "im,mpim",
                    "keywords": ["deploy"],
                    "after": "1792390000",
                    "before": "1792400000",
                    "sort": "timestamp",
                    "sort_dir": "asc",
                    "limit": 20,
                    "include_context": False,
                    "natural_language_query": "",
                    "response_format": "detailed",
                },
                "digest": None,
            },
        )

    def test_omits_channel_types_and_keywords_when_unset(self):
        self.assertTrue({"channel_types", "keywords", "cursor"}.isdisjoint(self.first_call()["arguments"]))

    def test_starts_a_lookback_search_that_many_days_before_the_window_end(self):
        call = self.first_call({**DMS, "since": {"lookback_days": 2}})

        self.assertEqual(call["arguments"]["after"], str(1792400000 - 2 * 86400))

    def test_plans_the_next_page_from_the_response_cursor(self):
        step = slack.plan(search_source(), SEARCH_WINDOW, {}, [], ordered({"team-chat-1": saved("search_page_1.json")}), CONNECTOR)

        self.assertEqual((step["calls"][0]["id"], step["calls"][0]["arguments"]["cursor"]), ("team-chat-2", SEARCH_CURSOR))

    def test_ends_the_search_at_a_page_without_cursor(self):
        seen, step, _ = drive(search_source(), {"team-chat-1": saved("search_empty.json")})

        self.assertEqual((seen, step["partial"]), ([], None))

    def test_plans_the_reads_of_the_units_found_before_a_search_cut_by_the_page_cap(self):
        seen, step, _ = drive(search_source(search_page_cap=1), {"team-chat-1": saved("search_page_1.json")})

        self.assertEqual(([tool for tool, _ in seen], step["partial"]), ([TOOL], None))

    def test_keeps_the_units_read_and_names_the_search_when_a_search_is_cut_by_the_page_cap(self):
        _, _, responses = drive(search_source(search_page_cap=1), {"team-chat-1": saved("search_page_1.json")})

        result = search_parse(search_source(search_page_cap=1), responses)

        self.assertEqual(
            ([unit["channel"] for unit in result["records"]["units"]], result["entries"]),
            (["D000001", "C000002"], {"search:dms": failed("page cap: 1 page(s) read")}),
        )

    def test_reads_every_page_up_to_the_cap(self):
        _, step, _ = drive(search_source(search_page_cap=2), {"team-chat-1": saved("search_page_1.json"), "team-chat-2": saved("search_page_2.json")})

        self.assertIsNone(step["partial"])

    def test_a_response_without_results_is_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable):
            search_parse(search_source(), {"team-chat-1": json.dumps({"error": "boom"})})


class SearchRoutingTest(unittest.TestCase):
    def routed(self, *hits, search=DMS, **options):
        seen, _, _ = drive(search_source(search, **options), {"team-chat-1": search_text(*hits)})
        return [(tool, arguments["channel_id"], arguments.get("message_ts")) for tool, arguments in seen]

    def test_routes_a_direct_conversation_hit_to_one_conversation_read_from_the_window_start(self):
        responses = {"team-chat-1": search_text(hit("D1", "DM", PEER, "1792395000.000100"))}
        seen, _, _ = drive(search_source(), responses)

        self.assertEqual((seen[0][0], seen[0][1]["channel_id"], seen[0][1]["oldest"]), (TOOL, "D1", "1792390000"))

    def test_routes_a_hit_with_a_reply_count_to_a_thread_read_by_its_own_ts(self):
        reads = self.routed(hit("C3", "#ops", PEER, "1792395000.000100", reply=2))

        self.assertEqual(reads, [(THREAD_TOOL, "C3", "1792395000.000100")])

    def test_routes_a_hit_with_a_thread_ts_to_a_thread_read_by_the_root(self):
        reads = self.routed(hit("C3", "#ops", PEER, "1792396000.000100", thread="1792395000.000100"))

        self.assertEqual(reads, [(THREAD_TOOL, "C3", "1792395000.000100")])

    def test_reads_a_conversation_and_a_thread_once_whatever_the_number_of_hits(self):
        reads = self.routed(
            hit("D1", "DM", PEER, "1792395000.000100"),
            hit("D1", "DM", PEER, "1792395500.000100"),
            hit("C3", "#ops", PEER, "1792396000.000100", reply=2),
            hit("C3", "#ops", PEER, "1792396500.000100", thread="1792396000.000100"),
            hit("C3", "#ops", PEER, "1792397000.000100", thread="1792396800.000100"),
            hit("C4", "#dev", PEER, "1792397500.000100"),
        )

        self.assertEqual(reads, [(TOOL, "D1", None), (THREAD_TOOL, "C3", "1792396000.000100"), (THREAD_TOOL, "C3", "1792396800.000100")])

    def test_reads_a_conversation_hit_found_by_two_searches_once(self):
        second = {**DMS, "name": "groups"}
        responses = {"team-chat-1": search_text(hit("D1", "DM", PEER, "1792395000.000100")), "team-chat-2": search_text(hit("D1", "DM", PEER, "1792395000.000100"))}
        seen, _, _ = drive(search_source(DMS, second), responses)

        self.assertEqual([tool for tool, _ in seen], [TOOL])

    def test_routes_a_group_conversation_of_a_conversation_only_search_to_a_conversation_read(self):
        reads = self.routed(hit("G5", "mpdm-a--b-1", PEER, "1792395000.000100"))

        self.assertEqual(reads, [(TOOL, "G5", None)])

    def test_routes_a_group_conversation_named_group_dm_to_a_conversation_read(self):
        reads = self.routed(hit("C7", "group DM", PEER, "1792395000.000100"))

        self.assertEqual(reads, [(TOOL, "C7", None)])

    def test_routes_every_hit_of_an_im_and_mpim_only_search_to_a_conversation_read(self):
        reads = self.routed(hit("G5", "friends", PEER, "1792395000.000100"), search={**DMS, "channel_types": "im,mpim"})

        self.assertEqual(reads, [(TOOL, "G5", None)])

    def test_keeps_a_hit_of_a_mixed_channel_types_search_in_a_channel_when_nothing_says_conversation(self):
        reads = self.routed(hit("G5", "friends", PEER, "1792395000.000100"), search={**DMS, "channel_types": "public_channel,im"})

        self.assertEqual(reads, [])

    def test_routes_a_thread_reply_hit_in_a_direct_conversation_to_the_conversation_read(self):
        reads = self.routed(hit("D1", "DM", PEER, "1792395000.000100", thread="1792394000.000100"))

        self.assertEqual(reads, [(TOOL, "D1", None)])

    def test_drops_a_hit_outside_the_window(self):
        reads = self.routed(hit("D1", "DM", PEER, "1792399999.000100"), hit("D2", "DM", PEER, "1792400001.000100"), hit("D3", "DM", PEER, "1792390000.000000"))

        self.assertEqual(reads, [(TOOL, "D1", None)])

    def test_asks_no_reactions_without_the_reactions_option(self):
        reads = self.routed(hit("D1", "DM", PEER, "1792395000.000100"))

        self.assertNotIn(REACTIONS_TOOL, [tool for tool, _, _ in reads])


class SearchThreadWithoutRepliesTest(unittest.TestCase):
    def test_keeps_the_root_text_of_a_thread_answered_by_the_parent_and_the_no_thread_text(self):
        parent = relay_text(thread_parent(THREAD_ROOT) + "\n\nNo thread messsages\n", "There are no more messages in this thread.")
        responses = {"team-chat-1": search_text(hit("C3", "#ops", PEER, "1792398000.000050", reply=1)), "team-chat-2": parent}

        unit = search_parse(search_source(), responses)["records"]["units"][0]

        self.assertEqual(unit["messages"], [unit_message("U1", "Ada Example", THREAD_ROOT, "Release notes", root=THREAD_ROOT)])


class SearchRelayPageSizeTest(unittest.TestCase):
    NEWEST, OLDEST = "1792398500.000100", "1792398200.000100"

    def pages(self, root=THREAD_ROOT):
        newest = thread_page(thread_reply(PEER, self.NEWEST, "latest", index=1, total=2), root=root, total=2, pagination=THREAD_MORE.format(THREAD_CURSOR))
        oldest = thread_page(thread_reply(PEER, self.OLDEST, "first", index=2, total=2), root=root, total=2)
        return lambda call: (oldest if "cursor" in call["arguments"] else newest) if call["tool"] == THREAD_TOOL else empty_response(call)

    def read(self, source, *hits, root=THREAD_ROOT):
        return drive(source, {"team-chat-1": search_text(*hits)}, self.pages(root))

    def test_reads_a_conversation_thirty_messages_at_a_time(self):
        seen, _, _ = drive(search_source(), {"team-chat-1": search_text(hit("D1", "DM", PEER, "1792395000.000100"))})

        self.assertEqual([arguments["limit"] for tool, arguments in seen if tool == TOOL], [30])

    def test_reads_a_thread_twenty_replies_at_a_time_and_follows_its_cursor_to_the_last_page(self):
        seen, _, _ = self.read(search_source(), hit("C3", "#ops", PEER, THREAD_ROOT, reply=2))

        self.assertEqual([(arguments["limit"], arguments.get("cursor")) for tool, arguments in seen if tool == THREAD_TOOL], [(20, None), (20, THREAD_CURSOR)])

    def test_keeps_the_replies_of_every_page_of_a_thread(self):
        source = search_source()
        _, _, responses = self.read(source, hit("C3", "#ops", PEER, THREAD_ROOT, reply=2))

        messages = search_parse(source, responses)["records"]["units"][0]["messages"]

        self.assertEqual([message["ts"] for message in messages], [THREAD_ROOT, self.OLDEST, self.NEWEST])

    def test_reads_a_stored_thread_twenty_replies_at_a_time(self):
        seen, _, _ = self.read(search_source(rereads=[THREAD_REREAD]), root=STORED_ROOT)

        self.assertEqual([(arguments["limit"], arguments.get("cursor")) for tool, arguments in seen if tool == THREAD_TOOL], [(20, None), (20, THREAD_CURSOR)])


class SearchRelayRecordsTest(unittest.TestCase):
    def test_parses_the_connector_pages_into_one_unit_per_conversation_thread_and_message(self):
        result = search_parse(search_source(), full_responses())

        self.assertEqual(
            result["records"]["units"],
            [
                {
                    "channel": "D000001",
                    "name": "DM",
                    "participants": [{"id": BOT, "name": "Bot App"}, {"id": OWNER, "name": "Owner Name"}],
                    "messages": [
                        unit_message(BOT, "Bot App", "1792397053.514349", "multi line text", root="1792397053.514349", bot=True),
                        unit_message(OWNER, "Owner Name", "1792398000.000200", "On it"),
                    ],
                },
                {
                    "channel": "C000003",
                    "name": "#ops",
                    "participants": [],
                    "messages": [
                        unit_message("U1", "Ada Example", THREAD_ROOT, "Release notes", root=THREAD_ROOT),
                        unit_message(PEER, "Bea Example", "1792398500.000100", "Can you review?", root=THREAD_ROOT),
                    ],
                },
                {
                    "channel": "C000002",
                    "name": "#general",
                    "participants": [],
                    "messages": [unit_message(PEER, "Peer Name", "1792397952.306719", "hello")],
                },
            ],
        )

    def test_keeps_a_plain_channel_hit_as_a_message_of_its_own_unit_without_a_read(self):
        seen, _, _ = drive(search_source(), {"team-chat-1": search_text(hit("C000002", "#general", PEER, "1792397952.306719"))})

        self.assertEqual(seen, [])

    def test_flags_a_bot_author_and_keeps_the_others_unflagged(self):
        units = search_parse(search_source(), full_responses())["records"]["units"]

        self.assertEqual([[message["bot"] for message in unit["messages"]] for unit in units], [[True, False], [False, False], [False]])

    def test_cuts_the_text_at_300_characters(self):
        responses = {"team-chat-1": search_text(hit("C4", "#dev", PEER, "1792397500.000100", text="0123456789" * 40))}

        text = search_parse(search_source(), responses)["records"]["units"][0]["messages"][0]["text"]

        self.assertEqual(text, ("0123456789" * 40)[:300])

    def test_flags_a_bot_marked_in_a_read_header_and_keeps_its_user_id(self):
        header = "=== Message from Bot App (U000009) [BOT] at 2026-10-19 10:04:13 UTC === "
        page = relay_page("D1", "\n".join((header, "Message TS: 1792395000.000100", "ping")))
        responses = {"team-chat-1": search_text(hit("D1", "DM", PEER, "1792395000.000100")), "team-chat-2": page}

        message = search_parse(search_source(), responses)["records"]["units"][0]["messages"][0]

        self.assertEqual((message["user"], message["bot"]), ("U000009", True))

    def test_keeps_no_permalink(self):
        units = search_parse(search_source(), full_responses())["records"]["units"]

        self.assertNotIn("example.slack.test", json.dumps(units))

    def test_reads_an_empty_search_as_no_unit(self):
        result = search_parse(search_source(), {"team-chat-1": saved("search_empty.json")})

        self.assertEqual(result["records"], {"messages": [], "units": []})

    def test_records_a_failed_conversation_as_an_entry_without_a_unit(self):
        responses = {"team-chat-1": search_text(hit("D1", "DM", PEER, "1792395000.000100")), "team-chat-2": json.dumps({"error": "channel_not_found"})}

        result = search_parse(search_source(), responses)

        self.assertEqual((result["records"]["units"], result["entries"]), ([], {"D1": failed("channel_not_found")}))

    def test_a_source_without_searches_has_no_units_key(self):
        result = relay_one(relay_message("U1", "1760004000.000400", "hi"))

        self.assertEqual(list(result["records"]), ["messages"])

    def test_keeps_the_stored_cursor_of_a_search_only_source(self):
        result = search_parse(search_source(), {"team-chat-1": saved("search_empty.json")})

        self.assertEqual(result["cursor"], {"ts": {}})

    def test_the_collection_passes_the_role_check(self):
        result = search_parse(search_source(), full_responses())

        self.assertIsNone(roles.validate_collection(collection(result, "mcp")))


class SearchReactionsTest(unittest.TestCase):
    ENTRIES = [
        (PEER, "1792396500.000100", "e"),
        (PEER, "1792396400.000100", "d"),
        (PEER, "1792396300.000100", "c"),
        (PEER, "1792396250.000100", "b"),
        (OWNER, "1792396200.000100", "mine"),
        (PEER, "1792396100.000100", "a"),
    ]

    def reactions_calls(self, entries):
        responses = {"team-chat-1": search_text(hit("D1", "DM", PEER, entries[0][1])), "team-chat-2": conversation_page("D1", *entries)}
        seen, _, _ = drive(search_source(reactions=True), responses)
        return [arguments["message_ts"] for tool, arguments in seen if tool == REACTIONS_TOOL]

    def test_reads_the_reactions_of_the_newest_three_messages_after_the_owner_last_message(self):
        self.assertEqual(self.reactions_calls(self.ENTRIES), ["1792396300.000100", "1792396400.000100", "1792396500.000100"])

    def test_reads_no_reactions_when_the_owner_wrote_last(self):
        entries = [(OWNER, "1792396500.000100", "mine"), (PEER, "1792396000.000100", "question")]

        self.assertEqual(self.reactions_calls(entries), [])

    def test_reads_every_message_of_a_unit_the_owner_never_wrote_in_up_to_three(self):
        entries = [(PEER, "1792396300.000100", "c"), (PEER, "1792396200.000100", "b")]

        self.assertEqual(self.reactions_calls(entries), ["1792396200.000100", "1792396300.000100"])

    def reacted(self, name):
        entries = [(PEER, "1792395000.000100", "question")]
        responses = {"team-chat-1": search_text(hit("D1", "DM", PEER, entries[0][1])), "team-chat-2": conversation_page("D1", *entries), "team-chat-3": saved(name)}
        return search_parse(search_source(reactions=True), responses)["records"]["units"][0]["messages"][0]

    def test_parses_an_owner_reaction_to_owner_reacted_true(self):
        self.assertIs(self.reacted("reactions_some.json")["owner_reacted"], True)

    def test_parses_a_message_without_reactions_to_owner_reacted_false(self):
        self.assertIs(self.reacted("reactions_none.json")["owner_reacted"], False)

    def test_leaves_owner_reacted_out_of_a_message_whose_reactions_were_not_read(self):
        units = search_parse(search_source(), full_responses())["records"]["units"]

        self.assertNotIn("owner_reacted", units[0]["messages"][0])

    def reaction_entries(self, text):
        entries = [(PEER, "1792395000.000100", "question")]
        responses = {"team-chat-1": search_text(hit("D1", "DM", PEER, entries[0][1])), "team-chat-2": conversation_page("D1", *entries), "team-chat-3": text}
        return search_parse(search_source(reactions=True), responses)

    def test_a_reactions_text_that_is_neither_header_nor_no_reaction_text_is_a_failed_entry(self):
        result = self.reaction_entries(json.dumps({"result": "channel_not_found"}))

        self.assertEqual(
            (result["entries"], "owner_reacted" in result["records"]["units"][0]["messages"][0]),
            ({"reactions:D1:1792395000.000100": failed("unreadable reactions response")}, False),
        )

    def test_a_reactions_response_without_result_is_a_failed_entry_not_a_source_failure(self):
        result = self.reaction_entries("{}")

        self.assertEqual(list(result["entries"]), ["reactions:D1:1792395000.000100"])

    def test_a_display_name_holding_an_id_does_not_count_as_a_reacting_user(self):
        text = json.dumps({"result": "Reactions on message:\n\n:eyes: \u00d7 2 \u2014 Eve (" + OWNER + ") (U000005), Ann (U000003)"})

        result = self.reaction_entries(text)

        self.assertIs(result["records"]["units"][0]["messages"][0]["owner_reacted"], False)

    def test_reads_each_user_id_after_the_name_separator_of_a_reaction_line(self):
        text = json.dumps({"result": "Reactions on message:\n\n:eyes: \u00d7 2 \u2014 Eve (U000005), Owner Name (" + OWNER + ")\n:+1: \u00d7 1 \u2014 Ann (U000003)"})

        result = self.reaction_entries(text)

        self.assertIs(result["records"]["units"][0]["messages"][0]["owner_reacted"], True)


INFO_PATH = "/api/conversations.info"
MEMBERS_PATH = "/api/conversations.members"
USERS = {"U1": "Ada Example", "U2": "Bea Example", OWNER: "Owner Name"}


def api_match(channel, ts, user="U2", text="hi", im=False, mpim=False, thread=None, channel_name="ops", **extra):
    link = f"{BASE}/archives/{channel}/p{ts.replace('.', '')}" + (f"?thread_ts={thread}&cid={channel}" if thread else "")
    return {"channel": {"id": channel, "name": channel_name, "is_im": im, "is_mpim": mpim}, "user": user, "ts": ts, "text": text, "permalink": link, **extra}


def search_doc(*matches, pages=1):
    return {"ok": True, "messages": {"matches": list(matches), "paging": {"count": 20, "total": len(matches), "page": 1, "pages": pages}}}


def history_doc(*messages):
    return {"ok": True, "messages": list(messages), "has_more": False, "response_metadata": {"next_cursor": ""}}


def reaction_doc(*users):
    return {"ok": True, "message": {"reactions": [{"name": "eyes", "users": list(users), "count": len(users)}] if users else []}}


def user_doc(name):
    return {"ok": True, "user": {"profile": {"display_name": name}}}


def info_doc(channel, user):
    return {"ok": True, "channel": {"id": channel, "user": user}}


def error_doc(code):
    return {"ok": False, "error": code}


class RoutedOpener(FakeOpener):
    def __init__(self, routes, users):
        super().__init__([])
        self.routes = {path: list(documents) for path, documents in routes.items()}
        self.users = users

    def open(self, request, timeout=None):
        self.requests.append(request)
        parts = urllib.parse.urlsplit(request.full_url)
        if parts.path == USERS_PATH:
            return body(self.users[urllib.parse.parse_qs(parts.query)["user"][0]])
        return body(self.routes[parts.path].pop(0))


def api_units(routes, users=None, window=WINDOW, source=None, **options):
    known = {user: user_doc(name) for user, name in USERS.items()} if users is None else users
    opener = RoutedOpener(routes, known)
    return opener, slack.fetch(source or search_source(**options), window, {}, [], live(client(opener)))


def path_counts(opener):
    return dict(collections.Counter(urllib.parse.urlsplit(request.full_url).path for request in opener.requests))


def plain_match(user="U2", ts="1760004000.000400"):
    return api_match("C4", ts, user=user, text="solo", channel_name="dev")


class SearchApiTest(unittest.TestCase):
    def test_reads_search_pages_oldest_first_twenty_at_a_time_with_the_dated_query(self):
        routes = {SEARCH_PATH: [search_doc(plain_match(), pages=2), search_doc(plain_match(ts="1760005000.000500"), pages=2)]}

        opener, _ = api_units(routes)

        self.assertEqual(
            [query(call) for call in requests_to(opener, SEARCH_PATH)],
            [
                {"query": ["is:dm after:2025-10-07 before:2025-10-11"], "sort": ["timestamp"], "sort_dir": ["asc"], "count": ["20"], "page": [str(page)]}
                for page in (1, 2)
            ],
        )

    def test_appends_the_keywords_before_the_dates(self):
        opener, _ = api_units({SEARCH_PATH: [search_doc()]}, source=search_source({**DMS, "keywords": ["deploy", "now"]}))

        self.assertEqual(query(opener.requests[0])["query"], ["is:dm deploy now after:2025-10-07 before:2025-10-11"])

    def test_dates_a_lookback_search_from_its_own_start(self):
        opener, _ = api_units({SEARCH_PATH: [search_doc()]}, source=search_source({**DMS, "since": {"lookback_days": 2}}))

        self.assertEqual(query(opener.requests[0])["query"], ["is:dm after:2025-10-05 before:2025-10-11"])

    def test_drops_the_hits_outside_the_window_by_ts(self):
        matches = [plain_match(ts=ts) for ts in ("1759999999.000001", "1760004000.000400", "1760010801.000001")]

        _, result = api_units({SEARCH_PATH: [search_doc(*matches)]})

        self.assertEqual([unit["messages"][0]["ts"] for unit in result["records"]["units"]], ["1760004000.000400"])

    def test_drops_the_hits_of_other_channel_types(self):
        matches = [api_match("D1", "1760004000.000400", im=True), plain_match(ts="1760005000.000500")]

        _, result = api_units({SEARCH_PATH: [search_doc(*matches)]}, source=search_source({**DMS, "channel_types": "public_channel"}))

        self.assertEqual([unit["channel"] for unit in result["records"]["units"]], ["C4"])

    def test_keeps_the_units_read_and_names_the_search_when_it_is_cut_by_the_page_cap(self):
        _, result = api_units({SEARCH_PATH: [search_doc(plain_match(), pages=3)]}, search_page_cap=1)

        self.assertEqual((len(result["records"]["units"]), result["entries"]), (1, {"search:dms": failed("page cap: 1 page(s) read")}))

    def test_does_not_cut_a_search_that_ends_on_its_last_allowed_page(self):
        _, result = api_units({SEARCH_PATH: [search_doc(plain_match(), pages=1)]}, search_page_cap=1)

        self.assertEqual(result["entries"], {})

    def test_a_missing_scope_answer_makes_the_search_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            api_units({SEARCH_PATH: [error_doc("missing_scope")]})

        self.assertIn("missing_scope", str(caught.exception))

    def test_an_invalid_auth_answer_makes_the_search_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            api_units({SEARCH_PATH: [error_doc("invalid_auth")]})

        self.assertIn("invalid_auth", str(caught.exception))

    def test_an_answer_without_an_error_code_makes_the_search_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            api_units({SEARCH_PATH: [{"ok": False}]})

        self.assertIn("unknown error", str(caught.exception))

    def test_refuses_a_hit_whose_channel_id_is_not_an_id(self):
        with self.assertRaises(_http.SourceUnreadable):
            api_units({SEARCH_PATH: [search_doc(api_match("c4/../x", "1760004000.000400"))]})

    def test_routes_each_hit_to_its_read_and_names_users_and_participants(self):
        thread_root = "1760002000.000200"
        matches = [
            api_match("D1", "1760004000.000400", im=True, text="ping"),
            api_match("C3", "1760005000.000500", thread=thread_root, text="Can you review?"),
            plain_match(user="U1", ts="1760006000.000600"),
        ]
        routes = {
            SEARCH_PATH: [search_doc(*matches)],
            HISTORY_PATH: [history_doc({"type": "message", "user": "U2", "text": "ping", "ts": "1760004000.000400"})],
            INFO_PATH: [info_doc("D1", "U2")],
            REPLIES_PATH: [history_doc(root_item(thread_root, 1), reply_item("1760005000.000500", text="Can you review?", root=thread_root))],
        }

        opener, result = api_units(routes)

        self.assertEqual(path_counts(opener), {SEARCH_PATH: 1, HISTORY_PATH: 1, INFO_PATH: 1, REPLIES_PATH: 1, USERS_PATH: 3})
        self.assertEqual(
            result["records"]["units"],
            [
                {
                    "channel": "D1",
                    "name": "DM",
                    "participants": [{"id": "U2", "name": "Bea Example"}, {"id": OWNER, "name": "Owner Name"}],
                    "messages": [unit_message("U2", "Bea Example", "1760004000.000400", "ping")],
                },
                {
                    "channel": "C3",
                    "name": "#ops",
                    "participants": [],
                    "messages": [
                        unit_message("U1", "Ada Example", thread_root, "Release notes", root=thread_root),
                        unit_message("U2", "Bea Example", "1760005000.000500", "Can you review?", root=thread_root),
                    ],
                },
                {"channel": "C4", "name": "#dev", "participants": [], "messages": [unit_message("U1", "Ada Example", "1760006000.000600", "solo")]},
            ],
        )

    def test_reads_a_conversation_from_the_window_start_and_once_for_two_hits(self):
        matches = [api_match("D1", "1760004000.000400", im=True), api_match("D1", "1760005000.000500", im=True)]
        routes = {SEARCH_PATH: [search_doc(*matches)], HISTORY_PATH: [history_doc()], INFO_PATH: [info_doc("D1", "U2")]}

        opener, _ = api_units(routes)

        self.assertEqual((path_counts(opener)[HISTORY_PATH], query(requests_to(opener, HISTORY_PATH)[0])["oldest"]), (1, [str(WINDOW["from_ts"])]))

    def test_reads_a_thread_once_for_two_hits(self):
        matches = [api_match("C3", "1760005000.000500", thread=ROOT_TS), api_match("C3", "1760006000.000600", thread=ROOT_TS)]
        replies = history_doc(root_item(), reply_item("1760005000.000500"), reply_item("1760006000.000600"))

        opener, _ = api_units({SEARCH_PATH: [search_doc(*matches)], REPLIES_PATH: [replies]})

        self.assertEqual(path_counts(opener)[REPLIES_PATH], 1)

    def test_routes_a_thread_reply_hit_in_a_direct_conversation_to_the_conversation_read(self):
        match = api_match("D1", "1760004000.000400", im=True, thread=ROOT_TS)
        routes = {SEARCH_PATH: [search_doc(match)], HISTORY_PATH: [history_doc()], INFO_PATH: [info_doc("D1", "U2")]}

        opener, _ = api_units(routes)

        self.assertNotIn(REPLIES_PATH, path_counts(opener))

    def test_names_a_group_conversation_and_reads_its_members(self):
        routes = {
            SEARCH_PATH: [search_doc(api_match("G5", "1760004000.000400", mpim=True))],
            HISTORY_PATH: [history_doc()],
            MEMBERS_PATH: [{"ok": True, "members": ["U1", "U2", OWNER]}],
        }

        opener, result = api_units(routes)

        unit = result["records"]["units"][0]
        self.assertEqual(
            (unit["name"], [member["id"] for member in unit["participants"]], path_counts(opener)[MEMBERS_PATH]),
            ("group DM", ["U1", "U2", OWNER], 1),
        )

    def test_a_conversation_whose_info_the_token_cannot_read_is_a_failed_entry_without_a_unit(self):
        routes = {SEARCH_PATH: [search_doc(api_match("D1", "1760004000.000400", im=True))], HISTORY_PATH: [history_doc()], INFO_PATH: [error_doc("channel_not_found")]}

        _, result = api_units(routes)

        self.assertEqual((result["records"]["units"], result["entries"]), ([], {"D1": failed("channel_not_found")}))

    def test_a_conversation_the_token_cannot_read_is_a_failed_entry_without_a_unit(self):
        routes = {SEARCH_PATH: [search_doc(api_match("D1", "1760004000.000400", im=True))], HISTORY_PATH: [error_doc("not_in_channel")]}

        _, result = api_units(routes)

        self.assertEqual((result["records"]["units"], result["entries"]), ([], {"D1": failed("not_in_channel")}))

    def test_flags_a_bot_author_without_looking_its_name_up(self):
        opener, result = api_units({SEARCH_PATH: [search_doc(api_match("C4", "1760004000.000400", user=None, bot_id="B1"))]})

        message = result["records"]["units"][0]["messages"][0]
        self.assertEqual((message["bot"], message["user"], USERS_PATH in path_counts(opener)), (True, "B1", False))

    def test_looks_a_user_up_once_across_units(self):
        matches = [plain_match(ts="1760004000.000400"), api_match("C5", "1760005000.000500", text="other")]

        opener, _ = api_units({SEARCH_PATH: [search_doc(*matches)]})

        self.assertEqual(path_counts(opener)[USERS_PATH], 1)

    def test_a_missing_scope_on_the_name_lookup_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            api_units({SEARCH_PATH: [search_doc(plain_match())]}, users={"U2": error_doc("missing_scope")})

        self.assertIn("missing_scope", str(caught.exception))

    def test_keeps_an_empty_name_for_a_user_that_is_not_found(self):
        _, result = api_units({SEARCH_PATH: [search_doc(plain_match())]}, users={"U2": error_doc("user_not_found")})

        self.assertEqual(result["records"]["units"][0]["messages"][0]["name"], "")

    def test_keeps_no_permalink(self):
        _, result = api_units({SEARCH_PATH: [search_doc(plain_match())]})

        self.assertNotIn("/archives/", json.dumps(result["records"]["units"]))

    def test_reads_the_reactions_of_the_newest_three_messages_after_the_owner_last_message(self):
        stamps = [f"17600040{n}0.000100" for n in range(1, 5)]
        items = [{"type": "message", "user": "U2", "text": f"m{n}", "ts": ts} for n, ts in reversed(list(enumerate(stamps, 1)))]
        routes = {
            SEARCH_PATH: [search_doc(api_match("D1", stamps[-1], im=True))],
            HISTORY_PATH: [history_doc(*items)],
            INFO_PATH: [info_doc("D1", "U2")],
            REACTIONS_PATH: [reaction_doc(OWNER), reaction_doc(), reaction_doc()],
        }

        opener, result = api_units(routes, reactions=True)

        self.assertEqual(
            (
                [query(request)["timestamp"][0] for request in requests_to(opener, REACTIONS_PATH)],
                [message.get("owner_reacted") for message in result["records"]["units"][0]["messages"]],
            ),
            (stamps[1:], [None, True, False, False]),
        )

    def test_a_message_the_reactions_read_cannot_find_is_a_failed_entry_without_owner_reacted(self):
        routes = {SEARCH_PATH: [search_doc(plain_match())], REACTIONS_PATH: [error_doc("message_not_found")]}

        _, result = api_units(routes, reactions=True)

        self.assertEqual(
            (result["entries"], "owner_reacted" in result["records"]["units"][0]["messages"][0]),
            ({"reactions:C4:1760004000.000400": failed("message_not_found")}, False),
        )

    def test_the_collection_passes_the_role_check(self):
        _, result = api_units({SEARCH_PATH: [search_doc(plain_match())]})

        self.assertIsNone(roles.validate_collection(collection(result)))


class SearchApiCallCapTest(unittest.TestCase):
    def capped(self, routes, **options):
        with self.assertRaises(_http.PartialRead) as caught:
            api_units(routes, **options)
        return str(caught.exception)

    def test_counts_the_search_pages(self):
        routes = {SEARCH_PATH: [search_doc(plain_match(), pages=3)] * 3}

        self.assertEqual(self.capped(routes, call_cap=2), "partial: call cap")

    def test_counts_the_unit_reads(self):
        routes = {SEARCH_PATH: [search_doc(api_match("D1", "1760004000.000400", im=True))], HISTORY_PATH: [history_doc()]}

        self.assertEqual(self.capped(routes, call_cap=1), "partial: call cap")

    def test_counts_the_name_lookups(self):
        self.assertEqual(self.capped({SEARCH_PATH: [search_doc(plain_match())]}, call_cap=1), "partial: call cap")

    def test_counts_the_reactions_reads(self):
        routes = {SEARCH_PATH: [search_doc(plain_match())], REACTIONS_PATH: [reaction_doc()]}

        self.assertEqual(self.capped(routes, call_cap=2, reactions=True), "partial: call cap")

    def test_reads_past_the_default_cap_when_the_source_raises_it(self):
        routes = {SEARCH_PATH: [search_doc(plain_match(), pages=60)] * 60}

        _, result = api_units(routes, call_cap=60, search_page_cap=51)

        self.assertEqual(result["entries"], {"search:dms": failed("page cap: 51 page(s) read")})


class SearchTransportEqualityTest(unittest.TestCase):
    FIRST, SECOND = "1792395000.000100", "1792395500.000150"
    ROOT, REPLY, SOLO = "1792396000.000200", "1792396500.000250", "1792397000.000300"

    def over_relay(self):
        participants = [("Ada Example", "U1"), ("Bea Example", "U2")]
        hits = [
            hit("D1", "DM", "U1", self.FIRST, participants=participants, text="ping", sender="Ada Example"),
            hit("C3", "#ops", "U2", self.REPLY, thread=self.ROOT, text="Thanks", sender="Bea Example"),
            hit("C4", "#dev", "U1", self.SOLO, text="solo", sender="Ada Example"),
        ]
        responses = {
            "team-chat-1": search_text(*hits),
            "team-chat-2": conversation_page("D1", ("U2", self.SECOND, "On it"), ("U1", self.FIRST, "ping"), names=USERS),
            "team-chat-3": thread_page(thread_reply("U2", self.REPLY, "Thanks", index=1, total=1), root=self.ROOT, total=1),
        }
        return search_parse(search_source(owner="U2"), responses)

    def over_api(self):
        matches = [
            api_match("D1", self.FIRST, user="U1", im=True, text="ping"),
            api_match("C3", self.REPLY, user="U2", thread=self.ROOT, text="Thanks"),
            api_match("C4", self.SOLO, user="U1", text="solo", channel_name="dev"),
        ]
        root = {"type": "message", "user": "U1", "text": "Release notes", "ts": self.ROOT, "thread_ts": self.ROOT, "reply_count": 1}
        routes = {
            SEARCH_PATH: [search_doc(*matches)],
            HISTORY_PATH: [history_doc({"type": "message", "user": "U2", "text": "On it", "ts": self.SECOND}, {"type": "message", "user": "U1", "text": "ping", "ts": self.FIRST})],
            INFO_PATH: [info_doc("D1", "U1")],
            REPLIES_PATH: [history_doc(root, reply_item(self.REPLY, text="Thanks", user="U2", root=self.ROOT))],
        }
        return api_units(routes, window=SEARCH_WINDOW, owner="U2")[1]

    def test_both_transports_give_the_same_units_for_a_conversation_a_thread_and_a_single_message(self):
        self.assertEqual(state.dump(self.over_relay()["records"]), state.dump(self.over_api()["records"]))

    def test_both_transports_give_the_same_entries_and_cursor(self):
        over_relay, over_api = self.over_relay(), self.over_api()

        self.assertEqual(state.dump([over_relay["entries"], over_relay["cursor"]]), state.dump([over_api["entries"], over_api["cursor"]]))

STORED_ROOT = "1792300500.000200"
STORED_LAST = "1792300000.000100"
LATE_REPLY = "1792395000.000100"
DM_REREAD = {"kind": "dm", "channel": "D5", "root_ts": None, "last_ts": STORED_LAST}
THREAD_REREAD = {"kind": "thread", "channel": "C6", "root_ts": STORED_ROOT, "last_ts": "1792300600.000300"}


def reread_source(*rereads, **options):
    return search_source(rereads=list(rereads), **options)


class SearchRereadRelayTest(unittest.TestCase):
    def reads(self, source, *hits):
        seen, _, _ = drive(source, {"team-chat-1": search_text(*hits)})
        return [(tool, arguments["channel_id"], arguments.get("oldest"), arguments.get("message_ts")) for tool, arguments in seen]

    def test_reads_a_stored_conversation_again_from_just_before_its_last_message_outside_the_window(self):
        reads = self.reads(reread_source(DM_REREAD))

        self.assertEqual(reads, [(TOOL, "D5", "1792300000.000099", None)])

    def test_reads_a_stored_thread_again_by_its_root_outside_the_window(self):
        reads = self.reads(reread_source(THREAD_REREAD))

        self.assertEqual(reads, [(THREAD_TOOL, "C6", None, STORED_ROOT)])

    def test_reads_a_conversation_found_by_a_hit_and_a_reread_once_from_the_earlier_start(self):
        reads = self.reads(reread_source(DM_REREAD), hit("D5", "DM", PEER, "1792395000.000100"))

        self.assertEqual(reads, [(TOOL, "D5", "1792300000.000099", None)])

    def test_reads_a_conversation_hit_from_the_window_start_when_the_stored_message_is_newer(self):
        newer = {**DM_REREAD, "last_ts": "1792395500.000100"}

        reads = self.reads(reread_source(newer), hit("D5", "DM", PEER, "1792395000.000100"))

        self.assertEqual(reads, [(TOOL, "D5", "1792390000", None)])

    def test_reads_a_thread_found_by_a_hit_and_a_reread_once(self):
        reads = self.reads(reread_source(THREAD_REREAD), hit("C6", "#ops", PEER, "1792396000.000100", thread=STORED_ROOT))

        self.assertEqual(reads, [(THREAD_TOOL, "C6", None, STORED_ROOT)])

    def test_reads_the_same_stored_unit_listed_twice_once(self):
        reads = self.reads(reread_source(DM_REREAD, DM_REREAD, THREAD_REREAD, THREAD_REREAD))

        self.assertEqual([tool for tool, _, _, _ in reads], [TOOL, THREAD_TOOL])

    def test_names_a_group_conversation_reread_group_dm(self):
        responses = {"team-chat-1": saved("search_empty.json"), "team-chat-2": conversation_page("G5", (PEER, LATE_REPLY, "still open"))}

        result = search_parse(reread_source({**DM_REREAD, "kind": "group_dm", "channel": "G5"}), responses)

        self.assertEqual(result["records"]["units"][0]["name"], "group DM")

    def test_keeps_the_reread_conversation_as_a_unit_without_participants(self):
        responses = {"team-chat-1": saved("search_empty.json"), "team-chat-2": conversation_page("D5", (PEER, LATE_REPLY, "still open"))}

        result = search_parse(reread_source(DM_REREAD), responses)

        self.assertEqual(
            result["records"]["units"],
            [{"channel": "D5", "name": "DM", "participants": [], "messages": [unit_message(PEER, "Peer Name", LATE_REPLY, "still open")]}],
        )

    def test_keeps_the_reread_thread_with_its_parent_and_replies(self):
        reply = thread_reply(PEER, LATE_REPLY, "Thanks", index=1, total=1)
        responses = {"team-chat-1": saved("search_empty.json"), "team-chat-2": thread_page(reply, root=STORED_ROOT, total=1)}

        unit = search_parse(reread_source(THREAD_REREAD), responses)["records"]["units"][0]

        self.assertEqual((unit["channel"], unit["name"], [message["ts"] for message in unit["messages"]]), ("C6", "C6", [STORED_ROOT, LATE_REPLY]))

    def test_names_a_reread_thread_after_the_channel_of_a_hit(self):
        hits = (hit("C6", "#ops", PEER, "1792396000.000100"),)
        responses = {"team-chat-1": search_text(*hits), "team-chat-2": thread_page(thread_reply(PEER, LATE_REPLY, "Thanks", index=1, total=1), root=STORED_ROOT, total=1)}

        units = search_parse(reread_source(THREAD_REREAD), responses)["records"]["units"]

        self.assertEqual([(unit["channel"], unit["name"]) for unit in units], [("C6", "#ops"), ("C6", "#ops")])

    def test_drops_a_reread_conversation_without_a_message(self):
        responses = {"team-chat-1": saved("search_empty.json"), "team-chat-2": conversation_page("D5")}

        self.assertEqual(search_parse(reread_source(DM_REREAD), responses)["records"]["units"], [])

    def test_records_a_failed_reread_conversation_as_an_entry(self):
        responses = {"team-chat-1": saved("search_empty.json"), "team-chat-2": json.dumps({"error": "channel_not_found"})}

        result = search_parse(reread_source(DM_REREAD), responses)

        self.assertEqual((result["records"]["units"], result["entries"]), ([], {"D5": failed("channel_not_found")}))

    def test_a_source_without_rereads_plans_the_same_calls(self):
        self.assertEqual(self.reads(search_source(rereads=[])), [])


class SearchRereadApiTest(unittest.TestCase):
    def test_reads_a_stored_conversation_again_from_just_before_its_last_message(self):
        message = {"type": "message", "user": "U2", "text": "still open", "ts": "1760004000.000400"}
        routes = {SEARCH_PATH: [search_doc()], HISTORY_PATH: [history_doc(message)]}
        stored = {"kind": "dm", "channel": "D5", "root_ts": None, "last_ts": "1759900000.000100"}

        opener, result = api_units(routes, source=reread_source(stored))

        self.assertEqual(
            (query(requests_to(opener, HISTORY_PATH)[0])["oldest"], path_counts(opener).get(INFO_PATH), result["records"]["units"]),
            (["1759900000.000099"], None, [{"channel": "D5", "name": "DM", "participants": [], "messages": [unit_message("U2", "Bea Example", "1760004000.000400", "still open")]}]),
        )

    def test_reads_a_stored_thread_again_and_once_for_a_hit_in_it(self):
        replies = history_doc(root_item(ROOT_TS, 1), reply_item("1760005000.000500", root=ROOT_TS))
        routes = {SEARCH_PATH: [search_doc(api_match("C3", "1760005000.000500", thread=ROOT_TS))], REPLIES_PATH: [replies]}
        stored = {"kind": "thread", "channel": "C3", "root_ts": ROOT_TS, "last_ts": "1759900000.000100"}

        opener, result = api_units(routes, source=reread_source(stored))

        self.assertEqual((path_counts(opener)[REPLIES_PATH], len(result["records"]["units"])), (1, 1))

    def test_counts_the_reread_in_the_call_cap(self):
        stored = {"kind": "dm", "channel": "D5", "root_ts": None, "last_ts": "1759900000.000100"}

        with self.assertRaises(_http.PartialRead) as caught:
            api_units({SEARCH_PATH: [search_doc()], HISTORY_PATH: [history_doc()]}, source=reread_source(stored, call_cap=1))

        self.assertEqual(str(caught.exception), "partial: call cap")


KNOWN_THREAD = {"channel": "C6", "root_ts": STORED_ROOT, "last_ts": "1792300600.000300"}
KNOWN_OLDEST = "1792300600.000299"


class SearchKnownThreadRelayTest(unittest.TestCase):
    def reads(self, source, *hits):
        seen, _, _ = drive(source, {"team-chat-1": search_text(*hits)})
        return [(tool, arguments["channel_id"], arguments.get("oldest"), arguments.get("message_ts")) for tool, arguments in seen]

    def thread_hit(self, root=STORED_ROOT):
        return hit("C6", "#ops", PEER, "1792396000.000100", thread=root)

    def test_reads_a_known_thread_found_by_a_hit_from_just_before_its_last_message(self):
        reads = self.reads(search_source(known_threads=[KNOWN_THREAD]), self.thread_hit())

        self.assertEqual(reads, [(THREAD_TOOL, "C6", KNOWN_OLDEST, STORED_ROOT)])

    def test_reads_a_known_thread_that_is_also_reread_from_just_before_its_last_message(self):
        reads = self.reads(search_source(rereads=[THREAD_REREAD], known_threads=[KNOWN_THREAD]))

        self.assertEqual(reads, [(THREAD_TOOL, "C6", KNOWN_OLDEST, STORED_ROOT)])

    def test_reads_in_full_a_thread_that_is_not_known(self):
        other = {**KNOWN_THREAD, "root_ts": "1792300400.000100"}

        reads = self.reads(search_source(known_threads=[other]), self.thread_hit())

        self.assertEqual(reads, [(THREAD_TOOL, "C6", None, STORED_ROOT)])

    def test_reads_in_full_a_thread_known_in_another_channel(self):
        other = {**KNOWN_THREAD, "channel": "C7"}

        reads = self.reads(search_source(known_threads=[other]), self.thread_hit())

        self.assertEqual(reads, [(THREAD_TOOL, "C6", None, STORED_ROOT)])

    def test_reads_in_full_without_known_threads(self):
        reads = self.reads(search_source(), self.thread_hit())

        self.assertEqual(reads, [(THREAD_TOOL, "C6", None, STORED_ROOT)])

    def test_keeps_the_root_of_a_known_thread_without_a_reply_after_oldest(self):
        parent = relay_text(thread_parent(STORED_ROOT) + "\n\nNo thread messsages\n", "There are no more messages in this thread.")
        responses = {"team-chat-1": saved("search_empty.json"), "team-chat-2": parent}

        unit = search_parse(search_source(rereads=[THREAD_REREAD], known_threads=[KNOWN_THREAD]), responses)["records"]["units"][0]

        self.assertEqual([message["ts"] for message in unit["messages"]], [STORED_ROOT])

    def test_keeps_the_root_and_the_replies_after_oldest_of_a_known_thread(self):
        reply = thread_reply(PEER, LATE_REPLY, "Thanks", index=1, total=1)
        responses = {"team-chat-1": saved("search_empty.json"), "team-chat-2": thread_page(reply, root=STORED_ROOT, total=1)}

        unit = search_parse(search_source(rereads=[THREAD_REREAD], known_threads=[KNOWN_THREAD]), responses)["records"]["units"][0]

        self.assertEqual([message["ts"] for message in unit["messages"]], [STORED_ROOT, LATE_REPLY])


class SearchKnownThreadApiTest(unittest.TestCase):
    ROOT_LAST = "1760002500.000300"
    ROOT_OLDEST = "1760002500.000299"

    def replies_requests(self, **options):
        replies = history_doc(root_item(ROOT_TS, 1), reply_item("1760005000.000500", root=ROOT_TS))
        routes = {SEARCH_PATH: [search_doc(api_match("C3", "1760005000.000500", thread=ROOT_TS))], REPLIES_PATH: [replies]}
        opener, _ = api_units(routes, source=search_source(**options))
        return requests_to(opener, REPLIES_PATH)

    def test_reads_a_known_thread_from_just_before_its_last_message(self):
        known = {"channel": "C3", "root_ts": ROOT_TS, "last_ts": self.ROOT_LAST}

        requests = self.replies_requests(known_threads=[known])

        self.assertEqual([query(request).get("oldest") for request in requests], [[self.ROOT_OLDEST]])

    def test_reads_a_thread_that_is_not_known_in_full(self):
        known = {"channel": "C3", "root_ts": "1760001000.000100", "last_ts": self.ROOT_LAST}

        requests = self.replies_requests(known_threads=[known])

        self.assertEqual([query(request).get("oldest") for request in requests], [None])

    def test_reads_in_full_without_known_threads(self):
        requests = self.replies_requests()

        self.assertEqual([query(request).get("oldest") for request in requests], [None])


class SearchRereadTransportEqualityTest(unittest.TestCase):
    ROOT, REPLY, MESSAGE = "1792300500.000200", "1792396000.000300", "1792395000.000100"

    def sources(self):
        stored = [
            {"kind": "dm", "channel": "D5", "root_ts": None, "last_ts": "1792300000.000100"},
            {"kind": "thread", "channel": "C6", "root_ts": self.ROOT, "last_ts": "1792300600.000300"},
        ]
        return reread_source(*stored, owner="U2")

    def over_relay(self):
        responses = {
            "team-chat-1": saved("search_empty.json"),
            "team-chat-2": conversation_page("D5", ("U1", self.MESSAGE, "still open"), names=USERS),
            "team-chat-3": thread_page(thread_reply("U2", self.REPLY, "Thanks", index=1, total=1), root=self.ROOT, total=1),
        }
        return search_parse(self.sources(), responses)

    def over_api(self):
        root = {"type": "message", "user": "U1", "text": "Release notes", "ts": self.ROOT, "thread_ts": self.ROOT, "reply_count": 1}
        routes = {
            SEARCH_PATH: [search_doc()],
            HISTORY_PATH: [history_doc({"type": "message", "user": "U1", "text": "still open", "ts": self.MESSAGE})],
            REPLIES_PATH: [history_doc(root, reply_item(self.REPLY, text="Thanks", user="U2", root=self.ROOT))],
        }
        return api_units(routes, window=SEARCH_WINDOW, source=self.sources())[1]

    def test_both_transports_give_the_same_units_for_a_reread_conversation_and_thread(self):
        self.assertEqual(state.dump(self.over_relay()["records"]), state.dump(self.over_api()["records"]))


MENTION_CASES = {
    "a_user_mention": ("ping <@U000001> now", ["U000001"], []),
    "a_user_mention_with_a_name": ("ping <@U000001|Owner Name> now", ["U000001"], []),
    "an_enterprise_user_mention": ("ping <@W000001> now", ["W000001"], []),
    "a_group_mention": ("ping <!subteam^S000001> now", [], ["S000001"]),
    "a_group_mention_with_a_label": ("ping <!subteam^S000001|@core> now", [], ["S000001"]),
    "duplicates_sorted": ("<@U000003> <@U000001> <@U000003> <!subteam^S000002> <!subteam^S000001> <!subteam^S000002>", ["U000001", "U000003"], ["S000001", "S000002"]),
    "a_mention_past_the_300_character_cut": ("x" * 310 + " <@U000001> <!subteam^S000001>", ["U000001"], ["S000001"]),
    "no_mention": ("hello", [], []),
    "an_id_written_as_plain_text": ("see U000001 and S000001 and @U000001 and subteam^S000001", [], []),
    "a_channel_or_broadcast_markup": ("<!here> <!channel> <#C000001|ops>", [], []),
}


def mentions_over_relay(text):
    responses = {"team-chat-1": search_text(hit("C4", "#dev", PEER, "1792397500.000100", text=text))}
    return search_parse(search_source(), responses)["records"]["units"][0]["messages"][0]


def mentions_over_api(text):
    match = api_match("C4", "1760004000.000400", text=text, channel_name="dev")
    return api_units({SEARCH_PATH: [search_doc(match)]})[1]["records"]["units"][0]["messages"][0]


def mention_tests(read, transport):
    def build(text, mentions, groups):
        def test(self):
            message = read(text)
            self.assertEqual((message["mentions"], message["group_mentions"]), (mentions, groups))

        return test

    return {f"test_reads_{transport}_{name}": build(*case) for name, case in MENTION_CASES.items()}


class SearchRelayMentionsTest(unittest.TestCase):
    def test_cuts_the_text_but_not_the_mentions(self):
        text = "x" * 310 + " <@U000001>"

        self.assertEqual(len(mentions_over_relay(text)["text"]), 300)

    def test_reads_the_mentions_of_a_search_hit_fixture(self):
        message = search_parse(search_source(), {"team-chat-1": saved("search_mentions.json")})["records"]["units"][0]["messages"][0]

        self.assertEqual((message["mentions"], message["group_mentions"]), (["U000001"], ["S000001"]))

    def test_reads_the_mentions_of_a_channel_read_fixture(self):
        responses = {"team-chat-1": search_text(hit("D000005", "DM", PEER, "1792395500.000200")), "team-chat-2": saved("read_mentions.json")}

        message = search_parse(search_source(), responses)["records"]["units"][0]["messages"][0]

        self.assertEqual((message["mentions"], message["group_mentions"]), (["U000001"], ["S000002"]))

    def test_reads_the_mentions_of_a_thread_read_fixture(self):
        responses = {"team-chat-1": search_text(hit("C000003", "#ops", PEER, "1792398500.000100", thread=THREAD_ROOT)), "team-chat-2": saved("thread_mentions.json")}

        messages = search_parse(search_source(), responses)["records"]["units"][0]["messages"]

        self.assertEqual([(item["mentions"], item["group_mentions"]) for item in messages], [([], ["S000001"]), (["U000001"], [])])

    def test_keeps_the_text_cleaned_of_the_mention_markup(self):
        message = search_parse(search_source(), {"team-chat-1": saved("search_mentions.json")})["records"]["units"][0]["messages"][0]

        self.assertEqual([char in message["text"] for char in "<>@"], [False, False, False])


class SearchApiMentionsTest(unittest.TestCase):
    def test_reads_the_mentions_of_a_conversation_read(self):
        history = history_doc({"type": "message", "user": "U2", "text": "hi <@U000001> and <!subteam^S000002|@core>", "ts": "1760004000.000400"})
        routes = {SEARCH_PATH: [search_doc(api_match("D1", "1760004000.000400", im=True))], HISTORY_PATH: [history], INFO_PATH: [info_doc("D1", "U2")]}

        message = api_units(routes)[1]["records"]["units"][0]["messages"][0]

        self.assertEqual((message["mentions"], message["group_mentions"]), (["U000001"], ["S000002"]))

    def test_reads_the_mentions_of_a_thread_read(self):
        replies = history_doc(
            {**root_item(ROOT_TS, 1), "text": "Hey <!subteam^S000001> :wave:"},
            reply_item("1760005000.000500", text="Hi <@U000001|Peer Name> question", root=ROOT_TS),
        )
        routes = {SEARCH_PATH: [search_doc(api_match("C3", "1760005000.000500", thread=ROOT_TS))], REPLIES_PATH: [replies]}

        messages = api_units(routes)[1]["records"]["units"][0]["messages"]

        self.assertEqual([(item["mentions"], item["group_mentions"]) for item in messages], [([], ["S000001"]), (["U000001"], [])])


class SearchMentionsTransportEqualityTest(unittest.TestCase):
    TEXT = MENTION_CASES["duplicates_sorted"][0] + " <!subteam^S000009|@x> <@U000001|name>"

    def test_both_transports_give_the_same_mentions_for_the_same_text(self):
        relay, api = mentions_over_relay(self.TEXT), mentions_over_api(self.TEXT)

        self.assertEqual(
            ((relay["mentions"], relay["group_mentions"]), (api["mentions"], api["group_mentions"])),
            ((["U000001", "U000003"], ["S000001", "S000002", "S000009"]),) * 2,
        )


for _name, _test in {**mention_tests(mentions_over_relay, "over_the_connector"), **mention_tests(mentions_over_api, "over_the_api")}.items():
    target = SearchRelayMentionsTest if "connector" in _name else SearchApiMentionsTest
    setattr(target, _name, _test)


class InvalidEntityTest(unittest.TestCase):
    LONG_ROOT = "12345678901234567.000100"

    def responses(self):
        return {"team-chat-1": search_text(hit("C4", "#dev", PEER, "1792396000.000100", thread=self.LONG_ROOT))}

    def test_fails_the_thread_of_a_hit_whose_root_is_not_a_slack_ts(self):
        result = search_parse(search_source(), self.responses())

        self.assertEqual(result["entries"], {f"C4:{self.LONG_ROOT}": failed("invalid entity id")})

    def test_still_reads_the_source_when_a_root_is_not_a_slack_ts(self):
        self.assertTrue(search_parse(search_source(), self.responses())["records"]["units"] == [])


class SearchStoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def session(self, transport="mcp"):
        return store_session(self.tmp.name, transport)

    def kinds(self, session):
        return sorted(os.listdir(session.base))

    def document(self, session, relative):
        with open(os.path.join(session.base, relative, store.READ_FILE), encoding="utf-8") as stream:
            return json.load(stream)


class SearchRelayStoreTest(SearchStoreCase):
    def run_store(self, source, responses):
        session = self.session()
        return session, relay_through(session, responses, source=source, cursor={}, window=SEARCH_WINDOW)[1]

    def test_names_the_first_search_call_by_its_read(self):
        step = slack.plan(search_source(), SEARCH_WINDOW, {}, [], self.session(), CONNECTOR)

        self.assertEqual(step["calls"][0]["id"], f"kind=search/search=dms/read=1792390000_1792400000-{RUN}.team-chat/page-001")

    def test_gives_the_units_of_the_same_responses_by_call_order(self):
        _, result = self.run_store(search_source(), full_responses())

        self.assertEqual(state.dump(result), state.dump(search_parse(search_source(), full_responses())))

    def test_files_the_search_the_conversation_and_the_thread_reads(self):
        session, _ = self.run_store(search_source(), full_responses())

        self.assertEqual(self.kinds(session), ["kind=history", "kind=search", "kind=thread"])

    def test_starts_a_whole_thread_read_at_its_root(self):
        session, _ = self.run_store(search_source(), full_responses())

        reads = [name for _, folders, _ in os.walk(os.path.join(session.base, "kind=thread")) for name in folders if name.startswith("read=")]
        self.assertEqual(reads, [f"read={THREAD_ROOT}_1792400000-{RUN}.team-chat"])

    def test_marks_a_search_cut_at_its_page_cap_partial(self):
        session, _ = self.run_store(search_source(search_page_cap=1), {"team-chat-1": search_text(hit("C4", "#dev", PEER, "1792396000.000100"), cursor="next")})

        relative = f"kind=search/search=dms/read=1792390000_1792400000-{RUN}.team-chat"
        self.assertEqual(self.document(session, relative)["outcome"], {"reason": "partial: search cut", "status": "partial"})

    def test_marks_an_unreadable_reactions_read_failed(self):
        entries = [(PEER, "1792395000.000100", "question")]
        responses = {"team-chat-1": search_text(hit("D1", "DM", PEER, entries[0][1])), "team-chat-2": conversation_page("D1", *entries), "team-chat-3": "{}"}
        session, _ = self.run_store(search_source(reactions=True), responses)

        relative = f"kind=reactions/channel=D1/message=1792395000.000100/read={RUN}.team-chat"
        self.assertEqual(self.document(session, relative)["outcome"], {"reason": "unreadable reactions response", "status": "failed"})

    def test_writes_the_hits_of_a_search_read(self):
        session, _ = self.run_store(search_source(), full_responses())

        records = session.open("search", (("search", "dms"),), ("1792390000", "1792400000")).records()
        self.assertEqual(len(records), 3)


class SearchApiStoreTest(SearchStoreCase):
    MESSAGE = {"type": "message", "user": "U2", "text": "question", "ts": "1760004000.000400"}

    def routes(self):
        return {
            SEARCH_PATH: [search_doc(api_match("D1", "1760004000.000400", im=True))],
            HISTORY_PATH: [history_doc(self.MESSAGE)],
            INFO_PATH: [info_doc("D1", "U2")],
            REACTIONS_PATH: [reaction_doc(OWNER)],
        }

    def fetch_store(self, users=None):
        known = {user: user_doc(name) for user, name in USERS.items()} if users is None else users
        opener, session = RoutedOpener(self.routes(), known), self.session("api")
        session.http = client(opener)
        return opener, session, slack.fetch(search_source(reactions=True), WINDOW, {}, [], session)

    def test_gives_the_units_of_a_fetch_without_store(self):
        _, _, result = self.fetch_store()

        self.assertEqual(state.dump(result), state.dump(api_units(self.routes(), reactions=True)[1]))

    def test_makes_the_same_calls_as_a_fetch_without_store(self):
        opener, _, _ = self.fetch_store()

        self.assertEqual(path_counts(opener), path_counts(api_units(self.routes(), reactions=True)[0]))

    def test_files_members_user_and_reactions_reads(self):
        _, session, _ = self.fetch_store()

        self.assertEqual(self.kinds(session), ["kind=history", "kind=members", "kind=reactions", "kind=search", "kind=users"])

    def test_writes_an_unknown_user_as_an_empty_name(self):
        users = {user: user_doc(name) for user, name in USERS.items()}
        _, session, _ = self.fetch_store({**users, "U2": error_doc("user_not_found")})

        self.assertEqual(session.open("users", (("user", "U2"),), None).records(), [{"name": ""}])


if __name__ == "__main__":
    unittest.main()
