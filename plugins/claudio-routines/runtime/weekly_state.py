import re
from datetime import date

import recap_state
import state
from state import Nullable, Rejected, leaf

SCHEMA_NAME = "weekly-1"
DAY_TEXT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
KEY_CAP = 80


def is_day(value):
    return isinstance(value, str) and DAY_TEXT.fullmatch(value) is not None and state.parses(date.fromisoformat, value)


SCHEMA = leaf(lambda value: value == SCHEMA_NAME, f"schema {SCHEMA_NAME}")
DIGEST = leaf(lambda value: state.is_label(value) and value != "", f"a non-empty string of at most {state.LABEL_CAP} characters without control characters")
DAY = leaf(is_day, "a day like 2026-01-31")

LAST_RUN_SPEC = {"run_at": recap_state.UTC_TIME, "week_start": DAY}
STATE_SPEC = {"schema": SCHEMA, "digest": DIGEST, "last_run": Nullable(LAST_RUN_SPEC)}


def reject_unknown(value, spec, path):
    for name in value:
        if name not in spec:
            raise Rejected(f"unexpected key {state.join(path, state.clean_text(name, KEY_CAP))}: the state holds the digest, the time of the last run and its week start only")


def check_state(document):
    state.check(document, STATE_SPEC, "")
    reject_unknown(document, STATE_SPEC, "")
    if document["last_run"] is not None:
        reject_unknown(document["last_run"], LAST_RUN_SPEC, "last_run")


def initial_state(digest):
    return {"schema": SCHEMA_NAME, "digest": digest, "last_run": None}


def load(path):
    return state.load(path, "state", check_state)


def write(path, document):
    check_state(document)
    state.write_all([(path, state.dump(document))])
