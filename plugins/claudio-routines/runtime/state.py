import argparse
import json
import math
import os
import re
import sys
import tempfile
import unicodedata
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA_VERSION = 2
RECORD_SCHEMA_VERSION = 1
SOURCES = ("monitors", "metrics")
SEVERITY = ("Low", "Medium", "High")
URGENCY = ("watch", "within months", "now")
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
HOUR = 3600
BASELINE_SECONDS = 3 * HOUR
CAP_SECONDS = 72 * HOUR
RESOLVE_RUNS = 2
CHANGES = ("new", "escalated", "resolved")
ESCALATION_RATIO = 1.5
KNOWN_GAP_RUNS = 3
BLIND_SPOT_CAP = 8
PLACES = ("cloud", "local")
TRANSPORTS = ("api", "mcp")
MONITOR_PREFIX = "monitor-"
MESSAGE_PART_CAP = 4000
BLOCK_BREAK = "\n\n"
LABEL_CAP = 300
MITIGATION_CAP = 3
REASON_TAGS = ("measured", "inferred")
BARRED_CATEGORIES = ("Cc", "Cf", "Cs", "Zl", "Zp")
MENTION = re.compile(r"[@<>]")
TRACKED_MONITOR = re.compile(re.escape(MONITOR_PREFIX) + "[0-9]+")


class InputError(Exception):
    pass


class InvalidJson(InputError):
    pass


class Rejected(Exception):
    pass


class Nullable:
    def __init__(self, spec):
        self.spec = spec


class Omittable:
    def __init__(self, spec):
        self.spec = spec


def is_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return isinstance(value, int) or math.isfinite(value)


def is_integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def parse_time(text):
    if not isinstance(text, str):
        raise ValueError(f"expected a string, got {type(text).__name__}")
    moment = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    if moment.tzinfo is None:
        raise ValueError(f"{text} has no UTC offset")
    return moment


def is_barred(character):
    return unicodedata.category(character) in BARRED_CATEGORIES


def has_barred(text):
    return any(is_barred(character) for character in text)


def blank_controls(text):
    return "".join(" " if is_barred(character) else character for character in text)


def clean_text(value, cap):
    return MENTION.sub(" ", blank_controls(unicodedata.normalize("NFKC", value)))[:cap]


def is_label(value):
    return isinstance(value, str) and len(value) <= LABEL_CAP and not has_barred(value)


def is_tracked_monitor(key):
    return TRACKED_MONITOR.fullmatch(key) is not None


def parses(parser, value):
    try:
        parser(value)
    except (TypeError, ValueError):
        return False
    return True


def leaf(test, expected):
    def check_leaf(value, path):
        if not test(value):
            raise Rejected(f"expected {expected} at {path}")
    return check_leaf


PRESENT = leaf(lambda value: True, "a value")
NUMBER_OR_NULL = leaf(lambda value: value is None or is_number(value), "a finite number or null")
INTEGER = leaf(is_integer, "an integer")
COUNT = leaf(lambda value: is_integer(value) and value >= 0, "a non-negative integer")
BOOLEAN = leaf(lambda value: isinstance(value, bool), "a boolean")
TEXT = leaf(lambda value: isinstance(value, str), "a string")
SCHEMA = leaf(lambda value: is_integer(value) and value == SCHEMA_VERSION, f"schema {SCHEMA_VERSION}")
SEVERITY_LEVEL = leaf(lambda value: value in SEVERITY, "one of " + ", ".join(SEVERITY))
URGENCY_LEVEL = leaf(lambda value: value in URGENCY, "one of " + ", ".join(URGENCY))
TIME_OR_NULL = leaf(lambda value: value is None or parses(parse_time, value), "a UTC time like 2026-01-31T08:00:00Z or null")
DATE = leaf(lambda value: isinstance(value, str) and parses(date.fromisoformat, value), "a date like 2026-01-31")
PLACE = leaf(lambda value: value in PLACES, "one of " + ", ".join(PLACES))
TRANSPORT = leaf(lambda value: value in TRANSPORTS, "one of " + ", ".join(TRANSPORTS))
LABEL = leaf(is_label, f"a string of at most {LABEL_CAP} characters without control characters")
RANK = leaf(lambda value: is_integer(value) and value > 0, "a positive integer")
REASON_TAG = leaf(lambda value: value in REASON_TAGS, "one of " + ", ".join(REASON_TAGS))
MUTES_SPEC = [{"key": TEXT, "until": DATE}]


