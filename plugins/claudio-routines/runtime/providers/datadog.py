import datetime
import json
import math
import re
import urllib.parse

import roles
from state import clean_text, load_zone, local_date

from . import _common
from ._common import as_list, dig, json_object
from ._http import PAGE_CAP
from ._errors import GROUP_CAP_PARTIAL, PAGE_CAP_PARTIAL, PartialRead, SourceUnreadable

ROLE = "observability"
CREDENTIALS = ("api_key", "app_key")
STATIC_HEADERS = {}
ACCESS_TOKEN = "token"
MONITOR_PATH = "/api/v1/monitor/"
SEARCH_PATH = MONITOR_PATH + "search"
EVENTS_PATH = "/api/v2/events"
SCALAR_PATH = "/api/v2/query/scalar"
TIMESERIES_PATH = "/api/v2/query/timeseries"
EVENTS_PAGE_LIMIT = 100
EVENTS_PAGE_CAP = 100
SEARCH_PAGE_SIZE = 100
HOUR_MS = 3600000
DAY_MS = 24 * HOUR_MS
NOT_FOUND = 404
NOT_FOUND_REASON = "not found"
SOURCE_LEVEL_STATUSES = (401, 403)
ISO_FRACTION = re.compile(r"\.(\d+)")
ISO_COMPACT_OFFSET = re.compile(r"([+-]\d{2})(\d{2})$")
EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
MILLISECOND = datetime.timedelta(milliseconds=1)
TOOL = "execute_code"
INTENT = "Collect monitors and metrics for a scheduled routine run"
AGGREGATE_TOOL = "aggregate_events"
AGGREGATE_INTENT = "Count alert events per monitor for a scheduled routine run"
AGGREGATE_HEADER = "@monitor_id\tcount\tfirst_ts\tlast_ts"
AGGREGATE_TOKENS = 20000
GROUP_CAP = 1000
TOTAL_BUCKETS = re.compile(r"<total_buckets>\s*([0-9]+)\s*</total_buckets>")
TABLE = re.compile(r"<TSV_DATA>(.*?)</TSV_DATA>", re.S)
INTEGER_TEXT = re.compile(r"[0-9]+")
SCRIPT_TIMEOUT = 120
PARAMS_SLOT = "__PARAMS_LITERAL__"
MONITOR_ID = re.compile(r"[0-9]+")
STATE_CAP = 50
EVENT_MONITOR_CAP = 50
ERROR_CLASS = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]{0,63}")
NO_DATAPOINTS = "no datapoints"
TREND_AGGREGATORS = {
    "max": max,
    "min": min,
    "sum": sum,
    "avg": lambda values: sum(values) / len(values),
    "last": lambda values: values[-1],
}
SCRIPT_TEMPLATE = r"""import { client, v1, v2 } from "@datadog/datadog-api-client";

const PARAMS_TEXT = __PARAMS_LITERAL__;
const params = JSON.parse(PARAMS_TEXT);
const cfg = client.createConfiguration();
const runSpan = { from: params.window.from_ms, to: params.window.to_ms };
const MONITOR_ID = /^[0-9]+$/;
const NAME_CAP = 300;

function ascii(text) {
  return text.replace(/[\u0080-\uffff]/g, (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
}

function capped(text) {
  return typeof text === "string" ? Array.from(text).slice(0, NAME_CAP).join("") : text;
}

function fnv(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}

function failure(error) {
  const code = error !== null && typeof error === "object" ? error.code : undefined;
  const name = error !== null && error !== undefined && error.constructor ? error.constructor.name : "Error";
  return { ok: false, status: Number.isInteger(code) ? code : null, error: name };
}

async function guarded(read) {
  try {
    return await read();
  } catch (error) {
    return failure(error);
  }
}

async function readMonitor(api, entry) {
  if (!MONITOR_ID.test(entry.monitor)) {
    return { ok: false, status: null, error: "InvalidMonitorId" };
  }
  const monitor = await api.getMonitor({ monitorId: Number(entry.monitor) });
  return { ok: true, monitor: { id: monitor.id, name: capped(monitor.name), overall_state: monitor.overallState, priority: monitor.priority ?? null } };
}

function searchItem(item) {
  return { id: item.id, name: capped(item.name), status: item.status, priority: item.priority ?? null };
}

async function readDiscovery(api) {
  const pages = [];
  try {
    while (pages.length < params.page_cap) {
      const page = pages.length;
      const body = await api.searchMonitors({ query: params.discovery_query, page, perPage: params.search_page_size });
      const pageCount = body.metadata ? body.metadata.pageCount : undefined;
      pages.push({ monitors: body.monitors ? body.monitors.map(searchItem) : null, metadata: { page_count: pageCount } });
      if (!(page + 1 < pageCount)) {
        return { ok: true, pages, partial: null };
      }
    }
    return { ok: true, pages, partial: "page cap" };
  } catch (error) {
    return { ...failure(error), pages };
  }
}

function eventMonitorIds(discovery) {
  const covered = new Set(params.entries.map((entry) => entry.monitor));
  for (const page of discovery ? discovery.pages : []) {
    for (const item of page.monitors || []) {
      covered.add(String(item.id));
    }
  }
  return params.event_monitor_ids.filter((id) => !covered.has(id));
}

async function readEventMonitors(api, discovery) {
  const ids = eventMonitorIds(discovery);
  const reads = [];
  for (const id of ids.slice(0, params.event_monitor_cap)) {
    reads.push({ id, ...(await guarded(() => readMonitor(api, { monitor: id }))) });
  }
  return { capped: ids.length > params.event_monitor_cap, reads };
}

async function readSeries(api, entry, span, interval) {
  const query = { dataSource: "metrics", query: entry.query, name: "a" };
  const attributes = { ...span, interval, queries: [query], formulas: [{ formula: "a" }] };
  const body = await api.queryTimeseriesData({ body: { data: { type: "timeseries_request", attributes } } });
  const data = (body.data && body.data.attributes) || {};
  return { ok: true, timeseries: { times: data.times, values: data.values } };
}

async function readMetric(api, entry) {
  const span = entry.span ? { from: entry.span.from_ms, to: entry.span.to_ms } : runSpan;
  if (entry.read === "hourly") {
    return readSeries(api, entry, span, entry.span ? params.daily_interval_ms : params.interval_ms);
  }
  const query = { dataSource: "metrics", query: entry.query, name: "a" };
  const formula = { formula: "a", limit: { count: entry.top, order: "desc" } };
  const attributes = { ...span, queries: [{ ...query, aggregator: entry.aggregator }], formulas: [formula] };
  const body = await api.queryScalarData({ body: { data: { type: "scalar_request", attributes } } });
  const columns = (body.data && body.data.attributes && body.data.attributes.columns) || [];
  return { ok: true, scalar: { columns: columns.map((column) => ({ type: column.type, name: column.name, values: column.values })) } };
}

async function readTrend(api, entry) {
  return readSeries(api, entry, { from: entry.trend_span.from_ms, to: entry.trend_span.to_ms }, params.interval_ms);
}

async function collect() {
  if (params.kind === "monitors") {
    const monitorsApi = new v1.MonitorsApi(cfg);
    const monitors = [];
    for (const entry of params.entries) {
      monitors.push({ entry: entry.key, ...(await guarded(() => readMonitor(monitorsApi, entry))) });
    }
    const discovery = params.discovery_query ? await readDiscovery(monitorsApi) : null;
    const eventMonitors = await readEventMonitors(monitorsApi, discovery);
    return { monitors, ...(discovery ? { discovery } : {}), event_monitors: eventMonitors };
  }
  const metricsApi = new v2.MetricsApi(cfg);
  const metrics = [];
  for (const entry of params.entries) {
    const item = await guarded(() => readMetric(metricsApi, entry));
    const trend = item.ok && entry.trend_span ? { trend: await guarded(() => readTrend(metricsApi, entry)) } : {};
    metrics.push({ entry: entry.key, ...item, ...trend });
  }
  return { metrics };
}

const payload = ascii(JSON.stringify(await collect()));
return { payload, checksum: fnv(payload), digest: fnv(PARAMS_TEXT) };
"""


