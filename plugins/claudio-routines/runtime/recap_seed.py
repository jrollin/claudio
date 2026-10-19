import re
from datetime import datetime, timezone

import recap_state
import state
from state import Nullable, leaf

SOURCE_KINDS = ("dm", "group", "mention", "thread")
SOURCE_STATUSES = ("handled", "waiting", "team_ask", "waiting_on_others", "promise")
LATE_LEADING = re.compile(r"([0-9]{1,4})(?![0-9])")
MAX_SECONDS = int(datetime.max.replace(tzinfo=timezone.utc).timestamp())

SECONDS = leaf(lambda value: state.is_integer(value) and 0 <= value <= MAX_SECONDS, "a Unix time in seconds")
LATE_TEXT = leaf(lambda value: isinstance(value, str) and LATE_LEADING.match(value) is not None, 'a text starting with an integer like "3 working days"')
LIST = leaf(lambda value: isinstance(value, list), "a list")

SOURCE_UNIT_SPEC = {
    "kind": recap_state.one_of(SOURCE_KINDS),
    "channel": recap_state.NAME,
    "title": state.TEXT,
    "first_seen": SECONDS,
    "last_ts": SECONDS,
    "status": recap_state.one_of(SOURCE_STATUSES),
    "runs_waiting": recap_state.COUNT,
    "late": Nullable(LATE_TEXT),
}
SOURCE_SPEC = {"schema": recap_state.SCHEMA, "run": recap_state.STATE_SPEC["run"], "units": {}, "blind_spots": LIST}


def check_source(document):
    state.check(document, SOURCE_SPEC, "")
    recap_state.check_unit_keys(document)
    for key, unit in document["units"].items():
        state.check(unit, SOURCE_UNIT_SPEC, recap_state.key_path("units", key))


def cut_title(text):
    return " ".join(text.split()[: recap_state.TITLE_WORDS])


def convert_unit(unit):
    late = unit["late"]
    return {
        "kind": unit["kind"],
        "channel": unit["channel"],
        "title": cut_title(unit["title"]),
        "first_seen": state.utc_text(unit["first_seen"]),
        "last_ts": f"{unit['last_ts']}.000000",
        "status": unit["status"],
        "runs_waiting": unit["runs_waiting"],
        "late": None if late is None else int(LATE_LEADING.match(late).group(1)),
        "due": None,
    }


def convert_run(run):
    window = run["window"]
    return {
        "at": run["at"],
        "previous_at": run["previous_at"],
        "window": None if window is None else {"from_ts": window["from_ts"], "to_ts": window["to_ts"]},
    }


def seed(path, digest):
    source = state.load(path, "seed", check_source)
    document = {
        **recap_state.initial_state(digest),
        "run": convert_run(source["run"]),
        "units": {key: convert_unit(unit) for key, unit in source["units"].items()},
    }
    try:
        recap_state.check_state(document)
    except state.Rejected as error:
        raise state.Rejected(f"seed: {error}") from error
    return document