def check_mitigation(value, path):
    if not isinstance(value, list) or not 1 <= len(value) <= MITIGATION_CAP:
        raise Rejected(f"expected a list of 1 to {MITIGATION_CAP} labels at {path}")
    check(value, [LABEL], path)


ANALYSIS_SPEC = {
    "risk": Omittable(LABEL),
    "reason": Omittable([{"tag": REASON_TAG, "claim": LABEL}]),
    "mitigation": Omittable(check_mitigation),
    "action": Omittable(LABEL),
}
OPTIONAL_FIELDS = tuple(ANALYSIS_SPEC)

ITEM_SPEC = {
    "title": LABEL,
    "topic": PRESENT,
    "severity": SEVERITY_LEVEL,
    "when": URGENCY_LEVEL,
    "status": PRESENT,
    "confidence": PRESENT,
    "since": PRESENT,
    "runs_under_threshold": INTEGER,
    "last_value": PRESENT,
    "link": LABEL,
    **ANALYSIS_SPEC,
}
STATE_SPEC = {
    "schema": SCHEMA,
    "digest": PRESENT,
    "run": {
        "at": TIME_OR_NULL,
        "previous_at": PRESENT,
        "sources_last_edited": PRESENT,
        "window": Nullable({"from_ts": PRESENT, "to_ts": PRESENT}),
        "daily_metrics_on": PRESENT,
        "models": PRESENT,
        "posted": PRESENT,
        "mutes": Omittable(MUTES_SPEC),
    },
    "cursors": {"observability": {"events_ts_ms": NUMBER_OR_NULL, "monitors": PRESENT, "metrics": PRESENT}},
    "items": {"*": ITEM_SPEC},
    "resolved_queries": PRESENT,
    "blind_spots": [{"key": TEXT, "gap": LABEL, "runs": INTEGER}],
}
SOURCE_SPEC = {"read": BOOLEAN}
OBSERVATION_SPEC = {
    "source": TEXT,
    "over": BOOLEAN,
    "value": NUMBER_OR_NULL,
    "severity": SEVERITY_LEVEL,
    "when": URGENCY_LEVEL,
    "title": LABEL,
    "link": LABEL,
    "last_value": PRESENT,
    "rank": Omittable(Nullable(RANK)),
    **ANALYSIS_SPEC,
}
SKIPPED_SPEC = [{"transport": TRANSPORT, "missing": [TEXT]}]
SOURCES_SPEC = [{"source": TEXT, "role": TEXT, "provider": TEXT, "transport": Nullable(TRANSPORT), "skipped": SKIPPED_SPEC}]
RUN_CONTEXT_SPEC = {
    "place": PLACE,
    "runtime": Nullable(TEXT),
    "config": Nullable(TEXT),
    "config_dirty": Nullable(BOOLEAN),
    "collected": {
        "*": {
            "role": TEXT,
            "transport": TRANSPORT,
            "skipped": Omittable(SKIPPED_SPEC),
            "read": BOOLEAN,
            "reason": Nullable(TEXT),
            "reads": Omittable({"fetched": COUNT, "reused": COUNT}),
        }
    },
}
RUN_CONTEXT_FIELDS = tuple(RUN_CONTEXT_SPEC)
FACTS_SPEC = {
    "sources": {source: SOURCE_SPEC for source in SOURCES},
    "observations": {"*": OBSERVATION_SPEC},
    "cursors": {"events_ts_ms": NUMBER_OR_NULL, "monitors": PRESENT, "metrics": PRESENT},
    "blind_spots": [{"key": TEXT, "gap": LABEL}],
    "blind_spots_retried": [TEXT],
    "mutes": MUTES_SPEC,
    "deferred": Omittable([TEXT]),
    "overrides": Omittable([TEXT]),
    "sources_last_edited": PRESENT,
    "daily_metrics_on": PRESENT,
    "resolved_queries": PRESENT,
    "models": PRESENT,
    "run_context": Omittable(RUN_CONTEXT_SPEC),
}
WINDOW_SPEC = {"from_ts": INTEGER, "to_ts": INTEGER, "cut": PRESENT, "explicit": BOOLEAN}


