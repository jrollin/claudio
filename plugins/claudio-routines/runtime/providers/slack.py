import decimal
import re
import urllib.parse

from . import _common
from ._common import dig, json_object
from ._http import PAGE_CAP
from ._errors import PAGE_CAP_PARTIAL, PartialRead, SourceUnreadable

ROLE = "chat"
CREDENTIAL = "token"
HISTORY_PATH = "/api/conversations.history"
API_PAGE_SIZE = 200
RELAY_PAGE_SIZE = 100
SKIPPED_SUBTYPES = frozenset(("channel_join", "channel_leave"))
LINKS_BASE = "https://slack.com"
TOOL = "slack_read_channel"
CURSOR_REPEATED = "cursor repeated"
TS = re.compile(r"[0-9]+\.[0-9]+")
ERROR_CODE = re.compile(r"[a-z0-9_]{1,64}")
LINE_BREAK = re.compile(r"\r\n|\r|\n")
CHANNEL_OPEN = "Channel: "
HEADER_OPEN = "=== Message from "
HEADER_CLOSE = " ==="
HEADER_AT = " at "
MESSAGE_TS = re.compile(r"Message TS: ([0-9]+\.[0-9]+)\s*")
NEXT_CURSOR = re.compile(r"use cursor: `([^`]+)`")
NO_MORE = "There are no more messages available."


def api_client(provider, opener=None, environ=None, sleep=None):
    return _common.api_client(provider, (CREDENTIAL,), _auth, opener, environ, sleep)


def _auth(values):
    return {"Authorization": "Bearer " + values[CREDENTIAL]}


def fetch(source, window, cursor, entries, http):
    stored = _stored(cursor)
    found = []
    for channel in source["channels"]:
        found.extend(_read_channel(channel, _oldest(stored, channel, window), window, http))
    return _result(source, window, stored, found)


def plan(source, window, cursor, entries, responses, connector):
    stored = _stored(cursor)
    try:
        _, pending, partial = _walk(source, window, stored, responses)
    except SourceUnreadable:
        return _common.ended(None)
    if pending is None:
        return _common.ended(partial)
    call_id, channel, after = pending
    arguments = {
        "channel_id": channel,
        "oldest": _oldest(stored, channel, window),
        "latest": str(window["to_ts"]),
        "limit": RELAY_PAGE_SIZE,
        "response_format": "detailed",
    }
    if after is not None:
        arguments["cursor"] = after
    call = {"id": call_id, "connector": connector, "tool": TOOL, "arguments": arguments, "digest": None}
    return {"done": False, "partial": None, "calls": [call]}


def parse(source, window, cursor, entries, responses, digests):
    stored = _stored(cursor)
    found, pending, partial = _walk(source, window, stored, responses)
    if partial is not None:
        raise PartialRead(partial)
    if pending is not None:
        raise SourceUnreadable(f"{TOOL}: no response {pending[0]}")
    return _result(source, window, stored, found)


def _read_channel(channel, oldest, window, http):
    params = {"channel": channel, "oldest": oldest, "latest": str(window["to_ts"]), "inclusive": "true", "limit": str(API_PAGE_SIZE)}
    found, page = [], params
    for _ in range(PAGE_CAP):
        body = http.get(HISTORY_PATH, page)
        if dig(body, "ok") is not True:
            raise SourceUnreadable(f"{channel}: {_error_code(body)}")
        items = dig(body, "messages")
        if not isinstance(items, list):
            raise SourceUnreadable(f"GET {HISTORY_PATH}: {channel}: response without messages")
        found.extend(_api_message(channel, item) for item in items if dig(item, "subtype") not in SKIPPED_SUBTYPES)
        if dig(body, "has_more") is not True:
            return found
        after = dig(body, "response_metadata", "next_cursor")
        if not isinstance(after, str) or not after:
            raise PartialRead(f"GET {HISTORY_PATH}: {channel}: has_more without next_cursor")
        page = {**params, "cursor": after}
    raise PartialRead(PAGE_CAP_PARTIAL)


def _error_code(body):
    error = dig(body, "error")
    return error if isinstance(error, str) and ERROR_CODE.fullmatch(error) else "unknown error"


def _api_message(channel, item):
    ts = dig(item, "ts")
    if not isinstance(ts, str) or not TS.fullmatch(ts):
        raise SourceUnreadable(f"GET {HISTORY_PATH}: {channel}: message without a valid ts")
    return channel, ts, _string(dig(item, "user")) or _string(dig(item, "bot_id")), _string(dig(item, "text"))


def _walk(source, window, stored, responses):
    found, number = [], 1
    for channel in source["channels"]:
        after, seen, seen_ts = None, set(), set()
        oldest = decimal.Decimal(_oldest(stored, channel, window))
        for page in range(1, PAGE_CAP + 1):
            call_id = f"{source['name']}-{number}"
            if call_id not in responses:
                return found, (call_id, channel, after), None
            messages, after = _relay_page(call_id, channel, responses[call_id], seen_ts, oldest)
            found.extend(messages)
            number += 1
            if after is None:
                break
            if after in seen:
                return found, None, CURSOR_REPEATED
            if page == PAGE_CAP:
                return found, None, PAGE_CAP_PARTIAL
            seen.add(after)
    return found, None, None


