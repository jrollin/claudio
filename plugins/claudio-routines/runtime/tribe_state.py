import re

import state
from state import InputError, Nullable, Rejected, leaf

SCHEMA_NAME = "tribe-1"
LAYOUT_VERSION = 1
SEVERITIES = state.SEVERITY
WHENS = state.URGENCY
CONFIDENCES = ("measured", "inferred", "reported")
STATUSES = ("open", "in progress", "mitigated", "decided", "dropped")
CHECK_GROUPS = ("This week", "Before the month-end", "Investigate")
KEYED_SECTIONS = ("warnings", "checks", "retired")
KEY = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
KEY_CAP = 60
DECISION_CAP = 3
COVERAGE_NOTE_CAP = 10
COVERAGE_SOURCE_CAP = 60
PAGE_KEY = re.compile(r"[a-z0-9]+")
UTC_TIME_TEXT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
ISO_WEEK = re.compile(r"[0-9]{4}-W(?:0[1-9]|[1-4][0-9]|5[0-3])")
LABEL_LIMITS = f"of at most {state.LABEL_CAP} characters without control characters"


def one_of(options):
    return leaf(lambda value: isinstance(value, str) and value in options, "one of " + ", ".join(options))


def is_key(key):
    return len(key) <= KEY_CAP and KEY.fullmatch(key) is not None


def page_key(page_id):
    return page_id.replace("-", "").lower()


def iso_week(moment):
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def is_utc_time(value):
    return isinstance(value, str) and UTC_TIME_TEXT.fullmatch(value) is not None and state.parses(state.parse_time, value)


SEVERITY_LEVEL = one_of(SEVERITIES)
WHEN_LEVEL = one_of(WHENS)
CONFIDENCE_LEVEL = one_of(CONFIDENCES)
STATUS = one_of(STATUSES)
CHECK_GROUP = one_of(CHECK_GROUPS)
UTC_TIME = leaf(is_utc_time, "a UTC time like 2026-01-31T08:00:00Z")
NAME = leaf(lambda value: isinstance(value, str) and value != "", "a non-empty string")
LABEL = leaf(state.is_label, "a string " + LABEL_LIMITS)
TITLE = leaf(lambda value: state.is_label(value) and value != "", "a non-empty string " + LABEL_LIMITS)
PAGE = leaf(lambda value: isinstance(value, str) and PAGE_KEY.fullmatch(value) is not None, "a page id of lowercase letters and digits")
WEEK = leaf(lambda value: isinstance(value, str) and ISO_WEEK.fullmatch(value) is not None, "an ISO week like 2026-W41")
COUNT = leaf(lambda value: state.is_integer(value) and value >= 0, "a non-negative integer")
LAYOUT = leaf(lambda value: state.is_integer(value) and value == LAYOUT_VERSION, f"layout version {LAYOUT_VERSION}")
SCHEMA = leaf(lambda value: value == SCHEMA_NAME, f"schema {SCHEMA_NAME}")
METRIC = leaf(lambda value: value is None or (isinstance(value, str) and value != ""), "a pack entry key or null")
OBJECT = leaf(lambda value: isinstance(value, dict), "an object")
RECORD_CITE = {"source": TITLE, "link": TITLE}
FEATURE_CITE = {"feature": TITLE, "name": TITLE}
BLIND_SPOT = {"key": NAME, "gap": LABEL, "runs": state.INTEGER}


def check_mitigation(value, path):
    if value != []:
        state.check_mitigation(value, path)


def check_cite(value, path):
    if not isinstance(value, dict):
        raise Rejected(f"expected an object at {path}")
    state.check(value, FEATURE_CITE if "feature" in value else RECORD_CITE, path)
    if "value" in value:
        raise Rejected(f"unexpected key {state.join(path, 'value')}: a stored cite omits the value")


def check_links(value, path):
    if not isinstance(value, list) or not value:
        raise Rejected(f"expected a list of at least 1 link at {path}")
    state.check(value, [NAME], path)


WARNING_SPEC = {
    "title": TITLE,
    "topic": TITLE,
    "severity": SEVERITY_LEVEL,
    "when": WHEN_LEVEL,
    "runway": LABEL,
    "status": STATUS,
    "confidence": CONFIDENCE_LEVEL,
    "risk": LABEL,
    "impact": LABEL,
    "mitigation": check_mitigation,
    "cites": [check_cite],
    "metric": METRIC,
    "runs_under": COUNT,
    "since": UTC_TIME,
}
CHECK_SPEC = {"text": TITLE, "topic": TITLE, "group": CHECK_GROUP, "since": UTC_TIME}
STATE_SPEC = {
    "schema": SCHEMA,
    "digest": NAME,
    "run": {
        "at": Nullable(UTC_TIME),
        "window": Nullable({"from_ts": state.INTEGER, "to_ts": state.INTEGER}),
        "daily_metrics_on": Nullable(state.DATE),
        "previous_page": Nullable({"id": PAGE, "written_at": UTC_TIME}),
        "weekly_heading_week": Nullable(WEEK),
        "layout_version": LAYOUT,
        "models": {"*": NAME},
        "posted": state.BOOLEAN,
    },
    "warnings": {"*": WARNING_SPEC},
    "checks": {"*": CHECK_SPEC},
    "cursors": {
        "observability": {"events_ts_ms": state.NUMBER_OR_NULL, "monitors": {"*": state.TEXT}, "metrics": {"*": state.NUMBER_OR_NULL}},
        "*": OBJECT,
    },
    "threads": {"*": [{"channel": NAME, "root_ts": NAME, "links": check_links}]},
    "blind_spots": [BLIND_SPOT],
    "retired": {"*": TITLE},
}


def check_state(document):
    state.check(document, STATE_SPEC, "")
    for section in KEYED_SECTIONS:
        for key in document[section]:
            if not is_key(key):
                raise Rejected(f"expected a kebab-case key of at most {KEY_CAP} characters at {state.join(section, state.clean_text(key, KEY_CAP))}")
    window = document["run"]["window"]
    if window is not None and window["from_ts"] > window["to_ts"]:
        raise Rejected(f"run.window: from_ts {window['from_ts']} is after to_ts {window['to_ts']}")


def initial_state(digest):
    return {
        "schema": SCHEMA_NAME,
        "digest": digest,
        "run": {
            "at": None,
            "window": None,
            "daily_metrics_on": None,
            "previous_page": None,
            "weekly_heading_week": None,
            "layout_version": LAYOUT_VERSION,
            "models": {},
            "posted": False,
        },
        "warnings": {},
        "checks": {},
        "cursors": {"observability": {"events_ts_ms": None, "monitors": {}, "metrics": {}}},
        "threads": {},
        "blind_spots": [],
        "retired": {},
    }


def load_input(path, label, spec):
    try:
        return state.load(path, label, lambda document: state.check(document, spec, ""))
    except Rejected as error:
        raise InputError(str(error)) from error


def load(path):
    return state.load(path, "state", check_state)


def write(path, document):
    check_state(document)
    state.write_all([(path, state.dump(document))])
