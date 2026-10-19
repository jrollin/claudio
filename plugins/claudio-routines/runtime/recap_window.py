from datetime import datetime, timedelta

import recap_state
import state
from state import Nullable, Rejected

FIRST_WEEKEND_DAY = 5
LIMITS = ("baseline", "gap")
WINDOW_SPEC = {"from_ts": state.INTEGER, "to_ts": state.INTEGER, "limited": Nullable(recap_state.one_of(LIMITS)), "explicit": state.BOOLEAN}
MAX_LOOKBACK_WORKING_DAYS = 365


def check_window(document):
    state.check(document, WINDOW_SPEC, "")
    if document["from_ts"] > document["to_ts"]:
        raise Rejected(f"from_ts {document['from_ts']} is after to_ts {document['to_ts']}")


def is_working_day(day):
    return day.weekday() < FIRST_WEEKEND_DAY


def working_days_between(from_ts, to_ts, zone):
    start = state.local_date(from_ts, zone)
    days = (state.local_date(to_ts, zone) - start).days
    return sum(1 for offset in range(1, days + 1) if is_working_day(start + timedelta(days=offset)))


def working_days_back(ts, count, zone):
    day = state.local_date(ts, zone)
    remaining = count
    while remaining > 0:
        day -= timedelta(days=1)
        if is_working_day(day):
            remaining -= 1
    return int(datetime(day.year, day.month, day.day, tzinfo=zone).timestamp())


def window_start(previous_ts, to_ts, lookback, zone):
    if previous_ts is None:
        return working_days_back(to_ts, lookback, zone), "baseline"
    if working_days_between(previous_ts, to_ts, zone) > lookback:
        return working_days_back(to_ts, lookback, zone), "gap"
    return previous_ts, None


def compute_window(document, now, zone, lookback, since=None, report_only=False):
    to_ts = int(now.timestamp())
    previous_ts = state.previous_run_ts(document, now)
    if since is None:
        from_ts, limited = window_start(previous_ts, to_ts, lookback, zone)
    elif since > now:
        raise Rejected(f"time: --since {since.isoformat()} is after --now {now.isoformat()}")
    else:
        from_ts, limited = int(since.timestamp()), None
    return {"from_ts": from_ts, "to_ts": to_ts, "limited": limited, "explicit": since is not None or report_only}
