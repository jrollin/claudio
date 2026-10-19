import copy
from collections import namedtuple
from decimal import Decimal, InvalidOperation

import roles
import state
import tribe_judgment
import tribe_state
from config import accept_any
from state import InputError, Nullable, Omittable, Rejected

MOVE_FIELDS = ("severity", "when", "status")
RESOLVING_STATUSES = ("decided", "dropped")
JUDGED_FIELDS = tuple(name for name in tribe_judgment.WARNING_FIELDS if name != "verdict")
OBJECT = tribe_state.OBJECT
TEXT = state.TEXT
ROLE = state.leaf(lambda value: value in roles.ROLES, "one of " + ", ".join(roles.ROLES))

KEY_DOC = {"kind": TEXT, "source": TEXT, "link": Nullable(TEXT), "values": OBJECT}
EDITS_SPEC = {
    "page_id": Nullable(TEXT),
    "edited_at": Nullable(TEXT),
    "after_written": state.BOOLEAN,
    "statuses": {"*": tribe_state.STATUS},
    "ticked": [TEXT],
    "unticked": [TEXT],
    "ignored": [{"where": TEXT, "why": TEXT}],
}
FEATURES_SPEC = {
    "keys": {"*": KEY_DOC},
    "previous": {
        "warnings": {"*": tribe_state.WARNING_SPEC},
        "checks": {"*": tribe_state.CHECK_SPEC},
        "retired": {"*": tribe_state.TITLE},
    },
    "edits": EDITS_SPEC,
    "deferred": [TEXT],
    "authors": [TEXT],
    "pack": [TEXT],
}
SOURCE_ROW = {
    "source": TEXT,
    "role": ROLE,
    "read": state.BOOLEAN,
    "reason": Nullable(TEXT),
    "from_ts": Nullable(state.INTEGER),
    "to_ts": Nullable(state.INTEGER),
}
BASE_SPEC = {
    "sources": [SOURCE_ROW],
    "cursors": {"*": OBJECT},
    "blind_spots": [{"key": TEXT, "gap": state.LABEL}],
    "blind_spots_retried": Omittable([TEXT]),
    "daily_metrics_on": Nullable(state.DATE),
    "models": {"*": tribe_state.NAME},
}

Applied = namedtuple("Applied", "state summary record raw")
Outcome = namedtuple("Outcome", "warnings annotated resolved moves held checks done spots dropped ignored")


def load_features(path):
    return tribe_state.load_input(path, "features", FEATURES_SPEC)


def load_base(path):
    return tribe_state.load_input(path, "base", BASE_SPEC)


def load_judgment(path):
    try:
        return state.load(path, "judgment", accept_any)
    except state.InvalidJson as error:
        raise Rejected(str(error)) from error


def check_judgment(features_doc, document):
    try:
        return tribe_judgment.checked_judgment(features_doc, document)
    except Rejected as error:
        raise Rejected(f"judgment: {error}") from error


def judge(features_path, judgment_path):
    features_doc = load_features(features_path)
    check_judgment(features_doc, load_judgment(judgment_path))


def check_previous(previous, features_doc):
    if features_doc["previous"] != {name: previous[name] for name in ("warnings", "checks", "retired")}:
        raise InputError("features: previous differs from the state; build the features from the state of this run")
    edits = features_doc["edits"]
    stored = {
        "deferred": ("warnings", features_doc["deferred"]),
        "edits.statuses": ("warnings", sorted(edits["statuses"])),
        "edits.ticked": ("checks", edits["ticked"]),
        "edits.unticked": ("checks", edits["unticked"]),
    }
    for path, (section, keys) in stored.items():
        for index, key in enumerate(keys):
            if key not in previous[section]:
                raise InputError(f"features: {path}[{index}]: {tribe_judgment.named(key)} is not a stored {section.rstrip('s')}")


