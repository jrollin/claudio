from datetime import date, timedelta

import evaluate
import features
import roles
import state
import tribe_page
import tribe_state
from config import adapter_role

TEXT_CAP = 4000
RECENT_DAYS = 7
MONTH_DAYS = 30
METRIC_PREFIX = "metric:"
TREND_PREFIX = "trend:"
RECORD_PREFIX = "record:"
PREVIOUS_OPTION = ("page_from_state", "previous_page")
PREVIOUS_UNREADABLE = "previous digest unreadable"
PREVIOUS_SOURCE = "previous-digest"
NO_TREND = "no trend"
EDIT_SECTIONS = ("Warnings", "What to check")
TREND_NAMES = ("max_7d", "mean_7d", "max_span", "mean_span", "growth_monthly")


class TribeReading(features.Reading):
    def doc(self, key, kind, entry, engine_source, title, link, values, **extra):
        source = entry["source"] if entry else engine_source
        return super().doc(key, kind, entry, source, title, link, values, **extra)

    def monitor_doc(self, key, entry, name, monitor):
        return {**super().monitor_doc(key, entry, name, monitor), "source": name}


def cleaned(text, cap=TEXT_CAP):
    return state.clean_text(text, cap)


def document(kind, source, link, title, values, text=None):
    doc = {"kind": kind, "source": source, "link": link, "title": title, "values": values}
    if text is not None:
        doc["text"] = text
    return doc


def block_lines(blocks):
    lines = []
    for block in blocks:
        if block["type"] == "table":
            lines += [" | ".join(row) for row in block["rows"]]
        elif block["type"] != "other":
            lines.append(block["text"])
    return lines


def message_records(name, collection):
    docs = {}
    for message in collection["records"]["messages"]:
        channel, stamp = features.title_of(message["channel"]), features.title_of(message["ts"])
        thread = features.title_of(message["thread_ts"] or message["ts"])
        values = {"channel": channel, "ts": stamp, "thread": thread, "reply": thread != stamp}
        docs[f"{RECORD_PREFIX}{name}:{channel}:{stamp}"] = document(
            "record", name, message["link"], features.title_of(message["text"]), values, cleaned(message["text"])
        )
    return docs


def issue_records(name, collection):
    docs = {}
    for issue in collection["records"]["issues"]:
        values = {field: features.title_of(issue[field]) for field in ("key", "type", "status")}
        values["priority"] = None if issue["priority"] is None else features.title_of(issue["priority"])
        values.update({"updated": issue["updated"], "in_open_sprint": issue["in_open_sprint"]})
        docs[f"{RECORD_PREFIX}{name}:{values['key']}"] = document(
            "record", name, issue["link"], features.title_of(issue["title"]), values, cleaned(issue["title"])
        )
    return docs


def page_records(name, collection, skipped):
    docs = {}
    for page in collection["records"]["pages"]:
        if same_page(page["id"], skipped):
            continue
        docs[f"{RECORD_PREFIX}{name}:{features.title_of(page['id'])}"] = document(
            "record", name, page["link"], features.title_of(page["title"]), {"last_edited": page["last_edited"]}, cleaned("\n".join(block_lines(page["blocks"])))
        )
    return docs


RECORDS = {"chat": message_records, "issue_tracker": issue_records}


def same_page(page_id, other):
    return other is not None and tribe_state.page_key(page_id) == tribe_state.page_key(other)


def is_previous(source):
    return source.get(PREVIOUS_OPTION[0]) == PREVIOUS_OPTION[1]


def previous_source(sources):
    return next((name for name, source in sources.items() if is_previous(source)), None)


def record_documents(sources, collections, previous_id):
    docs = {}
    for name, source in sources.items():
        collection = collections[name]
        if not collection["read"] or is_previous(source):
            continue
        if source["role"] == "document_store":
            docs.update(page_records(name, collection, previous_id))
        elif source["role"] in RECORDS:
            docs.update(RECORDS[source["role"]](name, collection))
    return docs


def authors_of(sources, collections):
    ids = {
        message["author"]
        for name, source in sources.items()
        if source["role"] == "chat" and collections[name]["read"]
        for message in collections[name]["records"]["messages"]
    }
    return sorted(ids)


def mean(values):
    return sum(values) / len(values) if values else None


def span_halves(points, to_day, span):
    start = to_day - timedelta(days=span - 1)
    first = [value for day, value in points if 0 <= (day - start).days < span / 2]
    second = [value for day, value in points if span / 2 <= (day - start).days < span]
    return first, second


def growth_monthly(points, to_day, span):
    first, second = span_halves(points, to_day, span)
    if len(first) < 2 or len(second) < 2 or mean(first) <= 0 or mean(second) < 0:
        return None
    try:
        return ((mean(second) / mean(first)) ** (MONTH_DAYS / (span / 2)) - 1) * 100
    except OverflowError:
        return None


