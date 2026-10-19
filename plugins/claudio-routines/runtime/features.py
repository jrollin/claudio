import json
import re
from collections import Counter, namedtuple
from datetime import datetime, timezone

import roles
import state

MAX_KEY = 120
SIGNIFICANT = 4
HASH_LENGTH = 8
SLUG_RUNS = re.compile(r"[^a-z0-9]+")
NAME_PRIORITY = re.compile(r"\[P([1-5])\]", re.IGNORECASE)
NO_DATAPOINTS = "no datapoints"
EMPTY_AS_ZERO = "zero"
MONITOR_ABSENT = "monitor absent"
NOT_FOUND = "not found"
NOT_IN_PACK = "not in the query pack"
MUTES_UNREADABLE = "mutes table unreadable"
DISCOVERY_INCOMPLETE = "discovery incomplete"
STATE_NOT_RECOGNISED = "monitor state not recognised"
NOT_A_MONITOR_ID = "not a monitor id"
EVENT_MONITORS_CAPPED = "event monitors capped at 50"
DISCOVERY_CAP = 100
DISCOVERY_CAPPED = f"discovery capped at {DISCOVERY_CAP} monitors"
OK_STATE = "OK"
GROUP_MISSING = "group missing"
REPLACED_BY_GROUPS = "replaced by groups"
NOT_COLLECTED = {"status": "failed", "reason": "no entry in the collection"}

UNREAD = "unread"
DEFERRED = "deferred"
GAP = "gap"
OBSERVED = "observed"
MISSING = "missing"
GROUPS = "groups"
ATTEMPTED = (GAP, OBSERVED)

Outcome = namedtuple("Outcome", ("status", "reason", "docs", "groups"), defaults=(None, (), ()))


def fnv1a32(text):
    value = roles.FNV_OFFSET
    for byte in text.encode("utf-8", "surrogatepass"):
        value = ((value ^ byte) * roles.FNV_PRIME) & 0xFFFFFFFF
    return f"{value:08x}"


def label(text):
    return state.blank_controls(text)[: state.LABEL_CAP]


def title_of(text):
    return state.clean_text(text, state.LABEL_CAP)


