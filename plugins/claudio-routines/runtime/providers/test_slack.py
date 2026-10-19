import collections
import email.message
import io
import json
import pathlib
import unittest
import urllib.error
import urllib.parse

import roles
import state
from providers import _http, slack

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "slack"
BASE = "https://chat.example.test"
TOKEN_VAR = "CHAT_TOKEN"
TOKEN_VALUE = "-".join(["token", "sentinel"])
PROVIDER = {"adapter": "slack", "api": {"base_url": BASE, "credentials": {"token": TOKEN_VAR}}}
WINDOW = {"from_ts": 1760000000, "to_ts": 1760010800, "first_read_from_ts": 1760000000}
COLLECTED_WINDOW = {"from_ts": 1760000000, "to_ts": 1760010800}
WINDOW_END_CURSOR = "1760010800.000000"
LATER_THAN_WINDOW_END = "1760020000.000100"
TRANSPORT = {"cloud": "api", "local": "api"}
SOURCE = {
    "name": "team-chat",
    "provider": "chat",
    "transport": TRANSPORT,
    "channels": ["CHAN1", "CHAN2"],
    "provider_config": PROVIDER,
}
STORED = {"ts": {"CHAN1": "1760000500.000050", "CHAN9": "1759000000.000900"}}
HISTORY_PATH = "/api/conversations.history"
REPLIES_PATH = "/api/conversations.replies"
SHARED_OVER_API = (
    "history_chan1_page_1.json",
    "history_chan1_page_2.json",
    "replies_chan1_page_1.json",
    "replies_chan1_page_2.json",
    "history_chan2.json",
)
SHARED_OVER_RELAY = {
    "team-chat-1": "read_chan1_page_1.json",
    "team-chat-2": "read_chan1_page_2.json",
    "team-chat-3": "thread_chan1_page_1.json",
    "team-chat-4": "thread_chan1_page_2.json",
    "team-chat-5": "read_chan2.json",
}
CONNECTOR = "chat-connector"
TOOL = "slack_read_channel"
THREAD_TOOL = "slack_read_thread"
ROOT_TS = "1760002000.000200"
NO_MORE = "There are no more messages available."
MORE = "There are more messages available. To view the next page, use cursor: `{}`"
THREAD_MORE = "There are more messages in this thread. To view the next page, use cursor: `{}`"
THREAD_NO_MORE = "There are no more messages in this thread."
THREAD_CURSOR = "bmV4dF90czoxNzYwMDAyMzAwLjAwMDIzMA=="


def message(channel, ts, author, text, thread_ts=None):
    return {
        "channel": channel,
        "ts": ts,
        "thread_ts": thread_ts,
        "author": author,
        "text": text,
        "link": f"{BASE}/archives/{channel}/p{ts.replace('.', '')}",
    }


SHARED_MESSAGES = [
    message("CHAN1", "1760001000.000100", "U1", "Morning"),
    message("CHAN1", ROOT_TS, "U1", "Release notes:\n- api 1.2\n- web 3.4", ROOT_TS),
    message("CHAN1", "1760002300.000230", "U2", "Thanks, merging", ROOT_TS),
    message("CHAN1", "1760002600.000260", "U1", "Fixed", ROOT_TS),
    message("CHAN1", "1760003000.000300", "U2", "Deploy done"),
    message("CHAN2", "1760004000.000400", "U1", "=== incident review ===\nall clear"),
    message("CHAN2", "1760004500.000450", "U2", "See thread"),
]
SHARED_CURSOR = {"ts": {"CHAN1": "1760003000.000300", "CHAN2": "1760004500.000450", "CHAN9": "1759000000.000900"}}


class FakeResponse:
    def __init__(self, body):
        self.stream = io.BytesIO(body)
        self.headers = email.message.Message()

    def read(self, size=-1):
        return self.stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeOpener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def fixture(name):
    return (FIXTURES / name).read_bytes()


def ok(name):
    return FakeResponse(fixture(name))


def body(document):
    return FakeResponse(json.dumps(document).encode("utf-8"))


def history(*messages, more=None):
    return body({"ok": True, "messages": list(messages), "has_more": more is not None, "response_metadata": {"next_cursor": more or ""}})


def status(code):
    return urllib.error.HTTPError(BASE, code, "status", email.message.Message(), io.BytesIO(fixture(f"error_{code}.json")))


def client(opener, environ=None):
    environ = {TOKEN_VAR: TOKEN_VALUE} if environ is None else environ
    return slack.api_client(PROVIDER, opener=opener, environ=environ, sleep=lambda seconds: None)


def run(*outcomes, source=SOURCE, cursor=STORED, environ=None, window=WINDOW):
    opener = FakeOpener(outcomes)
    return opener, slack.fetch(source, window, cursor, [], client(opener, environ))


def read_shared():
    return run(*(ok(name) for name in SHARED_OVER_API))


def one_channel(channel="CHAN1", **config):
    return {**SOURCE, "channels": [channel], "provider_config": config or PROVIDER}


def query(request):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)


def requests_to(opener, path):
    return [request for request in opener.requests if urllib.parse.urlsplit(request.full_url).path == path]


def window_from(first_read_from_ts, to_ts=WINDOW["to_ts"]):
    return {"from_ts": WINDOW["from_ts"], "to_ts": to_ts, "first_read_from_ts": first_read_from_ts}


def unreadable(test, *outcomes, error=_http.SourceUnreadable):
    with test.assertRaises(error) as caught:
        run(*outcomes, source=one_channel())
    return caught.exception


def collection(result, transport="api"):
    return {
        "schema": 1,
        "source": SOURCE["name"],
        "role": slack.ROLE,
        "provider": "chat",
        "transport": transport,
        "place": "cloud",
        "window": COLLECTED_WINDOW,
        "read": True,
        "reason": None,
        **result,
    }


def saved(name):
    return fixture(name).decode("utf-8")


def shared_responses():
    return {call_id: saved(name) for call_id, name in SHARED_OVER_RELAY.items()}


def relay_text(messages, pagination=NO_MORE):
    return json.dumps({"messages": messages, "pagination_info": pagination})


def header(user):
    return f"=== Message from Ada Example ada@example.test ({user}) at 2025-10-09 10:00:00 UTC === "


def relay_message(user, ts, *lines):
    return "\n".join((header(user), f"Message TS: {ts}", *lines))


def relay_page(channel, *blocks, pagination=NO_MORE):
    return relay_text("\n".join((f"Channel: #room ({channel})", "", *blocks)), pagination)


def relay_plan(responses, cursor=STORED):
    return slack.plan(SOURCE, WINDOW, cursor, [], responses, CONNECTOR)


def relay(responses, source=SOURCE, cursor=STORED):
    return slack.parse(source, WINDOW, cursor, [], responses, {call_id: None for call_id in responses})


def relay_one(*blocks):
    return relay({"team-chat-1": relay_page("CHAN1", *blocks)}, source=one_channel())


def relay_texts(*blocks):
    return [item["text"] for item in relay_one(*blocks)["records"]["messages"]]


def api_one(*messages):
    _, result = run(history(*messages), source=one_channel())
    return result


def relay_failure(test, response, error=_http.SourceUnreadable):
    with test.assertRaises(error) as caught:
        relay({"team-chat-1": response}, source=one_channel())
    return caught.exception


def endless_pages(channel, count):
    return {f"team-chat-{n}": relay_page(channel, pagination=MORE.format(f"c{n}")) for n in range(1, count + 1)}


def thread_call(call_id, channel, root, cursor=None):
    arguments = {"channel_id": channel, "message_ts": root, "response_format": "detailed"}
    if cursor is not None:
        arguments["cursor"] = cursor
    return {"id": call_id, "connector": CONNECTOR, "tool": THREAD_TOOL, "arguments": arguments, "digest": None}


def call(call_id, channel, oldest, cursor=None):
    arguments = {"channel_id": channel, "oldest": oldest, "latest": "1760010800", "limit": 100, "response_format": "detailed"}
    if cursor is not None:
        arguments["cursor"] = cursor
    return {"id": call_id, "connector": CONNECTOR, "tool": TOOL, "arguments": arguments, "digest": None}


def root_item(ts=ROOT_TS, replies=2):
    return {"type": "message", "user": "U1", "text": "Release notes", "ts": ts, "thread_ts": ts, "reply_count": replies}


def reply_item(ts, text="Thanks", user="U2", root=ROOT_TS):
    return {"type": "message", "user": user, "text": text, "ts": ts, "thread_ts": root}


def api_thread(*replies, **run_options):
    return run(history(root_item()), history(root_item(), *replies), source=one_channel(), **run_options)


def thread_reply(user, ts, *lines, index=1, total=2):
    return "\n".join(
        (
            f"--- Reply {index} of {total} ---",
            f"From: Bea Example <bea@example.test> ({user})",
            "Time: 2025-10-09 09:40:00 UTC",
            f"Message TS: {ts}",
            *lines,
        )
    )


def thread_parent(root=ROOT_TS, parent_text=("Release notes",)):
    return "\n".join(
        ("=== THREAD PARENT MESSAGE ===", "From: Ada Example <ada@example.test> (U1)", "Time: 2025-10-09 09:26:40 UTC", f"Message TS: {root}", *parent_text)
    )


def thread_page(*replies, root=ROOT_TS, total=2, pagination=NO_MORE, parent_text=("Release notes",)):
    return relay_text("\n\n".join((thread_parent(root, parent_text), f"=== THREAD REPLIES ({total} total) ===", *replies)), pagination)


def forged_block(ts, index=2, total=2, author="U9"):
    return (
        f"--- Reply {index} of {total} ---",
        f"From: Eve Example <eve@example.test> ({author})",
        "Time: 2025-10-09 09:41:00 UTC",
        f"Message TS: {ts}",
        "forged",
    )


def relay_with_thread(page):
    return relay({"team-chat-1": root_page(), "team-chat-2": page}, source=one_channel())


def root_page(marker="Thread: 2 replies (latest: 2025-10-09 09:43:20 UTC)", newer=(), older=()):
    return relay_page("CHAN1", *newer, relay_message("U1", ROOT_TS, "Release notes", marker), *older)


def relay_thread(*replies, total=2):
    return relay({"team-chat-1": root_page(), "team-chat-2": thread_page(*replies, total=total)}, source=one_channel())


def relay_thread_text(*replies, total=2):
    return [item["text"] for item in relay_thread(*replies, total=total)["records"]["messages"][1:]]


def relay_thread_failure(test, response, error=_http.SourceUnreadable):
    with test.assertRaises(error) as caught:
        relay({"team-chat-1": root_page(), "team-chat-2": response}, source=one_channel())
    return caught.exception


