import collections
import decimal
import json
import re

from . import _common
from ._common import dig
from ._errors import CALL_CAP, CALL_CAP_PARTIAL, PAGE_CAP_PARTIAL, PartialRead, SourceUnreadable
from ._http import PAGE_CAP

HISTORY_PATH = "/api/conversations.history"
REPLIES_PATH = "/api/conversations.replies"
API_PAGE_SIZE = 200
RELAY_PAGE_SIZE = 100
SKIPPED_SUBTYPES = frozenset(("channel_join", "channel_leave"))
FAILED_CHANNEL_CODES = ("channel_not_found", "is_archived", "not_in_channel")
THREAD_NOT_FOUND = "thread_not_found"
TOOL = "slack_read_channel"
THREAD_TOOL = "slack_read_thread"
CURSOR_REPEATED = "cursor repeated"
TS = re.compile(r"[0-9]+\.[0-9]+")
KEY_PART_CAP = 64
ERROR_CODE = re.compile(r"[a-z0-9_]{1,64}")
CHANNEL_FAILURE = re.compile(r"(?<![a-z0-9_])(" + "|".join(FAILED_CHANNEL_CODES) + r")(?![a-z0-9_])")
THREAD_FAILURE = re.compile(r"(?<![a-z0-9_])" + THREAD_NOT_FOUND + r"(?![a-z0-9_])")
LINE_BREAK = re.compile(r"\r\n|\r|\n")
CHANNEL_OPEN = "Channel: "
HEADER_OPEN = "=== Message from "
HEADER_CLOSE = " ==="
HEADER_AT = " at "
MESSAGE_TS = re.compile(r"Message TS: ([0-9]+\.[0-9]+)\s*")
THREAD_MARKER = re.compile(r"Thread: [1-9][0-9]* repl(?:y|ies) \(latest: .+\)")
NEXT_CURSOR = re.compile(r"use cursor: `([^`]+)`")
NO_MORE = "There are no more messages available."
THREAD_NO_MORE = "There are no more messages in this thread."
METADATA_OPEN = ("Reactions: ", "Files: ")
THREAD_PARENT = "=== THREAD PARENT MESSAGE ==="
THREAD_REPLIES = re.compile(r"=== THREAD REPLIES \(([0-9]+) total\) ===")
REPLY_HEADER = re.compile(r"--- Reply [0-9]+ of ([0-9]+) ---")
NO_THREAD = ("No thread messsages", "No thread messages")
FROM_OPEN = "From: "
TIME_OPEN = "Time: "
PARENT_LINES = 4
BOT_MARK = re.compile(r"\s*\[BOT\]\s*$")
EMAIL_TAIL = re.compile(r"\s*<?[^\s<>]+@[^\s<>]+>?$")

Item = collections.namedtuple("Item", "channel ts thread_ts author text name bot", defaults=("", False))
Read = collections.namedtuple("Read", "channel history replies failure lost")


class ChannelFailed(SourceUnreadable):
    def __init__(self, channel, code):
        super().__init__(f"{channel}: {code}")
        self.code = code


class ThreadNotFound(SourceUnreadable):
    def __init__(self, channel, code):
        super().__init__(f"{channel}: {code}")
        self.code = code


class _Pending(Exception):
    def __init__(self, call_id, tool, arguments):
        super().__init__(call_id)
        self.call_id = call_id
        self.tool = tool
        self.arguments = arguments


class _Calls:
    def __init__(self, cap=CALL_CAP):
        self.left = cap

    def spend(self):
        if self.left == 0:
            raise PartialRead(CALL_CAP_PARTIAL)
        self.left -= 1


def _thread_key(channel, root):
    return f"{channel}:{root}"


def _unread_roots(roots, history):
    read = {decimal.Decimal(root) for root in _roots(history)}
    return [root for root in roots if decimal.Decimal(root) not in read]


def _cited_replies(channel, roots, history, read):
    found, lost = [], {}
    for root in _unread_roots(roots, history):
        try:
            found.extend(read(root))
        except (ThreadNotFound, ChannelFailed) as failure:
            lost[_thread_key(channel, root)] = failure.code
    return found, lost


def _api_read(channel, window, stored, http, calls, roots):
    start = _start(window, stored, channel)
    params = {"channel": channel, "oldest": str(start), "latest": str(window["to_ts"]), "limit": str(API_PAGE_SIZE)}
    try:
        history = _in_window(_api_pages(channel, HISTORY_PATH, params, http, calls), start, window)
        replies = [reply for root in _roots(history) for reply in _api_replies(channel, root, window, http, calls, start)]
    except ChannelFailed as failure:
        return Read(channel, [], [], failure.code, {})
    found, lost = _cited_replies(channel, roots, history, lambda root: _api_replies(channel, root, window, http, calls, window["from_ts"]))
    return Read(channel, history, [*replies, *found], None, lost)


