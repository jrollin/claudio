import collections
import datetime
import decimal
import json
import re

from state import clean_text

from . import _common
from ._common import dig
from ._errors import PAGE_CAP_PARTIAL, PartialRead, SourceUnreadable
from ._slack_read import (
    API_PAGE_SIZE,
    EMAIL_TAIL,
    FROM_OPEN,
    KEY_PART_CAP,
    LINE_BREAK,
    NO_MORE,
    NO_THREAD,
    PARENT_LINES,
    RELAY_THREAD_PAGE_SIZE,
    REPLIES_PATH,
    THREAD_NO_MORE,
    THREAD_PARENT,
    THREAD_TOOL,
    TS,
    ChannelFailed,
    Item,
    ThreadNotFound,
    _api_failure,
    _api_pages,
    _channel_read,
    _error_code,
    _is_count,
    _next_cursor,
    _no_replies_line,
    _relay_body,
    _relay_pages,
    _replies_line,
    _string,
    _thread_key,
    _thread_replies,
    _who_parts,
    _without_metadata,
)

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
REREAD_MARGIN = decimal.Decimal("0.000001")
TEXT_CAP = 300
DAY_SECONDS = 86400
DM = "DM"
GROUP_DM = "group DM"
CONVERSATION_TYPES = frozenset(("im", "mpim"))
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
USER_MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")
GROUP_MENTION = re.compile(r"<!subteam\^(S[A-Z0-9]+)(?:\|[^>]*)?>")

Hit = collections.namedtuple("Hit", "channel name kind participants root item kind_type", defaults=(None,))


class ReactionsFailed(SourceUnreadable):
    def __init__(self, code):
        super().__init__(f"reactions: {code}")
        self.code = code


class _Unit:
    def __init__(self, hit):
        self.channel = hit.channel
        self.kind = hit.kind
        self.name = hit.kind or hit.name
        self.participants = hit.participants
        self.items = {}
        self.reacted = {}
        self.reread_only = False

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


def _unit_window(window, start):
    first = window["from_ts"] if start is None else min(window["from_ts"], start)
    return {**window, "first_read_from_ts": first}


def _within(hit, start, to):
    return start < decimal.Decimal(hit.item.ts) <= to


def _search_units(source, window, reader):
    cap = source.get("search_page_cap", SEARCH_PAGE_CAP)
    hits, lost = [], {}
    for search in source["searches"]:
        found, cut = reader.search(search, _since(search, window), cap)
        hits.extend(found)
        if cut is not None:
            lost[f"search:{search['name']}"] = f"{PAGE_CAP_PARTIAL}: {cut} page(s) read"
    conversations, threads, singles = _grouped(hits)
    starts = _add_rereads(source.get("rereads") or [], hits, conversations, threads)
    lost.update(_read_conversations(reader, conversations, starts))
    lost.update(_read_threads(reader, threads, lost, _known_oldest(source.get("known_threads") or [])))
    units = [unit for unit in (*conversations.values(), *threads.values(), *singles.values()) if unit.items]
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


def _add_rereads(rereads, hits, conversations, threads):
    names = {hit.channel: hit.name for hit in hits}
    starts = {}
    for reread in rereads:
        channel, root = reread["channel"], reread["root_ts"]
        if root is not None:
            if (channel, root) not in threads:
                threads[(channel, root)] = _reread_unit(Hit(channel, names.get(channel, channel), None, [], root, None))
            continue
        kind = GROUP_DM if reread["kind"] == "group_dm" else DM
        if channel not in conversations:
            conversations[channel] = _reread_unit(Hit(channel, kind, kind, [], None, None))
        starts[channel] = min(starts.get(channel, decimal.Decimal("Infinity")), decimal.Decimal(reread["last_ts"]) - REREAD_MARGIN)
    return starts


def _reread_unit(hit):
    unit = _Unit(hit)
    unit.reread_only = True
    return unit


def _read_conversations(reader, conversations, starts):
    lost = {}
    for channel, unit in list(conversations.items()):
        read = reader.conversation(channel, starts.get(channel))
        if read.failure is not None:
            lost[channel] = read.failure
            del conversations[channel]
            continue
        for item in (*read.history, *read.replies):
            unit.add(item)
        try:
            if not unit.reread_only:
                unit.participants = reader.participants(unit)
        except ChannelFailed as failure:
            lost[channel] = failure.code
            del conversations[channel]
    return lost


def _known_oldest(known):
    return {(item["channel"], item["root_ts"]): decimal.Decimal(item["last_ts"]) - REREAD_MARGIN for item in known}


def _read_threads(reader, threads, failed, oldest):
    lost = {}
    for (channel, root), unit in list(threads.items()):
        if channel in failed or channel in lost:
            del threads[(channel, root)]
            continue
        try:
            items = reader.thread(channel, root, oldest.get((channel, root)))
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
        "mentions": sorted(set(USER_MENTION.findall(item.text))),
        "group_mentions": sorted(set(GROUP_MENTION.findall(item.text))),
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
    def __init__(self, reads, relay, window):
        self.reads = reads
        self.relay = relay
        self.window = window

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
        return [hit for hit in kept if _within(hit, start, self.window["to_ts"])], cut

    def conversation(self, channel, start=None):
        return _channel_read(self.reads, channel, _unit_window(self.window, start), {}, [])

    def thread(self, channel, root, oldest):
        arguments = {"channel_id": channel, "message_ts": root, "limit": RELAY_THREAD_PAGE_SIZE, "response_format": "detailed"}
        if oldest is not None:
            arguments["oldest"] = str(oldest)
        seen_ts = set()
        parse = lambda call_id, text: _unit_thread_page(channel, call_id, text, root, self.window["to_ts"], seen_ts)
        return _relay_pages(self.relay, THREAD_TOOL, arguments, parse)

    def participants(self, unit):
        return unit.participants

    def named(self, item):
        return item

    def reactions(self, channel, ts):
        _, text = self.relay.read(REACTIONS_TOOL, {"channel_id": channel, "message_ts": ts})
        return _relay_reactions(text)


