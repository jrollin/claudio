import decimal
import json
import tempfile
import unittest

import state
import store
from providers import _slack_reads as reads
from providers._errors import PartialRead, SourceUnreadable
from providers._slack_read import HISTORY_PATH, ChannelFailed, Item, _api_page, _relay_page
from providers._slack_search import Hit, _search_page, _search_types, _unit_thread_page
from providers.slack_support import ROOT_TS, fixture

CHANNEL = "CHAN1"
START = decimal.Decimal("1760000500.000050")
TO = 1760010800
RUN = "20261020T073004Z-z1x7pc"
HISTORY_ARGUMENTS = {"channel_id": CHANNEL, "oldest": str(START), "latest": str(TO), "limit": 30, "response_format": "detailed"}
THREAD_ARGUMENTS = {"channel_id": CHANNEL, "message_ts": ROOT_TS, "limit": 20, "response_format": "detailed"}
SEARCH_ARGUMENTS = {"filters": "to:me", "channel_types": "im,mpim", "after": "1760000000", "before": str(TO)}
ITEM = Item(CHANNEL, "1760003000.000300", None, "U2", "Deploy done", "Bea Example", False)
ROOT = Item(CHANNEL, ROOT_TS, ROOT_TS, "U1", "Release notes", "Ada Example", False)
HIT = Hit("D000001", "DM", "DM", [("U000009", "Bot App"), ("U000001", "Owner Name")], "1792397053.514349", Item("D000001", "1792397053.514349", "1792397053.514349", "U000009", "hello", "Bot App", True))


def relay_request(arguments, cursor=None):
    return {"tool": "slack_read_channel", "arguments": arguments if cursor is None else {**arguments, "cursor": cursor}}


def api_record(path, response, error=None):
    return json.dumps({"method": "GET", "path": path, "query": "", "body": None, "status": 200, "link": None, "response": response, "error": error}).encode("utf-8")


def read_document(kind, transport, entity, span, requests):
    return {
        "kind": kind,
        "transport": transport,
        "entity": entity,
        "span": None if span is None else {"from": span[0], "to": span[1]},
        "pages": [{"file": f"page-{number:03d}{store.PAGE_SUFFIXES[transport]}", "request": request} for number, request in enumerate(requests, 1)],
    }


class KeyTest(unittest.TestCase):
    def test_keys_a_history_read_by_channel_and_span(self):
        self.assertEqual(reads.history_key(CHANNEL, START, TO), reads.ReadKey("history", (("channel", CHANNEL),), (str(START), str(TO))))

    def test_starts_a_whole_thread_read_at_its_root(self):
        self.assertEqual(reads.thread_key(CHANNEL, ROOT_TS, None, TO).span, (ROOT_TS, str(TO)))

    def test_starts_a_thread_read_at_its_oldest(self):
        self.assertEqual(reads.thread_key(CHANNEL, ROOT_TS, decimal.Decimal("1760002500.000099"), TO).span, ("1760002500.000099", str(TO)))

    def test_keys_a_thread_read_by_channel_and_root(self):
        self.assertEqual(reads.thread_key(CHANNEL, ROOT_TS, None, TO).entity, (("channel", CHANNEL), ("root", ROOT_TS)))

    def test_keys_a_reactions_read_by_message_without_span(self):
        self.assertEqual(reads.reactions_key(CHANNEL, ROOT_TS), reads.ReadKey("reactions", (("channel", CHANNEL), ("message", ROOT_TS)), None))

    def test_keys_a_members_read_by_channel(self):
        self.assertEqual(reads.members_key("D000001"), reads.ReadKey("members", (("channel", "D000001"),), None))

    def test_keys_a_user_lookup_by_user(self):
        self.assertEqual(reads.users_key("U000001"), reads.ReadKey("users", (("user", "U000001"),), None))

    def test_percent_encodes_a_search_name(self):
        self.assertEqual(reads.search_key("own/threads=..", 1760000000, TO).entity, (("search", "own%2Fthreads%3D.."),))

    def test_names_the_hive_folder_of_a_key(self):
        session = store.ReadSession(tempfile.gettempdir(), "chat", RUN, "chat", "slack", "mcp")

        handle = session.open(*reads.thread_key(CHANNEL, ROOT_TS, None, TO))

        self.assertEqual(handle.relative, f"kind=thread/channel={CHANNEL}/root={ROOT_TS}/read={ROOT_TS}_{TO}-{RUN}.chat")

    def test_refuses_a_channel_id_that_is_not_a_slack_id(self):
        for channel in ("chan1", "C/1", "", "C" * 33, None):
            with self.subTest(channel=channel), self.assertRaises(reads.InvalidEntity) as caught:
                reads.history_key(channel, START, TO)
            self.assertEqual(caught.exception.code, "invalid entity id")

    def test_refuses_a_root_that_is_not_a_message_ts(self):
        for root in ("1760002000", "../x", "1." + "0" * 10):
            with self.subTest(root=root), self.assertRaises(reads.InvalidEntity):
                reads.thread_key(CHANNEL, root, None, TO)

    def test_refuses_a_message_ts_that_is_not_one(self):
        with self.assertRaises(reads.InvalidEntity):
            reads.reactions_key(CHANNEL, "1760002000/x")

    def test_refuses_a_user_id_that_is_not_a_slack_id(self):
        with self.assertRaises(reads.InvalidEntity):
            reads.users_key("u1")

    def test_never_names_the_refused_id(self):
        with self.assertRaises(reads.InvalidEntity) as caught:
            reads.history_key("C/secret", START, TO)

        self.assertNotIn("secret", str(caught.exception))