class EntryFailed(Exception):
    def __init__(self, reason, status=None):
        super().__init__(reason)
        self.status = status


class EntryMissing(Exception):
    pass


def api_client(provider, opener=None, environ=None, sleep=None):
    named = provider["api"]["credentials"]
    if ACCESS_TOKEN not in named:
        return _common.api_client(provider, CREDENTIALS, _auth, opener, environ, sleep)
    if any(name in named for name in CREDENTIALS):
        raise SourceUnreadable(f"api.credentials: name either {ACCESS_TOKEN}, or {' and '.join(CREDENTIALS)}")
    return _common.api_client(provider, (ACCESS_TOKEN,), _bearer, opener, environ, sleep)


def _auth(values):
    return {"DD-API-KEY": values["api_key"], "DD-APPLICATION-KEY": values["app_key"]}


def _bearer(values):
    return {"Authorization": "Bearer " + values[ACCESS_TOKEN]}


def fetch(source, window, cursor, entries, http):
    cursor = cursor or {}
    if source["kind"] == "monitors":
        return _fetch_monitors(source, window, cursor, entries, http)
    return _fetch_metrics(window, cursor, entries, http)


def plan(source, window, cursor, entries, responses, connector):
    if source["kind"] == "monitors":
        return _plan_monitors(source, window, entries, responses, connector)
    call_id = _call_id(source)
    if call_id in responses:
        return _common.ended()
    return _step(_script_call(source, window, entries, [], call_id, connector))


