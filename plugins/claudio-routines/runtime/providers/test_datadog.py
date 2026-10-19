import json
import unittest
import urllib.error
import urllib.parse

import roles
from providers import _http, datadog
from providers.datadog_support import (
    API_VALUE,
    API_VAR,
    APP,
    APP_VALUE,
    APP_VAR,
    BASE,
    BY_SERVICE,
    CHECKOUT,
    DISCOVERING,
    DISK,
    FALL_BACK_DAY,
    FRESH,
    FROM_MS,
    FakeOpener,
    HOURLY,
    LOOKBACK_FROM_MS,
    METRICS,
    MONITORS,
    NOT_FOUND,
    NO_METRICS,
    ODD,
    OK,
    P95,
    PROVIDER,
    QUERY,
    QUEUE,
    SPRING_FORWARD_DAY,
    STORED_TS,
    TOKEN_VALUE,
    TOKEN_VAR,
    TO_MS,
    TREND_FROM_MS,
    TREND_SERIES,
    TREND_WINDOW,
    WINDOW,
    at,
    client,
    clock_change_series,
    collection,
    configured,
    discover,
    event,
    events_page,
    failed,
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
SEARCH_PATH = "/api/v1/monitor/search"


def missing_monitors(count):
    return [status(404) for _ in range(count)]


def scalar_response(*columns):
    return served({"data": {"type": "scalar_response", "attributes": {"columns": list(columns)}}})


def numbers(*values):
    return {"name": "a", "type": "number", "values": list(values)}


def timeseries_response(times, values):
    series = [{"group_tags": [], "query_index": 0, "unit": None}]
    return served({"data": {"type": "timeseries_response", "attributes": {"series": series, "times": times, "values": [values]}}})


def based(source, base_url):
    return configured(source, {**PROVIDER, "api": {**PROVIDER["api"], "base_url": base_url}})


def transitions_of(*items, reads=1):
    _, result = run(MONITORS, [], FRESH, events_page(*items), *missing_monitors(reads))
    return result["records"]["transitions"]


def dated(timestamp, monitor_id=301):
    return event("e1", timestamp=timestamp, attributes={"monitor_id": monitor_id})


def endpoint(request):
    return request.get_method(), urllib.parse.urlsplit(request.full_url).path


def query(request):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)


def sent(request):
    return json.loads(request.data)


class ClientTest(unittest.TestCase):
    def test_role_is_observability(self):
        self.assertEqual(datadog.ROLE, "observability")

    def test_sends_the_api_and_application_keys(self):
        opener, _ = run(MONITORS, [], FRESH, ok("events_empty.json"))

        request = opener.requests[0]
        self.assertEqual((request.get_header("Dd-api-key"), request.get_header("Dd-application-key")), (API_VALUE, APP_VALUE))

    def test_sends_an_access_token_as_a_bearer_token_without_keys(self):
        provider = {"api": {"base_url": BASE, "credentials": {"token": TOKEN_VAR}}}
        opener = FakeOpener([ok("events_empty.json")])
        http = datadog.api_client(provider, opener=opener, environ={TOKEN_VAR: TOKEN_VALUE}, sleep=lambda seconds: None)

        http.get(datadog.EVENTS_PATH)
        request = opener.requests[0]
        self.assertEqual((request.get_header("Authorization"), request.get_header("Dd-api-key")), (f"Bearer {TOKEN_VALUE}", None))

    def test_rejects_a_provider_naming_the_token_and_the_keys(self):
        provider = {"api": {"base_url": BASE, "credentials": {"token": TOKEN_VAR, "api_key": API_VAR, "app_key": APP_VAR}}}

        with self.assertRaises(_http.SourceUnreadable) as caught:
            datadog.api_client(provider, opener=FakeOpener([]))
        self.assertEqual(str(caught.exception), "api.credentials: name either token, or api_key and app_key")

    def test_rejects_a_provider_without_the_application_key(self):
        provider = {"api": {"base_url": BASE, "credentials": {"api_key": API_VAR}}}

        with self.assertRaises(_http.SourceUnreadable) as caught:
            datadog.api_client(provider, opener=FakeOpener([]))
        self.assertEqual(str(caught.exception), "api.credentials: must name api_key and app_key; missing app_key")

    def test_rejects_a_base_url_that_is_not_https_naming_the_key(self):
        provider = {"api": {"base_url": "http://api.example.test", "credentials": {"api_key": API_VAR, "app_key": APP_VAR}}}

        with self.assertRaises(_http.SourceUnreadable) as caught:
            datadog.api_client(provider, opener=FakeOpener([]))
        self.assertEqual(str(caught.exception), "api.base_url: must be an https URL without user info, query or fragment")

    def test_missing_credential_makes_the_source_unreadable(self):
        opener = FakeOpener([])

        with self.assertRaises(_http.SourceUnreadable) as caught:
            datadog.fetch(MONITORS, WINDOW, FRESH, [QUEUE], client(opener, environ={API_VAR: API_VALUE}))
        self.assertEqual(str(caught.exception), f"credentials missing: {APP_VAR}")


