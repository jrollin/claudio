import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime

import evaluate
import state

ROUTINE = "prod-watch"
ADAPTER_ROLES = {"obs": "observability", "docs": "document_store"}
MON = str(10**6 + 77)
KEY = state.MONITOR_PREFIX + MON


def ts(text):
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


FROM_TS = ts("2026-06-01T22:30:00Z")
TO_TS = ts("2026-06-01T23:30:00Z")
HOUR_0 = ts("2026-06-01T22:00:00Z")
HOUR_1 = ts("2026-06-01T23:00:00Z")
STORED_EVENTS_MS = FROM_TS * 1000
NEW_EVENTS_MS = TO_TS * 1000
COMMIT = "1a2b" * 10
STORED_MUTES = [{"key": "disk", "until": "2026-07-01"}]


def role_of(adapter):
    return ADAPTER_ROLES.get(adapter, "unknown")


def git_answers(commit=COMMIT + "\n", status=""):
    answers = {"rev-parse": commit, "status": status}
    return lambda directory, args: answers[args[0]]


def write_json(path, document):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle)


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def provider(adapter, name):
    return {
        "adapter": adapter,
        "api": {"base_url": f"https://{name}.example.test", "credentials": {"token": "EXAMPLE_TOKEN"}},
        "mcp": {"connectors": {"cloud": name, "local": name}},
    }


def source(provider_name, cloud="api", **options):
    return dict({"provider": provider_name, "transport": {"cloud": cloud, "local": "mcp"}}, **options)


def monitor_entry(schedule="every_run", monitor=MON):
    return {
        "key": state.MONITOR_PREFIX + monitor,
        "source": "alerts",
        "monitor": monitor,
        "title": "API monitor",
        "link": "https://example.test/monitor",
        "rule": "Alert is High and now",
        "schedule": schedule,
    }


def metric_entry(read="scalar", schedule="every_run", key="cpu", source="gauges", **extra):
    entry = {
        "key": key,
        "source": source,
        "query": "avg:cpu",
        "read": read,
        "aggregator": "avg",
        "title": f"Metric {key}",
        "link": f"https://example.test/{key}",
        "rule": "Open above 80",
        "schedule": schedule,
    }
    entry.update(extra)
    return entry


def make_config(pack=None, timezone="Europe/Paris", rules=None, **sources):
    configured = {
        "alerts": source("observer", kind="monitors", scope_filter=""),
        "gauges": source("observer", kind="metrics", scope_filter=""),
        "notes": source("pages", page_id="page-1"),
    }
    configured.update(sources)
    routine = {
        "sources": configured,
        "query_pack": [monitor_entry(), metric_entry()] if pack is None else pack,
        "models": {"main": "model-a"},
    }
    if rules is not None:
        routine["rules"] = rules
    return {
        "timezone": timezone,
        "places": {place: {"runtime_dir": "/opt/runtime", "state_dir": "/opt/state"} for place in ("cloud", "local")},
        "providers": {"observer": provider("obs", "observer"), "pages": provider("docs", "pages")},
        "routines": {ROUTINE: routine},
    }


def make_item(severity="Low", when="watch", **extra):
    item = {
        "title": "Disk", "topic": "metrics", "severity": severity, "when": when, "status": "open",
        "confidence": "high", "since": "2026-05-30T08:00:00Z", "opened_value": 70,
        "runs_under_threshold": 0, "last_value": 70, "link": "https://example.test/disk",
    }
    item.update(extra)
    return item


def make_state(blind_spots=None, items=None, metrics=None):
    document = state.initial_state("Prod watch")
    document["run"].update({
        "at": "2026-06-01T22:30:00Z",
        "sources_last_edited": "2026-05-01T08:00:00Z",
        "daily_metrics_on": "2026-06-01",
        "mutes": STORED_MUTES,
    })
    document["cursors"]["observability"] = {
        "events_ts_ms": STORED_EVENTS_MS, "monitors": {MON: "OK"}, "metrics": {"cpu": 10} if metrics is None else metrics,
    }
    document["resolved_queries"] = {"cpu": "avg:cpu"}
    document["blind_spots"] = blind_spots or []
    document["items"] = items or {}
    return document


def make_window(retry_known_gaps=False):
    return {
        "from_ts": FROM_TS, "to_ts": TO_TS, "buckets": [], "cut": None,
        "explicit": False, "retry_known_gaps": retry_known_gaps,
    }


def ok():
    return {"status": "ok", "reason": None}


def skipped(reason):
    return {"status": "deferred", "reason": reason}


def failed(reason):
    return {"status": "failed", "reason": reason}


def missing():
    return {"status": "missing", "reason": "not found"}


def collection(name, role, records, cursor, entries, read=True, reason=None, transport="api"):
    return {
        "schema": 1, "source": name, "role": role, "provider": "observer", "transport": transport,
        "place": "cloud", "window": {"from_ts": FROM_TS, "to_ts": TO_TS},
        "read": read, "reason": reason, "cursor": cursor, "records": records, "entries": entries,
    }


def monitor(state_name="Alert", monitor_id=MON, **extra):
    return dict({"id": monitor_id, "name": "API", "state": state_name, "priority": None, "link": "https://example.test/mon"}, **extra)