def check_window_order(previous, window):
    at = previous["run"]["at"]
    if at is not None and window["to_ts"] < state.parse_time(at).timestamp():
        raise Rejected(f"window: to_ts {window['to_ts']} is before the state run.at {at}")


def merged_warning(stored, entry, status, run_at):
    warning = {name: copy.deepcopy(entry[name]) for name in JUDGED_FIELDS}
    warning["cites"] = copy.deepcopy(entry["cites"])
    if status is not None:
        warning["status"] = status
    under = entry["verdict"] == "under" and entry["metric"] is not None
    warning["runs_under"] = (stored["runs_under"] if stored else 0) + 1 if under else 0
    warning["since"] = stored["since"] if stored else run_at
    return warning


def resolution(warning, replacement):
    if replacement is not None:
        return f"replaced by {replacement['title']}"
    if warning["status"] in RESOLVING_STATUSES:
        return f"status {warning['status']}"
    if warning["runs_under"] >= state.RESOLVE_RUNS:
        return f"under every threshold for {state.RESOLVE_RUNS} runs"
    return None


def moves_of(key, stored, warning):
    return [{"key": key, "field": field, "from": stored[field], "to": warning[field]} for field in MOVE_FIELDS if stored[field] != warning[field]]


def settled_status(stored, edited):
    if edited is not None:
        return edited
    if stored is not None and stored["status"] in RESOLVING_STATUSES:
        return stored["status"]
    return None


def outcome_of(key, stored, entry, held, edited, replacement, run_at):
    if key in held:
        return {**stored, "status": edited or stored["status"]}, None, []
    warning = stored if entry is None else merged_warning(stored, entry, settled_status(stored, edited), run_at)
    evidence = [] if entry is None else copy.deepcopy(entry["evidence"])
    return warning, resolution(warning, replacement), evidence


def warning_lifecycle(previous, judged, held, statuses, run_at):
    replacements = {entry["replaces"]: entry for entry in judged["warnings"].values() if entry.get("replaces")}
    warnings, annotated, resolved, moves = {}, {}, [], []
    for key in sorted(set(previous["warnings"]) | set(judged["warnings"])):
        stored, entry = previous["warnings"].get(key), judged["warnings"].get(key)
        warning, reason, evidence = outcome_of(key, stored, entry, held, statuses.get(key), replacements.get(key), run_at)
        if reason is not None:
            resolved.append({"key": key, "title": warning["title"], "reason": reason})
            continue
        changes = moves_of(key, stored, warning) if stored else []
        change = "new" if stored is None else "moved" if changes else "same"
        warnings[key] = warning
        annotated[key] = {**warning, "evidence": evidence, "change": change}
        moves.extend(changes)
    return warnings, annotated, resolved, moves


def check_lifecycle(previous, judged, ticked, run_at):
    checks, done = {}, []
    for key in sorted(set(previous) | set(judged)):
        stored, entry = previous.get(key), judged.get(key)
        if key in ticked:
            done.append({"key": key, "text": stored["text"]})
        elif entry is None:
            checks[key] = stored
        else:
            checks[key] = {**entry, "since": stored["since"] if stored else run_at}
    return checks, done


def retired_after(previous, resolved, done):
    retired = dict(previous)
    retired.update({entry["key"]: entry["title"] for entry in resolved})
    retired.update({entry["key"]: entry["text"] for entry in done})
    return retired


def mapping(cursor, name):
    value = cursor.get(name)
    return value if isinstance(value, dict) else {}


CURSOR_POINTS = {
    "observability": lambda cursor: {"events_ts_ms": cursor.get("events_ts_ms")},
    "chat": lambda cursor: {f"ts.{channel}": value for channel, value in mapping(cursor, "ts").items()},
    "document_store": lambda cursor: {f"pages.{page}": value for page, value in mapping(cursor, "pages").items()},
    "issue_tracker": lambda cursor: {"updated": cursor.get("updated")},
    "code_host": lambda cursor: {"updated_at": cursor.get("updated_at")},
}