class RowsTest(unittest.TestCase):
    def test_leaves_the_channel_out_of_a_history_row(self):
        self.assertEqual(
            reads.to_rows("history", [ITEM]),
            [{"author": "U2", "bot": False, "name": "Bea Example", "text": "Deploy done", "thread_ts": None, "ts": "1760003000.000300"}],
        )

    def test_restores_a_history_record_from_its_row(self):
        self.assertEqual(reads.from_rows("history", {"channel": CHANNEL}, reads.to_rows("history", [ITEM, ROOT])), [ITEM, ROOT])

    def test_leaves_the_channel_and_thread_out_of_a_thread_row(self):
        self.assertEqual(reads.to_rows("thread", [ROOT]), [{"author": "U1", "bot": False, "name": "Ada Example", "text": "Release notes", "ts": ROOT_TS}])

    def test_restores_the_root_as_the_thread_of_every_thread_record(self):
        reply = Item(CHANNEL, "1760002600.000260", None, "U2", "Fixed", "", False)

        restored = reads.from_rows("thread", {"channel": CHANNEL, "root": ROOT_TS}, reads.to_rows("thread", [reply]))

        self.assertEqual(restored, [reply._replace(thread_ts=ROOT_TS)])

    def test_restores_a_search_hit_from_its_row(self):
        self.assertEqual(reads.from_rows("search", {"search": "mentions"}, reads.to_rows("search", [HIT])), [HIT])

    def test_restores_an_api_search_hit_with_its_channel_type(self):
        hit = HIT._replace(kind_type="im")

        self.assertEqual(reads.from_rows("search", {"search": "mentions"}, reads.to_rows("search", [hit])), [hit])

    def test_restores_the_reacting_users(self):
        self.assertEqual(reads.from_rows("reactions", {}, reads.to_rows("reactions", ["U000001", "U000002"])), ["U000001", "U000002"])

    def test_restores_the_members_in_order(self):
        self.assertEqual(reads.from_rows("members", {}, reads.to_rows("members", ["U000002", "U000001"])), ["U000002", "U000001"])

    def test_restores_a_user_name(self):
        self.assertEqual(reads.from_rows("users", {"user": "U000001"}, reads.to_rows("users", ["Owner Name"])), ["Owner Name"])

    def test_refuses_a_row_without_one_of_its_fields(self):
        with self.assertRaises(state.Rejected) as caught:
            reads.from_rows("history", {"channel": CHANNEL}, [{"ts": "1760003000.000300"}])

        self.assertIn("history", str(caught.exception))

    def test_refuses_an_unknown_kind(self):
        with self.assertRaises(state.Rejected):
            reads.to_rows("channel", [ITEM])


