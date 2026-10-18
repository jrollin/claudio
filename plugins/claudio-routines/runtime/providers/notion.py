import html
import html.entities
import re

from . import _common
from ._common import as_list, dig, json_object, quote, utc_text
from ._http import PAGE_CAP
from ._errors import PAGE_CAP_PARTIAL, PartialRead, SourceUnreadable

ROLE = "document_store"
CREDENTIAL = "token"
API_VERSION = "2026-03-11"
PAGES_PATH = "/v1/pages/"
BLOCKS_PATH = "/v1/blocks/"
PAGE_SIZE = 100
REQUEST_CAP = 50
REQUEST_CAP_PARTIAL = "request cap"
BLOCK_KINDS = {
    "heading_1": "heading",
    "heading_2": "heading",
    "heading_3": "heading",
    "heading_4": "heading",
    "paragraph": "paragraph",
    "quote": "paragraph",
    "bulleted_list_item": "list",
    "numbered_list_item": "list",
    "to_do": "list",
    "code": "code",
    "table": "table",
}
FETCH_TOOL = "notion-fetch"
CONTENT_OPEN = re.compile(r"^<content>", re.M)
CONTENT_CLOSE = "</content>"
PROPERTIES_CLOSE = re.compile(r"^</properties>\r?$", re.M)
FENCE = re.compile(r"`{3,}")
EQUATION_FENCE = "$$"
EQUATION = re.compile(r"\$\$.+\$\$")
IMAGE = re.compile(r"!\[[^\]\n]*\]\([^)\n]*\)")
LINE_BREAK = re.compile(r"\r\n|\r|\n")
HEADING = re.compile(r"#{1,4} (.*)")
LIST_ITEM = re.compile(r"(?:[-*] \[[ xX]\] |[-*] |[0-9]+\. )(.*)")
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
    return _result(_read_page(source["page_id"], _Budget(http)))


def plan(source, window, cursor, entries, responses, connector):
    call_id = _call_id(source)
    if call_id in responses:
        return _common.ended()
    arguments = {"id": source["page_id"]}
    call = {"id": call_id, "connector": connector, "tool": FETCH_TOOL, "arguments": arguments, "digest": None}
    return {"done": False, "partial": None, "calls": [call]}


def parse(source, window, cursor, entries, responses, digests):
    body = _response(responses, _call_id(source))
    unknown = body.get("unknown_block_count")
    if body.get("truncated") is True or (isinstance(unknown, int) and unknown > 0):
        raise PartialRead("page truncated")
    text = body.get("text")
    if not isinstance(text, str):
        raise SourceUnreadable(f"{FETCH_TOOL}: response without text")
    last_edited = utc_text(body.get("page_last_edited_at"))
    if last_edited is None:
        raise SourceUnreadable(f"{FETCH_TOOL}: response without a valid page_last_edited_at")
    title = body.get("title")
    return _result(
        {
            "id": source["page_id"],
            "title": title if isinstance(title, str) else "",
            "last_edited": last_edited,
            "blocks": _markdown_blocks(_content_lines(text)),
        }
    )


def _result(page):
    return {"records": {"pages": [page]}, "cursor": {"last_edited": page["last_edited"]}, "entries": {}}


def _call_id(source):
    return source["name"] + "-1"


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
    for pattern, kind in ((HEADING, "heading"), (LIST_ITEM, "list"), (QUOTE, "paragraph")):
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
        return {"type": "table", "text": "", "rows": _table_rows("\n".join(lines[index : end + 1]), index)}, end + 1
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


def _text_block(kind, text):
    return {"type": kind, "text": text, "rows": None}


def _other():
    return {"type": "other", "text": "", "rows": None}


def _read_page(page_id, http):
    path = PAGES_PATH + quote(page_id)
    body = http.get(path)
    last_edited = utc_text(dig(body, "last_edited_time"))
    if last_edited is None:
        raise SourceUnreadable(f"GET {path}: response without a valid last_edited_time")
    items = _children(page_id, http)
    return {
        "id": page_id,
        "title": _title(dig(body, "properties")),
        "last_edited": last_edited,
        "blocks": [_block(item, index, page_id, http) for index, item in enumerate(items)],
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


def _block(item, index, parent_id, http):
    block_type = dig(item, "type")
    kind = BLOCK_KINDS.get(block_type, "other") if isinstance(block_type, str) else "other"
    if kind == "table":
        return {"type": kind, "text": "", "rows": _rows(_table_id(item, index, parent_id), http)}
    if kind == "other":
        return {"type": kind, "text": "", "rows": None}
    return {"type": kind, "text": _text(dig(item, block_type, "rich_text")), "rows": None}


def _table_id(item, index, parent_id):
    table_id = dig(item, "id")
    if not isinstance(table_id, str) or not table_id:
        raise SourceUnreadable(f"GET {_children_path(parent_id)}: table block {index} without an id")
    return table_id


def _rows(table_id, http):
    rows = (dig(child, "table_row") for child in _children(table_id, http) if dig(child, "type") == "table_row")
    return [[_text(cell).strip() for cell in as_list(dig(row, "cells"))] for row in rows]


def _title(properties):
    values = properties.values() if isinstance(properties, dict) else []
    return next((_text(dig(value, "title")) for value in values if dig(value, "type") == "title"), "")


def _text(parts):
    return "".join(str(dig(part, "plain_text") or "") for part in as_list(parts))