def sortable(value):
    if isinstance(value, str) and state.parses(state.parse_time, value):
        return Decimal(str(state.parse_time(value).timestamp()))
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def check_forward(name, role, stored, fresh):
    if stored is None:
        return
    before, after = CURSOR_POINTS[role](stored), CURSOR_POINTS[role](fresh)
    for point in sorted(before.keys() & after.keys()):
        old, new = sortable(before[point]), sortable(after[point])
        if old is None or (new is None and point == "events_ts_ms" and after[point] is None):
            continue
        if new is None or new < old:
            shown = state.clean_text(f"{after[point]}", tribe_judgment.NAME_CAP)
            where = f"cursors.{name}.{state.clean_text(point, tribe_judgment.NAME_CAP)}"
            stored_shown = state.clean_text(f"{before[point]}", tribe_judgment.NAME_CAP)
            raise Rejected(f"base: {where}: {shown} does not move forward from the stored {stored_shown}")


def next_cursors(previous, base, window):
    read = {row["source"]: row["role"] for row in base["sources"] if row["read"]}
    cursors = copy.deepcopy(previous)
    for name in sorted(base["cursors"]):
        fresh = base["cursors"][name]
        role = "observability" if name == "observability" else read.get(name)
        if role is None:
            raise InputError(f"base: cursors.{state.clean_text(name, tribe_judgment.NAME_CAP)}: no source of that name was read in this run")
        if not window["explicit"]:
            check_forward(name, role, previous.get(name), fresh)
        if name == "observability":
            fresh = {key: value for key, value in fresh.items() if not (key == "events_ts_ms" and value is None)}
            cursors[name] = {**previous[name], **copy.deepcopy(fresh)}
        else:
            cursors[name] = copy.deepcopy(fresh)
    return cursors


def thread_index(keys):
    index = {}
    for doc in keys.values():
        values = doc["values"]
        if doc["kind"] == "record" and isinstance(values.get("channel"), str) and isinstance(values.get("thread"), str):
            index[(doc["source"], doc["link"])] = {"channel": values["channel"], "root_ts": values["thread"]}
    return index


def cited_links(warnings):
    links = {}
    for warning in warnings.values():
        for cite in warning["cites"]:
            if "link" in cite:
                links.setdefault(cite["source"], set()).add(cite["link"])
    return links


def read_threads(stored, links, source, index):
    found = {}
    for entry in stored:
        kept = set(entry["links"]) & links
        if kept:
            found.setdefault((entry["channel"], entry["root_ts"]), set()).update(kept)
    for link in links:
        thread = index.get((source, link))
        if thread is not None:
            found.setdefault((thread["channel"], thread["root_ts"]), set()).add(link)
    return [{"channel": channel, "root_ts": root_ts, "links": sorted(found[(channel, root_ts)])} for channel, root_ts in sorted(found)]


def next_threads(previous, base, keys, warnings):
    read = {row["source"] for row in base["sources"] if row["read"]}
    cited, index = cited_links(warnings), thread_index(keys)
    threads = {source: copy.deepcopy(entries) for source, entries in previous.items() if source not in read}
    for source in sorted(read):
        entries = read_threads(previous.get(source, []), cited.get(source, set()), source, index)
        if entries:
            threads[source] = entries
    return dict(sorted(threads.items()))


def run_block(previous, base, window, run_at):
    return {
        "at": run_at,
        "window": {"from_ts": window["from_ts"], "to_ts": window["to_ts"]},
        "daily_metrics_on": base["daily_metrics_on"],
        "previous_page": previous["run"]["previous_page"],
        "weekly_heading_week": previous["run"]["weekly_heading_week"],
        "layout_version": tribe_state.LAYOUT_VERSION,
        "models": base["models"],
        "posted": False,
    }


