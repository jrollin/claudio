import email.message
import io
import json
import pathlib
import urllib.error
import urllib.parse

from providers import _http, datadog


FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "datadog"
BASE = "https://api.example.test"
APP = "https://app.example.test"
API_VAR = "OBS_API_KEY"
APP_VAR = "OBS_APP_KEY"
API_VALUE = "-".join(["api", "sentinel"])
APP_VALUE = "-".join(["app", "sentinel"])
TOKEN_VAR = "OBS_ACCESS_TOKEN"
TOKEN_VALUE = "-".join(["token", "sentinel"])
PROVIDER = {"adapter": "datadog", "api": {"base_url": BASE, "credentials": {"api_key": API_VAR, "app_key": APP_VAR}}}
WINDOW = {"from_ts": 1760000000, "to_ts": 1760010800}
FROM_MS = 1760000000000
TO_MS = 1760010800000
TRANSPORT = {"cloud": "api", "local": "api"}
MONITORS = {
    "name": "alerts",
    "provider": "obs",
    "transport": TRANSPORT,
    "kind": "monitors",
    "scope_filter": "source:alert env:prod",
    "provider_config": PROVIDER,
}
METRICS = {"name": "metrics", "provider": "obs", "transport": TRANSPORT, "kind": "metrics", "scope_filter": "", "provider_config": PROVIDER}
FRESH = {"events_ts_ms": None, "monitors": {}}
STORED_TS = 1760000500000
NO_METRICS = {"metrics": {}}
ENVIRON = {API_VAR: API_VALUE, APP_VAR: APP_VALUE}
OK = {"status": "ok", "reason": None}
QUERY = "avg:checkout.latency{env:prod}"


def failed(reason):
    return {"status": "failed", "reason": reason}


def monitor_entry(key, monitor):
    return {
        "key": key,
        "source": "alerts",
        "monitor": monitor,
        "title": "Monitor " + monitor,
        "link": APP + "/monitors/" + monitor,
        "severity": "High",
        "urgency": "now",
        "schedule": "every_run",
    }


def metric_entry(key, read, **extra):
    return {
        "key": key,
        "source": "metrics",
        "query": QUERY,
        "read": read,
        "aggregator": "avg",
        "threshold": {"op": ">", "value": 2},
        "title": key,
        "link": APP + "/metric/explorer",
        "severity": "Medium",
        "urgency": "watch",
        "schedule": "every_run",
        **extra,
    }


QUEUE = monitor_entry("monitor-queue", "102")
ODD = monitor_entry("monitor-odd", "12ab")
CHECKOUT = monitor_entry("monitor-checkout", "101")
DISK = monitor_entry("monitor-disk", "103")
P95 = metric_entry("checkout-p95", "scalar")
BY_SERVICE = metric_entry("errors-by-service", "top", top=5, aggregator="sum")
HOURLY = metric_entry("queue-hourly", "hourly", aggregator="max")
DAY = 86400
LOOKBACK = {"from_ts": WINDOW["to_ts"] - 7 * DAY, "to_ts": WINDOW["to_ts"]}
LOOKBACK_FROM_MS = LOOKBACK["from_ts"] * 1000

PARIS = "Europe/Paris"
TREND_WINDOW = {**WINDOW, "timezone": PARIS}
TREND_SPAN = {"from_ts": 1759442400, "to_ts": WINDOW["to_ts"]}
TREND_FROM_MS = TREND_SPAN["from_ts"] * 1000
FIRST_DAY = 1759615200
SPRING_FORWARD_DAY = 1774738800
FALL_BACK_DAY = 1792879200
HOUR = 3600

DISCOVERING = {**MONITORS, "discovery_query": "status:alert env:prod"}
NOT_FOUND = {"status": "missing", "reason": "not found"}


def lookback(entry):
    return {**entry, "schedule": "daily", "lookback_days": 7, "span": LOOKBACK}


def trended(entry, aggregator):
    return {**entry, "aggregator": aggregator, "trend_span": TREND_SPAN}


def at(day, hour, value):
    return FIRST_DAY + (day * 24 + hour) * HOUR, value


def series(*points):
    return {"times": [ts * 1000 for ts, _ in points], "values": [[value for _, value in points]]}


def clock_change_series(day_start, hours):
    around = [(day_start - HOUR, 100.0), (day_start + hours * HOUR, 200.0)]
    return series(*around, *((day_start + hour * HOUR, 1.0) for hour in range(hours)))


TREND_SERIES = series(at(2, 6, 1.0), at(0, 23, 2.0), at(0, 0, 4.0), at(2, 0, 7.0), at(0, 1, 9.0), at(2, 5, None), at(2, 7, None))


class FakeResponse:
    def __init__(self, body):
        self.stream = io.BytesIO(body)
        self.headers = email.message.Message()

    def read(self, size=-1):
        return self.stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeOpener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def fixture(name):
    return (FIXTURES / name).read_bytes()


def ok(name):
    return FakeResponse(fixture(name))


def served(document):
    return FakeResponse(json.dumps(document).encode("utf-8"))


def series_response(document):
    return served({"data": {"type": "timeseries_response", "attributes": document}})


def status(code):
    return urllib.error.HTTPError(BASE, code, "status", email.message.Message(), io.BytesIO(fixture(f"error_{code}.json")))


def client(opener, environ=ENVIRON):
    return datadog.api_client(PROVIDER, opener=opener, environ=environ, sleep=lambda seconds: None)


def run(source, entries, cursor, *outcomes, window=WINDOW):
    opener = FakeOpener(outcomes)
    return opener, datadog.fetch(source, window, cursor, entries, client(opener))


def configured(source, provider_config):
    return {**source, "provider_config": provider_config}


def collection(source, result):
    return {
        "schema": 1,
        "source": source["name"],
        "role": datadog.ROLE,
        "provider": "obs",
        "transport": "api",
        "place": "cloud",
        "window": WINDOW,
        "read": True,
        "reason": None,
        **result,
    }


def search_page(page, page_count, *monitors):
    metadata = {"page": page, "page_count": page_count, "per_page": 100, "total_count": len(monitors)}
    return served({"monitors": list(monitors), "metadata": metadata})


def found(monitor_id, status_text="Alert", **extra):
    return {"id": monitor_id, "name": f"Monitor {monitor_id}", "status": status_text, "priority": None, **extra}


def discover(*outcomes):
    return run(DISCOVERING, [], FRESH, ok("events_empty.json"), *outcomes)


def event(event_id, **attributes):
    return {"id": event_id, "type": "event", "attributes": attributes}


def events_page(*items):
    return served({"data": list(items), "meta": {"page": {}}})


def named_by_event(*monitor_ids):
    return events_page(*(event(f"ev-{monitor_id}", timestamp=FROM_MS + 1000, attributes={"monitor_id": monitor_id}) for monitor_id in monitor_ids))


def monitor_body(monitor_id, state_name="OK", **extra):
    return served({"id": monitor_id, "name": f"Monitor {monitor_id}", "overall_state": state_name, **extra})
