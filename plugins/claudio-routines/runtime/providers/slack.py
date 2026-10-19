import collections
import datetime
import decimal
import json
import re
import urllib.parse

from state import clean_text

from . import _common
from ._common import dig
from ._http import PAGE_CAP
from ._errors import CALL_CAP, CALL_CAP_PARTIAL, PAGE_CAP_PARTIAL, PartialRead, SourceUnreadable

ROLE = "chat"
CREDENTIAL = "token"
HISTORY_PATH = "/api/conversations.history"
REPLIES_PATH = "/api/conversations.replies"
API_PAGE_SIZE = 200
RELAY_PAGE_SIZE = 100
SKIPPED_SUBTYPES = frozenset(("channel_join", "channel_leave"))
FAILED_CHANNEL_CODES = ("channel_not_found", "is_archived", "not_in_channel")
THREAD_NOT_FOUND = "thread_not_found"
NOT_LISTED = "channel not listed"
INVALID_ROOT = "invalid root ts"
LINKS_BASE = "https://slack.com"
TOOL = "slack_read_channel"
THREAD_TOOL = "slack_read_thread"
SEARCH_TOOL = "slack_search_public_and_private"
REACTIONS_TOOL = "slack_get_reactions"
SEARCH_PATH = "/api/search.messages"
REACTIONS_PATH = "/api/reactions.get"
USERS_PATH = "/api/users.info"
INFO_PATH = "/api/conversations.info"
MEMBERS_PATH = "/api/conversations.members"
SEARCH_CUT = "search cut"
NO_REACTIONS = "No reactions found on this message."
REACTIONS_OPEN = "Reactions on message:"
NAME_SEPARATOR = " \u2014 "
SEARCH_PAGE_SIZE = 20
SEARCH_PAGE_CAP = 10
REACTIONS_PER_UNIT = 3
TEXT_CAP = 300
DAY_SECONDS = 86400
DM = "DM"
GROUP_DM = "group DM"
CONVERSATION_TYPES = frozenset(("im", "mpim"))
CURSOR_REPEATED = "cursor repeated"
TS = re.compile(r"[0-9]+\.[0-9]+")
ROOT_TS = re.compile(r"[0-9]{1,16}\.[0-9]{1,9}")
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
RESULT_HEADER = re.compile(r"### Result ([0-9]+) of ([0-9]+)")
RESULTS_COUNT = re.compile(r"## Messages \(([0-9]+) results?\)")
SEARCH_CHANNEL = re.compile(r"(.+) \(ID: ([A-Z0-9]+)\)")
SEARCH_FROM = re.compile(r"(.*?)\s*\(ID: ([A-Z0-9]+)\)\s*(\[BOT\])?\s*")
SEARCH_PARTICIPANT = re.compile(r"([^,()]+?) \(ID: ([A-Z0-9]+)\)")
SEARCH_CURSOR = re.compile(r"cursor:?\s*`([^`]+)`", re.IGNORECASE)
PERMALINK_THREAD = re.compile(r"[?&]thread_ts=([0-9]+\.[0-9]+)")
REACTION_USER = re.compile(r"\(([UW][A-Z0-9]+)\)(?=,|$)")
CHANNEL_ID = re.compile(r"[A-Z0-9]+")
USER_ID = re.compile(r"[UW][A-Z0-9]+")
SEARCH_BLOCK_END = "---"

Item = collections.namedtuple("Item", "channel ts thread_ts author text name bot", defaults=("", False))
Read = collections.namedtuple("Read", "channel history replies failure lost")
Hit = collections.namedtuple("Hit", "channel name kind participants root item kind_type", defaults=(None,))


class ChannelFailed(SourceUnreadable):
    def __init__(self, channel, code):
        super().__init__(f"{channel}: {code}")
        self.code = code


class ThreadNotFound(SourceUnreadable):
    def __init__(self, channel, code):
        super().__init__(f"{channel}: {code}")
        self.code = code


class ReactionsFailed(SourceUnreadable):
    def __init__(self, code):
        super().__init__(f"reactions: {code}")
        self.code = code


