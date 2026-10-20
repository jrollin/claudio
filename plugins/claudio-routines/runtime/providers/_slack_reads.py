import collections
import decimal
import json
import re
import urllib.parse

import state
import store

from ._common import dig
from ._errors import PAGE_CAP_PARTIAL, PartialRead, SourceUnreadable
from ._http import PAGE_CAP
from ._replay import recorded_error
from ._slack_read import (
    API_PAGE_SIZE,
    CURSOR_REPEATED,
    HISTORY_PATH,
    RELAY_PAGE_SIZE,
    RELAY_THREAD_PAGE_SIZE,
    REPLIES_PATH,
    THREAD_TOOL,
    TOOL,
    InvalidEntity,
    Item,
    _api_page,
    _in_span,
    _is_count,
    _Pending,
    _relay_page,
)
from ._slack_search import (
    INFO_PATH,
    MEMBERS_PATH,
    REACTIONS_PATH,
    REACTIONS_TOOL,
    SEARCH_CUT,
    SEARCH_PAGE_SIZE,
    SEARCH_PATH,
    SEARCH_TOOL,
    USERS_PATH,
    Hit,
    _api_members,
    _api_reactions,
    _api_search_page,
    _api_query,
    _api_user_name,
    _relay_reactions,
    _search_arguments,
    _search_page,
    _search_types,
    _unit_thread_page,
)

KINDS = ("history", "thread", "reactions", "members", "users", "search")
SLACK_ID = re.compile(r"[A-Z0-9]{1,32}")
MESSAGE_TS = re.compile(r"[0-9]{1,16}\.[0-9]{1,9}")
RECORD_KEYS = ("response", "error")
ERROR_KEYS = ("class", "message", "status")

ReadKey = collections.namedtuple("ReadKey", "kind entity span")

MESSAGE_ROW = {"ts": state.TEXT, "author": state.TEXT, "text": state.TEXT, "name": state.TEXT, "bot": state.BOOLEAN}
THREADED_ROW = {**MESSAGE_ROW, "thread_ts": state.Nullable(state.TEXT)}
ROW_SPECS = {
    "history": THREADED_ROW,
    "thread": MESSAGE_ROW,
    "search": {
        "channel": state.TEXT,
        "name": state.TEXT,
        "kind": state.Nullable(state.TEXT),
        "participants": [{"id": state.TEXT, "name": state.TEXT}],
        "root": state.Nullable(state.TEXT),
        "kind_type": state.Nullable(state.TEXT),
        "item": THREADED_ROW,
    },
    "reactions": {"user": state.TEXT},
    "members": {"id": state.TEXT},
    "users": {"name": state.TEXT},
}


def _slack_id(value, what):
    if not isinstance(value, str) or SLACK_ID.fullmatch(value) is None:
        raise InvalidEntity(what)
    return value


def _message_ts(value, what):
    if not isinstance(value, str) or MESSAGE_TS.fullmatch(value) is None:
        raise InvalidEntity(what)
    return value


def history_key(channel, start, to):
    return ReadKey("history", (("channel", _slack_id(channel, "channel")),), (str(start), str(to)))


def thread_key(channel, root, oldest, to):
    root = _message_ts(root, "thread root")
    return ReadKey("thread", (("channel", _slack_id(channel, "channel")), ("root", root)), (root if oldest is None else str(oldest), str(to)))


def reactions_key(channel, ts):
    return ReadKey("reactions", (("channel", _slack_id(channel, "channel")), ("message", _message_ts(ts, "message ts"))), None)


def members_key(channel):
    return ReadKey("members", (("channel", _slack_id(channel, "channel")),), None)


def users_key(user):
    return ReadKey("users", (("user", _slack_id(user, "user")),), None)


def search_key(name, start, to):
    return ReadKey("search", (("search", urllib.parse.quote(name, safe="")),), (str(start), str(to)))


def _known_kind(kind):
    if kind not in KINDS:
        raise state.Rejected(f"slack read: unknown kind {kind}")
    return kind


def _message_row(item):
    return {"ts": item.ts, "author": item.author, "text": item.text, "name": item.name, "bot": item.bot}


def _threaded_row(item):
    return {**_message_row(item), "thread_ts": item.thread_ts}


def _hit_row(hit):
    participants = [{"id": who, "name": name} for who, name in hit.participants]
    return {"channel": hit.channel, "name": hit.name, "kind": hit.kind, "participants": participants, "root": hit.root, "kind_type": hit.kind_type, "item": _threaded_row(hit.item)}


