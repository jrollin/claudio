import datetime
import html
import html.entities
import re

from . import _common
from ._common import UTC, as_list, dig, json_object, quote, utc_text
from ._http import PAGE_CAP
from ._errors import PAGE_CAP_PARTIAL, PartialRead, SourceUnreadable

ROLE = "document_store"
CREDENTIAL = "token"
LINKS_BASE = "https://www.notion.so"
API_VERSION = "2026-03-11"
PAGES_PATH = "/v1/pages/"
BLOCKS_PATH = "/v1/blocks/"
SEARCH_PATH = "/v1/search"
SEARCH_BODY = {
    "filter": {"property": "object", "value": "page"},
    "sort": {"timestamp": "last_edited_time", "direction": "descending"},
    "page_size": 100,
}
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
EDITED_CAP = 10
PAGE_SIZE = 100
REQUEST_CAP = 50
REQUEST_CAP_PARTIAL = "request cap"
MAX_DEPTH = 4
BLOCK_KINDS = {
    "heading_1": "heading",
    "heading_2": "heading",
    "heading_3": "heading",
    "heading_4": "heading",
    "paragraph": "paragraph",
    "quote": "paragraph",
    "toggle": "paragraph",
    "callout": "paragraph",
    "synced_block": "container",
    "column_list": "container",
    "column": "container",
    "bulleted_list_item": "list",
    "numbered_list_item": "list",
    "to_do": "list",
    "code": "code",
    "table": "table",
}
FETCH_TOOL = "notion-fetch"
HTTP_NOT_FOUND = 404
HTTP_BAD_REQUEST = 400
DATABASE_TYPE = "database"
NOT_FOUND_CODE = "object_not_found"
MINUTE_CHARS = 16
READ = {"status": "ok", "reason": None}
UNCHANGED = {"status": "deferred", "reason": "unchanged"}
NOT_SHARED = {"status": "failed", "reason": "not found or not shared"}
NOT_A_PAGE = {"status": "failed", "reason": "not a page"}
FAILED_BY_STATUS = {HTTP_NOT_FOUND: NOT_SHARED, HTTP_BAD_REQUEST: NOT_A_PAGE}
PAGE_TRUNCATED = "page truncated"
TRUNCATED = {"status": "failed", "reason": f"partial: {PAGE_TRUNCATED}"}
CONTENT_OPEN = re.compile(r"^<content>", re.M)
CONTENT_CLOSE = "</content>"
PROPERTIES_CLOSE = re.compile(r"^</properties>\r?$", re.M)
FENCE = re.compile(r"`{3,}")
EQUATION_FENCE = "$$"
EQUATION = re.compile(r"\$\$.+\$\$")
IMAGE = re.compile(r"!\[[^\]\n]*\]\([^)\n]*\)")
LINE_BREAK = re.compile(r"\r\n|\r|\n")
HEADING = re.compile(r"#{1,4} (.*)")
LIST_ITEM = re.compile(r"(?:[-*] \[(?P<mark>[ xX])\] |[-*] |[0-9]+\. )(?P<text>.*)")
TICKED = "xX"
QUOTE = re.compile(r"> ?(.*)")
ATTRIBUTES = re.compile(r'\{(?:[\w-]+="[^"]*"\s*)+\}$')
OPEN_TAG = re.compile(r"<([A-Za-z][\w-]*)")
BLOCK_TAGS = frozenset(
    {
        "table",
        "details",
        "callout",
        "columns",
        "column",
        "page",
        "database",
        "synced_block",
        "table_of_contents",
        "empty-block",
        "audio",
        "video",
        "image",
        "file",
        "pdf",
        "embed",
        "bookmark",
        "equation",
    }
)
ROW = re.compile(r"<tr\b[^<>]*>(.*?)</tr>", re.S)
CELL = re.compile(r"<td\b[^<>]*>(.*?)</td>", re.S)
ROW_TAG = re.compile(r"<(/?)tr\b")
CELL_TAG = re.compile(r"<(/?)td\b")
BREAK_TAG = re.compile(r"<br\s*/?>", re.I)
TAG = re.compile(r"</?[A-Za-z][\w-]*(?:\s[^<>]*)?/?>")
INLINE = re.compile(
    r"`([^`]+)`|\\([!-/:-@\[-`{-~])|\[([^\[\]\n]*)\]\([^)\s\[]*\)|\*\*(.+?)\*\*|~~(.+?)~~|\*(?=\S)([^*\n]+?)(?<=\S)\*"
)
ENTITY = re.compile(r"&(?:#[0-9]+|#[xX][0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]*);")
EMPTY_BLOCK = "empty-block"
DIVIDER = "---"