class _Pending(Exception):
    def __init__(self, call_id, tool, arguments):
        super().__init__(call_id)
        self.call_id = call_id
        self.tool = tool
        self.arguments = arguments


def api_client(provider, opener=None, environ=None, sleep=None):
    return _common.api_client(provider, (CREDENTIAL,), _auth, opener, environ, sleep)


def _auth(values):
    return {"Authorization": "Bearer " + values[CREDENTIAL]}


def fetch(source, window, cursor, entries, http):
    stored, calls = _stored(cursor), _Calls(source.get("call_cap", CALL_CAP))
    cited, refused = _cited(source)
    reads = [_api_read(channel, window, stored, http, calls, cited[channel]) for channel in _channels(source)]
    found = _search_units(source, window, _ApiReader(http, calls, window, source["owner"])) if source.get("searches") else None
    return _result(source, window, stored, reads, refused, found)


def _channels(source):
    return source.get("channels") or []


def plan(source, window, cursor, entries, responses, connector):
    try:
        _walk(source, window, _stored(cursor), responses)
    except _Pending as pending:
        call = {"id": pending.call_id, "connector": connector, "tool": pending.tool, "arguments": pending.arguments, "digest": None}
        return {"done": False, "partial": None, "calls": [call]}
    except PartialRead as stop:
        return _common.ended(stop.why)
    except SourceUnreadable:
        return _common.ended(None)
    return _common.ended()


def parse(source, window, cursor, entries, responses, digests):
    stored = _stored(cursor)
    try:
        reads, refused, found = _walk(source, window, stored, responses)
    except _Pending as pending:
        raise SourceUnreadable(f"{pending.tool}: no response {pending.call_id}") from None
    return _result(source, window, stored, reads, refused, found)


class _Calls:
    def __init__(self, cap=CALL_CAP):
        self.left = cap

    def spend(self):
        if self.left == 0:
            raise PartialRead(CALL_CAP_PARTIAL)
        self.left -= 1


def _cited(source):
    pairs = dict.fromkeys((thread["channel"], thread["root_ts"]) for thread in source.get("threads") or [])
    cited, refused = {channel: [] for channel in _channels(source)}, {}
    for channel, root in pairs:
        if channel not in cited:
            refused[_refused_key(channel, root)] = NOT_LISTED
        elif ROOT_TS.fullmatch(root) is None:
            refused[_refused_key(channel, root)] = INVALID_ROOT
        else:
            cited[channel].append(root)
    return cited, refused


def _thread_key(channel, root):
    return f"{channel}:{root}"


def _refused_key(channel, root):
    return _thread_key(clean_text(channel, KEY_PART_CAP), clean_text(root, KEY_PART_CAP))


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
        replies = [reply for root in _roots(history) for reply in _api_replies(channel, root, window, http, calls)]
    except ChannelFailed as failure:
        return Read(channel, [], [], failure.code, {})
    found, lost = _cited_replies(channel, roots, history, lambda root: _api_replies(channel, root, window, http, calls, window["from_ts"]))
    return Read(channel, history, [*replies, *found], None, lost)


def _api_replies(channel, root, window, http, calls, newer_than=None):
    params = {"channel": channel, "ts": root, "latest": str(window["to_ts"]), "limit": str(API_PAGE_SIZE)}
    start = decimal.Decimal(root)
    if newer_than is not None:
        params["oldest"] = str(newer_than)
        start = max(start, decimal.Decimal(newer_than))
    items = _api_pages(channel, REPLIES_PATH, params, http, calls)
    return [item._replace(thread_ts=root) for item in _in_window(items, start, window)]


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


def _walk(source, window, stored, responses):
    relay = _Relay(source["name"], responses)
    cited, refused = _cited(source)
    reads = [_relay_read(relay, channel, window, stored, cited[channel]) for channel in _channels(source)]
    found = _search_units(source, window, _RelayReader(relay, window)) if source.get("searches") else None
    return reads, refused, found