def trend_values(trend, value, to_day, span):
    values = dict.fromkeys(TREND_NAMES)
    values["value"] = value
    if not trend:
        return values
    points = [(date.fromisoformat(point["day"]), point["value"]) for point in trend]
    recent = [item for day, item in points if to_day - timedelta(days=RECENT_DAYS - 1) <= day <= to_day]
    every = [item for _, item in points]
    values.update(
        {
            "max_7d": max(recent, default=None),
            "mean_7d": mean(recent),
            "max_span": max(every),
            "mean_span": mean(every),
            "growth_monthly": growth_monthly(points, to_day, span),
        }
    )
    return values


def empty_trend_values(value):
    return {**dict.fromkeys(TREND_NAMES, 0), "value": value, "growth_monthly": None}


def trend_documents(reading, collections, to_day):
    docs, gaps = {}, []
    for entry in reading.pack:
        if "trend_days" not in entry or reading.gate(entry["key"], entry["source"], "metrics").status != features.OBSERVED:
            continue
        record = next((item for item in collections[entry["source"]]["records"]["metrics"] if item["key"] == entry["key"]), None)
        if record is None:
            continue
        trend = record.get("trend")
        window = reading.keys.get(entry["key"])
        value = window["values"]["value"] if window else None
        empty = not trend and features.reads_empty_as_zero(entry) and record.get("trend_reason") == features.NO_DATAPOINTS
        values = empty_trend_values(value) if empty else trend_values(trend, value, to_day, entry["trend_days"])
        docs[TREND_PREFIX + entry["key"]] = document("trend", entry["source"], entry["link"], entry["title"], values)
        if not trend and not empty:
            gaps.append((TREND_PREFIX + entry["key"], features.label(record.get("trend_reason") or NO_TREND)))
    return docs, gaps


def window_documents(reading):
    docs = {}
    for key, doc in reading.keys.items():
        name = key if doc["kind"] == "monitor" else METRIC_PREFIX + key
        docs[name] = document("monitor" if doc["kind"] == "monitor" else "metric", doc["source"], doc["link"], doc["title"], doc["values"])
    return docs


def todo_line(block, checks):
    body = block["text"].rstrip()
    head, _, key = body.rpartition(" ")
    if not head or tribe_state.KEY.fullmatch(key) is None:
        text = body
    else:
        topic = checks[key]["topic"] if key in checks else None
        if topic is not None and head.startswith(topic + " "):
            head = f"{tribe_page.gray_bg(topic)} {head[len(topic) + 1:]}"
        text = f"{head} {tribe_page.gray(key)}"
    return f"- [{'x' if block['checked'] else ' '}] {text}"


def table_lines(rows):
    lines = ['<table header-row="true">']
    for row in rows:
        lines.append("<tr>")
        for index, text in enumerate(row):
            segments = text.split("\n")
            if index == 0 and segments[-1].startswith("key: "):
                segments[-1] = tribe_page.gray(segments[-1])
            lines.append(f"<td>{'<br>'.join(segments)}</td>")
        lines.append("</tr>")
    return [*lines, "</table>"]


def page_markdown(blocks, checks):
    lines, position = [], 0
    for block in blocks:
        if block["type"] == "heading":
            is_section = position < len(tribe_page.H2) and block["text"] == tribe_page.H2[position]
            position += is_section
            lines.append(("## " if is_section else "### ") + block["text"])
        elif block["type"] == "table":
            lines += table_lines(block["rows"])
        elif block["type"] == "list" and block.get("checked") is not None:
            lines.append(todo_line(block, checks))
    return "\n".join(lines), tribe_page.H2[:position]


def empty_edits(page_id, edited_at=None):
    return {"page_id": page_id, "edited_at": edited_at, "after_written": False, "statuses": {}, "ticked": [], "unticked": [], "ignored": []}


def previous_edits(sources, collections, stored):
    previous = stored["run"]["previous_page"]
    if previous is None:
        return empty_edits(None), None
    name = previous_source(sources)
    collection = collections.get(name) if name else None
    if collection is not None and collection["read"]:
        for page in collection["records"]["pages"]:
            if same_page(page["id"], previous["id"]):
                text, sections = page_markdown(page["blocks"], stored["checks"])
                edits = tribe_page.parse_edits(text, stored, previous["written_at"], page["last_edited"], previous["id"])
                if edits["after_written"] and not set(EDIT_SECTIONS) <= set(sections):
                    return empty_edits(previous["id"]), (name, PREVIOUS_UNREADABLE)
                return edits, None
        entry = next((item for key, item in collection["entries"].items() if same_page(key, previous["id"])), None)
        if entry is not None and entry["status"] == "deferred":
            return empty_edits(previous["id"]), None
    return empty_edits(previous["id"]), (name or PREVIOUS_SOURCE, PREVIOUS_UNREADABLE)


def failed_entries(sources, collections):
    return [
        (key, features.label(entry["reason"]))
        for name, source in sources.items()
        if source["role"] != "observability" and collections[name]["read"] and not is_previous(source)
        for key, entry in sorted(collections[name]["entries"].items())
        if entry["status"] == "failed"
    ]


