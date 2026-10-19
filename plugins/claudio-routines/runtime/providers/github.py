import datetime
import itertools
import json
import re
import urllib.parse

from . import _common
from ._common import UTC, dig, quote, utc_text
from ._http import PAGE_CAP
from ._errors import PAGE_CAP_PARTIAL, PartialRead, SourceUnreadable

ROLE = "code_host"
CREDENTIAL = "token"
MEDIA_TYPE = "application/vnd.github+json"
API_VERSION = "2022-11-28"
PER_PAGE = 100
ISSUES_DISABLED = 410
PULLS_TOOL = "list_pull_requests"
ISSUES_TOOL = "list_issues"
PULL_FIELDS = ("number", "title", "state", "draft", "html_url", "user", "created_at", "updated_at", "merged_at")
ISSUE_FIELDS = ("number", "title", "state", "user", "created_at", "updated_at")
LINK = re.compile(r'<([^<>]*)>\s*;\s*rel="([^"]*)"')
PUBLIC_LINKS = "https://github.com"


def api_client(provider, opener=None, environ=None, sleep=None):
    return _common.api_client(provider, (CREDENTIAL,), _auth, opener, environ, sleep)


def _auth(values):
    return {"Authorization": "Bearer " + values[CREDENTIAL], "Accept": MEDIA_TYPE, "X-GitHub-Api-Version": API_VERSION}


def fetch(source, window, cursor, entries, http):
    _check_query(source, "api")
    links, span = _links_base(source), _span(window, cursor)
    pulls, issues = [], []
    for repo in source["repos"]:
        try:
            pulls.extend(_api_pages(http, _repo_path(repo, "pulls"), _pull_params(), span, _pulls_of(repo)))
            issues.extend(_api_issues(http, repo, span, links))
        except SourceUnreadable as exc:
            if exc.status == 404:
                raise SourceUnreadable(f"repo {repo} not found: {exc}", exc.status) from None
            raise
    return _result(pulls, issues, cursor)


def plan(source, window, cursor, entries, responses, connector):
    try:
        pending, _, _ = _relay(source, window, cursor, responses)
    except PartialRead as exc:
        return _common.ended(exc.why)
    except SourceUnreadable:
        return _common.ended()
    if pending is None:
        return _common.ended()
    return {"done": False, "partial": None, "calls": [{**pending, "connector": connector, "digest": None}]}


def parse(source, window, cursor, entries, responses, digests):
    pending, pulls, issues = _relay(source, window, cursor, responses)
    if pending is not None:
        arguments = pending["arguments"]
        raise SourceUnreadable(f"{pending['tool']} {arguments['owner']}/{arguments['repo']} {pending['id']}: no saved response")
    return _result(pulls, issues, cursor)


def _check_query(source, transport):
    if source.get("query"):
        raise SourceUnreadable(f"query not supported by the {transport} transport")


def _links_base(source):
    config = source.get("provider_config") or {}
    if config.get("links_base"):
        return config["links_base"].rstrip("/")
    base_url = dig(config, "api", "base_url")
    if base_url:
        parts = urllib.parse.urlsplit(base_url)
        return f"{parts.scheme}://{parts.netloc.removeprefix('api.')}"
    return PUBLIC_LINKS


def _span(window, cursor):
    start = _iso(window["from_ts"])
    stored = utc_text(dig(cursor, "updated_at"))
    return max(start, stored) if stored is not None else start, _iso(window["to_ts"])


def _repo_path(repo, kind):
    owner, name = repo.split("/", 1)
    return f"/repos/{quote(owner)}/{quote(name)}/{kind}"


def _pull_params():
    return {"state": "all", "sort": "updated", "direction": "desc", "per_page": str(PER_PAGE), "page": "1"}


def _issue_params(span):
    return {"state": "all", "since": span[0], "sort": "updated", "direction": "desc", "per_page": str(PER_PAGE), "page": "1"}


def _pulls_of(repo):
    return lambda items, where: [_pull_record(repo, item, where) for item in items]


def _issues_of(repo, links):
    return lambda items, where: [_issue_record(repo, item, links, where) for item in items if not _is_pull(item)]


def _is_pull(item):
    return isinstance(item, dict) and "pull_request" in item


def _api_issues(http, repo, span, links):
    try:
        return _api_pages(http, _repo_path(repo, "issues"), _issue_params(span), span, _issues_of(repo, links))
    except SourceUnreadable as exc:
        if exc.status == ISSUES_DISABLED:
            return []
        raise


def _api_pages(http, path, params, span, records_of):
    kept, url = [], None
    for _ in range(PAGE_CAP):
        body = http.get(path, params) if url is None else http.get_url(url)
        if not isinstance(body, list):
            raise SourceUnreadable(f"GET {path}: response is not a list")
        records, ended = _in_window(records_of(body, f"GET {path}"), span)
        kept.extend(records)
        url = _next_link(http.response_headers)
        if ended or len(body) < PER_PAGE or url is None:
            return kept
    raise PartialRead(PAGE_CAP_PARTIAL)


def _next_link(headers):
    header = headers.get("Link") if headers is not None else None
    links = LINK.findall(header) if isinstance(header, str) else []
    return next((url for url, rel in links if "next" in rel.split()), None)