def _relay_read(relay, channel, window, stored, roots):
    start = _start(window, stored, channel)
    arguments = {"channel_id": channel, "oldest": str(start), "latest": str(window["to_ts"]), "limit": RELAY_PAGE_SIZE, "response_format": "detailed"}
    seen_ts = set()
    try:
        items = _relay_pages(relay, TOOL, arguments, lambda call_id, text: _relay_page(channel, call_id, text, seen_ts, start))
        history = _in_window(items, start, window)
        replies = [reply for root in _roots(history) for reply in _relay_replies(relay, channel, root, window)]
    except ChannelFailed as failure:
        return Read(channel, [], [], failure.code, {})
    found, lost = _cited_replies(channel, roots, history, lambda root: _relay_new_replies(relay, channel, root, window))
    return Read(channel, history, [*replies, *found], None, lost)


def _relay_replies(relay, channel, root, window):
    arguments = {"channel_id": channel, "message_ts": root, "response_format": "detailed"}
    seen_ts = set()
    return _relay_pages(relay, THREAD_TOOL, arguments, lambda call_id, text: _thread_page(channel, call_id, text, root, window, seen_ts))


def _relay_new_replies(relay, channel, root, window):
    arguments = {"channel_id": channel, "message_ts": root, "response_format": "detailed"}
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


def _result(source, window, stored, reads, refused, found=None):
    base = _links_base(source)
    records, cursor, entries = [], {}, _failed(refused)
    for read in reads:
        if read.failure is None:
            records.extend(_record(base, item) for item in _merged(read))
            cursor[read.channel] = _newest(read.history, _stored_ts(stored, read.channel), window)
            entries.update(_failed(read.lost))
        else:
            entries[read.channel] = {"status": "failed", "reason": read.failure}
    kept = {"messages": records}
    if found is not None:
        kept["units"] = found[0]
        entries.update(_failed(found[1]))
    return {"records": kept, "cursor": {"ts": {**stored, **cursor}}, "entries": entries}


def _failed(reasons):
    return {key: {"status": "failed", "reason": reason} for key, reason in reasons.items()}


def _merged(read):
    copies = {decimal.Decimal(item.ts): item for item in (*read.history, *read.replies)}
    return [copies[ts] for ts in sorted(copies)]


def _newest(history, stored_ts, window):
    if history:
        return max(history, key=lambda item: decimal.Decimal(item.ts)).ts
    end = f"{window['to_ts']}.000000"
    return end if stored_ts is None else max(end, stored_ts, key=decimal.Decimal)


def _record(base, item):
    link = _message_link(base, item.channel, item.ts)
    text = LINE_BREAK.sub("\n", item.text).rstrip()
    return {"channel": item.channel, "ts": item.ts, "thread_ts": item.thread_ts, "author": item.author, "text": text, "link": link}


def message_link(source, channel, ts):
    return _message_link(_links_base(source), channel, ts)


def _message_link(base, channel, ts):
    return f"{base}/archives/{urllib.parse.quote(channel, safe='')}/p{ts.replace('.', '')}"


def _links_base(source):
    config = source.get("provider_config") or {}
    return (config.get("links_base") or dig(config, "api", "base_url") or LINKS_BASE).rstrip("/")


def _stored(cursor):
    stored = dig(cursor, "ts")
    return {channel: ts for channel, ts in stored.items() if isinstance(ts, str)} if isinstance(stored, dict) else {}


def _stored_ts(stored, channel):
    ts = stored.get(channel)
    return ts if isinstance(ts, str) and TS.fullmatch(ts) else None


def _start(window, stored, channel):
    ts = _stored_ts(stored, channel)
    return decimal.Decimal(_common.read_start(window, None if ts is None else decimal.Decimal(ts)))


def _string(value):
    return value if isinstance(value, str) else ""


class _Unit:
    def __init__(self, hit):
        self.channel = hit.channel
        self.kind = hit.kind
        self.name = hit.kind or hit.name
        self.participants = hit.participants
        self.items = {}
        self.reacted = {}

    def add(self, item):
        key = decimal.Decimal(item.ts)
        before = self.items.get(key)
        if before is not None:
            item = item._replace(bot=item.bot or before.bot, name=item.name or before.name, thread_ts=item.thread_ts or before.thread_ts)
        self.items[key] = item

    def ordered(self):
        return [self.items[ts] for ts in sorted(self.items)]


