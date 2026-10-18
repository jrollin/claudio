import contextlib
import io
from datetime import datetime

import state

TZ = "Europe/Paris"
PREVIOUS = "2026-06-01T10:00:00Z"
NOW = "2026-06-01T11:00:00Z"


def ts(text):
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


def make_item(title="Metric A", severity="Medium", when="watch", opened_value=10, runs=0, **extra):
    item = {
        "title": title,
        "topic": "metrics",
        "severity": severity,
        "when": when,
        "status": "open",
        "confidence": "high",
        "since": "2026-05-30T08:00:00Z",
        "opened_value": opened_value,
        "runs_under_threshold": runs,
        "last_value": str(opened_value),
        "link": "https://example.test/metric-a",
    }
    item.update(extra)
    return item


def make_state(at=PREVIOUS, items=None, blind_spots=None, events_ts_ms=1000):
    return {
        "schema": 2,
        "digest": "Prod watch",
        "run": {
            "at": at,
            "previous_at": "2026-06-01T09:00:00Z",
            "sources_last_edited": "2026-05-01",
            "window": {"from_ts": ts("2026-06-01T09:00:00Z"), "to_ts": ts(PREVIOUS)},
            "daily_metrics_on": "2026-06-01",
            "models": {"main": "model-a"},
            "posted": True,
        },
        "cursors": {"observability": {
            "events_ts_ms": events_ts_ms, "monitors": {"monitor-1001": "OK"}, "metrics": {"metric-a": 5},
        }},
        "items": items or {},
        "resolved_queries": {},
        "blind_spots": blind_spots or [],
    }


def obs(over=True, value=10, severity="Medium", when="watch", source="metrics", title="Metric A", **extra):
    observation = {
        "source": source,
        "over": over,
        "value": value,
        "severity": severity,
        "when": when,
        "title": title,
        "link": "https://example.test/metric-a",
        "last_value": str(value),
    }
    observation.update(extra)
    return observation


def make_analysis(risk="queue grows", action="restart the consumer"):
    return {
        "risk": risk,
        "reason": [
            {"tag": "measured", "claim": "error rate doubled"},
            {"tag": "inferred", "claim": "a deploy changed the consumer"},
        ],
        "mitigation": ["roll back the consumer", "scale the workers", "pause the producer"],
        "action": action,
    }


def make_facts(observations=None, monitors=True, metrics=True, **extra):
    facts = {
        "sources": {"monitors": {"read": monitors}, "metrics": {"read": metrics}},
        "observations": observations or {},
        "cursors": {"events_ts_ms": 2000, "monitors": {"monitor-1001": "Alert"}, "metrics": {"metric-a": 12}},
        "blind_spots": [],
        "blind_spots_retried": [],
        "mutes": [],
        "sources_last_edited": "2026-05-02",
        "daily_metrics_on": "2026-06-01",
        "resolved_queries": {"query-a": "done"},
        "models": {"main": "model-b"},
    }
    facts.update(extra)
    return facts


def make_window(start=PREVIOUS, end=NOW, cut=None, explicit=False):
    return {
        "from_ts": ts(start), "to_ts": ts(end), "buckets": [], "cut": cut, "explicit": explicit, "retry_known_gaps": False,
    }


def make_run_context(place="local", runtime="ab" * 20, config="cd" * 20, config_dirty=True):
    return {
        "place": place,
        "runtime": runtime,
        "config": config,
        "config_dirty": config_dirty,
        "collected": {
            "monitors": {"role": "observability", "transport": "api", "read": True, "reason": None},
            "sources_page": {"role": "document_store", "transport": "mcp", "read": False, "reason": "no collection"},
        },
    }


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = state.main(list(argv))
        except SystemExit as error:
            code = error.code
    return code, out.getvalue(), err.getvalue()