class MonitorsTest(unittest.TestCase):
    def test_reads_each_monitor_sorted_by_id(self):
        _, result = run(MONITORS, [QUEUE, CHECKOUT], FRESH, ok("monitor_alert.json"), ok("monitor_ok.json"), ok("events_empty.json"))

        self.assertEqual(
            result["records"]["monitors"],
            [
                {"id": "101", "name": "Checkout latency", "state": "OK", "priority": None, "link": APP + "/monitors/101"},
                {"id": "102", "name": "Queue depth", "state": "Alert", "priority": None, "link": APP + "/monitors/102"},
            ],
        )

    def test_gets_each_monitor_by_id_then_the_events(self):
        opener, _ = run(MONITORS, [QUEUE, CHECKOUT], FRESH, ok("monitor_alert.json"), ok("monitor_ok.json"), ok("events_empty.json"))

        self.assertEqual(
            [endpoint(request) for request in opener.requests],
            [("GET", "/api/v1/monitor/102"), ("GET", "/api/v1/monitor/101"), ("GET", "/api/v2/events")],
        )

    def test_read_monitors_are_ok_entries(self):
        _, result = run(MONITORS, [QUEUE, CHECKOUT], FRESH, ok("monitor_alert.json"), ok("monitor_ok.json"), ok("events_empty.json"))

        self.assertEqual(result["entries"], {"monitor-queue": OK, "monitor-checkout": OK})

    def test_not_found_monitor_is_a_missing_entry(self):
        _, result = run(MONITORS, [QUEUE, CHECKOUT], FRESH, status(404), ok("monitor_ok.json"), ok("events_empty.json"))

        self.assertEqual(result["entries"], {"monitor-queue": NOT_FOUND, "monitor-checkout": OK})

    def test_rejected_monitor_id_fails_only_its_entry(self):
        _, result = run(MONITORS, [QUEUE, CHECKOUT], FRESH, status(400), ok("monitor_ok.json"), ok("events_empty.json"))

        self.assertEqual(result["entries"], {"monitor-queue": failed("HTTP 400 GET /api/v1/monitor/102"), "monitor-checkout": OK})

    def test_missing_monitor_is_left_out_of_the_records(self):
        _, result = run(MONITORS, [QUEUE, CHECKOUT], FRESH, status(404), ok("monitor_ok.json"), ok("events_empty.json"))

        self.assertEqual([monitor["id"] for monitor in result["records"]["monitors"]], ["101"])

    def test_failed_monitor_is_left_out_of_the_records(self):
        _, result = run(MONITORS, [QUEUE, CHECKOUT], FRESH, status(400), ok("monitor_ok.json"), ok("events_empty.json"))

        self.assertEqual([monitor["id"] for monitor in result["records"]["monitors"]], ["101"])

    def test_missing_monitor_still_reads_the_source(self):
        _, result = run(MONITORS, [QUEUE], FRESH, status(404), ok("events_empty.json"))

        self.assertIsNone(roles.validate_collection(collection(MONITORS, result)))

    def test_by_id_read_records_the_priority(self):
        _, result = run(MONITORS, [QUEUE], FRESH, ok("monitor_priority.json"), ok("events_empty.json"))

        self.assertEqual(result["records"]["monitors"][0]["priority"], 2)

    def test_monitor_without_a_priority_reads_as_null(self):
        _, result = run(MONITORS, [QUEUE], FRESH, ok("monitor_alert.json"), ok("events_empty.json"))

        self.assertIsNone(result["records"]["monitors"][0]["priority"])

    def test_monitor_with_a_null_priority_reads_as_null(self):
        body = {"id": 102, "name": "Queue depth", "overall_state": "Alert", "priority": None}

        _, result = run(MONITORS, [QUEUE], FRESH, served(body), ok("events_empty.json"))

        self.assertIsNone(result["records"]["monitors"][0]["priority"])

    def test_monitor_priority_that_is_not_an_integer_reads_as_null(self):
        priorities = ("high", True, 2.5)

        read = [self.priority_of(priority) for priority in priorities]

        self.assertEqual(read, [None, None, None])

    def priority_of(self, priority):
        body = {"id": 102, "name": "Queue depth", "overall_state": "Alert", "priority": priority}
        _, result = run(MONITORS, [QUEUE], FRESH, served(body), ok("events_empty.json"))
        return result["records"]["monitors"][0]["priority"]

    def test_server_error_after_the_retry_fails_only_its_entry(self):
        _, result = run(MONITORS, [QUEUE], FRESH, status(503), status(503), ok("events_empty.json"))

        self.assertEqual(result["entries"], {"monitor-queue": failed("HTTP 503 GET /api/v1/monitor/102")})

    def test_non_numeric_monitor_id_fails_only_its_entry(self):
        _, result = run(MONITORS, [ODD, CHECKOUT], FRESH, ok("monitor_ok.json"), ok("events_empty.json"))

        self.assertEqual(result["entries"], {"monitor-odd": failed("monitor id 12ab is not a number"), "monitor-checkout": OK})

    def test_non_numeric_monitor_id_sends_no_request(self):
        opener, _ = run(MONITORS, [ODD], FRESH, ok("events_empty.json"))

        self.assertEqual([endpoint(request) for request in opener.requests], [("GET", "/api/v2/events")])

    def test_none_cursor_reads_like_an_empty_cursor(self):
        _, result = run(MONITORS, [QUEUE], None, ok("monitor_alert.json"), ok("events_empty.json"))

        self.assertEqual(result["cursor"], {"events_ts_ms": None, "monitors": {"102": "Alert"}})

    def test_monitor_without_a_state_fails_its_entry(self):
        _, result = run(MONITORS, [DISK], FRESH, ok("monitor_no_state.json"), ok("events_empty.json"))

        self.assertEqual(result["entries"], {"monitor-disk": failed("GET /api/v1/monitor/103: response without overall_state")})

    def test_unauthorized_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            run(MONITORS, [QUEUE, CHECKOUT], FRESH, status(401))
        self.assertEqual(str(caught.exception), "HTTP 401 GET /api/v1/monitor/102")

    def test_forbidden_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            run(MONITORS, [QUEUE, CHECKOUT], FRESH, status(403))
        self.assertEqual(str(caught.exception), "HTTP 403 GET /api/v1/monitor/102")

    def test_network_error_on_a_monitor_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            run(MONITORS, [QUEUE, CHECKOUT], FRESH, urllib.error.URLError(ConnectionRefusedError()))
        self.assertEqual(str(caught.exception), "GET /api/v1/monitor/102: ConnectionRefusedError")

    def test_response_without_id_reads_the_entry_monitor(self):
        _, result = run(MONITORS, [QUEUE], FRESH, served({"name": "Queue depth", "overall_state": "Warn"}), ok("events_empty.json"))

        self.assertEqual(
            result["records"]["monitors"],
            [{"id": "102", "name": "Queue depth", "state": "Warn", "priority": None, "link": APP + "/monitors/102"}],
        )

    def test_response_id_differing_from_the_entry_fails_it(self):
        _, result = run(MONITORS, [QUEUE], FRESH, served({"id": 105, "name": "Other", "overall_state": "OK"}), ok("events_empty.json"))

        self.assertEqual(
            result["entries"], {"monitor-queue": failed("GET /api/v1/monitor/102: response id 105 differs from monitor 102")}
        )

    def test_cursor_takes_read_states_and_keeps_the_others(self):
        stored = {"events_ts_ms": None, "monitors": {"102": "OK", "999": "Warn"}}

        _, result = run(MONITORS, [QUEUE, CHECKOUT], stored, status(404), ok("monitor_ok.json"), ok("events_empty.json"))

        self.assertEqual(result["cursor"]["monitors"], {"101": "OK", "102": "OK", "999": "Warn"})

    def test_collection_passes_the_role_schema(self):
        _, result = run(
            MONITORS, [QUEUE, CHECKOUT], FRESH, ok("monitor_alert.json"), ok("monitor_ok.json"), ok("events_page_1.json"), ok("events_page_2.json")
        )

        self.assertIsNone(roles.validate_collection(collection(MONITORS, result)))


