import decimal
import os

import evaluate
import recap_features
import recap_message
import recap_state
import roles
import state
import weekly_window
from config import adapter_role
from state import Rejected

SCHEMA_VERSION = 1
RECAP_SOURCE = "recap"
EXCERPT_CAP = 500
PULL_REQUEST_EXCERPTS = 10
MESSAGE_EXCERPTS = 15
PAGE_EXCERPT_CAP = 1000
CHAT_TITLE_CAP = 80
RECORD_SPEC = {"run_at": recap_state.UTC_TIME, "new": [state.TEXT], "resolved": [state.TEXT], "handled": [state.TEXT]}
COUNTED = ("new", "resolved", "handled")


def seconds(text, where):
    try:
        return int(state.parse_time(text).timestamp())
    except ValueError as error:
        raise Rejected(f"{where}: expected a UTC time, got {text!r}") from error


def stamp_seconds(stamp, where):
    if recap_state.SLACK_TS_TEXT.fullmatch(stamp) is None:
        raise Rejected(f"{where}: expected a message ts like 1791990730.002679, got {stamp!r}")
    return recap_message.stamp_seconds(stamp)


def in_window(window, moment):
    return window["from_ts"] <= moment <= window["to_ts"]


def make_item(source, role, kind, title, status, link, when, people=(), excerpts=()):
    return {
        "source": source,
        "role": role,
        "kind": kind,
        "title": title,
        "status": status,
        "link": link,
        "when": state.utc_text(when),
        "people": list(people),
        "excerpts": list(excerpts),
    }


def make_excerpt(by, moment, text, cap=EXCERPT_CAP):
    return {"by": by, "at": state.utc_text(moment), "text": text[:cap]}


def issue_items(name, records, window, items):
    for index, issue in enumerate(records["issues"]):
        when = seconds(issue["updated"], f"collection {name}: records.issues[{index}].updated")
        if in_window(window, when):
            items.setdefault(f"issue:{issue['key']}", make_item(name, "issue_tracker", "issue", issue["title"], issue["status"], issue["link"], when))


def activity_in_window(name, records, window):
    found = {}
    for index, entry in enumerate(records.get("activity", [])):
        moment = seconds(entry["at"], f"collection {name}: records.activity[{index}].at")
        if in_window(window, moment):
            found.setdefault((entry["repo"], entry["number"]), []).append((moment, entry))
    return {key: sorted(entries, key=lambda pair: pair[0], reverse=True) for key, entries in found.items()}


def pull_request_items(name, records, window, items):
    activity = activity_in_window(name, records, window)
    for index, request in enumerate(records["pull_requests"]):
        recent = activity.get((request["repo"], request["number"]), [])
        when = recent[0][0] if recent else seconds(request["updated_at"], f"collection {name}: records.pull_requests[{index}].updated_at")
        if in_window(window, when):
            excerpts = [make_excerpt(entry["author"], moment, entry["text"]) for moment, entry in recent[:PULL_REQUEST_EXCERPTS]]
            people = sorted({entry["author"] for _, entry in recent})
            key = f"pr:{request['repo']}#{request['number']}"
            items.setdefault(key, make_item(name, "code_host", "pull_request", request["title"], request["state"], request["link"], when, people, excerpts))


def page_items(name, records, window, items):
    for index, page in enumerate(records["pages"]):
        when = seconds(page["last_edited"], f"collection {name}: records.pages[{index}].last_edited")
        if in_window(window, when):
            text = "\n".join(block["text"] for block in page["blocks"] if block["text"])
            excerpts = [make_excerpt(None, when, text, PAGE_EXCERPT_CAP)] if text else []
            items.setdefault(f"page:{page['id']}", make_item(name, "document_store", "page", page["title"], None, page["link"], when, excerpts=excerpts))


def thread_root(key):
    found = recap_state.THREAD_KEY.fullmatch(key)
    return None if found is None else found.group(2)


def chat_link(host, channel, ts, root_ts):
    return recap_message.link_url({"channel": channel, "ts": ts, "root_ts": root_ts}, host)


def recap_unit_items(stored, window, routine, excluded, items):
    for key, unit in sorted(stored["units"].items()):
        last = stamp_seconds(unit["last_ts"], f"recap state: units.{key}.last_ts")
        first = seconds(unit["first_seen"], f"recap state: units.{key}.first_seen")
        if unit["channel"] in excluded or not (in_window(window, last) or in_window(window, first)):
            continue
        kind = "dm" if unit["kind"] in recap_state.DM_KINDS else "thread"
        people = [] if unit["person"] is None else [unit["person"]["name"]]
        link = chat_link(routine["workspace"], unit["channel"], unit["last_ts"], thread_root(key))
        items[f"chat:{key}"] = make_item(RECAP_SOURCE, "chat", kind, unit["title"], unit["status"], link, last if in_window(window, last) else first, people)


def recap_counts(records, window, excluded):
    inside = [record for record in records if in_window(window, seconds(record["run_at"], "recap record: run_at"))]
    return {name: len({key for record in inside for key in record[name] if recap_state.key_channel(key) not in excluded}) for name in COUNTED}