def _api_replies(channel, root, window, http, calls, oldest):
    params = {"channel": channel, "ts": root, "oldest": str(oldest), "latest": str(window["to_ts"]), "limit": str(API_PAGE_SIZE)}
    items = _api_pages(channel, REPLIES_PATH, params, http, calls)
    return [item._replace(thread_ts=root) for item in _in_window(items, max(decimal.Decimal(root), decimal.Decimal(oldest)), window)]


def _api_pages(channel, path, params, http, calls):
    found, page = [], params
    for _ in range(PAGE_CAP):
        calls.spend()
        body = http.get(path, page)
        if dig(body, "ok") is not True:
            raise _api_failure(channel, body)
        items = dig(body, "messages")
        if not isinstance(items, list):
            raise SourceUnreadable(f"GET {path}: {channel}: response without messages")
        found.extend(_api_message(channel, path, item) for item in items if dig(item, "subtype") not in SKIPPED_SUBTYPES)
        if dig(body, "has_more") is not True:
            return found
        after = dig(body, "response_metadata", "next_cursor")
        if not isinstance(after, str) or not after:
            raise PartialRead(f"GET {path}: {channel}: has_more without next_cursor")
        page = {**params, "cursor": after}
    raise PartialRead(PAGE_CAP_PARTIAL)


def _api_failure(channel, body):
    code = _error_code(body)
    if code in FAILED_CHANNEL_CODES:
        return ChannelFailed(channel, code)
    return ThreadNotFound(channel, code) if code == THREAD_NOT_FOUND else SourceUnreadable(f"{channel}: {code}")


def _error_code(body):
    error = dig(body, "error")
    return error if isinstance(error, str) and ERROR_CODE.fullmatch(error) else "unknown error"


def _api_message(channel, path, item):
    ts = dig(item, "ts")
    if not isinstance(ts, str) or not TS.fullmatch(ts):
        raise SourceUnreadable(f"GET {path}: {channel}: message without a valid ts")
    root = dig(item, "thread_ts") == ts and _is_count(dig(item, "reply_count"))
    user = _string(dig(item, "user"))
    author = user or _string(dig(item, "bot_id"))
    name = "" if user else _string(dig(item, "username"))
    bot = bool(dig(item, "bot_id")) or dig(item, "subtype") == "bot_message"
    return Item(channel, ts, ts if root else None, author, _string(dig(item, "text")), name, bot)


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


class _Relay:
    def __init__(self, name, responses):
        self.name = name
        self.responses = responses
        self.number = 0

    def read(self, tool, arguments):
        self.number += 1
        call_id = f"{self.name}-{self.number}"
        if call_id not in self.responses:
            raise _Pending(call_id, tool, arguments)
        return call_id, self.responses[call_id]


def _relay_read(relay, channel, window, stored, roots):
    start = _start(window, stored, channel)
    arguments = {"channel_id": channel, "oldest": str(start), "latest": str(window["to_ts"]), "limit": RELAY_PAGE_SIZE, "response_format": "detailed"}
    seen_ts = set()
    try:
        items = _relay_pages(relay, TOOL, arguments, lambda call_id, text: _relay_page(channel, call_id, text, seen_ts, start))
        history = _in_window(items, start, window)
        replies = [reply for root in _roots(history) for reply in _relay_replies(relay, channel, root, window, start)]
    except ChannelFailed as failure:
        return Read(channel, [], [], failure.code, {})
    found, lost = _cited_replies(channel, roots, history, lambda root: _relay_new_replies(relay, channel, root, window))
    return Read(channel, history, [*replies, *found], None, lost)


def _relay_replies(relay, channel, root, window, oldest):
    arguments = {"channel_id": channel, "message_ts": root, "oldest": str(oldest), "response_format": "detailed"}
    seen_ts = set()
    return _relay_pages(relay, THREAD_TOOL, arguments, lambda call_id, text: _thread_page(channel, call_id, text, root, window, seen_ts))


def _relay_new_replies(relay, channel, root, window):
    arguments = {"channel_id": channel, "message_ts": root, "oldest": str(window["from_ts"]), "response_format": "detailed"}
    start, seen_ts = max(decimal.Decimal(root), decimal.Decimal(window["from_ts"])), set()
    items = _relay_pages(relay, THREAD_TOOL, arguments, lambda call_id, text: _newer_page(channel, call_id, text, root, window, seen_ts, start))
    return [item for item in items if decimal.Decimal(item.ts) > start]