def _relay(source, window, cursor, responses):
    _check_query(source, "mcp")
    links, span = _links_base(source), _span(window, cursor)
    ids = (f"{source['name']}-{number}" for number in itertools.count(1))
    pulls, issues = [], []
    for repo in source["repos"]:
        pending = _relay_pulls(repo, span, ids, responses, pulls)
        if pending is None:
            pending = _relay_issues(repo, span, links, ids, responses, issues)
        if pending is not None:
            return pending, pulls, issues
    return None, pulls, issues


def _relay_pulls(repo, span, ids, responses, pulls):
    owner, name = repo.split("/", 1)
    for page in range(1, PAGE_CAP + 1):
        arguments = {"owner": owner, "repo": name, "state": "all", "sort": "updated", "direction": "desc"}
        call = _call(next(ids), PULLS_TOOL, {**arguments, "perPage": PER_PAGE, "page": page, "fields": list(PULL_FIELDS)})
        if call["id"] not in responses:
            return call
        where = f"{PULLS_TOOL} {repo} {call['id']}"
        items = _saved(responses[call["id"]], where)
        if not isinstance(items, list):
            raise SourceUnreadable(f"{where}: response is not a JSON array")
        records, ended = _in_window(_pulls_of(repo)(items, where), span)
        pulls.extend(records)
        if ended or len(items) < PER_PAGE:
            return None
    raise PartialRead(PAGE_CAP_PARTIAL)


def _relay_issues(repo, span, links, ids, responses, issues):
    owner, name = repo.split("/", 1)
    after, seen = None, set()
    for _ in range(PAGE_CAP):
        arguments = {"owner": owner, "repo": name, "since": span[0], "orderBy": "UPDATED_AT", "direction": "DESC"}
        arguments = {**arguments, "perPage": PER_PAGE, "fields": list(ISSUE_FIELDS), **({"after": after} if after else {})}
        call = _call(next(ids), ISSUES_TOOL, arguments)
        if call["id"] not in responses:
            return call
        where = f"{ISSUES_TOOL} {repo} {call['id']}"
        body = _saved(responses[call["id"]], where)
        items = dig(body, "issues")
        if not isinstance(items, list):
            raise SourceUnreadable(f"{where}: response without an issues list")
        records, ended = _in_window(_issues_of(repo, links)(items, where), span)
        issues.extend(records)
        if ended or not items or dig(body, "pageInfo", "hasNextPage") is not True:
            return None
        after = dig(body, "pageInfo", "endCursor")
        if not isinstance(after, str) or not after:
            raise SourceUnreadable(f"{where}: next page without an endCursor")
        if after in seen:
            raise PartialRead("cursor repeated")
        seen.add(after)
    raise PartialRead(PAGE_CAP_PARTIAL)


def _call(call_id, tool, arguments):
    return {"id": call_id, "tool": tool, "arguments": arguments}


def _saved(text, where):
    try:
        return json.loads(text)
    except ValueError:
        raise SourceUnreadable(f"{where}: response is not JSON") from None


def _in_window(records, span):
    start, end = span
    kept = [record for record in records if start <= record["updated_at"] <= end]
    return kept, any(record["updated_at"] < start for record in records)


def _pull_record(repo, item, where):
    return {
        "repo": repo,
        "number": _number(item, where),
        "title": _text(item, "title"),
        "author": _author(item),
        "state": _text(item, "state").lower(),
        "draft": dig(item, "draft") is True,
        "created_at": _time(item, "created_at", where),
        "updated_at": _time(item, "updated_at", where),
        "merged_at": None if dig(item, "merged_at") is None else _time(item, "merged_at", where),
        "link": _text(item, "html_url"),
    }


def _issue_record(repo, item, links, where):
    number = _number(item, where)
    return {
        "repo": repo,
        "number": number,
        "title": _text(item, "title"),
        "author": _author(item),
        "state": _text(item, "state").lower(),
        "created_at": _time(item, "created_at", where),
        "updated_at": _time(item, "updated_at", where),
        "link": f"{links}/{repo}/issues/{number}",
    }


def _number(item, where):
    number = dig(item, "number")
    if isinstance(number, bool) or not isinstance(number, int):
        raise SourceUnreadable(f"{where}: item without a valid number")
    return number


def _time(item, field, where):
    moment = utc_text(dig(item, field))
    if moment is None:
        raise SourceUnreadable(f"{where}: item without a valid {field}")
    return moment


def _text(item, field):
    value = dig(item, field)
    return value if isinstance(value, str) else ""


def _author(item):
    login = dig(item, "user", "login")
    return login if isinstance(login, str) else ""


def _result(pulls, issues, cursor):
    pull_records, issue_records = _unique(pulls), _unique(issues)
    newest = max((record["updated_at"] for record in pull_records + issue_records), default=utc_text(dig(cursor, "updated_at")))
    return {
        "records": {"pull_requests": pull_records, "issues": issue_records},
        "cursor": {"updated_at": newest},
        "entries": {},
    }


def _unique(records):
    first = {}
    for record in records:
        first.setdefault((record["repo"], record["number"]), record)
    return [first[key] for key in sorted(first)]


def _iso(ts):
    return _z(datetime.datetime.fromtimestamp(ts, UTC))


def _z(moment):
    return moment.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