class EventsTest(unittest.TestCase):
    def test_events_aggregate_per_monitor_taking_the_outer_timestamp_then_the_inner_one(self):
        _, result = run(MONITORS, [], FRESH, ok("events_page_1.json"), ok("events_page_2.json"), *missing_monitors(2))

        self.assertEqual(
            result["records"]["transitions"],
            [
                {"monitor": "101", "count": 2, "first_ts_ms": 1760001000000, "last_ts_ms": 1760002000000},
                {"monitor": "102", "count": 2, "first_ts_ms": 1760001000000, "last_ts_ms": 1760001000000},
            ],
        )

    def test_records_hold_no_raw_events(self):
        _, result = run(MONITORS, [], FRESH, ok("events_page_1.json"), ok("events_page_2.json"), *missing_monitors(2))

        self.assertEqual(sorted(result["records"]), ["discovered", "discovery", "monitors", "transitions"])

    def test_events_without_a_monitor_or_a_timestamp_are_not_counted(self):
        _, result = run(MONITORS, [], FRESH, ok("events_page_1.json"), ok("events_page_2.json"), *missing_monitors(2))

        self.assertEqual(sum(item["count"] for item in result["records"]["transitions"]), 4)

    def test_events_without_a_numeric_monitor_id_are_not_counted(self):
        self.assertEqual(transitions_of(dated(FROM_MS + 1000, "web-1"), dated(FROM_MS + 1000, "1.5"), dated(FROM_MS + 1000, True), reads=0), [])

    def test_events_at_the_window_bounds_count_and_those_just_outside_do_not(self):
        items = [dated(FROM_MS - 1), dated(FROM_MS), dated(TO_MS), dated(TO_MS + 1)]

        self.assertEqual(transitions_of(*items), [{"monitor": "301", "count": 2, "first_ts_ms": FROM_MS, "last_ts_ms": TO_MS}])

    def test_events_outside_the_window_move_the_cursor_but_name_no_monitor(self):
        opener, result = run(MONITORS, [], FRESH, events_page(dated(FROM_MS - 5), dated(TO_MS + 9)))

        self.assertEqual((result["records"]["transitions"], result["cursor"]["events_ts_ms"]), ([], TO_MS + 9))
        self.assertEqual(requested_paths(opener), ["/api/v2/events"])

    def test_events_without_a_monitor_move_the_cursor(self):
        _, result = run(MONITORS, [], FRESH, events_page(event("e1", timestamp=FROM_MS + 5)))

        self.assertEqual((result["records"]["transitions"], result["cursor"]["events_ts_ms"]), ([], FROM_MS + 5))

    def test_transitions_sort_by_monitor_id_length_then_text(self):
        items = [dated(FROM_MS + 1, 1010), dated(FROM_MS + 1, 99), dated(FROM_MS + 1, 100)]

        _, result = run(MONITORS, [], FRESH, events_page(*items), *missing_monitors(3))

        self.assertEqual([item["monitor"] for item in result["records"]["transitions"]], ["99", "100", "1010"])

    def test_iso_nanoseconds_truncate_to_milliseconds(self):
        self.assertEqual(transitions_of(dated("2025-10-09T08:55:00.123456789Z"))[0]["first_ts_ms"], 1760000100123)

    def test_iso_short_fraction_reads_as_milliseconds(self):
        self.assertEqual(transitions_of(dated("2025-10-09T08:55:00.5Z"))[0]["first_ts_ms"], 1760000100500)

    def test_iso_compact_offset_converts_to_utc(self):
        self.assertEqual(transitions_of(dated("2025-10-09T10:55:00+0200"))[0]["first_ts_ms"], 1760000100000)

    def test_unparseable_iso_timestamp_skips_the_event(self):
        self.assertEqual(transitions_of(dated("yesterday"), reads=0), [])

    def test_bool_timestamp_skips_the_event(self):
        self.assertEqual(transitions_of(dated(True), reads=0), [])

    def test_first_page_queries_the_window(self):
        opener, _ = run(MONITORS, [], FRESH, ok("events_empty.json"))

        self.assertEqual(
            query(opener.requests[0]),
            {
                "filter[query]": ["source:alert env:prod"],
                "filter[from]": [str(FROM_MS)],
                "filter[to]": [str(TO_MS)],
                "sort": ["timestamp"],
                "page[limit]": ["100"],
            },
        )

    def test_stored_cursor_inside_the_window_starts_after_the_last_event(self):
        opener, _ = run(MONITORS, [], {"events_ts_ms": STORED_TS, "monitors": {}}, ok("events_empty.json"))

        self.assertEqual(query(opener.requests[0])["filter[from]"], [str(STORED_TS + 1)])

    def test_stored_cursor_before_the_window_starts_at_the_window(self):
        opener, _ = run(MONITORS, [], {"events_ts_ms": FROM_MS - 3600000, "monitors": {}}, ok("events_empty.json"))

        self.assertEqual(query(opener.requests[0])["filter[from]"], [str(FROM_MS)])

    def test_empty_scope_filter_sends_no_query_filter(self):
        opener, _ = run({**MONITORS, "scope_filter": ""}, [], FRESH, ok("events_empty.json"))

        self.assertNotIn("filter[query]", query(opener.requests[0]))

    def test_next_page_follows_the_after_cursor(self):
        opener, _ = run(MONITORS, [], FRESH, ok("events_page_1.json"), ok("events_page_2.json"), *missing_monitors(2))

        self.assertEqual(query(opener.requests[1])["page[cursor]"], ["page-2"])

    def test_page_cap_marks_the_source_partial(self):
        pages = [ok("events_page_1.json") for _ in range(datadog.EVENTS_PAGE_CAP)]

        with self.assertRaises(_http.PartialRead) as caught:
            run(MONITORS, [], FRESH, *pages)
        self.assertEqual(str(caught.exception), "partial: page cap")

    def test_last_page_at_the_cap_reads_the_source(self):
        pages = [ok("events_page_1.json") for _ in range(datadog.EVENTS_PAGE_CAP - 1)] + [ok("events_page_2.json")]

        opener, _ = run(MONITORS, [], FRESH, *pages, *missing_monitors(2))

        self.assertEqual(requested_paths(opener).count("/api/v2/events"), datadog.EVENTS_PAGE_CAP)

    def test_pages_past_the_search_cap_are_read(self):
        pages = [ok("events_page_1.json") for _ in range(_http.PAGE_CAP)] + [ok("events_page_2.json")]

        opener, result = run(MONITORS, [], FRESH, *pages, *missing_monitors(2))

        self.assertEqual(requested_paths(opener).count("/api/v2/events"), _http.PAGE_CAP + 1)
        self.assertEqual({item["monitor"]: item["count"] for item in result["records"]["transitions"]}["102"], _http.PAGE_CAP + 1)

    def test_events_failure_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            run(MONITORS, [], FRESH, status(400))
        self.assertEqual(str(caught.exception), "HTTP 400 GET /api/v2/events")

    def test_cursor_advances_to_the_newest_event(self):
        _, result = run(MONITORS, [], {"events_ts_ms": STORED_TS, "monitors": {}}, ok("events_page_1.json"), ok("events_page_2.json"), *missing_monitors(2))

        self.assertEqual(result["cursor"]["events_ts_ms"], 1760002000000)

    def test_cursor_keeps_the_stored_position_without_events(self):
        _, result = run(MONITORS, [], {"events_ts_ms": STORED_TS, "monitors": {}}, ok("events_empty.json"))

        self.assertEqual(result["cursor"]["events_ts_ms"], STORED_TS)

    def test_cursor_stays_null_without_events_or_stored_position(self):
        _, result = run(MONITORS, [], FRESH, ok("events_empty.json"))

        self.assertIsNone(result["cursor"]["events_ts_ms"])


class LinksTest(unittest.TestCase):
    def test_two_label_site_prefixes_app(self):
        _, result = run(based(MONITORS, "https://api.example.eu"), [CHECKOUT], FRESH, ok("monitor_ok.json"), ok("events_empty.json"))

        self.assertEqual(result["records"]["monitors"][0]["link"], "https://app.example.eu/monitors/101")

    def test_regional_site_drops_api(self):
        _, result = run(based(MONITORS, "https://api.us3.example.com"), [CHECKOUT], FRESH, ok("monitor_ok.json"), ok("events_empty.json"))

        self.assertEqual(result["records"]["monitors"][0]["link"], "https://us3.example.com/monitors/101")

    def test_host_without_api_is_kept(self):
        _, result = run(based(MONITORS, "https://obs.example.test"), [CHECKOUT], FRESH, ok("monitor_ok.json"), ok("events_empty.json"))

        self.assertEqual(result["records"]["monitors"][0]["link"], "https://obs.example.test/monitors/101")

    def test_links_base_wins_over_the_base_url(self):
        source = configured(MONITORS, {**PROVIDER, "links_base": "https://ui.example.test/"})

        _, result = run(source, [CHECKOUT], FRESH, ok("monitor_ok.json"), ok("events_empty.json"))

        self.assertEqual(result["records"]["monitors"][0]["link"], "https://ui.example.test/monitors/101")

    def test_links_base_is_used_without_the_api_rewrite(self):
        source = configured(MONITORS, {**PROVIDER, "links_base": "https://api.example.eu"})

        _, result = run(source, [CHECKOUT], FRESH, ok("monitor_ok.json"), ok("events_empty.json"))

        self.assertEqual(result["records"]["monitors"][0]["link"], "https://api.example.eu/monitors/101")

    def test_provider_without_links_base_or_base_url_makes_monitors_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            run(configured(MONITORS, {"adapter": "datadog"}), [CHECKOUT], FRESH)
        self.assertEqual(str(caught.exception), "links_base missing in providers.obs")


class ScalarTest(unittest.TestCase):
    def test_reads_the_first_value(self):
        _, result = run(METRICS, [P95], NO_METRICS, ok("scalar.json"))

        self.assertEqual(result["records"]["metrics"], [{"key": "checkout-p95", "value": 42.5, "hourly": [], "groups": []}])

    def test_posts_to_the_scalar_endpoint(self):
        opener, _ = run(METRICS, [P95], NO_METRICS, ok("scalar.json"))

        self.assertEqual(endpoint(opener.requests[0]), ("POST", "/api/v2/query/scalar"))

    def test_request_body_queries_the_window_with_one_value(self):
        opener, _ = run(METRICS, [P95], NO_METRICS, ok("scalar.json"))

        self.assertEqual(
            sent(opener.requests[0]),
            {
                "data": {
                    "type": "scalar_request",
                    "attributes": {
                        "from": FROM_MS,
                        "to": TO_MS,
                        "queries": [{"data_source": "metrics", "query": QUERY, "name": "a", "aggregator": "avg"}],
                        "formulas": [{"formula": "a", "limit": {"count": 1, "order": "desc"}}],
                    },
                }
            },
        )

    def test_null_value_reads_as_null(self):
        _, result = run(METRICS, [P95], NO_METRICS, ok("scalar_null.json"))

        self.assertIsNone(result["records"]["metrics"][0]["value"])

    def test_response_without_columns_reads_as_null(self):
        _, result = run(METRICS, [P95], NO_METRICS, ok("scalar_empty.json"))

        self.assertIsNone(result["records"]["metrics"][0]["value"])

    def test_string_value_reads_as_null(self):
        _, result = run(METRICS, [P95], NO_METRICS, scalar_response(numbers("42")))

        self.assertIsNone(result["records"]["metrics"][0]["value"])

    def test_bool_value_reads_as_null(self):
        _, result = run(METRICS, [P95], NO_METRICS, scalar_response(numbers(True)))

        self.assertIsNone(result["records"]["metrics"][0]["value"])

    def test_non_finite_value_reads_as_null(self):
        _, result = run(METRICS, [P95], NO_METRICS, scalar_response(numbers(float("nan"))))

        self.assertIsNone(result["records"]["metrics"][0]["value"])


