import decimal
import json
import os
import tempfile
import unittest
import urllib.parse

import days
import state
import store
from providers import _slack_reads as reads
from providers import slack
from providers._errors import PartialRead, SourceUnreadable
from providers._slack_read import HISTORY_PATH, ChannelFailed, Item, _api_page, _Calls, _Pending, _relay_page
from providers._slack_search import MEMBERS_PATH, REACTIONS_TOOL, SEARCH_TOOL, Hit, _search_page, _search_types, _unit_thread_page
from providers.slack_support import CONNECTOR, ROOT_TS, STORED, WINDOW, fixture, one_channel, relay_message, relay_page
from providers.test_http import FakeOpener, FakeResponse, make_client

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


class DayRowTest(unittest.TestCase):
    def test_files_a_history_row_by_its_ts(self):
        row = {"ts": "1793059199.999999", "author": "U0A", "text": "hi", "thread_ts": None, "name": "", "bot": False}

        self.assertEqual(reads.day_row("history", {"channel": "C0A"}, row), ("1793059199.999999", "1793059199.999999"))

    def test_files_a_thread_row_by_its_ts(self):
        row = {"ts": "1793059200.000100", "author": "U0A", "text": "hi", "name": "", "bot": False}

        self.assertEqual(reads.day_row("thread", {"channel": "C0A", "root": "1793000000.000100"}, row), ("1793059200.000100", "1793059200.000100"))

    def test_files_a_search_hit_by_its_message_ts_keyed_by_channel(self):
        item = {"ts": "1793000000.000200", "author": "U0A", "text": "hi", "thread_ts": None, "name": "", "bot": False}
        row = {"channel": "C0B", "name": "b", "kind": None, "participants": [], "root": None, "kind_type": None, "item": item}

        self.assertEqual(reads.day_row("search", {"search": "mentions"}, row), ("1793000000.000200", "C0B:1793000000.000200"))

    def test_files_a_reaction_by_the_message_it_reacts_to(self):
        self.assertEqual(reads.day_row("reactions", {"channel": "C0A", "message": "1793000000.000300"}, {"user": "U0B"}), ("1793000000.000300", "U0B"))

    def test_refuses_a_kind_not_filed_by_day(self):
        with self.assertRaises(state.Rejected):
            reads.day_row("members", {"channel": "C0A"}, {"id": "U0A"})


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


SHARED_RUN = "20251009T115000Z-a1b2c3"
STORED_AT = "2025-10-09T11:50:00Z"
RUNTIME = "ab" * 20
MID = "1760009000"
NEW = Item(CHANNEL, "1760009500.000100", None, "U3", "Shipped", "Cy Example", False)
REPLY = Item(CHANNEL, "1760002500.000100", ROOT_TS, "U2", "Thanks", "Bea Example", False)
THREAD_ROOT = Item(CHANNEL, ROOT_TS, ROOT_TS, "U1", "Release notes", "Ada Example", False)


class ReuseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.shared = os.path.join(self.tmp.name, "shared")

    def store_read(self, key, rows, transport="mcp", status="complete", fetched_at=STORED_AT):
        root = os.path.join(self.tmp.name, "other", transport)
        session = store.ReadSession(root, "chat", SHARED_RUN, "channels", "slack", transport, clock=lambda: fetched_at, runtime=RUNTIME, shared=self.shared)
        handle = session.open(*key)
        handle.page({"tool": "stored"}, fetch=lambda: b"stored page")
        handle.finish(status, None if status == "complete" else "why", rows)

    def session(self, transport="mcp"):
        root = os.path.join(self.tmp.name, "run", "store")
        return store.ReadSession(root, "chat", RUN, "team-chat", "slack", transport, clock=lambda: "2025-10-09T11:55:00Z", runtime=RUNTIME, shared=self.shared)

    def relay(self, max_age=60, session=None):
        return reads.RelayReads(session or self.session(), reads.Freshness(max_age, TO))

    def pending(self, call):
        with self.assertRaises(_Pending) as caught:
            call()
        return caught.exception

    def answer(self, session, pending, text):
        path = session.page_path(pending.call_id)
        store.make_folders(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(text)


class RelayHistoryReuseTest(ReuseCase):
    def stored_history(self, **options):
        self.store_read(reads.history_key(CHANNEL, START, MID), reads.to_rows("history", [ITEM]), **options)

    def test_reads_only_the_gap_after_a_fresh_read(self):
        self.stored_history()

        pending = self.pending(lambda: self.relay().history(CHANNEL, START, TO))

        self.assertEqual(pending.arguments, {**HISTORY_ARGUMENTS, "oldest": MID})

    def test_merges_the_reused_and_the_fetched_messages(self):
        self.stored_history()
        session = self.session()
        pending = self.pending(lambda: self.relay(session=session).history(CHANNEL, START, TO))
        self.answer(session, pending, relay_page(CHANNEL, relay_message("U3", NEW.ts, "Shipped")))

        found = self.relay(session=session).history(CHANNEL, START, TO)

        self.assertEqual([item.ts for item in found], [ITEM.ts, NEW.ts])

    def test_reads_the_whole_span_with_a_max_age_of_zero(self):
        self.stored_history()

        pending = self.pending(lambda: self.relay(max_age=0).history(CHANNEL, START, TO))

        self.assertEqual(pending.arguments, HISTORY_ARGUMENTS)

    def test_reads_the_whole_span_without_freshness(self):
        self.stored_history()

        pending = self.pending(lambda: reads.RelayReads(self.session()).history(CHANNEL, START, TO))

        self.assertEqual(pending.arguments, HISTORY_ARGUMENTS)

    def test_rereads_a_span_whose_read_failed(self):
        self.stored_history(status="failed")

        pending = self.pending(lambda: self.relay().history(CHANNEL, START, TO))

        self.assertEqual(pending.arguments, HISTORY_ARGUMENTS)

    def test_rereads_a_span_whose_read_is_partial(self):
        self.stored_history(status="partial")

        pending = self.pending(lambda: self.relay().history(CHANNEL, START, TO))

        self.assertEqual(pending.arguments, HISTORY_ARGUMENTS)

    def test_needs_no_call_for_a_covered_span(self):
        self.store_read(reads.history_key(CHANNEL, START, TO), reads.to_rows("history", [ITEM, NEW]))

        self.assertEqual(self.relay().history(CHANNEL, START, TO), [ITEM, NEW])

    def test_keeps_the_newest_fetch_of_a_message(self):
        edited = NEW._replace(text="Shipped, edited")
        self.store_read(reads.history_key(CHANNEL, START, TO), reads.to_rows("history", [NEW]), fetched_at="2025-10-09T11:40:00Z")
        self.store_read(reads.history_key(CHANNEL, MID, TO), reads.to_rows("history", [edited]))

        self.assertEqual(self.relay().history(CHANNEL, START, TO), [edited])

    def test_keeps_only_messages_of_the_needed_span(self):
        early = ITEM._replace(ts="1760000100.000100")
        self.store_read(reads.history_key(CHANNEL, "1760000000", TO), reads.to_rows("history", [early, ITEM]))

        self.assertEqual(self.relay().history(CHANNEL, START, TO), [ITEM])


class RelayThreadReuseTest(ReuseCase):
    def test_reads_a_thread_from_the_end_of_its_fresh_read(self):
        self.store_read(reads.thread_key(CHANNEL, ROOT_TS, None, MID), reads.to_rows("thread", [THREAD_ROOT, REPLY]))

        pending = self.pending(lambda: self.relay().thread(CHANNEL, ROOT_TS, None, TO))

        self.assertEqual(pending.arguments, {**THREAD_ARGUMENTS, "oldest": MID})

    def test_reuses_the_root_and_replies_of_a_covered_thread(self):
        self.store_read(reads.thread_key(CHANNEL, ROOT_TS, None, TO), reads.to_rows("thread", [THREAD_ROOT, REPLY]))

        self.assertEqual(self.relay().thread(CHANNEL, ROOT_TS, None, TO), [THREAD_ROOT, REPLY])

    def test_reads_replies_after_the_root_of_a_covered_thread(self):
        self.store_read(reads.thread_key(CHANNEL, ROOT_TS, START, TO), reads.to_rows("thread", [THREAD_ROOT, REPLY]))

        self.assertEqual(self.relay().replies(CHANNEL, ROOT_TS, START, TO), [REPLY])


class RelayKindReuseTest(ReuseCase):
    def test_reuses_the_reactions_of_a_message(self):
        self.store_read(reads.reactions_key(CHANNEL, ITEM.ts), reads.to_rows("reactions", ["U1", "U2"]))

        self.assertEqual(self.relay().reactions(CHANNEL, ITEM.ts), {"U1", "U2"})

    def test_reuses_reactions_only_under_their_own_max_age(self):
        self.store_read(reads.reactions_key(CHANNEL, ITEM.ts), reads.to_rows("reactions", ["U1"]))

        pending = self.pending(lambda: self.relay(max_age={"default": 60, "reactions": 0}).reactions(CHANNEL, ITEM.ts))

        self.assertEqual(pending.tool, REACTIONS_TOOL)

    def test_never_reuses_a_search(self):
        search = {"name": "dms", "filters": "to:me", "channel_types": "im,mpim", "since": "window"}
        self.store_read(reads.search_key("dms", 1760000000, TO), [])

        pending = self.pending(lambda: self.relay().search(search, 1760000000, TO, 2))

        self.assertEqual(pending.tool, SEARCH_TOOL)


class ApiReuseTest(ReuseCase):
    def api(self, opener, max_age=60):
        calls = _Calls(5)
        return reads.ApiReads(self.session("api"), make_client(opener, sleeps=[]), calls, reads.Freshness(max_age, TO)), calls

    def test_an_api_source_rereads_a_span_held_by_a_connector_read(self):
        self.store_read(reads.history_key(CHANNEL, START, TO), reads.to_rows("history", [ITEM]), transport="mcp")
        opener = FakeOpener(FakeResponse(json.dumps({"ok": True, "messages": [], "has_more": False}).encode("utf-8")))
        api, _ = self.api(opener)

        api.history(CHANNEL, START, TO)

        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(opener.requests[0].full_url).query)["oldest"], [str(START)])

    def test_reuses_the_members_of_a_channel_without_a_call(self):
        self.store_read(reads.members_key(CHANNEL), reads.to_rows("members", ["U1", "U2"]), transport="api")
        opener = FakeOpener()
        api, calls = self.api(opener)

        members = api.members(CHANNEL, MEMBERS_PATH)

        self.assertEqual((members, opener.requests, calls.left), (["U1", "U2"], [], 5))

    def test_reuses_a_user_name_under_the_people_max_age(self):
        self.store_read(reads.users_key("U1"), reads.to_rows("users", ["Ada Example"]), transport="api")
        opener = FakeOpener()
        api, _ = self.api(opener, max_age={"people": 1440})

        self.assertEqual((api.user_name("U1"), opener.requests), ("Ada Example", []))


