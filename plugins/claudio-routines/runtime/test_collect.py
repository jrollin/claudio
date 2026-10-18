import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import collect
import roles
import state
from providers._http import PAGE_CAP, PartialRead, SourceUnreadable
from providers._errors import CredentialsMissing

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE_ADAPTERS_MAIN = """
import sys, types
sys.path.insert(0, sys.argv[1])
for name, role in (("fakeobs", "observability"), ("fakedoc", "document_store")):
    module = types.ModuleType("providers." + name)
    module.ROLE = role
    sys.modules[module.__name__] = module
import collect
sys.exit(collect.main(sys.argv[2:]))
"""
ROUTINE = "prod-watch"
OBS_HOST = "api.example.test"
DOC_HOST = "docs.example.test"
OBS_KEY_VAR = "OBS_API_KEY"
OBS_APP_VAR = "OBS_APP_KEY"
DOC_TOKEN_VAR = "DOC_TOKEN"
WINDOW_END = 1_780_011_000
UTC_DAY = "2026-05-28"
PARIS_DAY = "2026-05-29"
MONITOR_ID = str(4000 + 2)
OTHER_MONITOR_ID = str(4000 + 3)
TRACKED_MONITOR_ID = str(4000 + 4)
API_KEY = "monitor-" + MONITOR_ID
DB_KEY = "monitor-" + OTHER_MONITOR_ID
TRACKED_KEY = "monitor-" + TRACKED_MONITOR_ID
EVENT_TS_MS = (WINDOW_END - 60) * 1000
STORED_TS_MS = (WINDOW_END - 7200) * 1000
UTC_EDIT = "2026-10-01T08:00:00.000Z"
CLIENT = object()
SENTINEL = "-".join(["sentinel", "response", "text"])
OK = {"status": "ok", "reason": None}
RESPONSES = "responses"
ADAPTER_CONNECTOR = "adapter-connector"


def page_id():
    return "page-" + "ab" * 4


def entry(key, source, **fields):
    base = {
        "key": key,
        "source": source,
        "title": key + " title",
        "link": "https://app.example.test/" + key,
        "rule": key + " rule",
        "schedule": "every_run",
    }
    return {**base, **fields}


def metric(key, schedule):
    return entry(
        key,
        "metrics",
        schedule=schedule,
        query="avg:api.latency{env:prod}",
        read="scalar",
        aggregator="max",
    )


def tracked_item():
    return {
        "title": "tracked monitor",
        "topic": "monitors",
        "severity": "High",
        "when": "now",
        "status": "open",
        "confidence": "high",
        "since": "2026-05-30T08:00:00Z",
        "runs_under_threshold": 0,
        "last_value": "Alert",
        "link": "https://app.example.test/tracked",
    }


def tracked_entry():
    return {"key": TRACKED_KEY, "monitor": TRACKED_MONITOR_ID}


def make_config():
    return {
        "timezone": "Europe/Paris",
        "places": {
            "cloud": {"runtime_dir": "/opt/runtime", "state_dir": "/opt/state"},
            "local": {"runtime_dir": "/srv/runtime", "state_dir": "/srv/state"},
        },
        "providers": {
            "obs": {
                "adapter": "fakeobs",
                "api": {"base_url": "https://" + OBS_HOST, "credentials": {"api_key": OBS_KEY_VAR, "app_key": OBS_APP_VAR}},
                "mcp": {"connectors": {"cloud": "obs-cloud", "local": "obs-local"}},
            },
            "docs": {
                "adapter": "fakedoc",
                "api": {"base_url": "https://" + DOC_HOST + "/v1", "credentials": {"token": DOC_TOKEN_VAR}},
                "mcp": {"connectors": {"cloud": "docs-cloud", "local": "docs-local"}},
            },
        },
        "routines": {
            ROUTINE: {
                "sources": {
                    "monitors": {"provider": "obs", "transport": {"cloud": "api", "local": "api"}, "kind": "monitors", "scope_filter": ""},
                    "metrics": {"provider": "obs", "transport": {"cloud": "api", "local": "mcp"}, "kind": "metrics", "scope_filter": "env:prod"},
                    "sources-page": {"provider": "docs", "transport": {"cloud": "mcp", "local": "api"}, "page_id": page_id()},
                },
                "query_pack": [
                    entry(API_KEY, "monitors", monitor=MONITOR_ID),
                    entry(DB_KEY, "monitors", monitor=OTHER_MONITOR_ID),
                    metric("api-p95", "every_run"),
                    metric("db-size", "daily"),
                ],
            }
        },
    }


def make_state():
    document = state.initial_state("prod-watch")
    document["cursors"]["observability"] = {
        "events_ts_ms": STORED_TS_MS,
        "monitors": {MONITOR_ID: "OK"},
        "metrics": {"api-p95": 380.0},
    }
    return document


def make_window(retry_known_gaps=True):
    return {
        "from_ts": WINDOW_END - 3600,
        "to_ts": WINDOW_END,
        "buckets": [],
        "cut": False,
        "explicit": False,
        "retry_known_gaps": retry_known_gaps,
    }


UNREAD_MONITORS = {"monitors": [], "events": [], "discovered": [], "discovery": None}
RESULTS = {
    "monitors": (
        {
            "monitors": [{"id": MONITOR_ID, "name": "API errors", "state": "Alert", "priority": None, "link": "https://app.example.test/m"}],
            "events": [{"ts_ms": EVENT_TS_MS, "link": "https://app.example.test/e", "monitor": MONITOR_ID}],
            "discovered": [],
            "discovery": {"read": True, "reason": None},
        },
        {"events_ts_ms": EVENT_TS_MS, "monitors": {MONITOR_ID: "Alert"}},
    ),
    "metrics": (
        {"metrics": [{"key": "api-p95", "value": 420.5, "hourly": [], "groups": []}]},
        {"metrics": {"api-p95": 420.5}},
    ),
    "document_store": (
        {"pages": [{"id": page_id(), "title": "Sources", "last_edited": UTC_EDIT, "blocks": [{"type": "heading", "text": "Mutes", "rows": None}]}]},
        {"last_edited": UTC_EDIT},
    ),
}


def planned_call(name, page):
    arguments = {"page": page}
    return {
        "id": f"{name}-{page}",
        "connector": ADAPTER_CONNECTOR,
        "tool": "read-page",
        "arguments": arguments,
        "digest": roles.fnv1a32(roles.params_text(arguments)),
    }


def fake_adapter(name, role):
    module = types.ModuleType(f"providers.{name}")
    module.ROLE = role
    module.calls = []
    module.clients = []
    module.plans = []
    module.parses = []
    module.error = None
    module.client_error = None
    module.plan_error = None
    module.result = None
    module.plan_result = None
    module.pages = 2

    def api_client(provider, opener=None, environ=None, sleep=None):
        module.clients.append(provider)
        if module.client_error is not None:
            raise module.client_error
        return CLIENT

    def outcome(source, entries):
        if module.error is not None:
            raise module.error
        if module.result is not None:
            return module.result
        records, next_cursor = RESULTS[source.get("kind", role)]
        return {"records": records, "cursor": next_cursor, "entries": {item["key"]: {"status": "ok", "reason": None} for item in entries}}

    def fetch(source, window, cursor, entries, http):
        module.calls.append({"source": source, "window": window, "cursor": cursor, "entries": entries, "http": http})
        return outcome(source, entries)

    def plan(source, window, cursor, entries, responses, connector):
        module.plans.append({"source": source, "cursor": cursor, "entries": entries, "responses": dict(responses), "connector": connector})
        if module.plan_error is not None:
            raise module.plan_error
        if module.plan_result is not None:
            return module.plan_result
        if len(responses) >= module.pages:
            return {"done": True, "partial": None, "calls": []}
        return {"done": False, "partial": None, "calls": [planned_call(source["name"], len(responses) + 1)]}

    def parse(source, window, cursor, entries, responses, digests):
        module.parses.append({"source": source, "cursor": cursor, "entries": entries, "responses": dict(responses), "digests": digests})
        return outcome(source, entries)

    module.api_client = api_client
    module.fetch = fetch
    module.plan = plan
    module.parse = parse
    return module