def alerts(monitors=None, entries=None, events=None, transport="api", **records):
    document = {
        "monitors": [monitor()] if monitors is None else monitors,
        "events": events or [],
        "discovered": [],
        "discovery": {"read": True, "reason": None},
    }
    document.update(records)
    cursor = {"events_ts_ms": NEW_EVENTS_MS, "monitors": {MON: "Alert"}}
    return collection("alerts", "observability", document, cursor, {KEY: ok()} if entries is None else entries, transport=transport)


def metric(value=90, hourly=None, groups=None, key="cpu", **extra):
    return dict({"key": key, "value": value, "hourly": hourly or [], "groups": groups or []}, **extra)


def gauges(metrics=None, entries=None, cursor=None, transport="api"):
    records = {"metrics": [metric()] if metrics is None else metrics}
    cursor = {"metrics": {"cpu": 90}} if cursor is None else cursor
    return collection("gauges", "observability", records, cursor, {"cpu": ok()} if entries is None else entries, transport=transport)


def unread_gauges(reason="HTTP 503 GET /query"):
    return collection("gauges", "observability", {"metrics": []}, None, {"cpu": failed(reason)}, read=False, reason=reason)


def unread_alerts():
    reason = "HTTP 503 GET /monitors"
    records = {"monitors": [], "events": [], "discovered": [], "discovery": None}
    return collection("alerts", "observability", records, None, {KEY: failed(reason)}, read=False, reason=reason)


MUTES_BLOCKS = [
    {"type": "heading", "text": "Mutes", "rows": None},
    {"type": "table", "text": "", "rows": [["key", "until"], ["cpu", "2026-06-10"]]},
]


def notes(blocks=None):
    page = {"id": "page-1", "title": "Sources", "last_edited": "2026-06-01T20:00:00Z", "blocks": MUTES_BLOCKS if blocks is None else blocks}
    return collection("notes", "document_store", {"pages": [page]}, {"last_edited": "2026-06-01T20:00:00Z"}, {})


def metrics_collection(name, metrics, cursor, entries):
    return collection(name, "observability", {"metrics": metrics}, {"metrics": cursor}, entries)


def collections(**overrides):
    documents = {"alerts": alerts(), "gauges": gauges(), "notes": notes()}
    documents.update(overrides)
    return documents


class EvaluateCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def path(self, name):
        return os.path.join(self.dir, name)

    def run_evaluate(self, config=None, stored=None, window=None, docs=None, place="cloud", git=None, role_of=role_of, tag=""):
        write_json(self.path("config.json"), make_config() if config is None else config)
        write_json(self.path("state.json"), make_state() if stored is None else stored)
        write_json(self.path("window.json"), make_window() if window is None else window)
        directory = self.path("collections")
        os.makedirs(directory, exist_ok=True)
        for name, document in (collections() if docs is None else docs).items():
            write_json(os.path.join(directory, f"{name}.json"), document)
        argv = [
            "features", "--config", self.path("config.json"), "--routine", ROUTINE, "--state", self.path("state.json"),
            "--window", self.path("window.json"), "--collections", directory, "--place", place, "--runtime", "runtime-a",
            "--out", self.path(f"features{tag}.json"), "--base-out", self.path(f"base{tag}.json"),
            "--rules-out", self.path(f"rules{tag}.json"),
        ]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = evaluate.main(argv, role_of=role_of, git=git or git_answers())
        return code, stderr.getvalue()

    def raw(self, name, tag="", **kwargs):
        code, error = self.run_evaluate(tag=tag, **kwargs)
        self.assertEqual((code, error), (0, ""))
        with open(self.path(f"{name}{tag}.json"), "rb") as handle:
            return handle.read()

    def load(self, name, **kwargs):
        return json.loads(self.raw(name, **kwargs).decode("utf-8"))

    def base(self, **kwargs):
        return self.load("base", **kwargs)

    def features(self, **kwargs):
        return self.load("features", **kwargs)

    def rules(self, **kwargs):
        return self.load("rules", **kwargs)

    def keys(self, **kwargs):
        return sorted(self.features(**kwargs)["keys"])


def monitor_verdict(rank=1, **extra):
    return dict({"open": True, "severity": "High", "urgency": "now", "rank": rank, "cites": {"state": "Alert"}}, **extra)


def cpu_verdict(rank=2, **extra):
    return dict({"open": True, "severity": "Medium", "urgency": "watch", "rank": rank, "cites": {"value": 90}}, **extra)


def judgment_of(**verdicts):
    return {"schema": 1, "verdicts": verdicts or {KEY: monitor_verdict(), "cpu": cpu_verdict()}}


def analysis_item(cites, **extra):
    item = {
        "risk": "the service degrades for every caller",
        "reason": [{"tag": "measured", "claim": "the value is above its limit", "cites": cites}],
        "mitigation": ["roll back the last deploy"],
        "action": "page the owner",
    }
    item.update(extra)
    return item


def analysis_of(**items):
    return {
        "schema": 1,
        "items": items or {KEY: analysis_item({"state": "Alert"}), "cpu": analysis_item({"value": 90})},
    }