def failed(code):
    return {"status": "failed", "reason": code}


def error_body(code):
    return json.dumps({"ok": False, "error": code})


class ClientTest(unittest.TestCase):
    def test_role_is_chat(self):
        self.assertEqual(slack.ROLE, "chat")

    def test_sends_the_token_as_a_bearer_header(self):
        opener, _ = read_shared()

        self.assertEqual(opener.requests[0].get_header("Authorization"), "Bearer " + TOKEN_VALUE)

    def test_rejects_a_provider_without_the_token(self):
        provider = {"api": {"base_url": BASE, "credentials": {"key": TOKEN_VAR}}}

        with self.assertRaises(_http.SourceUnreadable) as caught:
            slack.api_client(provider, opener=FakeOpener([]))
        self.assertEqual(str(caught.exception), "api.credentials: must name token")


class FetchTest(unittest.TestCase):
    def test_reads_every_channel_in_message_order(self):
        _, result = read_shared()

        self.assertEqual(result["records"], {"messages": SHARED_MESSAGES})

    def test_cursor_holds_the_newest_ts_per_channel_and_keeps_other_stored_channels(self):
        _, result = read_shared()

        self.assertEqual(result["cursor"], SHARED_CURSOR)

    def test_has_no_entries(self):
        _, result = read_shared()

        self.assertEqual(result["entries"], {})

    def test_calls_the_history_endpoint(self):
        opener, _ = read_shared()

        self.assertEqual(urllib.parse.urlsplit(opener.requests[0].full_url).path, HISTORY_PATH)

    def test_starts_a_channel_after_its_stored_ts(self):
        opener, _ = read_shared()

        self.assertEqual(
            query(opener.requests[0]),
            {"channel": ["CHAN1"], "oldest": ["1760000500.000050"], "latest": ["1760010800"], "limit": ["200"]},
        )

    def test_starts_a_channel_without_stored_ts_at_the_first_read_start(self):
        opener, _ = read_shared()

        self.assertEqual(query(requests_to(opener, HISTORY_PATH)[2])["oldest"], ["1760000000"])

    def test_starts_at_the_first_read_start_when_the_stored_ts_is_older(self):
        opener, _ = run(ok("history_empty.json"), source=one_channel(), cursor={"ts": {"CHAN1": "1759990000.000100"}})

        self.assertEqual(query(opener.requests[0])["oldest"], ["1760000000"])

    def test_starts_at_the_first_read_start_when_the_stored_ts_is_invalid(self):
        opener, _ = run(ok("history_empty.json"), source=one_channel(), cursor={"ts": {"CHAN1": "yesterday"}})

        self.assertEqual(query(opener.requests[0])["oldest"], ["1760000000"])

    def test_keeps_a_message_at_the_window_end(self):
        result = api_one({"type": "message", "user": "U1", "text": "last", "ts": "1760010800.000000"})

        self.assertEqual([item["ts"] for item in result["records"]["messages"]], ["1760010800.000000"])

    def test_drops_a_message_at_the_stored_ts(self):
        result = api_one({"type": "message", "user": "U1", "text": "seen", "ts": "1760000500.000050"})

        self.assertEqual(result["records"]["messages"], [])

    def test_sorts_ts_as_numbers_not_as_text(self):
        newer = {"type": "message", "user": "U1", "text": "newer", "ts": "1000000000.000100"}
        older = {"type": "message", "user": "U1", "text": "older", "ts": "999999999.000100"}

        _, result = run(history(newer, older), source=one_channel(), cursor=None, window={"from_ts": 900000000, "to_ts": 1100000000, "first_read_from_ts": 900000000})

        self.assertEqual([item["text"] for item in result["records"]["messages"]], ["older", "newer"])

    def test_follows_the_next_cursor(self):
        opener, _ = read_shared()

        self.assertEqual(query(opener.requests[1])["cursor"], ["cursor-chan1-2"])

    def test_skips_join_and_leave_messages(self):
        leave = {"type": "message", "subtype": "channel_leave", "user": "U3", "text": "left", "ts": "1760005000.000500"}
        kept = {"type": "message", "user": "U1", "text": "hi", "ts": "1760004000.000400"}

        _, result = run(history(leave, kept), source=one_channel())

        self.assertEqual(result["records"]["messages"], [message("CHAN1", "1760004000.000400", "U1", "hi")])

    def test_author_falls_back_to_the_bot_id(self):
        _, result = run(history({"type": "message", "bot_id": "B1", "text": "backup ok", "ts": "1760004000.000400"}), source=one_channel())

        self.assertEqual(result["records"]["messages"][0]["author"], "B1")

    def test_author_is_empty_without_user_or_bot(self):
        _, result = run(history({"type": "message", "text": "anonymous", "ts": "1760004000.000400"}), source=one_channel())

        self.assertEqual(result["records"]["messages"][0]["author"], "")

    def test_link_uses_the_configured_links_base(self):
        source = one_channel(**PROVIDER, links_base="https://team.example.test/")

        _, result = run(history({"type": "message", "user": "U1", "text": "hi", "ts": "1760004000.000400"}), source=source)

        self.assertEqual(result["records"]["messages"][0]["link"], "https://team.example.test/archives/CHAN1/p1760004000000400")

    def test_channel_without_message_in_the_window_gets_the_window_end_as_cursor(self):
        _, result = run(ok("history_empty.json"), source=one_channel(), cursor={"ts": {"CHAN1": "1760000500.000050"}})

        self.assertEqual(result["cursor"], {"ts": {"CHAN1": WINDOW_END_CURSOR}})

    def test_channel_without_message_keeps_a_stored_ts_later_than_the_window_end(self):
        _, result = run(ok("history_empty.json"), source=one_channel(), cursor={"ts": {"CHAN1": LATER_THAN_WINDOW_END}})

        self.assertEqual(result["cursor"], {"ts": {"CHAN1": LATER_THAN_WINDOW_END}})

    def test_channel_without_stored_cursor_and_without_message_gets_the_window_end_as_cursor(self):
        _, result = run(ok("history_empty.json"), source=one_channel(), cursor=None)

        self.assertEqual(result["cursor"], {"ts": {"CHAN1": WINDOW_END_CURSOR}})

    def test_collection_passes_the_role_schema(self):
        _, result = read_shared()

        self.assertIsNone(roles.validate_collection(collection(result)))


class FetchErrorsTest(unittest.TestCase):
    def test_not_ok_response_names_the_channel_and_the_error_code(self):
        error = unreadable(self, body({"ok": False, "error": "invalid_auth"}))

        self.assertEqual(str(error), "CHAN1: invalid_auth")

    def test_rate_limited_body_with_status_200_is_not_read(self):
        error = unreadable(self, body({"ok": False, "error": "ratelimited"}))

        self.assertEqual(str(error), "CHAN1: ratelimited")

    def test_error_code_outside_the_code_alphabet_is_not_echoed(self):
        error = unreadable(self, body({"ok": False, "error": "<html>secret</html>"}))

        self.assertEqual(str(error), "CHAN1: unknown error")

    def test_response_without_messages_names_the_channel(self):
        error = unreadable(self, body({"ok": True, "has_more": False}))

        self.assertEqual(str(error), f"GET {HISTORY_PATH}: CHAN1: response without messages")

    def test_message_without_a_valid_ts_names_the_channel(self):
        error = unreadable(self, history({"type": "message", "user": "U1", "text": "hi", "ts": "yesterday"}))

        self.assertEqual(str(error), f"GET {HISTORY_PATH}: CHAN1: message without a valid ts")

    def test_has_more_without_next_cursor_makes_the_read_partial(self):
        error = unreadable(self, body({"ok": True, "messages": [], "has_more": True}), error=_http.PartialRead)

        self.assertEqual(str(error), f"partial: GET {HISTORY_PATH}: CHAN1: has_more without next_cursor")

    def test_page_cap_makes_the_read_partial(self):
        error = unreadable(self, *(history(more=f"c{n}") for n in range(_http.PAGE_CAP)), error=_http.PartialRead)

        self.assertEqual(str(error), "partial: page cap")

    def test_page_cap_stops_requests(self):
        opener = FakeOpener([history(more=f"c{n}") for n in range(_http.PAGE_CAP + 1)])

        with self.assertRaises(_http.PartialRead):
            slack.fetch(one_channel(), WINDOW, STORED, [], client(opener))
        self.assertEqual(len(opener.requests), _http.PAGE_CAP)

    def test_http_error_names_the_status_and_the_path(self):
        error = unreadable(self, status(401))

        self.assertEqual(str(error), f"HTTP 401 GET {HISTORY_PATH}")

    def test_missing_token_names_the_variable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            run(source=one_channel(), environ={})
        self.assertEqual(str(caught.exception), f"credentials missing: {TOKEN_VAR}")