def direct_units(sources, collections, excluded):
    grouped = {}
    for name, source in sorted(sources.items()):
        collection = collections[name]
        if source["role"] != "chat" or collection is None:
            continue
        for record in collection["records"].get("units", []):
            if record["channel"] in excluded:
                continue
            conversation = record["name"] in recap_features.CONVERSATION_NAMES
            for index, message in enumerate(record["messages"]):
                moment = stamp_seconds(message["ts"], f"collection {name}: records.units messages[{index}].ts")
                root = None if conversation else message["root_ts"] or message["ts"]
                key = recap_state.dm_key(record["channel"]) if conversation else recap_state.thread_key(record["channel"], root)
                unit = grouped.setdefault(key, {"source": name, "channel": record["channel"], "root": root, "messages": {}})
                unit["messages"].setdefault(message["ts"], (moment, message))
    return grouped


def direct_chat_items(sources, collections, window, host, excluded, items):
    for key, unit in sorted(direct_units(sources, collections, excluded).items()):
        ordered = [(stamp, moment, message) for stamp, (moment, message) in sorted(unit["messages"].items(), key=lambda pair: decimal.Decimal(pair[0]))]
        inside = [row for row in reversed(ordered) if in_window(window, row[1])]
        if not inside:
            continue
        excerpts = [make_excerpt(message["name"], moment, message["text"]) for _, moment, message in inside[:MESSAGE_EXCERPTS]]
        item = items.get(f"chat:{key}")
        if item is not None:
            item["excerpts"] = excerpts
            continue
        newest_stamp, newest, _ = inside[0]
        title = " ".join(ordered[0][2]["text"].split())[:CHAT_TITLE_CAP]
        people = sorted({message["name"] for _, _, message in inside})
        link = chat_link(host, unit["channel"], newest_stamp, unit["root"])
        kind = "dm" if unit["root"] is None else "thread"
        items[f"chat:{key}"] = make_item(unit["source"], "chat", kind, title, None, link, newest, people, excerpts)


RECORD_ITEMS = {"issue_tracker": issue_items, "code_host": pull_request_items, "document_store": page_items}


def read_collection(directory, name, source, window):
    path = os.path.join(directory, f"{name}.json")
    if not os.path.exists(path):
        return None
    return state.load(path, f"collection {path}", lambda document: check_collection(document, name, source, window))


def check_collection(document, name, source, window):
    try:
        roles.validate_collection(document)
        evaluate.check_collection_source(document, name, source, document["place"], window)
    except ValueError as error:
        raise Rejected(str(error)) from error


def load_records(directory):
    folder = os.path.join(directory, "runs")
    try:
        names = sorted(name for name in os.listdir(folder) if name.endswith(".json"))
    except FileNotFoundError:
        return []
    except OSError as error:
        raise state.InputError(f"recap: cannot read {folder}: {error.strerror}") from error
    return [state.load(os.path.join(folder, name), "recap record", lambda document: state.check(document, RECORD_SPEC, "")) for name in names]


def source_rows(sources, collections):
    rows = []
    for name, source in sorted(sources.items()):
        collection = collections[name]
        read, reason = (False, evaluate.NO_COLLECTION) if collection is None else (collection["read"], collection["reason"])
        rows.append({"source": name, "role": source["role"], "read": read, "reason": reason})
    return rows


def compute(routine, sources, collections, window, recap):
    excluded = set(routine.get("exclude", {}).get("channels", []))
    items = {}
    counts = dict.fromkeys(COUNTED, 0)
    if recap is not None:
        stored, records = recap
        recap_unit_items(stored, window, routine, excluded, items)
        counts = recap_counts(records, window, excluded)
    direct_chat_items(sources, collections, window, routine["workspace"], excluded, items)
    for name, source in sorted(sources.items()):
        collection = collections[name]
        if collection is not None and source["role"] in RECORD_ITEMS:
            RECORD_ITEMS[source["role"]](name, collection["records"], window, items)
    return {
        "schema": SCHEMA_VERSION,
        "window": window,
        "week_start": window["week_start"],
        "items": items,
        "recap_counts": counts,
        "sources": source_rows(sources, collections),
    }


def load_routine(args, role_of):
    loaded = [evaluate.load_config(args.config, args.routine, place, role_of) for place in roles.PLACES]
    routine, sources = loaded[0][1], loaded[0][2]
    if routine.get("engine") != roles.WEEKLY_ENGINE:
        raise state.InputError(f"config: routine {args.routine} is not a weekly routine")
    return routine, sources


def load_recap(directory):
    if directory is None:
        return None
    return recap_state.load(os.path.join(directory, "state.json")), load_records(directory)


def run_features(args, role_of=adapter_role):
    routine, sources = load_routine(args, role_of)
    window = state.load(args.window, "window", weekly_window.check_window)
    collections = {name: read_collection(args.collections, name, source, window) for name, source in sources.items()}
    document = compute(routine, sources, collections, window, load_recap(args.recap))
    state.write_all([(args.out, state.dump(document))])
    return 0