def api_client(provider, opener=None, environ=None, sleep=None):
    return _common.api_client(provider, (CREDENTIAL,), _auth, opener, environ, sleep)


def _auth(values):
    return {"Authorization": "Bearer " + values[CREDENTIAL], "Notion-Version": API_VERSION}


class _Budget:
    def __init__(self, http):
        self.http = http
        self.left = REQUEST_CAP

    def get(self, path, params=None):
        if self.left == 0:
            raise PartialRead(REQUEST_CAP_PARTIAL)
        self.left -= 1
        return self.http.get(path, params)


def fetch(source, window, cursor, entries, http):
    budget = _Budget(http)
    if "edited_by" in source:
        return _fetch_listed_pages(source, _edited_page_ids(source, window, http), cursor, budget)
    if "pages" not in source:
        page = _read_page(source["page_id"], budget)
        return _result(source, [page], {}, {page["id"]: page["last_edited"]})
    return _fetch_listed_pages(source, source["pages"], cursor, budget)


def _fetch_listed_pages(source, page_ids, cursor, budget):
    stored = _stored(cursor)
    outcomes = [_fetch_listed(page_id, stored.get(page_id), budget) for page_id in page_ids]
    return _listed(source, page_ids, stored, outcomes)


def plan(source, window, cursor, entries, responses, connector):
    stored = _stored(cursor)
    for index, page_id in enumerate(_page_ids(source), 1):
        call_id = _call_id(source, index)
        if call_id not in responses:
            call = {"id": call_id, "connector": connector, "tool": FETCH_TOOL, "arguments": {"id": page_id}, "digest": None}
            return {"done": False, "partial": None, "calls": [call]}
        if "pages" in source and _source_unreadable(page_id, responses, call_id, stored.get(page_id)):
            break
    return _common.ended()


def _source_unreadable(page_id, responses, call_id, stored):
    try:
        _parse_listed(page_id, _response(responses, call_id), stored)
    except SourceUnreadable:
        return True
    return False


def parse(source, window, cursor, entries, responses, digests):
    page_ids = _page_ids(source)
    if "pages" not in source:
        page = _page_from_response(page_ids[0], _response(responses, _call_id(source, 1)))
        return _result(source, [page], {}, {page["id"]: page["last_edited"]})
    stored = _stored(cursor)
    outcomes = [
        _parse_listed(page_id, _response(responses, _call_id(source, index)), stored.get(page_id))
        for index, page_id in enumerate(page_ids, 1)
    ]
    return _listed(source, page_ids, stored, outcomes)


def _page_from_response(page_id, body):
    if _truncated(body):
        raise PartialRead(PAGE_TRUNCATED)
    text = body.get("text")
    if not isinstance(text, str):
        raise SourceUnreadable(f"{FETCH_TOOL}: response without text")
    last_edited = utc_text(body.get("page_last_edited_at"))
    if last_edited is None:
        raise SourceUnreadable(f"{FETCH_TOOL}: response without a valid page_last_edited_at")
    title = body.get("title")
    return {
        "id": page_id,
        "title": title if isinstance(title, str) else "",
        "last_edited": last_edited,
        "blocks": _markdown_blocks(_content_lines(text)),
    }


def _truncated(body):
    unknown = body.get("unknown_block_count")
    return body.get("truncated") is True or (isinstance(unknown, int) and unknown > 0)


def _page_ids(source):
    return source["pages"] if "pages" in source else [source["page_id"]]