def _newer_page(channel, call_id, text, root, window, seen_ts, start):
    replies, after = _thread_page(channel, call_id, text, root, window, seen_ts)
    reached = any(decimal.Decimal(reply.ts) <= start for reply in replies)
    return replies, None if reached else after


def _relay_pages(relay, tool, arguments, parse_page, cap=PAGE_CAP, capped=PAGE_CAP_PARTIAL):
    found, after, seen = [], None, set()
    for _ in range(cap):
        asked = arguments if after is None else {**arguments, "cursor": after}
        call_id, text = relay.read(tool, asked)
        items, after = parse_page(call_id, text)
        found.extend(items)
        if after is None:
            return found
        if after in seen:
            raise PartialRead(CURSOR_REPEATED)
        seen.add(after)
    raise PartialRead(capped)


def _relay_body(tool, call_id, channel, text, page_open):
    try:
        document = json.loads(text)
    except ValueError:
        _raise_failure(channel, [text], page_open)
        raise SourceUnreadable(f"{tool}: response {call_id} is not JSON") from None
    if not isinstance(document, dict):
        raise SourceUnreadable(f"{tool}: response {call_id} is not a JSON object")
    _raise_failure(channel, [document.get("error"), document.get("messages")], page_open)
    messages, info = document.get("messages"), document.get("pagination_info")
    if not isinstance(messages, str) or not isinstance(info, str):
        raise SourceUnreadable(f"{tool}: response {call_id} without messages or pagination_info")
    return messages, info


def _raise_failure(channel, carriers, page_open):
    texts = [carrier for carrier in carriers if isinstance(carrier, str) and not carrier.startswith(page_open)]
    for found in filter(None, (CHANNEL_FAILURE.search(carrier) for carrier in texts)):
        raise ChannelFailed(channel, found.group(1))
    if page_open == THREAD_PARENT and any(THREAD_FAILURE.search(carrier) for carrier in texts):
        raise ThreadNotFound(channel, THREAD_NOT_FOUND)


def _relay_page(channel, call_id, text, seen_ts, oldest):
    messages, info = _relay_body(TOOL, call_id, channel, text, CHANNEL_OPEN)
    return _relay_messages(call_id, channel, LINE_BREAK.split(messages), seen_ts, oldest), _next_cursor(TOOL, call_id, info, (NO_MORE,))


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
    parts = _header_parts(line)
    return None if parts is None else parts[0]


def _header_parts(line):
    header = line.rstrip()
    if not header.startswith(HEADER_OPEN) or not header.endswith(HEADER_CLOSE):
        return None
    who, at, _ = header[len(HEADER_OPEN) : -len(HEADER_CLOSE)].rpartition(HEADER_AT)
    return _who_parts(who) if at else None


def _who_parts(who):
    bot = BOT_MARK.search(who) is not None
    who = BOT_MARK.sub("", who).rstrip()
    author = _parenthesized(who)
    shown = who[: who.rfind("(")] if author else who
    return author, EMAIL_TAIL.sub("", shown.rstrip()).strip(), bot


def _parenthesized(text):
    text = text.rstrip()
    start = text.rfind("(")
    inner = text[start + 1 : -1]
    if start < 0 or not text.endswith(")") or ")" in inner or any(char.isspace() for char in inner):
        return ""
    return inner


def _relay_message(channel, header, ts_line, body):
    kept, root = _without_metadata(body)
    ts = MESSAGE_TS.fullmatch(ts_line).group(1)
    author, name, bot = _header_parts(header)
    return Item(channel, ts, ts if root else None, author, "\n".join(kept), name, bot)


def _without_metadata(body):
    kept, root = list(body), False
    while kept and not kept[-1].strip():
        kept.pop()
    while kept and _is_metadata(kept[-1]):
        root = root or THREAD_MARKER.fullmatch(kept[-1].rstrip()) is not None
        kept.pop()
    return kept, root


def _is_metadata(line):
    return line.startswith(METADATA_OPEN) or THREAD_MARKER.fullmatch(line.rstrip()) is not None


def _thread_page(channel, call_id, text, root, window, seen_ts):
    messages, info = _relay_body(THREAD_TOOL, call_id, channel, text, THREAD_PARENT)
    replies = [] if messages.strip() in NO_THREAD else _thread_replies(call_id, channel, root, LINE_BREAK.split(messages), window, seen_ts)
    return replies, _next_cursor(THREAD_TOOL, call_id, info, (NO_MORE, THREAD_NO_MORE))