class RelayParseTest(unittest.TestCase):
    def test_parses_channel_pages_as_the_walk_does(self):
        pages = [fixture("read_chan1_page_1.json"), fixture("read_chan1_page_2.json")]
        read = read_document("history", "mcp", {"channel": CHANNEL}, (str(START), str(TO)), [relay_request(HISTORY_ARGUMENTS), relay_request(HISTORY_ARGUMENTS, "c2")])
        seen = set()
        expected = [item for page in pages for item in _relay_page(CHANNEL, "page", page.decode("utf-8"), seen, START)[0]]

        self.assertEqual(reads.parse_read("history", read, pages), expected)

    def test_parses_newest_first_thread_pages_without_repeating_a_reply(self):
        pages = [fixture("thread_chan1_page_1.json"), fixture("thread_chan1_page_2.json")]
        read = read_document("thread", "mcp", {"channel": CHANNEL, "root": ROOT_TS}, (ROOT_TS, str(TO)), [relay_request(THREAD_ARGUMENTS), relay_request(THREAD_ARGUMENTS, "c2")])

        records = reads.parse_read("thread", read, pages)

        replies = [item.ts for item in records if item.ts != ROOT_TS]
        self.assertEqual(len(replies), len(set(replies)))

    def test_parses_thread_pages_as_the_unit_walk_does(self):
        pages = [fixture("thread_chan1_page_1.json"), fixture("thread_chan1_page_2.json")]
        read = read_document("thread", "mcp", {"channel": CHANNEL, "root": ROOT_TS}, (ROOT_TS, str(TO)), [relay_request(THREAD_ARGUMENTS), relay_request(THREAD_ARGUMENTS, "c2")])
        seen = set()
        expected = [item for page in pages for item in _unit_thread_page(CHANNEL, "page", page.decode("utf-8"), ROOT_TS, TO, seen)[0]]

        self.assertEqual(reads.parse_read("thread", read, pages), expected)

    def test_parses_search_pages_with_the_channel_types_of_the_call(self):
        pages = [fixture("search_page_1.json")]
        read = read_document("search", "mcp", {"search": "conversations"}, ("1760000000", str(TO)), [{"tool": "slack_search_public_and_private", "arguments": SEARCH_ARGUMENTS}])

        self.assertEqual(reads.parse_read("search", read, pages), _search_page("page", pages[0].decode("utf-8"), _search_types(SEARCH_ARGUMENTS))[0])

    def test_parses_the_reacting_users_sorted(self):
        read = read_document("reactions", "mcp", {"channel": CHANNEL, "message": ROOT_TS}, None, [{"tool": "slack_get_reactions", "arguments": {}}])

        self.assertEqual(reads.parse_read("reactions", read, [fixture("reactions_some.json")]), ["U000001", "U000002"])

    def test_reads_a_page_saved_as_the_harness_text_blocks(self):
        page = fixture("read_chan1_page_2.json")
        wrapped = json.dumps([{"type": "text", "text": page.decode("utf-8")}]).encode("utf-8")
        read = read_document("history", "mcp", {"channel": CHANNEL}, (str(START), str(TO)), [relay_request(HISTORY_ARGUMENTS)])

        self.assertEqual(reads.parse_read("history", read, [wrapped]), reads.parse_read("history", read, [page]))

    def test_keeps_a_deeply_nested_page_as_text(self):
        self.assertEqual(reads.page_text("page-001.txt", b"[" * 200000), "[" * 200000)

    def test_names_the_page_it_cannot_read(self):
        read = read_document("history", "mcp", {"channel": CHANNEL}, (str(START), str(TO)), [relay_request(HISTORY_ARGUMENTS)])

        with self.assertRaises(SourceUnreadable) as caught:
            reads.parse_read("history", read, [b"not json"])

        self.assertIn("page-001.txt", str(caught.exception))

    def test_refuses_a_page_that_is_not_utf8(self):
        read = read_document("history", "mcp", {"channel": CHANNEL}, (str(START), str(TO)), [relay_request(HISTORY_ARGUMENTS)])

        with self.assertRaises(SourceUnreadable):
            reads.parse_read("history", read, [b"\xff\xfe"])

    def test_refuses_a_members_read_over_the_connector(self):
        read = read_document("members", "mcp", {"channel": "D000001"}, None, [{"tool": "x", "arguments": {}}])

        with self.assertRaises(SourceUnreadable):
            reads.parse_read("members", read, [b"{}"])