def _since(search, window):
    since = search["since"]
    return window["from_ts"] if since == "window" else window["to_ts"] - since["lookback_days"] * DAY_SECONDS


def _within(hit, start, window):
    return start < decimal.Decimal(hit.item.ts) <= window["to_ts"]


def _search_units(source, window, reader):
    cap = source.get("search_page_cap", SEARCH_PAGE_CAP)
    hits, lost = [], {}
    for search in source["searches"]:
        found, cut = reader.search(search, _since(search, window), cap)
        hits.extend(found)
        if cut is not None:
            lost[f"search:{search['name']}"] = f"{PAGE_CAP_PARTIAL}: {cut} page(s) read"
    conversations, threads, singles = _grouped(hits)
    lost.update(_read_conversations(reader, conversations))
    lost.update(_read_threads(reader, threads, lost))
    units = [*conversations.values(), *threads.values(), *singles.values()]
    for unit in units:
        unit.items = {key: reader.named(item) for key, item in unit.items.items()}
    if source.get("reactions") is True:
        for unit in units:
            lost.update(_read_reactions(reader, unit, source["owner"]))
    return [_unit_record(unit) for unit in units], lost


def _grouped(hits):
    conversations, threads, singles = {}, {}, {}
    for hit in hits:
        if hit.kind is not None:
            table, key = conversations, hit.channel
        elif hit.root is not None:
            table, key = threads, (hit.channel, hit.root)
        else:
            table, key = singles, (hit.channel, hit.item.ts)
        table.setdefault(key, _Unit(hit)).add(hit.item)
    return conversations, threads, singles


def _read_conversations(reader, conversations):
    lost = {}
    for channel, unit in list(conversations.items()):
        read = reader.conversation(channel)
        if read.failure is not None:
            lost[channel] = read.failure
            del conversations[channel]
            continue
        for item in (*read.history, *read.replies):
            unit.add(item)
        try:
            unit.participants = reader.participants(unit)
        except ChannelFailed as failure:
            lost[channel] = failure.code
            del conversations[channel]
    return lost


def _read_threads(reader, threads, failed):
    lost = {}
    for (channel, root), unit in list(threads.items()):
        if channel in failed or channel in lost:
            del threads[(channel, root)]
            continue
        try:
            items = reader.thread(channel, root)
        except ChannelFailed as failure:
            lost[channel] = failure.code
            del threads[(channel, root)]
        except ThreadNotFound as failure:
            lost[_thread_key(channel, root)] = failure.code
            del threads[(channel, root)]
        else:
            for item in items:
                unit.add(item._replace(thread_ts=root))
    return lost


def _read_reactions(reader, unit, owner):
    messages, lost = unit.ordered(), {}
    last = max((decimal.Decimal(item.ts) for item in messages if item.author == owner), default=None)
    later = [item for item in messages if item.author != owner and (last is None or decimal.Decimal(item.ts) > last)]
    for item in later[-REACTIONS_PER_UNIT:]:
        try:
            users = reader.reactions(unit.channel, item.ts)
        except (ChannelFailed, ThreadNotFound, ReactionsFailed) as failure:
            lost[f"reactions:{unit.channel}:{item.ts}"] = failure.code
        else:
            unit.reacted[decimal.Decimal(item.ts)] = owner in users
    return lost


def _unit_record(unit):
    participants = [{"id": who, "name": clean_text(name, KEY_PART_CAP)} for who, name in unit.participants]
    messages = [_unit_message(item, unit.reacted) for item in unit.ordered()]
    return {"channel": unit.channel, "name": clean_text(unit.name, KEY_PART_CAP), "participants": participants, "messages": messages}


def _unit_message(item, reacted):
    record = {
        "user": item.author,
        "name": clean_text(item.name, KEY_PART_CAP),
        "bot": item.bot,
        "ts": item.ts,
        "root_ts": item.thread_ts,
        "text": clean_text(item.text, TEXT_CAP),
    }
    seen = reacted.get(decimal.Decimal(item.ts))
    return record if seen is None else {**record, "owner_reacted": seen}