def _thread_replies(call_id, channel, root, lines, window, seen_ts):
    if lines[0].rstrip() != THREAD_PARENT:
        raise SourceUnreadable(f"{THREAD_TOOL}: response {call_id} without its parent line")
    stamp = MESSAGE_TS.fullmatch(lines[PARENT_LINES - 1]) if len(lines) >= PARENT_LINES else None
    if not stamp or decimal.Decimal(stamp.group(1)) != decimal.Decimal(root):
        raise SourceUnreadable(f"{THREAD_TOOL}: response {call_id} is not thread {root}")
    marker = _replies_line(lines, root)
    if marker is None and _no_replies_line(lines) is not None:
        return []
    if marker is None:
        raise SourceUnreadable(f"{THREAD_TOOL}: response {call_id} without its replies line")
    first, total = marker
    if [line.strip() for line in lines[first + 1 :] if line.strip()] in [[text] for text in NO_THREAD]:
        return []
    starts = _reply_starts(lines, first + 1, total, root, window, seen_ts)
    if any(line.strip() for line in lines[first + 1 : starts[0][0] if starts else len(lines)]):
        raise SourceUnreadable(f"{THREAD_TOOL}: response {call_id} has text outside a reply")
    ends = [start for start, _ in starts[1:]] + [len(lines)]
    replies = [_thread_reply(channel, root, lines, start, ts, end) for (start, ts), end in zip(starts, ends)]
    return [reply for reply in replies if decimal.Decimal(reply.ts) <= window["to_ts"]]


def _no_replies_line(lines):
    for index in range(len(lines) - 1, PARENT_LINES - 1, -1):
        if lines[index].strip():
            return index if lines[index].strip() in NO_THREAD else None
    return None


def _replies_line(lines, root):
    for index in range(PARENT_LINES, len(lines)):
        found = THREAD_REPLIES.fullmatch(lines[index].rstrip())
        if found and _opens_replies(lines, index + 1, found.group(1), root):
            return index, found.group(1)
    return None


def _opens_replies(lines, index, total, root):
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index == len(lines) or lines[index].strip() in NO_THREAD:
        return True
    return _reply_start(lines, index, total, decimal.Decimal(root), ()) is not None


def _reply_start(lines, index, total, previous, seen_ts):
    if index + 3 >= len(lines):
        return None
    header, stamp = REPLY_HEADER.fullmatch(lines[index].rstrip()), MESSAGE_TS.fullmatch(lines[index + 3])
    if not header or not stamp or header.group(1) != total:
        return None
    if not lines[index + 1].startswith(FROM_OPEN) or not lines[index + 2].startswith(TIME_OPEN):
        return None
    ts = decimal.Decimal(stamp.group(1))
    return stamp.group(1) if previous < ts and ts not in seen_ts else None


def _reply_starts(lines, first, total, root, window, seen_ts):
    starts, previous = [], decimal.Decimal(root)
    for index in range(first, len(lines) - 3):
        stamp = _reply_start(lines, index, total, previous, seen_ts)
        if stamp is None:
            continue
        ts = decimal.Decimal(stamp)
        # Pages come newest first, so the order guard restarts at the root on each page.
        # A reply after the window end still ends the text before it, without moving the guard.
        starts.append((index, stamp))
        seen_ts.add(ts)
        previous = ts if ts <= window["to_ts"] else previous
    return starts


def _thread_reply(channel, root, lines, start, ts, end):
    kept, _ = _without_metadata(lines[start + 4 : end])
    author, name, bot = _who_parts(lines[start + 1][len(FROM_OPEN) :])
    return Item(channel, ts, root, author, "\n".join(kept), name, bot)


def _next_cursor(tool, call_id, info, last_pages):
    more = NEXT_CURSOR.search(info)
    if more:
        return more.group(1)
    if info.strip() in last_pages:
        return None
    raise SourceUnreadable(f"{tool}: response {call_id} has an unreadable pagination_info")


def _in_window(items, start, window):
    return [item for item in items if start < decimal.Decimal(item.ts) <= window["to_ts"]]


def _roots(history):
    return sorted({item.ts for item in history if item.thread_ts is not None}, key=decimal.Decimal)


def _stored_ts(stored, channel):
    ts = stored.get(channel)
    return ts if isinstance(ts, str) and TS.fullmatch(ts) else None


def _start(window, stored, channel):
    ts = _stored_ts(stored, channel)
    return decimal.Decimal(_common.read_start(window, None if ts is None else decimal.Decimal(ts)))


def _string(value):
    return value if isinstance(value, str) else ""