def _relay_page(call_id, channel, text, seen_ts, oldest):
    body = json_object(text, f"{TOOL}: response {call_id} is not JSON", f"{TOOL}: response {call_id} is not a JSON object")
    messages, info = body.get("messages"), body.get("pagination_info")
    if not isinstance(messages, str) or not isinstance(info, str):
        raise SourceUnreadable(f"{TOOL}: response {call_id} without messages or pagination_info")
    return _relay_messages(call_id, channel, LINE_BREAK.split(messages), seen_ts, oldest), _next_cursor(call_id, info)


def _relay_messages(call_id, channel, lines, seen_ts, oldest):
    shown = _parenthesized(lines[0][len(CHANNEL_OPEN) :]) if lines[0].startswith(CHANNEL_OPEN) else ""
    if not shown:
        raise SourceUnreadable(f"{TOOL}: response {call_id} without its Channel line")
    if shown != channel:
        raise SourceUnreadable(f"{TOOL}: response {call_id} is not channel {channel}")
    starts = _message_starts(lines, seen_ts, oldest)
    if any(line.strip() for line in lines[1 : starts[0] if starts else len(lines)]):
        raise SourceUnreadable(f"{TOOL}: response {call_id} has text outside a message")
    ends = starts[1:] + [len(lines)]
    return [_relay_message(channel, lines[start], lines[start + 1], lines[start + 2 : end]) for start, end in zip(starts, ends)]


def _message_starts(lines, seen_ts, oldest):
    starts, previous = [], None
    for index in range(1, len(lines) - 1):
        stamp = MESSAGE_TS.fullmatch(lines[index + 1])
        if _header_author(lines[index]) is None or not stamp:
            continue
        ts = decimal.Decimal(stamp.group(1))
        # A forged header with a ts between oldest and the message's own ts still splits it (README).
        if oldest < ts and ts not in seen_ts and (previous is None or ts < previous):
            starts.append(index)
            seen_ts.add(ts)
            previous = ts
    return starts


def _header_author(line):
    header = line.rstrip()
    if not header.startswith(HEADER_OPEN) or not header.endswith(HEADER_CLOSE):
        return None
    who, at, _ = header[len(HEADER_OPEN) : -len(HEADER_CLOSE)].rpartition(HEADER_AT)
    return _parenthesized(who) if at else None


def _parenthesized(text):
    text = text.rstrip()
    start = text.rfind("(")
    inner = text[start + 1 : -1]
    if start < 0 or not text.endswith(")") or ")" in inner or any(char.isspace() for char in inner):
        return ""
    return inner


def _relay_message(channel, header, ts_line, body):
    return channel, MESSAGE_TS.fullmatch(ts_line).group(1), _header_author(header), "\n".join(body)


def _next_cursor(call_id, info):
    more = NEXT_CURSOR.search(info)
    if more:
        return more.group(1)
    if info.strip() == NO_MORE:
        return None
    raise SourceUnreadable(f"{TOOL}: response {call_id} has an unreadable pagination_info")


def _result(source, window, stored, found):
    base = _links_base(source)
    kept = (item for item in found if _in_window(item, stored, window))
    records = sorted((_record(base, *item) for item in kept), key=_order)
    newest = {record["channel"]: record["ts"] for record in records}
    return {"records": {"messages": records}, "cursor": {"ts": {**stored, **newest}}, "entries": {}}


def _in_window(item, stored, window):
    channel, ts = item[0], item[1]
    return decimal.Decimal(_oldest(stored, channel, window)) < decimal.Decimal(ts) <= window["to_ts"]


def _record(base, channel, ts, author, text):
    link = f"{base}/archives/{urllib.parse.quote(channel, safe='')}/p{ts.replace('.', '')}"
    return {"channel": channel, "ts": ts, "author": author, "text": LINE_BREAK.sub("\n", text).rstrip(), "link": link}


def _order(record):
    return record["channel"], decimal.Decimal(record["ts"])


def _links_base(source):
    config = source.get("provider_config") or {}
    return (config.get("links_base") or dig(config, "api", "base_url") or LINKS_BASE).rstrip("/")


def _stored(cursor):
    stored = dig(cursor, "ts")
    return {channel: ts for channel, ts in stored.items() if isinstance(ts, str)} if isinstance(stored, dict) else {}


def _oldest(stored, channel, window):
    ts = stored.get(channel)
    if isinstance(ts, str) and TS.fullmatch(ts) and decimal.Decimal(ts) > window["from_ts"]:
        return ts
    return str(window["from_ts"])


def _string(value):
    return value if isinstance(value, str) else ""