class ThreadFetchTest(unittest.TestCase):
    def test_reads_the_replies_of_a_root_up_to_the_window_end(self):
        opener, _ = api_thread(reply_item("1760002300.000230"))

        self.assertEqual(
            query(requests_to(opener, REPLIES_PATH)[0]),
            {"channel": ["CHAN1"], "ts": [ROOT_TS], "latest": ["1760010800"], "limit": ["200"]},
        )

    def test_history_and_replies_reads_are_exclusive_at_both_ends(self):
        opener, _ = api_thread(reply_item("1760002300.000230"))

        self.assertEqual(["inclusive" in query(request) for request in opener.requests], [False, False])

    def test_follows_the_next_cursor_of_a_thread(self):
        opener, _ = read_shared()

        self.assertEqual(query(requests_to(opener, REPLIES_PATH)[1])["cursor"], ["cursor-thread-2"])

    def test_root_carries_its_own_ts(self):
        _, result = api_thread(reply_item("1760002300.000230"))

        self.assertEqual(result["records"]["messages"][0]["thread_ts"], ROOT_TS)

    def test_reply_carries_the_ts_of_its_root(self):
        _, result = api_thread(reply_item("1760002300.000230"))

        self.assertEqual(result["records"]["messages"][1], message("CHAN1", "1760002300.000230", "U2", "Thanks", ROOT_TS))

    def test_reply_shown_in_the_history_and_in_the_thread_gives_one_record_with_the_root_ts(self):
        _, result = read_shared()

        broadcast = [item for item in result["records"]["messages"] if item["ts"] == "1760002600.000260"]
        self.assertEqual(broadcast, [message("CHAN1", "1760002600.000260", "U1", "Fixed", ROOT_TS)])

    def test_thread_copy_wins_over_the_history_copy(self):
        shown = reply_item("1760002300.000230", text="history copy", root="1759000000.000001")
        opener = FakeOpener([history(root_item(), shown), history(root_item(), reply_item("1760002300.000230", text="thread copy"))])

        result = slack.fetch(one_channel(), WINDOW, STORED, [], client(opener))

        self.assertEqual([item["text"] for item in result["records"]["messages"]], ["Release notes", "thread copy"])

    def test_reply_shown_in_the_history_only_carries_null(self):
        shown = reply_item("1760004000.000400", root="1759000000.000001")

        result = api_one(shown)

        self.assertIsNone(result["records"]["messages"][0]["thread_ts"])

    def test_message_without_reply_count_is_not_a_root(self):
        item = {"type": "message", "user": "U1", "text": "alone", "ts": "1760004000.000400", "thread_ts": "1760004000.000400"}

        opener, result = run(history(item), source=one_channel())

        self.assertEqual((len(opener.requests), result["records"]["messages"][0]["thread_ts"]), (1, None))

    def test_message_with_zero_replies_is_not_a_root(self):
        opener, result = run(history(root_item(replies=0)), source=one_channel())

        self.assertEqual((len(opener.requests), result["records"]["messages"][0]["thread_ts"]), (1, None))

    def test_root_older_than_the_window_is_not_expanded(self):
        old = root_item(ts="1759990000.000100")

        opener, result = run(history(old), source=one_channel(), cursor=None)

        self.assertEqual((len(opener.requests), result["records"]["messages"]), (1, []))

    def test_root_at_the_stored_ts_is_not_expanded(self):
        opener, result = run(history(root_item(ts="1760000500.000050")), source=one_channel())

        self.assertEqual((len(opener.requests), result["records"]["messages"]), (1, []))

    def test_reply_after_the_window_end_is_dropped(self):
        _, result = api_thread(reply_item("1760002300.000230"), reply_item("1760010900.000001"))

        self.assertEqual([item["ts"] for item in result["records"]["messages"]], [ROOT_TS, "1760002300.000230"])

    def test_reply_at_the_window_end_is_kept(self):
        _, result = api_thread(reply_item("1760010800.000000"))

        self.assertEqual([item["ts"] for item in result["records"]["messages"]], [ROOT_TS, "1760010800.000000"])

    def test_parent_of_the_thread_read_is_not_read_again(self):
        parent = {**root_item(), "text": "parent copy"}
        opener = FakeOpener([history(root_item()), history(parent, reply_item("1760002300.000230"))])

        result = slack.fetch(one_channel(), WINDOW, STORED, [], client(opener))

        self.assertEqual([item["text"] for item in result["records"]["messages"]], ["Release notes", "Thanks"])

    def test_skips_join_messages_of_a_thread(self):
        join = {"type": "message", "subtype": "channel_join", "user": "U3", "text": "joined", "ts": "1760002400.000240", "thread_ts": ROOT_TS}

        _, result = api_thread(join, reply_item("1760002300.000230"))

        self.assertEqual([item["ts"] for item in result["records"]["messages"]], [ROOT_TS, "1760002300.000230"])

    def test_cursor_holds_the_newest_history_ts_and_ignores_newer_replies(self):
        _, result = api_thread(reply_item("1760005000.000500"))

        self.assertEqual(result["cursor"]["ts"]["CHAN1"], ROOT_TS)

    def test_thread_response_without_messages_names_the_channel_and_the_path(self):
        error = unreadable(self, history(root_item()), body({"ok": True, "has_more": False}))

        self.assertEqual(str(error), f"GET {REPLIES_PATH}: CHAN1: response without messages")

    def test_other_thread_error_fails_the_source(self):
        error = unreadable(self, history(root_item()), body({"ok": False, "error": "thread_not_found"}))

        self.assertEqual(str(error), "CHAN1: thread_not_found")

    def test_thread_page_cap_makes_the_read_partial(self):
        pages = [history(more=f"t{n}") for n in range(_http.PAGE_CAP)]

        error = unreadable(self, history(root_item()), *pages, error=_http.PartialRead)

        self.assertEqual(str(error), "partial: page cap")


class CallCapTest(unittest.TestCase):
    def roots(self, count):
        return [root_item(ts=f"{1760001000 + 100 * n}.000100") for n in range(count)]

    def test_history_pages_and_thread_reads_share_a_budget_of_50_calls(self):
        opener = FakeOpener([history(*self.roots(60)), *(history() for _ in range(60))])

        with self.assertRaises(_http.PartialRead):
            slack.fetch(one_channel(), WINDOW, STORED, [], client(opener))
        self.assertEqual(len(opener.requests), 50)

    def test_reaching_the_budget_makes_the_read_partial(self):
        opener = FakeOpener([history(*self.roots(60)), *(history() for _ in range(60))])

        with self.assertRaises(_http.PartialRead) as caught:
            slack.fetch(one_channel(), WINDOW, STORED, [], client(opener))
        self.assertEqual(str(caught.exception), "partial: call cap")

    def test_exactly_the_budget_is_not_partial(self):
        opener = FakeOpener([history(*self.roots(49)), *(history() for _ in range(49))])

        result = slack.fetch(one_channel(), WINDOW, STORED, [], client(opener))

        self.assertEqual((len(opener.requests), len(result["records"]["messages"])), (50, 49))


class ReadStartTest(unittest.TestCase):
    def test_channel_without_cursor_starts_at_the_first_read_start(self):
        opener, _ = run(ok("history_empty.json"), source=one_channel(), cursor=None, window=window_from(1759000000))

        self.assertEqual(query(opener.requests[0])["oldest"], ["1759000000"])

    def test_message_between_the_first_read_start_and_the_window_start_is_kept(self):
        result = run(history({"type": "message", "user": "U1", "text": "earlier", "ts": "1759500000.000100"}), source=one_channel(), cursor=None, window=window_from(1759000000))[1]

        self.assertEqual([item["ts"] for item in result["records"]["messages"]], ["1759500000.000100"])

    def test_later_stored_ts_wins_over_the_first_read_start(self):
        opener, _ = run(ok("history_empty.json"), source=one_channel(), window=window_from(1759000000))

        self.assertEqual(query(opener.requests[0])["oldest"], ["1760000500.000050"])

    def test_stored_ts_earlier_than_the_first_read_start_is_ignored(self):
        opener, _ = run(ok("history_empty.json"), source=one_channel(), cursor={"ts": {"CHAN1": "1758000000.000001"}}, window=window_from(1759000000))

        self.assertEqual(query(opener.requests[0])["oldest"], ["1759000000"])

    def test_message_at_the_first_read_start_is_not_kept(self):
        result = run(history({"type": "message", "user": "U1", "text": "edge", "ts": "1759000000.000000"}), source=one_channel(), cursor=None, window=window_from(1759000000))[1]

        self.assertEqual(result["records"]["messages"], [])