def entry_read(reading, collections, feature):
    if feature.startswith(RECORD_PREFIX):
        return collections.get(feature.split(":")[1], {}).get("read", False)
    prefix = next((item for item in (METRIC_PREFIX, TREND_PREFIX) if feature.startswith(item)), "")
    name = feature[len(prefix) :]
    if not prefix and not feature.startswith(state.MONITOR_PREFIX):
        return True
    if name not in reading.statuses:
        tops = [entry["key"] for entry in reading.top_entries() if name.startswith(entry["key"] + "-")]
        if tops:
            name = tops[0]
        elif not prefix:
            return reading.kinds_read["monitors"]
    return reading.statuses.get(name) == features.OBSERVED


def holds_unread(warning, reading, collections):
    if warning["metric"] is not None and reading.statuses.get(warning["metric"]) != features.OBSERVED:
        return True
    for cite in warning["cites"]:
        if "link" in cite and not collections.get(cite["source"], {}).get("read", False):
            return True
        if "feature" in cite and not entry_read(reading, collections, cite["feature"]):
            return True
    return False


def deferred_warnings(stored, reading, collections):
    return sorted(key for key, warning in stored["warnings"].items() if holds_unread(warning, reading, collections))


def source_rows(sources, collections, window):
    rows = []
    for name, source in sources.items():
        collection = collections[name]
        read = collection["read"]
        rows.append(
            {
                "source": name,
                "role": source["role"],
                "read": read,
                "reason": collection["reason"],
                "from_ts": window["from_ts"] if read else None,
                "to_ts": window["to_ts"] if read else None,
            }
        )
    return rows


def other_cursors(sources, collections):
    return {
        name: collections[name]["cursor"]
        for name, source in sources.items()
        if source["role"] != "observability" and collections[name]["read"] and not is_previous(source) and collections[name]["cursor"] is not None
    }


def blind_spots(reading, sources, collections, extra):
    skipped = {previous_source(sources)} if previous_source(sources) else set()
    gaps = list(reading.gaps)
    gaps += [gap for gap in reading.source_gaps() if gap[0] not in skipped]
    gaps += extra
    found = {}
    for key, gap in gaps:
        found.setdefault(key, gap)
    return [{"key": key, "gap": found[key]} for key in sorted(found)]


def compute(routine, sources, collections, stored, window, zone):
    shim = {"items": {}, "cursors": stored["cursors"], "run": stored["run"], "blind_spots": stored["blind_spots"]}
    reading = TribeReading({**routine, "query_pack": routine.get("query_pack", [])}, sources, collections, shim, window, zone)
    reading.read_all()
    previous = stored["run"]["previous_page"]
    edits, previous_gap = previous_edits(sources, collections, stored)
    trends, trend_gaps = trend_documents(reading, collections, state.local_date(window["to_ts"], zone))
    keys = {
        **record_documents(sources, collections, previous["id"] if previous else None),
        **window_documents(reading),
        **trends,
    }
    deferred = deferred_warnings(stored, reading, collections)
    features_doc = {
        "keys": keys,
        "previous": {"warnings": stored["warnings"], "checks": stored["checks"], "retired": stored["retired"]},
        "edits": edits,
        "deferred": deferred,
        "authors": authors_of(sources, collections),
        "pack": [entry["key"] for entry in reading.pack],
    }
    extra = trend_gaps + failed_entries(sources, collections) + ([previous_gap] if previous_gap else [])
    base = {
        "sources": source_rows(sources, collections, window),
        "cursors": {"observability": reading.cursors(shim), **other_cursors(sources, collections)},
        "blind_spots": blind_spots(reading, sources, collections, extra),
        "blind_spots_retried": reading.retried(shim),
        "deferred": deferred,
        "daily_metrics_on": reading.daily_metrics_on(shim),
        "models": routine.get("models", {}),
    }
    rules = {"routine": list(routine.get("rules", [])), "entries": {entry["key"]: entry["rule"] for entry in reading.pack}}
    return features.rounded(features_doc), base, rules


def load_inputs(args, role_of):
    config, routine, sources = evaluate.load_config(args.config, args.routine, args.place, role_of)
    if routine.get("engine", roles.DEFAULT_ENGINE) != "tribe":
        raise state.InputError(f"config: routine {args.routine} is not a tribe routine")
    evaluate.check_pack({**routine, "query_pack": routine.get("query_pack", [])}, sources, args.routine, args.config)
    zone = evaluate.config_zone(config)
    stored = state.load(args.state, "state", tribe_state.check_state)
    window = state.load(args.window, "window", evaluate.check_window)
    collections = {
        name: evaluate.read_collection(args.collections, name, source, args.place, window) for name, source in sources.items()
    }
    return routine, sources, collections, stored, window, zone


def run_features(args, role_of=adapter_role):
    routine, sources, collections, stored, window, zone = load_inputs(args, role_of)
    features_doc, base, rules = compute(routine, sources, collections, stored, window, zone)
    state.write_all(
        [
            (args.out, features.compact_dump(features_doc)),
            (args.base_out, state.dump(base)),
            (args.rules_out, features.compact_dump(rules)),
        ]
    )
    return 0