def join(path, key):
    return f"{path}.{key}" if path else str(key)


def check(value, spec, path):
    if isinstance(spec, Omittable):
        spec = spec.spec
    if isinstance(spec, Nullable):
        if value is None:
            return
        spec = spec.spec
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            raise Rejected(f"expected an object at {path or '<root>'}")
        for key, sub in spec.items():
            if key == "*":
                for name, child in value.items():
                    check(child, sub, join(path, name))
            elif key not in value:
                if not isinstance(sub, Omittable):
                    raise Rejected(f"missing key {join(path, key)}")
            else:
                check(value[key], sub, join(path, key))
    elif isinstance(spec, list):
        if not isinstance(value, list):
            raise Rejected(f"expected a list at {path}")
        for index, child in enumerate(value):
            check(child, spec[0], f"{path}[{index}]")
    else:
        spec(value, path)


def check_sources(document):
    check(document, SOURCES_SPEC, "")


def check_state(document):
    check(document, STATE_SPEC, "")
    for key, item in document["items"].items():
        if "opened_value" in item:
            NUMBER_OR_NULL(item["opened_value"], f"items.{key}.opened_value")


def key_source(key):
    return "monitors" if key.startswith(MONITOR_PREFIX) else "metrics"


def check_facts(document):
    check(document, FACTS_SPEC, "")
    for key, observation in document["observations"].items():
        if observation["source"] != key_source(key):
            raise Rejected(f"expected source {key_source(key)} at observations.{key}.source")
    for key in document.get("deferred", []):
        if key in document["observations"]:
            raise Rejected(f"observations.{key} is observed while the key is listed in deferred")
    for index, key in enumerate(document.get("overrides", [])):
        if key not in document["observations"]:
            raise Rejected(f"overrides[{index}] names {key}, which is not in observations")
        LABEL(document["observations"][key]["last_value"], f"observations.{key}.last_value")


def check_window(document):
    check(document, WINDOW_SPEC, "")
    if document["from_ts"] > document["to_ts"]:
        raise Rejected(f"from_ts {document['from_ts']} is after to_ts {document['to_ts']}")


def load_raw(path, label, checker):
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as error:
        raise InputError(f"{label}: cannot read {path}: {error.strerror}") from error
    try:
        document = json.loads(raw.decode("utf-8"))
    except ValueError as error:
        raise InvalidJson(f"{label}: invalid JSON in {path}: {error}") from error
    try:
        checker(document)
    except Rejected as error:
        raise Rejected(f"{label}: {error}") from error
    return raw, document


def load(path, label, checker):
    return load_raw(path, label, checker)[1]