def _stored(cursor):
    stored = dig(cursor, "pages")
    return stored if isinstance(stored, dict) else {}


def _same_minute(edited, stored):
    return edited is not None and stored is not None and edited[:MINUTE_CHARS] == stored[:MINUTE_CHARS]


def _fetch_listed(page_id, stored, http):
    try:
        body, last_edited = _metadata(page_id, http)
    except SourceUnreadable as error:
        if error.status not in FAILED_BY_STATUS:
            raise
        return dict(FAILED_BY_STATUS[error.status]), None
    if dig(body, "in_trash") is True or dig(body, "archived") is True:
        return dict(NOT_SHARED), None
    if _same_minute(last_edited, stored):
        return dict(UNCHANGED), None
    return dict(READ), _page(page_id, body, last_edited, http)


def _parse_listed(page_id, body, stored):
    if _not_found(body):
        return dict(NOT_SHARED), None
    if dig(body, "metadata", "type") == DATABASE_TYPE:
        return dict(NOT_A_PAGE), None
    if _same_minute(utc_text(body.get("page_last_edited_at")), stored):
        return dict(UNCHANGED), None
    if _truncated(body):
        return dict(TRUNCATED), None
    return dict(READ), _page_from_response(page_id, body)


def _not_found(body):
    reported = body.get("status") == HTTP_NOT_FOUND or body.get("code") == NOT_FOUND_CODE
    return reported and not isinstance(body.get("text"), str)


def _listed(source, page_ids, stored, outcomes):
    pages = [page for _, page in outcomes if page is not None]
    read = {page["id"]: page["last_edited"] for page in pages}
    kept = {page_id: read.get(page_id, stored.get(page_id)) for page_id in page_ids}
    entries = {page_id: entry for page_id, (entry, _) in zip(page_ids, outcomes)}
    return _result(source, pages, entries, {page_id: edited for page_id, edited in kept.items() if edited is not None})


def _edited_page_ids(source, window, http):
    start, end, cap = _utc(window["from_ts"]), _utc(window["to_ts"]), source.get("edited_cap", EDITED_CAP)
    page_ids = []
    for index, item in enumerate(_search_results(http)):
        edited = utc_text(dig(item, "last_edited_time"))
        if edited is None:
            raise SourceUnreadable(f"POST {SEARCH_PATH}: result {index} without a valid last_edited_time")
        if edited < start:
            break
        if edited <= end and dig(item, "last_edited_by", "id") == source["edited_by"]:
            page_ids.append(_result_id(item, index))
            if len(page_ids) == cap:
                break
    return page_ids


def _utc(ts):
    return datetime.datetime.fromtimestamp(ts, UTC).strftime(TIME_FORMAT)


def _result_id(item, index):
    page_id = dig(item, "id")
    if not isinstance(page_id, str) or not page_id:
        raise SourceUnreadable(f"POST {SEARCH_PATH}: result {index} without an id")
    return page_id


def _search_results(http):
    request = SEARCH_BODY
    for _ in range(PAGE_CAP):
        body = http.post(SEARCH_PATH, request)
        results = dig(body, "results")
        if not isinstance(results, list):
            raise SourceUnreadable(f"POST {SEARCH_PATH}: response without results")
        yield from results
        if dig(body, "has_more") is not True:
            return
        after = dig(body, "next_cursor")
        if not isinstance(after, str) or not after:
            raise PartialRead(f"POST {SEARCH_PATH}: has_more without next_cursor")
        request = {**SEARCH_BODY, "start_cursor": after}
    raise PartialRead(PAGE_CAP_PARTIAL)


def _result(source, pages, entries, cursor):
    records = [{**page, "link": _link(source, page["id"])} for page in pages]
    return {"records": {"pages": records}, "cursor": {"pages": cursor}, "entries": entries}


def _link(source, page_id):
    base = (dig(source, "provider_config", "links_base") or LINKS_BASE).rstrip("/")
    return f"{base}/{page_id.replace('-', '')}"


def _call_id(source, index):
    return f"{source['name']}-{index}"


