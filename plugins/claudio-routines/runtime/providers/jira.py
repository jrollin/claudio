import base64
import datetime
import itertools
import json

from . import _common
from ._common import UTC, dig
from ._http import PAGE_CAP
from ._errors import PAGE_CAP_PARTIAL, PartialRead, SourceUnreadable

ROLE = "issue_tracker"
CREDENTIALS = ("email", "token")
SEARCH_PATH = "/rest/api/3/search/jql"
SEARCH_TOOL = "searchJiraIssuesUsingJql"
FIELDS = ("summary", "issuetype", "status", "priority", "created", "updated")
PAGE_SIZE = 100
OVERLAP = 3600
QUERY_MARGIN = 86400
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
QUERY_TIME_FORMAT = "%Y-%m-%d %H:%M"
RESULT_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
REFUSALS = {400: "or its query rejected", 403: "not found or forbidden", 404: "not found or forbidden"}


class _Pending(Exception):
    def __init__(self, call):
        super().__init__(call["id"])
        self.call = call


def api_client(provider, opener=None, environ=None, sleep=None):
    return _common.api_client(provider, CREDENTIALS, _auth, opener, environ, sleep)


def _auth(values):
    pair = f"{values['email']}:{values['token']}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(pair).decode("ascii")}


def fetch(source, window, cursor, entries, http):
    site, bound = _site(source), _bound(window, cursor)
    updated, sprint = _read(source, bound, site, _api_load(http, source))
    return _result(updated, sprint, bound, cursor)


def plan(source, window, cursor, entries, responses, connector):
    try:
        _relay(source, window, cursor, responses)
    except _Pending as pending:
        return {"done": False, "partial": None, "calls": [{**pending.call, "connector": connector, "digest": None}]}
    except PartialRead as exc:
        return _common.ended(exc.why)
    except SourceUnreadable:
        return _common.ended()
    return _common.ended()


def parse(source, window, cursor, entries, responses, digests):
    try:
        updated, sprint, bound = _relay(source, window, cursor, responses)
    except _Pending as pending:
        raise SourceUnreadable(f"{SEARCH_TOOL} {pending.call['id']}: no saved response") from None
    return _result(updated, sprint, bound, cursor)


def _site(source):
    config = source.get("provider_config") or {}
    site = config.get("links_base") or dig(config, "api", "base_url")
    if not site:
        raise SourceUnreadable(f"links_base missing in providers.{source['provider']}")
    return site.rstrip("/")


def _bound(window, cursor):
    stored = _moment(dig(cursor, "updated"))
    return _common.read_start(window, None if stored is None else int(stored.timestamp()) - OVERLAP)


def _read(source, bound, site, load):
    updated = _pages(_updated_jql(source, bound), site, load)
    sprint = _pages(_sprint_jql(source), site, load) if source.get("open_sprints") is True else []
    return updated, sprint


def _updated_jql(source, bound):
    since = _clock(bound - QUERY_MARGIN).strftime(QUERY_TIME_FORMAT)
    clauses = [_selection(source)]
    query = (source.get("query") or "").strip()
    if query:
        clauses.append(f"({query})")
    return _ordered([*clauses, f'updated >= "{since}"'])


def _selection(source):
    jql = source.get("jql")
    return f"filter = {source['filter']}" if jql is None else f"({jql})"


def _origin(source):
    return "jql" if "jql" in source else f"filter {source['filter']}"


def _sprint_jql(source):
    return _ordered([f"filter = {source['filter']}", "sprint in openSprints()"])


def _ordered(clauses):
    return " AND ".join(clauses) + " ORDER BY key ASC"


def _search(jql, token):
    search = {"jql": jql, "fields": list(FIELDS), "maxResults": PAGE_SIZE}
    return search if token is None else {**search, "nextPageToken": token}


def _pages(jql, site, load):
    records, token = [], None
    for _ in range(PAGE_CAP):
        body, where = load(_search(jql, token))
        records.extend(_record(item, site, where) for item in _issues(body, where))
        token = _next_token(body, where)
        if token is None:
            return records
    raise PartialRead(PAGE_CAP_PARTIAL)