def _search_types(search):
    types = search.get("channel_types")
    return frozenset(types.split(",")) if types else None


def _conversation_kind(channel, name, types):
    if channel.startswith("D"):
        return DM
    if name.lower() == GROUP_DM.lower() or name.startswith("mpdm-") or (types is not None and types <= CONVERSATION_TYPES):
        return GROUP_DM
    return None


class _RelayReader:
    def __init__(self, relay, window):
        self.relay = relay
        self.window = window
        self.unit_window = {**window, "first_read_from_ts": window["from_ts"]}

    def search(self, search, start, cap):
        arguments = _search_arguments(search, start, self.window)
        types, kept = _search_types(search), []

        def parse(call_id, text):
            hits, after = _search_page(call_id, text, types)
            kept.extend(hits)
            return hits, after

        try:
            _relay_pages(self.relay, SEARCH_TOOL, arguments, parse, cap, SEARCH_CUT)
        except PartialRead as stop:
            if stop.why != SEARCH_CUT:
                raise
            cut = cap
        else:
            cut = None
        return [hit for hit in kept if _within(hit, start, self.window)], cut

    def conversation(self, channel):
        return _relay_read(self.relay, channel, self.unit_window, {}, [])

    def thread(self, channel, root):
        arguments = {"channel_id": channel, "message_ts": root, "response_format": "detailed"}
        seen_ts = set()
        parse = lambda call_id, text: _unit_thread_page(channel, call_id, text, root, self.window, seen_ts)
        return _relay_pages(self.relay, THREAD_TOOL, arguments, parse)

    def participants(self, unit):
        return unit.participants

    def named(self, item):
        return item

    def reactions(self, channel, ts):
        _, text = self.relay.read(REACTIONS_TOOL, {"channel_id": channel, "message_ts": ts})
        result = _reactions_text(text)
        if result is None:
            raise ReactionsFailed("unreadable reactions response")
        users = set()
        for line in LINE_BREAK.split(result)[1:]:
            _, separator, names = line.partition(NAME_SEPARATOR)
            if separator:
                users.update(REACTION_USER.findall(names.rstrip()))
        return users


def _reactions_text(text):
    try:
        document = json.loads(text)
    except ValueError:
        return None
    result = document.get("result") if isinstance(document, dict) else None
    if isinstance(result, str) and (result.strip() == NO_REACTIONS or result.startswith(REACTIONS_OPEN)):
        return result
    return None


def _search_arguments(search, start, window):
    arguments = {"filters": search["filters"]}
    if "channel_types" in search:
        arguments["channel_types"] = search["channel_types"]
    if "keywords" in search:
        arguments["keywords"] = search["keywords"]
    return {
        **arguments,
        "after": str(start),
        "before": str(window["to_ts"]),
        "sort": "timestamp",
        "sort_dir": "asc",
        "limit": SEARCH_PAGE_SIZE,
        "include_context": False,
        "natural_language_query": "",
        "response_format": "detailed",
    }


def _search_page(call_id, text, types):
    shape = f"{SEARCH_TOOL}: response {call_id}"
    document = _common.json_object(text, f"{shape} is not JSON", f"{shape} is not a JSON object")
    results, info = document.get("results"), document.get("pagination_info", "")
    if not isinstance(results, str) or not isinstance(info, str):
        raise SourceUnreadable(f"{shape} without results or pagination_info")
    more = SEARCH_CURSOR.search(info)
    return _search_hits(call_id, LINE_BREAK.split(results), types), more.group(1) if more else None


def _search_hits(call_id, lines, types):
    starts, expected, total = [], 1, None
    for index, line in enumerate(lines):
        found = RESULT_HEADER.fullmatch(line.rstrip())
        if found is None or int(found.group(1)) != expected:
            continue
        total = found.group(2) if total is None else total
        if found.group(2) == total:
            starts.append(index)
            expected += 1
    listed = RESULTS_COUNT.search("\n".join(lines[: starts[0] if starts else len(lines)]))
    if starts and listed is not None and int(listed.group(1)) != len(starts):
        raise SourceUnreadable(f"{SEARCH_TOOL}: response {call_id} lists {listed.group(1)} results but holds {len(starts)}")
    ends = starts[1:] + [len(lines)]
    return [_search_hit(call_id, _without_separator(lines[start + 1 : end]), types) for start, end in zip(starts, ends)]