def _response(responses, call_id):
    if call_id not in responses:
        raise SourceUnreadable(f"{FETCH_TOOL}: no response {call_id}")
    where = f"{FETCH_TOOL}: response {call_id}"
    return json_object(responses[call_id], f"{where} is not JSON", f"{where} is not a JSON object")


def _content_lines(text):
    properties = PROPERTIES_CLOSE.search(text)
    start = CONTENT_OPEN.search(text, properties.end() if properties else 0)
    end = text.rfind(CONTENT_CLOSE)
    if start is None or end < start.end():
        raise SourceUnreadable(f"{FETCH_TOOL}: response text without a <content> part")
    first, *rest = LINE_BREAK.split(text[start.end() : end])
    return [first, *rest] if first.strip() else rest


def _markdown_blocks(lines):
    blocks, index = [], 0
    while index < len(lines):
        block, index = _markdown_block(lines, index)
        if block is not None:
            blocks.append(block)
    return blocks


def _markdown_block(lines, index):
    line = lines[index]
    if not line.strip() or line[0].isspace():
        return None, index + 1
    fence = FENCE.match(line)
    if fence:
        end = _closing(lines, index, fence.group(), "code fence without its end")
        return _text_block("code", "\n".join(lines[index + 1 : end])), end + 1
    if line.rstrip() == EQUATION_FENCE:
        return _other(), _closing(lines, index, EQUATION_FENCE, "equation without its end") + 1
    tag = OPEN_TAG.match(line)
    if tag and tag.group(1) in BLOCK_TAGS:
        return _tag_block(lines, index, tag.group(1))
    if line.strip() == DIVIDER or EQUATION.fullmatch(line.rstrip()) or IMAGE.fullmatch(line.rstrip()):
        return _other(), index + 1
    item = LIST_ITEM.fullmatch(line)
    if item:
        mark = item.group("mark")
        return _text_block("list", _plain(_without_attributes(item.group("text"))), None if mark is None else mark in TICKED), index + 1
    for pattern, kind in ((HEADING, "heading"), (QUOTE, "paragraph")):
        marker = pattern.fullmatch(line)
        if marker:
            return _text_block(kind, _plain(_without_attributes(marker.group(1)))), index + 1
    return _text_block("paragraph", _plain(_without_attributes(line))), index + 1


def _without_attributes(text):
    attributes = ATTRIBUTES.search(text)
    return text[: attributes.start()].rstrip() if attributes else text


def _tag_block(lines, index, name):
    line, close = lines[index], f"</{name}>"
    one_line = line.rstrip().endswith("/>") or close in line
    end = index if one_line else _closing(lines, index, close, f"<{name}> without {close}")
    if name == "table":
        return {"type": "table", "text": "", "rows": _table_rows("\n".join(lines[index : end + 1]), index), "checked": None}, end + 1
    if name == EMPTY_BLOCK:
        return _text_block("paragraph", ""), end + 1
    return _other(), end + 1


def _closing(lines, index, close, problem):
    end = next((later for later in range(index + 1, len(lines)) if lines[later].rstrip() == close), None)
    if end is None:
        raise SourceUnreadable(f"{FETCH_TOOL}: {problem} at content line {index + 1}")
    return end


def _table_rows(markup, index):
    row_tags, cell_tags = ROW_TAG.findall(markup), CELL_TAG.findall(markup)
    if not (_paired(row_tags) and _paired(cell_tags)):
        raise _malformed_table(index)
    rows = [[_plain(cell).strip() for cell in CELL.findall(row)] for row in ROW.findall(markup)]
    if 2 * len(rows) != len(row_tags) or 2 * sum(map(len, rows)) != len(cell_tags):
        raise _malformed_table(index)
    return rows