def _relay_reactions(text):
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


def _unit_thread_page(channel, call_id, text, root, to, seen_ts):
    messages, info = _relay_body(THREAD_TOOL, call_id, channel, text, THREAD_PARENT)
    lines = LINE_BREAK.split(messages)
    items = [] if messages.strip() in NO_THREAD else [*_thread_replies(call_id, channel, root, lines, to, seen_ts), _thread_parent(channel, root, lines)]
    return items, _next_cursor(THREAD_TOOL, call_id, info, (NO_MORE, THREAD_NO_MORE))


def _thread_parent(channel, root, lines):
    marker = _replies_line(lines, root)
    end = marker[0] if marker else _no_replies_line(lines)
    kept, _ = _without_metadata(lines[PARENT_LINES : len(lines) if end is None else end])
    who = lines[1][len(FROM_OPEN) :] if lines[1].startswith(FROM_OPEN) else ""
    author, name, bot = _who_parts(who)
    return Item(channel, root, root, author, "\n".join(kept), name, bot)


class _ApiReader:
    def __init__(self, reads, http, calls, window, owner):
        self.reads = reads
        self.http = http
        self.calls = calls
        self.window = window
        self.owner = owner
        self.names = {}

    def search(self, search, start, cap):
        types = _search_types(search)
        params = {"query": _api_query(search, start, self.window), "sort": "timestamp", "sort_dir": "asc", "count": str(SEARCH_PAGE_SIZE)}
        found, cut = [], cap
        for page in range(1, cap + 1):
            self.calls.spend()
            body = self.http.get(SEARCH_PATH, {**params, "page": str(page)})
            found.extend(hit for hit in _api_search_page(search["name"], body) if types is None or hit.kind_type in types)
            pages = dig(body, "messages", "paging", "pages")
            if not _is_count(pages) or page >= pages:
                cut = None
                break
        return [hit for hit in found if _within(hit, start, self.window["to_ts"])], cut

    def conversation(self, channel, start=None):
        return _channel_read(self.reads, channel, _unit_window(self.window, start), {}, [])

    def thread(self, channel, root, oldest):
        to = self.window["to_ts"]
        params = {"channel": channel, "ts": root, "latest": str(to), "limit": str(API_PAGE_SIZE)}
        if oldest is not None:
            params["oldest"] = str(oldest)
        items = _api_pages(channel, REPLIES_PATH, params, self.http, self.calls)
        return [item for item in items if decimal.Decimal(item.ts) <= to]

    def participants(self, unit):
        self.calls.spend()
        if unit.kind == DM:
            others = _api_members(unit.channel, INFO_PATH, self.http.get(INFO_PATH, {"channel": unit.channel}))
            other = others[0] if others else ""
            members = [other, self.owner] if other and other != self.owner else [self.owner]
        else:
            members = _api_members(unit.channel, MEMBERS_PATH, self.http.get(MEMBERS_PATH, {"channel": unit.channel, "limit": str(API_PAGE_SIZE)}))
        return [(member, self._name_of(member)) for member in members]

    def reactions(self, channel, ts):
        self.calls.spend()
        return _api_reactions(channel, self.http.get(REACTIONS_PATH, {"channel": channel, "timestamp": ts, "full": "true"}))

    def named(self, item):
        return item if item.name or not item.author else item._replace(name=self._name_of(item.author))

    def _name_of(self, user):
        if user not in self.names:
            self.names[user] = self._lookup(user) if USER_ID.fullmatch(user) else ""
        return self.names[user]

    def _lookup(self, user):
        self.calls.spend()
        return _api_user_name(self.http.get(USERS_PATH, {"user": user}))


def _api_search_page(name, body):
    matches = dig(body, "messages", "matches")
    if dig(body, "ok") is not True or not isinstance(matches, list):
        raise SourceUnreadable(f"GET {SEARCH_PATH}: {name}: {_error_code(body)}")
    return [_api_hit(match) for match in matches]


def _api_members(channel, path, body):
    if dig(body, "ok") is not True:
        raise _api_failure(channel, body)
    if path == INFO_PATH:
        other = _string(dig(body, "channel", "user"))
        return [other] if other else []
    return [member for member in _common.as_list(dig(body, "members")) if isinstance(member, str)]


def _api_reactions(channel, body):
    if dig(body, "ok") is not True:
        if _error_code(body) == "message_not_found":
            raise ReactionsFailed("message_not_found")
        raise _api_failure(channel, body)
    found = _common.as_list(dig(body, "message", "reactions"))
    return {user for reaction in found for user in _common.as_list(dig(reaction, "users")) if isinstance(user, str)}


def _api_user_name(body):
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