def _history_record(entity, row):
    return Item(entity["channel"], row["ts"], row["thread_ts"], row["author"], row["text"], row["name"], row["bot"])


def _thread_record(entity, row):
    return Item(entity["channel"], row["ts"], entity["root"], row["author"], row["text"], row["name"], row["bot"])


def _hit_record(entity, row):
    shown = row["item"]
    item = Item(row["channel"], shown["ts"], shown["thread_ts"], shown["author"], shown["text"], shown["name"], shown["bot"])
    participants = [(who["id"], who["name"]) for who in row["participants"]]
    return Hit(row["channel"], row["name"], row["kind"], participants, row["root"], item, row["kind_type"])


ROW_WRITERS = {
    "history": _threaded_row,
    "thread": _message_row,
    "search": _hit_row,
    "reactions": lambda user: {"user": user},
    "members": lambda member: {"id": member},
    "users": lambda name: {"name": name},
}
ROW_READERS = {
    "history": _history_record,
    "thread": _thread_record,
    "search": _hit_record,
    "reactions": lambda entity, row: row["user"],
    "members": lambda entity, row: row["id"],
    "users": lambda entity, row: row["name"],
}


def to_rows(kind, records):
    write = ROW_WRITERS[_known_kind(kind)]
    return [write(record) for record in records]


def from_rows(kind, entity, rows):
    spec, read = ROW_SPECS[_known_kind(kind)], ROW_READERS[kind]
    for index, row in enumerate(rows):
        state.check(row, spec, f"{kind}[{index}]")
    return [read(entity, row) for row in rows]


def _is_text_block(block):
    return isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)


def page_text(call_id, data):
    try:
        text = data if isinstance(data, str) else data.decode("utf-8")
    except UnicodeDecodeError:
        raise SourceUnreadable(f"response {call_id} is not UTF-8") from None
    if not text.lstrip().startswith("["):
        return text
    try:
        blocks = json.loads(text)
    except (ValueError, RecursionError):
        return text
    if isinstance(blocks, list) and blocks and all(_is_text_block(block) for block in blocks):
        return "".join(block["text"] for block in blocks)
    return text


def api_body(call_id, data):
    try:
        record = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise SourceUnreadable(f"record {call_id} is not JSON") from None
    if not isinstance(record, dict) or any(key not in record for key in RECORD_KEYS):
        raise SourceUnreadable(f"record {call_id} is not an HTTP record")
    error = record["error"]
    if error is None:
        return record["response"]
    if not isinstance(error, dict) or any(key not in error for key in ERROR_KEYS):
        raise SourceUnreadable(f"record {call_id} has an unreadable error")
    raise recorded_error(error, f"record {call_id}")


def _relay_parser(kind, entity, span, request):
    seen = set()
    if kind == "history":
        oldest = decimal.Decimal(span[0])
        return lambda call_id, data: _relay_page(entity["channel"], call_id, page_text(call_id, data), seen, oldest)
    if kind == "thread":
        to = decimal.Decimal(span[1])
        return lambda call_id, data: _unit_thread_page(entity["channel"], call_id, page_text(call_id, data), entity["root"], to, seen)
    if kind == "search":
        types = _search_types((request or {}).get("arguments") or {})
        return lambda call_id, data: _search_page(call_id, page_text(call_id, data), types)
    if kind == "reactions":
        return lambda call_id, data: (sorted(_relay_reactions(page_text(call_id, data))), None)
    raise SourceUnreadable(f"{kind}: not read over the connector")


def _api_body_parser(kind, entity, request):
    if kind == "history":
        return lambda body: _api_page(entity["channel"], HISTORY_PATH, body)
    if kind == "thread":
        return lambda body: _api_page(entity["channel"], REPLIES_PATH, body)
    if kind == "search":
        name = urllib.parse.unquote(entity["search"])
        return lambda body: _api_search_page(name, body)
    if kind == "reactions":
        return lambda body: sorted(_api_reactions(entity["channel"], body))
    if kind == "members":
        path = INFO_PATH if str((request or {}).get("path", "")).endswith(INFO_PATH) else MEMBERS_PATH
        return lambda body: _api_members(entity["channel"], path, body)
    return lambda body: [_api_user_name(body)]


def page_parser(kind, transport, entity, span, request):
    _known_kind(kind)
    if transport == "mcp":
        return _relay_parser(kind, entity, span, request)
    parse = _api_body_parser(kind, entity, request)
    return lambda call_id, data: (parse(api_body(call_id, data)), None)