def _paired(slashes):
    return slashes == ["", "/"] * (len(slashes) // 2)


def _malformed_table(index):
    return SourceUnreadable(f"{FETCH_TOOL}: malformed table at content line {index + 1}")


def _plain(markup):
    return ENTITY.sub(_entity, _inline(TAG.sub("", BREAK_TAG.sub("\n", markup))))


def _entity(match):
    entity = match.group()
    if entity.startswith("&#"):
        return html.unescape(entity)
    return html.entities.html5.get(entity[1:], entity)


def _inline(text):
    return INLINE.sub(_unwrap, text)


def _unwrap(match):
    code, escaped, *wrapped = match.groups()
    if code is not None:
        return code
    if escaped is not None:
        return escaped
    return _inline(next(part for part in wrapped if part is not None))


def _text_block(kind, text, checked=None):
    return {"type": kind, "text": text, "rows": None, "checked": checked}


def _other():
    return {"type": "other", "text": "", "rows": None, "checked": None}


def _read_page(page_id, http):
    body, last_edited = _metadata(page_id, http)
    return _page(page_id, body, last_edited, http)


def _metadata(page_id, http):
    path = PAGES_PATH + quote(page_id)
    body = http.get(path)
    last_edited = utc_text(dig(body, "last_edited_time"))
    if last_edited is None:
        raise SourceUnreadable(f"GET {path}: response without a valid last_edited_time")
    return body, last_edited


def _page(page_id, body, last_edited, http):
    return {
        "id": page_id,
        "title": _title(dig(body, "properties")),
        "last_edited": last_edited,
        "blocks": _blocks(page_id, 1, http),
    }


def _children_path(block_id):
    return BLOCKS_PATH + quote(block_id) + "/children"


def _children(block_id, http):
    path = _children_path(block_id)
    params = {"page_size": str(PAGE_SIZE)}
    results, page = [], params
    for _ in range(PAGE_CAP):
        body = http.get(path, page)
        page_results = dig(body, "results")
        if not isinstance(page_results, list):
            raise SourceUnreadable(f"GET {path}: response without results")
        results.extend(page_results)
        if dig(body, "has_more") is not True:
            return results
        after = dig(body, "next_cursor")
        if not isinstance(after, str) or not after:
            raise PartialRead(f"GET {path}: has_more without next_cursor")
        page = {**params, "start_cursor": after}
    raise PartialRead(PAGE_CAP_PARTIAL)


def _blocks(parent_id, level, http):
    records = []
    for index, item in enumerate(_children(parent_id, http)):
        records.extend(_records(item, index, parent_id, level, http))
    return records


def _records(item, index, parent_id, level, http):
    block_type = dig(item, "type")
    kind = BLOCK_KINDS.get(block_type, "other") if isinstance(block_type, str) else "other"
    if kind == "table":
        rows = _rows(_block_id(item, "id", block_type, index, parent_id), http)
        return [{"type": kind, "text": "", "rows": rows, "checked": None}]
    if kind == "other":
        return [_other()]
    nested = _nested(item, block_type, index, parent_id, level, http)
    if kind == "container":
        return nested
    checked = dig(item, block_type, "checked") is True if block_type == "to_do" else None
    return [_text_block(kind, _text(dig(item, block_type, "rich_text")), checked), *nested]


def _nested(item, block_type, index, parent_id, level, http):
    if level >= MAX_DEPTH:
        return []
    synced_from = dig(item, "synced_block", "synced_from") if block_type == "synced_block" else None
    if synced_from is not None:
        return _blocks(_block_id(synced_from, "block_id", block_type, index, parent_id), level + 1, http)
    if dig(item, "has_children") is not True:
        return []
    return _blocks(_block_id(item, "id", block_type, index, parent_id), level + 1, http)


def _block_id(source, key, block_type, index, parent_id):
    block_id = dig(source, key)
    if not isinstance(block_id, str) or not block_id:
        raise SourceUnreadable(f"GET {_children_path(parent_id)}: {block_type} block {index} without an id")
    return block_id


def _rows(table_id, http):
    rows = (dig(child, "table_row") for child in _children(table_id, http) if dig(child, "type") == "table_row")
    return [[_text(cell).strip() for cell in as_list(dig(row, "cells"))] for row in rows]


def _title(properties):
    values = properties.values() if isinstance(properties, dict) else []
    return next((_text(dig(value, "title")) for value in values if dig(value, "type") == "title"), "")


def _text(parts):
    return "".join(str(dig(part, "plain_text") or "") for part in as_list(parts))
