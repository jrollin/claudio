import { client, v1, v2 } from "@datadog/datadog-api-client";

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

function timestamp(value) {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.toISOString();
  }
  return value;
}

function eventItem(item) {
  const outer = item.attributes || {};
  const inner = outer.attributes || {};
  return {
    id: item.id,
    attributes: {
      timestamp: timestamp(outer.timestamp),
      attributes: { monitor_id: inner.monitorId, timestamp: inner.timestamp },
    },
  };
}

async function readEvents(api) {
  const request = {
    filterFrom: String(params.events_from_ms),
    filterTo: String(params.window.to_ms),
    sort: "timestamp",
    pageLimit: params.page_limit,
  };
  if (params.scope_filter) {
    request.filterQuery = params.scope_filter;
  }
  const pages = [];
  let cursor = null;
  while (pages.length < params.page_cap) {
    const body = await api.listEvents(cursor === null ? request : { ...request, pageCursor: cursor });
    const after = (body.meta && body.meta.page && body.meta.page.after) || null;
    pages.push({ data: (body.data || []).map(eventItem), after });
    if (after === null) {
      return { ok: true, pages, partial: null };
    }
    cursor = after;
  }
  return { ok: true, pages, partial: "page cap" };
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

function eventMonitorIds(events, discovery) {
  const covered = new Set(params.entries.map((entry) => entry.monitor));
  for (const page of discovery ? discovery.pages : []) {
    for (const item of page.monitors || []) {
      covered.add(String(item.id));
    }
  }
  const named = new Set();
  for (const page of events.pages) {
    for (const item of page.data) {
      const inner = item.attributes.attributes;
      const dated = item.attributes.timestamp != null || inner.timestamp != null;
      const id = inner.monitor_id == null ? "" : String(inner.monitor_id);
      if (dated && MONITOR_ID.test(id) && !covered.has(id)) {
        named.add(id);
      }
    }
  }
  return Array.from(named).sort((a, b) => a.length - b.length || (a < b ? -1 : a > b ? 1 : 0));
}

async function readEventMonitors(api, events, discovery) {
  const ids = eventMonitorIds(events, discovery);
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
    const events = await guarded(() => readEvents(new v2.EventsApi(cfg)));
    if (events.ok === false) {
      return { monitors, events };
    }
    const discovery = params.discovery_query ? await readDiscovery(monitorsApi) : null;
    const eventMonitors = await readEventMonitors(monitorsApi, events, discovery);
    return { monitors, events, ...(discovery ? { discovery } : {}), event_monitors: eventMonitors };
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
