import decimal
import re
import urllib.parse

from state import clean_text

from . import _common, _slack_reads
from ._common import dig
from ._errors import CALL_CAP, PartialRead, SourceUnreadable
from ._slack_read import KEY_PART_CAP, LINE_BREAK, _Calls, _channel_read, _Pending, _stored_ts, _thread_key
from ._slack_reads import ApiReads, Freshness, RelayReads
from ._slack_search import _ApiReader, _RelayReader, _search_units

ROLE = "chat"
CREDENTIAL = "token"
STATIC_HEADERS = {}
STORE = True
NOT_LISTED = "channel not listed"
INVALID_ROOT = "invalid root ts"
LINKS_BASE = "https://slack.com"
ROOT_TS = re.compile(r"[0-9]{1,16}\.[0-9]{1,9}")

parse_read = _slack_reads.parse_read
to_rows = _slack_reads.to_rows
DAY_KINDS = _slack_reads.DAY_KINDS
day_row = _slack_reads.day_row


def api_client(provider, opener=None, environ=None, sleep=None):
    return _common.api_client(provider, (CREDENTIAL,), _auth, opener, environ, sleep)


def _auth(values):
    return {"Authorization": "Bearer " + values[CREDENTIAL]}


def fetch(source, window, cursor, entries, session):
    stored, calls = _stored(cursor), _Calls(source.get("call_cap", CALL_CAP))
    reads = ApiReads(session, session.http, calls, _freshness(source, window))
    cited, refused = _cited(source)
    channel_reads = [_channel_read(reads, channel, window, stored, cited[channel]) for channel in _channels(source)]
    found = _search_units(source, window, _ApiReader(reads, window, source["owner"])) if source.get("searches") else None
    return _result(source, window, stored, channel_reads, refused, found)


def _freshness(source, window):
    return Freshness(source.get("max_age"), window["to_ts"], source.get("closed_days", False))


def _channels(source):
    return source.get("channels") or []


def plan(source, window, cursor, entries, session, connector):
    try:
        _walk(source, window, _stored(cursor), session)
    except _Pending as pending:
        call = {"id": pending.call_id, "connector": connector, "tool": pending.tool, "arguments": pending.arguments, "digest": None}
        return {"done": False, "partial": None, "calls": [call]}
    except PartialRead as stop:
        return _common.ended(stop.why)
    except SourceUnreadable:
        return _common.ended(None)
    return _common.ended()


def parse(source, window, cursor, entries, session, digests):
    stored = _stored(cursor)
    try:
        reads, refused, found = _walk(source, window, stored, session)
    except _Pending as pending:
        raise SourceUnreadable(f"{pending.tool}: no response {pending.call_id}") from None
    return _result(source, window, stored, reads, refused, found)


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


def _refused_key(channel, root):
    return _thread_key(clean_text(channel, KEY_PART_CAP), clean_text(root, KEY_PART_CAP))


def _walk(source, window, stored, session):
    reads = RelayReads(session, _freshness(source, window))
    cited, refused = _cited(source)
    channel_reads = [_channel_read(reads, channel, window, stored, cited[channel]) for channel in _channels(source)]
    found = _search_units(source, window, _RelayReader(reads, window)) if source.get("searches") else None
    return channel_reads, refused, found


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