class ClosedDayReuseTest(ReuseCase):
    DAY = 1759968000
    NEXT = DAY + 86400

    def filed(self, key, rows, transport="mcp"):
        root = os.path.join(self.tmp.name, "other", transport)
        session = store.ReadSession(
            root, "chat", SHARED_RUN, "channels", "slack", transport, clock=lambda: STORED_AT, runtime=RUNTIME, shared=self.shared, days=days.DayLayer(self.shared)
        )
        handle = session.open(*key)
        handle.page({"tool": "stored"}, fetch=lambda: b"stored page")
        handle.finish("complete", None, rows)

    def filing_session(self, transport="mcp"):
        root = os.path.join(self.tmp.name, "run", "store")
        return store.ReadSession(root, "chat", RUN, "team-chat", "slack", transport, clock=lambda: "2025-10-11T08:00:00Z", runtime=RUNTIME, shared=self.shared, days=days.DayLayer(self.shared))

    def closing(self, window_end=None, closed_days=True, session=None):
        freshness = reads.Freshness(0, self.NEXT if window_end is None else window_end, closed_days)
        return reads.RelayReads(session or self.filing_session(), freshness)

    def filed_day(self):
        self.filed(reads.history_key(CHANNEL, self.DAY, self.NEXT), reads.to_rows("history", [ITEM]))

    def test_needs_no_call_for_a_closed_day_already_filed(self):
        self.filed_day()

        self.assertEqual(self.closing().history(CHANNEL, START, self.NEXT), [ITEM])

    def test_reads_only_the_span_after_a_filed_closed_day(self):
        self.filed_day()

        pending = self.pending(lambda: self.closing(window_end=self.NEXT + 3600).history(CHANNEL, START, self.NEXT + 600))

        self.assertEqual((pending.arguments["oldest"], pending.arguments["latest"]), (str(self.NEXT), str(self.NEXT + 600)))

    def test_rereads_a_day_that_is_not_closed(self):
        self.filed_day()

        pending = self.pending(lambda: self.closing(window_end=self.NEXT - 1).history(CHANNEL, START, self.NEXT))

        self.assertEqual(pending.arguments["oldest"], str(START))

    def test_rereads_a_closed_day_when_closed_day_reuse_is_off(self):
        self.filed_day()

        pending = self.pending(lambda: self.closing(closed_days=False).history(CHANNEL, START, self.NEXT))

        self.assertEqual(pending.arguments["oldest"], str(START))

    def test_reuses_the_root_and_replies_of_a_thread_on_a_closed_day(self):
        self.filed(reads.thread_key(CHANNEL, ROOT_TS, None, self.NEXT), reads.to_rows("thread", [THREAD_ROOT, REPLY]))

        self.assertEqual(self.closing().thread(CHANNEL, ROOT_TS, None, self.NEXT), [THREAD_ROOT, REPLY])

    def test_never_reuses_reactions_from_the_day_layer(self):
        self.filed(reads.reactions_key(CHANNEL, ITEM.ts), reads.to_rows("reactions", ["U1"]))

        pending = self.pending(lambda: self.closing().reactions(CHANNEL, ITEM.ts))

        self.assertEqual(pending.tool, REACTIONS_TOOL)

    def test_an_api_source_rereads_a_closed_day_a_connector_filed(self):
        self.filed_day()
        opener = FakeOpener(FakeResponse(json.dumps({"ok": True, "messages": [], "has_more": False}).encode("utf-8")))
        api = reads.ApiReads(self.filing_session("api"), make_client(opener, sleeps=[]), _Calls(5), reads.Freshness(0, self.NEXT, True))

        api.history(CHANNEL, START, self.NEXT)

        self.assertEqual(len(opener.requests), 1)