class CollectTestCase(unittest.TestCase):
    def setUp(self):
        self.obs = fake_adapter("fakeobs", "observability")
        self.doc = fake_adapter("fakedoc", "document_store")
        self.modules = mock.patch.dict(sys.modules, {"providers.fakeobs": self.obs, "providers.fakedoc": self.doc})
        self.modules.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.config = make_config()
        self.state = make_state()
        self.window = make_window()

    def tearDown(self):
        self.modules.stop()
        self.tmp.cleanup()

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def write(self, name, document):
        with open(self.path(name), "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        return self.path(name)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = collect.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def run_command(self, command, place="cloud"):
        config = self.write("config.json", self.config)
        return self.run_main(command, "--config", config, "--routine", ROUTINE, "--place", place)

    def fetch(self, source="monitors", place="cloud", out=None):
        config = self.write("config.json", self.config)
        window = self.write("window.json", self.window)
        stored = self.write("state.json", self.state)
        return self.run_main(
            "fetch", "--config", config, "--routine", ROUTINE, "--source", source, "--place", place,
            "--window", window, "--state", stored, "--out", out or self.path("collection.json"),
        )

    def collection(self):
        with open(self.path("collection.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def written(self):
        with open(self.path("collection.json"), encoding="utf-8") as handle:
            return handle.read()

    def adapter_keys(self, adapter):
        return [item["key"] for item in adapter.calls[0]["entries"]]

    def statuses(self):
        return {key: value["status"] for key, value in self.collection()["entries"].items()}

    def adapter_result(self, entries):
        records, cursor = RESULTS["monitors"]
        self.obs.result = {"records": records, "cursor": cursor, "entries": entries}

    def invalid_result(self):
        self.obs.result = {"records": {"monitors": [{"id": 7}], "events": []}, "cursor": RESULTS["monitors"][1], "entries": {}}


class ParserTest(unittest.TestCase):
    COMMON = ["--config", "c", "--routine", ROUTINE, "--place", "cloud"]

    def parse(self, *argv):
        return collect.build_parser().parse_args(list(argv))

    def test_parses_the_five_commands(self):
        fetch = ["--source", "s", "--window", "w", "--state", "s", "--out", "o"]
        relay = [*fetch, "--responses", "d"]
        parsed = [
            self.parse("sources", *self.COMMON).command,
            self.parse("check-env", *self.COMMON).command,
            self.parse("fetch", *self.COMMON, *fetch).command,
            self.parse("plan", *self.COMMON, *relay).command,
            self.parse("parse", *self.COMMON, *relay).command,
        ]
        self.assertEqual(parsed, ["sources", "check-env", "fetch", "plan", "parse"])

    def test_rejects_a_command_outside_the_five(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            self.parse("relay", *self.COMMON)
        self.assertEqual(raised.exception.code, 2)

    def test_plan_requires_the_responses_directory(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            self.parse("plan", *self.COMMON, "--source", "s", "--window", "w", "--state", "s", "--out", "o")
        self.assertEqual(raised.exception.code, 2)

    def test_fetch_requires_the_output_path(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            collect.build_parser().parse_args(
                ["fetch", "--config", "c", "--routine", ROUTINE, "--source", "s", "--place", "cloud", "--window", "w", "--state", "s"]
            )
        self.assertEqual(raised.exception.code, 2)


class ConfigCheckTest(CollectTestCase):
    def test_an_invalid_config_exits_2(self):
        self.config["routines"][ROUTINE]["sources"]["monitors"]["provider"] = "absent"
        self.assertEqual(self.fetch()[0], 2)

    def test_an_invalid_config_names_the_key_path(self):
        self.config["routines"][ROUTINE]["sources"]["monitors"]["provider"] = "absent"
        self.assertIn(f"routines.{ROUTINE}.sources.monitors.provider", self.fetch()[2])

    def test_an_invalid_config_makes_no_provider_call(self):
        self.config["routines"][ROUTINE]["sources"]["monitors"]["provider"] = "absent"
        self.fetch()
        self.assertEqual(self.obs.clients, [])

    def test_an_unreadable_config_exits_2(self):
        code = self.run_main("sources", "--config", self.path("absent.json"), "--routine", ROUTINE, "--place", "cloud")[0]
        self.assertEqual(code, 2)

    def test_an_invalid_query_pack_exits_3(self):
        del self.config["routines"][ROUTINE]["query_pack"][0]["rule"]
        self.assertEqual(self.fetch()[0], 3)

    def test_an_invalid_query_pack_names_the_key_path(self):
        del self.config["routines"][ROUTINE]["query_pack"][0]["rule"]
        self.assertIn(f"routines.{ROUTINE}.query_pack[0].rule: missing", self.fetch()[2])

    def test_an_invalid_query_pack_makes_no_provider_call(self):
        del self.config["routines"][ROUTINE]["query_pack"][0]["rule"]
        self.fetch()
        self.assertEqual(self.obs.clients, [])

    def test_a_query_pack_title_over_300_characters_exits_3_naming_the_key_path(self):
        self.config["routines"][ROUTINE]["query_pack"][0]["title"] = "t" * 301
        code, _, err = self.fetch()
        self.assertEqual((code, f"routines.{ROUTINE}.query_pack[0].title" in err), (3, True))

    def test_a_query_pack_link_with_a_line_separator_exits_3_naming_the_key_path(self):
        self.config["routines"][ROUTINE]["query_pack"][0]["link"] = "https://app.example.test/\u2028"
        code, _, err = self.fetch()
        self.assertEqual((code, f"routines.{ROUTINE}.query_pack[0].link" in err), (3, True))

    def test_a_query_pack_title_over_300_characters_makes_no_provider_call(self):
        self.config["routines"][ROUTINE]["query_pack"][0]["title"] = "t" * 301
        self.fetch()
        self.assertEqual((self.obs.clients, self.obs.calls), ([], []))

    def test_a_pack_key_equal_to_a_source_name_exits_3(self):
        sources = self.config["routines"][ROUTINE]["sources"]
        sources["api-p95"] = dict(sources["metrics"])
        self.assertEqual(self.fetch()[0], 3)

    def test_an_unknown_source_exits_2(self):
        self.assertEqual(self.fetch(source="absent")[0], 2)

    def test_an_unknown_time_zone_exits_2(self):
        self.config["timezone"] = "Mars/Olympus"
        self.assertEqual(self.fetch()[0], 2)

    def test_an_unknown_time_zone_names_the_timezone_key(self):
        self.config["timezone"] = "Mars/Olympus"
        self.assertIn("timezone: unknown time zone Mars/Olympus", self.fetch()[2])

    def test_a_missing_time_zone_exits_2(self):
        del self.config["timezone"]
        self.assertEqual(self.fetch()[0], 2)

    def test_a_non_string_time_zone_exits_2(self):
        self.config["timezone"] = 2
        self.assertEqual(self.fetch()[0], 2)

    def test_a_document_store_fetch_needs_no_time_zone(self):
        del self.config["timezone"]
        self.assertEqual(self.fetch(source="sources-page", place="local")[0], 0)

    def test_a_rejected_state_exits_3(self):
        self.state["schema"] = 99
        self.assertEqual(self.fetch()[0], 3)

    def test_a_write_failure_exits_2(self):
        self.assertEqual(self.fetch(out=self.path(os.path.join("absent", "collection.json")))[0], 2)

    def test_sources_exits_3_on_an_invalid_query_pack(self):
        del self.config["routines"][ROUTINE]["query_pack"][0]["rule"]
        self.assertEqual(self.run_command("sources")[0], 3)

    def test_check_env_exits_3_on_an_invalid_query_pack(self):
        del self.config["routines"][ROUTINE]["query_pack"][0]["rule"]
        self.assertEqual(self.run_command("check-env")[0], 3)

    def test_a_window_without_retry_known_gaps_exits_3(self):
        del self.window["retry_known_gaps"]
        self.assertEqual(self.fetch()[0], 3)


class McpTransportTest(CollectTestCase):
    def test_fetch_on_an_mcp_source_exits_2(self):
        self.assertEqual(self.fetch(source="metrics", place="local")[0], 2)

    def test_fetch_on_an_mcp_source_names_the_source_place_and_transport(self):
        self.assertIn("source metrics uses the mcp transport at place local", self.fetch(source="metrics", place="local")[2])

    def test_fetch_on_an_mcp_source_makes_no_provider_call(self):
        self.fetch(source="metrics", place="local")
        self.assertEqual(self.obs.clients, [])

    def test_fetch_on_an_mcp_source_writes_no_collection(self):
        self.fetch(source="metrics", place="local")
        self.assertFalse(os.path.exists(self.path("collection.json")))


class SourcesTest(CollectTestCase):
    def test_lists_each_source_with_its_role_provider_and_place_transport(self):
        expected = [
            {"provider": "obs", "role": "observability", "source": "metrics", "transport": "mcp"},
            {"provider": "obs", "role": "observability", "source": "monitors", "transport": "api"},
            {"provider": "docs", "role": "document_store", "source": "sources-page", "transport": "api"},
        ]
        self.assertEqual(self.run_command("sources", place="local")[1], state.dump(expected).decode("utf-8"))

    def test_exits_0(self):
        self.assertEqual(self.run_command("sources")[0], 0)


class CheckEnvTest(CollectTestCase):
    def check_env(self, environ, place="cloud"):
        with mock.patch.dict(os.environ, environ, clear=True):
            return self.run_command("check-env", place=place)

    def test_exits_1_when_a_variable_is_missing(self):
        self.assertEqual(self.check_env({OBS_KEY_VAR: "set"})[0], 1)

    def test_prints_missing_variables_and_connectors_sorted(self):
        expected = f"connector sources-page docs-cloud\nmissing metrics {OBS_APP_VAR}\nmissing monitors {OBS_APP_VAR}\n"
        self.assertEqual(self.check_env({OBS_KEY_VAR: "set"})[1], expected)

    def test_counts_an_empty_variable_as_missing(self):
        environ = {OBS_KEY_VAR: "set", OBS_APP_VAR: "", DOC_TOKEN_VAR: "set"}
        self.assertIn(f"missing monitors {OBS_APP_VAR}", self.check_env(environ, place="local")[1])

    def test_exits_0_when_every_variable_is_set(self):
        environ = {OBS_KEY_VAR: "set", OBS_APP_VAR: "set"}
        self.assertEqual(self.check_env(environ)[0], 0)

    def test_prints_only_connectors_when_every_variable_is_set(self):
        environ = {OBS_KEY_VAR: "set", OBS_APP_VAR: "set", DOC_TOKEN_VAR: "set"}
        self.assertEqual(self.check_env(environ, place="local")[1], "connector metrics obs-local\n")


class FetchReadTest(CollectTestCase):
    def test_exits_0(self):
        self.assertEqual(self.fetch()[0], 0)

    def test_writes_the_collection(self):
        self.fetch()
        records, cursor = RESULTS["monitors"]
        expected = {
            "schema": 1,
            "source": "monitors",
            "role": "observability",
            "provider": "obs",
            "transport": "api",
            "place": "cloud",
            "window": {"from_ts": WINDOW_END - 3600, "to_ts": WINDOW_END},
            "read": True,
            "reason": None,
            "cursor": cursor,
            "records": records,
            "entries": {API_KEY: {"status": "ok", "reason": None}, DB_KEY: {"status": "ok", "reason": None}},
        }
        self.assertEqual(self.collection(), expected)

    def test_writes_canonical_json(self):
        self.fetch()
        with open(self.path("collection.json"), "rb") as handle:
            raw = handle.read()
        self.assertEqual(raw, state.dump(json.loads(raw)))

    def test_builds_the_client_from_the_provider_config(self):
        self.fetch()
        self.assertEqual(self.obs.clients, [self.config["providers"]["obs"]])

    def test_passes_the_client_to_the_adapter(self):
        self.fetch()
        self.assertIs(self.obs.calls[0]["http"], CLIENT)

    def test_passes_the_source_config_with_its_name(self):
        self.fetch()
        expected = {
            **self.config["routines"][ROUTINE]["sources"]["monitors"],
            "name": "monitors",
            "provider_config": self.config["providers"]["obs"],
        }
        self.assertEqual(self.obs.calls[0]["source"], expected)

    def test_passes_the_window(self):
        self.fetch()
        self.assertEqual(self.obs.calls[0]["window"], self.window)

    def test_passes_the_stored_monitors_cursor(self):
        self.fetch()
        self.assertEqual(self.obs.calls[0]["cursor"], {"events_ts_ms": STORED_TS_MS, "monitors": {MONITOR_ID: "OK"}})

    def test_passes_the_stored_metrics_cursor(self):
        self.fetch(source="metrics")
        self.assertEqual(self.obs.calls[0]["cursor"], {"metrics": {"api-p95": 380.0}})

    def test_passes_the_stored_cursor_of_another_role(self):
        self.state["cursors"]["sources-page"] = {"last_edited": UTC_EDIT}
        self.fetch(source="sources-page", place="local")
        self.assertEqual(self.doc.calls[0]["cursor"], {"last_edited": UTC_EDIT})

    def test_passes_a_null_cursor_when_none_is_stored(self):
        self.fetch(source="sources-page", place="local")
        self.assertIsNone(self.doc.calls[0]["cursor"])

    def test_passes_no_entries_to_another_role(self):
        self.fetch(source="sources-page", place="local")
        self.assertEqual(self.doc.calls[0]["entries"], [])

    def test_passes_only_the_entries_of_the_source(self):
        self.fetch()
        self.assertEqual(self.adapter_keys(self.obs), [API_KEY, DB_KEY])

    def test_passes_a_null_cursor_when_the_stored_one_breaks_the_schema(self):
        self.state["cursors"]["observability"]["events_ts_ms"] = STORED_TS_MS + 0.5
        self.fetch()
        self.assertIsNone(self.obs.calls[0]["cursor"])

    def test_fails_a_selected_entry_the_adapter_did_not_report(self):
        self.adapter_result({API_KEY: OK})
        self.fetch()
        self.assertEqual(self.collection()["entries"][DB_KEY], {"status": "failed", "reason": "not reported by the adapter"})

    def test_ignores_an_adapter_entry_outside_the_selection(self):
        self.adapter_result({API_KEY: OK, DB_KEY: OK, "monitor-extra": OK})
        self.fetch()
        self.assertEqual(sorted(self.collection()["entries"]), [API_KEY, DB_KEY])

    def test_keeps_a_deferred_entry_the_adapter_reported(self):
        self.state["blind_spots"] = [{"key": DB_KEY, "gap": "no data", "runs": 3}]
        self.window = make_window(retry_known_gaps=False)
        self.adapter_result({API_KEY: OK, DB_KEY: OK})
        self.fetch()
        self.assertEqual(self.collection()["entries"][DB_KEY], {"status": "deferred", "reason": "known gap"})


class InvalidAdapterResultTest(CollectTestCase):
    def setUp(self):
        super().setUp()
        self.invalid_result()

    def test_exits_0(self):
        self.assertEqual(self.fetch()[0], 0)

    def test_marks_the_source_not_read_naming_the_key_path(self):
        self.fetch()
        reason = self.collection()["reason"]
        self.assertEqual([self.collection()["read"], reason.startswith("adapter output invalid: records.monitors[0].id")], [False, True])

    def test_writes_empty_records_and_the_stored_cursor(self):
        self.fetch()
        expected = [UNREAD_MONITORS, {"events_ts_ms": STORED_TS_MS, "monitors": {MONITOR_ID: "OK"}}]
        self.assertEqual([self.collection()["records"], self.collection()["cursor"]], expected)

    def test_fails_the_selected_entries(self):
        self.fetch()
        self.assertEqual(self.statuses(), {API_KEY: "failed", DB_KEY: "failed"})


class EntrySelectionTest(CollectTestCase):
    def test_reads_a_daily_entry_when_the_local_day_differs(self):
        self.state["run"]["daily_metrics_on"] = UTC_DAY
        self.fetch(source="metrics")
        self.assertEqual(self.adapter_keys(self.obs), ["api-p95", "db-size"])

    def test_skips_a_daily_entry_already_read_on_the_local_day(self):
        self.state["run"]["daily_metrics_on"] = PARIS_DAY
        self.fetch(source="metrics")
        self.assertEqual(self.adapter_keys(self.obs), ["api-p95"])

    def test_defers_a_daily_entry_not_due(self):
        self.state["run"]["daily_metrics_on"] = PARIS_DAY
        self.fetch(source="metrics")
        self.assertEqual(self.collection()["entries"]["db-size"], {"status": "deferred", "reason": "not due"})

    def test_reads_a_daily_entry_when_the_window_end_starts_a_new_local_day(self):
        self.window["from_ts"] = WINDOW_END - 7200
        self.state["run"]["daily_metrics_on"] = UTC_DAY
        self.fetch(source="metrics")
        self.assertEqual(self.adapter_keys(self.obs), ["api-p95", "db-size"])

    def test_defers_a_daily_entry_read_on_the_local_day_of_the_window_end(self):
        self.window["from_ts"] = WINDOW_END - 7200
        self.state["run"]["daily_metrics_on"] = PARIS_DAY
        self.fetch(source="metrics")
        self.assertEqual(self.collection()["entries"]["db-size"], {"status": "deferred", "reason": "not due"})

    def test_skips_a_known_gap_when_gaps_are_not_retried(self):
        self.state["blind_spots"] = [{"key": DB_KEY, "gap": "no data", "runs": 3}]
        self.window = make_window(retry_known_gaps=False)
        self.fetch()
        self.assertEqual(self.adapter_keys(self.obs), [API_KEY])

    def test_defers_a_known_gap_not_retried(self):
        self.state["blind_spots"] = [{"key": DB_KEY, "gap": "no data", "runs": 3}]
        self.window = make_window(retry_known_gaps=False)
        self.fetch()
        self.assertEqual(self.collection()["entries"][DB_KEY], {"status": "deferred", "reason": "known gap"})

    def test_reads_a_known_gap_when_gaps_are_retried(self):
        self.state["blind_spots"] = [{"key": DB_KEY, "gap": "no data", "runs": 3}]
        self.fetch()
        self.assertEqual(self.adapter_keys(self.obs), [API_KEY, DB_KEY])

    def test_defers_a_key_both_not_due_and_a_known_gap_as_not_due(self):
        self.state["run"]["daily_metrics_on"] = PARIS_DAY
        self.state["blind_spots"] = [{"key": "db-size", "gap": "no data", "runs": 3}]
        self.window = make_window(retry_known_gaps=False)
        self.fetch(source="metrics")
        self.assertEqual(self.collection()["entries"]["db-size"], {"status": "deferred", "reason": "not due"})

    def test_reads_a_gap_below_three_runs(self):
        self.state["blind_spots"] = [{"key": DB_KEY, "gap": "no data", "runs": 2}]
        self.window = make_window(retry_known_gaps=False)
        self.fetch()
        self.assertEqual(self.adapter_keys(self.obs), [API_KEY, DB_KEY])


class TrackedMonitorTest(CollectTestCase):
    def setUp(self):
        super().setUp()
        self.state["items"][TRACKED_KEY] = tracked_item()

    def entries(self, source="monitors"):
        self.fetch(source=source)
        return self.obs.calls[0]["entries"]

    def test_hands_a_tracked_monitor_the_pack_does_not_list_to_the_adapter(self):
        self.assertEqual(self.entries()[2:], [tracked_entry()])

    def test_keeps_the_pack_entries_ahead_of_the_tracked_monitors(self):
        self.assertEqual([item["key"] for item in self.entries()], [API_KEY, DB_KEY, TRACKED_KEY])

    def test_hands_a_tracked_monitor_the_pack_lists_once(self):
        self.state["items"][API_KEY] = tracked_item()
        self.assertEqual([item["key"] for item in self.entries()], [API_KEY, DB_KEY, TRACKED_KEY])

    def test_keeps_the_pack_entry_of_a_tracked_monitor_the_pack_lists(self):
        self.state["items"][API_KEY] = tracked_item()
        self.assertEqual(self.entries()[0], self.config["routines"][ROUTINE]["query_pack"][0])

    def test_orders_the_tracked_monitors_by_key(self):
        later, earlier = state.MONITOR_PREFIX + str(4000 + 9), state.MONITOR_PREFIX + str(4000 + 5)
        self.state["items"][later] = tracked_item()
        self.state["items"][earlier] = tracked_item()
        self.assertEqual([item["key"] for item in self.entries()[2:]], [TRACKED_KEY, earlier, later])

    def test_ignores_a_state_key_that_is_not_a_monitor_id(self):
        for key in (state.MONITOR_PREFIX, TRACKED_KEY + "x", state.MONITOR_PREFIX + "api", state.MONITOR_PREFIX + "\u0661", "api-p95", "x" + TRACKED_KEY):
            self.state["items"][key] = tracked_item()
        self.assertEqual([item["key"] for item in self.entries()], [API_KEY, DB_KEY, TRACKED_KEY])

    def test_hands_no_tracked_monitor_to_a_metrics_source(self):
        self.assertEqual([item["key"] for item in self.entries(source="metrics")], ["api-p95", "db-size"])

    def test_hands_no_tracked_monitor_to_another_role(self):
        self.fetch(source="sources-page", place="local")
        self.assertEqual(self.doc.calls[0]["entries"], [])

    def test_hands_the_tracked_monitors_to_the_first_monitors_source_by_name(self):
        sources = self.config["routines"][ROUTINE]["sources"]
        sources["alpha-monitors"] = dict(sources["monitors"])
        self.assertEqual(self.entries(source="alpha-monitors"), [tracked_entry()])

    def test_hands_no_tracked_monitor_to_a_later_monitors_source(self):
        sources = self.config["routines"][ROUTINE]["sources"]
        sources["alpha-monitors"] = dict(sources["monitors"])
        self.assertEqual([item["key"] for item in self.entries()], [API_KEY, DB_KEY])

    def test_names_a_tracked_monitor_in_the_collection_entries(self):
        self.fetch()
        self.assertEqual(self.collection()["entries"][TRACKED_KEY], OK)

    def test_fails_a_tracked_monitor_the_adapter_did_not_report(self):
        self.adapter_result({API_KEY: OK, DB_KEY: OK})
        self.fetch()
        self.assertEqual(self.collection()["entries"][TRACKED_KEY], {"status": "failed", "reason": "not reported by the adapter"})

    def test_defers_a_tracked_monitor_with_a_known_gap_not_retried(self):
        self.state["blind_spots"] = [{"key": TRACKED_KEY, "gap": "no data", "runs": 3}]
        self.window = make_window(retry_known_gaps=False)
        self.fetch()
        self.assertEqual(self.collection()["entries"][TRACKED_KEY], {"status": "deferred", "reason": "known gap"})

    def test_hands_a_tracked_monitor_with_a_known_gap_not_retried_to_no_adapter(self):
        self.state["blind_spots"] = [{"key": TRACKED_KEY, "gap": "no data", "runs": 3}]
        self.window = make_window(retry_known_gaps=False)
        self.assertEqual([item["key"] for item in self.entries()], [API_KEY, DB_KEY])

    def test_reads_a_tracked_monitor_with_a_known_gap_when_gaps_are_retried(self):
        self.state["blind_spots"] = [{"key": TRACKED_KEY, "gap": "no data", "runs": 3}]
        self.assertEqual([item["key"] for item in self.entries()], [API_KEY, DB_KEY, TRACKED_KEY])

    def test_reads_a_tracked_monitor_when_every_pack_entry_is_deferred(self):
        self.state["blind_spots"] = [{"key": API_KEY, "gap": "no data", "runs": 3}, {"key": DB_KEY, "gap": "no data", "runs": 3}]
        self.window = make_window(retry_known_gaps=False)
        self.assertEqual(self.entries(), [tracked_entry()])

    def test_reads_a_tracked_monitor_on_a_day_a_daily_entry_is_not_due(self):
        self.state["run"]["daily_metrics_on"] = PARIS_DAY
        self.assertEqual([item["key"] for item in self.entries()], [API_KEY, DB_KEY, TRACKED_KEY])

    def test_hands_a_tracked_monitor_to_the_relay_plan_and_parse(self):
        self.config["routines"][ROUTINE]["sources"]["monitors"]["transport"]["cloud"] = "mcp"
        self.obs.pages = 0
        config = self.write("config.json", self.config)
        common = [
            "--config", config, "--routine", ROUTINE, "--source", "monitors", "--place", "cloud",
            "--window", self.write("window.json", self.window), "--state", self.write("state.json", self.state),
            "--responses", self.path(RESPONSES),
        ]
        self.run_main("plan", *common, "--out", self.path("plan.json"))
        self.run_main("parse", *common, "--out", self.path("collection.json"))
        self.assertEqual([self.obs.plans[0]["entries"][-1], self.obs.parses[0]["entries"][-1]], [tracked_entry(), tracked_entry()])


class LookbackSpanTest(CollectTestCase):
    def lookback(self, days=7):
        self.config["routines"][ROUTINE]["query_pack"][3]["lookback_days"] = days
        self.state["run"]["daily_metrics_on"] = UTC_DAY
        self.fetch(source="metrics")
        return {item["key"]: item for item in self.obs.calls[0]["entries"]}

    def test_gives_a_lookback_entry_a_span_ending_at_the_window_end(self):
        self.assertEqual(self.lookback(7)["db-size"]["span"], {"from_ts": WINDOW_END - 7 * 86400, "to_ts": WINDOW_END})

    def test_sizes_the_span_by_the_lookback_days(self):
        self.assertEqual(self.lookback(31)["db-size"]["span"]["from_ts"], WINDOW_END - 31 * 86400)

    def test_ends_the_span_at_the_window_end_of_a_cut_window(self):
        self.window["from_ts"] = WINDOW_END - 72 * 3600
        self.window["cut"] = {"from_ts": WINDOW_END - 77 * 3600, "to_ts": WINDOW_END - 72 * 3600}
        self.assertEqual(self.lookback(2)["db-size"]["span"], {"from_ts": WINDOW_END - 2 * 86400, "to_ts": WINDOW_END})

    def test_keeps_the_lookback_days_on_the_entry(self):
        self.assertEqual(self.lookback(7)["db-size"]["lookback_days"], 7)

    def test_gives_an_entry_without_a_lookback_no_span(self):
        self.assertNotIn("span", self.lookback()["api-p95"])

    def test_gives_a_daily_entry_without_a_lookback_no_span(self):
        self.state["run"]["daily_metrics_on"] = UTC_DAY
        self.fetch(source="metrics")
        entries = {item["key"]: item for item in self.obs.calls[0]["entries"]}
        self.assertNotIn("span", entries["db-size"])

    def test_leaves_the_run_window_of_the_call_unchanged(self):
        self.lookback()
        self.assertEqual(self.obs.calls[0]["window"], self.window)

    def test_does_not_hand_a_deferred_lookback_entry_to_the_adapter(self):
        self.config["routines"][ROUTINE]["query_pack"][3]["lookback_days"] = 7
        self.state["run"]["daily_metrics_on"] = PARIS_DAY
        self.fetch(source="metrics")
        self.assertEqual(self.adapter_keys(self.obs), ["api-p95"])


class RoutineRulesTest(CollectTestCase):
    def test_accepts_the_routine_rules(self):
        self.config["routines"][ROUTINE]["rules"] = ["flapping monitors are noise"]
        self.assertEqual(self.fetch()[0], 0)

    def test_accepts_a_routine_without_rules(self):
        self.assertNotIn("rules", self.config["routines"][ROUTINE])
        self.assertEqual(self.fetch()[0], 0)

    def test_a_null_routine_rules_exits_3_naming_the_key_path(self):
        self.config["routines"][ROUTINE]["rules"] = None
        code, _, err = self.fetch()
        self.assertEqual([code, f"routines.{ROUTINE}.rules" in err], [3, True])

    def test_an_invalid_routine_rule_exits_3(self):
        self.config["routines"][ROUTINE]["rules"] = [""]
        self.assertEqual(self.fetch()[0], 3)

    def test_an_invalid_routine_rule_names_the_key_path(self):
        self.config["routines"][ROUTINE]["rules"] = ["fine", "x" * 501]
        self.assertIn(f"routines.{ROUTINE}.rules[1]", self.fetch()[2])

    def test_an_invalid_routine_rule_makes_no_provider_call(self):
        self.config["routines"][ROUTINE]["rules"] = [""]
        self.fetch()
        self.assertEqual(self.obs.clients, [])

    def test_sources_exits_3_on_an_invalid_routine_rule(self):
        self.config["routines"][ROUTINE]["rules"] = [""]
        self.assertEqual(self.run_command("sources")[0], 3)


class FetchNotReadTest(CollectTestCase):
    def test_names_the_host_in_a_credentials_invalid_reason(self):
        self.obs.error = SourceUnreadable(f"credentials invalid: {OBS_APP_VAR}")
        self.fetch()
        self.assertEqual(self.collection()["reason"], f"{OBS_HOST}: credentials invalid: {OBS_APP_VAR}")

    def test_an_adapter_error_exits_0(self):
        self.obs.error = ValueError(SENTINEL)
        self.assertEqual(self.fetch()[0], 0)

    def test_names_the_host_and_class_of_an_adapter_error(self):
        self.obs.error = ValueError(SENTINEL)
        self.fetch()
        self.assertEqual(self.collection()["reason"], f"{OBS_HOST}: adapter error: ValueError")

    def test_fails_a_tracked_monitor_with_the_pack_keys_when_the_source_is_unreadable(self):
        self.state["items"][TRACKED_KEY] = tracked_item()
        self.obs.error = SourceUnreadable("HTTP 503 GET /api/v1/monitor")
        self.fetch()
        entries = self.collection()["entries"]
        self.assertEqual(entries[TRACKED_KEY], entries[API_KEY])
        self.assertEqual(entries[TRACKED_KEY]["status"], "failed")

    def test_keeps_the_adapter_error_text_out_of_every_output(self):
        self.obs.error = ValueError(SENTINEL)
        _, out, err = self.fetch()
        self.assertNotIn(SENTINEL, out + err + self.written())

    def test_names_the_host_and_class_of_a_client_error(self):
        self.obs.client_error = KeyError(SENTINEL)
        self.fetch()
        self.assertEqual(self.collection()["reason"], f"{OBS_HOST}: adapter error: KeyError")

    def test_fails_the_selected_entries_on_an_adapter_error(self):
        self.obs.error = TypeError(SENTINEL)
        self.fetch()
        self.assertEqual(self.statuses(), {API_KEY: "failed", DB_KEY: "failed"})

    def test_writes_a_null_cursor_when_the_stored_one_breaks_the_schema(self):
        self.state["cursors"]["observability"]["events_ts_ms"] = STORED_TS_MS + 0.5
        self.obs.error = SourceUnreadable("HTTP 503 GET /api/v1/monitor")
        self.fetch()
        self.assertIsNone(self.collection()["cursor"])

    def test_exits_0(self):
        self.obs.error = SourceUnreadable("HTTP 503 GET /api/v1/monitor")
        self.assertEqual(self.fetch()[0], 0)

    def test_names_the_host_in_an_api_failure(self):
        self.obs.error = SourceUnreadable("HTTP 503 GET /api/v1/monitor")
        self.fetch()
        self.assertEqual(self.collection()["reason"], f"{OBS_HOST}: HTTP 503 GET /api/v1/monitor")

    def test_keeps_a_missing_credential_reason(self):
        self.obs.error = CredentialsMissing(f"credentials missing: {OBS_APP_VAR}")
        self.fetch()
        self.assertEqual(self.collection()["reason"], f"credentials missing: {OBS_APP_VAR}")

    def test_marks_a_partial_read_not_read(self):
        self.obs.error = PartialRead("page cap")
        self.fetch()
        self.assertEqual([self.collection()["read"], self.collection()["reason"]], [False, "partial: page cap"])

    def test_writes_empty_records_and_the_stored_cursor(self):
        self.obs.error = SourceUnreadable("HTTP 503 GET /api/v1/monitor")
        self.fetch()
        expected = [UNREAD_MONITORS, {"events_ts_ms": STORED_TS_MS, "monitors": {MONITOR_ID: "OK"}}]
        self.assertEqual([self.collection()["records"], self.collection()["cursor"]], expected)

    def test_fails_selected_entries_and_keeps_deferred_ones(self):
        self.state["run"]["daily_metrics_on"] = PARIS_DAY
        self.obs.error = SourceUnreadable("GET /api/v1/query: URLError")
        self.fetch(source="metrics")
        expected = {
            "api-p95": {"status": "failed", "reason": f"{OBS_HOST}: GET /api/v1/query: URLError"},
            "db-size": {"status": "deferred", "reason": "not due"},
        }
        self.assertEqual(self.collection()["entries"], expected)

    def test_names_the_host_of_a_base_url_with_a_path(self):
        self.doc.error = SourceUnreadable("HTTP 404 GET /pages")
        self.fetch(source="sources-page", place="local")
        self.assertEqual(self.collection()["reason"], f"{DOC_HOST}: HTTP 404 GET /pages")



def digest(page):
    return planned_call("sources-page", page)["digest"]


class RelayTestCase(CollectTestCase):
    def relay(self, command, out, source, place):
        config = self.write("config.json", self.config)
        window = self.write("window.json", self.window)
        stored = self.write("state.json", self.state)
        return self.run_main(
            command, "--config", config, "--routine", ROUTINE, "--source", source, "--place", place,
            "--window", window, "--state", stored, "--responses", self.path(RESPONSES), "--out", out,
        )

    def plan(self, source="sources-page", place="cloud"):
        return self.relay("plan", self.path("plan.json"), source, place)

    def parse(self, source="sources-page", place="cloud"):
        return self.relay("parse", self.path("collection.json"), source, place)

    def parse_in_subprocess(self):
        argv = [
            "parse", "--config", self.path("config.json"), "--routine", ROUTINE, "--source", "sources-page", "--place", "cloud",
            "--window", self.path("window.json"), "--state", self.path("state.json"), "--responses", self.path(RESPONSES),
            "--out", self.path("collection.json"),
        ]
        subprocess.run([sys.executable, "-c", FAKE_ADAPTERS_MAIN, HERE, *argv], capture_output=True, timeout=10, check=True)

    def response_path(self, call_id):
        return os.path.join(self.path(RESPONSES), call_id + ".txt")

    def respond(self, call_id, text="{}"):
        self.respond_bytes(call_id, text.encode("utf-8"))

    def respond_bytes(self, call_id, data):
        os.makedirs(self.path(RESPONSES), exist_ok=True)
        with open(self.response_path(call_id), "wb") as handle:
            handle.write(data)

    def write_calls(self, text):
        with open(os.path.join(self.path(RESPONSES), "calls.json"), "w", encoding="utf-8") as handle:
            handle.write(text)

    def loop(self, source="sources-page", place="cloud"):
        self.plan(source, place)
        self.respond(f"{source}-1")
        self.plan(source, place)
        self.respond(f"{source}-2")
        return self.plan(source, place)

    def fill(self, pages):
        for page in range(1, pages + 1):
            self.plan()
            self.respond(f"sources-page-{page}")
        return self.plan()

    def plan_doc(self):
        with open(self.path("plan.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def calls_doc(self):
        with open(os.path.join(self.path(RESPONSES), "calls.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def call_ids(self):
        return [call["id"] for call in self.plan_doc()["calls"]]


class PlanLoopTest(RelayTestCase):
    def test_exits_0(self):
        self.assertEqual(self.plan()[0], 0)

    def test_creates_the_responses_directory(self):
        self.plan()
        self.assertTrue(os.path.isdir(self.path(RESPONSES)))

    def test_lists_the_first_call(self):
        self.plan()
        expected = {
            "done": False,
            "partial": None,
            "calls": [{"id": "sources-page-1", "connector": "docs-cloud", "tool": "read-page", "arguments": {"page": 1}}],
        }
        self.assertEqual(self.plan_doc(), expected)

    def test_writes_canonical_json(self):
        self.plan()
        with open(self.path("plan.json"), "rb") as handle:
            raw = handle.read()
        self.assertEqual(raw, state.dump(json.loads(raw)))

    def test_lists_the_next_page_after_a_saved_response(self):
        self.plan()
        self.respond("sources-page-1")
        self.plan()
        self.assertEqual(self.call_ids(), ["sources-page-2"])

    def test_ends_when_the_adapter_is_done(self):
        self.loop()
        self.assertEqual(self.plan_doc(), {"done": True, "partial": None, "calls": []})

    def test_records_the_digest_of_every_listed_call_across_steps(self):
        self.loop()
        expected = {"calls": {"sources-page-1": digest(1), "sources-page-2": digest(2)}, "done": True, "partial": None}
        self.assertEqual(self.calls_doc(), expected)

    def test_records_a_step_that_is_not_done(self):
        self.plan()
        self.assertEqual(self.calls_doc(), {"calls": {"sources-page-1": digest(1)}, "done": False, "partial": None})

    def test_ignores_a_text_file_outside_the_id_pattern(self):
        self.plan()
        self.respond("notes")
        self.respond("sources-page-1")
        self.plan()
        self.assertEqual(self.doc.plans[1]["responses"], {"sources-page-1": "{}"})

    def test_passes_the_provider_config_to_the_adapter(self):
        self.plan()
        self.assertEqual(self.doc.plans[0]["source"]["provider_config"], self.config["providers"]["docs"])

    def test_passes_the_saved_responses_unchanged_to_the_adapter(self):
        text = '{"note": "café"}\r\n'
        self.plan()
        self.respond("sources-page-1", text)
        self.plan()
        self.assertEqual(self.doc.plans[1]["responses"], {"sources-page-1": text})

    def test_passes_the_place_connector_to_the_adapter(self):
        self.plan(source="metrics", place="local")
        self.assertEqual(self.obs.plans[0]["connector"], "obs-local")

    def test_names_the_place_connector_in_each_call(self):
        self.plan(source="metrics", place="local")
        self.assertEqual(self.plan_doc()["calls"][0]["connector"], "obs-local")

    def test_passes_the_stored_cursor_and_selected_entries(self):
        self.state["run"]["daily_metrics_on"] = PARIS_DAY
        self.plan(source="metrics", place="local")
        plan = self.obs.plans[0]
        self.assertEqual([plan["cursor"], [item["key"] for item in plan["entries"]]], [{"metrics": {"api-p95": 380.0}}, ["api-p95"]])


class RelistTest(RelayTestCase):
    def test_drops_a_call_whose_response_is_saved(self):
        self.doc.plan_result = {"done": False, "partial": None, "calls": [planned_call("sources-page", 1), planned_call("sources-page", 2)]}
        self.respond("sources-page-1")
        self.plan()
        self.assertEqual(self.call_ids(), ["sources-page-2"])

    def test_ends_partial_when_every_listed_call_has_a_response(self):
        self.doc.plan_result = {"done": False, "partial": None, "calls": [planned_call("sources-page", 1)]}
        self.respond("sources-page-1")
        self.plan()
        self.assertEqual(self.plan_doc(), {"done": True, "partial": "no new call", "calls": []})


class CallCapTest(RelayTestCase):
    def test_ends_with_a_call_cap_partial(self):
        self.doc.pages = collect.CALL_CAP + 1
        self.fill(collect.CALL_CAP)
        self.assertEqual(self.plan_doc(), {"done": True, "partial": "call cap", "calls": []})

    def test_records_the_call_cap_partial(self):
        self.doc.pages = collect.CALL_CAP + 1
        self.fill(collect.CALL_CAP)
        self.assertEqual(self.calls_doc()["partial"], "call cap")

    def test_parse_marks_the_source_partial(self):
        self.doc.pages = collect.CALL_CAP + 1
        self.fill(collect.CALL_CAP)
        self.parse()
        self.assertEqual([self.collection()["read"], self.collection()["reason"]], [False, "partial: call cap"])

    def test_ends_without_partial_when_the_adapter_is_done_at_the_cap(self):
        self.doc.pages = collect.CALL_CAP
        self.fill(collect.CALL_CAP)
        self.assertEqual(self.plan_doc(), {"done": True, "partial": None, "calls": []})

    def test_keeps_listing_calls_past_the_page_cap_of_one_query(self):
        self.doc.pages = PAGE_CAP + 1
        self.fill(PAGE_CAP)
        self.assertEqual(self.call_ids(), [f"sources-page-{PAGE_CAP + 1}"])


class AdapterPageCapTest(RelayTestCase):
    def setUp(self):
        super().setUp()
        self.plan()
        self.respond("sources-page-1")
        self.doc.plan_result = {"done": True, "partial": "page cap", "calls": []}
        self.plan()

    def test_ends_the_loop_with_the_adapter_page_cap(self):
        self.assertEqual(self.plan_doc(), {"done": True, "partial": "page cap", "calls": []})

    def test_parse_marks_the_source_partial(self):
        self.parse()
        self.assertEqual([self.collection()["read"], self.collection()["reason"]], [False, "partial: page cap"])


class CursorRepeatedTest(RelayTestCase):
    def setUp(self):
        super().setUp()
        self.plan()
        self.respond("sources-page-1")
        self.doc.plan_result = {"done": True, "partial": "cursor repeated", "calls": []}
        self.plan()

    def test_ends_the_loop_with_the_adapter_partial(self):
        self.assertEqual(self.plan_doc(), {"done": True, "partial": "cursor repeated", "calls": []})

    def test_parse_marks_the_source_partial(self):
        self.parse()
        self.assertEqual([self.collection()["read"], self.collection()["reason"]], [False, "partial: cursor repeated"])


class PlanFailureTest(RelayTestCase):
    def test_ends_the_loop_on_an_adapter_error(self):
        self.doc.plan_error = ValueError(SENTINEL)
        self.plan()
        self.assertEqual(self.plan_doc(), {"done": True, "partial": "adapter error: ValueError", "calls": []})

    def test_keeps_the_adapter_error_text_out_of_every_output(self):
        self.doc.plan_error = ValueError(SENTINEL)
        _, out, err = self.plan()
        with open(self.path("plan.json"), encoding="utf-8") as handle:
            written = handle.read()
        self.assertNotIn(SENTINEL, out + err + written)

    def test_parse_marks_the_source_partial_after_an_adapter_error(self):
        self.doc.plan_error = ValueError(SENTINEL)
        self.plan()
        self.parse()
        self.assertEqual(self.collection()["reason"], "partial: adapter error: ValueError")

    def test_ends_the_loop_on_a_call_id_outside_the_source(self):
        escape = {**planned_call("sources-page", 1), "id": os.path.join("..", "escape")}
        self.doc.plan_result = {"done": False, "partial": None, "calls": [escape]}
        self.plan()
        self.assertTrue(self.plan_doc()["partial"].startswith("adapter output invalid: plan.calls[0].id"))

    def test_ends_the_loop_on_a_malformed_plan(self):
        self.doc.plan_result = {"done": "no", "partial": None, "calls": []}
        self.plan()
        self.assertTrue(self.plan_doc()["partial"].startswith("adapter output invalid: "))

    def test_keeps_the_text_of_a_source_unreadable_error(self):
        self.doc.plan_error = SourceUnreadable("unreadable response sources-page-1 of tool read-page")
        self.plan()
        self.assertEqual(self.plan_doc()["partial"], "docs-cloud: unreadable response sources-page-1 of tool read-page")

    def test_rejects_a_done_step_that_lists_calls(self):
        self.doc.plan_result = {"done": True, "partial": None, "calls": [planned_call("sources-page", 1)]}
        self.plan()
        self.assertTrue(self.plan_doc()["partial"].startswith("adapter output invalid: plan.calls: "))

    def test_rejects_a_step_not_done_with_a_partial(self):
        self.doc.plan_result = {"done": False, "partial": "page cap", "calls": [planned_call("sources-page", 1)]}
        self.plan()
        self.assertTrue(self.plan_doc()["partial"].startswith("adapter output invalid: plan.partial: "))

    def test_rejects_a_duplicate_call_id(self):
        self.doc.plan_result = {"done": False, "partial": None, "calls": [planned_call("sources-page", 1), planned_call("sources-page", 1)]}
        self.plan()
        self.assertTrue(self.plan_doc()["partial"].startswith("adapter output invalid: plan.calls[1].id: "))


class ParseReadTest(RelayTestCase):
    def setUp(self):
        super().setUp()
        self.loop()

    def test_exits_0(self):
        self.assertEqual(self.parse()[0], 0)

    def test_writes_the_collection(self):
        self.parse()
        records, cursor = RESULTS["document_store"]
        expected = {
            "schema": 1,
            "source": "sources-page",
            "role": "document_store",
            "provider": "docs",
            "transport": "mcp",
            "place": "cloud",
            "window": {"from_ts": WINDOW_END - 3600, "to_ts": WINDOW_END},
            "read": True,
            "reason": None,
            "cursor": cursor,
            "records": records,
            "entries": {},
        }
        self.assertEqual(self.collection(), expected)

    def test_passes_the_saved_responses_to_the_adapter(self):
        self.parse()
        self.assertEqual(self.doc.parses[0]["responses"], {"sources-page-1": "{}", "sources-page-2": "{}"})

    def test_passes_the_provider_config_to_the_adapter(self):
        self.parse()
        self.assertEqual(self.doc.parses[0]["source"]["provider_config"], self.config["providers"]["docs"])

    def test_passes_the_recorded_digests_to_the_adapter(self):
        self.parse()
        self.assertEqual(self.doc.parses[0]["digests"], {"sources-page-1": digest(1), "sources-page-2": digest(2)})

    def test_names_the_call_id_of_a_digest_mismatch(self):
        self.doc.error = SourceUnreadable("digest mismatch sources-page-2")
        self.parse()
        self.assertEqual([self.collection()["read"], self.collection()["reason"]], [False, "docs-cloud: digest mismatch sources-page-2"])

    def test_names_only_the_class_of_an_adapter_error(self):
        self.doc.error = ValueError(SENTINEL)
        self.parse()
        self.assertEqual(self.collection()["reason"], "docs-cloud: adapter error: ValueError")

    def test_keeps_the_adapter_error_text_out_of_every_output(self):
        self.doc.error = ValueError(SENTINEL)
        _, out, err = self.parse()
        self.assertNotIn(SENTINEL, out + err + self.written())

    def test_marks_an_invalid_adapter_output_not_read(self):
        self.doc.result = {"records": {"pages": [{"id": 7}]}, "cursor": RESULTS["document_store"][1], "entries": {}}
        self.parse()
        self.assertTrue(self.collection()["reason"].startswith("adapter output invalid: records.pages[0]"))


class ParseEntriesTest(RelayTestCase):
    def test_fails_a_selected_entry_the_adapter_did_not_report(self):
        records, cursor = RESULTS["metrics"]
        self.obs.result = {"records": records, "cursor": cursor, "entries": {"api-p95": OK}}
        self.loop(source="metrics", place="local")
        self.parse(source="metrics", place="local")
        self.assertEqual(self.collection()["entries"]["db-size"], {"status": "failed", "reason": "not reported by the adapter"})

    def test_keeps_a_deferred_entry(self):
        self.state["run"]["daily_metrics_on"] = PARIS_DAY
        self.loop(source="metrics", place="local")
        self.parse(source="metrics", place="local")
        self.assertEqual(self.collection()["entries"]["db-size"], {"status": "deferred", "reason": "not due"})

    def test_writes_the_stored_cursor_when_not_read(self):
        self.obs.error = SourceUnreadable("unreadable response metrics-1 of tool run-code")
        self.loop(source="metrics", place="local")
        self.parse(source="metrics", place="local")
        self.assertEqual(self.collection()["cursor"], {"metrics": {"api-p95": 380.0}})


class RelayGapTest(RelayTestCase):
    def outcome(self):
        return [self.collection()["read"], self.collection()["reason"]]

    def test_marks_a_plan_not_done_not_read(self):
        self.plan()
        self.respond("sources-page-1")
        self.parse()
        self.assertEqual(self.outcome(), [False, "plan not done"])

    def test_names_the_connector_when_no_response_is_saved(self):
        self.plan()
        self.parse()
        self.assertEqual(self.outcome(), [False, "docs-cloud: no response saved (connector missing or relay not run)"])

    def test_counts_only_responses_of_the_source_as_saved(self):
        self.plan()
        self.respond("notes")
        self.parse()
        self.assertEqual(self.outcome(), [False, "docs-cloud: no response saved (connector missing or relay not run)"])

    def test_marks_a_missing_response_not_read(self):
        self.loop()
        os.unlink(self.response_path("sources-page-2"))
        self.parse()
        self.assertEqual(self.outcome(), [False, "missing response sources-page-2"])

    def test_marks_an_unplanned_response_not_read(self):
        self.loop()
        self.respond("sources-page-9")
        self.parse()
        self.assertEqual(self.outcome(), [False, "unplanned response sources-page-9"])

    def test_reports_a_text_file_outside_the_id_pattern_as_unplanned(self):
        self.loop()
        self.respond("notes")
        self.parse()
        self.assertEqual(self.outcome(), [False, "unplanned response notes"])

    def test_makes_no_adapter_parse_call_on_a_gap(self):
        self.plan()
        self.respond("sources-page-1")
        self.parse()
        self.assertEqual(self.doc.parses, [])

    def test_exits_2_without_a_recorded_plan(self):
        self.respond("sources-page-1")
        self.assertEqual(self.parse()[0], 2)

    def test_exits_2_on_a_calls_file_that_is_not_json(self):
        self.loop()
        self.write_calls("{")
        self.assertEqual(self.parse()[0], 2)

    def test_exits_3_on_a_calls_file_of_the_wrong_shape(self):
        self.loop()
        self.write_calls('{"calls": [], "done": true, "partial": null}')
        self.assertEqual(self.parse()[0], 3)


class UnreadableResponseTest(RelayTestCase):
    def reason(self):
        return self.collection()["reason"]

    def plan_partial(self):
        return [self.plan_doc()["done"], self.plan_doc()["partial"], self.plan_doc()["calls"]]

    def test_parse_exits_0_on_a_response_that_is_not_utf8(self):
        self.loop()
        self.respond_bytes("sources-page-2", b"\xff\xfe")
        self.assertEqual(self.parse()[0], 0)

    def test_parse_marks_a_response_that_is_not_utf8_not_read(self):
        self.loop()
        self.respond_bytes("sources-page-2", b"\xff\xfe")
        self.parse()
        self.assertEqual(self.reason(), "docs-cloud: response sources-page-2 is not UTF-8 text")

    def test_plan_ends_the_loop_on_a_response_that_is_not_utf8(self):
        self.plan()
        self.respond_bytes("sources-page-1", b"\xff\xfe")
        self.plan()
        self.assertEqual(self.plan_partial(), [True, "docs-cloud: response sources-page-1 is not UTF-8 text", []])

    def test_parse_marks_a_response_over_the_size_cap_partial(self):
        self.loop()
        self.respond("sources-page-2", "0123456789")
        with mock.patch.object(collect, "BODY_CAP", 4):
            self.parse()
        self.assertEqual(self.reason(), "partial: response over 10 MB sources-page-2")

    def test_plan_ends_the_loop_on_a_response_over_the_size_cap(self):
        self.plan()
        self.respond("sources-page-1", "0123456789")
        with mock.patch.object(collect, "BODY_CAP", 4):
            self.plan()
        self.assertEqual(self.plan_partial(), [True, "partial: response over 10 MB sources-page-1", []])

    def test_parse_marks_a_symlinked_response_not_read(self):
        self.loop()
        os.unlink(self.response_path("sources-page-2"))
        os.symlink(self.write("target.txt", {}), self.response_path("sources-page-2"))
        self.parse()
        self.assertEqual(self.reason(), "docs-cloud: response sources-page-2 is not a regular file")

    def test_parse_marks_a_fifo_response_not_read(self):
        self.loop()
        os.unlink(self.response_path("sources-page-2"))
        os.mkfifo(self.response_path("sources-page-2"))
        self.parse_in_subprocess()
        self.assertEqual(self.reason(), "docs-cloud: response sources-page-2 is not a regular file")

    def test_plan_ends_the_loop_on_a_symlinked_response(self):
        self.plan()
        os.symlink(self.write("target.txt", {}), self.response_path("sources-page-1"))
        self.plan()
        self.assertEqual(self.plan_partial(), [True, "docs-cloud: response sources-page-1 is not a regular file", []])

    @unittest.skipIf(os.geteuid() == 0, "root reads a file without read permission")
    def test_parse_exits_2_on_a_response_it_cannot_open(self):
        self.loop()
        os.chmod(self.response_path("sources-page-2"), 0)
        self.assertEqual(self.parse()[0], 2)

    def test_plan_exits_2_when_the_responses_path_is_a_file(self):
        self.write(RESPONSES, {})
        self.assertEqual(self.plan()[0], 2)


class RelayApiSourceTest(RelayTestCase):
    def test_plan_on_an_api_source_exits_2(self):
        self.assertEqual(self.plan(source="monitors")[0], 2)

    def test_plan_on_an_api_source_names_the_source_place_and_transport(self):
        self.assertIn("source monitors uses the api transport at place cloud", self.plan(source="monitors")[2])

    def test_plan_on_an_api_source_makes_no_adapter_call(self):
        self.plan(source="monitors")
        self.assertEqual(self.obs.plans, [])

    def test_plan_on_an_api_source_writes_no_plan(self):
        self.plan(source="monitors")
        self.assertFalse(os.path.exists(self.path("plan.json")))

    def test_parse_on_an_api_source_exits_2(self):
        self.assertEqual(self.parse(source="monitors")[0], 2)


class RelayConfigCheckTest(RelayTestCase):
    def test_plan_exits_2_on_an_invalid_config(self):
        self.config["routines"][ROUTINE]["sources"]["sources-page"]["provider"] = "absent"
        self.assertEqual(self.plan()[0], 2)

    def test_plan_exits_3_on_an_invalid_query_pack(self):
        del self.config["routines"][ROUTINE]["query_pack"][0]["rule"]
        self.assertEqual(self.plan()[0], 3)

    def test_plan_makes_no_adapter_call_on_an_invalid_query_pack(self):
        del self.config["routines"][ROUTINE]["query_pack"][0]["rule"]
        self.plan()
        self.assertEqual(self.doc.plans, [])

    def test_parse_exits_3_on_an_invalid_query_pack(self):
        del self.config["routines"][ROUTINE]["query_pack"][0]["rule"]
        self.assertEqual(self.parse()[0], 3)


class ReasonTextTest(RelayTestCase):
    def test_turns_each_control_character_of_a_reason_into_a_space(self):
        self.obs.error = SourceUnreadable("first\nsecond\tthird\x00end")
        self.fetch()
        self.assertEqual(self.collection()["reason"], f"{OBS_HOST}: first second third end")

    def test_collapses_a_run_of_spaces_in_a_reason(self):
        self.obs.error = SourceUnreadable("first \r\n  second")
        self.fetch()
        self.assertEqual(self.collection()["reason"], f"{OBS_HOST}: first second")

    def test_caps_a_reason_at_200_characters(self):
        self.obs.error = SourceUnreadable("x" * 500)
        self.fetch()
        self.assertEqual(self.collection()["reason"], (f"{OBS_HOST}: " + "x" * 500)[:200])

    def test_cleans_the_reason_of_a_failed_entry(self):
        self.adapter_result({API_KEY: {"status": "failed", "reason": "no\ndata"}, DB_KEY: OK})
        self.fetch()
        self.assertEqual(self.collection()["entries"][API_KEY]["reason"], "no data")

    def test_cleans_the_reason_of_a_parsed_collection(self):
        self.loop()
        self.doc.error = SourceUnreadable("bad\nresponse")
        self.parse()
        self.assertEqual(self.collection()["reason"], "docs-cloud: bad response")

    def test_cleans_the_partial_of_a_plan_step(self):
        self.doc.plan_error = SourceUnreadable("bad\nresponse")
        self.plan()
        self.assertEqual(self.plan_doc()["partial"], "docs-cloud: bad response")

    def test_turns_a_line_separator_and_a_bidirectional_override_of_a_reason_into_spaces(self):
        self.obs.error = SourceUnreadable("first\u2028second\u202ethird\u200bend")
        self.fetch()
        self.assertEqual(self.collection()["reason"], f"{OBS_HOST}: first second third end")

    def test_names_the_config_key_of_a_client_config_error(self):
        self.obs.client_error = SourceUnreadable("api.credentials: must name api_key and app_key; missing app_key")
        self.fetch()
        self.assertEqual(self.collection()["reason"], f"{OBS_HOST}: api.credentials: must name api_key and app_key; missing app_key")


class LoneSurrogateTest(RelayTestCase):
    def monitors_with_a_lone_surrogate(self):
        records, cursor = RESULTS["monitors"]
        named = dict(records["monitors"][0], name="API \ud800 errors")
        reason = "bad \udfff reason"
        self.obs.result = {
            "records": dict(records, monitors=[named]),
            "cursor": cursor,
            "entries": {API_KEY: {"status": "failed", "reason": reason}, DB_KEY: OK},
        }

    def test_fetch_exits_0_and_replaces_a_lone_surrogate_of_a_record_with_a_replacement_character(self):
        self.monitors_with_a_lone_surrogate()
        code = self.fetch()[0]
        self.assertEqual((code, self.collection()["records"]["monitors"][0]["name"]), (0, "API \ufffd errors"))

    def test_fetch_replaces_a_lone_surrogate_of_an_entry_reason(self):
        self.monitors_with_a_lone_surrogate()
        self.fetch()
        self.assertEqual(self.collection()["entries"][API_KEY]["reason"], "bad \ufffd reason")

    def test_fetch_replaces_a_lone_surrogate_of_a_mapping_key(self):
        self.monitors_with_a_lone_surrogate()
        self.obs.result["cursor"] = {"events_ts_ms": EVENT_TS_MS, "monitors": {"4\ud800": "Alert"}}
        self.fetch()
        self.assertEqual(self.collection()["cursor"]["monitors"], {"4\ufffd": "Alert"})

    def test_fetch_replaces_a_lone_surrogate_of_a_source_not_read_reason(self):
        self.obs.error = SourceUnreadable("no \ud800 access")
        self.fetch()
        self.assertEqual(self.collection()["reason"], f"{OBS_HOST}: no \ufffd access")

    def test_fetch_keeps_a_valid_surrogate_pair_as_one_character(self):
        self.monitors_with_a_lone_surrogate()
        self.obs.result["records"]["monitors"][0]["name"] = "API \U0001f680"
        self.fetch()
        self.assertEqual(self.collection()["records"]["monitors"][0]["name"], "API \U0001f680")

    def test_parse_exits_0_and_replaces_a_lone_surrogate_of_a_record(self):
        self.loop()
        records, cursor = RESULTS["document_store"]
        page = dict(records["pages"][0], title="Sources \ud800")
        self.doc.result = {"records": {"pages": [page]}, "cursor": cursor, "entries": {}}
        code = self.parse()[0]
        self.assertEqual((code, self.collection()["records"]["pages"][0]["title"]), (0, "Sources \ufffd"))


if __name__ == "__main__":
    unittest.main()