def build_summary(previous, judged, base, window, run_at, outcome):
    return {
        "digest": previous["digest"],
        "run_at": run_at,
        "window": {"from_ts": window["from_ts"], "to_ts": window["to_ts"]},
        "baseline": previous["run"]["at"] is None,
        "report_only": window["explicit"],
        "previous_page": previous["run"]["previous_page"],
        "warnings": outcome.annotated,
        "moved": outcome.moves,
        "resolved": outcome.resolved,
        "checks": outcome.checks,
        "done": outcome.done,
        "decisions": judged["decisions"],
        "details": judged["details"],
        "corrections": judged["corrections"],
        "highlights": judged["highlights"],
        "blind_spots": outcome.spots,
        "blind_spots_dropped": outcome.dropped,
        "coverage_notes": judged["coverage_notes"],
        "sources": [{**row, "role": row["role"].replace("_", " ")} for row in base["sources"]],
        "edits_ignored": outcome.ignored,
    }


def build_record(previous, base, window, run_at, outcome):
    keys = {
        "new": [key for key, warning in outcome.annotated.items() if warning["change"] == "new"],
        "moved": sorted({move["key"] for move in outcome.moves}),
        "resolved": [entry["key"] for entry in outcome.resolved],
        "done": [entry["key"] for entry in outcome.done],
        "held": outcome.held,
    }
    counts = {name: len(items) for name, items in keys.items()}
    counts.update({"open": len(outcome.warnings), "checks": len(outcome.checks)})
    record = {
        "schema": state.RECORD_SCHEMA_VERSION,
        "digest": previous["digest"],
        "run_at": run_at,
        "window": {"from_ts": window["from_ts"], "to_ts": window["to_ts"], "explicit": window["explicit"], "cut": window["cut"]},
        "counts": counts,
        **keys,
        "blind_spots": [{"key": spot["key"], "runs": spot["runs"]} for spot in outcome.spots],
        "blind_spots_dropped": outcome.dropped,
        "sources_read": [row["source"] for row in base["sources"] if row["read"]],
        "edits_ignored": outcome.ignored,
    }
    return record


def apply_run(previous, features_doc, judged, base, window):
    check_window_order(previous, window)
    edits = features_doc["edits"]
    held = set(features_doc["deferred"])
    run_at = state.utc_text(window["to_ts"])
    warnings, annotated, resolved, moves = warning_lifecycle(previous, judged, held, edits["statuses"], run_at)
    checks, done = check_lifecycle(previous["checks"], judged["checks"], set(edits["ticked"]), run_at)
    spots, dropped = state.apply_blind_spots(
        previous["blind_spots"], {"blind_spots": base["blind_spots"], "blind_spots_retried": base.get("blind_spots_retried", [])}
    )
    outcome = Outcome(warnings, annotated, resolved, moves, sorted(held), checks, done, spots, dropped, list(edits["ignored"]))
    next_state = {
        "schema": tribe_state.SCHEMA_NAME,
        "digest": previous["digest"],
        "run": run_block(previous, base, window, run_at),
        "warnings": warnings,
        "checks": checks,
        "cursors": next_cursors(previous["cursors"], base, window),
        "threads": next_threads(previous["threads"], base, features_doc["keys"], warnings),
        "blind_spots": spots,
        "retired": retired_after(previous["retired"], resolved, done),
    }
    return next_state, build_summary(previous, judged, base, window, run_at, outcome), build_record(previous, base, window, run_at, outcome)


def apply(state_path, features_path, base_path, judgment_path, window_path):
    raw, previous = state.load_raw(state_path, "state", tribe_state.check_state)
    features_doc = load_features(features_path)
    base = load_base(base_path)
    window = state.load(window_path, "window", state.check_window)
    check_previous(previous, features_doc)
    judged = check_judgment(features_doc, load_judgment(judgment_path))
    next_state, summary, record = apply_run(previous, features_doc, judged, base, window)
    tribe_state.check_state(next_state)
    return Applied(next_state, summary, record, raw if window["explicit"] else None)
