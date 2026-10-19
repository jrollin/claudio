import re

import state
from state import Nullable, Rejected, leaf

SCHEMA_VERSION = 1
DM_KINDS = ("dm", "group_dm")
THREAD_KINDS = ("thread", "mention", "group")
UNIT_KINDS = DM_KINDS + THREAD_KINDS
KEY_KINDS = {"dm": DM_KINDS, "thread": THREAD_KINDS}
STATUSES = ("waiting", "promise", "waiting_on_others", "team_ask", "handled", "announcement")
TITLE_WORDS = 8
KEY_CAP = 80
CHANNEL_ID = "[A-Za-z0-9]{1,32}"
SLACK_TS = "[0-9]+[.][0-9]+"
DM_KEY = re.compile(f"dm-({CHANNEL_ID})")
THREAD_KEY = re.compile(f"thread-({CHANNEL_ID})-({SLACK_TS})")
SLACK_TS_TEXT = re.compile(SLACK_TS)
BLIND_SPOT_KEY_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}")
UTC_TIME_TEXT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
LABEL_LIMITS = f"of at most {state.LABEL_CAP} characters without control characters"


def dm_key(channel):
    return f"dm-{channel}"


def thread_key(channel, root_ts):
    return f"thread-{channel}-{root_ts}"


def key_channel(key):
    found = DM_KEY.fullmatch(key) or THREAD_KEY.fullmatch(key)
    return None if found is None else found.group(1)


def key_prefix(key):
    return key.split("-", 1)[0]


def word_count(text):
    return len(text.split())


def is_title(value):
    return state.is_label(value) and 0 < word_count(value) <= TITLE_WORDS


def is_utc_time(value):
    return isinstance(value, str) and UTC_TIME_TEXT.fullmatch(value) is not None and state.parses(state.parse_time, value)


def one_of(options):
    return leaf(lambda value: isinstance(value, str) and value in options, "one of " + ", ".join(options))


SCHEMA = leaf(lambda value: state.is_integer(value) and value == SCHEMA_VERSION, f"schema {SCHEMA_VERSION}")
NAME = leaf(lambda value: isinstance(value, str) and value != "", "a non-empty string")
LABEL = leaf(state.is_label, "a string " + LABEL_LIMITS)
DIGEST = leaf(lambda value: state.is_label(value) and value != "", "a non-empty string " + LABEL_LIMITS)
BLIND_SPOT_KEY = leaf(
    lambda value: isinstance(value, str) and BLIND_SPOT_KEY_TEXT.fullmatch(value) is not None,
    "a key of letters, digits, dots, colons and dashes, at most 80 characters",
)
TITLE = leaf(is_title, f"a non-empty string of at most {TITLE_WORDS} words " + LABEL_LIMITS)
UTC_TIME = leaf(is_utc_time, "a UTC time like 2026-01-31T08:00:00Z")
MESSAGE_TS = leaf(lambda value: isinstance(value, str) and SLACK_TS_TEXT.fullmatch(value) is not None, "a message ts like 1791990730.002679")
COUNT = leaf(lambda value: state.is_integer(value) and value >= 0, "a non-negative integer")
UNIT_KIND = one_of(UNIT_KINDS)
UNIT_STATUS = one_of(STATUSES)

UNIT_SPEC = {
    "kind": UNIT_KIND,
    "channel": NAME,
    "title": TITLE,
    "first_seen": UTC_TIME,
    "last_ts": MESSAGE_TS,
    "status": UNIT_STATUS,
    "runs_waiting": COUNT,
    "late": Nullable(COUNT),
    "due": Nullable(UTC_TIME),
}
STATE_SPEC = {
    "schema": SCHEMA,
    "digest": DIGEST,
    "run": {
        "at": Nullable(UTC_TIME),
        "previous_at": Nullable(UTC_TIME),
        "window": Nullable({"from_ts": state.INTEGER, "to_ts": state.INTEGER}),
    },
    "units": {"*": UNIT_SPEC},
    "blind_spots": [{"key": BLIND_SPOT_KEY, "gap": LABEL, "runs": state.INTEGER}],
}


def key_path(path, key):
    return state.join(path, state.clean_text(key, KEY_CAP))


def check_unit_keys(document):
    units = document.get("units") if isinstance(document, dict) else None
    if isinstance(units, dict):
        for key in units:
            if key_channel(key) is None:
                raise Rejected(f"expected a unit key dm-<channel> or thread-<channel>-<root ts> at {key_path('units', key)}")


def reject_unknown(value, spec, path):
    if isinstance(spec, Nullable):
        if value is None:
            return
        spec = spec.spec
    if isinstance(spec, dict):
        for name, child in value.items():
            sub = spec.get(name, spec.get("*"))
            if sub is None:
                raise Rejected(f"unexpected key {key_path(path, name)}: the state holds ids, times, titles and counts only")
            reject_unknown(child, sub, key_path(path, name))
    elif isinstance(spec, list):
        for index, child in enumerate(value):
            reject_unknown(child, spec[0], f"{path}[{index}]")


def check_unit_links(units):
    for key, unit in units.items():
        path = key_path("units", key)
        channel = key_channel(key)
        if unit["channel"] != channel:
            raise Rejected(f"expected channel {channel} of the unit key at {state.join(path, 'channel')}")
        allowed = KEY_KINDS[key_prefix(key)]
        if unit["kind"] not in allowed:
            raise Rejected(f"expected one of {', '.join(allowed)} under a {key_prefix(key)}- key at {state.join(path, 'kind')}")


def check_state(document):
    check_unit_keys(document)
    state.check(document, STATE_SPEC, "")
    reject_unknown(document, STATE_SPEC, "")
    check_unit_links(document["units"])
    window = document["run"]["window"]
    if window is not None and window["from_ts"] > window["to_ts"]:
        raise Rejected(f"run.window: from_ts {window['from_ts']} is after to_ts {window['to_ts']}")


def initial_state(digest):
    return {
        "schema": SCHEMA_VERSION,
        "digest": digest,
        "run": {"at": None, "previous_at": None, "window": None},
        "units": {},
        "blind_spots": [],
    }


def load(path):
    return state.load(path, "state", check_state)


def write(path, document):
    check_state(document)
    state.write_all([(path, state.dump(document))])