def _plan_monitors(source, window, entries, responses, connector):
    _require_links_base(source)
    aggregate_id, script_id = _call_id(source, 1), _call_id(source, 2)
    if script_id in responses:
        return _common.ended()
    if aggregate_id not in responses:
        return _step(_aggregate_call(source, window, aggregate_id, connector))
    named = {item["monitor"] for item in _aggregate_response(responses, aggregate_id)["transitions"]}
    ids = sorted(named - {entry["monitor"] for entry in entries}, key=_id_order)
    return _step(_script_call(source, window, entries, ids, script_id, connector))


def _step(call):
    return {"done": False, "partial": None, "calls": [call]}


def _aggregate_call(source, window, call_id, connector):
    computes = [
        {"field": "*", "aggregation": "COUNT", "output": "count", "sort": "desc"},
        {"field": "timestamp", "aggregation": "MIN", "output": "first_ts"},
        {"field": "timestamp", "aggregation": "MAX", "output": "last_ts"},
    ]
    arguments = {
        "query": source.get("scope_filter") or "",
        "from": _iso_utc(window["from_ts"]),
        "to": _iso_utc(window["to_ts"]),
        "group_by": {"fields": ["@monitor_id"], "limit": GROUP_CAP},
        "computes": computes,
        "max_tokens": AGGREGATE_TOKENS,
        "telemetry": {"intent": AGGREGATE_INTENT},
    }
    return {"id": call_id, "connector": connector, "tool": AGGREGATE_TOOL, "arguments": arguments, "digest": None}