class ApiParseTest(unittest.TestCase):
    def test_parses_history_records_as_the_walk_does(self):
        body = json.loads(fixture("history_chan1_page_1.json"))
        read = read_document("history", "api", {"channel": CHANNEL}, (str(START), str(TO)), [{"method": "GET", "path": HISTORY_PATH, "query": "", "body": None}])

        self.assertEqual(reads.parse_read("history", read, [api_record(HISTORY_PATH, body)]), _api_page(CHANNEL, HISTORY_PATH, body))

    def test_raises_the_channel_failure_of_a_refused_read(self):
        read = read_document("history", "api", {"channel": CHANNEL}, (str(START), str(TO)), [{"method": "GET", "path": HISTORY_PATH, "query": "", "body": None}])

        with self.assertRaises(ChannelFailed) as caught:
            reads.parse_read("history", read, [api_record(HISTORY_PATH, {"ok": False, "error": "not_in_channel"})])

        self.assertEqual(caught.exception.code, "not_in_channel")

    def test_raises_the_recorded_error_of_a_failed_call(self):
        error = {"class": "SourceUnreadable", "message": f"GET {HISTORY_PATH}: HTTP 500", "status": 500}
        read = read_document("history", "api", {"channel": CHANNEL}, (str(START), str(TO)), [{"method": "GET", "path": HISTORY_PATH, "query": "", "body": None}])

        with self.assertRaises(SourceUnreadable) as caught:
            reads.parse_read("history", read, [api_record(HISTORY_PATH, None, error)])

        self.assertEqual((str(caught.exception), caught.exception.status), (error["message"], 500))

    def test_raises_a_recorded_partial_read_as_partial(self):
        error = {"class": "PartialRead", "message": "partial: page cap", "status": None}
        read = read_document("history", "api", {"channel": CHANNEL}, (str(START), str(TO)), [{"method": "GET", "path": HISTORY_PATH, "query": "", "body": None}])

        with self.assertRaises(PartialRead):
            reads.parse_read("history", read, [api_record(HISTORY_PATH, None, error)])

    def test_names_a_record_that_is_not_json(self):
        read = read_document("history", "api", {"channel": CHANNEL}, (str(START), str(TO)), [{"method": "GET", "path": HISTORY_PATH, "query": "", "body": None}])

        with self.assertRaises(SourceUnreadable) as caught:
            reads.parse_read("history", read, [b"{"])

        self.assertIn("page-001.json", str(caught.exception))

    def test_parses_the_other_member_of_a_direct_conversation(self):
        read = read_document("members", "api", {"channel": "D000001"}, None, [{"method": "GET", "path": "/api/conversations.info", "query": "", "body": None}])

        records = reads.parse_read("members", read, [api_record("/api/conversations.info", {"ok": True, "channel": {"user": "U000002"}})])

        self.assertEqual(records, ["U000002"])

    def test_parses_the_members_of_a_group_conversation(self):
        read = read_document("members", "api", {"channel": "G000001"}, None, [{"method": "GET", "path": "/api/conversations.members", "query": "", "body": None}])

        records = reads.parse_read("members", read, [api_record("/api/conversations.members", {"ok": True, "members": ["U000002", "U000003"]})])

        self.assertEqual(records, ["U000002", "U000003"])

    def test_parses_an_unknown_user_as_an_empty_name(self):
        read = read_document("users", "api", {"user": "U000002"}, None, [{"method": "GET", "path": "/api/users.info", "query": "", "body": None}])

        self.assertEqual(reads.parse_read("users", read, [api_record("/api/users.info", {"ok": False, "error": "user_not_found"})]), [""])

    def test_parses_the_reacting_users_of_a_message(self):
        body = {"ok": True, "message": {"reactions": [{"name": "eyes", "users": ["U000002", "U000001"]}, {"name": "+1", "users": ["U000002"]}]}}
        read = read_document("reactions", "api", {"channel": CHANNEL, "message": ROOT_TS}, None, [{"method": "GET", "path": "/api/reactions.get", "query": "", "body": None}])

        self.assertEqual(reads.parse_read("reactions", read, [api_record("/api/reactions.get", body)]), ["U000001", "U000002"])

    def test_keeps_every_search_hit_for_the_walk_to_filter(self):
        match = {"channel": {"id": "C000002", "name": "general", "is_private": True}, "ts": "1760003000.000300", "user": "U2", "text": "hi", "permalink": ""}
        read = read_document("search", "api", {"search": "mentions"}, ("1760000000", str(TO)), [{"method": "GET", "path": "/api/search.messages", "query": "", "body": None}])

        records = reads.parse_read("search", read, [api_record("/api/search.messages", {"ok": True, "messages": {"matches": [match], "paging": {"pages": 1}}})])

        self.assertEqual([(hit.channel, hit.kind_type) for hit in records], [("C000002", "private_channel")])

    def test_names_the_search_of_a_refused_search_page(self):
        read = read_document("search", "api", {"search": "own%2Fthreads"}, ("1760000000", str(TO)), [{"method": "GET", "path": "/api/search.messages", "query": "", "body": None}])

        with self.assertRaises(SourceUnreadable) as caught:
            reads.parse_read("search", read, [api_record("/api/search.messages", {"ok": False, "error": "invalid_auth"})])

        self.assertIn("own/threads", str(caught.exception))


class ParseReadTest(unittest.TestCase):
    def test_refuses_a_read_of_another_kind(self):
        read = read_document("history", "mcp", {"channel": CHANNEL}, (str(START), str(TO)), [])

        with self.assertRaises(state.Rejected):
            reads.parse_read("thread", read, [])

    def test_refuses_pages_that_do_not_match_the_listed_ones(self):
        read = read_document("history", "mcp", {"channel": CHANNEL}, (str(START), str(TO)), [relay_request(HISTORY_ARGUMENTS)])

        with self.assertRaises(state.Rejected):
            reads.parse_read("history", read, [])

    def test_parses_a_read_with_no_page_as_no_record(self):
        read = read_document("history", "mcp", {"channel": CHANNEL}, (str(START), str(TO)), [])

        self.assertEqual(reads.parse_read("history", read, []), [])


if __name__ == "__main__":
    unittest.main()
