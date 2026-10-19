import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from unittest import mock

import roles
import state
from providers import _http, datadog
from providers.datadog_support import (
    APP,
    BY_SERVICE,
    CHECKOUT,
    DISCOVERING,
    DISK,
    FRESH,
    FROM_MS,
    HOURLY,
    LOOKBACK_FROM_MS,
    METRICS,
    MONITORS,
    NO_METRICS,
    NOT_FOUND,
    ODD,
    OK,
    P95,
    QUERY,
    QUEUE,
    STORED_TS,
    TO_MS,
    TREND_FROM_MS,
    TREND_SERIES,
    TREND_SPAN,
    TREND_WINDOW,
    WINDOW,
    collection,
    configured,
    discover,
    event,
    events_page,
    failed,
    fixture,
    found,
    lookback,
    monitor_body,
    named_by_event,
    ok,
    run,
    search_page,
    series,
    series_response,
    served,
    status,
    trended,
)

CONNECTOR = "obs-connector"
SLOT = "__PARAMS_LITERAL__"
PARAMS_LINE = re.compile(r"^const PARAMS_TEXT = (.*);$", re.MULTILINE)
DIAGNOSTICS = {"api_calls": {"total": 3, "succeeded": 3, "failed": 0}, "console_truncated": False}
NO_EVENT_MONITORS = {"capped": False, "reads": []}
HOSTILE = '"; globalThis.leak = 1; //\n</script> caf\u00e9 \U0001f600 \u2028 \u2029 \\'
LONE_SURROGATE = "\ud83d"
CHECKOUT_ERRORS = found(201, name="Checkout errors", priority=1)
DISK_USAGE = found(203, "Warn", name="Disk usage")


AGGREGATE_HEAD = "<METADATA>\n  <total_buckets>{}</total_buckets>\n</METADATA>\n<TSV_DATA>\n"
TABLE_HEADER = "@monitor_id\tcount\tfirst_ts\tlast_ts"


def aggregate_text(*rows, total=None):
    lines = [TABLE_HEADER, *("\t".join(str(cell) for cell in row) for row in rows)]
    return AGGREGATE_HEAD.format(len(rows) if total is None else total) + "\n".join(lines) + "\n</TSV_DATA>\n"


EMPTY_AGGREGATE = aggregate_text()
AGGREGATE_FIXTURE = fixture("aggregate_events.txt").decode("ascii")


def aggregate_naming(*monitor_ids):
    return aggregate_text(*((number, 1, FROM_MS + 1000, FROM_MS + 1000) for number in monitor_ids))


def aggregate_call(source, entries, cursor, window=WINDOW):
    return datadog.plan(source, window, cursor, entries, {}, CONNECTOR)["calls"][0]


def script_call(source, entries, cursor, window=WINDOW, aggregate=EMPTY_AGGREGATE):
    first = aggregate_call(source, entries, cursor, window)
    if source["kind"] != "monitors":
        return first
    return datadog.plan(source, window, cursor, entries, {first["id"]: aggregate}, CONNECTOR)["calls"][0]


def embedded(call):
    return PARAMS_LINE.search(call["arguments"]["code"]).group(1)


def stringified(document):
    return json.dumps(document, separators=(",", ":"), ensure_ascii=True)


def wrapped(value, **fields):
    wrapper = {"outcome": "success", "success": True, "value": value, "duration": "199ms", "diagnostics": DIAGNOSTICS}
    return json.dumps({**wrapper, **fields})


def script_value(payload, digest):
    return {"payload": payload, "checksum": roles.fnv1a32(payload), "digest": digest}


def parse_text(source, entries, cursor, text, window=WINDOW, aggregate=EMPTY_AGGREGATE):
    call = script_call(source, entries, cursor, window, aggregate)
    responses, digests = {call["id"]: text}, {call["id"]: call["digest"]}
    if source["kind"] == "monitors":
        responses[f"{source['name']}-1"], digests[f"{source['name']}-1"] = aggregate, None
    return datadog.parse(source, window, cursor, entries, responses, digests)


def relay(source, entries, cursor, document, window=WINDOW, aggregate=EMPTY_AGGREGATE):
    digest = script_call(source, entries, cursor, window, aggregate)["digest"]
    return parse_text(source, entries, cursor, wrapped(script_value(stringified(document), digest)), window, aggregate)


def relay_fixture(name):
    return json.loads(fixture(name))


def monitor_failure(key, code, error="ApiException"):
    return {"entry": key, "ok": False, "status": code, "error": error}


def monitors_payload(*items, event_monitors=NO_EVENT_MONITORS):
    return {"monitors": list(items), "event_monitors": event_monitors}


def metric_failure(key, code):
    return {"metrics": [{"entry": key, "ok": False, "status": code, "error": "ApiException"}]}


def relayed_monitor(state_name, key="monitor-queue", monitor_id=102, name="Queue depth"):
    return {"entry": key, "ok": True, "monitor": {"id": monitor_id, "name": name, "overall_state": state_name}}


def relayed_checkout():
    return relayed_monitor("OK", "monitor-checkout", 101, "Checkout latency")


def relay_page(page_count, *monitors):
    return {"monitors": list(monitors), "metadata": {"page_count": page_count}}


def search_outcome(*pages, **tail):
    return {"ok": True, "pages": list(pages), "partial": None, **tail}


def search_failure(code, *pages, error="ApiException"):
    return {"ok": False, "status": code, "error": error, "pages": list(pages)}


def with_discovery(search, *items):
    return {**monitors_payload(*items), "discovery": search}


def relay_discovery(search):
    return relay(DISCOVERING, [], FRESH, with_discovery(search))


STUB_MODULE = """import { writeFileSync } from "node:fs";

const fake = JSON.parse(process.env.FAKE);
const failure = (code) => Object.assign(new Error("stubbed"), { code });
class MonitorsApi {
  async getMonitor({ monitorId }) {
    const found = fake.monitors[String(monitorId)];
    if (found.error) throw failure(found.error);
    return found;
  }
  async searchMonitors({ page }) {
    return fake.search[Math.min(page, fake.search.length - 1)];
  }
}
let timeseriesCalls = 0;
class MetricsApi {
  async queryTimeseriesData() {
    timeseriesCalls += 1;
    writeFileSync("timeseries_calls", String(timeseriesCalls));
    const next = fake.sequence ? fake.sequence[timeseriesCalls - 1] : fake.timeseries;
    if (next.error) throw failure(next.error);
    return next;
  }
  async queryScalarData() {
    return fake.scalar;
  }
}
export const client = { createConfiguration: () => ({}) };
export const v1 = { MonitorsApi };
export const v2 = { MetricsApi };
"""
SCRIPT_RETURN = "return { payload"
SCRIPT_RESULT = "console.log(JSON.stringify({ payload, checksum: fnv(payload), digest: fnv(PARAMS_TEXT) }));\n"


def sdk_monitor(monitor_id, status_text, name):
    return {"id": monitor_id, "name": name, "status": status_text, "type": "metric alert", "tags": []}


def sdk_page(page_count, *monitors):
    return {"monitors": list(monitors), "metadata": {"page": 0, "pageCount": page_count, "perPage": 100, "totalCount": len(monitors)}}