def dump(document):
    return (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def stage(path, data):
    handle, temp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
    except OSError:
        os.unlink(temp)
        raise
    return temp


def message_pieces(body, cap):
    for block in body.split(BLOCK_BREAK):
        if len(block) <= cap:
            yield BLOCK_BREAK, block
            continue
        for line_index, line in enumerate(block.split("\n")):
            chunks = [line[start : start + cap] for start in range(0, len(line), cap)] or [""]
            for chunk_index, chunk in enumerate(chunks):
                yield (BLOCK_BREAK if line_index == 0 else "\n") if chunk_index == 0 else "", chunk


def message_parts(text, cap=None):
    cap = MESSAGE_PART_CAP if cap is None else cap
    body = text.rstrip("\n")
    if len(body) <= cap:
        return [text]
    parts, current = [], None
    for separator, piece in message_pieces(body, cap):
        joined = piece if current is None else current + separator + piece
        if len(joined) <= cap:
            current = joined
        else:
            parts.append(current)
            current = piece
    parts.append(current)
    return [part + "\n" for part in parts]


def part_path(path, number):
    root, extension = os.path.splitext(path)
    return f"{root}.{number}{extension}"


def message_files(path, text, cap=None):
    parts = message_parts(text, cap)
    return [(path if number == 1 else part_path(path, number), part.encode("utf-8")) for number, part in enumerate(parts, 1)]


def write_all(documents):
    staged = []
    try:
        for path, data in documents:
            staged.append((path, stage(path, data)))
        while staged:
            path, temp = staged[-1]
            os.replace(temp, path)
            staged.pop()
    except OSError as error:
        for _, temp in staged:
            os.unlink(temp)
        raise InputError(f"cannot write {path}: {error.strerror}") from error


def load_zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise InputError(f"--tz: unknown time zone {name}") from error


def load_time(text, flag):
    try:
        return parse_time(text)
    except ValueError as error:
        raise InputError(f"{flag}: expected an ISO 8601 time with a UTC offset, got {text}") from error


def local_date(timestamp, zone):
    return datetime.fromtimestamp(timestamp, zone).date()


def utc_text(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bucket_label(timestamp, zone):
    local = datetime.fromtimestamp(timestamp, zone)
    offset_minutes = int(local.utcoffset().total_seconds()) // 60
    sign = "+" if offset_minutes >= 0 else "-"
    hours, minutes = divmod(abs(offset_minutes), 60)
    return f"{DAYS[local.weekday()]} {local:%H:%M}{sign}{hours:02d}:{minutes:02d}"


def hour_starts(from_ts, to_ts, zone):
    local = datetime.fromtimestamp(from_ts, zone)
    return range(from_ts - local.minute * 60 - local.second, to_ts, HOUR)


def hour_buckets(from_ts, to_ts, zone):
    return [bucket_label(hour, zone) for hour in hour_starts(from_ts, to_ts, zone)]


def previous_run_ts(state, now):
    previous = state["run"]["at"]
    if previous is None:
        return None
    previous_moment = parse_time(previous)
    if now < previous_moment:
        raise Rejected(f"time: --now {now.isoformat()} is before the previous run.at {previous}")
    return int(previous_moment.timestamp())


def window_start(previous_ts, to_ts, since, now):
    if since is not None:
        if since > now:
            raise Rejected(f"time: --since {since.isoformat()} is after --now {now.isoformat()}")
        return int(since.timestamp()), None
    if previous_ts is None:
        return to_ts - BASELINE_SECONDS, None
    if to_ts - previous_ts > CAP_SECONDS:
        return to_ts - CAP_SECONDS, {"from_ts": previous_ts, "to_ts": to_ts - CAP_SECONDS}
    return previous_ts, None


def compute_window(state, now, zone, since=None, report_only=False):
    to_ts = int(now.timestamp())
    previous_ts = previous_run_ts(state, now)
    from_ts, cut = window_start(previous_ts, to_ts, since, now)
    return {
        "from_ts": from_ts,
        "to_ts": to_ts,
        "buckets": hour_buckets(from_ts, to_ts, zone),
        "cut": cut,
        "explicit": since is not None or report_only,
        "retry_known_gaps": previous_ts is None or local_date(previous_ts, zone) != local_date(to_ts, zone),
    }


def moved_up(item, observation):
    return (
        SEVERITY.index(observation["severity"]) > SEVERITY.index(item["severity"])
        or URGENCY.index(observation["when"]) > URGENCY.index(item["when"])
    )


def value_jumped(opened_value, value):
    if not (is_number(opened_value) and is_number(value)) or opened_value <= 0:
        return False
    return value > ESCALATION_RATIO * opened_value


def pick_present(source, names):
    return {name: source[name] for name in names if name in source}


def observed_fields(observation):
    fields = {name: observation[name] for name in ("title", "severity", "when", "link", "last_value")}
    fields.update(pick_present(observation, ("confidence",) + OPTIONAL_FIELDS))
    return fields


def open_item(observation, source, run_at):
    item = {
        "title": observation["title"],
        "topic": source,
        "severity": observation["severity"],
        "when": observation["when"],
        "status": "open",
        "confidence": observation.get("confidence"),
        "since": run_at,
        "opened_value": observation["value"],
        "runs_under_threshold": 0,
        "last_value": observation["last_value"],
        "link": observation["link"],
    }
    item.update(pick_present(observation, OPTIONAL_FIELDS))
    return item


def still_over(item, observation):
    escalated = moved_up(item, observation) or value_jumped(item.get("opened_value"), observation["value"])
    updated = dict(item, runs_under_threshold=0, **observed_fields(observation))
    if escalated or updated.get("opened_value") is None:
        updated["opened_value"] = observation["value"]
    return ("escalated" if escalated else "open"), updated


def under(item, observation):
    updated = dict(item, runs_under_threshold=item["runs_under_threshold"] + 1, last_value=observation["last_value"])
    if updated["runs_under_threshold"] >= RESOLVE_RUNS:
        return "resolved", updated
    return "open", updated


def hold(item):
    return ("open", item) if item is not None else (None, None)


def next_item(key, item, observation, sources, run_at, deferred):
    source = key_source(key)
    if key in deferred:
        return hold(item)
    if not sources[source]["read"]:
        if item is None and observation is not None and observation["over"]:
            raise Rejected(f"facts: observations.{key} is over threshold while source {source} was not read")
        return hold(item)
    if observation is None:
        raise Rejected(f"facts: missing key observations.{key}, tracked in state while source {source} was read")
    if observation["over"]:
        if item is None:
            return "new", open_item(observation, source, run_at)
        return still_over(item, observation)
    if item is None:
        return None, None
    return under(item, observation)


def summary_entry(key, item, rank):
    entry = {"key": key, "rank": rank}
    entry.update({name: item[name] for name in ("title", "severity", "when", "link", "last_value")})
    entry.update(pick_present(item, OPTIONAL_FIELDS))
    return entry


def apply_items(previous, facts, run_at):
    observations = facts["observations"]
    deferred = set(facts.get("deferred", []))
    items = {}
    outcomes = []
    for key in sorted(set(previous) | set(observations)):
        outcome, item = next_item(key, previous.get(key), observations.get(key), facts["sources"], run_at, deferred)
        if outcome is None:
            continue
        if outcome != "resolved":
            items[key] = item
        outcomes.append((key, outcome, item))
    return items, outcomes


def muted_change_keys(outcomes, muted):
    return [key for key, outcome, _ in outcomes if outcome in CHANGES and key in muted]


def rank_order(entry):
    return entry["rank"] is None, entry["rank"] or 0, entry["key"]


def summary_lists(outcomes, muted, observations):
    changes = {name: [] for name in CHANGES}
    still_open = {level: [] for level in reversed(SEVERITY)}
    for key, outcome, item in outcomes:
        if key in muted:
            continue
        if outcome in changes:
            changes[outcome].append(summary_entry(key, item, observations[key].get("rank")))
        else:
            still_open[item["severity"]].append({"key": key, "title": item["title"]})
    for name in ("new", "escalated"):
        changes[name].sort(key=rank_order)
    return changes, still_open


def is_known(spot):
    return spot["runs"] >= KNOWN_GAP_RUNS


def apply_blind_spots(previous, facts):
    before = {spot["key"]: spot for spot in previous}
    retried = set(facts["blind_spots_retried"])
    spots = []
    seen = set()
    for gap in facts["blind_spots"]:
        if gap["key"] in seen:
            continue
        seen.add(gap["key"])
        prior = before.get(gap["key"])
        spots.append({"key": gap["key"], "gap": gap["gap"], "runs": prior["runs"] + 1 if prior else 1})
    for spot in previous:
        if spot["key"] not in seen and is_known(spot) and spot["key"] not in retried:
            seen.add(spot["key"])
            spots.append(spot)
    spots.sort(key=lambda spot: not is_known(spot))
    return spots[:BLIND_SPOT_CAP], max(0, len(spots) - BLIND_SPOT_CAP)


def check_cursor_order(stored, fresh):
    old, new = stored["events_ts_ms"], fresh["events_ts_ms"]
    if new is not None and old is not None and new < old:
        raise Rejected(f"facts: cursors.events_ts_ms {new} is older than the stored cursors.observability.events_ts_ms {old}")


def next_cursors(stored, fresh, sources):
    cursors = dict(fresh)
    for source in SOURCES:
        if not sources[source]["read"]:
            cursors[source] = stored[source]
    if fresh["events_ts_ms"] is None:
        cursors["events_ts_ms"] = stored["events_ts_ms"]
    return cursors


def summary_overrides(facts, muted):
    observations = facts["observations"]
    return [
        {"key": key, "title": observations[key]["title"], "state": observations[key]["last_value"]}
        for key in sorted(set(facts.get("overrides", [])) - muted)
    ]


def build_summary(changes, still_open, tracked, muted_changes, blind_spots, dropped, cut, overrides):
    summary = dict(changes)
    summary.update({
        "still_open": still_open,
        "counts": {
            "new": len(changes["new"]),
            "escalated": len(changes["escalated"]),
            "resolved": len(changes["resolved"]),
            "still_open": sum(len(entries) for entries in still_open.values()),
            "tracked": tracked,
        },
        "muted_changes": muted_changes,
        "blind_spots": blind_spots,
        "blind_spots_dropped": dropped,
        "overrides": overrides,
        "cut": cut,
        "post": any(changes.values()),
    })
    return summary


def build_record(digest, window, outcomes, muted_keys, tracked, blind_spots, dropped, facts):
    keys = {name: [key for key, outcome, _ in outcomes if outcome == name] for name in CHANGES + ("open",)}
    counts = {name: len(keys[name]) for name in CHANGES}
    counts.update({"still_open": len(keys["open"]), "tracked": tracked, "muted_changes": len(muted_keys)})
    record = {
        "schema": RECORD_SCHEMA_VERSION,
        "digest": digest,
        "run_at": utc_text(window["to_ts"]),
        "window": {name: window[name] for name in ("from_ts", "to_ts", "explicit", "cut")},
        "counts": counts,
        "muted": muted_keys,
        "blind_spots": [{"key": spot["key"], "runs": spot["runs"]} for spot in blind_spots],
        "blind_spots_dropped": dropped,
        "sources_read": [source for source in SOURCES if facts["sources"][source]["read"]],
    }
    record.update({name: keys[name] for name in CHANGES})
    record.update(pick_present(facts, ("overrides",)))
    record.update(pick_present(facts.get("run_context", {}), RUN_CONTEXT_FIELDS))
    return record


def apply_run(state, facts, window, zone):
    previous_at = state["run"]["at"]
    if previous_at is not None and window["to_ts"] < parse_time(previous_at).timestamp():
        raise Rejected(f"window: to_ts {window['to_ts']} is before the state run.at {previous_at}")
    if not window["explicit"]:
        check_cursor_order(state["cursors"]["observability"], facts["cursors"])
    run_at = utc_text(window["to_ts"])
    end_date = local_date(window["to_ts"], zone)
    muted = {mute["key"] for mute in facts["mutes"] if date.fromisoformat(mute["until"]) > end_date}
    items, outcomes = apply_items(state["items"], facts, run_at)
    changes, still_open = summary_lists(outcomes, muted, facts["observations"])
    muted_keys = muted_change_keys(outcomes, muted)
    blind_spots, dropped = apply_blind_spots(state["blind_spots"], facts)
    next_state = {
        "schema": SCHEMA_VERSION,
        "digest": state["digest"],
        "run": {
            "at": run_at,
            "previous_at": previous_at,
            "sources_last_edited": facts["sources_last_edited"],
            "window": {"from_ts": window["from_ts"], "to_ts": window["to_ts"]},
            "daily_metrics_on": facts["daily_metrics_on"],
            "models": facts["models"],
            "posted": False,
            "mutes": facts["mutes"],
        },
        "cursors": {
            "observability": next_cursors(state["cursors"]["observability"], facts["cursors"], facts["sources"]),
        },
        "items": items,
        "resolved_queries": facts["resolved_queries"],
        "blind_spots": blind_spots,
    }
    overrides = summary_overrides(facts, muted)
    summary = build_summary(changes, still_open, len(items), len(muted_keys), blind_spots, dropped, window["cut"], overrides)
    record = build_record(state["digest"], window, outcomes, muted_keys, len(items), blind_spots, dropped, facts)
    return next_state, summary, record


def run_window(args):
    zone = load_zone(args.tz)
    now = load_time(args.now, "--now")
    since = None if args.since is None else load_time(args.since, "--since")
    state = load(args.state, "state", check_state)
    write_all([(args.out, dump(compute_window(state, now, zone, since, args.report_only)))])
    return 0


def run_apply(args):
    zone = load_zone(args.tz)
    raw_state, state = load_raw(args.state, "state", check_state)
    facts = load(args.facts, "facts", check_facts)
    window = load(args.window, "window", check_window)
    next_state, summary, record = apply_run(state, facts, window, zone)
    state_data = raw_state if window["explicit"] else dump(next_state)
    write_all([(args.out, state_data), (args.record, dump(record)), (args.summary, dump(summary))])
    return 0


def initial_state(digest):
    return {
        "schema": SCHEMA_VERSION,
        "digest": digest,
        "run": {
            "at": None,
            "previous_at": None,
            "sources_last_edited": None,
            "window": None,
            "daily_metrics_on": None,
            "models": {},
            "posted": False,
            "mutes": [],
        },
        "cursors": {"observability": {"events_ts_ms": None, "monitors": {}, "metrics": {}}},
        "items": {},
        "resolved_queries": {},
        "blind_spots": [],
    }


def run_init(args):
    write_all([(args.out, dump(initial_state(args.digest)))])
    return 0


def run_validate(args):
    if args.state is not None:
        load(args.state, "state", check_state)
    else:
        load(args.facts, "facts", check_facts)
    print("ok")
    return 0


COMMANDS = {"window": run_window, "apply": run_apply, "init": run_init, "validate": run_validate}


def build_parser():
    parser = argparse.ArgumentParser(prog="state.py", description="Prod watch state engine")
    commands = parser.add_subparsers(dest="command", required=True)
    window = commands.add_parser("window", help="compute the run window and hour buckets")
    for flag in ("--state", "--now", "--tz", "--out"):
        window.add_argument(flag, required=True)
    start = window.add_mutually_exclusive_group()
    start.add_argument("--since", help="explicit window start, uncapped; the run then never advances the state")
    start.add_argument("--report-only", action="store_true", help="normal window start, marked explicit so the run never advances the state")
    apply = commands.add_parser("apply", help="write the next state, the change summary and the run record")
    for flag in ("--state", "--facts", "--window", "--tz", "--out", "--summary", "--record"):
        apply.add_argument(flag, required=True)
    init = commands.add_parser("init", help="write the baseline state of a routine that has none")
    for flag in ("--digest", "--out"):
        init.add_argument(flag, required=True)
    validate = commands.add_parser("validate", help="check the required keys of a state or facts file")
    target = validate.add_mutually_exclusive_group(required=True)
    target.add_argument("--state")
    target.add_argument("--facts")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except InputError as error:
        print(f"state.py: {error}", file=sys.stderr)
        return 2
    except Rejected as error:
        print(f"state.py: rejected: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