def _without_separator(block):
    block = list(block)
    while block and not block[-1].strip():
        block.pop()
    if block and block[-1].strip() == SEARCH_BLOCK_END:
        block.pop()
    return block


def _search_hit(call_id, block, types):
    fields, text = {}, ""
    for index, line in enumerate(block):
        if line.startswith("Text:"):
            text = "\n".join([line[len("Text:") :], *block[index + 1 :]]).strip()
            break
        key, separator, value = line.partition(": ")
        if separator:
            fields.setdefault(key, value)
    channel = SEARCH_CHANNEL.fullmatch(fields.get("Channel", "").rstrip())
    sender = SEARCH_FROM.fullmatch(fields.get("From", ""))
    ts = fields.get("Message_ts", "").strip()
    if channel is None or sender is None or not TS.fullmatch(ts):
        raise SourceUnreadable(f"{SEARCH_TOOL}: response {call_id} has a result without its Channel, From or Message_ts line")
    shown, cid = channel.groups()
    kind = _conversation_kind(cid, shown, types)
    replied = fields.get("Reply count", "").strip().isdigit() and int(fields["Reply count"]) > 0
    linked = PERMALINK_THREAD.search(fields.get("Permalink", ""))
    root = linked.group(1) if linked else ts if replied else None
    participants = SEARCH_PARTICIPANT.findall(fields.get("Participants", ""))
    item = Item(cid, ts, root, sender.group(2), text, EMAIL_TAIL.sub("", sender.group(1)).strip(), sender.group(3) is not None)
    return Hit(cid, shown, kind, [(who, EMAIL_TAIL.sub("", name).strip()) for name, who in participants], root, item)


def _unit_thread_page(channel, call_id, text, root, window, seen_ts):
    messages, info = _relay_body(THREAD_TOOL, call_id, channel, text, THREAD_PARENT)
    lines = LINE_BREAK.split(messages)
    items = [] if messages.strip() in NO_THREAD else [*_thread_replies(call_id, channel, root, lines, window, seen_ts), _thread_parent(channel, root, lines)]
    return items, _next_cursor(THREAD_TOOL, call_id, info, (NO_MORE, THREAD_NO_MORE))


def _thread_parent(channel, root, lines):
    marker = _replies_line(lines, root)
    kept, _ = _without_metadata(lines[PARENT_LINES : marker[0] if marker else len(lines)])
    who = lines[1][len(FROM_OPEN) :] if lines[1].startswith(FROM_OPEN) else ""
    author, name, bot = _who_parts(who)
    return Item(channel, root, root, author, "\n".join(kept), name, bot)