class TopTest(unittest.TestCase):
    def test_groups_sort_by_value_desc_then_group_with_nulls_last(self):
        _, result = run(METRICS, [BY_SERVICE], NO_METRICS, ok("top.json"))

        self.assertEqual(
            result["records"]["metrics"][0]["groups"],
            [
                {"group": "api", "value": 300.0},
                {"group": "batch,eu", "value": 120.0},
                {"group": "web", "value": 120.0},
                {"group": "jobs", "value": None},
            ],
        )

    def test_value_is_the_first_group_value(self):
        _, result = run(METRICS, [BY_SERVICE], NO_METRICS, ok("top.json"))

        self.assertEqual(result["records"]["metrics"][0]["value"], 300.0)

    def test_request_body_limits_to_the_top_groups(self):
        opener, _ = run(METRICS, [BY_SERVICE], NO_METRICS, ok("top.json"))

        self.assertEqual(
            sent(opener.requests[0]),
            {
                "data": {
                    "type": "scalar_request",
                    "attributes": {
                        "from": FROM_MS,
                        "to": TO_MS,
                        "queries": [{"data_source": "metrics", "query": QUERY, "name": "a", "aggregator": "sum"}],
                        "formulas": [{"formula": "a", "limit": {"count": 5, "order": "desc"}}],
                    },
                }
            },
        )

    def test_two_group_columns_join_their_tags(self):
        service = {"name": "service", "type": "group", "values": [["web"], ["api"]]}
        env = {"name": "env", "type": "group", "values": [["prod"], ["eu", "staging"]]}

        _, result = run(METRICS, [BY_SERVICE], NO_METRICS, scalar_response(service, env, numbers(2.0, 1.0)))

        self.assertEqual(
            result["records"]["metrics"][0]["groups"], [{"group": "web,prod", "value": 2.0}, {"group": "api,eu,staging", "value": 1.0}]
        )

    def test_string_group_value_reads_as_null(self):
        service = {"name": "service", "type": "group", "values": [["web"]]}

        _, result = run(METRICS, [BY_SERVICE], NO_METRICS, scalar_response(service, numbers("300")))

        self.assertEqual(result["records"]["metrics"][0]["groups"], [{"group": "web", "value": None}])

    def test_response_without_groups_reads_as_null(self):
        _, result = run(METRICS, [BY_SERVICE], NO_METRICS, ok("top_empty.json"))

        self.assertEqual(result["records"]["metrics"], [{"key": "errors-by-service", "value": None, "hourly": [], "groups": []}])


class HourlyTest(unittest.TestCase):
    def test_reads_each_hour_bucket_in_seconds(self):
        _, result = run(METRICS, [HOURLY], NO_METRICS, ok("timeseries.json"))

        self.assertEqual(
            result["records"]["metrics"][0]["hourly"],
            [{"ts": 1760000000, "value": 3.5}, {"ts": 1760003600, "value": None}, {"ts": 1760007200, "value": 7.25}],
        )

    def test_value_is_the_highest_bucket(self):
        _, result = run(METRICS, [HOURLY], NO_METRICS, ok("timeseries.json"))

        self.assertEqual(result["records"]["metrics"][0]["value"], 7.25)

    def test_posts_to_the_timeseries_endpoint(self):
        opener, _ = run(METRICS, [HOURLY], NO_METRICS, ok("timeseries.json"))

        self.assertEqual(endpoint(opener.requests[0]), ("POST", "/api/v2/query/timeseries"))

    def test_request_body_asks_for_hour_buckets(self):
        opener, _ = run(METRICS, [HOURLY], NO_METRICS, ok("timeseries.json"))

        self.assertEqual(
            sent(opener.requests[0]),
            {
                "data": {
                    "type": "timeseries_request",
                    "attributes": {
                        "from": FROM_MS,
                        "to": TO_MS,
                        "interval": 3600000,
                        "queries": [{"data_source": "metrics", "query": QUERY, "name": "a"}],
                        "formulas": [{"formula": "a"}],
                    },
                }
            },
        )

    def test_null_buckets_read_as_a_null_value(self):
        _, result = run(METRICS, [HOURLY], NO_METRICS, ok("timeseries_null.json"))

        self.assertIsNone(result["records"]["metrics"][0]["value"])

    def test_unsorted_times_sort_by_ts(self):
        times = [FROM_MS + 7200000, FROM_MS, FROM_MS + 3600000]

        _, result = run(METRICS, [HOURLY], NO_METRICS, timeseries_response(times, [3.0, 1.0, 2.0]))

        self.assertEqual(
            result["records"]["metrics"][0]["hourly"],
            [{"ts": 1760000000, "value": 1.0}, {"ts": 1760003600, "value": 2.0}, {"ts": 1760007200, "value": 3.0}],
        )

    def test_bool_bucket_reads_as_null(self):
        _, result = run(METRICS, [HOURLY], NO_METRICS, timeseries_response([FROM_MS, FROM_MS + 3600000], [True, 2.0]))

        self.assertEqual(result["records"]["metrics"][0]["hourly"], [{"ts": 1760000000, "value": None}, {"ts": 1760003600, "value": 2.0}])

    def test_string_time_fails_the_entry(self):
        _, result = run(METRICS, [HOURLY], NO_METRICS, timeseries_response([str(FROM_MS)], [2.0]))

        self.assertEqual(result["entries"], {"queue-hourly": failed("POST /api/v2/query/timeseries: response time is not a number")})

    def test_response_without_series_reads_as_empty(self):
        _, result = run(METRICS, [HOURLY], NO_METRICS, ok("timeseries_empty.json"))

        self.assertEqual(result["records"]["metrics"], [{"key": "queue-hourly", "value": None, "hourly": [], "groups": []}])