def compact_dump(document):
    return (json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def local_iso(timestamp, zone):
    return datetime.fromtimestamp(timestamp, zone).isoformat(timespec="seconds")


def rounded(value):
    if isinstance(value, float):
        return float(f"{value:.{SIGNIFICANT}g}")
    if isinstance(value, dict):
        return {key: rounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [rounded(item) for item in value]
    return value


def names_of_kind(sources, kind):
    return [name for name, source in sources.items() if source["role"] == "observability" and source["kind"] == kind]


def kind_read(sources, collections, kind):
    names = names_of_kind(sources, kind)
    return bool(names) and all(collections[name]["read"] for name in names)


def monitor_priority(monitor):
    if monitor["priority"] is not None:
        return monitor["priority"]
    prefix = NAME_PRIORITY.match(monitor["name"])
    return int(prefix.group(1)) if prefix else None


def merged(parts):
    result = {}
    for part in parts:
        result.update(part)
    return result


def newest(values):
    present = [value for value in values if value is not None]
    return max(present) if present else None


def monitor_key(monitor):
    return state.MONITOR_PREFIX + monitor["id"]


def id_order(monitor):
    return len(monitor["id"]), monitor["id"]


def group_keys(entry_key, groups):
    slugs = [SLUG_RUNS.sub("-", group["group"].lower()).strip("-") for group in groups]
    counts = Counter(slugs)
    room = MAX_KEY - len(entry_key) - 1
    keys = []
    for group, slug in zip(groups, slugs):
        if slug and len(slug) <= room and counts[slug] == 1:
            keys.append(f"{entry_key}-{slug}")
            continue
        suffix = fnv1a32(group["group"])
        head = slug[: max(room - HASH_LENGTH - 1, 0)].strip("-")
        keys.append("-".join(part for part in (entry_key, head, suffix) if part))
    return keys


def reads_empty_as_zero(entry):
    return entry.get("empty") == EMPTY_AS_ZERO


def metric_values(value, window_max, window_max_at, latest, previous):
    change = None if value is None or previous is None else value - previous
    percent = None if change is None or previous == 0 else change / abs(previous) * 100
    return {
        "value": value,
        "window_max": window_max,
        "window_max_at": window_max_at,
        "latest": latest,
        "previous": previous,
        "change": change,
        "change_percent": percent,
    }


def daily_values(days, previous):
    present = [day for day in days if day["value"] is not None]
    if not present:
        return None
    peak = max(present, key=lambda day: day["value"])
    return metric_values(peak["value"], peak["value"], peak["label"], present[-1]["value"], previous)


def days_of(record):
    points = sorted(record.get("daily", []), key=lambda point: point["ts"])
    days = [
        {"label": datetime.fromtimestamp(point["ts"], timezone.utc).date().isoformat(), "value": point["value"]}
        for point in points
    ]
    if days:
        days[-1]["partial"] = True
    return days


def expand_mutes(mutes, tops, known_keys):
    expanded = []
    seen = set()
    for mute in mutes:
        extra = [
            {"key": key, "until": mute["until"]}
            for key in sorted(known_keys)
            if mute["key"] in tops and key.startswith(mute["key"] + "-")
        ]
        for candidate in [mute, *extra]:
            identity = (candidate["key"], candidate["until"])
            if identity not in seen:
                seen.add(identity)
                expanded.append(candidate)
    return expanded


class Reading:
    def __init__(self, routine, sources, collections, stored, window, zone):
        self.pack = routine["query_pack"]
        self.sources = sources
        self.collections = collections
        self.items = stored["items"]
        self.previous = stored["cursors"]["observability"]["metrics"]
        self.window = window
        self.zone = zone
        self.kinds_read = {kind: kind_read(sources, collections, kind) for kind in state.SOURCES}
        self.hours = state.hour_starts(window["from_ts"], window["to_ts"], zone)
        self.bucket_labels = [local_iso(hour, zone) for hour in self.hours]
        self.keys = {}
        self.auto = {}
        self.gaps = []
        self.deferred = set()
        self.attempted = set()
        self.statuses = {}
        self.unknown_states = {}
        self.capped = set()

    def tracked(self, key):
        item = self.items.get(key)
        if item is None:
            return None
        analysed = any(name in item for name in state.OPTIONAL_FIELDS)
        return {
            "severity": item["severity"],
            "when": item["when"],
            "since": item["since"],
            "runs_under_threshold": item["runs_under_threshold"],
            "has_analysis": analysed,
        }

    def set_auto(self, key, reason):
        item = self.items[key]
        self.auto[key] = {
            "reason": reason, "title": item["title"], "link": item["link"], "severity": item["severity"], "when": item["when"],
        }

    def tracked_groups(self, entry_key):
        return sorted(key for key in self.items if key.startswith(entry_key + "-"))

    def top_entries(self):
        return [entry for entry in self.pack if entry.get("read") == "top"]

    def gate(self, key, name, kind):
        collection = self.collections[name]
        if not collection["read"]:
            return Outcome(UNREAD)
        status = collection["entries"].get(key, NOT_COLLECTED)
        if status["status"] == "deferred":
            return Outcome(DEFERRED)
        if status["status"] == "failed":
            return Outcome(GAP, status["reason"])
        if not self.kinds_read[kind]:
            return Outcome(UNREAD)
        return Outcome(MISSING if status["status"] == "missing" else OBSERVED)

    def monitor_outcome(self, key, monitor_id, name, entry):
        gated = self.gate(key, name, "monitors")
        if gated.status != OBSERVED:
            return gated
        records = self.collections[name]["records"]
        found = [monitor for monitor in records["monitors"] + records["discovered"] if monitor["id"] == monitor_id]
        if not found:
            return Outcome(GAP, MONITOR_ABSENT)
        if found[0]["state"] not in roles.MONITOR_STATES:
            return Outcome(GAP, title_of(f"{STATE_NOT_RECOGNISED}: {found[0]['state']}"))
        return Outcome(OBSERVED, docs=[(key, self.monitor_doc(key, entry, name, found[0]))])

    def window_transitions(self, name):
        return {item["monitor"]: item for item in self.collections[name]["records"]["transitions"]}

    def monitor_doc(self, key, entry, name, monitor):
        seen = self.window_transitions(name).get(monitor["id"])
        count = 0 if seen is None else seen["count"]
        first, last = (None, None) if seen is None else (seen["first_ts_ms"], seen["last_ts_ms"])
        hours = None if first is None else (last - first) / (state.HOUR * 1000)
        values = {
            "state": monitor["state"],
            "priority": monitor_priority(monitor),
            "transitions": count,
            "first_transition": None if first is None else local_iso(first // 1000, self.zone),
            "last_transition": None if last is None else local_iso(last // 1000, self.zone),
            "transitions_per_hour": count / hours if count >= 2 and hours else None,
        }
        title = entry["title"] if entry else title_of(monitor["name"])
        link = entry["link"] if entry else label(monitor["link"])
        return self.doc(key, "monitor", entry, "monitors", title, link, values)

    def doc(self, key, kind, entry, engine_source, title, link, values, **extra):
        return {
            "kind": kind,
            "entry": entry["key"] if entry else None,
            "source": engine_source,
            "title": title,
            "link": link,
            "values": values,
            "tracked": self.tracked(key),
            **extra,
        }

    def metric_outcome(self, entry):
        key = entry["key"]
        gated = self.gate(key, entry["source"], "metrics")
        if gated.status == MISSING:
            return Outcome(GAP, NOT_FOUND)
        if gated.status != OBSERVED:
            return gated
        record = next((item for item in self.collections[entry["source"]]["records"]["metrics"] if item["key"] == key), None)
        if record is None:
            return Outcome(GAP, NO_DATAPOINTS)
        if entry["read"] == "top":
            if record["groups"] or reads_empty_as_zero(entry):
                return Outcome(GROUPS, groups=record["groups"])
            return Outcome(GAP, NO_DATAPOINTS)
        doc = self.series_doc(entry, record)
        return Outcome(OBSERVED, docs=[(key, doc)]) if doc else Outcome(GAP, NO_DATAPOINTS)

    def series_doc(self, entry, record):
        key = entry["key"]
        previous = self.previous.get(key)
        lookback = "lookback_days" in entry
        days = days_of(record) if lookback else []
        extra = {"days": days} if days else {}
        if entry["read"] == "hourly" and lookback:
            values = daily_values(days, previous)
            if values is None:
                return None
        elif entry["read"] == "hourly":
            buckets, excluded = self.buckets(entry, record)
            present = [(value, index) for index, value in enumerate(buckets) if value is not None]
            if not present:
                return None
            kept = [(value, index) for value, index in present if index not in excluded]
            peak = max(kept, key=lambda pair: pair[0], default=(None, None))
            at = None if peak[1] is None else self.bucket_labels[peak[1]]
            values = metric_values(peak[0], peak[0], at, present[-1][0], previous)
            extra.update({"buckets": buckets, "excluded": excluded})
        else:
            value = record["value"]
            if value is None and not any(day["value"] is not None for day in days):
                if not reads_empty_as_zero(entry):
                    return None
                value = 0
            values = metric_values(value, value, None, value, previous)
        return self.doc(key, "metric", entry, "metrics", entry["title"], entry["link"], values, **extra)

    def buckets(self, entry, record):
        buckets = [None] * len(self.hours)
        for point in record["hourly"]:
            index = (point["ts"] - self.hours.start) // state.HOUR
            if 0 <= index < len(buckets) and point["value"] is not None:
                current = buckets[index]
                buckets[index] = point["value"] if current is None else max(current, point["value"])
        barred = entry.get("excluded_hours", [])
        excluded = [index for index, hour in enumerate(self.hours) if datetime.fromtimestamp(hour, self.zone).hour in barred]
        return buckets, excluded

    def settle(self, key, status, reason=None):
        self.statuses[key] = status
        if status == GAP:
            self.gaps.append((key, reason))
            self.deferred.add(key)
        elif status == DEFERRED:
            self.deferred.add(key)
        if status in ATTEMPTED:
            self.attempted.add(key)

    def settle_top(self, entry, groups, keys):
        entry_key, limit = entry["key"], entry["top"]
        complete = len(groups) < limit
        self.settle(entry_key, OBSERVED)
        if entry_key in self.items:
            self.set_auto(entry_key, REPLACED_BY_GROUPS if groups else GROUP_MISSING)
        for key, group in zip(keys, groups):
            title = label(f"{entry['title']}: {title_of(group['group'])}")
            value = group["value"]
            values = metric_values(value, value, None, value, self.previous.get(key))
            values["groups_complete"] = complete
            self.keys[key] = self.doc(key, "group", entry, "metrics", title, entry["link"], values)
        capped = False
        for key in self.tracked_groups(entry_key):
            if key in self.keys:
                continue
            if complete:
                self.set_auto(key, GROUP_MISSING)
            else:
                self.deferred.add(key)
                capped = True
        if capped:
            self.gaps.append((entry_key, f"outside the top {limit}"))

    def settle_entry(self, entry, outcome):
        key, status = entry["key"], outcome.status
        if status == OBSERVED:
            self.keys.update(dict(outcome.docs))
            self.settle(key, OBSERVED)
        elif status == MISSING:
            if key in self.items:
                self.set_auto(key, NOT_FOUND)
                self.settle(key, OBSERVED)
            else:
                self.settle(key, GAP, NOT_FOUND)
        else:
            self.settle(key, status, outcome.reason)
        if entry.get("read") == "top" and status in (GAP, DEFERRED):
            self.deferred.update(self.tracked_groups(key))

    def resolve_collisions(self, outcomes):
        taken = {entry["key"] for entry in self.pack} | set(self.sources)
        named = {key: group_keys(key, outcome.groups) for key, outcome in outcomes.items() if outcome.status == GROUPS}
        counts = Counter(name for names in named.values() for name in names)
        resolved = dict(outcomes)
        for key, names in named.items():
            bad = next((name for name in names if counts[name] > 1 or name in taken), None)
            if bad is not None:
                resolved[key] = Outcome(GAP, f"group key collision: {bad}")
        return resolved, named

    def read_pack(self):
        outcomes = {}
        for entry in self.pack:
            if "monitor" in entry:
                outcomes[entry["key"]] = self.monitor_outcome(entry["key"], entry["monitor"], entry["source"], entry)
            else:
                outcomes[entry["key"]] = self.metric_outcome(entry)
        resolved, named = self.resolve_collisions(outcomes)
        for entry in self.pack:
            key = entry["key"]
            outcome = resolved[key]
            if outcome.status == GROUPS:
                self.settle_top(entry, outcome.groups, named[key])
            elif outcome.status == UNREAD:
                self.statuses[key] = UNREAD
            else:
                self.settle_entry(entry, outcome)

    def read_tracked_monitors(self):
        if not self.kinds_read["monitors"]:
            return
        names = names_of_kind(self.sources, "monitors")
        in_pack = {entry["key"] for entry in self.pack}
        for key in sorted(self.items):
            if key in in_pack or state.key_source(key) != "monitors":
                continue
            if not state.is_tracked_monitor(key):
                self.settle(key, GAP, NOT_A_MONITOR_ID)
                continue
            home = next((name for name in names if key in self.collections[name]["entries"]), names[0])
            self.settle_entry({"key": key}, self.monitor_outcome(key, key[len(state.MONITOR_PREFIX) :], home, None))

    def read_discovered(self):
        if not self.kinds_read["monitors"]:
            return
        handled = {entry["key"] for entry in self.pack} | {key for key in self.items if state.is_tracked_monitor(key)}
        for name in names_of_kind(self.sources, "monitors"):
            found = self.untracked_discovered(name, handled)
            handled.update(monitor_key(monitor) for monitor in found)
            self.feature_discovered(name, found)

    def untracked_discovered(self, name, handled):
        found, named = {}, set(self.window_transitions(name))
        for monitor in self.collections[name]["records"]["discovered"]:
            if monitor_key(monitor) not in handled and (monitor["state"] != OK_STATE or monitor["id"] in named):
                found.setdefault(monitor_key(monitor), monitor)
        return sorted(found.values(), key=id_order)

    def feature_discovered(self, name, found):
        featured = 0
        for monitor in found:
            if monitor["state"] not in roles.MONITOR_STATES:
                self.unknown_states.setdefault(name, []).append(monitor["id"])
            elif featured < DISCOVERY_CAP:
                featured += 1
                self.keys[monitor_key(monitor)] = self.monitor_doc(monitor_key(monitor), None, name, monitor)
            else:
                self.capped.add(name)

    def read_all(self):
        self.read_pack()
        self.read_tracked_monitors()
        self.read_discovered()
        self.attempted.update(self.keys)
        self.attempted.update(name for name, collection in self.collections.items() if collection["read"])

    def orphans(self):
        in_pack = {entry["key"] for entry in self.pack}
        prefixes = tuple(entry["key"] + "-" for entry in self.top_entries())
        return sorted(
            key
            for key in self.items
            if self.kinds_read["metrics"]
            and state.key_source(key) == "metrics"
            and key not in in_pack
            and not key.startswith(prefixes)
        )

    def source_gaps(self):
        gaps = [(name, collection["reason"]) for name, collection in self.collections.items() if not collection["read"]]
        for name in names_of_kind(self.sources, "monitors"):
            parts = []
            discovery = self.discovery_of(name) or {}
            if not discovery.get("read", True):
                parts.append(DISCOVERY_INCOMPLETE)
            if discovery.get("event_monitors_capped"):
                parts.append(EVENT_MONITORS_CAPPED)
            if name in self.capped:
                parts.append(DISCOVERY_CAPPED)
            if name in self.unknown_states:
                parts.append(f"{STATE_NOT_RECOGNISED}: {', '.join(self.unknown_states[name])}")
            if parts:
                gaps.append((name, label("; ".join(parts))))
        return gaps

    def discovery_of(self, name):
        collection = self.collections[name]
        return collection["records"]["discovery"] if collection["read"] else None

    def cursors(self, stored):
        observability = stored["cursors"]["observability"]
        cursors = {key: observability[key] for key in ("events_ts_ms", "monitors", "metrics")}
        if self.kinds_read["monitors"]:
            parts = [self.collections[name]["cursor"] for name in names_of_kind(self.sources, "monitors")]
            cursors["events_ts_ms"] = newest(part["events_ts_ms"] for part in parts)
            cursors["monitors"] = merged(part["monitors"] for part in parts)
        if self.kinds_read["metrics"]:
            cursors["metrics"] = self.metric_cursor(merged(self.collections[name]["cursor"]["metrics"] for name in names_of_kind(self.sources, "metrics")))
        return cursors

    def metric_cursor(self, collected):
        metrics = dict(collected)
        self.fold_read_values(metrics)
        self.prune_stale_groups(metrics)
        self.keep_stored_groups(metrics)
        return metrics

    def fold_read_values(self, metrics):
        for key, doc in self.keys.items():
            if doc["kind"] == "monitor":
                continue
            value = doc["values"]["value"]
            if value is None:
                value = self.previous.get(key)
            if value is None:
                metrics.pop(key, None)
            else:
                metrics[key] = value

    def prune_stale_groups(self, metrics):
        for entry in self.top_entries():
            if self.statuses[entry["key"]] != OBSERVED:
                continue
            prefix = entry["key"] + "-"
            tracked = set(self.tracked_groups(entry["key"]))
            for key in [name for name in metrics if name.startswith(prefix)]:
                if key not in self.keys and key not in tracked:
                    del metrics[key]

    def keep_stored_groups(self, metrics):
        for entry in self.top_entries():
            for key in self.tracked_groups(entry["key"]):
                if key not in metrics and key in self.previous:
                    metrics[key] = self.previous[key]

    def retried(self, stored):
        if not self.window["retry_known_gaps"]:
            return []
        return sorted(spot["key"] for spot in stored["blind_spots"] if state.is_known(spot) and spot["key"] in self.attempted)

    def daily_metrics_on(self, stored):
        daily = [self.statuses[entry["key"]] for entry in self.pack if entry["schedule"] == "daily"]
        if UNREAD in daily or not any(status in ATTEMPTED for status in daily):
            return stored["run"]["daily_metrics_on"]
        return state.local_date(self.window["to_ts"], self.zone).isoformat()


def compute(routine, sources, collections, stored, window, zone, page):
    reading = Reading(routine, sources, collections, stored, window, zone)
    reading.read_all()
    orphans = reading.orphans()
    gaps = list(reading.gaps)
    gaps.extend((key, NOT_IN_PACK) for key in orphans)
    gaps.extend(reading.source_gaps())
    if page and page["mutes"] is None:
        gaps.append((page["source"], MUTES_UNREADABLE))
    tops = {entry["key"] for entry in reading.top_entries()}
    stored_mutes = stored["run"].get("mutes", [])
    mutes = stored_mutes if page is None or page["mutes"] is None else page["mutes"]
    deferred = reading.deferred | set(orphans)
    features = {"bucket_labels": reading.bucket_labels, "keys": reading.keys, "auto": reading.auto}
    base = {
        "sources": {kind: {"read": reading.kinds_read[kind]} for kind in state.SOURCES},
        "cursors": reading.cursors(stored),
        "blind_spots": sorted(({"key": key, "gap": gap} for key, gap in gaps), key=lambda spot: spot["key"]),
        "blind_spots_retried": reading.retried(stored),
        "mutes": expand_mutes(mutes, tops, set(reading.keys) | set(stored["items"])),
        "deferred": sorted(deferred),
        "sources_last_edited": page["last_edited"] if page else stored["run"]["sources_last_edited"],
        "daily_metrics_on": reading.daily_metrics_on(stored),
        "resolved_queries": stored["resolved_queries"],
        "models": routine.get("models", {}),
    }
    rules = {"routine": list(routine.get("rules", [])), "entries": {entry["key"]: entry["rule"] for entry in reading.pack}}
    return rounded(features), base, rules