class MaxAgeTest(unittest.TestCase):
    def test_applies_minutes_to_every_kind(self):
        self.assertEqual([reads.minutes(30, kind) for kind in ("history", "thread", "reactions", "members", "users")], [30] * 5)

    def test_never_reuses_a_search(self):
        self.assertEqual(reads.minutes({"default": 30}, "search"), 0)

    def test_falls_back_to_the_default(self):
        self.assertEqual(reads.minutes({"default": 30, "history": 5}, "thread"), 30)

    def test_takes_zero_without_a_default(self):
        self.assertEqual(reads.minutes({"history": 5}, "thread"), 0)

    def test_maps_members_and_users_to_people(self):
        self.assertEqual([reads.minutes({"people": 90}, kind) for kind in ("members", "users")], [90, 90])

    def test_takes_zero_when_unset(self):
        self.assertEqual(reads.minutes(None, "history"), 0)


class AdapterReuseTest(ReuseCase):
    def test_plans_only_the_gap_for_a_source_with_max_age(self):
        self.store_read(reads.history_key(CHANNEL, START, MID), reads.to_rows("history", [ITEM]))

        step = slack.plan({**one_channel(), "max_age": 60}, WINDOW, STORED, [], self.session(), CONNECTOR)

        self.assertEqual(step["calls"][0]["arguments"], {**HISTORY_ARGUMENTS, "oldest": MID})

    def test_plans_the_whole_span_for_a_source_without_max_age(self):
        self.store_read(reads.history_key(CHANNEL, START, MID), reads.to_rows("history", [ITEM]))

        step = slack.plan(one_channel(), WINDOW, STORED, [], self.session(), CONNECTOR)

        self.assertEqual(step["calls"][0]["arguments"], HISTORY_ARGUMENTS)

    def test_fetches_nothing_for_a_covered_api_source(self):
        self.store_read(reads.history_key(CHANNEL, START, TO), reads.to_rows("history", [ITEM]), transport="api")
        session, opener = self.session("api"), FakeOpener()
        session.http = make_client(opener, sleeps=[])

        result = slack.fetch({**one_channel(), "max_age": 60}, WINDOW, STORED, [], session)

        self.assertEqual(([record["ts"] for record in result["records"]["messages"]], opener.requests), ([ITEM.ts], []))


if __name__ == "__main__":
    unittest.main()
