import email.message
import io
import json
import os
import pathlib
import urllib.parse

import store
from providers import slack

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "slack"
BASE = "https://chat.example.test"
TOKEN_VAR = "CHAT_TOKEN"
TOKEN_VALUE = "-".join(["token", "sentinel"])
PROVIDER = {"adapter": "slack", "api": {"base_url": BASE, "credentials": {"token": TOKEN_VAR}}}
WINDOW = {"from_ts": 1760000000, "to_ts": 1760010800, "first_read_from_ts": 1760000000}
COLLECTED_WINDOW = {"from_ts": 1760000000, "to_ts": 1760010800}
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
CONNECTOR = "chat-connector"
TOOL = "slack_read_channel"
THREAD_TOOL = "slack_read_thread"
ROOT_TS = "1760002000.000200"
NO_MORE = "There are no more messages available."
RUN = "20261020T073004Z-z1x7pc"
FETCHED_AT = "2026-10-20T07:30:09Z"


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


def body(document):
    return FakeResponse(json.dumps(document).encode("utf-8"))


def client(opener, environ=None):
    environ = {TOKEN_VAR: TOKEN_VALUE} if environ is None else environ
    return slack.api_client(PROVIDER, opener=opener, environ=environ, sleep=lambda seconds: None)


def one_channel(channel="CHAN1", **config):
    return {**SOURCE, "channels": [channel], "provider_config": config or PROVIDER}


def query(request):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)


def requests_to(opener, path):
    return [request for request in opener.requests if urllib.parse.urlsplit(request.full_url).path == path]


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


def relay_text(messages, pagination=NO_MORE):
    return json.dumps({"messages": messages, "pagination_info": pagination})


def header(user):
    return f"=== Message from Ada Example ada@example.test ({user}) at 2025-10-09 10:00:00 UTC === "


def relay_message(user, ts, *lines):
    return "\n".join((header(user), f"Message TS: {ts}", *lines))


def relay_page(channel, *blocks, pagination=NO_MORE):
    return relay_text("\n".join((f"Channel: #room ({channel})", "", *blocks)), pagination)


def relay(responses, source=SOURCE, cursor=STORED):
    return slack.parse(source, WINDOW, cursor, [], ordered(responses, source["name"]), {call_id: None for call_id in responses})


def relay_one(*blocks):
    return relay({"team-chat-1": relay_page("CHAN1", *blocks)}, source=one_channel())


def root_item(ts=ROOT_TS, replies=2):
    return {"type": "message", "user": "U1", "text": "Release notes", "ts": ts, "thread_ts": ts, "reply_count": replies}


def reply_item(ts, text="Thanks", user="U2", root=ROOT_TS):
    return {"type": "message", "user": user, "text": text, "ts": ts, "thread_ts": root}


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


def failed(code):
    return {"status": "failed", "reason": code}


class _OrderedHandle:
    def __init__(self, session):
        self.session = session
        self.last_id = None

    def page(self, request, fetch=None):
        self.last_id = self.session.next_id()
        if self.last_id in self.session.responses:
            return self.session.responses[self.last_id]
        raise store.PagePending(self.last_id, None, request)

    def finish(self, status, reason=None, records=None):
        return None


class CallOrderSession:
    def __init__(self, name, responses):
        self.name = name
        self.responses = responses
        self.number = 0

    def next_id(self):
        self.number += 1
        return f"{self.name}-{self.number}"

    def open(self, kind, entity, span=None):
        return _OrderedHandle(self)


class _LiveHandle:
    last_id = None

    def page(self, request, fetch=None):
        return fetch()

    def finish(self, status, reason=None, records=None):
        return None


class LiveSession:
    def __init__(self, http):
        self.http = http

    def open(self, kind, entity, span=None):
        return _LiveHandle()


def ordered(responses, name=SOURCE["name"]):
    return CallOrderSession(name, responses)


def live(http):
    return LiveSession(http)


def store_session(root, transport="mcp", name=SOURCE["name"]):
    return store.ReadSession(root, "chat", RUN, name, "slack", transport, clock=lambda: FETCHED_AT)


def save_planned(session, call, text):
    path = os.path.join(session.base, call["id"] + session.suffix)
    store.make_folders(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(text)


def relay_through(session, responses, source=SOURCE, cursor=STORED, window=WINDOW):
    answers = [responses[call_id] for call_id in sorted(responses, key=lambda call_id: int(call_id.rsplit("-", 1)[1]))]
    planned = []
    while answers:
        step = slack.plan(source, window, cursor, [], session, CONNECTOR)
        if step["done"]:
            break
        planned.append(step["calls"][0]["id"])
        save_planned(session, step["calls"][0], answers.pop(0))
    return planned, slack.parse(source, window, cursor, [], session, {})
