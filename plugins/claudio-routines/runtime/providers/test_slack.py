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
WINDOW = {"from_ts": 1760000000, "to_ts": 1760010800}
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
SHARED_OVER_API = ("history_chan1_page_1.json", "history_chan1_page_2.json", "history_chan2.json")
SHARED_OVER_RELAY = {"team-chat-1": "read_chan1_page_1.json", "team-chat-2": "read_chan1_page_2.json", "team-chat-3": "read_chan2.json"}
CONNECTOR = "chat-connector"
TOOL = "slack_read_channel"
NO_MORE = "There are no more messages available."
MORE = "There are more messages available. To view the next page, use cursor: `{}`"


def message(channel, ts, author, text):
    return {
        "channel": channel,
        "ts": ts,
        "author": author,
        "text": text,
        "link": f"{BASE}/archives/{channel}/p{ts.replace('.', '')}",
    }


SHARED_MESSAGES = [
    message("CHAN1", "1760001000.000100", "U1", "Morning"),
    message("CHAN1", "1760002000.000200", "U1", "Release notes:\n- api 1.2\n- web 3.4"),
    message("CHAN1", "1760003000.000300", "U2", "Deploy done"),
    message("CHAN2", "1760004000.000400", "U1", "=== incident review ===\nall clear"),
]
SHARED_CURSOR = {"ts": {"CHAN1": "1760003000.000300", "CHAN2": "1760004000.000400", "CHAN9": "1759000000.000900"}}


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
        "window": WINDOW,
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


def call(call_id, channel, oldest, cursor=None):
    arguments = {"channel_id": channel, "oldest": oldest, "latest": "1760010800", "limit": 100, "response_format": "detailed"}
    if cursor is not None:
        arguments["cursor"] = cursor
    return {"id": call_id, "connector": CONNECTOR, "tool": TOOL, "arguments": arguments, "digest": None}


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
            {"channel": ["CHAN1"], "oldest": ["1760000500.000050"], "latest": ["1760010800"], "inclusive": ["true"], "limit": ["200"]},
        )

    def test_starts_a_channel_without_stored_ts_at_the_window_start(self):
        opener, _ = read_shared()

        self.assertEqual(query(opener.requests[2])["oldest"], ["1760000000"])

    def test_starts_at_the_window_start_when_the_stored_ts_is_older(self):
        opener, _ = run(ok("history_empty.json"), source=one_channel(), cursor={"ts": {"CHAN1": "1759990000.000100"}})

        self.assertEqual(query(opener.requests[0])["oldest"], ["1760000000"])

    def test_starts_at_the_window_start_when_the_stored_ts_is_invalid(self):
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

        _, result = run(history(newer, older), source=one_channel(), cursor=None, window={"from_ts": 900000000, "to_ts": 1100000000})

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

    def test_channel_without_new_messages_keeps_its_stored_ts(self):
        _, result = run(ok("history_empty.json"), source=one_channel(), cursor={"ts": {"CHAN1": "1760000500.000050"}})

        self.assertEqual(result["cursor"], {"ts": {"CHAN1": "1760000500.000050"}})

    def test_null_stored_cursor_reads_from_the_window_start(self):
        _, result = run(ok("history_empty.json"), source=one_channel(), cursor=None)

        self.assertEqual(result["cursor"], {"ts": {}})

    def test_collection_passes_the_role_schema(self):
        _, result = read_shared()

        self.assertIsNone(roles.validate_collection(collection(result)))


class FetchErrorsTest(unittest.TestCase):
    def test_not_ok_response_names_the_channel_and_the_error_code(self):
        error = unreadable(self, ok("error_not_in_channel.json"))

        self.assertEqual(str(error), "CHAN1: not_in_channel")

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


class PlanTest(unittest.TestCase):
    def test_first_step_reads_the_first_channel_after_its_stored_ts(self):
        self.assertEqual(relay_plan({})["calls"], [call("team-chat-1", "CHAN1", "1760000500.000050")])

    def test_first_step_is_not_done(self):
        self.assertFalse(relay_plan({})["done"])

    def test_next_page_passes_the_saved_cursor(self):
        responses = {"team-chat-1": saved("read_chan1_page_1.json")}

        self.assertEqual(relay_plan(responses)["calls"], [call("team-chat-2", "CHAN1", "1760000500.000050", "cursor-chan1-2")])

    def test_last_page_of_a_channel_moves_to_the_next_channel(self):
        responses = {"team-chat-1": saved("read_chan1_page_1.json"), "team-chat-2": saved("read_chan1_page_2.json")}

        self.assertEqual(relay_plan(responses)["calls"], [call("team-chat-3", "CHAN2", "1760000000")])

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

    def test_empty_window_keeps_the_stored_ts(self):
        result = relay({"team-chat-1": saved("read_empty.json")}, source=one_channel())

        self.assertEqual(result["cursor"], STORED)

    def test_message_at_the_stored_ts_is_not_read_again(self):
        result = relay_one(relay_message("U1", "1760004000.000400", "new"), relay_message("U1", "1760000500.000050", "seen"))

        self.assertEqual([item["ts"] for item in result["records"]["messages"]], ["1760004000.000400"])

    def test_page_without_messages_keeps_the_stored_ts(self):
        result = relay_one()

        self.assertEqual(result["cursor"], {"ts": {"CHAN1": "1760000500.000050", "CHAN9": "1759000000.000900"}})

    def test_link_defaults_to_the_vendor_web_host_without_api_or_links_base(self):
        source = {**one_channel(), "provider_config": {"adapter": "slack", "mcp": {"connectors": {"cloud": CONNECTOR}}}}

        result = relay({"team-chat-1": relay_page("CHAN1", relay_message("U1", "1760004000.000400", "hi"))}, source=source)

        self.assertEqual(result["records"]["messages"][0]["link"], "https://slack.com/archives/CHAN1/p1760004000000400")

    def test_collection_passes_the_role_schema(self):
        result = relay(shared_responses())

        self.assertIsNone(roles.validate_collection(collection(result, transport="mcp")))


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

    def test_missing_response_names_the_tool(self):
        responses = {"team-chat-1": saved("read_chan1_page_1.json"), "team-chat-2": saved("read_chan1_page_2.json")}

        with self.assertRaises(_http.SourceUnreadable) as caught:
            relay(responses)
        self.assertEqual(str(caught.exception), f"{TOOL}: no response team-chat-3")

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


if __name__ == "__main__":
    unittest.main()