class FailedChannelTest(unittest.TestCase):
    def test_channel_not_found_is_a_failed_entry(self):
        _, result = run(body({"ok": False, "error": "channel_not_found"}), source=one_channel())

        self.assertEqual(result["entries"], {"CHAN1": failed("channel_not_found")})

    def test_archived_channel_is_a_failed_entry(self):
        _, result = run(body({"ok": False, "error": "is_archived"}), source=one_channel())

        self.assertEqual(result["entries"], {"CHAN1": failed("is_archived")})

    def test_channel_not_joined_is_a_failed_entry(self):
        _, result = run(ok("error_not_in_channel.json"), source=one_channel())

        self.assertEqual(result["entries"], {"CHAN1": failed("not_in_channel")})

    def test_other_channels_are_still_read(self):
        _, result = run(ok("error_not_in_channel.json"), ok("history_chan2.json"))

        self.assertEqual(result["records"]["messages"], SHARED_MESSAGES[5:])

    def test_failed_channel_is_the_only_entry(self):
        _, result = run(ok("error_not_in_channel.json"), ok("history_chan2.json"))

        self.assertEqual(result["entries"], {"CHAN1": failed("not_in_channel")})

    def test_failed_channel_keeps_its_stored_cursor(self):
        _, result = run(ok("error_not_in_channel.json"), ok("history_chan2.json"))

        self.assertEqual(result["cursor"]["ts"], {"CHAN1": "1760000500.000050", "CHAN2": "1760004500.000450", "CHAN9": "1759000000.000900"})

    def test_failed_channel_without_stored_cursor_gets_none(self):
        _, result = run(ok("error_not_in_channel.json"), source=one_channel(), cursor=None)

        self.assertEqual(result["cursor"], {"ts": {}})

    def test_failed_thread_read_makes_the_channel_a_failed_entry(self):
        _, result = run(history(root_item()), body({"ok": False, "error": "is_archived"}), source=one_channel())

        self.assertEqual((result["records"]["messages"], result["entries"]), ([], {"CHAN1": failed("is_archived")}))

    def test_other_error_on_a_later_channel_fails_the_source(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            run(ok("error_not_in_channel.json"), body({"ok": False, "error": "ratelimited"}))
        self.assertEqual(str(caught.exception), "CHAN2: ratelimited")

    def test_collection_with_a_failed_entry_passes_the_role_schema(self):
        _, result = run(ok("error_not_in_channel.json"), ok("history_chan2.json"))

        self.assertIsNone(roles.validate_collection(collection(result)))


class PlanTest(unittest.TestCase):
    def test_first_step_reads_the_first_channel_after_its_stored_ts(self):
        self.assertEqual(relay_plan({})["calls"], [call("team-chat-1", "CHAN1", "1760000500.000050")])

    def test_first_step_is_not_done(self):
        self.assertFalse(relay_plan({})["done"])

    def test_next_page_passes_the_saved_cursor(self):
        responses = {"team-chat-1": saved("read_chan1_page_1.json")}

        self.assertEqual(relay_plan(responses)["calls"], [call("team-chat-2", "CHAN1", "1760000500.000050", "cursor-chan1-2")])

    def test_last_page_of_a_channel_reads_the_thread_of_its_root(self):
        responses = {"team-chat-1": saved("read_chan1_page_1.json"), "team-chat-2": saved("read_chan1_page_2.json")}

        self.assertEqual(relay_plan(responses)["calls"], [thread_call("team-chat-3", "CHAN1", ROOT_TS)])

    def test_next_thread_page_passes_the_saved_cursor(self):
        responses = {name: saved(file) for name, file in list(SHARED_OVER_RELAY.items())[:3]}

        self.assertEqual(relay_plan(responses)["calls"], [thread_call("team-chat-4", "CHAN1", ROOT_TS, THREAD_CURSOR)])

    def test_last_thread_page_moves_to_the_next_channel(self):
        responses = {name: saved(file) for name, file in list(SHARED_OVER_RELAY.items())[:4]}

        self.assertEqual(relay_plan(responses)["calls"], [call("team-chat-5", "CHAN2", "1760000000")])

    def test_channel_without_a_root_moves_to_the_next_channel_after_its_history(self):
        responses = {"team-chat-1": relay_page("CHAN1", relay_message("U1", "1760004000.000400", "plain"))}

        self.assertEqual(relay_plan(responses)["calls"], [call("team-chat-2", "CHAN2", "1760000000")])

    def test_first_read_start_is_the_oldest_of_a_channel_without_stored_ts(self):
        plan = slack.plan(SOURCE, window_from(1759000000), None, [], {}, CONNECTOR)

        self.assertEqual(plan["calls"], [call("team-chat-1", "CHAN1", "1759000000")])

    def test_later_stored_ts_is_the_oldest_of_a_channel(self):
        plan = slack.plan(SOURCE, window_from(1759000000), STORED, [], {}, CONNECTOR)

        self.assertEqual(plan["calls"], [call("team-chat-1", "CHAN1", "1760000500.000050")])

    def test_failed_channel_moves_to_the_next_channel(self):
        responses = {"team-chat-1": json.dumps({"ok": False, "error": "channel_not_found"})}

        self.assertEqual(relay_plan(responses)["calls"], [call("team-chat-2", "CHAN2", "1760000000")])

    def test_last_page_of_the_last_channel_ends_the_plan(self):
        self.assertEqual(relay_plan(shared_responses()), {"done": True, "partial": None, "calls": []})

    def test_unreadable_response_ends_the_plan(self):
        self.assertEqual(relay_plan({"team-chat-1": "Channel not found"}), {"done": True, "partial": None, "calls": []})

    def test_repeated_cursor_ends_the_plan_partial(self):
        responses = {
            "team-chat-1": relay_page("CHAN1", pagination=MORE.format("again")),
            "team-chat-2": relay_page("CHAN1", pagination=MORE.format("again")),
        }

        self.assertEqual(relay_plan(responses), {"done": True, "partial": "cursor repeated", "calls": []})

    def test_page_cap_of_a_channel_ends_the_plan_partial(self):
        self.assertEqual(relay_plan(endless_pages("CHAN1", _http.PAGE_CAP)), {"done": True, "partial": "page cap", "calls": []})


class TransportEqualityTest(unittest.TestCase):
    def test_both_transports_give_the_same_records(self):
        _, over_api = read_shared()

        self.assertEqual(state.dump(relay(shared_responses())["records"]), state.dump(over_api["records"]))

    def test_both_transports_give_the_same_cursor(self):
        _, over_api = read_shared()

        self.assertEqual(state.dump(relay(shared_responses())["cursor"]), state.dump(over_api["cursor"]))

    def test_both_transports_give_the_same_failed_entry_and_cursor(self):
        _, over_api = run(ok("error_not_in_channel.json"), ok("history_chan2.json"))

        responses = {"team-chat-1": error_body("not_in_channel"), "team-chat-2": saved("read_chan2.json")}

        self.assertEqual(state.dump(relay(responses)), state.dump(over_api))

    def test_both_transports_read_a_broadcast_reply_shown_in_the_history_the_same(self):
        shown = reply_item("1760002300.000230", text="history copy")
        opener = FakeOpener([history(root_item(), shown), history(root_item(), reply_item("1760002300.000230", text="thread copy"))])
        over_api = slack.fetch(one_channel(), WINDOW, STORED, [], client(opener))
        shown_in_history = relay_message("U2", "1760002300.000230", "history copy")
        responses = {"team-chat-1": root_page(newer=(shown_in_history, "")), "team-chat-2": thread_page(thread_reply("U2", "1760002300.000230", "thread copy"))}

        self.assertEqual(state.dump(relay(responses, source=one_channel())), state.dump(over_api))


CITED_ROOT = "1759990000.000100"
GONE_ROOT = "1759980000.000100"
OLD_REPLY = "1759995000.000500"
FIRST_REPLY = "1760003000.000300"
SECOND_REPLY = "1760004000.000400"
CITED_MESSAGES = [
    message("CHAN1", FIRST_REPLY, "U2", "Agreed", CITED_ROOT),
    message("CHAN1", SECOND_REPLY, "U1", "Shipped", CITED_ROOT),
]
CITED_CURSOR = {"ts": {"CHAN1": WINDOW_END_CURSOR, "CHAN9": "1759000000.000900"}}
CITED_REPLIES = (
    ("U2", OLD_REPLY, "Earlier"),
    ("U2", FIRST_REPLY, "Agreed"),
    ("U1", SECOND_REPLY, "Shipped"),
    ("U1", LATER_THAN_WINDOW_END, "Next week"),
)


def cited_source(*roots, channel="CHAN1", source=None):
    return {**(source or one_channel()), "threads": [{"channel": channel, "root_ts": root} for root in roots]}


def cited_api_thread(root=CITED_ROOT, replies=CITED_REPLIES, more=None):
    items = [reply_item(ts, text, user, root) for user, ts, text in replies]
    return history(root_item(root, len(items)), *items, more=more)


def cited_relay_thread(root=CITED_ROOT, replies=CITED_REPLIES, pagination=NO_MORE):
    blocks = [thread_reply(user, ts, text, index=number, total=len(replies)) for number, (user, ts, text) in enumerate(replies, 1)]
    return thread_page(*blocks, root=root, total=len(replies), pagination=pagination)


def api_cited(*outcomes, source=None):
    return run(history(), *outcomes, source=source or cited_source(CITED_ROOT))


def relay_cited(*pages, source=None):
    responses = {f"team-chat-{number}": page for number, page in enumerate([relay_page("CHAN1"), *pages], 1)}
    return relay(responses, source=source or cited_source(CITED_ROOT))


class CitedThreadFetchTest(unittest.TestCase):
    def test_reads_only_the_replies_newer_than_the_previous_window_end(self):
        _, result = api_cited(cited_api_thread())

        self.assertEqual(result["records"]["messages"], CITED_MESSAGES)

    def test_asks_for_the_replies_after_the_previous_window_end_exclusively(self):
        opener, _ = api_cited(cited_api_thread())

        self.assertEqual(
            query(requests_to(opener, REPLIES_PATH)[0]),
            {"channel": ["CHAN1"], "ts": [CITED_ROOT], "oldest": ["1760000000"], "latest": ["1760010800"], "limit": ["200"]},
        )

    def test_reads_the_cited_thread_after_the_history_of_its_channel(self):
        opener, _ = api_cited(cited_api_thread())

        self.assertEqual([urllib.parse.urlsplit(request.full_url).path for request in opener.requests], [HISTORY_PATH, REPLIES_PATH])

    def test_follows_the_next_cursor_of_a_cited_thread(self):
        opener, result = api_cited(cited_api_thread(replies=CITED_REPLIES[:2], more="cursor-cited-2"), cited_api_thread(replies=CITED_REPLIES[2:]))

        self.assertEqual((query(requests_to(opener, REPLIES_PATH)[1])["cursor"], result["records"]["messages"]), (["cursor-cited-2"], CITED_MESSAGES))

    def test_reads_a_cited_thread_whose_root_lies_in_the_history_once(self):
        source = cited_source(ROOT_TS)
        opener, result = run(history(root_item()), history(root_item(), reply_item("1760002300.000230")), source=source)

        self.assertEqual((len(requests_to(opener, REPLIES_PATH)), len(result["records"]["messages"])), (1, 2))

    def test_reads_a_thread_cited_twice_once(self):
        opener, _ = api_cited(cited_api_thread(), source=cited_source(CITED_ROOT, CITED_ROOT))

        self.assertEqual(len(requests_to(opener, REPLIES_PATH)), 1)

    def test_replies_of_a_cited_thread_do_not_move_the_cursor(self):
        _, result = run(history(), cited_api_thread(), source=cited_source(CITED_ROOT))

        self.assertEqual(result["cursor"], CITED_CURSOR)

    def test_cited_thread_with_no_new_reply_adds_no_record(self):
        _, result = api_cited(cited_api_thread(replies=CITED_REPLIES[:1]))

        self.assertEqual((result["records"]["messages"], result["entries"]), ([], {}))

    def test_cited_thread_not_found_is_a_failed_entry_keyed_by_channel_and_root(self):
        _, result = api_cited(body({"ok": False, "error": "thread_not_found"}))

        self.assertEqual((result["records"]["messages"], result["entries"]), ([], {f"CHAN1:{CITED_ROOT}": failed("thread_not_found")}))

    def test_deleted_thread_does_not_stop_the_threads_read_after_it(self):
        source = cited_source(GONE_ROOT, CITED_ROOT)

        _, result = api_cited(body({"ok": False, "error": "thread_not_found"}), cited_api_thread(), source=source)

        self.assertEqual((result["records"]["messages"], result["entries"]), (CITED_MESSAGES, {f"CHAN1:{GONE_ROOT}": failed("thread_not_found")}))

    def test_channel_error_on_a_cited_thread_is_a_failed_entry_of_that_thread(self):
        _, result = api_cited(body({"ok": False, "error": "is_archived"}))

        self.assertEqual(result["entries"], {f"CHAN1:{CITED_ROOT}": failed("is_archived")})

    def test_other_error_on_a_cited_thread_fails_the_source(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            api_cited(body({"ok": False, "error": "ratelimited"}))

        self.assertEqual(str(caught.exception), "CHAN1: ratelimited")

    def test_cited_thread_of_a_failed_channel_is_not_read(self):
        opener, result = run(ok("error_not_in_channel.json"), source=cited_source(CITED_ROOT))

        self.assertEqual((len(opener.requests), result["entries"]), (1, {"CHAN1": failed("not_in_channel")}))

    def test_cited_thread_of_a_channel_outside_the_source_is_a_failed_entry_without_a_call(self):
        opener, result = run(history(), source=cited_source(CITED_ROOT, channel="CHAN7"))

        self.assertEqual((len(opener.requests), result["entries"]), (1, {f"CHAN7:{CITED_ROOT}": failed("channel not listed")}))

    def test_cited_thread_with_an_invalid_root_ts_is_a_failed_entry_without_a_call(self):
        opener, result = run(history(), source=cited_source("not-a-ts"))

        self.assertEqual((len(opener.requests), result["entries"]), (1, {"CHAN1:not-a-ts": failed("invalid root ts")}))

    def test_cited_thread_with_a_root_ts_over_the_bounds_is_a_failed_entry_without_a_call(self):
        root = "1" * 17 + ".000100"

        opener, result = run(history(), source=cited_source(root))

        self.assertEqual((len(opener.requests), result["entries"]), (1, {f"CHAN1:{root}": failed("invalid root ts")}))

    def test_invalid_root_ts_is_capped_in_the_entry_key(self):
        _, result = run(history(), source=cited_source("1" * 200 + ".1"))

        self.assertEqual(list(result["entries"]), ["CHAN1:" + "1" * slack.KEY_PART_CAP])

    def test_invalid_root_ts_blanks_control_characters_in_the_entry_key(self):
        _, result = run(history(), source=cited_source("12\n34\x00"))

        self.assertEqual(list(result["entries"]), ["CHAN1:12 34 "])

    def test_channel_outside_the_source_blanks_control_characters_in_the_entry_key(self):
        _, result = run(history(), source=cited_source(CITED_ROOT, channel="CH\nAN7"))

        self.assertEqual(list(result["entries"]), [f"CH AN7:{CITED_ROOT}"])

    def test_collection_with_a_failed_thread_entry_passes_the_role_schema(self):
        _, result = api_cited(body({"ok": False, "error": "thread_not_found"}))

        self.assertIsNone(roles.validate_collection(collection(result)))

    def test_cited_threads_share_the_call_budget_with_the_history(self):
        opener = FakeOpener([history(), *(cited_api_thread() for _ in range(60))])
        source = cited_source(*(f"{1759900000 + 100 * n}.000100" for n in range(60)))

        with self.assertRaises(_http.PartialRead) as caught:
            slack.fetch(source, WINDOW, STORED, [], client(opener))

        self.assertEqual((len(opener.requests), str(caught.exception)), (50, "partial: call cap"))


class CitedThreadRelayTest(unittest.TestCase):
    def test_reads_only_the_replies_newer_than_the_previous_window_end(self):
        result = relay_cited(cited_relay_thread())

        self.assertEqual(result["records"]["messages"], CITED_MESSAGES)

    def test_plan_reads_the_cited_thread_after_its_channel(self):
        step = slack.plan(cited_source(CITED_ROOT), WINDOW, STORED, [], {"team-chat-1": relay_page("CHAN1")}, CONNECTOR)

        self.assertEqual(step, {"done": False, "partial": None, "calls": [thread_call("team-chat-2", "CHAN1", CITED_ROOT)]})

    def test_plan_of_a_complete_read_with_a_cited_thread_is_done(self):
        responses = {"team-chat-1": relay_page("CHAN1"), "team-chat-2": cited_relay_thread()}

        self.assertEqual(slack.plan(cited_source(CITED_ROOT), WINDOW, STORED, [], responses, CONNECTOR), {"done": True, "partial": None, "calls": []})

    def test_plan_asks_the_next_page_while_every_reply_is_newer_than_the_previous_window_end(self):
        newest = cited_relay_thread(replies=CITED_REPLIES[1:3], pagination=THREAD_MORE.format(THREAD_CURSOR))
        responses = {"team-chat-1": relay_page("CHAN1"), "team-chat-2": newest}

        step = slack.plan(cited_source(CITED_ROOT), WINDOW, STORED, [], responses, CONNECTOR)

        self.assertEqual(step["calls"], [thread_call("team-chat-3", "CHAN1", CITED_ROOT, THREAD_CURSOR)])

    def test_stops_at_the_page_that_reaches_the_previous_window_end(self):
        newest = cited_relay_thread(replies=CITED_REPLIES[1:3], pagination=THREAD_MORE.format(THREAD_CURSOR))
        older = cited_relay_thread(replies=CITED_REPLIES[:1], pagination=THREAD_MORE.format("older-cursor"))
        responses = {"team-chat-1": relay_page("CHAN1"), "team-chat-2": newest, "team-chat-3": older}

        step = slack.plan(cited_source(CITED_ROOT), WINDOW, STORED, [], responses, CONNECTOR)

        self.assertEqual((step["done"], relay(responses, source=cited_source(CITED_ROOT))["records"]["messages"]), (True, CITED_MESSAGES))

    def test_thread_not_found_is_a_failed_entry_keyed_by_channel_and_root(self):
        result = relay_cited(error_body("thread_not_found"))

        self.assertEqual((result["records"]["messages"], result["entries"]), ([], {f"CHAN1:{CITED_ROOT}": failed("thread_not_found")}))

    def test_thread_not_found_in_a_text_that_is_not_json_is_a_failed_entry(self):
        result = relay_cited("Error: thread_not_found")

        self.assertEqual(result["entries"], {f"CHAN1:{CITED_ROOT}": failed("thread_not_found")})

    def test_deleted_thread_does_not_stop_the_threads_read_after_it(self):
        result = relay_cited(error_body("thread_not_found"), cited_relay_thread(), source=cited_source(GONE_ROOT, CITED_ROOT))

        self.assertEqual((result["records"]["messages"], result["entries"]), (CITED_MESSAGES, {f"CHAN1:{GONE_ROOT}": failed("thread_not_found")}))

    def test_channel_error_on_a_cited_thread_is_a_failed_entry_of_that_thread(self):
        result = relay_cited(error_body("is_archived"))

        self.assertEqual(result["entries"], {f"CHAN1:{CITED_ROOT}": failed("is_archived")})

    def test_reply_quoting_the_not_found_code_is_a_reply_not_a_failure(self):
        replies = (("U2", FIRST_REPLY, "the api said thread_not_found"),)

        result = relay_cited(cited_relay_thread(replies=replies))

        self.assertEqual((result["records"]["messages"][0]["text"], result["entries"]), ("the api said thread_not_found", {}))

    def test_other_error_code_on_a_cited_thread_fails_the_source(self):
        with self.assertRaises(_http.SourceUnreadable):
            relay_cited(error_body("ratelimited"))

    def test_cited_thread_of_a_failed_channel_is_not_read(self):
        responses = {"team-chat-1": error_body("not_in_channel")}

        step = slack.plan(cited_source(CITED_ROOT), WINDOW, STORED, [], responses, CONNECTOR)

        self.assertEqual((step["done"], relay(responses, source=cited_source(CITED_ROOT))["entries"]), (True, {"CHAN1": failed("not_in_channel")}))

    def test_cited_thread_of_a_channel_outside_the_source_is_a_failed_entry_without_a_call(self):
        responses = {"team-chat-1": relay_page("CHAN1")}
        source = cited_source(CITED_ROOT, channel="CHAN7")

        self.assertEqual((slack.plan(source, WINDOW, STORED, [], responses, CONNECTOR)["done"], relay(responses, source=source)["entries"]), (True, {f"CHAN7:{CITED_ROOT}": failed("channel not listed")}))

    def test_cited_thread_with_an_invalid_root_ts_is_a_failed_entry_without_a_call(self):
        responses = {"team-chat-1": relay_page("CHAN1")}
        source = cited_source("not-a-ts")

        self.assertEqual((slack.plan(source, WINDOW, STORED, [], responses, CONNECTOR)["done"], relay(responses, source=source)["entries"]), (True, {"CHAN1:not-a-ts": failed("invalid root ts")}))

    def test_cited_thread_with_its_root_in_the_history_is_read_once(self):
        responses = {"team-chat-1": root_page(), "team-chat-2": thread_page(thread_reply("U2", "1760002300.000230", "Thanks"))}

        step = slack.plan(cited_source(ROOT_TS), WINDOW, STORED, [], responses, CONNECTOR)

        self.assertEqual(step["done"], True)


class CitedThreadTransportEqualityTest(unittest.TestCase):
    def test_both_transports_give_the_same_records_cursor_and_entries(self):
        _, over_api = api_cited(cited_api_thread())

        self.assertEqual(state.dump(relay_cited(cited_relay_thread())), state.dump(over_api))

    def test_both_transports_give_a_deleted_thread_next_to_a_read_one_the_same(self):
        source = cited_source(GONE_ROOT, CITED_ROOT)
        _, over_api = api_cited(body({"ok": False, "error": "thread_not_found"}), cited_api_thread(), source=source)

        over_relay = relay_cited(error_body("thread_not_found"), cited_relay_thread(), source=source)

        self.assertEqual(state.dump(over_relay), state.dump(over_api))

    def test_both_transports_give_several_thread_pages_the_same_with_the_early_stop(self):
        newest = (CITED_REPLIES[2],)
        oldest = CITED_REPLIES[:2]
        _, over_api = api_cited(cited_api_thread(replies=CITED_REPLIES[1:2], more="cursor-cited-2"), cited_api_thread(replies=newest))
        responses = {
            "team-chat-1": relay_page("CHAN1"),
            "team-chat-2": cited_relay_thread(replies=newest, pagination=THREAD_MORE.format(THREAD_CURSOR)),
            "team-chat-3": cited_relay_thread(replies=oldest, pagination=THREAD_MORE.format("older-cursor")),
        }

        self.assertEqual(state.dump(relay(responses, source=cited_source(CITED_ROOT))), state.dump(over_api))
        self.assertEqual(slack.plan(cited_source(CITED_ROOT), WINDOW, STORED, [], responses, CONNECTOR)["done"], True)

    def test_both_transports_give_the_cited_cursor(self):
        _, over_api = api_cited(cited_api_thread())

        self.assertEqual((over_api["cursor"], relay_cited(cited_relay_thread())["cursor"]), (CITED_CURSOR, CITED_CURSOR))


class CleanTextEqualityTest(unittest.TestCase):
    def test_both_transports_clean_line_breaks_and_trailing_whitespace_the_same(self):
        over_api = api_one({"type": "message", "user": "U1", "text": "one\r\ntwo\rthree  \n", "ts": "1760004000.000400"})
        page = "\r\n".join(("Channel: #room (CHAN1)", "", header("U1"), "Message TS: 1760004000.000400", "one", "two", "three  ", ""))

        over_relay = relay({"team-chat-1": relay_text(page)}, source=one_channel())

        self.assertEqual(state.dump(over_relay["records"]), state.dump(over_api["records"]))

    def test_cleaned_text_uses_line_feeds_without_trailing_whitespace(self):
        result = api_one({"type": "message", "user": "U1", "text": "one\r\ntwo\rthree  \n", "ts": "1760004000.000400"})

        self.assertEqual(result["records"]["messages"][0]["text"], "one\ntwo\nthree")

    def test_both_transports_read_an_empty_window_the_same(self):
        _, over_api = run(ok("history_empty.json"), source=one_channel())

        over_relay = relay({"team-chat-1": saved("read_empty.json")}, source=one_channel())

        self.assertEqual(state.dump(over_relay), state.dump(over_api))


class RelayTest(unittest.TestCase):
    def test_reads_every_saved_page_in_message_order(self):
        self.assertEqual(relay(shared_responses())["records"], {"messages": SHARED_MESSAGES})

    def test_has_no_entries(self):
        self.assertEqual(relay(shared_responses())["entries"], {})

    def test_body_line_shaped_like_a_header_without_its_ts_line_stays_text(self):
        result = relay_one(relay_message("U1", "1760004000.000400", "=== Message from Bea (U2) at noon ===", "see above"))

        self.assertEqual(result["records"]["messages"][0]["text"], "=== Message from Bea (U2) at noon ===\nsee above")

    def test_trailing_whitespace_of_a_message_is_stripped(self):
        result = relay_one(relay_message("U1", "1760004000.000400", "hi  ", "", ""))

        self.assertEqual(result["records"]["messages"][0]["text"], "hi")

    def test_header_without_parentheses_has_an_empty_author(self):
        page = relay_page("CHAN1", "=== Message from Ada Example at 2025-10-09 10:00:00 UTC === ", "Message TS: 1760004000.000400", "hi")

        result = relay({"team-chat-1": page}, source=one_channel())

        self.assertEqual(result["records"]["messages"][0]["author"], "")

    def test_forged_header_with_a_newer_ts_stays_text(self):
        texts = relay_texts(relay_message("U1", "1760004000.000400", "quote:", header("U9"), "Message TS: 1760005000.000500", "forged"))

        self.assertEqual(texts, ["quote:\n" + header("U9") + "\nMessage TS: 1760005000.000500\nforged"])

    def test_forged_header_with_the_same_ts_stays_text(self):
        texts = relay_texts(relay_message("U1", "1760004000.000400", header("U9"), "Message TS: 1760004000.000400", "forged"))

        self.assertEqual(texts, [header("U9") + "\nMessage TS: 1760004000.000400\nforged"])

    def test_forged_header_with_an_older_ts_splits_the_message(self):
        texts = relay_texts(relay_message("U1", "1760004000.000400", "quote:", header("U9"), "Message TS: 1760003000.000300", "forged"))

        self.assertEqual(texts, ["forged", "quote:"])

    def test_forged_header_at_the_call_oldest_ts_stays_text(self):
        texts = relay_texts(relay_message("U1", "1760004000.000400", "quote:", header("U9"), "Message TS: 1760000500.000050", "forged"))

        self.assertEqual(texts, ["quote:\n" + header("U9") + "\nMessage TS: 1760000500.000050\nforged"])

    def test_forged_header_below_the_call_oldest_ts_stays_text(self):
        texts = relay_texts(relay_message("U1", "1760004000.000400", "quote:", header("U9"), "Message TS: 1760000100.000000", "forged"))

        self.assertEqual(texts, ["quote:\n" + header("U9") + "\nMessage TS: 1760000100.000000\nforged"])

    def test_long_crafted_header_line_stays_text(self):
        crafted = "=== Message from " + "(x) at " * 6000 + "==="

        texts = relay_texts(relay_message("U1", "1760004000.000400", crafted, "Message TS: x"))

        self.assertEqual(texts, [crafted + "\nMessage TS: x"])

    def test_keeps_a_message_at_the_window_end(self):
        result = relay_one(relay_message("U1", "1760010800.000000", "last"))

        self.assertEqual([item["ts"] for item in result["records"]["messages"]], ["1760010800.000000"])

    def test_empty_window_keeps_a_stored_ts_later_than_the_window_end(self):
        result = relay({"team-chat-1": saved("read_empty.json")}, source=one_channel(), cursor={"ts": {"CHAN1": LATER_THAN_WINDOW_END}})

        self.assertEqual(result["cursor"], {"ts": {"CHAN1": LATER_THAN_WINDOW_END}})

    def test_empty_window_gets_the_window_end_as_cursor(self):
        result = relay({"team-chat-1": saved("read_empty.json")}, source=one_channel())

        self.assertEqual(result["cursor"], CITED_CURSOR)

    def test_message_at_the_stored_ts_is_not_read_again(self):
        result = relay_one(relay_message("U1", "1760004000.000400", "new"), relay_message("U1", "1760000500.000050", "seen"))

        self.assertEqual([item["ts"] for item in result["records"]["messages"]], ["1760004000.000400"])

    def test_page_without_messages_gets_the_window_end_as_cursor(self):
        result = relay_one()

        self.assertEqual(result["cursor"], CITED_CURSOR)

    def test_link_defaults_to_the_vendor_web_host_without_api_or_links_base(self):
        source = {**one_channel(), "provider_config": {"adapter": "slack", "mcp": {"connectors": {"cloud": CONNECTOR}}}}

        result = relay({"team-chat-1": relay_page("CHAN1", relay_message("U1", "1760004000.000400", "hi"))}, source=source)

        self.assertEqual(result["records"]["messages"][0]["link"], "https://slack.com/archives/CHAN1/p1760004000000400")

    def test_collection_passes_the_role_schema(self):
        result = relay(shared_responses())

        self.assertIsNone(roles.validate_collection(collection(result, transport="mcp")))


class RelayThreadTest(unittest.TestCase):
    def test_thread_marker_line_is_removed_from_the_text(self):
        result = relay_thread(thread_reply("U2", "1760002300.000230", "Thanks"))

        self.assertEqual(result["records"]["messages"][0]["text"], "Release notes")

    def test_marker_of_a_single_reply_is_removed_from_the_text(self):
        responses = {"team-chat-1": root_page("Thread: 1 reply (latest: 2025-10-09 09:43:20 UTC)"), "team-chat-2": thread_page(thread_reply("U2", "1760002300.000230", "Thanks"))}

        result = relay(responses, source=one_channel())

        self.assertEqual(result["records"]["messages"][0]["text"], "Release notes")

    def test_marker_followed_by_blank_lines_and_another_message_is_removed(self):
        older = relay_message("U1", "1760001000.000100", "older")
        responses = {"team-chat-1": root_page(older=("", older)), "team-chat-2": thread_page(thread_reply("U2", "1760002300.000230", "Thanks"))}

        result = relay(responses, source=one_channel())

        self.assertEqual([item["text"] for item in result["records"]["messages"]], ["older", "Release notes", "Thanks"])

    def test_root_carries_its_own_ts(self):
        result = relay_thread(thread_reply("U2", "1760002300.000230", "Thanks"))

        self.assertEqual(result["records"]["messages"][0]["thread_ts"], ROOT_TS)

    def test_reply_carries_the_ts_of_its_root(self):
        result = relay_thread(thread_reply("U2", "1760002300.000230", "Thanks"))

        self.assertEqual(result["records"]["messages"][1], message("CHAN1", "1760002300.000230", "U2", "Thanks", ROOT_TS))

    def test_marker_in_the_middle_of_the_body_stays_text_and_is_no_root(self):
        result = relay_one(relay_message("U1", "1760004000.000400", "Thread: 2 replies", "more"))

        self.assertEqual(result["records"]["messages"], [message("CHAN1", "1760004000.000400", "U1", "Thread: 2 replies\nmore")])

    def test_marker_without_its_latest_part_stays_text_and_is_no_root(self):
        result = relay_one(relay_message("U1", "1760004000.000400", "hi", "Thread: 2 replies"))

        self.assertEqual(result["records"]["messages"], [message("CHAN1", "1760004000.000400", "U1", "hi\nThread: 2 replies")])

    def test_marker_with_trailing_words_instead_of_its_latest_part_stays_text_and_is_no_root(self):
        result = relay_one(relay_message("U1", "1760004000.000400", "hi", "Thread: 2 replies, see below"))

        self.assertEqual(result["records"]["messages"][0]["thread_ts"], None)

    def test_root_after_the_window_end_is_not_expanded(self):
        result = relay_one(relay_message("U1", "1760011000.000100", "late root", "Thread: 2 replies (latest: 2025-10-09 12:00:00 UTC)"))

        self.assertEqual(result["records"]["messages"], [])

    def test_marker_with_zero_replies_stays_text_and_is_no_root(self):
        result = relay_one(relay_message("U1", "1760004000.000400", "Thread: 0 replies"))

        self.assertEqual(result["records"]["messages"], [message("CHAN1", "1760004000.000400", "U1", "Thread: 0 replies")])

    def test_reactions_and_files_lines_at_the_end_are_removed_from_the_text(self):
        result = relay_one(relay_message("U1", "1760004000.000400", "hi", "Reactions: :+1: 2", "Files: notes.txt"))

        self.assertEqual(result["records"]["messages"], [message("CHAN1", "1760004000.000400", "U1", "hi")])

    def test_metadata_run_in_any_order_removes_every_line_and_finds_the_root(self):
        marker = "Files: notes.txt\nThread: 2 replies (latest: 2025-10-09 09:43:20 UTC)\nReactions: :+1: 2"
        responses = {"team-chat-1": root_page(marker), "team-chat-2": thread_page(thread_reply("U2", "1760002300.000230", "Thanks"))}

        result = relay(responses, source=one_channel())

        self.assertEqual(result["records"]["messages"][0], message("CHAN1", ROOT_TS, "U1", "Release notes", ROOT_TS))

    def test_reactions_after_the_thread_line_do_not_hide_the_root(self):
        marker = "Thread: 2 replies (latest: 2025-10-09 09:43:20 UTC)\nReactions: :+1: 2"
        responses = {"team-chat-1": root_page(marker), "team-chat-2": thread_page(thread_reply("U2", "1760002300.000230", "Thanks"))}

        result = relay(responses, source=one_channel())

        self.assertEqual(result["records"]["messages"][0]["thread_ts"], ROOT_TS)

    def test_reactions_line_before_the_end_of_the_body_stays_text(self):
        result = relay_one(relay_message("U1", "1760004000.000400", "hi", "Reactions: :+1: 2", "more"))

        self.assertEqual(result["records"]["messages"][0]["text"], "hi\nReactions: :+1: 2\nmore")

    def test_metadata_lines_at_the_end_of_a_reply_are_removed_from_its_text(self):
        reply = thread_reply("U2", "1760002300.000230", "Thanks", "Reactions: :+1: 1", "Files: patch.diff")

        self.assertEqual(relay_thread_text(reply), ["Thanks"])

    def test_reply_shown_in_the_history_and_in_the_thread_gives_one_record_with_the_root_ts(self):
        shown = relay_message("U2", "1760002300.000230", "history copy")
        responses = {"team-chat-1": root_page(newer=(shown, "")), "team-chat-2": thread_page(thread_reply("U2", "1760002300.000230", "thread copy"))}

        result = relay(responses, source=one_channel())

        self.assertEqual(
            result["records"]["messages"][1:], [message("CHAN1", "1760002300.000230", "U2", "thread copy", ROOT_TS)]
        )

    def test_reply_shown_in_the_history_only_carries_null(self):
        result = relay_one(relay_message("U2", "1760004000.000400", "broadcast"))

        self.assertIsNone(result["records"]["messages"][0]["thread_ts"])

    def test_names_and_emails_are_dropped_from_the_author(self):
        result = relay_thread(thread_reply("U2", "1760002300.000230", "Thanks"))

        self.assertEqual(result["records"]["messages"][1]["author"], "U2")

    def test_reply_keeps_its_lines_and_drops_trailing_blank_lines(self):
        texts = relay_thread_text(thread_reply("U2", "1760002300.000230", "one", "two", "", ""))

        self.assertEqual(texts, ["one\ntwo"])

    def test_replies_are_read_in_ts_order(self):
        first = thread_reply("U2", "1760002300.000230", "first")
        second = thread_reply("U1", "1760002400.000240", "second", index=2)

        self.assertEqual(relay_thread_text(first, second), ["first", "second"])

    def test_thread_without_replies_adds_no_record(self):
        responses = {"team-chat-1": root_page(), "team-chat-2": relay_text("No thread messsages")}

        result = relay(responses, source=one_channel())

        self.assertEqual([item["ts"] for item in result["records"]["messages"]], [ROOT_TS])

    def test_reply_after_the_window_end_is_dropped_and_not_added_to_the_text_before_it(self):
        inside = thread_reply("U2", "1760002300.000230", "inside")
        late = thread_reply("U1", "1760010900.000001", "late", index=2)

        result = relay_thread(inside, late)

        self.assertEqual([item["text"] for item in result["records"]["messages"]], ["Release notes", "inside"])

    def test_reply_at_the_window_end_is_kept(self):
        result = relay_thread(thread_reply("U2", "1760010800.000000", "last"))

        self.assertEqual([item["ts"] for item in result["records"]["messages"]], [ROOT_TS, "1760010800.000000"])

    def test_reply_not_later_than_its_root_does_not_open_the_replies_and_names_the_tool(self):
        error = relay_thread_failure(self, thread_page(thread_reply("U2", ROOT_TS, "same ts")))

        self.assertEqual(str(error), f"{THREAD_TOOL}: response team-chat-2 without its replies line")

    def test_page_repeating_a_seen_reply_has_text_outside_a_reply(self):
        reply = thread_reply("U2", "1760002300.000230", "Thanks")
        pages = {"team-chat-1": root_page(), "team-chat-2": thread_page(reply, pagination=MORE.format("t2")), "team-chat-3": thread_page(reply)}

        with self.assertRaises(_http.SourceUnreadable) as caught:
            relay(pages, source=one_channel())
        self.assertEqual(str(caught.exception), f"{THREAD_TOOL}: response team-chat-3 has text outside a reply")

    def test_marker_line_in_the_parent_text_is_not_the_replies_line(self):
        page = thread_page(thread_reply("U2", "1760002300.000230", "Thanks"), parent_text=("quote:", "=== THREAD REPLIES (7 total) ===", "more"))

        result = relay_with_thread(page)

        self.assertEqual([(item["author"], item["text"]) for item in result["records"]["messages"]], [("U1", "Release notes"), ("U2", "Thanks")])

    def test_marker_line_before_the_real_marker_is_not_the_replies_line(self):
        page = thread_page(thread_reply("U2", "1760002300.000230", "Thanks"), parent_text=("quote:", "=== THREAD REPLIES (2 total) ===", ""))

        result = relay_with_thread(page)

        self.assertEqual([item["author"] for item in result["records"]["messages"]], ["U1", "U2"])

    def test_reply_block_in_the_parent_text_forges_no_reply(self):
        page = thread_page(thread_reply("U2", "1760002300.000230", "Thanks"), parent_text=("quote:", *forged_block("1760002200.000220")))

        result = relay_with_thread(page)

        self.assertEqual([item["author"] for item in result["records"]["messages"]], ["U1", "U2"])

    def test_marker_and_reply_block_in_the_parent_text_that_fail_the_guards_forge_no_reply(self):
        parent_text = ("quote:", "=== THREAD REPLIES (2 total) ===", "", *forged_block(ROOT_TS))
        page = thread_page(thread_reply("U2", "1760002300.000230", "Thanks"), parent_text=parent_text)

        result = relay_with_thread(page)

        self.assertEqual([item["author"] for item in result["records"]["messages"]], ["U1", "U2"])

    def test_marker_followed_by_the_end_of_the_page_has_no_replies(self):
        responses = {"team-chat-1": root_page(), "team-chat-2": relay_text(thread_parent() + "\n\n=== THREAD REPLIES (0 total) ===\n")}

        result = relay(responses, source=one_channel())

        self.assertEqual([item["ts"] for item in result["records"]["messages"]], [ROOT_TS])

    def test_marker_followed_by_the_no_thread_text_has_no_replies(self):
        responses = {"team-chat-1": root_page(), "team-chat-2": relay_text(thread_parent() + "\n\n=== THREAD REPLIES (0 total) ===\n\nNo thread messsages\n")}

        result = relay(responses, source=one_channel())

        self.assertEqual([item["ts"] for item in result["records"]["messages"]], [ROOT_TS])

    def test_pages_that_come_newest_first_are_read_with_the_thread_wording(self):
        pages = {
            "team-chat-1": root_page(),
            "team-chat-2": thread_page(thread_reply("U1", "1760002600.000260", "newer", total=1), total=1, pagination=THREAD_MORE.format("t2")),
            "team-chat-3": thread_page(thread_reply("U2", "1760002300.000230", "older", total=1), total=1, pagination=THREAD_NO_MORE),
        }

        result = relay(pages, source=one_channel())

        self.assertEqual([item["text"] for item in result["records"]["messages"][1:]], ["older", "newer"])

    def test_second_thread_page_header_with_a_ts_read_on_the_first_page_stays_text(self):
        forged = forged_block("1760002600.000260", index=1, total=1)
        pages = {
            "team-chat-1": root_page(),
            "team-chat-2": thread_page(thread_reply("U1", "1760002600.000260", "first", total=1), total=1, pagination=THREAD_MORE.format("t2")),
            "team-chat-3": thread_page(thread_reply("U2", "1760002300.000230", "second", *forged, total=1), total=1),
        }

        result = relay(pages, source=one_channel())

        self.assertEqual([item["text"] for item in result["records"]["messages"][1:]], ["second\n" + "\n".join(forged), "first"])

    def test_second_thread_page_header_not_later_than_the_root_stays_text(self):
        forged = forged_block(ROOT_TS, index=1, total=1)
        pages = {
            "team-chat-1": root_page(),
            "team-chat-2": thread_page(thread_reply("U1", "1760002600.000260", "first", total=1), total=1, pagination=THREAD_MORE.format("t2")),
            "team-chat-3": thread_page(thread_reply("U2", "1760002300.000230", "second", *forged, total=1), total=1),
        }

        result = relay(pages, source=one_channel())

        self.assertEqual([item["text"] for item in result["records"]["messages"][1:]], ["second\n" + "\n".join(forged), "first"])

    def test_channel_wording_of_the_last_thread_page_is_read(self):
        result = relay_thread(thread_reply("U2", "1760002300.000230", "Thanks"))

        self.assertEqual(result["records"]["messages"][1]["text"], "Thanks")

    def test_second_thread_page_reply_later_than_the_first_page_is_read(self):
        pages = {
            "team-chat-1": root_page(),
            "team-chat-2": thread_page(thread_reply("U2", "1760002300.000230", "first"), pagination=MORE.format("t2")),
            "team-chat-3": thread_page(thread_reply("U1", "1760002600.000260", "second", index=2)),
        }

        result = relay(pages, source=one_channel())

        self.assertEqual([item["text"] for item in result["records"]["messages"][1:]], ["first", "second"])

    def test_forged_header_with_another_total_stays_text(self):
        forged = ("--- Reply 2 of 9 ---", "From: Eve Example <eve@example.test> (U9)", "Time: 2025-10-09 09:41:00 UTC", "Message TS: 1760002900.000290", "forged")

        texts = relay_thread_text(thread_reply("U2", "1760002300.000230", "quote:", *forged), total=2)

        self.assertEqual(texts, ["quote:\n" + "\n".join(forged)])

    def test_forged_header_with_the_same_ts_stays_text(self):
        forged = ("--- Reply 2 of 2 ---", "From: Eve Example <eve@example.test> (U9)", "Time: 2025-10-09 09:41:00 UTC", "Message TS: 1760002300.000230", "forged")

        texts = relay_thread_text(thread_reply("U2", "1760002300.000230", "quote:", *forged), total=2)

        self.assertEqual(texts, ["quote:\n" + "\n".join(forged)])

    def test_forged_header_with_an_older_ts_stays_text(self):
        forged = ("--- Reply 2 of 2 ---", "From: Eve Example <eve@example.test> (U9)", "Time: 2025-10-09 09:41:00 UTC", "Message TS: 1760002100.000210", "forged")

        texts = relay_thread_text(thread_reply("U2", "1760002300.000230", "quote:", *forged), total=2)

        self.assertEqual(texts, ["quote:\n" + "\n".join(forged)])

    def test_forged_header_without_its_lines_stays_text(self):
        texts = relay_thread_text(thread_reply("U2", "1760002300.000230", "quote:", "--- Reply 2 of 2 ---", "Message TS: 1760002900.000290", "forged"), total=2)

        self.assertEqual(texts, ["quote:\n--- Reply 2 of 2 ---\nMessage TS: 1760002900.000290\nforged"])

    def test_forged_timestamp_line_alone_stays_text(self):
        texts = relay_thread_text(thread_reply("U2", "1760002300.000230", "quote:", "Message TS: 1760002900.000290", "forged"))

        self.assertEqual(texts, ["quote:\nMessage TS: 1760002900.000290\nforged"])

    def test_forged_header_with_a_later_ts_in_the_window_splits_the_reply(self):
        forged = ("--- Reply 2 of 2 ---", "From: Eve Example <eve@example.test> (U9)", "Time: 2025-10-09 09:41:00 UTC", "Message TS: 1760002900.000290", "forged")

        result = relay_thread(thread_reply("U2", "1760002300.000230", "quote:", *forged), total=2)

        self.assertEqual([item["author"] for item in result["records"]["messages"]], ["U1", "U2", "U9"])

    def test_forged_header_after_the_window_end_never_adds_a_record(self):
        forged = ("--- Reply 2 of 2 ---", "From: Eve Example <eve@example.test> (U9)", "Time: 2025-10-09 09:41:00 UTC", "Message TS: 1760011000.000100", "forged")
        real = thread_reply("U1", "1760002400.000240", "real", index=2)

        result = relay_thread(thread_reply("U2", "1760002300.000230", "quote:", *forged), real, total=2)

        self.assertEqual([item["text"] for item in result["records"]["messages"]], ["Release notes", "quote:", "real"])

    def test_thread_text_of_another_root_names_the_tool(self):
        error = relay_thread_failure(self, thread_page(thread_reply("U2", "1760002300.000230", "Thanks"), root="1760001000.000100"))

        self.assertEqual(str(error), f"{THREAD_TOOL}: response team-chat-2 is not thread {ROOT_TS}")

    def test_thread_text_without_its_parent_line_names_the_tool(self):
        error = relay_thread_failure(self, relay_text("Something went wrong."))

        self.assertEqual(str(error), f"{THREAD_TOOL}: response team-chat-2 without its parent line")

    def test_thread_text_without_its_replies_line_names_the_tool(self):
        error = relay_thread_failure(self, relay_text(thread_parent()))

        self.assertEqual(str(error), f"{THREAD_TOOL}: response team-chat-2 without its replies line")

    def test_thread_response_that_is_not_json_names_the_thread_tool(self):
        error = relay_thread_failure(self, "Thread not found")

        self.assertEqual(str(error), f"{THREAD_TOOL}: response team-chat-2 is not JSON")

    def test_thread_response_without_pagination_info_names_the_thread_tool(self):
        error = relay_thread_failure(self, json.dumps({"messages": thread_parent()}))

        self.assertEqual(str(error), f"{THREAD_TOOL}: response team-chat-2 without messages or pagination_info")

    def test_unknown_thread_pagination_info_names_the_thread_tool(self):
        error = relay_thread_failure(self, thread_page(pagination="Maybe more later."))

        self.assertEqual(str(error), f"{THREAD_TOOL}: response team-chat-2 has an unreadable pagination_info")

    def test_page_cap_of_a_thread_makes_the_read_partial(self):
        pages = {f"team-chat-{n}": thread_page(pagination=MORE.format(f"t{n}")) for n in range(2, _http.PAGE_CAP + 2)}

        with self.assertRaises(_http.PartialRead) as caught:
            relay({"team-chat-1": root_page(), **pages}, source=one_channel())
        self.assertEqual(str(caught.exception), "partial: page cap")

    def test_repeated_thread_cursor_makes_the_read_partial(self):
        pages = {"team-chat-2": thread_page(pagination=MORE.format("again")), "team-chat-3": thread_page(pagination=MORE.format("again"))}

        with self.assertRaises(_http.PartialRead) as caught:
            relay({"team-chat-1": root_page(), **pages}, source=one_channel())
        self.assertEqual(str(caught.exception), "partial: cursor repeated")

    def test_plan_reads_the_thread_of_a_root_with_the_message_ts(self):
        plan = slack.plan(one_channel(), WINDOW, STORED, [], {"team-chat-1": root_page()}, CONNECTOR)

        self.assertEqual(plan["calls"], [thread_call("team-chat-2", "CHAN1", ROOT_TS)])

    def test_plan_of_a_complete_read_with_threads_is_done(self):
        self.assertEqual(relay_plan(shared_responses()), {"done": True, "partial": None, "calls": []})


class RelayFailedChannelTest(unittest.TestCase):
    def failed_read(self, response, source=one_channel()):
        return relay({"team-chat-1": response}, source=source)

    def test_error_code_in_a_text_that_is_not_json_is_a_failed_entry(self):
        result = self.failed_read("Error: channel_not_found")

        self.assertEqual(result["entries"], {"CHAN1": failed("channel_not_found")})

    def test_error_field_of_a_json_object_is_a_failed_entry(self):
        result = self.failed_read(error_body("is_archived"))

        self.assertEqual(result["entries"], {"CHAN1": failed("is_archived")})

    def test_messages_text_without_a_channel_line_is_a_failed_entry(self):
        result = self.failed_read(relay_text("Error: not_in_channel"))

        self.assertEqual(result["entries"], {"CHAN1": failed("not_in_channel")})

    def test_message_text_quoting_a_code_is_a_message_not_a_failure(self):
        result = relay_one(relay_message("U1", "1760004000.000400", "the api returned not_in_channel"))

        self.assertEqual((result["records"]["messages"][0]["text"], result["entries"]), ("the api returned not_in_channel", {}))

    def test_code_inside_a_longer_word_is_not_a_failure(self):
        with self.assertRaises(_http.SourceUnreadable):
            self.failed_read("Error: no_is_archived_here")

    def test_human_wording_without_a_code_fails_the_source(self):
        with self.assertRaises(_http.SourceUnreadable):
            self.failed_read("Channel not found")

    def test_other_error_code_fails_the_source(self):
        with self.assertRaises(_http.SourceUnreadable):
            self.failed_read(error_body("ratelimited"))

    def test_failed_channel_keeps_its_stored_cursor_and_the_others_are_read(self):
        responses = {"team-chat-1": error_body("channel_not_found"), "team-chat-2": saved("read_chan2.json")}

        result = relay(responses)

        self.assertEqual(result["cursor"]["ts"], {"CHAN1": "1760000500.000050", "CHAN2": "1760004500.000450", "CHAN9": "1759000000.000900"})

    def test_other_channels_are_still_read(self):
        responses = {"team-chat-1": error_body("channel_not_found"), "team-chat-2": saved("read_chan2.json")}

        result = relay(responses)

        self.assertEqual((result["records"]["messages"], result["entries"]), (SHARED_MESSAGES[5:], {"CHAN1": failed("channel_not_found")}))

    def test_failed_thread_read_makes_the_channel_a_failed_entry(self):
        responses = {"team-chat-1": root_page(), "team-chat-2": error_body("is_archived")}

        result = relay(responses, source=one_channel())

        self.assertEqual((result["records"]["messages"], result["entries"]), ([], {"CHAN1": failed("is_archived")}))

    def test_collection_with_a_failed_entry_passes_the_role_schema(self):
        responses = {"team-chat-1": error_body("channel_not_found"), "team-chat-2": saved("read_chan2.json")}

        self.assertIsNone(roles.validate_collection(collection(relay(responses), transport="mcp")))


class RelayFailureTest(unittest.TestCase):
    def test_response_that_is_not_json_names_the_tool(self):
        error = relay_failure(self, "Channel not found")

        self.assertEqual(str(error), f"{TOOL}: response team-chat-1 is not JSON")

    def test_response_that_is_not_an_object_names_the_tool(self):
        error = relay_failure(self, "[]")

        self.assertEqual(str(error), f"{TOOL}: response team-chat-1 is not a JSON object")

    def test_response_without_pagination_info_names_the_tool(self):
        error = relay_failure(self, json.dumps({"messages": "Channel: #room (CHAN1)"}))

        self.assertEqual(str(error), f"{TOOL}: response team-chat-1 without messages or pagination_info")

    def test_unknown_pagination_info_names_the_tool(self):
        error = relay_failure(self, relay_page("CHAN1", pagination="Maybe more later."))

        self.assertEqual(str(error), f"{TOOL}: response team-chat-1 has an unreadable pagination_info")

    def test_text_without_its_channel_line_names_the_tool(self):
        error = relay_failure(self, relay_text("Something went wrong."))

        self.assertEqual(str(error), f"{TOOL}: response team-chat-1 without its Channel line")

    def test_text_of_another_channel_names_the_tool(self):
        error = relay_failure(self, relay_page("CHAN2"))

        self.assertEqual(str(error), f"{TOOL}: response team-chat-1 is not channel CHAN1")

    def test_text_outside_a_message_names_the_tool(self):
        error = relay_failure(self, relay_page("CHAN1", "Something went wrong."))

        self.assertEqual(str(error), f"{TOOL}: response team-chat-1 has text outside a message")

    def test_missing_history_response_names_the_tool(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            relay({})
        self.assertEqual(str(caught.exception), f"{TOOL}: no response team-chat-1")

    def test_missing_thread_response_names_the_thread_tool(self):
        responses = {"team-chat-1": saved("read_chan1_page_1.json"), "team-chat-2": saved("read_chan1_page_2.json")}

        with self.assertRaises(_http.SourceUnreadable) as caught:
            relay(responses)
        self.assertEqual(str(caught.exception), f"{THREAD_TOOL}: no response team-chat-3")

    def test_page_cap_of_a_channel_makes_the_read_partial(self):
        with self.assertRaises(_http.PartialRead) as caught:
            relay(endless_pages("CHAN1", _http.PAGE_CAP))
        self.assertEqual(str(caught.exception), "partial: page cap")

    def test_repeated_cursor_makes_the_read_partial(self):
        responses = {
            "team-chat-1": relay_page("CHAN1", pagination=MORE.format("again")),
            "team-chat-2": relay_page("CHAN1", pagination=MORE.format("again")),
        }

        with self.assertRaises(_http.PartialRead) as caught:
            relay(responses)
        self.assertEqual(str(caught.exception), "partial: cursor repeated")


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
        step = slack.plan(source, SEARCH_WINDOW, {}, [], responses, CONNECTOR)
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
    return slack.parse(source, SEARCH_WINDOW, {}, [], responses, {})


def unit_message(user, name, ts, text, root=None, bot=False, **extra):
    return {"user": user, "name": name, "bot": bot, "ts": ts, "root_ts": root, "text": text, **extra}


def full_responses():
    return {
        "team-chat-1": saved("search_page_1.json"),
        "team-chat-2": saved("search_page_2.json"),
        "team-chat-3": conversation_page("D000001", (OWNER, "1792398000.000200", "On it"), (BOT, "1792397053.514349", "multi\nline text")),
        "team-chat-4": thread_page(thread_reply(PEER, "1792398500.000100", "Can you review?", index=1, total=1), root=THREAD_ROOT, total=1),
    }


class SearchRelayPlanTest(unittest.TestCase):
    def first_call(self, search=DMS, **options):
        return slack.plan(search_source(search, **options), SEARCH_WINDOW, {}, [], {}, CONNECTOR)["calls"][0]

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
        step = slack.plan(search_source(), SEARCH_WINDOW, {}, [], {"team-chat-1": saved("search_page_1.json")}, CONNECTOR)

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
    return opener, slack.fetch(source or search_source(**options), window, {}, [], client(opener))


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


if __name__ == "__main__":
    unittest.main()