def _api_load(http, source):
    where = f"POST {SEARCH_PATH}"

    def load(search):
        try:
            return http.post(SEARCH_PATH, search), where
        except SourceUnreadable as exc:
            reason = REFUSALS.get(exc.status)
            if reason is None:
                raise
            raise SourceUnreadable(f"{_origin(source)} {reason}: {exc}", exc.status) from None

    return load


def _relay(source, window, cursor, responses):
    site, bound = _site(source), _bound(window, cursor)
    ids = (f"{source['name']}-{number}" for number in itertools.count(1))
    updated, sprint = _read(source, bound, site, _relay_load(source, site, ids, responses))
    return updated, sprint, bound


def _relay_load(source, site, ids, responses):
    def load(search):
        call = {"id": next(ids), "tool": SEARCH_TOOL, "arguments": {"cloudId": site, **search, "view": "full"}}
        if call["id"] not in responses:
            raise _Pending(call)
        where = f"{SEARCH_TOOL} {call['id']}"
        return _data(responses[call["id"]], where, _origin(source)), where

    return load


def _data(text, where, origin):
    try:
        document = json.loads(text)
    except ValueError:
        raise SourceUnreadable(f"{where}: response is not JSON") from None
    data = dig(document, "data")
    if isinstance(data, dict):
        return data
    error = dig(document, "error")
    if isinstance(error, str):
        raise SourceUnreadable(f"{SEARCH_TOOL}: {origin} not read: connector error")
    raise SourceUnreadable(f"{where}: response without data")


def _issues(body, where):
    items = dig(body, "issues")
    if not isinstance(items, list):
        raise SourceUnreadable(f"{where}: response without an issues list")
    return items


def _next_token(body, where):
    if dig(body, "isLast") is True:
        return None
    token = dig(body, "nextPageToken")
    if not isinstance(token, str) or not token:
        raise SourceUnreadable(f"{where}: next page without a nextPageToken")
    return token


def _record(item, site, where):
    key = dig(item, "key")
    if not isinstance(key, str) or not key:
        raise SourceUnreadable(f"{where}: issue without a valid key")
    return {
        "key": key,
        "title": _string(item, "summary") or "",
        "type": _string(item, "issuetype", "name") or "",
        "status": _string(item, "status", "name") or "",
        "priority": _string(item, "priority", "name"),
        "created": _time(item, "created", key, where),
        "updated": _time(item, "updated", key, where),
        "link": f"{site}/browse/{key}",
        "in_open_sprint": False,
    }


def _string(item, *path):
    value = dig(item, "fields", *path)
    return value if isinstance(value, str) else None


def _time(item, field, key, where):
    moment = _stamp(dig(item, "fields", field))
    if moment is None:
        raise SourceUnreadable(f"{where}: issue {key} without a valid {field}")
    return moment


def _moment(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.strptime(_common.FRACTION.sub("", value, count=1), TIME_FORMAT).astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def _stamp(value):
    moment = _moment(value)
    return None if moment is None else moment.strftime(RESULT_TIME_FORMAT)


def _clock(ts):
    return datetime.datetime.fromtimestamp(ts, UTC)


def _result(updated, sprint, bound, cursor):
    start = _clock(bound).strftime(RESULT_TIME_FORMAT)
    kept = [record for record in updated if record["updated"] >= start]
    in_sprint = {record["key"] for record in sprint}
    newest = _newest((*kept, *sprint))
    issues = [{**newest[key], "in_open_sprint": key in in_sprint} for key in sorted(newest)]
    stored = _stamp(dig(cursor, "updated"))
    latest = max(filter(None, (stored, *(record["updated"] for record in kept))), default=None)
    return {"records": {"issues": issues}, "cursor": {"updated": latest}, "entries": {}}


def _newest(records):
    by_key = {}
    for record in records:
        known = by_key.get(record["key"])
        if known is None or record["updated"] > known["updated"]:
            by_key[record["key"]] = record
    return by_key