def parse_read(kind, read, pages):
    _known_kind(kind)
    if read["kind"] != kind:
        raise state.Rejected(f"slack read: a {read['kind']} read parsed as {kind}")
    listed = read["pages"]
    if len(pages) != len(listed):
        raise state.Rejected(f"slack read: {len(listed)} page(s) listed, {len(pages)} given")
    span = None if read["span"] is None else (read["span"]["from"], read["span"]["to"])
    parse = page_parser(kind, read["transport"], read["entity"], span, listed[0]["request"] if listed else None)
    records = []
    for page, data in zip(listed, pages):
        records.extend(parse(page["file"], data)[0])
    return records


def _settled(handle, kind, read):
    try:
        records = read()
    except PartialRead as stop:
        handle.finish("partial", str(stop))
        raise
    except SourceUnreadable as error:
        handle.finish("failed", getattr(error, "code", None) or str(error))
        raise
    handle.finish("complete", None, to_rows(kind, records))
    return records


def _relay_read_pages(handle, tool, arguments, parse, stop=None, cap=PAGE_CAP, capped=PAGE_CAP_PARTIAL):
    found, after, seen = [], None, set()
    for _ in range(cap):
        asked = arguments if after is None else {**arguments, "cursor": after}
        try:
            data = handle.page({"tool": tool, "arguments": asked})
        except store.PagePending as pending:
            raise _Pending(pending.call_id, tool, asked) from None
        items, after = parse(handle.last_id, data)
        found.extend(items)
        if stop is not None and stop(items):
            after = None
        if after is None:
            return found
        if after in seen:
            raise PartialRead(CURSOR_REPEATED)
        seen.add(after)
    raise PartialRead(capped)


def _thread_arguments(channel, root, oldest):
    return {"channel_id": channel, "message_ts": root, "oldest": str(oldest), "limit": RELAY_THREAD_PAGE_SIZE, "response_format": "detailed"}


class RelayReads:
    def __init__(self, session):
        self.session = session

    def history(self, channel, start, to):
        arguments = {"channel_id": channel, "oldest": str(start), "latest": str(to), "limit": RELAY_PAGE_SIZE, "response_format": "detailed"}
        return self._read(history_key(channel, start, to), TOOL, arguments)

    def replies(self, channel, root, oldest, to):
        items = self._read(thread_key(channel, root, oldest, to), THREAD_TOOL, _thread_arguments(channel, root, oldest))
        return [item for item in items if decimal.Decimal(item.ts) > decimal.Decimal(root)]

    def cited(self, channel, root, oldest, to):
        first, start = decimal.Decimal(root), max(decimal.Decimal(root), decimal.Decimal(oldest))
        reached = lambda items: any(first < decimal.Decimal(item.ts) <= start for item in items)
        items = self._read(thread_key(channel, root, oldest, to), THREAD_TOOL, _thread_arguments(channel, root, oldest), reached)
        return [item for item in items if decimal.Decimal(item.ts) > start]

    def thread(self, channel, root, oldest, to):
        arguments = {"channel_id": channel, "message_ts": root, "limit": RELAY_THREAD_PAGE_SIZE, "response_format": "detailed"}
        if oldest is not None:
            arguments["oldest"] = str(oldest)
        return self._read(thread_key(channel, root, oldest, to), THREAD_TOOL, arguments)

    def search(self, search, start, to, cap):
        key, arguments, kept = search_key(search["name"], start, to), _search_arguments(search, start, to), []
        handle = self.session.open(*key)
        parse = page_parser("search", "mcp", dict(key.entity), key.span, {"tool": SEARCH_TOOL, "arguments": arguments})

        def keep(call_id, data):
            hits, after = parse(call_id, data)
            kept.extend(hits)
            return hits, after

        try:
            _settled(handle, "search", lambda: _relay_read_pages(handle, SEARCH_TOOL, arguments, keep, cap=cap, capped=SEARCH_CUT))
        except PartialRead as stop:
            if stop.why != SEARCH_CUT:
                raise
            return kept, cap
        return kept, None

    def reactions(self, channel, ts):
        return set(self._read(reactions_key(channel, ts), REACTIONS_TOOL, {"channel_id": channel, "message_ts": ts}))

    def _read(self, key, tool, arguments, stop=None):
        handle = self.session.open(*key)
        parse = page_parser(key.kind, "mcp", dict(key.entity), key.span, {"tool": tool, "arguments": arguments})
        return _settled(handle, key.kind, lambda: _relay_read_pages(handle, tool, arguments, parse, stop))