def served_search(pages):
    return [
        served({"monitors": body["monitors"], "metadata": {"page": number, "page_count": body["metadata"]["pageCount"], "per_page": 100}})
        for number, body in enumerate(pages)
    ]


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class RelayScriptExecutionTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        package = os.path.join(self.dir, "node_modules", "@datadog", "datadog-api-client")
        os.makedirs(package)
        with open(os.path.join(package, "package.json"), "w", encoding="utf-8") as handle:
            json.dump({"name": "@datadog/datadog-api-client", "type": "module", "exports": "./index.js"}, handle)
        with open(os.path.join(package, "index.js"), "w", encoding="utf-8") as handle:
            handle.write(STUB_MODULE)

    def relayed(self, source, entries, cursor, fake, window=WINDOW, aggregate=EMPTY_AGGREGATE):
        call = script_call(source, entries, cursor, window, aggregate)
        head = call["arguments"]["code"].rsplit(SCRIPT_RETURN, 1)[0]
        script = os.path.join(self.dir, "script.mjs")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(head + SCRIPT_RESULT)
        done = subprocess.run(
            ["node", script], cwd=self.dir, env={**os.environ, "FAKE": json.dumps(fake)}, capture_output=True, text=True, timeout=30, check=False
        )
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        return parse_text(source, entries, cursor, wrapped(json.loads(done.stdout)), window, aggregate)

    def test_paged_discovery_with_a_priority_lookup_and_a_missing_monitor_equals_the_api_transport(self):
        search = [
            sdk_page(2, sdk_monitor(203, "Warn", "Disk usage"), sdk_monitor(201, "Alert", "Checkout errors")),
            sdk_page(2, sdk_monitor(202, "No Data", "Cache hit ratio")),
        ]
        monitors = {"102": {"id": 102, "name": "Queue depth", "overallState": "Alert", "priority": 2}, "101": {"error": 404}}
        rest_monitor = {"id": 102, "name": "Queue depth", "overall_state": "Alert", "priority": 2}

        relayed = self.relayed(DISCOVERING, [QUEUE, CHECKOUT], FRESH, {"monitors": monitors, "search": search})
        _, api = run(DISCOVERING, [QUEUE, CHECKOUT], FRESH, served(rest_monitor), status(404), ok("events_empty.json"), *served_search(search))

        self.assertEqual(relayed, api)
        self.assertEqual(len(relayed["records"]["discovered"]), 3)

    def test_event_named_monitors_equal_the_api_transport(self):
        search = [sdk_page(1, sdk_monitor(201, "Alert", "Checkout errors"))]
        monitors = {
            "102": {"id": 102, "name": "Queue depth", "overallState": "Alert", "priority": 2},
            "301": {"id": 301, "name": "Monitor 301", "overallState": "OK", "priority": 3},
            "302": {"error": 404},
        }
        rest_queue = {"id": 102, "name": "Queue depth", "overall_state": "Alert", "priority": 2}

        relayed = self.relayed(DISCOVERING, [QUEUE], FRESH, {"monitors": monitors, "search": search}, aggregate=aggregate_naming(302, 301, 201, 102))
        _, api = run(
            DISCOVERING,
            [QUEUE],
            FRESH,
            served(rest_queue),
            named_by_event(302, 301, 201, 102),
            *served_search(search),
            monitor_body(301, "OK", priority=3),
            status(404),
        )

        self.assertEqual(relayed, api)
        self.assertEqual([(monitor["id"], monitor["state"]) for monitor in relayed["records"]["discovered"]], [("201", "Alert"), ("301", "OK")])

    def test_failed_and_unrecognised_event_monitors_equal_the_api_transport(self):
        monitors = {"301": {"error": 403}, "302": {"id": 302, "name": "Monitor 302", "overallState": "Weird"}, "303": {"error": 404}}

        relayed = self.relayed(MONITORS, [], FRESH, {"monitors": monitors, "search": []}, aggregate=aggregate_naming(301, 302, 303))
        _, api = run(MONITORS, [], FRESH, named_by_event(301, 302, 303), status(403), monitor_body(302, "Weird"), status(404))

        self.assertEqual(relayed, api)
        self.assertEqual(relayed["records"]["discovery"], {"read": False, "reason": "HTTP 403 GET /api/v1/monitor/301"})
        self.assertEqual([(monitor["id"], monitor["state"]) for monitor in relayed["records"]["discovered"]], [("302", "Weird")])

    def test_event_monitors_beyond_the_cap_equal_the_api_transport(self):
        numbers = list(range(1051, 1000, -1))
        monitors = {str(number): {"id": number, "name": f"Monitor {number}", "overallState": "OK"} for number in numbers}

        relayed = self.relayed(MONITORS, [], FRESH, {"monitors": monitors, "search": []}, aggregate=aggregate_naming(*numbers))
        _, api = run(MONITORS, [], FRESH, named_by_event(*numbers), *(monitor_body(number) for number in sorted(numbers)[:50]))

        self.assertEqual(relayed, api)
        self.assertEqual(relayed["records"]["discovery"], {"read": True, "reason": None, "event_monitors_capped": True})

    def test_discovery_stops_at_the_page_cap_like_the_api_transport(self):
        capped = [sdk_page(21, sdk_monitor(201, "Alert", "Checkout errors"))]

        relayed = self.relayed(DISCOVERING, [], FRESH, {"monitors": {}, "search": capped})
        _, api = run(DISCOVERING, [], FRESH, ok("events_empty.json"), *served_search(capped * 20))

        self.assertEqual(relayed, api)
        self.assertFalse(relayed["records"]["discovery"]["read"])

    def test_lookback_read_equals_the_api_transport(self):
        series = {"data": {"attributes": {"times": [1759406000000, 1759492400000], "values": [[12.5, None]]}}}
        entries = [lookback(HOURLY)]

        relayed = self.relayed(METRICS, entries, NO_METRICS, {"monitors": {}, "search": [], "timeseries": series})
        _, api = run(METRICS, entries, NO_METRICS, served(series))

        self.assertEqual(relayed, api)
        self.assertEqual(relayed["records"]["metrics"][0]["daily"][0]["value"], 12.5)

    def test_trend_reads_equal_the_api_transport(self):
        entries = [trended(HOURLY, "max"), trended(P95, "avg")]
        sdk = {"data": {"attributes": TREND_SERIES}}
        fake = {"monitors": {}, "search": [], "sequence": [json.loads(fixture("timeseries.json")), sdk, sdk], "scalar": json.loads(fixture("scalar.json"))}

        relayed = self.relayed(METRICS, entries, NO_METRICS, fake, TREND_WINDOW)
        _, api = run(
            METRICS, entries, NO_METRICS, ok("timeseries.json"), series_response(TREND_SERIES), ok("scalar.json"), series_response(TREND_SERIES), window=TREND_WINDOW
        )

        self.assertEqual(relayed, api)
        self.assertEqual([len(record["trend"]) for record in relayed["records"]["metrics"]], [2, 2])

    def test_failed_trend_read_equals_the_api_transport(self):
        entries = [trended(HOURLY, "max")]
        fake = {"monitors": {}, "search": [], "sequence": [json.loads(fixture("timeseries.json")), {"error": 500}]}

        relayed = self.relayed(METRICS, entries, NO_METRICS, fake, TREND_WINDOW)
        _, api = run(METRICS, entries, NO_METRICS, ok("timeseries.json"), status(500), status(500), window=TREND_WINDOW)

        self.assertEqual(relayed, api)
        self.assertEqual(relayed["records"]["metrics"][0]["trend_reason"], "HTTP 500 POST /api/v2/query/timeseries")

    def test_unauthorized_trend_read_fails_the_source_like_the_api_transport(self):
        entries = [trended(HOURLY, "max")]
        fake = {"monitors": {}, "search": [], "sequence": [json.loads(fixture("timeseries.json")), {"error": 401}]}

        with self.assertRaises(_http.SourceUnreadable) as relayed:
            self.relayed(METRICS, entries, NO_METRICS, fake, TREND_WINDOW)
        with self.assertRaises(_http.SourceUnreadable) as api:
            run(METRICS, entries, NO_METRICS, ok("timeseries.json"), status(401), window=TREND_WINDOW)

        self.assertEqual((str(relayed.exception), relayed.exception.status), (str(api.exception), api.exception.status))


    def test_failed_window_read_skips_the_trend_read(self):
        entries = [trended(HOURLY, "max")]
        fake = {"monitors": {}, "search": [], "sequence": [{"error": 400}, {"data": {"attributes": TREND_SERIES}}]}

        relayed = self.relayed(METRICS, entries, NO_METRICS, fake, TREND_WINDOW)

        with open(os.path.join(self.dir, "timeseries_calls"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "1")
        self.assertEqual(relayed["entries"], {"queue-hourly": failed("HTTP 400 POST /api/v2/query/timeseries")})


class PlanTest(unittest.TestCase):
    def test_first_step_lists_the_aggregate_call_on_the_connector(self):
        step = datadog.plan(MONITORS, WINDOW, FRESH, [QUEUE], {}, CONNECTOR)

        self.assertEqual(
            [(call["id"], call["connector"], call["tool"]) for call in step["calls"]], [("alerts-1", CONNECTOR, "aggregate_events")]
        )

    def test_aggregate_call_groups_the_alert_events_of_the_window_by_monitor(self):
        call = aggregate_call(MONITORS, [QUEUE], FRESH)

        self.assertEqual(
            (call["arguments"], call["digest"]),
            (
                {
                    "query": "source:alert env:prod",
                    "from": "2025-10-09T08:53:20Z",
                    "to": "2025-10-09T11:53:20Z",
                    "group_by": {"fields": ["@monitor_id"], "limit": 1000},
                    "computes": [
                        {"field": "*", "aggregation": "COUNT", "output": "count", "sort": "desc"},
                        {"field": "timestamp", "aggregation": "MIN", "output": "first_ts"},
                        {"field": "timestamp", "aggregation": "MAX", "output": "last_ts"},
                    ],
                    "max_tokens": 20000,
                    "telemetry": {"intent": "Count alert events per monitor for a scheduled routine run"},
                },
                None,
            ),
        )

    def test_aggregate_call_queries_the_window_whatever_the_stored_cursor(self):
        stored = aggregate_call(MONITORS, [QUEUE], {"events_ts_ms": STORED_TS, "monitors": {}})["arguments"]

        self.assertEqual((stored["from"], stored["to"]), ("2025-10-09T08:53:20Z", "2025-10-09T11:53:20Z"))

    def test_aggregate_call_carries_the_scope_filter_as_given(self):
        call = aggregate_call({**MONITORS, "scope_filter": HOSTILE}, [], FRESH)

        self.assertEqual(call["arguments"]["query"], HOSTILE)

    def test_aggregate_call_without_a_scope_filter_queries_an_empty_text(self):
        self.assertEqual(aggregate_call({**MONITORS, "scope_filter": ""}, [], FRESH)["arguments"]["query"], "")

    def test_aggregate_response_makes_the_second_step_the_script_call(self):
        step = datadog.plan(MONITORS, WINDOW, FRESH, [QUEUE], {"alerts-1": EMPTY_AGGREGATE}, CONNECTOR)

        self.assertEqual(
            [(call["id"], call["connector"], call["tool"]) for call in step["calls"]], [("alerts-2", CONNECTOR, "execute_code")]
        )

    def test_unreadable_aggregate_response_ends_the_plan_as_an_unreadable_source(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            datadog.plan(MONITORS, WINDOW, FRESH, [QUEUE], {"alerts-1": "no table"}, CONNECTOR)
        self.assertEqual(str(caught.exception), "aggregate_events alerts-1: response without a bucket count")

    def test_aggregate_over_the_group_cap_ends_the_plan_as_partial(self):
        with self.assertRaises(_http.PartialRead) as caught:
            datadog.plan(MONITORS, WINDOW, FRESH, [QUEUE], {"alerts-1": aggregate_text(total=1001)}, CONNECTOR)
        self.assertEqual(str(caught.exception), "partial: group cap")

    def test_monitors_named_by_the_aggregate_are_embedded_without_the_entries(self):
        aggregate = aggregate_naming(1010, 101, 99)

        call = script_call(MONITORS, [CHECKOUT], FRESH, aggregate=aggregate)

        self.assertEqual(json.loads(json.loads(embedded(call)))["event_monitor_ids"], ["99", "1010"])

    def test_monitors_named_by_the_aggregate_are_covered_by_the_plan_digest(self):
        plain = script_call(MONITORS, [QUEUE], FRESH)["digest"]

        self.assertNotEqual(script_call(MONITORS, [QUEUE], FRESH, aggregate=aggregate_naming(301))["digest"], plain)

    def test_first_step_is_not_done(self):
        step = datadog.plan(MONITORS, WINDOW, FRESH, [QUEUE], {}, CONNECTOR)

        self.assertEqual((step["done"], step["partial"]), (False, None))

    def test_call_carries_the_telemetry_intent_and_timeout(self):
        arguments = script_call(MONITORS, [QUEUE], FRESH)["arguments"]

        self.assertEqual(
            {key: value for key, value in arguments.items() if key != "code"},
            {"telemetry": {"intent": "Collect monitors and metrics for a scheduled routine run"}, "timeout": 120},
        )

    def test_none_cursor_plans_the_same_aggregate_call_as_an_empty_cursor(self):
        self.assertEqual(aggregate_call(MONITORS, [QUEUE], None), aggregate_call(MONITORS, [QUEUE], FRESH))

    def test_none_cursor_plans_a_metrics_call(self):
        step = datadog.plan(METRICS, WINDOW, None, [P95], {}, CONNECTOR)

        self.assertEqual([call["id"] for call in step["calls"]], ["metrics-1"])

    def test_monitors_plan_without_a_link_base_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            datadog.plan(configured(MONITORS, {"adapter": "datadog"}), WINDOW, FRESH, [QUEUE], {}, CONNECTOR)
        self.assertEqual(str(caught.exception), "links_base missing in providers.obs")

    def test_saved_script_response_ends_the_plan(self):
        step = datadog.plan(MONITORS, WINDOW, FRESH, [QUEUE], {"alerts-1": EMPTY_AGGREGATE, "alerts-2": "{}"}, CONNECTOR)

        self.assertEqual(step, {"done": True, "partial": None, "calls": []})

    def test_saved_metrics_response_ends_the_plan(self):
        step = datadog.plan(METRICS, WINDOW, FRESH, [P95], {"metrics-1": "{}"}, CONNECTOR)

        self.assertEqual(step, {"done": True, "partial": None, "calls": []})

    def test_monitors_script_embeds_the_entries_and_the_window(self):
        call = script_call(MONITORS, [QUEUE, CHECKOUT], {"events_ts_ms": STORED_TS, "monitors": {}})

        self.assertEqual(
            json.loads(json.loads(embedded(call))),
            {
                "kind": "monitors",
                "entries": [{"key": "monitor-queue", "monitor": "102"}, {"key": "monitor-checkout", "monitor": "101"}],
                "window": {"from_ms": FROM_MS, "to_ms": TO_MS},
                "event_monitor_ids": [],
                "page_cap": _http.PAGE_CAP,
                "interval_ms": 3600000,
                "daily_interval_ms": 86400000,
                "discovery_query": "",
                "search_page_size": 100,
                "event_monitor_cap": 50,
            },
        )

    def test_event_monitor_cap_is_covered_by_the_plan_digest(self):
        plain = script_call(MONITORS, [QUEUE], FRESH)["digest"]

        with mock.patch.object(datadog, "EVENT_MONITOR_CAP", datadog.EVENT_MONITOR_CAP + 1):
            raised = script_call(MONITORS, [QUEUE], FRESH)["digest"]

        self.assertNotEqual(raised, plain)

    def test_discovery_query_is_embedded_in_the_params(self):
        call = script_call(DISCOVERING, [QUEUE], FRESH)

        self.assertEqual(json.loads(json.loads(embedded(call)))["discovery_query"], "status:alert env:prod")

    def test_discovery_query_is_covered_by_the_plan_digest(self):
        plain = script_call(MONITORS, [QUEUE], FRESH)["digest"]

        self.assertNotEqual(script_call(DISCOVERING, [QUEUE], FRESH)["digest"], plain)

    def test_lookback_entry_embeds_its_span_in_milliseconds(self):
        call = script_call(METRICS, [lookback(HOURLY), P95], NO_METRICS)

        spans = [entry.get("span") for entry in json.loads(json.loads(embedded(call)))["entries"]]
        self.assertEqual(spans, [{"from_ms": LOOKBACK_FROM_MS, "to_ms": TO_MS}, None])

    def test_metrics_script_embeds_the_queries_with_their_read(self):
        call = script_call(METRICS, [P95, BY_SERVICE], NO_METRICS)

        self.assertEqual(
            json.loads(json.loads(embedded(call)))["entries"],
            [
                {"key": "checkout-p95", "query": QUERY, "read": "scalar", "aggregator": "avg", "top": 1},
                {"key": "errors-by-service", "query": QUERY, "read": "top", "aggregator": "sum", "top": 5},
            ],
        )

    def test_trend_entry_embeds_its_span_in_milliseconds(self):
        call = script_call(METRICS, [trended(P95, "avg")], NO_METRICS)

        self.assertEqual(json.loads(json.loads(embedded(call)))["entries"][0]["trend_span"], {"from_ms": TREND_FROM_MS, "to_ms": TO_MS})

    def test_entries_without_a_trend_embed_no_span(self):
        call = script_call(METRICS, [P95], NO_METRICS)

        self.assertNotIn("trend_span", json.loads(json.loads(embedded(call)))["entries"][0])

    def test_trend_span_is_covered_by_the_plan_digest(self):
        plain = script_call(METRICS, [trended(P95, "avg")], NO_METRICS)["digest"]
        longer = {**trended(P95, "avg"), "trend_span": {**TREND_SPAN, "from_ts": TREND_SPAN["from_ts"] - 86400}}

        self.assertNotEqual(script_call(METRICS, [longer], NO_METRICS)["digest"], plain)

    def test_digest_hashes_the_embedded_params_text(self):
        call = script_call(MONITORS, [QUEUE], FRESH)

        self.assertEqual(call["digest"], roles.fnv1a32(json.loads(embedded(call))))

    def test_embedded_params_text_is_the_canonical_params_text(self):
        call = script_call(MONITORS, [QUEUE], FRESH)
        text = json.loads(embedded(call))

        self.assertEqual(text, roles.params_text(json.loads(text)))

    def test_script_is_the_golden_template_around_the_params_literal(self):
        source = {**DISCOVERING, "discovery_query": HOSTILE}
        call = script_call(source, [{**QUEUE, "monitor": HOSTILE + LONE_SURROGATE}], FRESH)

        self.assertEqual(call["arguments"]["code"], fixture("script_template.js").decode("ascii").replace(SLOT, embedded(call)))

    def test_hostile_text_stays_inside_the_params_literal(self):
        call = script_call({**DISCOVERING, "discovery_query": HOSTILE}, [], FRESH)

        self.assertEqual(json.loads(json.loads(embedded(call)))["discovery_query"], HOSTILE)

    def test_script_is_ascii(self):
        call = script_call(METRICS, [{**P95, "query": HOSTILE + LONE_SURROGATE}], NO_METRICS)

        self.assertTrue(call["arguments"]["code"].isascii())


class RelayEquivalenceTest(unittest.TestCase):
    STORED = {"events_ts_ms": STORED_TS, "monitors": {"999": "Warn"}}

    def test_monitors_and_paged_events_match_the_api(self):
        pages = (ok("events_page_1.json"), ok("events_page_2.json"))
        _, api = run(MONITORS, [QUEUE, CHECKOUT], self.STORED, ok("monitor_alert.json"), ok("monitor_ok.json"), *pages)

        relayed = relay(MONITORS, [QUEUE, CHECKOUT], self.STORED, relay_fixture("relay_monitors.json"), aggregate=AGGREGATE_FIXTURE)

        self.assertEqual(state.dump(relayed), state.dump(api))

    def test_aggregate_built_from_the_events_of_the_api_read_matches_it(self):
        stamps = [
            (FROM_MS + 1000, 101), (FROM_MS + 5000, 102), (FROM_MS + 2000, 101), (TO_MS, 103), ("2025-10-09T08:55:00.123456789Z", 104),
            ("2025-10-09T10:55:00+0200", 104), (FROM_MS + 3000, None), (FROM_MS + 4000, "web-1"),
        ]
        parsed = {"2025-10-09T08:55:00.123456789Z": 1760000100123, "2025-10-09T10:55:00+0200": 1760000100000}
        rest = [event(f"e{n}", timestamp=ts, attributes={"monitor_id": monitor}) for n, (ts, monitor) in enumerate(stamps)]
        moments = {}
        for ts, monitor in stamps:
            if isinstance(monitor, int):
                moments.setdefault(monitor, []).append(parsed.get(ts, ts))
        rows = [(monitor, len(found), min(found), max(found)) for monitor, found in sorted(moments.items())]
        _, api = run(MONITORS, [], FRESH, served({"data": rest[:5], "meta": {"page": {"after": "p1"}}}), events_page(*rest[5:]), *(monitor_body(number) for number in moments))

        relayed = relay(
            MONITORS, [], FRESH, monitors_payload(event_monitors={"capped": False, "reads": [event_read(number) for number in moments]}), aggregate=aggregate_text(*rows)
        )

        self.assertEqual(state.dump(relayed), state.dump(api))
        self.assertEqual([(item["monitor"], item["count"]) for item in relayed["records"]["transitions"]], [("101", 2), ("102", 1), ("103", 1), ("104", 2)])
        self.assertEqual(relayed["cursor"]["events_ts_ms"], TO_MS)

    def test_monitor_entry_errors_match_the_api(self):
        reads = (status(404), ok("monitor_ok.json"), ok("monitor_no_state.json"), ok("events_empty.json"))
        _, api = run(MONITORS, [QUEUE, CHECKOUT, DISK], FRESH, *reads)

        relayed = relay(MONITORS, [QUEUE, CHECKOUT, DISK], FRESH, relay_fixture("relay_monitor_errors.json"))

        self.assertEqual(state.dump(relayed), state.dump(api))

    def test_scalar_matches_the_api(self):
        _, api = run(METRICS, [P95], NO_METRICS, ok("scalar.json"))

        self.assertEqual(state.dump(relay(METRICS, [P95], NO_METRICS, relay_fixture("relay_scalar.json"))), state.dump(api))

    def test_top_matches_the_api(self):
        _, api = run(METRICS, [BY_SERVICE], NO_METRICS, ok("top.json"))

        self.assertEqual(state.dump(relay(METRICS, [BY_SERVICE], NO_METRICS, relay_fixture("relay_top.json"))), state.dump(api))

    def test_hourly_matches_the_api(self):
        _, api = run(METRICS, [HOURLY], NO_METRICS, ok("timeseries.json"))

        self.assertEqual(state.dump(relay(METRICS, [HOURLY], NO_METRICS, relay_fixture("relay_hourly.json"))), state.dump(api))

    def test_none_cursor_on_monitors_reads_like_an_empty_cursor(self):
        result = relay(MONITORS, [QUEUE, CHECKOUT], None, relay_fixture("relay_monitors.json"), aggregate=AGGREGATE_FIXTURE)

        self.assertEqual(result["cursor"], {"events_ts_ms": 1760002000000, "monitors": {"101": "OK", "102": "Alert"}})

    def test_none_cursor_on_metrics_reads_like_an_empty_cursor(self):
        result = relay(METRICS, [P95], None, relay_fixture("relay_scalar.json"))

        self.assertEqual(result["cursor"], {"metrics": {"checkout-p95": 42.5}})

    def test_metric_entry_errors_match_the_api(self):
        stored = {"metrics": {"checkout-p95": 1.5}}
        _, api = run(METRICS, [P95, BY_SERVICE], stored, status(400), ok("top.json"))

        relayed = relay(METRICS, [P95, BY_SERVICE], stored, relay_fixture("relay_metric_errors.json"))

        self.assertEqual(state.dump(relayed), state.dump(api))

    def test_not_found_on_a_plain_error_matches_the_api(self):
        _, api = run(MONITORS, [QUEUE, CHECKOUT], FRESH, status(404), ok("monitor_ok.json"), ok("events_empty.json"))

        relayed = relay(MONITORS, [QUEUE, CHECKOUT], FRESH, monitors_payload(monitor_failure("monitor-queue", 404, "Error"), relayed_checkout()))

        self.assertEqual(state.dump(relayed), state.dump(api))

    def test_unset_and_null_priorities_match_the_api(self):
        body = {"id": 102, "name": "Queue depth", "overall_state": "Alert", "priority": None}
        _, api = run(MONITORS, [QUEUE], FRESH, served(body), ok("events_empty.json"))

        relayed = relay(MONITORS, [QUEUE], FRESH, monitors_payload({"entry": "monitor-queue", "ok": True, "monitor": body}))

        self.assertEqual(state.dump(relayed), state.dump(api))
        self.assertIsNone(relayed["records"]["monitors"][0]["priority"])

    def test_hourly_lookback_matches_the_api(self):
        entries = [lookback(HOURLY)]
        _, api = run(METRICS, entries, NO_METRICS, ok("timeseries_daily.json"))

        relayed = relay(METRICS, entries, NO_METRICS, relay_fixture("relay_daily.json"))

        self.assertEqual(state.dump(relayed), state.dump(api))
        self.assertEqual(len(relayed["records"]["metrics"][0]["daily"]), 7)

    def test_scalar_lookback_matches_the_api(self):
        entries = [lookback(P95)]
        _, api = run(METRICS, entries, NO_METRICS, ok("scalar_lookback.json"))
        document = {"metrics": [{"entry": "checkout-p95", "ok": True, "scalar": {"columns": [{"type": "number", "name": "a", "values": [17.25]}]}}]}

        self.assertEqual(state.dump(relay(METRICS, entries, NO_METRICS, document)), state.dump(api))

    def test_top_lookback_matches_the_api(self):
        entries = [lookback(BY_SERVICE)]
        _, api = run(METRICS, entries, NO_METRICS, ok("top.json"))

        relayed = relay(METRICS, entries, NO_METRICS, relay_fixture("relay_top.json"))

        self.assertEqual(state.dump(relayed), state.dump(api))

    def test_lookback_and_window_entries_match_the_api(self):
        entries = [lookback(HOURLY), {**HOURLY, "key": "queue-window"}]
        _, api = run(METRICS, entries, NO_METRICS, ok("timeseries_daily.json"), ok("timeseries.json"))
        window = {**relay_fixture("relay_hourly.json")["metrics"][0], "entry": "queue-window"}
        document = {"metrics": [relay_fixture("relay_daily.json")["metrics"][0], window]}

        self.assertEqual(state.dump(relay(METRICS, entries, NO_METRICS, document)), state.dump(api))


def relayed_series(document):
    return {"ok": True, "timeseries": document}


def with_trend(item, trend):
    return {**item, "trend": trend}


class RelayTrendTest(unittest.TestCase):
    HOURLY = trended(HOURLY, "max")

    def window_item(self):
        return relay_fixture("relay_hourly.json")["metrics"][0]

    def relayed(self, trend, entries=None):
        document = {"metrics": [with_trend(self.window_item(), trend)]}
        return relay(METRICS, entries or [self.HOURLY], NO_METRICS, document, TREND_WINDOW)

    def test_trends_of_both_read_kinds_match_the_api(self):
        entries = [self.HOURLY, trended(P95, "avg")]
        document = {
            "metrics": [
                with_trend(self.window_item(), relayed_series(TREND_SERIES)),
                with_trend(relay_fixture("relay_scalar.json")["metrics"][0], relayed_series(TREND_SERIES)),
            ]
        }
        _, api = run(
            METRICS, entries, NO_METRICS, ok("timeseries.json"), series_response(TREND_SERIES), ok("scalar.json"), series_response(TREND_SERIES), window=TREND_WINDOW
        )

        relayed = relay(METRICS, entries, NO_METRICS, document, TREND_WINDOW)

        self.assertEqual(state.dump(relayed), state.dump(api))
        self.assertEqual(
            [[point["value"] for point in record["trend"]] for record in relayed["records"]["metrics"]], [[5.0, 4.0], [9.0, 7.0]]
        )

    def test_failed_trend_matches_the_api_and_keeps_the_window_value(self):
        _, api = run(METRICS, [self.HOURLY], NO_METRICS, ok("timeseries.json"), status(500), status(500), window=TREND_WINDOW)
        failure = {"ok": False, "status": 500, "error": "ApiException"}

        relayed = self.relayed(failure)

        self.assertEqual(state.dump(relayed), state.dump(api))
        self.assertEqual((relayed["records"]["metrics"][0]["value"], relayed["entries"]), (7.25, {"queue-hourly": OK}))

    def test_series_without_a_point_matches_the_api(self):
        _, api = run(METRICS, [self.HOURLY], NO_METRICS, ok("timeseries.json"), series_response(series()), window=TREND_WINDOW)

        relayed = self.relayed(relayed_series(series()))

        self.assertEqual(state.dump(relayed), state.dump(api))
        self.assertEqual(relayed["records"]["metrics"][0]["trend_reason"], "no datapoints")

    def test_unauthorized_trend_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            self.relayed({"ok": False, "status": 401, "error": "ApiException"})

        self.assertEqual((str(caught.exception), caught.exception.status), ("HTTP 401 POST /api/v2/query/timeseries", 401))

    def test_trend_error_without_a_status_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            self.relayed({"ok": False, "status": None, "error": "FetchError"})

        self.assertEqual(str(caught.exception), "POST /api/v2/query/timeseries: FetchError")

    def test_payload_without_a_trend_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            relay(METRICS, [self.HOURLY], NO_METRICS, {"metrics": [self.window_item()]}, TREND_WINDOW)

        self.assertEqual(str(caught.exception), "execute_code metrics-1: payload without trend for entry queue-hourly")

    def test_failed_window_read_needs_no_trend_in_the_payload(self):
        document = {"metrics": [{"entry": "queue-hourly", "ok": False, "status": 400, "error": "ApiException"}]}

        result = relay(METRICS, [self.HOURLY], NO_METRICS, document, TREND_WINDOW)

        self.assertEqual(result["entries"], {"queue-hourly": failed("HTTP 400 POST /api/v2/query/timeseries")})

    def test_entry_without_a_trend_span_ignores_a_trend_in_the_payload(self):
        document = {"metrics": [with_trend(self.window_item(), relayed_series(TREND_SERIES))]}

        result = relay(METRICS, [HOURLY], NO_METRICS, document, TREND_WINDOW)

        self.assertEqual(set(result["records"]["metrics"][0]), {"key", "value", "hourly", "groups"})

    def test_collection_passes_the_role_schema(self):
        result = self.relayed(relayed_series(TREND_SERIES))

        self.assertIsNone(roles.validate_collection(collection(METRICS, result)))


class RelayDiscoveryTest(unittest.TestCase):
    def matches_the_api(self, search, *outcomes):
        _, api = discover(*outcomes)

        relayed = relay_discovery(search)

        self.assertEqual(state.dump(relayed), state.dump(api))
        return relayed

    def test_paged_discovery_and_priority_match_the_api(self):
        reads = (ok("monitor_priority.json"), ok("events_empty.json"), ok("search_page_1.json"), ok("search_page_2.json"))
        _, api = run(DISCOVERING, [QUEUE], FRESH, *reads)

        relayed = relay(DISCOVERING, [QUEUE], FRESH, relay_fixture("relay_discovery.json"))

        self.assertEqual(state.dump(relayed), state.dump(api))
        self.assertEqual([monitor["id"] for monitor in relayed["records"]["discovered"]], ["201", "202", "203"])
        self.assertEqual(relayed["records"]["monitors"][0]["priority"], 2)

    def test_discovery_at_the_page_cap_matches_the_api(self):
        search = search_outcome(*[relay_page(21, CHECKOUT_ERRORS) for _ in range(_http.PAGE_CAP)], partial="page cap")

        relayed = self.matches_the_api(search, *[ok("search_capped.json") for _ in range(_http.PAGE_CAP)])

        self.assertEqual(relayed["records"]["discovery"], {"read": False, "reason": "partial: page cap"})

    def test_last_page_at_the_cap_matches_the_api(self):
        pages = range(_http.PAGE_CAP)
        search = search_outcome(*[relay_page(_http.PAGE_CAP, found(300 + page)) for page in pages])

        relayed = self.matches_the_api(search, *[search_page(page, _http.PAGE_CAP, found(300 + page)) for page in pages])

        self.assertEqual(relayed["records"]["discovery"], {"read": True, "reason": None})

    def test_failed_search_matches_the_api(self):
        relayed = self.matches_the_api(search_failure(503), status(503), status(503))

        self.assertEqual(relayed["records"]["discovery"], {"read": False, "reason": "HTTP 503 GET /api/v1/monitor/search"})

    def test_failure_on_a_later_page_matches_the_api(self):
        search = search_failure(400, relay_page(2, DISK_USAGE, CHECKOUT_ERRORS))

        relayed = self.matches_the_api(search, ok("search_page_1.json"), status(400))

        self.assertEqual([monitor["id"] for monitor in relayed["records"]["discovered"]], ["201", "203"])

    def test_search_failure_without_a_status_matches_the_api(self):
        failure = search_failure(None, error="ConnectionRefusedError")

        relayed = self.matches_the_api(failure, urllib.error.URLError(ConnectionRefusedError()))

        self.assertEqual(
            relayed["records"]["discovery"], {"read": False, "reason": "GET /api/v1/monitor/search: ConnectionRefusedError"}
        )

    def test_unreadable_page_keeps_the_earlier_pages_like_the_api(self):
        search = search_outcome(relay_page(2, found(201)), {"monitors": "none", "metadata": {"page_count": 1}})

        relayed = self.matches_the_api(search, search_page(0, 2, found(201)), ok("search_unreadable.json"))

        self.assertEqual([monitor["id"] for monitor in relayed["records"]["discovered"]], ["201"])

    def test_page_without_a_page_count_matches_the_api(self):
        search = search_outcome({"monitors": [found(201)], "metadata": {}})

        relayed = self.matches_the_api(search, served({"monitors": [found(201)], "metadata": {}}))

        self.assertEqual(relayed["records"]["discovery"]["read"], False)

    def test_page_without_a_monitor_list_matches_the_api(self):
        search = search_outcome({"monitors": None, "metadata": {"page_count": 1}})

        self.matches_the_api(search, served({"metadata": {"page_count": 1}}))

    def test_unknown_state_matches_the_api(self):
        relayed = self.matches_the_api(
            search_outcome(relay_page(1, found(201, "Paused"))), search_page(0, 1, found(201, "Paused"))
        )

        self.assertEqual([monitor["state"] for monitor in relayed["records"]["discovered"]], ["Paused"])

    def test_monitor_read_by_id_and_discovered_is_in_both_lists(self):
        document = with_discovery(search_outcome(relay_page(1, found(102))), relayed_monitor("Alert"))

        result = relay(DISCOVERING, [QUEUE], FRESH, document)

        self.assertEqual([monitor["id"] for monitor in result["records"]["monitors"]], ["102"])
        self.assertEqual([monitor["id"] for monitor in result["records"]["discovered"]], ["102"])

    def test_discovered_monitors_are_not_added_to_the_cursor(self):
        result = relay(DISCOVERING, [QUEUE], FRESH, relay_fixture("relay_discovery.json"))

        self.assertEqual(result["cursor"]["monitors"], {"102": "Alert"})

    def test_failed_search_leaves_the_source_and_the_by_id_reads_read(self):
        document = with_discovery(search_failure(503), relayed_monitor("Alert"))

        result = relay(DISCOVERING, [QUEUE], FRESH, document)

        self.assertEqual(result["entries"], {"monitor-queue": OK})
        self.assertEqual([monitor["id"] for monitor in result["records"]["monitors"]], ["102"])

    def test_payload_without_a_discovery_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            relay(DISCOVERING, [], FRESH, monitors_payload())
        self.assertEqual(str(caught.exception), "execute_code alerts-2: payload without discovery")

    def test_source_without_a_query_reads_no_discovery(self):
        document = with_discovery(search_outcome(relay_page(1, found(201))))

        result = relay(MONITORS, [], FRESH, document)

        self.assertEqual(sorted(result["records"]), ["discovered", "discovery", "monitors", "transitions"])
        self.assertEqual((result["records"]["discovered"], result["records"]["discovery"]), ([], {"read": True, "reason": None}))

    def test_collection_without_a_query_passes_the_role_schema(self):
        result = relay(MONITORS, [], FRESH, monitors_payload())

        self.assertIsNone(roles.validate_collection(collection(MONITORS, result)))

    def test_collection_passes_the_role_schema_when_read(self):
        result = relay(DISCOVERING, [QUEUE], FRESH, relay_fixture("relay_discovery.json"))

        self.assertIsNone(roles.validate_collection(collection(DISCOVERING, result)))

    def test_collection_passes_the_role_schema_when_the_discovery_failed(self):
        self.assertIsNone(roles.validate_collection(collection(DISCOVERING, relay_discovery(search_failure(400)))))


def event_read(monitor_id, state_name="OK", **extra):
    return {"id": str(monitor_id), "ok": True, "monitor": {"id": monitor_id, "name": f"Monitor {monitor_id}", "overall_state": state_name, **extra}}


def event_failure(monitor_id, code, error="ApiException"):
    return {"id": str(monitor_id), "ok": False, "status": code, "error": error}


class RelayEventMonitorTest(unittest.TestCase):
    def relayed(self, ids, reads, source=MONITORS, capped=False, **extra):
        payload = {**monitors_payload(event_monitors={"capped": capped, "reads": list(reads)}), **extra}
        return relay(source, [], FRESH, payload, aggregate=aggregate_naming(*ids))

    def matches_the_api(self, ids, reads, *outcomes, capped=False):
        _, api = run(MONITORS, [], FRESH, named_by_event(*ids), *outcomes)

        relayed = self.relayed(ids, reads, capped=capped)

        self.assertEqual(state.dump(relayed), state.dump(api))
        return relayed

    def test_event_monitor_matches_the_api(self):
        relayed = self.matches_the_api([301], [event_read(301, "OK", priority=3)], monitor_body(301, "OK", priority=3))

        self.assertEqual(relayed["records"]["discovered"], [{"id": "301", "name": "Monitor 301", "state": "OK", "priority": 3, "link": APP + "/monitors/301"}])

    def test_not_found_event_monitor_is_skipped_like_the_api(self):
        relayed = self.matches_the_api([301, 302], [event_failure(301, 404), event_read(302)], status(404), monitor_body(302))

        self.assertEqual([monitor["id"] for monitor in relayed["records"]["discovered"]], ["302"])

    def test_failed_event_monitor_reads_mark_the_discovery_not_read_like_the_api(self):
        reads = [event_failure(301, 403), event_failure(302, None, "ConnectionRefusedError"), event_read(303)]

        relayed = self.matches_the_api(
            [301, 302, 303], reads, status(403), urllib.error.URLError(ConnectionRefusedError()), monitor_body(303)
        )

        self.assertEqual(relayed["records"]["discovery"], {"read": False, "reason": "HTTP 403 GET /api/v1/monitor/301"})
        self.assertEqual([monitor["id"] for monitor in relayed["records"]["discovered"]], ["303"])

    def test_event_monitor_read_without_a_status_matches_the_api(self):
        relayed = self.matches_the_api([301], [event_failure(301, None, "ConnectionRefusedError")], urllib.error.URLError(ConnectionRefusedError()))

        self.assertEqual(relayed["records"]["discovery"], {"read": False, "reason": "GET /api/v1/monitor/301: ConnectionRefusedError"})

    def test_event_monitor_without_a_state_matches_the_api(self):
        read = {"id": "301", "ok": True, "monitor": {"id": 301, "name": "Monitor 301"}}

        relayed = self.matches_the_api([301], [read], served({"id": 301, "name": "Monitor 301"}))

        self.assertFalse(relayed["records"]["discovery"]["read"])

    def test_failed_search_keeps_its_reason_when_an_event_monitor_read_fails_too(self):
        _, api = run(DISCOVERING, [], FRESH, named_by_event(301), status(400), status(403))

        relayed = self.relayed([301], [event_failure(301, 403)], source=DISCOVERING, discovery=search_failure(400))

        self.assertEqual(state.dump(relayed), state.dump(api))
        self.assertEqual(relayed["records"]["discovery"], {"read": False, "reason": "HTTP 400 GET /api/v1/monitor/search"})

    def test_event_monitor_with_an_unknown_state_is_kept_like_the_api(self):
        relayed = self.matches_the_api([301], [event_read(301, "Weird")], monitor_body(301, "Weird"))

        self.assertEqual([(monitor["id"], monitor["state"]) for monitor in relayed["records"]["discovered"]], [("301", "Weird")])

    def test_read_of_a_monitor_the_search_found_is_dropped_like_the_api(self):
        search = search_outcome(relay_page(1, CHECKOUT_ERRORS))
        _, api = run(DISCOVERING, [], FRESH, named_by_event(201, 301), search_page(0, 1, CHECKOUT_ERRORS), monitor_body(301))

        relayed = self.relayed([201, 301], [event_read(201), event_read(301)], source=DISCOVERING, discovery=search)

        self.assertEqual(state.dump(relayed), state.dump(api))
        self.assertEqual([monitor["id"] for monitor in relayed["records"]["discovered"]], ["201", "301"])

    def test_read_of_a_monitor_the_aggregate_does_not_name_is_dropped_like_the_api(self):
        garbled = events_page(event("ev-301", timestamp="garbage", attributes={"monitor_id": 301}))
        _, api = run(MONITORS, [], FRESH, garbled)

        relayed = self.relayed([], [event_read(301)])

        self.assertEqual(state.dump(relayed), state.dump(api))
        self.assertEqual(relayed["records"]["discovered"], [])

    def test_capped_event_monitors_match_the_api(self):
        ids = range(1001, 1052)
        reads = [event_read(number) for number in range(1001, 1051)]

        relayed = self.matches_the_api(ids, reads, *(monitor_body(number) for number in range(1001, 1051)), capped=True)

        self.assertEqual(relayed["records"]["discovery"], {"read": True, "reason": None, "event_monitors_capped": True})

    def test_event_monitors_are_listed_with_the_discovered_ones(self):
        relayed = self.relayed([301], [event_read(301)], source=DISCOVERING, discovery=search_outcome(relay_page(1, CHECKOUT_ERRORS)))

        self.assertEqual([monitor["id"] for monitor in relayed["records"]["discovered"]], ["201", "301"])

    def test_payload_without_event_monitors_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            relay(MONITORS, [], FRESH, {"monitors": []})
        self.assertEqual(str(caught.exception), "execute_code alerts-2: payload without event_monitors")

    def test_collection_passes_the_role_schema_when_capped(self):
        relayed = self.relayed([301], [event_read(301)], capped=True)

        self.assertIsNone(roles.validate_collection(collection(MONITORS, relayed)))


class RelayResponseTest(unittest.TestCase):
    def unreadable(self, text):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            parse_text(MONITORS, [], FRESH, text)
        return str(caught.exception)

    def digest(self):
        return script_call(MONITORS, [], FRESH)["digest"]

    def test_checksum_mismatch_rejects_the_response(self):
        payload = stringified(monitors_payload())

        reason = self.unreadable(wrapped({**script_value(payload, self.digest()), "checksum": roles.fnv1a32(payload + " ")}))

        self.assertEqual(reason, "execute_code alerts-2: payload checksum mismatch")

    def test_digest_mismatch_rejects_the_response(self):
        reason = self.unreadable(wrapped(script_value(stringified(monitors_payload()), roles.fnv1a32("edited params"))))

        self.assertEqual(reason, "execute_code alerts-2: plan digest mismatch")

    def test_missing_digest_rejects_the_response(self):
        reason = self.unreadable(wrapped(script_value(stringified(monitors_payload()), None)))

        self.assertEqual(reason, "execute_code alerts-2: plan digest mismatch")

    def test_non_ascii_payload_rejects_the_response(self):
        payload = stringified(monitors_payload())[:-1] + ',"note":"caf\u00e9"}'

        reason = self.unreadable(wrapped({"payload": payload, "checksum": roles.fnv1a32("x"), "digest": self.digest()}))

        self.assertEqual(reason, "execute_code alerts-2: payload is not ASCII text")

    def test_failed_tool_call_rejects_the_response(self):
        reason = self.unreadable(wrapped(script_value(stringified(monitors_payload()), self.digest()), success=False))

        self.assertEqual(reason, "execute_code alerts-2: the tool call did not succeed")

    def test_partial_outcome_rejects_the_response(self):
        reason = self.unreadable(wrapped(script_value(stringified(monitors_payload()), self.digest()), outcome="partial"))

        self.assertEqual(reason, "execute_code alerts-2: the tool call did not succeed")

    def test_response_without_a_value_is_rejected(self):
        reason = self.unreadable(json.dumps({"outcome": "success", "success": True, "duration": "199ms"}))

        self.assertEqual(reason, "execute_code alerts-2: response without a value")

    def test_response_that_is_not_json_is_rejected(self):
        self.assertEqual(self.unreadable("Script finished"), "execute_code alerts-2: response is not a JSON object")

    def test_payload_that_is_not_json_is_rejected(self):
        reason = self.unreadable(wrapped(script_value("not json", self.digest())))

        self.assertEqual(reason, "execute_code alerts-2: payload is not a JSON object")

    def test_missing_response_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            datadog.parse(MONITORS, WINDOW, FRESH, [], {}, {"alerts-2": self.digest()})
        self.assertEqual(str(caught.exception), "aggregate_events alerts-1: no saved response")

    def test_missing_script_response_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            datadog.parse(MONITORS, WINDOW, FRESH, [], {"alerts-1": EMPTY_AGGREGATE}, {"alerts-2": self.digest()})
        self.assertEqual(str(caught.exception), "execute_code alerts-2: no saved response")

    def test_payload_without_an_entry_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            relay(MONITORS, [QUEUE], FRESH, monitors_payload())
        self.assertEqual(str(caught.exception), "execute_code alerts-2: payload without entry monitor-queue")


class RelayFailureTest(unittest.TestCase):
    def unreadable(self, source, entries, cursor, document):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            relay(source, entries, cursor, document)
        return caught.exception

    def test_unauthorized_monitor_makes_the_source_unreadable(self):
        failure = self.unreadable(MONITORS, [QUEUE], FRESH, monitors_payload(monitor_failure("monitor-queue", 401)))

        self.assertEqual(str(failure), "HTTP 401 GET /api/v1/monitor/102")

    def test_error_without_a_status_makes_the_source_unreadable(self):
        failure = self.unreadable(MONITORS, [QUEUE], FRESH, monitors_payload(monitor_failure("monitor-queue", None, "TypeError")))

        self.assertEqual(str(failure), "GET /api/v1/monitor/102: TypeError")

    def test_error_class_outside_the_identifier_shape_reads_as_error(self):
        failure = self.unreadable(MONITORS, [QUEUE], FRESH, monitors_payload(monitor_failure("monitor-queue", None, "token=abc def")))

        self.assertEqual(str(failure), "GET /api/v1/monitor/102: Error")

    def test_non_numeric_monitor_id_fails_only_its_entry(self):
        skipped = {"entry": "monitor-odd", "ok": False, "status": None, "error": "InvalidMonitorId"}

        result = relay(MONITORS, [ODD], FRESH, monitors_payload(skipped))

        self.assertEqual(result["entries"], {"monitor-odd": failed("monitor id 12ab is not a number")})

    def test_not_found_on_a_plain_error_is_a_missing_entry(self):
        result = relay(MONITORS, [QUEUE, CHECKOUT], FRESH, monitors_payload(monitor_failure("monitor-queue", 404, "Error"), relayed_checkout()))

        self.assertEqual(result["entries"], {"monitor-queue": NOT_FOUND, "monitor-checkout": OK})

    def test_missing_monitor_is_left_out_of_the_records_and_the_cursor(self):
        stored = {"events_ts_ms": None, "monitors": {"102": "Alert"}}

        result = relay(MONITORS, [QUEUE], stored, monitors_payload(monitor_failure("monitor-queue", 404, "Error")))

        self.assertEqual((result["records"]["monitors"], result["cursor"]["monitors"]), ([], {"102": "Alert"}))

    def test_server_error_fails_only_its_entry(self):
        result = relay(MONITORS, [QUEUE], FRESH, monitors_payload(monitor_failure("monitor-queue", 503)))

        self.assertEqual(result["entries"], {"monitor-queue": failed("HTTP 503 GET /api/v1/monitor/102")})

    def test_forbidden_metric_makes_the_source_unreadable(self):
        failure = self.unreadable(METRICS, [P95], NO_METRICS, metric_failure("checkout-p95", 403))

        self.assertEqual(str(failure), "HTTP 403 POST /api/v2/query/scalar")

    def test_rejected_hourly_query_names_the_timeseries_endpoint(self):
        result = relay(METRICS, [HOURLY], NO_METRICS, metric_failure("queue-hourly", 400))

        self.assertEqual(result["entries"], {"queue-hourly": failed("HTTP 400 POST /api/v2/query/timeseries")})


class RelayAggregateTest(unittest.TestCase):
    def read(self, text, cursor=FRESH):
        return relay(MONITORS, [], cursor, monitors_payload(), aggregate=text)

    def unreadable(self, text):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            self.read(text)
        return caught.exception

    def test_table_becomes_the_transitions_sorted_by_monitor_id(self):
        result = self.read(aggregate_text((1010, 1, 1760000300000, 1760000300000), (102, 2, 1760001000000, 1760001500000), (99, 3, 1760000200000, 1760002000000)))

        self.assertEqual(
            result["records"]["transitions"],
            [
                {"monitor": "99", "count": 3, "first_ts_ms": 1760000200000, "last_ts_ms": 1760002000000},
                {"monitor": "102", "count": 2, "first_ts_ms": 1760001000000, "last_ts_ms": 1760001500000},
                {"monitor": "1010", "count": 1, "first_ts_ms": 1760000300000, "last_ts_ms": 1760000300000},
            ],
        )

    def test_fixture_table_reads_like_the_api_events(self):
        result = self.read(AGGREGATE_FIXTURE)

        self.assertEqual([(item["monitor"], item["count"]) for item in result["records"]["transitions"]], [("101", 2), ("102", 2)])

    def test_cursor_is_the_newest_last_time(self):
        result = self.read(aggregate_text((101, 1, 1760001000000, 1760001000000), (102, 1, 1760000100000, 1760002000000)))

        self.assertEqual(result["cursor"]["events_ts_ms"], 1760002000000)

    def test_cursor_keeps_a_stored_position_after_the_newest_last_time(self):
        result = self.read(aggregate_text((101, 1, 1760001000000, 1760001000000)), {"events_ts_ms": 1760009000000, "monitors": {}})

        self.assertEqual(result["cursor"]["events_ts_ms"], 1760009000000)

    def test_cursor_keeps_the_stored_position_without_a_row(self):
        self.assertEqual(self.read(EMPTY_AGGREGATE, {"events_ts_ms": STORED_TS, "monitors": {}})["cursor"]["events_ts_ms"], STORED_TS)

    def test_cursor_stays_null_without_a_row_or_a_stored_position(self):
        self.assertIsNone(self.read(EMPTY_AGGREGATE)["cursor"]["events_ts_ms"])

    def test_group_without_a_numeric_monitor_moves_the_cursor_but_adds_no_transition(self):
        result = self.read(aggregate_text(("N/A", 4, 1760000100000, 1760003000000), (101, 1, 1760001000000, 1760001000000)))

        self.assertEqual([item["monitor"] for item in result["records"]["transitions"]], ["101"])
        self.assertEqual(result["cursor"]["events_ts_ms"], 1760003000000)

    def test_rows_may_use_windows_line_endings(self):
        text = aggregate_text((101, 1, 1760001000000, 1760001000000)).replace("\n", "\r\n")

        self.assertEqual(len(self.read(text)["records"]["transitions"]), 1)

    def test_buckets_at_the_group_cap_are_read(self):
        rows = [(number, 1, 1760001000000, 1760001000000) for number in range(1001, 2001)]

        self.assertEqual(len(self.read(aggregate_text(*rows))["records"]["transitions"]), datadog.GROUP_CAP)

    def test_buckets_over_the_group_cap_mark_the_source_partial(self):
        failure = self.unreadable(aggregate_text(total=1001))

        self.assertEqual((type(failure), str(failure)), (_http.PartialRead, "partial: group cap"))

    def test_response_without_a_bucket_count_is_unreadable(self):
        self.assertEqual(str(self.unreadable("<TSV_DATA>\n" + TABLE_HEADER + "\n</TSV_DATA>")), "aggregate_events alerts-1: response without a bucket count")

    def test_response_without_a_table_is_unreadable(self):
        text = "<METADATA><total_buckets>0</total_buckets></METADATA>"

        self.assertEqual(str(self.unreadable(text)), "aggregate_events alerts-1: response without a table")

    def test_table_with_another_header_is_unreadable(self):
        text = aggregate_text().replace("count", "total")

        self.assertEqual(str(self.unreadable(text)), "aggregate_events alerts-1: table header differs from " + repr(TABLE_HEADER))

    def test_row_with_a_missing_column_is_unreadable(self):
        text = aggregate_text((101, 1, 1760001000000))

        self.assertEqual(str(self.unreadable(text)), "aggregate_events alerts-1: unreadable table row 1")

    def test_row_with_a_text_count_is_unreadable(self):
        text = aggregate_text((101, 1, 1760001000000, 1760001000000), (102, "many", 1760001000000, 1760001000000))

        self.assertEqual(str(self.unreadable(text)), "aggregate_events alerts-1: unreadable table row 2")

    def test_row_with_a_zero_count_is_unreadable(self):
        self.assertEqual(str(self.unreadable(aggregate_text((101, 0, 1760001000000, 1760001000000)))), "aggregate_events alerts-1: unreadable table row 1")

    def test_row_ending_before_it_starts_is_unreadable(self):
        self.assertEqual(str(self.unreadable(aggregate_text((101, 1, 1760002000000, 1760001000000)))), "aggregate_events alerts-1: unreadable table row 1")

    def test_monitor_listed_twice_is_unreadable(self):
        text = aggregate_text((101, 1, 1760001000000, 1760001000000), (101, 2, 1760001000000, 1760002000000))

        self.assertEqual(str(self.unreadable(text)), "aggregate_events alerts-1: monitor 101 listed twice")

    def test_table_with_fewer_rows_than_buckets_is_unreadable(self):
        text = aggregate_text((101, 1, 1760001000000, 1760001000000), total=3)

        self.assertEqual(str(self.unreadable(text)), "aggregate_events alerts-1: table holds 1 rows for 3 buckets")

    def test_collection_passes_the_role_schema(self):
        result = self.read(AGGREGATE_FIXTURE)

        self.assertIsNone(roles.validate_collection(collection(MONITORS, result)))


class RelayLinksTest(unittest.TestCase):
    def test_links_base_builds_the_monitor_links(self):
        source = configured(MONITORS, {"adapter": "datadog", "links_base": "https://ui.example.test"})

        result = relay(source, [QUEUE, CHECKOUT], FRESH, relay_fixture("relay_monitors.json"))

        self.assertEqual(
            [monitor["link"] for monitor in result["records"]["monitors"]],
            ["https://ui.example.test/monitors/101", "https://ui.example.test/monitors/102"],
        )

    def test_provider_without_links_base_or_base_url_makes_monitors_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            relay(configured(MONITORS, {"adapter": "datadog"}), [QUEUE, CHECKOUT], FRESH, relay_fixture("relay_monitors.json"))
        self.assertEqual(str(caught.exception), "links_base missing in providers.obs")

    def test_metrics_read_without_any_links_base(self):
        result = relay(configured(METRICS, {"adapter": "datadog"}), [P95], NO_METRICS, relay_fixture("relay_scalar.json"))

        self.assertEqual(result["entries"], {"checkout-p95": OK})

    def test_collection_passes_the_role_schema(self):
        result = relay(MONITORS, [QUEUE, CHECKOUT], FRESH, relay_fixture("relay_monitors.json"))

        self.assertIsNone(roles.validate_collection(collection(MONITORS, result)))


def relay_state(state_name):
    return relay(MONITORS, [QUEUE], FRESH, monitors_payload(relayed_monitor(state_name)))["records"]["monitors"][0]["state"]


class RelayMonitorStateTest(unittest.TestCase):
    def test_keeps_each_known_monitor_state(self):
        known = ["OK", "Alert", "Warn", "No Data", "Skipped", "Unknown", "Ignored"]

        self.assertEqual([relay_state(name) for name in known], known)

    def test_unknown_monitor_state_fails_only_its_entry(self):
        result = relay(MONITORS, [QUEUE], FRESH, monitors_payload(relayed_monitor("Paused")))

        self.assertEqual(result["entries"], {"monitor-queue": failed("GET /api/v1/monitor/102: unknown monitor state: Paused")})


if __name__ == "__main__":
    unittest.main()
