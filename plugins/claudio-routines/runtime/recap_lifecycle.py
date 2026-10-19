import argparse
import copy
from collections import namedtuple
from datetime import datetime, timezone
from decimal import Decimal

import recap_features
import recap_state
import recap_window
import state
import tribe_state
from state import InputError, Nullable, Rejected

DEFAULT_LATE_AFTER = 3
DEFAULT_DROP_AFTER = 14
PROMISE_GRACE_DAYS = 1
SECONDS_PER_DAY = 86400
SCAN_CAP = 1000
SECTIONS = ("waiting", "good_to_know", "waiting_on_others", "handled")
SECTION_OF = {
    "waiting": "waiting",
    "promise": "waiting",
    "team_ask": "good_to_know",
    "announcement": "good_to_know",
    "waiting_on_others": "waiting_on_others",
    "handled": "handled",
}
STATUS_OF_KIND = {
    recap_features.WAITING_ON_YOU: "waiting",
    recap_features.PROMISE: "promise",
    recap_features.YOURE_WAITING_ON: "waiting_on_others",
    recap_features.TEAM_ASK: "team_ask",
    recap_features.ALREADY_HANDLED: "handled",
    recap_features.ANNOUNCEMENT: "announcement",
}
SETTLED_KINDS = (recap_features.ALREADY_HANDLED, recap_features.NOISE)
ASKED_STATUSES = ("waiting", "team_ask")
KINDS = tuple(recap_features.KIND_DEFINITIONS)
NO_PEOPLE = {"participants": [], "authors": []}

PEOPLE = [{"id": state.TEXT, "name": state.TEXT}]
FEATURES_SPEC = {
    "owner": state.TEXT,
    "units": {
        "*": {
            "kind": recap_state.UNIT_KIND,
            "channel": recap_state.NAME,
            "name": state.TEXT,
            "messages": [{"user": state.TEXT, "name": state.TEXT, "ts": recap_state.MESSAGE_TS, "root_ts": Nullable(state.TEXT)}],
            "facts": {"unanswered_from": Nullable(recap_state.MESSAGE_TS), "owner_answered": state.BOOLEAN},
        }
    },
    "blind_spots": [{"key": recap_state.BLIND_SPOT_KEY, "gap": state.LABEL}],
}
BASE_SPEC = {"units": {"*": {"participants": PEOPLE, "authors": PEOPLE}}}
DUE = state.leaf(lambda value: state.parses(state.parse_time, value), "an ISO 8601 time with a UTC offset")
JUDGMENT_SPEC = {
    "units": {
        "*": {
            "kind": recap_state.one_of(KINDS),
            "title": recap_state.TITLE,
            "summary": state.TEXT,
            "blocking": state.BOOLEAN,
            "due": Nullable(DUE),
        }
    },
    "reading": [{"text": state.TEXT, "cites": [state.TEXT]}],
}

History = namedtuple("History", "late_after drop_after")
Run = namedtuple("Run", "to_ts at zone history owner")


def load_features(path):
    document = tribe_state.load_input(path, "features", FEATURES_SPEC)
    for key, unit in document["units"].items():
        if not unit["messages"]:
            raise InputError(f"features: {state.join(recap_state.key_path('units', key), 'messages')}: expected at least one message")
    return document


def load_base(path):
    return tribe_state.load_input(path, "base", BASE_SPEC)


def check_judgment(document, features_doc):
    state.check(document, JUDGMENT_SPEC, "")
    for key in sorted(features_doc["units"]):
        if key not in document["units"]:
            raise Rejected(f"{recap_state.key_path('units', key)}: missing, every unit of the features needs one entry")
    for key in sorted(document["units"]):
        if key not in features_doc["units"]:
            raise Rejected(f"{recap_state.key_path('units', key)}: not a unit of the features")


def load_judgment(path, features_doc):
    try:
        return state.load(path, "judgment", lambda document: check_judgment(document, features_doc))
    except state.InvalidJson as error:
        raise Rejected(str(error)) from error


def check_window_order(previous, window):
    at = previous["run"]["at"]
    if at is not None and window["to_ts"] < state.parse_time(at).timestamp():
        raise Rejected(f"window: to_ts {window['to_ts']} is before the state run.at {at}")


def due_text(value):
    return state.utc_text(int(state.parse_time(value).timestamp()))


def days_since(moment, run):
    return recap_window.working_days_between(int(moment), run.to_ts, run.zone)


def late_age(status, facts, first_seen, due, run):
    if status == "waiting" and facts["unanswered_from"] is not None:
        age = days_since(Decimal(facts["unanswered_from"]), run)
        return age if age > run.history.late_after else None
    if status != "promise":
        return None
    if due is None:
        age = days_since(state.parse_time(first_seen).timestamp(), run)
        return age if age > PROMISE_GRACE_DAYS else None
    due_ts = state.parse_time(due).timestamp()
    return days_since(due_ts, run) if run.to_ts > due_ts else None