class MetricsTest(unittest.TestCase):
    def test_rejected_query_fails_only_its_entry(self):
        _, result = run(METRICS, [P95, BY_SERVICE], NO_METRICS, status(400), ok("top.json"))

        self.assertEqual(result["entries"], {"checkout-p95": failed("HTTP 400 POST /api/v2/query/scalar"), "errors-by-service": OK})

    def test_failed_query_is_left_out_of_the_records(self):
        _, result = run(METRICS, [P95, BY_SERVICE], NO_METRICS, status(400), ok("top.json"))

        self.assertEqual([metric["key"] for metric in result["records"]["metrics"]], ["errors-by-service"])

    def test_forbidden_makes_the_source_unreadable(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            run(METRICS, [P95, BY_SERVICE], NO_METRICS, status(403))
        self.assertEqual(str(caught.exception), "HTTP 403 POST /api/v2/query/scalar")

    def test_none_cursor_reads_like_an_empty_cursor(self):
        _, result = run(METRICS, [P95], None, ok("scalar.json"))

        self.assertEqual(result["cursor"], {"metrics": {"checkout-p95": 42.5}})

    def test_records_sort_by_key(self):
        _, result = run(METRICS, [HOURLY, P95], NO_METRICS, ok("timeseries.json"), ok("scalar.json"))

        self.assertEqual([metric["key"] for metric in result["records"]["metrics"]], ["checkout-p95", "queue-hourly"])

    def test_cursor_takes_read_values_and_keeps_the_others(self):
        stored = {"metrics": {"checkout-p95": 1.5, "queue-hourly": 4.0, "retired-key": 9}}

        _, result = run(METRICS, [P95, HOURLY, BY_SERVICE], stored, status(400), ok("timeseries.json"), ok("top_empty.json"))

        self.assertEqual(result["cursor"], {"metrics": {"checkout-p95": 1.5, "queue-hourly": 7.25, "retired-key": 9}})

    def test_collection_passes_the_role_schema(self):
        _, result = run(METRICS, [P95, BY_SERVICE, HOURLY], NO_METRICS, ok("scalar_null.json"), ok("top.json"), ok("timeseries.json"))

        self.assertIsNone(roles.validate_collection(collection(METRICS, result)))


def searches(opener):
    return [query(request) for request in opener.requests if endpoint(request)[1] == SEARCH_PATH]


class DiscoveryTest(unittest.TestCase):
    def test_without_a_query_nothing_is_searched(self):
        opener, result = run(MONITORS, [], FRESH, ok("events_empty.json"))

        self.assertEqual([endpoint(request) for request in opener.requests], [("GET", "/api/v2/events")])
        self.assertEqual(sorted(result["records"]), ["discovered", "discovery", "monitors", "transitions"])
        self.assertEqual((result["records"]["discovered"], result["records"]["discovery"]), ([], {"read": True, "reason": None}))

    def test_empty_query_searches_nothing(self):
        opener, result = run({**MONITORS, "discovery_query": ""}, [], FRESH, ok("events_empty.json"))

        self.assertEqual(len(opener.requests), 1)
        self.assertEqual((result["records"]["discovered"], result["records"]["discovery"]), ([], {"read": True, "reason": None}))

    def test_collection_without_a_query_passes_the_role_schema(self):
        _, result = run(MONITORS, [], FRESH, ok("events_empty.json"))

        self.assertIsNone(roles.validate_collection(collection(MONITORS, result)))

    def test_search_runs_after_the_by_id_reads_and_the_events(self):
        opener, _ = run(DISCOVERING, [QUEUE], FRESH, ok("monitor_alert.json"), ok("events_empty.json"), ok("search_empty.json"))

        self.assertEqual(
            [endpoint(request) for request in opener.requests],
            [("GET", "/api/v1/monitor/102"), ("GET", "/api/v2/events"), ("GET", SEARCH_PATH)],
        )

    def test_search_sends_the_query_page_and_page_size(self):
        opener, _ = discover(ok("search_page_1.json"), ok("search_page_2.json"))

        self.assertEqual(
            searches(opener),
            [
                {"query": ["status:alert env:prod"], "page": ["0"], "per_page": ["100"]},
                {"query": ["status:alert env:prod"], "page": ["1"], "per_page": ["100"]},
            ],
        )
        self.assertEqual(
            [request.full_url.split("?")[0] for request in opener.requests[1:]], [BASE + SEARCH_PATH, BASE + SEARCH_PATH]
        )

    def test_discovered_monitors_carry_id_name_state_priority_and_link(self):
        _, result = discover(ok("search_page_1.json"), ok("search_page_2.json"))

        self.assertEqual(
            result["records"]["discovered"],
            [
                {"id": "201", "name": "Checkout errors", "state": "Alert", "priority": 1, "link": APP + "/monitors/201"},
                {"id": "202", "name": "Cache hit ratio", "state": "No Data", "priority": 3, "link": APP + "/monitors/202"},
                {"id": "203", "name": "Disk usage", "state": "Warn", "priority": None, "link": APP + "/monitors/203"},
            ],
        )

    def test_a_read_discovery_is_marked_read(self):
        _, result = discover(ok("search_page_1.json"), ok("search_page_2.json"))

        self.assertEqual(result["records"]["discovery"], {"read": True, "reason": None})

    def test_a_search_with_no_monitor_is_read_and_empty(self):
        _, result = discover(ok("search_empty.json"))

        self.assertEqual((result["records"]["discovered"], result["records"]["discovery"]), ([], {"read": True, "reason": None}))

    def test_a_monitor_on_two_pages_is_discovered_once(self):
        _, result = discover(search_page(0, 2, found(201)), search_page(1, 2, found(201), found(202)))

        self.assertEqual([monitor["id"] for monitor in result["records"]["discovered"]], ["201", "202"])

    def test_search_priority_that_is_not_an_integer_reads_as_null(self):
        _, result = discover(search_page(0, 1, found(201, priority="high"), found(202, priority=True), found(203, priority=4)))

        self.assertEqual([monitor["priority"] for monitor in result["records"]["discovered"]], [None, None, 4])

    def test_discovered_monitors_are_not_added_to_the_cursor(self):
        _, result = discover(ok("search_page_1.json"), ok("search_page_2.json"))

        self.assertEqual(result["cursor"]["monitors"], {})

    def test_failed_search_leaves_the_source_and_the_by_id_reads_read(self):
        _, result = run(DISCOVERING, [QUEUE], FRESH, ok("monitor_alert.json"), ok("events_empty.json"), status(503), status(503))

        self.assertEqual(result["records"]["discovery"], {"read": False, "reason": "HTTP 503 GET /api/v1/monitor/search"})
        self.assertEqual(result["records"]["discovered"], [])
        self.assertEqual([monitor["id"] for monitor in result["records"]["monitors"]], ["102"])
        self.assertEqual(result["entries"], {"monitor-queue": OK})

    def test_forbidden_search_does_not_make_the_source_unreadable(self):
        _, result = discover(status(403))

        self.assertEqual(result["records"]["discovery"], {"read": False, "reason": "HTTP 403 GET /api/v1/monitor/search"})

    def test_search_network_error_does_not_make_the_source_unreadable(self):
        _, result = discover(urllib.error.URLError(ConnectionRefusedError()))

        self.assertEqual(
            result["records"]["discovery"], {"read": False, "reason": "GET /api/v1/monitor/search: ConnectionRefusedError"}
        )

    def test_failure_on_a_later_page_keeps_the_monitors_already_found(self):
        _, result = discover(ok("search_page_1.json"), status(400))

        self.assertEqual([monitor["id"] for monitor in result["records"]["discovered"]], ["201", "203"])
        self.assertEqual(result["records"]["discovery"], {"read": False, "reason": "HTTP 400 GET /api/v1/monitor/search"})

    def test_reaching_the_page_cap_marks_the_discovery_not_read(self):
        opener, result = discover(*[ok("search_capped.json") for _ in range(_http.PAGE_CAP)])

        self.assertEqual(result["records"]["discovery"], {"read": False, "reason": "partial: page cap"})
        self.assertEqual(len(searches(opener)), _http.PAGE_CAP)

    def test_capped_search_keeps_the_monitors_it_returned(self):
        _, result = discover(*[ok("search_capped.json") for _ in range(_http.PAGE_CAP)])

        self.assertEqual([monitor["id"] for monitor in result["records"]["discovered"]], ["201"])

    def test_capped_search_leaves_the_source_read(self):
        _, result = discover(*[ok("search_capped.json") for _ in range(_http.PAGE_CAP)])

        self.assertEqual(result["records"]["monitors"], [])
        self.assertIsNone(roles.validate_collection(collection(DISCOVERING, result)))

    def test_last_page_at_the_cap_reads_the_discovery(self):
        pages = [search_page(page, _http.PAGE_CAP, found(300 + page)) for page in range(_http.PAGE_CAP)]

        _, result = discover(*pages)

        self.assertEqual(result["records"]["discovery"], {"read": True, "reason": None})
        self.assertEqual(len(result["records"]["discovered"]), _http.PAGE_CAP)

    def test_response_without_a_monitor_list_marks_the_discovery_not_read(self):
        _, result = discover(ok("search_unreadable.json"))

        self.assertEqual(
            result["records"]["discovery"],
            {"read": False, "reason": "GET /api/v1/monitor/search: response without monitors or page_count"},
        )

    def test_response_without_a_page_count_marks_the_discovery_not_read(self):
        _, result = discover(served({"monitors": [found(201)], "metadata": {}}))

        self.assertEqual(result["records"]["discovery"]["read"], False)
        self.assertEqual(result["records"]["discovered"], [])

    def test_page_that_is_not_an_object_marks_the_discovery_not_read(self):
        _, result = discover(served([found(201)]))

        self.assertEqual(result["records"]["discovery"]["read"], False)

    def test_unreadable_page_keeps_the_monitors_of_earlier_pages(self):
        _, result = discover(search_page(0, 2, found(201)), ok("search_unreadable.json"))

        self.assertEqual([monitor["id"] for monitor in result["records"]["discovered"]], ["201"])
        self.assertEqual(result["records"]["discovery"]["read"], False)

    def test_monitor_without_a_numeric_id_makes_its_page_unreadable(self):
        _, result = discover(search_page(0, 1, found(201), found("12ab")))

        self.assertEqual(
            (result["records"]["discovered"], result["records"]["discovery"]),
            ([], {"read": False, "reason": "GET /api/v1/monitor/search: monitor without a numeric id"}),
        )

    def test_monitor_with_an_unknown_state_is_kept_with_its_state(self):
        _, result = discover(search_page(0, 1, found(201, "Paused")))

        self.assertEqual([(monitor["id"], monitor["state"]) for monitor in result["records"]["discovered"]], [("201", "Paused")])
        self.assertEqual(result["records"]["discovery"], {"read": True, "reason": None})

    def test_monitor_without_a_text_state_makes_its_page_unreadable(self):
        _, result = discover(search_page(0, 1, found(201), found(202, None)))

        self.assertEqual(
            (result["records"]["discovered"], result["records"]["discovery"]),
            ([], {"read": False, "reason": "GET /api/v1/monitor/search: monitor without a state"}),
        )

    def test_monitor_read_by_id_and_found_by_the_search_is_in_both_lists(self):
        _, result = run(
            DISCOVERING, [QUEUE], FRESH, ok("monitor_alert.json"), ok("events_empty.json"), search_page(0, 1, found(102), found(201))
        )

        self.assertEqual([monitor["id"] for monitor in result["records"]["monitors"]], ["102"])
        self.assertEqual([monitor["id"] for monitor in result["records"]["discovered"]], ["102", "201"])

    def test_events_failure_makes_the_source_unreadable_before_any_search(self):
        opener = FakeOpener([status(403)])

        with self.assertRaises(_http.SourceUnreadable):
            datadog.fetch(DISCOVERING, WINDOW, FRESH, [], client(opener))
        self.assertEqual(searches(opener), [])

    def test_collection_passes_the_role_schema_when_read(self):
        _, result = discover(ok("search_page_1.json"), ok("search_page_2.json"))

        self.assertIsNone(roles.validate_collection(collection(DISCOVERING, result)))

    def test_collection_passes_the_role_schema_when_the_discovery_failed(self):
        _, result = discover(status(400))

        self.assertIsNone(roles.validate_collection(collection(DISCOVERING, result)))


def requested_paths(opener):
    return [urllib.parse.urlsplit(request.full_url).path for request in opener.requests]


class EventMonitorTest(unittest.TestCase):
    def test_monitor_named_by_an_event_is_read_by_id_after_the_events_and_listed_as_discovered(self):
        opener, result = run(MONITORS, [], FRESH, named_by_event(301), monitor_body(301, "OK", priority=3))

        self.assertEqual(requested_paths(opener), ["/api/v2/events", "/api/v1/monitor/301"])
        self.assertEqual(
            result["records"]["discovered"], [{"id": "301", "name": "Monitor 301", "state": "OK", "priority": 3, "link": APP + "/monitors/301"}]
        )

    def test_monitors_of_the_entries_and_the_search_are_not_read_again(self):
        opener, result = run(
            DISCOVERING,
            [QUEUE],
            FRESH,
            ok("monitor_alert.json"),
            named_by_event(102, 201, 301),
            search_page(0, 1, found(201)),
            monitor_body(301),
        )

        self.assertEqual(requested_paths(opener)[-1], "/api/v1/monitor/301")
        self.assertEqual((len(opener.requests), [monitor["id"] for monitor in result["records"]["discovered"]]), (4, ["201", "301"]))

    def test_entry_whose_read_failed_is_not_read_again_by_the_events(self):
        opener, result = run(MONITORS, [QUEUE], FRESH, status(404), named_by_event(102))

        self.assertEqual((len(opener.requests), result["records"]["discovered"]), (2, []))

    def test_a_monitor_named_by_several_events_is_read_once(self):
        opener, _ = run(MONITORS, [], FRESH, named_by_event(301, 301), monitor_body(301))

        self.assertEqual(requested_paths(opener).count("/api/v1/monitor/301"), 1)

    def test_event_monitor_id_that_is_not_a_number_sends_no_request(self):
        opener, result = run(MONITORS, [], FRESH, named_by_event("12ab"))

        self.assertEqual((len(opener.requests), result["records"]["discovered"]), (1, []))

    def test_not_found_event_monitor_is_skipped(self):
        _, result = run(MONITORS, [], FRESH, named_by_event(301, 302), status(404), monitor_body(302))

        self.assertEqual([monitor["id"] for monitor in result["records"]["discovered"]], ["302"])

    def test_not_found_event_monitor_leaves_the_discovery_read(self):
        _, result = run(MONITORS, [], FRESH, named_by_event(301), status(404))

        self.assertEqual(result["records"]["discovery"], {"read": True, "reason": None})

    def test_failed_event_monitor_read_marks_the_discovery_not_read_and_keeps_the_others(self):
        _, result = run(MONITORS, [], FRESH, named_by_event(301, 302), status(403), monitor_body(302))

        self.assertEqual([monitor["id"] for monitor in result["records"]["discovered"]], ["302"])
        self.assertEqual(result["records"]["discovery"], {"read": False, "reason": "HTTP 403 GET /api/v1/monitor/301"})

    def test_event_monitor_read_that_hits_the_network_error_marks_the_discovery_not_read(self):
        _, result = run(MONITORS, [], FRESH, named_by_event(301), urllib.error.URLError(ConnectionRefusedError()))

        self.assertEqual(result["records"]["discovered"], [])
        self.assertEqual(result["records"]["discovery"], {"read": False, "reason": "GET /api/v1/monitor/301: ConnectionRefusedError"})

    def test_first_failed_event_monitor_read_gives_the_reason(self):
        _, result = run(MONITORS, [], FRESH, named_by_event(301, 302), status(403), status(400))

        self.assertEqual(result["records"]["discovery"]["reason"], "HTTP 403 GET /api/v1/monitor/301")

    def test_failed_search_keeps_its_reason_when_an_event_monitor_read_fails_too(self):
        _, result = run(DISCOVERING, [], FRESH, named_by_event(301), status(400), status(403))

        self.assertEqual(result["records"]["discovery"], {"read": False, "reason": "HTTP 400 GET /api/v1/monitor/search"})

    def test_event_monitor_with_an_unknown_state_is_kept_with_its_state(self):
        _, result = run(MONITORS, [], FRESH, named_by_event(301), monitor_body(301, "Weird"))

        self.assertEqual(
            result["records"]["discovered"], [{"id": "301", "name": "Monitor 301", "state": "Weird", "priority": None, "link": APP + "/monitors/301"}]
        )
        self.assertEqual(result["records"]["discovery"], {"read": True, "reason": None})

    def test_event_monitor_without_a_state_marks_the_discovery_not_read(self):
        _, result = run(MONITORS, [], FRESH, named_by_event(301), served({"id": 301, "name": "Monitor 301"}))

        self.assertEqual(result["records"]["discovered"], [])
        self.assertEqual(result["records"]["discovery"], {"read": False, "reason": "GET /api/v1/monitor/301: response without overall_state"})

    def test_event_monitors_are_not_added_to_the_cursor_or_the_entries(self):
        _, result = run(MONITORS, [], FRESH, named_by_event(301), monitor_body(301))

        self.assertEqual((result["cursor"]["monitors"], result["entries"]), ({}, {}))

    def test_event_monitors_join_the_discovered_ones_in_id_order(self):
        _, result = run(DISCOVERING, [], FRESH, named_by_event(301), search_page(0, 1, found(401), found(201)), monitor_body(301))

        self.assertEqual([monitor["id"] for monitor in result["records"]["discovered"]], ["201", "301", "401"])

    def test_event_monitors_are_read_without_a_discovery_query_and_leave_the_discovery_read(self):
        _, result = run(MONITORS, [], FRESH, named_by_event(301), monitor_body(301))

        self.assertEqual(result["records"]["discovery"], {"read": True, "reason": None})

    def test_event_monitors_are_read_after_a_failed_search(self):
        opener, result = run(DISCOVERING, [], FRESH, named_by_event(301), status(403), monitor_body(301))

        self.assertEqual(requested_paths(opener)[-1], "/api/v1/monitor/301")
        self.assertEqual(
            (result["records"]["discovery"]["read"], [monitor["id"] for monitor in result["records"]["discovered"]]), (False, ["301"])
        )

    def test_the_50_lowest_event_monitor_ids_are_read_and_the_excess_marks_the_discovery_capped(self):
        ids = [1000 + number for number in range(51, 0, -1)]
        opener, result = run(MONITORS, [], FRESH, named_by_event(*ids), *(monitor_body(number) for number in range(1001, 1051)))

        self.assertEqual(
            requested_paths(opener)[1:], [f"/api/v1/monitor/{number}" for number in range(1001, 1051)]
        )
        self.assertEqual(result["records"]["discovery"], {"read": True, "reason": None, "event_monitors_capped": True})
        self.assertEqual(len(result["records"]["discovered"]), 50)

    def test_event_monitor_ids_are_ordered_by_length_then_text(self):
        ids = [1000 + number for number in range(50)] + [999]
        opener, _ = run(MONITORS, [], FRESH, named_by_event(*ids), *(monitor_body(number) for number in [999, *range(1000, 1049)]))

        self.assertEqual(requested_paths(opener)[1], "/api/v1/monitor/999")

    def test_exactly_50_event_monitors_are_not_a_cap(self):
        _, result = run(MONITORS, [], FRESH, named_by_event(*range(1001, 1051)), *(monitor_body(number) for number in range(1001, 1051)))

        self.assertEqual(result["records"]["discovery"], {"read": True, "reason": None})

    def test_collection_passes_the_role_schema_when_an_event_monitor_read_failed(self):
        _, result = run(MONITORS, [], FRESH, named_by_event(301), status(403))

        self.assertIsNone(roles.validate_collection(collection(MONITORS, result)))

    def test_collection_with_event_monitors_passes_the_role_schema(self):
        _, result = run(MONITORS, [], FRESH, named_by_event(*range(1001, 1052)), *(monitor_body(number) for number in range(1001, 1051)))

        self.assertIsNone(roles.validate_collection(collection(MONITORS, result)))


class LookbackTest(unittest.TestCase):
    DAILY = lookback(HOURLY)

    def test_hourly_lookback_posts_the_span_at_a_daily_interval(self):
        opener, _ = run(METRICS, [self.DAILY], NO_METRICS, ok("timeseries_daily.json"))

        attributes = sent(opener.requests[0])["data"]["attributes"]
        self.assertEqual((attributes["from"], attributes["to"], attributes["interval"]), (LOOKBACK_FROM_MS, TO_MS, 86400000))

    def test_hourly_lookback_keeps_the_query_and_formula(self):
        opener, _ = run(METRICS, [self.DAILY], NO_METRICS, ok("timeseries_daily.json"))

        attributes = sent(opener.requests[0])["data"]["attributes"]
        self.assertEqual(
            (attributes["queries"], attributes["formulas"]),
            ([{"data_source": "metrics", "query": QUERY, "name": "a"}], [{"formula": "a"}]),
        )

    def test_hourly_lookback_posts_to_the_timeseries_endpoint(self):
        opener, _ = run(METRICS, [self.DAILY], NO_METRICS, ok("timeseries_daily.json"))

        self.assertEqual(endpoint(opener.requests[0]), ("POST", "/api/v2/query/timeseries"))

    def test_hourly_lookback_reads_a_daily_series_and_no_hourly_points(self):
        _, result = run(METRICS, [self.DAILY], NO_METRICS, ok("timeseries_daily.json"))

        record = result["records"]["metrics"][0]
        self.assertEqual(record["hourly"], [])
        self.assertEqual(
            record["daily"],
            [
                {"ts": 1759406000, "value": 12.5},
                {"ts": 1759492400, "value": None},
                {"ts": 1759578800, "value": 30.0},
                {"ts": 1759665200, "value": 8.0},
                {"ts": 1759751600, "value": 41.5},
                {"ts": 1759838000, "value": 22.0},
                {"ts": 1759924400, "value": 5.25},
            ],
        )

    def test_hourly_lookback_value_is_the_highest_day(self):
        _, result = run(METRICS, [self.DAILY], NO_METRICS, ok("timeseries_daily.json"))

        self.assertEqual(result["records"]["metrics"][0]["value"], 41.5)

    def test_hourly_lookback_cursor_takes_the_value(self):
        _, result = run(METRICS, [self.DAILY], NO_METRICS, ok("timeseries_daily.json"))

        self.assertEqual(result["cursor"], {"metrics": {"queue-hourly": 41.5}})

    def test_hourly_lookback_without_a_series_reads_as_empty(self):
        _, result = run(METRICS, [self.DAILY], NO_METRICS, ok("timeseries_empty.json"))

        self.assertEqual(
            result["records"]["metrics"], [{"key": "queue-hourly", "value": None, "hourly": [], "daily": [], "groups": []}]
        )

    def test_hourly_without_a_lookback_has_no_daily_series(self):
        _, result = run(METRICS, [HOURLY], NO_METRICS, ok("timeseries.json"))

        self.assertNotIn("daily", result["records"]["metrics"][0])

    def test_scalar_lookback_aggregates_over_the_span(self):
        opener, _ = run(METRICS, [lookback(P95)], NO_METRICS, ok("scalar_lookback.json"))

        attributes = sent(opener.requests[0])["data"]["attributes"]
        self.assertEqual(endpoint(opener.requests[0]), ("POST", "/api/v2/query/scalar"))
        self.assertEqual((attributes["from"], attributes["to"]), (LOOKBACK_FROM_MS, TO_MS))

    def test_scalar_lookback_reads_the_value_without_daily_points(self):
        _, result = run(METRICS, [lookback(P95)], NO_METRICS, ok("scalar_lookback.json"))

        self.assertEqual(result["records"]["metrics"], [{"key": "checkout-p95", "value": 17.25, "hourly": [], "groups": []}])

    def test_top_lookback_aggregates_over_the_span(self):
        opener, result = run(METRICS, [lookback(BY_SERVICE)], NO_METRICS, ok("top.json"))

        attributes = sent(opener.requests[0])["data"]["attributes"]
        self.assertEqual((attributes["from"], attributes["to"]), (LOOKBACK_FROM_MS, TO_MS))
        self.assertEqual(result["records"]["metrics"][0]["groups"][0], {"group": "api", "value": 300.0})

    def test_entry_without_a_span_reads_the_run_window(self):
        opener, _ = run(METRICS, [P95], NO_METRICS, ok("scalar.json"))

        attributes = sent(opener.requests[0])["data"]["attributes"]
        self.assertEqual((attributes["from"], attributes["to"]), (FROM_MS, TO_MS))

    def test_lookback_and_window_entries_read_in_the_same_run(self):
        opener, result = run(METRICS, [self.DAILY, HOURLY], NO_METRICS, ok("timeseries_daily.json"), ok("timeseries.json"))

        bodies = [sent(request)["data"]["attributes"] for request in opener.requests]
        self.assertEqual([(body["from"], body["interval"]) for body in bodies], [(LOOKBACK_FROM_MS, 86400000), (FROM_MS, 3600000)])

    def test_collection_passes_the_role_schema_with_lookbacks(self):
        _, result = run(
            METRICS,
            [self.DAILY, lookback(P95), lookback(BY_SERVICE)],
            NO_METRICS,
            ok("timeseries_daily.json"),
            ok("scalar_lookback.json"),
            ok("top.json"),
        )

        self.assertIsNone(roles.validate_collection(collection(METRICS, result)))


class TrendTest(unittest.TestCase):
    TREND = trended(HOURLY, "max")
    TIMESERIES = "/api/v2/query/timeseries"

    def read(self, entry, *outcomes):
        return run(METRICS, [entry], NO_METRICS, *outcomes, window=TREND_WINDOW)

    def trend_of(self, aggregator, document=TREND_SERIES):
        _, result = self.read(trended(HOURLY, aggregator), ok("timeseries.json"), series_response(document))
        return result["records"]["metrics"][0]["trend"]

    def test_trend_span_is_read_hourly_after_the_window_read(self):
        opener, _ = self.read(self.TREND, ok("timeseries.json"), series_response(TREND_SERIES))

        bodies = [sent(request)["data"]["attributes"] for request in opener.requests]
        self.assertEqual(
            [(body["from"], body["to"], body["interval"]) for body in bodies], [(FROM_MS, TO_MS, 3600000), (TREND_FROM_MS, TO_MS, 3600000)]
        )

    def test_trend_read_posts_the_entry_query_to_the_timeseries_endpoint(self):
        opener, _ = self.read(self.TREND, ok("timeseries.json"), series_response(TREND_SERIES))

        attributes = sent(opener.requests[1])["data"]["attributes"]
        self.assertEqual(endpoint(opener.requests[1]), ("POST", self.TIMESERIES))
        self.assertEqual(
            (attributes["queries"], attributes["formulas"]), ([{"data_source": "metrics", "query": QUERY, "name": "a"}], [{"formula": "a"}])
        )

    def test_scalar_entry_reads_its_trend_as_a_timeseries_after_the_scalar_read(self):
        opener, _ = self.read(trended(P95, "avg"), ok("scalar.json"), series_response(TREND_SERIES))

        self.assertEqual(
            [endpoint(request) for request in opener.requests], [("POST", "/api/v2/query/scalar"), ("POST", self.TIMESERIES)]
        )
        self.assertEqual(sent(opener.requests[1])["data"]["attributes"]["interval"], 3600000)

    def test_max_takes_the_highest_hour_of_each_day(self):
        self.assertEqual(
            self.trend_of("max"), [{"day": "2025-10-05", "value": 9.0}, {"day": "2025-10-07", "value": 7.0}]
        )

    def test_min_takes_the_lowest_hour_of_each_day(self):
        self.assertEqual(
            self.trend_of("min"), [{"day": "2025-10-05", "value": 2.0}, {"day": "2025-10-07", "value": 1.0}]
        )

    def test_sum_adds_the_hours_of_each_day(self):
        self.assertEqual(
            self.trend_of("sum"), [{"day": "2025-10-05", "value": 15.0}, {"day": "2025-10-07", "value": 8.0}]
        )

    def test_avg_is_the_mean_of_the_hourly_values_of_each_day(self):
        self.assertEqual(
            self.trend_of("avg"), [{"day": "2025-10-05", "value": 5.0}, {"day": "2025-10-07", "value": 4.0}]
        )

    def test_last_takes_the_latest_hour_with_a_value_of_each_day(self):
        self.assertEqual(
            self.trend_of("last"), [{"day": "2025-10-05", "value": 2.0}, {"day": "2025-10-07", "value": 1.0}]
        )

    def test_day_without_a_point_is_absent(self):
        self.assertNotIn("2025-10-06", [point["day"] for point in self.trend_of("max")])

    def test_point_lands_in_its_local_day(self):
        trend = self.trend_of("sum", series(at(1, 23, 5.0), at(2, 0, 6.0)))

        self.assertEqual(trend, [{"day": "2025-10-06", "value": 5.0}, {"day": "2025-10-07", "value": 6.0}])

    def test_spring_forward_day_aggregates_its_23_hours(self):
        trend = self.trend_of("sum", clock_change_series(SPRING_FORWARD_DAY, 23))

        self.assertEqual(
            trend,
            [{"day": "2026-03-28", "value": 100.0}, {"day": "2026-03-29", "value": 23.0}, {"day": "2026-03-30", "value": 200.0}],
        )

    def test_fall_back_day_aggregates_its_25_hours(self):
        trend = self.trend_of("sum", clock_change_series(FALL_BACK_DAY, 25))

        self.assertEqual(
            trend,
            [{"day": "2026-10-24", "value": 100.0}, {"day": "2026-10-25", "value": 25.0}, {"day": "2026-10-26", "value": 200.0}],
        )

    def test_trend_sits_next_to_the_window_value_and_hourly_points(self):
        _, result = self.read(self.TREND, ok("timeseries.json"), series_response(TREND_SERIES))

        record = result["records"]["metrics"][0]
        self.assertEqual((record["value"], len(record["hourly"]), record["trend_reason"]), (7.25, 3, None))

    def test_trend_read_leaves_the_entry_ok(self):
        _, result = self.read(self.TREND, ok("timeseries.json"), series_response(TREND_SERIES))

        self.assertEqual(result["entries"], {"queue-hourly": OK})

    def test_series_without_a_point_has_no_trend(self):
        _, result = self.read(self.TREND, ok("timeseries.json"), series_response(series()))

        record = result["records"]["metrics"][0]
        self.assertEqual((record["trend"], record["trend_reason"]), (None, "no datapoints"))

    def test_series_of_null_values_has_no_trend(self):
        _, result = self.read(self.TREND, ok("timeseries.json"), series_response(series(at(0, 0, None), at(0, 1, None))))

        record = result["records"]["metrics"][0]
        self.assertEqual((record["trend"], record["trend_reason"]), (None, "no datapoints"))

    def test_failed_trend_read_names_the_status_and_keeps_the_window_value(self):
        _, result = self.read(self.TREND, ok("timeseries.json"), status(500), status(500))

        record = result["records"]["metrics"][0]
        self.assertEqual((record["value"], record["trend"], record["trend_reason"]), (7.25, None, "HTTP 500 POST " + self.TIMESERIES))

    def test_failed_trend_read_leaves_the_entry_ok(self):
        _, result = self.read(self.TREND, ok("timeseries.json"), status(500), status(500))

        self.assertEqual(result["entries"], {"queue-hourly": OK})

    def test_trend_response_time_that_is_not_a_number_sets_the_reason(self):
        document = {"times": ["noon"], "values": [[1.0]]}
        _, result = self.read(self.TREND, ok("timeseries.json"), series_response(document))

        record = result["records"]["metrics"][0]
        self.assertEqual((record["trend"], record["trend_reason"]), (None, "POST " + self.TIMESERIES + ": response time is not a number"))

    def test_unauthorized_trend_read_fails_the_source(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            self.read(self.TREND, ok("timeseries.json"), status(401))

        self.assertEqual((str(caught.exception), caught.exception.status), ("HTTP 401 POST " + self.TIMESERIES, 401))

    def test_forbidden_trend_read_fails_the_source(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            self.read(self.TREND, ok("timeseries.json"), status(403))

        self.assertEqual(caught.exception.status, 403)

    def test_network_error_on_the_trend_read_fails_the_source(self):
        with self.assertRaises(_http.SourceUnreadable) as caught:
            self.read(self.TREND, ok("timeseries.json"), urllib.error.URLError("unreachable"))

        self.assertIsNone(caught.exception.status)

    def test_failed_window_read_skips_the_trend_read(self):
        opener, result = self.read(self.TREND, status(400))

        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(result["entries"], {"queue-hourly": failed("HTTP 400 POST " + self.TIMESERIES)})

    def test_entry_without_a_trend_span_carries_no_trend_keys_and_reads_once(self):
        opener, result = self.read(HOURLY, ok("timeseries.json"))

        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(set(result["records"]["metrics"][0]), {"key", "value", "hourly", "groups"})

    def test_collection_passes_the_role_schema_with_trends(self):
        entries = [self.TREND, {**trended(P95, "avg"), "key": "scalar-trend"}, {**self.TREND, "key": "empty-trend"}]
        _, result = run(
            METRICS,
            entries,
            NO_METRICS,
            ok("timeseries.json"),
            series_response(TREND_SERIES),
            ok("scalar.json"),
            status(500),
            status(500),
            ok("timeseries.json"),
            series_response(series()),
            window=TREND_WINDOW,
        )

        self.assertIsNone(roles.validate_collection(collection(METRICS, result)))


MONITOR_STATES = ["OK", "Alert", "Warn", "No Data", "Skipped", "Unknown", "Ignored"]


def monitor_in_state(name):
    return served({"id": 102, "name": "Queue depth", "overall_state": name})


def api_state(name):
    _, result = run(MONITORS, [QUEUE], FRESH, monitor_in_state(name), ok("events_empty.json"))
    return result["records"]["monitors"][0]["state"]


class MonitorStateTest(unittest.TestCase):
    def test_keeps_each_known_monitor_state(self):
        self.assertEqual([api_state(name) for name in MONITOR_STATES], MONITOR_STATES)

    def test_unknown_monitor_state_fails_only_its_entry(self):
        _, result = run(MONITORS, [QUEUE, CHECKOUT], FRESH, monitor_in_state("Paused"), ok("monitor_ok.json"), ok("events_empty.json"))

        self.assertEqual(result["entries"], {"monitor-queue": failed("GET /api/v1/monitor/102: unknown monitor state: Paused"), "monitor-checkout": OK})

    def test_unknown_monitor_state_is_cleaned_in_the_failure_reason(self):
        _, result = run(MONITORS, [QUEUE], FRESH, monitor_in_state("Pau\nsed @here"), ok("events_empty.json"))

        self.assertEqual(result["entries"], {"monitor-queue": failed("GET /api/v1/monitor/102: unknown monitor state: Pau sed  here")})

    def test_unknown_monitor_state_is_cut_to_50_characters_in_the_failure_reason(self):
        _, result = run(MONITORS, [QUEUE], FRESH, monitor_in_state("S" * 80), ok("events_empty.json"))

        self.assertEqual(result["entries"], {"monitor-queue": failed("GET /api/v1/monitor/102: unknown monitor state: " + "S" * 50)})

    def test_unknown_monitor_state_is_left_out_of_the_records(self):
        _, result = run(MONITORS, [QUEUE, CHECKOUT], FRESH, monitor_in_state("Paused"), ok("monitor_ok.json"), ok("events_empty.json"))

        self.assertEqual([monitor["id"] for monitor in result["records"]["monitors"]], ["101"])


if __name__ == "__main__":
    unittest.main()