class ApiReads:
    def __init__(self, session, http, calls):
        self.session = session
        self.http = http
        self.calls = calls

    def history(self, channel, start, to):
        params = {"channel": channel, "oldest": str(start), "latest": str(to), "limit": str(API_PAGE_SIZE)}
        return self._read(history_key(channel, start, to), channel, HISTORY_PATH, params)

    def replies(self, channel, root, oldest, to):
        params = {"channel": channel, "ts": root, "oldest": str(oldest), "latest": str(to), "limit": str(API_PAGE_SIZE)}
        items = self._read(thread_key(channel, root, oldest, to), channel, REPLIES_PATH, params)
        return [item._replace(thread_ts=root) for item in _in_span(items, max(decimal.Decimal(root), decimal.Decimal(oldest)), to)]

    def cited(self, channel, root, oldest, to):
        return self.replies(channel, root, oldest, to)

    def thread(self, channel, root, oldest, to):
        params = {"channel": channel, "ts": root, "latest": str(to), "limit": str(API_PAGE_SIZE)}
        if oldest is not None:
            params["oldest"] = str(oldest)
        items = self._read(thread_key(channel, root, oldest, to), channel, REPLIES_PATH, params)
        return [item for item in items if decimal.Decimal(item.ts) <= to]

    def search(self, search, start, to, cap):
        key, found = search_key(search["name"], start, to), []
        handle = self.session.open(*key)
        params = {"query": _api_query(search, start, to), "sort": "timestamp", "sort_dir": "asc", "count": str(SEARCH_PAGE_SIZE)}

        def pages():
            for page in range(1, cap + 1):
                body = self._body(handle, SEARCH_PATH, {**params, "page": str(page)})
                found.extend(_api_search_page(search["name"], body))
                last = dig(body, "messages", "paging", "pages")
                if not _is_count(last) or page >= last:
                    return found
            raise PartialRead(SEARCH_CUT)

        try:
            _settled(handle, "search", pages)
        except PartialRead as stop:
            if stop.why != SEARCH_CUT:
                raise
            return found, cap
        return found, None

    def members(self, channel, path):
        params = {"channel": channel} if path == INFO_PATH else {"channel": channel, "limit": str(API_PAGE_SIZE)}
        return self._single(members_key(channel), path, params, lambda body: _api_members(channel, path, body))

    def user_name(self, user):
        return self._single(users_key(user), USERS_PATH, {"user": user}, lambda body: [_api_user_name(body)])[0]

    def reactions(self, channel, ts):
        params = {"channel": channel, "timestamp": ts, "full": "true"}
        return set(self._single(reactions_key(channel, ts), REACTIONS_PATH, params, lambda body: sorted(_api_reactions(channel, body))))

    def _read(self, key, channel, path, params):
        handle = self.session.open(*key)
        return _settled(handle, key.kind, lambda: self._pages(handle, channel, path, params))

    def _single(self, key, path, params, parse):
        handle = self.session.open(*key)
        return _settled(handle, key.kind, lambda: parse(self._body(handle, path, params)))

    def _pages(self, handle, channel, path, params):
        found, page = [], params
        for _ in range(PAGE_CAP):
            body = self._body(handle, path, page)
            found.extend(_api_page(channel, path, body))
            if dig(body, "has_more") is not True:
                return found
            after = dig(body, "response_metadata", "next_cursor")
            if not isinstance(after, str) or not after:
                raise PartialRead(f"GET {path}: {channel}: has_more without next_cursor")
            page = {**params, "cursor": after}
        raise PartialRead(PAGE_CAP_PARTIAL)

    def _body(self, handle, path, params):
        self.calls.spend()
        live = []
        request = {"method": "GET", "path": path, "query": urllib.parse.urlencode(params, doseq=True), "body": None}
        data = handle.page(request, fetch=lambda: self._fetched(path, params, live))
        if not live:
            return api_body(handle.last_id, data)
        if isinstance(live[0], SourceUnreadable):
            raise live[0]
        return live[0]

    def _fetched(self, path, params, live):
        records, previous = [], self.http.recorder

        def capture(record):
            records.append(record)
            if previous is not None:
                previous(record)

        self.http.recorder = capture
        try:
            live.append(self.http.get(path, params))
        except SourceUnreadable as error:
            if not records:
                raise
            live.append(error)
        finally:
            self.http.recorder = previous
        return state.dump(store.replaced(records[-1]))