def status_of(kind, facts, stored):
    held = stored is not None and stored["status"] in recap_state.HELD_STATUSES
    if held and (kind in SETTLED_KINDS or facts["owner_answered"]):
        return "handled", True
    return STATUS_OF_KIND.get(kind), False


def label_of(text):
    return state.clean_text(text, SCAN_CAP).strip()[: recap_state.NAME_CAP].strip()


def channel_name(document, stored):
    label = label_of(document["name"])
    named = document["kind"] not in recap_state.DM_KINDS and label.lstrip("#").strip() != "" and label != document["channel"]
    if named:
        return label
    return None if stored is None else stored["channel_name"]


def display_name(user, messages, people):
    names = [item["name"] for item in reversed(messages) if item["user"] == user]
    names += [item["name"] for item in people["authors"] + people["participants"] if item["id"] == user]
    return next((name for name in names if name), "")


def as_person(user, name):
    label = label_of(name)
    if not recap_state.is_user_id(user) or not label:
        return None
    return {"id": user, "name": label}


def asker_of(document):
    stamp = document["facts"]["unanswered_from"]
    return next((item["user"] for item in document["messages"] if item["ts"] == stamp), None)


def counterpart_of(document, people, owner):
    if document["kind"] in recap_state.DM_KINDS:
        others = [item["id"] for item in people["participants"] if item["id"] != owner]
        if len(others) == 1:
            return others[0]
    return next((item["user"] for item in reversed(document["messages"]) if item["user"] != owner), None)


def person_of(status, document, people, owner, stored):
    if status in ASKED_STATUSES:
        who = asker_of(document)
    elif status == "waiting_on_others":
        who = counterpart_of(document, people, owner)
    else:
        who = None
    found = None if who is None else as_person(who, display_name(who, document["messages"], people))
    if found is not None:
        return found
    return None if stored is None else stored["person"]


def newest_ts(messages):
    return max((item["ts"] for item in messages), key=Decimal)


def unit_of(document, entry, stored, status, people, run):
    facts = document["facts"]
    first_seen = run.at if stored is None else stored["first_seen"]
    due = due_text(entry["due"]) if status == "promise" and entry["due"] is not None else None
    runs_waiting = (0 if stored is None else stored["runs_waiting"]) + 1
    return {
        "kind": document["kind"],
        "channel": document["channel"],
        "channel_name": channel_name(document, stored),
        "person": person_of(status, document, people, run.owner, stored),
        "title": entry["title"],
        "first_seen": first_seen,
        "last_ts": newest_ts(document["messages"]),
        "status": status,
        "runs_waiting": runs_waiting if status in recap_state.HELD_STATUSES else 0,
        "late": late_age(status, facts, first_seen, due, run),
        "due": due,
    }


def link_message(document):
    stamp = document["facts"]["unanswered_from"] or newest_ts(document["messages"])
    return next(item for item in document["messages"] if item["ts"] == stamp)


def line_of(key, unit, document, entry, resolved, is_new):
    message = link_message(document)
    return {
        "key": key,
        "kind": unit["kind"],
        "status": unit["status"],
        "channel": unit["channel"],
        "channel_name": unit["channel_name"],
        "ts": message["ts"],
        "root_ts": message["root_ts"] or None,
        "person": unit["person"],
        "title": unit["title"],
        "summary": entry["summary"],
        "blocking": entry["blocking"],
        "due": unit["due"],
        "late": unit["late"],
        "first_seen": unit["first_seen"],
        "unanswered_from": document["facts"]["unanswered_from"],
        "is_new": is_new,
        "resolved": resolved,
    }


def judge_unit(key, document, entry, stored, people, run):
    status, resolved = status_of(entry["kind"], document["facts"], stored)
    if status is None:
        return None, None
    unit = unit_of(document, entry, stored, status, people, run)
    already_handled = status == "handled" and stored is not None and stored["status"] == "handled"
    line = None if already_handled else line_of(key, unit, document, entry, resolved, stored is None)
    return unit, line


def stale_keys(units, run):
    cutoff = Decimal(run.to_ts) - run.history.drop_after * SECONDS_PER_DAY
    return sorted(key for key, unit in units.items() if Decimal(unit["last_ts"]) < cutoff)


def merge_units(previous, features_doc, judged, base, run):
    units, lines = copy.deepcopy(previous["units"]), {}
    for key in sorted(features_doc["units"]):
        unit, line = judge_unit(key, features_doc["units"][key], judged["units"][key], previous["units"].get(key), base["units"].get(key, NO_PEOPLE), run)
        if unit is None:
            units.pop(key, None)
        else:
            units[key] = unit
        if line is not None:
            lines[key] = line
    dropped = stale_keys(units, run)
    for key in dropped:
        del units[key]
        lines.pop(key, None)
    return units, lines, dropped