class _ApiReader:
    def __init__(self, http, calls, window, owner):
        self.http = http
        self.calls = calls
        self.window = window
        self.owner = owner
        self.unit_window = {**window, "first_read_from_ts": window["from_ts"]}
        self.names = {}

    def search(self, search, start, cap):
        types = _search_types(search)
        params = {"query": _api_query(search, start, self.window), "sort": "timestamp", "sort_dir": "asc", "count": str(SEARCH_PAGE_SIZE)}
        found, cut = [], cap
        for page in range(1, cap + 1):
            self.calls.spend()
            body = self.http.get(SEARCH_PATH, {**params, "page": str(page)})
            matches = dig(body, "messages", "matches")
            if dig(body, "ok") is not True or not isinstance(matches, list):
                raise SourceUnreadable(f"GET {SEARCH_PATH}: {search['name']}: {_error_code(body)}")
            found.extend(hit for hit in map(_api_hit, matches) if types is None or hit.kind_type in types)
            pages = dig(body, "messages", "paging", "pages")
            if not _is_count(pages) or page >= pages:
                cut = None
                break
        return [hit for hit in found if _within(hit, start, self.window)], cut

    def conversation(self, channel):
        return _api_read(channel, self.unit_window, {}, self.http, self.calls, [])

    def thread(self, channel, root):
        params = {"channel": channel, "ts": root, "latest": str(self.window["to_ts"]), "limit": str(API_PAGE_SIZE)}
        items = _api_pages(channel, REPLIES_PATH, params, self.http, self.calls)
        return [item for item in items if decimal.Decimal(item.ts) <= self.window["to_ts"]]

    def participants(self, unit):
        self.calls.spend()
        if unit.kind == DM:
            body = self.http.get(INFO_PATH, {"channel": unit.channel})
            if dig(body, "ok") is not True:
                raise _api_failure(unit.channel, body)
            other = _string(dig(body, "channel", "user"))
            members = [other, self.owner] if other and other != self.owner else [self.owner]
        else:
            body = self.http.get(MEMBERS_PATH, {"channel": unit.channel, "limit": str(API_PAGE_SIZE)})
            if dig(body, "ok") is not True:
                raise _api_failure(unit.channel, body)
            members = [member for member in _common.as_list(dig(body, "members")) if isinstance(member, str)]
        return [(member, self._name_of(member)) for member in members]

    def reactions(self, channel, ts):
        self.calls.spend()
        body = self.http.get(REACTIONS_PATH, {"channel": channel, "timestamp": ts, "full": "true"})
        if dig(body, "ok") is not True:
            if _error_code(body) == "message_not_found":
                raise ReactionsFailed("message_not_found")
            raise _api_failure(channel, body)
        found = _common.as_list(dig(body, "message", "reactions"))
        return {user for reaction in found for user in _common.as_list(dig(reaction, "users")) if isinstance(user, str)}

    def named(self, item):
        return item if item.name or not item.author else item._replace(name=self._name_of(item.author))

    def _name_of(self, user):
        if user not in self.names:
            self.names[user] = self._lookup(user) if USER_ID.fullmatch(user) else ""
        return self.names[user]

    def _lookup(self, user):
        self.calls.spend()
        body = self.http.get(USERS_PATH, {"user": user})
        if dig(body, "ok") is not True:
            code = _error_code(body)
            if code == "user_not_found":
                return ""
            raise SourceUnreadable(f"GET {USERS_PATH}: {code}")
        profile = dig(body, "user", "profile")
        return _string(dig(profile, "display_name")) or _string(dig(profile, "real_name")) or _string(dig(body, "user", "real_name"))


def _api_query(search, start, window):
    day = datetime.timedelta(days=2)
    first = datetime.datetime.fromtimestamp(start, datetime.timezone.utc).date() - day
    last = datetime.datetime.fromtimestamp(window["to_ts"], datetime.timezone.utc).date() + day
    return " ".join([search["filters"], *search.get("keywords", []), f"after:{first.isoformat()}", f"before:{last.isoformat()}"])


def _api_hit(match):
    channel = dig(match, "channel")
    cid, ts = dig(channel, "id"), dig(match, "ts")
    if not isinstance(cid, str) or not CHANNEL_ID.fullmatch(cid) or not isinstance(ts, str) or not TS.fullmatch(ts):
        raise SourceUnreadable(f"GET {SEARCH_PATH}: result without a valid channel id or ts")
    kind = DM if dig(channel, "is_im") is True else GROUP_DM if dig(channel, "is_mpim") is True else None
    linked = PERMALINK_THREAD.search(_string(dig(match, "permalink")))
    own = dig(match, "thread_ts")
    root = linked.group(1) if linked else own if isinstance(own, str) and TS.fullmatch(own) else ts if _is_count(dig(match, "reply_count")) else None
    author = _string(dig(match, "user")) or _string(dig(match, "bot_id"))
    bot = bool(dig(match, "bot_id")) or dig(match, "subtype") == "bot_message"
    return Hit(cid, "#" + _string(dig(channel, "name")), kind, [], root, Item(cid, ts, root, author, _string(dig(match, "text")), "", bot), _api_type(channel))


def _api_type(channel):
    if dig(channel, "is_im") is True:
        return "im"
    if dig(channel, "is_mpim") is True:
        return "mpim"
    return "private_channel" if dig(channel, "is_private") is True else "public_channel"
