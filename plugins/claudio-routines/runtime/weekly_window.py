from datetime import datetime, timedelta

import recap_state
import state
import weekly_state
from state import Rejected

WINDOW_SPEC = {"from_ts": state.INTEGER, "to_ts": state.INTEGER, "week_start": weekly_state.DAY, "report_only": state.BOOLEAN}


def check_window(document):
    state.check(document, WINDOW_SPEC, "")
    if document["from_ts"] > document["to_ts"]:
        raise Rejected(f"from_ts {document['from_ts']} is after to_ts {document['to_ts']}")


def load_now(text):
    if not recap_state.is_utc_time(text):
        raise state.InputError(f"--now: expected a UTC time like 2026-01-31T08:00:00Z, got {text}")
    return state.parse_time(text)


def compute_window(now, zone, report_only):
    monday = now.astimezone(zone).date()
    monday -= timedelta(days=monday.weekday())
    start = datetime(monday.year, monday.month, monday.day, tzinfo=zone)
    return {"from_ts": int(start.timestamp()), "to_ts": int(now.timestamp()), "week_start": monday.isoformat(), "report_only": report_only}