def next_blind_spots(previous, spots):
    runs = {spot["key"]: spot["runs"] for spot in previous}
    return [{"key": spot["key"], "gap": spot["gap"], "runs": runs.get(spot["key"], 0) + 1} for spot in spots]


def sections_of(lines):
    sections = {name: [] for name in SECTIONS}
    for key in sorted(lines):
        sections[SECTION_OF[lines[key]["status"]]].append(lines[key])
    return sections


def keys_of(sections, dropped):
    keys = {name: [line["key"] for line in sections[name]] for name in SECTIONS}
    shown = [line for name in SECTIONS if name != "handled" for line in sections[name]]
    keys["resolved"] = [line["key"] for line in sections["handled"] if line["resolved"]]
    keys["new"] = sorted(line["key"] for line in shown if line["is_new"])
    keys["late"] = [line["key"] for line in sections["waiting"] if line["late"] is not None]
    keys["dropped"] = dropped
    return keys


def span_of(window):
    return {"from_ts": window["from_ts"], "to_ts": window["to_ts"]}


def build_summary(previous, judged, window, run_at, sections, keys, spots):
    counts = {name: len(keys[name]) for name in ("waiting", "late", "new", "resolved", "waiting_on_others")}
    return {
        "digest": previous["digest"],
        "run_at": run_at,
        "window": span_of(window),
        "report_only": window["explicit"],
        "limited": window["limited"],
        **sections,
        "resolved": keys["resolved"],
        "reading": copy.deepcopy(judged["reading"]),
        "counts": counts,
        "blind_spots": spots,
        "post": counts["waiting"] > 0 or counts["new"] > 0 or counts["resolved"] > 0,
    }


def build_record(previous, window, run_at, keys, spots):
    return {
        "schema": state.RECORD_SCHEMA_VERSION,
        "digest": previous["digest"],
        "run_at": run_at,
        "window": {**span_of(window), "explicit": window["explicit"], "limited": window["limited"]},
        "counts": {name: len(items) for name, items in keys.items()},
        **keys,
        "blind_spots": [{"key": spot["key"], "runs": spot["runs"]} for spot in spots],
    }


def next_state_of(previous, units, spots, window, run_at):
    return {
        "schema": recap_state.SCHEMA_VERSION,
        "digest": previous["digest"],
        "run": {"at": run_at, "previous_at": previous["run"]["at"], "window": span_of(window)},
        "units": units,
        "blind_spots": spots,
    }


def apply(previous, features_doc, base, judged, window, now, zone, history):
    check_window_order(previous, window)
    run_at = state.utc_text(window["to_ts"])
    run = Run(int(now.timestamp()), state.utc_text(int(now.timestamp())), zone, history, features_doc["owner"])
    units, lines, dropped = merge_units(previous, features_doc, judged, base, run)
    spots = next_blind_spots(previous["blind_spots"], features_doc["blind_spots"])
    sections = sections_of(lines)
    keys = keys_of(sections, dropped)
    next_state = copy.deepcopy(previous) if window["explicit"] else next_state_of(previous, units, spots, window, run_at)
    return next_state, build_summary(previous, judged, window, run_at, sections, keys, spots), build_record(previous, window, run_at, keys, spots)


def whole_days(low):
    def parse(text):
        try:
            value = int(text)
        except ValueError:
            value = low - 1
        if not low <= value <= recap_window.MAX_LOOKBACK_WORKING_DAYS:
            raise argparse.ArgumentTypeError(f"expected an integer from {low} to {recap_window.MAX_LOOKBACK_WORKING_DAYS}, got {text}")
        return value

    return parse


def add_apply_arguments(parser):
    for flag in ("--state", "--features", "--base", "--judgment", "--window", "--tz", "--out", "--summary", "--record"):
        parser.add_argument(flag, required=True)
    parser.add_argument("--late-after-working-days", type=whole_days(0), default=DEFAULT_LATE_AFTER, help="working days an ask stays unanswered before it is late")
    parser.add_argument("--drop-after-days", type=whole_days(1), default=DEFAULT_DROP_AFTER, help="days without a message before a unit leaves the state")


def run_apply(args):
    zone = state.load_zone(args.tz)
    raw, previous = state.load_raw(args.state, "state", recap_state.check_state)
    features_doc = load_features(args.features)
    base = load_base(args.base)
    window = state.load(args.window, "window", recap_window.check_window)
    judged = load_judgment(args.judgment, features_doc)
    now = datetime.fromtimestamp(window["to_ts"], timezone.utc)
    history = History(args.late_after_working_days, args.drop_after_days)
    next_state, summary, record = apply(previous, features_doc, base, judged, window, now, zone, history)
    try:
        recap_state.check_state(next_state)
    except Rejected as error:
        raise Rejected(f"next state: {error}") from error
    written = raw if window["explicit"] else state.dump(next_state)
    state.write_all([(args.out, written), (args.record, state.dump(record)), (args.summary, state.dump(summary))])
    return 0