def _iso_utc(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _script_call(source, window, entries, event_ids, call_id, connector):
    text = roles.params_text(_script_params(source, window, entries, event_ids))
    code = SCRIPT_TEMPLATE.replace(PARAMS_SLOT, json.dumps(text), 1)
    arguments = {"code": code, "telemetry": {"intent": INTENT}, "timeout": SCRIPT_TIMEOUT}
    return {"id": call_id, "connector": connector, "tool": TOOL, "arguments": arguments, "digest": roles.fnv1a32(text)}


def parse(source, window, cursor, entries, responses, digests):
    cursor = cursor or {}
    if source["kind"] == "monitors":
        return _parse_monitors(source, cursor, entries, responses, digests)
    call_id = _call_id(source)
    data = _script_payload(call_id, responses, digests)
    items = _payload_items(data, "metrics", call_id)
    read, statuses = _read_entries(entries, lambda entry: _relay_metric(entry, items(entry), window, call_id))
    return _metrics_result(cursor, read, statuses)


def _parse_monitors(source, cursor, entries, responses, digests):
    app = _require_links_base(source)
    events = _aggregate_response(responses, _call_id(source, 1))
    call_id = _call_id(source, 2)
    data = _script_payload(call_id, responses, digests)
    items = _payload_items(data, "monitors", call_id)
    read, statuses = _read_entries(entries, lambda entry: _relay_monitor(entry, items(entry), app))
    result = _monitors_result(cursor, read, statuses, events)
    discovery = _relay_discovery(source, data, app, call_id)
    ids, _ = _event_monitor_ids(entries, result["records"]["transitions"], discovery["discovered"])
    monitors, capped, failure = _relay_event_monitors(data, app, call_id, ids)
    return _with_discovery(result, _with_event_monitors(discovery, monitors, capped, failure))


def _call_id(source, number=1):
    return f"{source['name']}-{number}"


def _script_params(source, window, entries, event_ids):
    if source["kind"] == "monitors":
        selected = [{"key": entry["key"], "monitor": entry["monitor"]} for entry in entries]
    else:
        selected = [_metric_params(entry) for entry in entries]
    return {
        "kind": source["kind"],
        "entries": selected,
        "window": {"from_ms": window["from_ts"] * 1000, "to_ms": window["to_ts"] * 1000},
        "event_monitor_ids": event_ids,
        "page_cap": PAGE_CAP,
        "interval_ms": HOUR_MS,
        "daily_interval_ms": DAY_MS,
        "discovery_query": source.get("discovery_query") or "",
        "search_page_size": SEARCH_PAGE_SIZE,
        "event_monitor_cap": EVENT_MONITOR_CAP,
    }


def _metric_params(entry):
    fields = ("key", "query", "read", "aggregator")
    selected = {**{field: entry[field] for field in fields}, "top": entry.get("top") or 1}
    for name in ("span", "trend_span"):
        if entry.get(name):
            selected[name] = {"from_ms": entry[name]["from_ts"] * 1000, "to_ms": entry[name]["to_ts"] * 1000}
    return selected


def _script_payload(call_id, responses, digests):
    where = f"{TOOL} {call_id}"
    if call_id not in responses:
        raise SourceUnreadable(f"{where}: no saved response")
    not_object = f"{where}: response is not a JSON object"
    wrapper = json_object(responses[call_id], not_object, not_object)
    if dig(wrapper, "success") is not True or dig(wrapper, "outcome") != "success":
        raise SourceUnreadable(f"{where}: the tool call did not succeed")
    value = dig(wrapper, "value")
    if not isinstance(value, dict):
        raise SourceUnreadable(f"{where}: response without a value")
    payload, digest = value.get("payload"), value.get("digest")
    if not isinstance(payload, str) or not payload.isascii():
        raise SourceUnreadable(f"{where}: payload is not ASCII text")
    if value.get("checksum") != roles.fnv1a32(payload):
        raise SourceUnreadable(f"{where}: payload checksum mismatch")
    if not isinstance(digest, str) or digest != digests.get(call_id):
        raise SourceUnreadable(f"{where}: plan digest mismatch")
    not_payload = f"{where}: payload is not a JSON object"
    return json_object(payload, not_payload, not_payload)


def _payload_items(data, field, call_id):
    items = {dig(item, "entry"): item for item in as_list(dig(data, field)) if isinstance(item, dict)}

    def item(entry):
        if entry["key"] not in items:
            raise SourceUnreadable(f"{TOOL} {call_id}: payload without entry {entry['key']}")
        return items[entry["key"]]

    return item


def _relayed(item, method, path):
    if dig(item, "ok") is True:
        return item
    status = dig(item, "status")
    if isinstance(status, int) and not isinstance(status, bool):
        raise SourceUnreadable(f"HTTP {status} {method} {path}", status)
    error = dig(item, "error")
    raise SourceUnreadable(f"{method} {path}: {error if isinstance(error, str) and ERROR_CLASS.fullmatch(error) else 'Error'}")


def _relay_monitor(entry, item, app):
    path = _monitor_path(entry)
    return _monitor_record(entry, dig(_monitor_call(_relayed, item, "GET", path), "monitor"), path, app)


def _aggregate_response(responses, call_id):
    if call_id not in responses:
        raise SourceUnreadable(f"{AGGREGATE_TOOL} {call_id}: no saved response")
    return _aggregate_table(responses[call_id], call_id)


def _aggregate_table(text, call_id):
    where = f"{AGGREGATE_TOOL} {call_id}"
    total, table = TOTAL_BUCKETS.search(text), TABLE.search(text)
    if total is None:
        raise SourceUnreadable(f"{where}: response without a bucket count")
    if table is None:
        raise SourceUnreadable(f"{where}: response without a table")
    buckets = int(total.group(1))
    if buckets > GROUP_CAP:
        raise PartialRead(GROUP_CAP_PARTIAL)
    lines = [line for line in table.group(1).splitlines() if line.strip()]
    if not lines or lines[0] != AGGREGATE_HEADER:
        raise SourceUnreadable(f"{where}: table header differs from {AGGREGATE_HEADER!r}")
    rows = [_aggregate_row(line, number, where) for number, line in enumerate(lines[1:], 1)]
    if len(rows) != buckets:
        raise SourceUnreadable(f"{where}: table holds {len(rows)} rows for {buckets} buckets")
    seen = {}
    for monitor, count, first, last in rows:
        if monitor in seen:
            raise SourceUnreadable(f"{where}: monitor {clean_text(monitor, STATE_CAP)} listed twice")
        seen[monitor] = {"monitor": monitor, "count": count, "first_ts_ms": first, "last_ts_ms": last}
    transitions = [item for monitor, item in seen.items() if MONITOR_ID.fullmatch(monitor)]
    return _events_read(transitions, max((last for _, _, _, last in rows), default=None))


def _aggregate_row(line, number, where):
    cells = line.split("\t")
    if len(cells) == 4 and all(INTEGER_TEXT.fullmatch(cell) for cell in cells[1:]):
        count, first, last = (int(cell) for cell in cells[1:])
        if count >= 1 and first <= last:
            return cells[0], count, first, last
    raise SourceUnreadable(f"{where}: unreadable table row {number}")


def _relay_discovery(source, data, app, call_id):
    if not source.get("discovery_query"):
        return _discovery(())
    search = dig(data, "discovery")
    if not isinstance(search, dict):
        raise SourceUnreadable(f"{TOOL} {call_id}: payload without discovery")
    return _discovery(_relay_search_pages(search, app))


def _relay_search_pages(search, app):
    for page in as_list(dig(search, "pages")):
        yield _search_page(page, app)[0]
    body = _relayed(search, "GET", SEARCH_PATH)
    if dig(body, "partial") is not None:
        raise PartialRead(PAGE_CAP_PARTIAL)


def _relay_event_monitors(data, app, call_id, ids):
    found = dig(data, "event_monitors")
    if not isinstance(found, dict):
        raise SourceUnreadable(f"{TOOL} {call_id}: payload without event_monitors")
    reads = [read for read in as_list(dig(found, "reads")) if isinstance(read, dict) and dig(read, "id") in ids]
    monitors, failure = _read_event_monitors(reads, lambda read: _relay_event_monitor(read, app))
    return monitors, dig(found, "capped") is True, failure


def _relay_event_monitor(read, app):
    monitor_id = dig(read, "id")
    path = MONITOR_PATH + monitor_id
    return _event_monitor_record(monitor_id, dig(_monitor_call(_relayed, read, "GET", path), "monitor"), path, app)


def _relay_metric(entry, item, window, call_id):
    hourly = entry["read"] == "hourly"
    body = _entry_call(_relayed, item, "POST", TIMESERIES_PATH if hourly else SCALAR_PATH)
    record = _metric_record(entry, {"data": {"attributes": dig(body, "timeseries" if hourly else "scalar")}})
    return _with_trend(entry, record, window, lambda: _relay_trend(entry, item, call_id))


def _relay_trend(entry, item, call_id):
    trend = dig(item, "trend")
    if not isinstance(trend, dict):
        raise SourceUnreadable(f"{TOOL} {call_id}: payload without trend for entry {entry['key']}")
    body = _entry_call(_relayed, trend, "POST", TIMESERIES_PATH)
    return {"data": {"attributes": dig(body, "timeseries")}}


def _require_links_base(source):
    config = source.get("provider_config") or {}
    if config.get("links_base"):
        return config["links_base"].rstrip("/")
    base_url = dig(config, "api", "base_url")
    if base_url:
        return _app_url(base_url)
    raise SourceUnreadable(f"links_base missing in providers.{source['provider']}")


def _fetch_monitors(source, window, cursor, entries, http):
    app = _require_links_base(source)
    read, statuses = _read_entries(entries, lambda entry: _read_monitor(entry, http, app))
    result = _monitors_result(cursor, read, statuses, _read_events(source, window, cursor, http))
    discovery = _api_discovery(source, http, app)
    ids, capped = _event_monitor_ids(entries, result["records"]["transitions"], discovery["discovered"])
    monitors, failure = _read_event_monitors(ids, lambda monitor_id: _read_event_monitor(monitor_id, http, app))
    return _with_discovery(result, _with_event_monitors(discovery, monitors, capped, failure))


def _with_discovery(result, discovery):
    return {**result, "records": {**result["records"], **discovery}}


def _with_event_monitors(discovery, monitors, capped, failure):
    discovered = sorted(discovery["discovered"] + monitors, key=lambda monitor: monitor["id"])
    status = {"read": False, "reason": failure} if failure is not None and discovery["discovery"]["read"] else discovery["discovery"]
    return {"discovered": discovered, "discovery": {**status, **({"event_monitors_capped": True} if capped else {})}}


def _id_order(monitor_id):
    return len(monitor_id), monitor_id


def _event_monitor_ids(entries, transitions, discovered):
    covered = {entry["monitor"] for entry in entries} | {monitor["id"] for monitor in discovered}
    ordered = sorted({item["monitor"] for item in transitions} - covered, key=_id_order)
    return ordered[:EVENT_MONITOR_CAP], len(ordered) > EVENT_MONITOR_CAP


def _read_event_monitor(monitor_id, http, app):
    path = MONITOR_PATH + monitor_id
    return _event_monitor_record(monitor_id, _monitor_call(http.get, path), path, app)


def _event_monitor_record(monitor_id, body, path, app):
    return _monitor_record({"monitor": monitor_id}, body, path, app, keep_unknown_state=True)


def _read_event_monitors(items, read):
    monitors, failure = [], None
    for item in items:
        try:
            monitors.append(read(item))
        except EntryMissing:
            continue
        except (SourceUnreadable, EntryFailed) as exc:
            failure = failure or str(exc)
    return monitors, failure


def _monitors_result(cursor, read, statuses, events):
    monitors = {record["id"]: record for record in read.values()}
    stored = cursor.get("events_ts_ms")
    newest = max((point for point in (stored, events["newest_ts_ms"]) if point is not None), default=None)
    states = {**(cursor.get("monitors") or {}), **{key: record["state"] for key, record in monitors.items()}}
    return {
        "records": {"monitors": [monitors[key] for key in sorted(monitors)], "transitions": events["transitions"]},
        "cursor": {"events_ts_ms": newest, "monitors": states},
        "entries": statuses,
    }


def _fetch_metrics(window, cursor, entries, http):
    read, statuses = _read_entries(entries, lambda entry: _read_metric(entry, window, http))
    return _metrics_result(cursor, read, statuses)


def _metrics_result(cursor, read, statuses):
    values = {key: record["value"] for key, record in read.items() if record["value"] is not None}
    return {
        "records": {"metrics": [read[key] for key in sorted(read)]},
        "cursor": {"metrics": {**(cursor.get("metrics") or {}), **values}},
        "entries": statuses,
    }


def _read_entries(entries, read):
    records, statuses = {}, {}
    for entry in entries:
        try:
            records[entry["key"]] = read(entry)
        except EntryFailed as exc:
            statuses[entry["key"]] = {"status": "failed", "reason": str(exc)}
        except EntryMissing as exc:
            statuses[entry["key"]] = {"status": "missing", "reason": str(exc)}
        else:
            statuses[entry["key"]] = {"status": "ok", "reason": None}
    return records, statuses


def _entry_call(call, *args):
    try:
        return call(*args)
    except SourceUnreadable as exc:
        if exc.status is None or exc.status in SOURCE_LEVEL_STATUSES:
            raise
        raise EntryFailed(str(exc), exc.status) from None


def _monitor_call(call, *args):
    try:
        return _entry_call(call, *args)
    except EntryFailed as exc:
        if exc.status == NOT_FOUND:
            raise EntryMissing(NOT_FOUND_REASON) from None
        raise


def _monitor_path(entry):
    if not MONITOR_ID.fullmatch(entry["monitor"]):
        raise EntryFailed(f"monitor id {entry['monitor']} is not a number")
    return MONITOR_PATH + entry["monitor"]


def _read_monitor(entry, http, app):
    path = _monitor_path(entry)
    return _monitor_record(entry, _monitor_call(http.get, path), path, app)


def _monitor_record(entry, body, path, app, keep_unknown_state=False):
    state = dig(body, "overall_state")
    if not isinstance(state, str):
        raise EntryFailed(f"GET {path}: response without overall_state")
    if state not in roles.MONITOR_STATES and not keep_unknown_state:
        raise EntryFailed(f"GET {path}: unknown monitor state: {clean_text(state, STATE_CAP)}")
    monitor_id = str(body.get("id", entry["monitor"]))
    if monitor_id != entry["monitor"]:
        raise EntryFailed(f"GET {path}: response id {monitor_id} differs from monitor {entry['monitor']}")
    return _monitor(monitor_id, body, state, app)


def _monitor(monitor_id, body, state, app):
    return {
        "id": monitor_id,
        "name": str(body.get("name") or ""),
        "state": state,
        "priority": _integer(dig(body, "priority")),
        "link": f"{app}/monitors/{monitor_id}",
    }


def _integer(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _api_discovery(source, http, app):
    query = source.get("discovery_query")
    return _discovery(_search_pages(query, http, app) if query else ())


def _discovery(pages):
    found, discovery = {}, {"read": True, "reason": None}
    try:
        for page in pages:
            for monitor in page:
                found.setdefault(monitor["id"], monitor)
    except SourceUnreadable as exc:
        discovery = {"read": False, "reason": str(exc)}
    return {"discovered": [found[key] for key in sorted(found)], "discovery": discovery}


def _search_pages(query, http, app):
    params = {"query": query, "per_page": str(SEARCH_PAGE_SIZE)}
    for page in range(PAGE_CAP):
        body = http.get(SEARCH_PATH, {**params, "page": str(page)})
        monitors, page_count = _search_page(body, app)
        yield monitors
        if page + 1 >= page_count:
            return
    raise PartialRead(PAGE_CAP_PARTIAL)


def _search_page(body, app):
    items, page_count = dig(body, "monitors"), _integer(dig(body, "metadata", "page_count"))
    if not isinstance(items, list) or page_count is None:
        raise SourceUnreadable(f"GET {SEARCH_PATH}: response without monitors or page_count")
    return [_found_monitor(item, app) for item in items], page_count


def _found_monitor(item, app):
    monitor_id = str(dig(item, "id"))
    if not MONITOR_ID.fullmatch(monitor_id):
        raise SourceUnreadable(f"GET {SEARCH_PATH}: monitor without a numeric id")
    state = dig(item, "status")
    if not isinstance(state, str):
        raise SourceUnreadable(f"GET {SEARCH_PATH}: monitor without a state")
    return _monitor(monitor_id, item, state, app)


def _events_from(window, cursor):
    stored = cursor.get("events_ts_ms")
    start = window["from_ts"] * 1000
    return max(stored + 1, start) if stored is not None else start


def _read_events(source, window, cursor, http):
    scope = source.get("scope_filter")
    params = {
        **({"filter[query]": scope} if scope else {}),
        "filter[from]": str(_events_from(window, cursor)),
        "filter[to]": str(window["to_ts"] * 1000),
        "sort": "timestamp",
        "page[limit]": str(EVENTS_PAGE_LIMIT),
    }
    events, page = [], params
    for _ in range(EVENTS_PAGE_CAP):
        body = http.get(EVENTS_PATH, page)
        events.extend(_page_events(body))
        after = dig(body, "meta", "page", "after")
        if not after:
            return _aggregate_events(events, window)
        page = {**params, "page[cursor]": after}
    raise PartialRead(PAGE_CAP_PARTIAL)


def _page_events(body):
    return [event for event in (_event(item) for item in as_list(dig(body, "data"))) if event is not None]


def _event(item):
    ts_ms = _timestamp_ms(dig(item, "attributes", "timestamp"))
    if ts_ms is None:
        ts_ms = _timestamp_ms(dig(item, "attributes", "attributes", "timestamp"))
    if ts_ms is None:
        return None
    monitor = dig(item, "attributes", "attributes", "monitor_id")
    return ts_ms, None if monitor is None else str(monitor)


def _aggregate_events(events, window):
    low, high = window["from_ts"] * 1000, window["to_ts"] * 1000
    stamps = {}
    for ts_ms, monitor in events:
        if monitor is not None and MONITOR_ID.fullmatch(monitor) and low <= ts_ms <= high:
            stamps.setdefault(monitor, []).append(ts_ms)
    transitions = [{"monitor": monitor, "count": len(found), "first_ts_ms": min(found), "last_ts_ms": max(found)} for monitor, found in stamps.items()]
    return _events_read(transitions, max((ts_ms for ts_ms, _ in events), default=None))


def _events_read(transitions, newest):
    return {"transitions": sorted(transitions, key=lambda item: _id_order(item["monitor"])), "newest_ts_ms": newest}


def _timestamp_ms(value):
    number = _number(value)
    if number is not None:
        return int(number)
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.datetime.fromisoformat(_iso(value))
    except ValueError:
        return None
    return (moment.replace(tzinfo=moment.tzinfo or datetime.timezone.utc) - EPOCH) // MILLISECOND


def _iso(text):
    text = ISO_FRACTION.sub(lambda match: "." + (match.group(1) + "000000")[:6], text)
    text = re.sub(r"Z$", "+00:00", text)
    return ISO_COMPACT_OFFSET.sub(r"\1:\2", text)


def _read_metric(entry, window, http):
    return _with_trend(entry, _read_window(entry, window, http), window, lambda: _read_trend(entry, http))


def _read_window(entry, window, http):
    lookback = entry.get("span")
    span = _span_ms(lookback or window)
    if entry["read"] != "hourly":
        return _metric_record(entry, _entry_call(http.post, SCALAR_PATH, _scalar_body(entry, span)))
    body = _entry_call(http.post, TIMESERIES_PATH, _timeseries_body(entry, span, DAY_MS if lookback else HOUR_MS))
    return _metric_record(entry, body)


def _read_trend(entry, http):
    return _entry_call(http.post, TIMESERIES_PATH, _timeseries_body(entry, _span_ms(entry["trend_span"]), HOUR_MS))


def _span_ms(bounds):
    return {"from": bounds["from_ts"] * 1000, "to": bounds["to_ts"] * 1000}


def _with_trend(entry, record, window, read):
    if not entry.get("trend_span"):
        return record
    try:
        return {**record, **_trend(entry, read(), load_zone(window["timezone"]))}
    except EntryFailed as exc:
        return {**record, "trend": None, "trend_reason": str(exc)}


def _trend(entry, body, zone):
    days = {}
    for point in _points(body):
        if point["value"] is not None:
            days.setdefault(local_date(point["ts"], zone).isoformat(), []).append(point["value"])
    if not days:
        return {"trend": None, "trend_reason": NO_DATAPOINTS}
    aggregate = TREND_AGGREGATORS[entry["aggregator"]]
    return {"trend": [{"day": day, "value": aggregate(days[day])} for day in sorted(days)], "trend_reason": None}


def _metric_record(entry, body):
    if entry["read"] == "hourly":
        record = {"key": entry["key"], **_hourly(body)}
        return {**record, "hourly": [], "daily": record["hourly"]} if entry.get("span") else record
    return {"key": entry["key"], **(_top(body) if entry["read"] == "top" else _scalar(body))}


def _scalar_body(entry, span):
    query = {"data_source": "metrics", "query": entry["query"], "name": "a", "aggregator": entry["aggregator"]}
    formula = {"formula": "a", "limit": {"count": entry.get("top") or 1, "order": "desc"}}
    return {"data": {"type": "scalar_request", "attributes": {**span, "queries": [query], "formulas": [formula]}}}


def _timeseries_body(entry, span, interval):
    query = {"data_source": "metrics", "query": entry["query"], "name": "a"}
    attributes = {**span, "interval": interval, "queries": [query], "formulas": [{"formula": "a"}]}
    return {"data": {"type": "timeseries_request", "attributes": attributes}}


def _columns(body, kind):
    columns = as_list(dig(body, "data", "attributes", "columns"))
    return [as_list(dig(column, "values")) for column in columns if dig(column, "type") == kind]


def _scalar(body):
    numbers = next(iter(_columns(body, "number")), [])
    return {"value": _number(numbers[0]) if numbers else None, "hourly": [], "groups": []}


def _top(body):
    numbers = next(iter(_columns(body, "number")), [])
    rows = zip(*_columns(body, "group"), numbers)
    groups = [{"group": ",".join(str(tag) for tags in row[:-1] for tag in as_list(tags)), "value": _number(row[-1])} for row in rows]
    groups.sort(key=lambda group: (group["value"] is None, -(group["value"] or 0), group["group"]))
    return {"value": groups[0]["value"] if groups else None, "hourly": [], "groups": groups}


def _points(body):
    attributes = dig(body, "data", "attributes")
    series = as_list(dig(attributes, "values"))
    first = as_list(series[0]) if series else []
    times = [_number(ts) for ts in as_list(dig(attributes, "times"))]
    if None in times:
        raise EntryFailed(f"POST {TIMESERIES_PATH}: response time is not a number")
    return sorted(
        ({"ts": int(ts) // 1000, "value": _number(value)} for ts, value in zip(times, first)), key=lambda point: point["ts"]
    )


def _hourly(body):
    points = _points(body)
    present = [point["value"] for point in points if point["value"] is not None]
    return {"value": max(present, default=None), "hourly": points, "groups": []}


def _app_url(base_url):
    parts = urllib.parse.urlsplit(base_url)
    host = parts.netloc
    if host.startswith("api."):
        rest = host[len("api.") :]
        host = rest if rest.count(".") >= 2 else "app." + rest
    return f"{parts.scheme}://{host}"


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None
