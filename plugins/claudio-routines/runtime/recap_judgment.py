import re
import unicodedata

import judgment
import recap_features
import recap_state
import state

KINDS = tuple(recap_features.KIND_DEFINITIONS)
WAITING_ON_YOU = recap_features.WAITING_ON_YOU
PROMISE = recap_features.PROMISE
SUMMARY_CHARS = 200
READING_CHARS = state.LABEL_CAP
READING_ENTRIES = (2, 4)
NAME_CAP = 80
SENTENCE_END = re.compile(r"[.!?]\s+\S")
CHAT_ID = re.compile(r"\b[UW](?=[A-Z0-9]*[0-9])[A-Z0-9]{6,}\b")
JUDGMENT_FIELDS = ("units", "reading")
UNIT_FIELDS = ("kind", "title", "summary", "blocking", "due")
READING_FIELDS = ("text", "cites")
FEATURES_SPEC = {"units": {"*": {"allowed": [state.TEXT], "messages": [{"user": state.TEXT}]}}}


def named(value):
    return state.clean_text(str(value), NAME_CAP)


def reject(path, why):
    raise state.Rejected(f"{path or '<root>'}: {why}")


def forms(value):
    return value, unicodedata.normalize("NFKC", value)


def author_pattern(users):
    held = [re.escape(user) for user in sorted(users) if user]
    return re.compile(r"(?<!\w)(?:" + "|".join(held) + r")(?!\w)") if held else None


def unit_authors(unit):
    return {message["user"] for message in unit["messages"]}


def check_fields(value, fields, path):
    if not isinstance(value, dict):
        reject(path, "expected an object")
    for field in fields:
        if field not in value:
            reject(state.join(path, field), "missing")
    for field in sorted(value):
        if field not in fields:
            reject(state.join(path, named(field)), "unknown field")


def check_text(value, path, authors, cap):
    if not isinstance(value, str):
        reject(path, "expected a string")
    if state.has_barred(value):
        reject(path, "must not contain control, format or separator characters")
    if not value.strip():
        reject(path, "must not be empty")
    both = forms(value)
    if any(len(form) > cap for form in both):
        reject(path, f"must be at most {cap} characters")
    if any(judgment.INERT.search(form) for form in both):
        reject(path, "must not contain <, >, @ or ://")
    if any(CHAT_ID.search(form) or (authors and authors.search(form)) for form in both):
        reject(path, "must not hold a chat author id")


def check_title(value, path, authors):
    check_text(value, path, authors, state.LABEL_CAP)
    if any(recap_state.word_count(form) > recap_state.TITLE_WORDS for form in forms(value)):
        reject(path, f"must be at most {recap_state.TITLE_WORDS} words")


def check_summary(value, path, authors):
    check_text(value, path, authors, SUMMARY_CHARS)
    if any(SENTENCE_END.search(form) for form in forms(value)):
        reject(path, "must be one sentence")


def check_kind(value, path, allowed):
    if not isinstance(value, str) or value not in KINDS:
        reject(path, "expected one of " + ", ".join(KINDS))
    if value not in allowed:
        reject(path, f"{value} is not allowed for this unit, the facts allow " + ", ".join(allowed))


def check_blocking(value, path, kind):
    if not isinstance(value, bool):
        reject(path, "expected a boolean")
    if value and kind != WAITING_ON_YOU:
        reject(path, f"may be true only on {WAITING_ON_YOU}")


def check_due(value, path, kind):
    if value is None:
        return
    if not state.parses(state.parse_time, value):
        reject(path, "expected null or an ISO 8601 time with a UTC offset")
    if kind != PROMISE:
        reject(path, f"is allowed only on {PROMISE}")


def check_unit(key, entry, unit):
    path = f"units.{named(key)}"
    check_fields(entry, UNIT_FIELDS, path)
    authors = author_pattern(unit_authors(unit))
    check_kind(entry["kind"], f"{path}.kind", unit["allowed"])
    check_title(entry["title"], f"{path}.title", authors)
    check_summary(entry["summary"], f"{path}.summary", authors)
    check_blocking(entry["blocking"], f"{path}.blocking", entry["kind"])
    check_due(entry["due"], f"{path}.due", entry["kind"])


def check_units(judged, units):
    if not isinstance(judged, dict):
        reject("units", "expected an object")
    for key in sorted(units):
        if key not in judged:
            reject(f"units.{named(key)}", "missing, every unit of the features needs one entry")
    for key in sorted(judged):
        if key not in units:
            reject(f"units.{named(key)}", "not a unit of the features")
    for key in sorted(units):
        check_unit(key, judged[key], units[key])


def check_cites(value, path, units):
    if not isinstance(value, list) or not value:
        reject(path, "expected at least 1 unit key")
    for index, cite in enumerate(value):
        if not isinstance(cite, str) or cite not in units:
            reject(f"{path}[{index}]", f"{named(cite)} is not a unit of the run")


def check_reading(reading, units):
    low, high = READING_ENTRIES
    if not isinstance(reading, list):
        reject("reading", "expected a list")
    if not low <= len(reading) <= high:
        reject("reading", f"expected {low} to {high} entries, got {len(reading)}")
    authors = author_pattern({user for unit in units.values() for user in unit_authors(unit)})
    for index, entry in enumerate(reading):
        path = f"reading[{index}]"
        check_fields(entry, READING_FIELDS, path)
        check_text(entry["text"], f"{path}.text", authors, READING_CHARS)
        check_cites(entry["cites"], f"{path}.cites", units)


def check_judgment(document, features_doc):
    check_fields(document, JUDGMENT_FIELDS, "")
    check_units(document["units"], features_doc["units"])
    check_reading(document["reading"], features_doc["units"])


def load_features(path):
    try:
        return state.load(path, "features", lambda document: state.check(document, FEATURES_SPEC, ""))
    except state.Rejected as error:
        raise state.InputError(str(error)) from error


def load_judgment(path, features_doc):
    try:
        return state.load(path, "judgment", lambda document: check_judgment(document, features_doc))
    except state.InvalidJson as error:
        raise state.Rejected(str(error)) from error


def add_judge_arguments(parser):
    for flag in ("--features", "--judgment"):
        parser.add_argument(flag, required=True)


def run_judge(args):
    load_judgment(args.judgment, load_features(args.features))
    return 0
