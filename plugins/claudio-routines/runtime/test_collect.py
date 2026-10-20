import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import collect
import providers
import relay_capture
import roles
import state
import store
from support import RELAY_START_NS, isolate_relay, publication_values
from providers._http import PAGE_CAP, PartialRead, SourceUnreadable
from providers import _common
from providers._errors import CredentialsMissing
from providers.test_http import PATH as HTTP_PATH
from providers.test_http import SECRET as HTTP_SECRET
from providers.test_http import FakeOpener, FakeResponse, http_error, make_client
from test_recap_features import OWNER as RECAP_OWNER
from test_recap_features import make_routine as make_recap_routine
from test_recap_state import CHANNEL_A as RECAP_CHANNEL_A
from test_recap_state import CHANNEL_B as RECAP_CHANNEL_B
from test_recap_state import LAST_TS as RECAP_LAST_TS
from test_recap_state import ROOT_TS as RECAP_ROOT_TS
from test_recap_state import make_state as make_recap_state
from test_recap_state import make_unit as make_recap_unit
from tribe_support import make_state as make_tribe_state
from tribe_support import make_warning

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
CREDENTIALS = {OBS_KEY_VAR: "set", OBS_APP_VAR: "set", DOC_TOKEN_VAR: "set"}
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
CLIENT = types.SimpleNamespace(recorder=None)
SENTINEL = "-".join(["sentinel", "response", "text"])
OK = {"status": "ok", "reason": None}
RUN = "run"
RESPONSES = "run/raw/document_store/sources-page"
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


UNREAD_MONITORS = {"monitors": [], "transitions": [], "discovered": [], "discovery": None}
RESULTS = {
    "monitors": (
        {
            "monitors": [{"id": MONITOR_ID, "name": "API errors", "state": "Alert", "priority": None, "link": "https://app.example.test/m"}],
            "transitions": [{"monitor": MONITOR_ID, "count": 1, "first_ts_ms": EVENT_TS_MS, "last_ts_ms": EVENT_TS_MS}],
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
        {
            "pages": [
                {
                    "id": page_id(),
                    "title": "Sources",
                    "last_edited": UTC_EDIT,
                    "link": "https://docs.example.test/" + page_id().replace("-", ""),
                    "blocks": [{"type": "heading", "text": "Mutes", "rows": None, "checked": None}],
                }
            ]
        },
        {"pages": {page_id(): UTC_EDIT}},
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
    module.STATIC_HEADERS = {}

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
        self.relay_dir, self.relay_clock = isolate_relay(self)
        self.obs = fake_adapter("fakeobs", "observability")
        self.doc = fake_adapter("fakedoc", "document_store")
        self.modules = mock.patch.dict(sys.modules, {"providers.fakeobs": self.obs, "providers.fakedoc": self.doc})
        self.modules.start()
        self.environment = mock.patch.dict(os.environ, CREDENTIALS, clear=True)
        self.environment.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.config = make_config()
        self.state = make_state()
        self.window = make_window()

    def tearDown(self):
        self.environment.stop()
        self.modules.stop()
        self.tmp.cleanup()

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def write(self, name, document):
        os.makedirs(os.path.dirname(self.path(name)), exist_ok=True)
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

    def raw_path(self, source):
        provider = self.config["routines"][ROUTINE]["sources"][source]["provider"]
        role = providers.load(self.config["providers"][provider]["adapter"]).ROLE
        return self.path(os.path.join(RUN, "raw", role, source))

    def fetch(self, source="monitors", place="cloud", out=None):
        config = self.write("config.json", self.config)
        window = self.write("window.json", self.window)
        stored = self.write("state.json", self.state)
        return self.run_main(
            "fetch", "--config", config, "--routine", ROUTINE, "--source", source, "--place", place,
            "--window", window, "--state", stored, "--out", out or self.path("collection.json"), "--run", self.path(RUN),
        )

    def collection(self):
        with open(self.path("collection.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def written(self):
        with open(self.path("collection.json"), encoding="utf-8") as handle:
            return handle.read()

    def added_to_window(self, first_read_from_ts=None):
        return {"first_read_from_ts": self.window["from_ts"] if first_read_from_ts is None else first_read_from_ts, "timezone": "Europe/Paris"}

    def adapter_keys(self, adapter):
        return [item["key"] for item in adapter.calls[0]["entries"]]

    def statuses(self):
        return {key: value["status"] for key, value in self.collection()["entries"].items()}

    def adapter_result(self, entries):
        records, cursor = RESULTS["monitors"]
        self.obs.result = {"records": records, "cursor": cursor, "entries": entries}

    def invalid_result(self):
        self.obs.result = {"records": {"monitors": [{"id": 7}], "transitions": []}, "cursor": RESULTS["monitors"][1], "entries": {}}


class ParserTest(unittest.TestCase):
    COMMON = ["--config", "c", "--routine", ROUTINE, "--place", "cloud"]

    def parse(self, *argv):
        return collect.build_parser().parse_args(list(argv))

    def test_parses_the_six_commands(self):
        fetch = ["--source", "s", "--window", "w", "--state", "s", "--out", "o", "--run", "r"]
        relay = fetch
        replay = ["--window", "w", "--state", "s", "--run", "r", "--out", "o"]
        parsed = [
            self.parse("sources", *self.COMMON).command,
            self.parse("check-env", *self.COMMON).command,
            self.parse("fetch", *self.COMMON, *fetch).command,
            self.parse("plan", *self.COMMON, *relay).command,
            self.parse("parse", *self.COMMON, *relay).command,
            self.parse("replay", *self.COMMON, *replay).command,
        ]
        self.assertEqual(parsed, ["sources", "check-env", "fetch", "plan", "parse", "replay"])

    def test_rejects_a_command_outside_the_six(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            self.parse("relay", *self.COMMON)
        self.assertEqual(raised.exception.code, 2)

    def test_plan_requires_the_run_folder(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            self.parse("plan", *self.COMMON, "--source", "s", "--window", "w", "--state", "s", "--out", "o")
        self.assertEqual(raised.exception.code, 2)

    def test_fetch_requires_the_run_folder(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            self.parse("fetch", *self.COMMON, "--source", "s", "--window", "w", "--state", "s", "--out", "o")
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

    def test_empty_sources_exit_2_naming_the_key_path(self):
        self.config["routines"][ROUTINE]["sources"] = {}
        code, _, err = self.run_command("sources")
        self.assertEqual((code, f"routines.{ROUTINE}.sources: " in err), (2, True))

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
            {"provider": "obs", "role": "observability", "source": "metrics", "transport": "mcp", "skipped": []},
            {"provider": "obs", "role": "observability", "source": "monitors", "transport": "api", "skipped": []},
            {"provider": "docs", "role": "document_store", "source": "sources-page", "transport": "api", "skipped": []},
        ]
        self.assertEqual(self.run_command("sources", place="local")[1], state.dump(expected).decode("utf-8"))

    def test_exits_0(self):
        self.assertEqual(self.run_command("sources")[0], 0)


class SourcesStoreDirTest(CollectTestCase):
    def sources_with(self, store_dir, place="local"):
        self.config["places"][place]["store_dir"] = store_dir
        return self.run_command("sources", place=place)

    def test_accepts_a_store_dir_outside_every_repository(self):
        self.assertEqual(self.sources_with(self.path("store"))[0], 0)

    def test_refuses_a_store_dir_inside_a_git_working_tree(self):
        subprocess.run(["git", "init", "--quiet", self.path("repository")], check=True)

        code, _, err = self.sources_with(self.path("repository/store"))

        self.assertEqual((code, "places.local.store_dir" in err), (2, True))

    def test_refuses_a_store_dir_that_is_a_link(self):
        os.mkdir(self.path("store"), 0o700)
        os.symlink(self.path("store"), self.path("linked"))

        code, _, err = self.sources_with(self.path("linked"))

        self.assertEqual((code, "places.local.store_dir" in err), (2, True))

    def test_refuses_a_store_dir_of_another_user(self):
        os.mkdir(self.path("store"), 0o700)

        with mock.patch.object(store.os, "getuid", return_value=os.getuid() + 1):
            code, _, err = self.sources_with(self.path("store"))

        self.assertEqual((code, "places.local.store_dir" in err), (2, True))

    def test_checks_only_the_store_dir_of_the_requested_place(self):
        os.symlink(self.tmp.name, self.path("linked"))
        self.config["places"]["cloud"]["store_dir"] = self.path("linked")

        self.assertEqual(self.run_command("sources", place="local")[0], 0)


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


class PreferenceCase(CollectTestCase):
    def setUp(self):
        super().setUp()
        sources = self.config["routines"][ROUTINE]["sources"]
        sources["monitors"]["transport"] = {"cloud": ["api", "mcp"], "local": ["api"]}
        sources["metrics"]["transport"] = {"cloud": ["mcp", "api"], "local": ["mcp"]}

    def sources(self, environ, place="cloud", out=None):
        config = self.write("config.json", self.config)
        extra = [] if out is None else ["--out", out]
        with mock.patch.dict(os.environ, environ, clear=True):
            return self.run_main("sources", "--config", config, "--routine", ROUTINE, "--place", place, *extra)

    def chosen(self, environ, source="monitors", place="cloud"):
        listed = json.loads(self.sources(environ, place)[1])
        return next(item for item in listed if item["source"] == source)

    def write_sources(self, entries):
        return self.write("sources.json", entries)

    def entry(self, transport, skipped=(), source="monitors"):
        return {"source": source, "role": "observability", "provider": "obs", "transport": transport, "skipped": list(skipped)}

    def command(self, command, *extra, source="monitors", place="cloud", environ=None, **flags):
        config = self.write("config.json", self.config)
        window = self.write("window.json", self.window)
        stored = self.write("state.json", self.state)
        argv = [
            command, "--config", config, "--routine", ROUTINE, "--source", source, "--place", place,
            "--window", window, "--state", stored, "--out", self.path("collection.json"),
        ]
        argv += ["--run", self.path(RUN)]
        with mock.patch.dict(os.environ, CREDENTIALS if environ is None else environ, clear=True):
            return self.run_main(*argv, *extra)


class TransportChoiceTest(PreferenceCase):
    def test_chooses_api_when_every_variable_holds_a_value(self):
        self.assertEqual(self.chosen(CREDENTIALS)["transport"], "api")

    def test_skips_nothing_when_api_is_chosen(self):
        self.assertEqual(self.chosen(CREDENTIALS)["skipped"], [])

    def test_chooses_the_next_transport_when_a_variable_is_unset(self):
        self.assertEqual(self.chosen({OBS_KEY_VAR: "set"})["transport"], "mcp")

    def test_chooses_the_next_transport_when_a_variable_is_empty(self):
        self.assertEqual(self.chosen({OBS_KEY_VAR: "set", OBS_APP_VAR: ""})["transport"], "mcp")

    def test_chooses_the_next_transport_when_a_variable_is_blank(self):
        self.assertEqual(self.chosen({OBS_KEY_VAR: "set", OBS_APP_VAR: " \t"})["transport"], "mcp")

    def test_names_the_missing_variables_of_a_skipped_transport_sorted(self):
        self.assertEqual(self.chosen({})["skipped"], [{"transport": "api", "missing": [OBS_KEY_VAR, OBS_APP_VAR]}])

    def test_keeps_the_listed_order_when_the_connector_comes_first(self):
        chosen = self.chosen(CREDENTIALS, source="metrics")
        self.assertEqual((chosen["transport"], chosen["skipped"]), ("mcp", []))

    def test_chooses_nothing_when_the_only_transport_is_unusable(self):
        self.assertEqual(self.chosen({OBS_KEY_VAR: "set"}, place="local")["transport"], None)

    def test_names_the_missing_variables_when_nothing_is_usable(self):
        self.assertEqual(self.chosen({OBS_KEY_VAR: "set"}, place="local")["skipped"], [{"transport": "api", "missing": [OBS_APP_VAR]}])

    def test_chooses_each_place_on_its_own(self):
        self.assertEqual((self.chosen({}, place="cloud")["transport"], self.chosen({}, place="local")["transport"]), ("mcp", None))

    def test_writes_the_choice_to_the_out_file(self):
        code, out, _ = self.sources({OBS_KEY_VAR: "set"}, out=self.path("run-sources.json"))
        with open(self.path("run-sources.json"), encoding="utf-8") as handle:
            self.assertEqual((code, handle.read()), (0, out))

    def test_writes_no_file_without_out(self):
        self.sources({})
        self.assertFalse(os.path.exists(self.path("run-sources.json")))

    def test_prints_the_role_provider_transport_and_skipped_of_each_source(self):
        self.assertEqual(
            self.chosen({OBS_KEY_VAR: "set"}),
            {"source": "monitors", "role": "observability", "provider": "obs", "transport": "mcp", "skipped": [{"transport": "api", "missing": [OBS_APP_VAR]}]},
        )


class CheckEnvPreferenceTest(PreferenceCase):
    def check_env(self, environ, place="cloud"):
        config = self.write("config.json", self.config)
        with mock.patch.dict(os.environ, environ, clear=True):
            return self.run_main("check-env", "--config", config, "--routine", ROUTINE, "--place", place)

    def test_prints_a_fallback_line_per_missing_variable_and_exits_0(self):
        expected = (
            "connector metrics obs-cloud\nconnector monitors obs-cloud\nconnector sources-page docs-cloud\n"
            f"fallback monitors api mcp {OBS_KEY_VAR}\nfallback monitors api mcp {OBS_APP_VAR}\n"
        )
        self.assertEqual(self.check_env({DOC_TOKEN_VAR: "set"}), (0, expected, ""))

    def test_prints_a_missing_line_only_for_a_source_with_no_usable_transport(self):
        code, out, _ = self.check_env({OBS_KEY_VAR: "set", DOC_TOKEN_VAR: "set"}, place="local")
        self.assertEqual((code, out), (1, f"connector metrics obs-local\nmissing monitors {OBS_APP_VAR}\n"))

    def test_prints_the_connector_of_the_chosen_fallback(self):
        self.assertIn("connector monitors obs-cloud\n", self.check_env({})[1])

    def test_prints_the_connector_of_a_listed_connector_that_comes_first(self):
        self.assertIn("connector metrics obs-cloud\n", self.check_env(CREDENTIALS)[1])

    def test_prints_nothing_for_a_source_whose_api_is_usable(self):
        self.assertNotIn("monitors", self.check_env(CREDENTIALS)[1])


class InjectedHostsTest(PreferenceCase):
    def setUp(self):
        super().setUp()
        self.config["places"]["cloud"]["injected_hosts"] = [OBS_HOST]

    def check_env(self, environ, place="cloud"):
        config = self.write("config.json", self.config)
        with mock.patch.dict(os.environ, environ, clear=True):
            return self.run_main("check-env", "--config", config, "--routine", ROUTINE, "--place", place)

    def test_a_listed_host_makes_api_usable_without_its_variables(self):
        chosen = self.chosen({})
        self.assertEqual((chosen["transport"], chosen["skipped"]), ("api", []))

    def test_an_unlisted_host_still_needs_its_variables(self):
        self.config["places"]["cloud"]["injected_hosts"] = [DOC_HOST]
        self.assertEqual(self.chosen({})["transport"], "mcp")

    def test_a_host_listed_for_another_place_still_needs_its_variables(self):
        self.assertEqual(self.chosen({OBS_KEY_VAR: "set"}, place="local")["transport"], None)

    def test_the_host_match_ignores_case(self):
        self.config["places"]["cloud"]["injected_hosts"] = [OBS_HOST.upper()]
        self.assertEqual(self.chosen({})["transport"], "api")

    def test_check_env_prints_an_injected_line_and_no_missing_line_and_exits_0(self):
        expected = f"connector metrics obs-cloud\nconnector sources-page docs-cloud\ninjected monitors {OBS_HOST}\n"
        self.assertEqual(self.check_env({DOC_TOKEN_VAR: "set"}), (0, expected, ""))

    def test_check_env_prints_injected_for_a_listed_host_whose_variables_are_set(self):
        self.assertIn(f"injected monitors {OBS_HOST}\n", self.check_env(CREDENTIALS)[1])

    def test_check_env_prints_no_injected_line_for_a_source_read_through_its_connector(self):
        self.assertNotIn("injected metrics", self.check_env(CREDENTIALS)[1])

    def test_check_env_still_prints_missing_for_an_unlisted_host(self):
        self.config["places"]["cloud"]["injected_hosts"] = [DOC_HOST]
        self.assertIn(f"fallback monitors api mcp {OBS_KEY_VAR}\n", self.check_env({})[1])

    def test_fetch_builds_the_client_in_injected_mode_without_its_variables(self):
        self.obs.STATIC_HEADERS = {"X-Api-Version": "1"}
        with mock.patch.object(_common, "injected_client", return_value=CLIENT) as injected:
            code = self.command("fetch", environ={})[0]
        self.assertEqual((code, self.obs.clients, self.obs.calls[0]["http"]), (0, [], CLIENT))
        self.assertEqual(injected.call_args.args, (self.config["providers"]["obs"], {"X-Api-Version": "1"}))

    def test_fetch_builds_the_client_from_the_provider_when_the_host_is_unlisted(self):
        self.config["places"]["cloud"]["injected_hosts"] = [DOC_HOST]
        self.command("fetch")
        self.assertEqual(self.obs.clients, [self.config["providers"]["obs"]])

    def test_replay_accepts_a_provider_without_credentials_in_injected_mode(self):
        provider = {"adapter": "jira", "api": {"base_url": "https://api.example.test", "credentials": {}}}
        client = collect.replaying_client(collect.providers.load("jira"), provider, "monitors", [], True)
        self.assertEqual(client.records, [])


class RelayPreferenceTest(PreferenceCase):
    def test_fetch_on_a_source_whose_choice_is_mcp_exits_2(self):
        self.assertEqual(self.command("fetch", environ={})[0], 2)

    def test_fetch_on_a_source_whose_choice_is_mcp_names_the_chosen_transport(self):
        self.assertIn("source monitors uses the mcp transport at place cloud", self.command("fetch", environ={})[2])

    def test_fetch_reads_a_source_whose_choice_is_api(self):
        self.assertEqual((self.command("fetch")[0], self.collection()["transport"]), (0, "api"))

    def test_plan_on_a_source_whose_choice_is_api_exits_2(self):
        self.assertEqual(self.command("plan")[0], 2)

    def test_the_sources_file_wins_over_an_environment_that_holds_every_variable(self):
        path = self.write_sources([self.entry("mcp", [{"transport": "api", "missing": [OBS_APP_VAR]}])])
        self.assertEqual(self.command("fetch", "--sources", path)[0], 2)

    def test_the_sources_file_wins_over_an_environment_that_misses_a_variable(self):
        path = self.write_sources([self.entry("api")])
        self.assertEqual((self.command("fetch", "--sources", path, environ={})[0], self.collection()["transport"]), (0, "api"))

    def test_a_null_choice_in_the_sources_file_still_fetches_the_lone_api_transport(self):
        path = self.write_sources([self.entry(None, [{"transport": "api", "missing": [OBS_APP_VAR]}])])
        self.assertEqual((self.command("fetch", "--sources", path, place="local", environ={})[0], self.collection()["transport"]), (0, "api"))

    def test_a_null_choice_makes_plan_exit_2(self):
        path = self.write_sources([self.entry(None, [{"transport": "api", "missing": [OBS_APP_VAR]}])])
        self.assertEqual(self.command("plan", "--sources", path, place="local")[0], 2)

    def test_a_sources_file_choosing_a_transport_the_source_does_not_list_exits_2(self):
        path = self.write_sources([self.entry("mcp")])
        code, _, err = self.command("plan", "--sources", path, place="local")
        self.assertEqual((code, "lists api" in err), (2, True))

    def test_a_source_the_sources_file_does_not_list_exits_2(self):
        path = self.write_sources([self.entry("api", source="other")])
        code, _, err = self.command("fetch", "--sources", path)
        self.assertEqual((code, "monitors" in err), (2, True))

    def test_a_sources_file_that_is_not_a_list_is_rejected(self):
        path = self.write_sources({"monitors": "api"})
        self.assertEqual(self.command("fetch", "--sources", path)[0], 3)

    def test_the_collection_holds_an_empty_skipped_list_for_the_chosen_first_transport(self):
        self.command("fetch")
        self.assertEqual(self.collection()["skipped"], [])

    def test_the_collection_of_a_null_choice_holds_the_skipped_transport(self):
        skipped = [{"transport": "api", "missing": [OBS_APP_VAR]}]
        self.command("fetch", "--sources", self.write_sources([self.entry(None, skipped)]), place="local", environ={})
        self.assertEqual(self.collection()["skipped"], skipped)


class RoutineFileCase(CollectTestCase):
    def setUp(self):
        super().setUp()
        self.routine = self.config["routines"].pop(ROUTINE)
        self.config["providers"]["obs"]["transport"] = {"cloud": "api", "local": "api"}
        self.config["providers"]["docs"]["transport"] = {"cloud": "mcp", "local": "api"}
        sources = self.routine["sources"]
        del sources["monitors"]["transport"]
        sources["metrics"]["transport"] = {"local": "mcp"}
        del sources["sources-page"]["transport"]

    def write_routine_file(self, slug, text):
        os.makedirs(self.path("config/routines"), exist_ok=True)
        with open(self.path(f"config/routines/{slug}.json"), "w", encoding="utf-8") as handle:
            handle.write(text)

    def run_main(self, *argv):
        self.write_routine_file(ROUTINE, json.dumps(self.routine))
        return super().run_main(*argv)


class RoutineFileTest(RoutineFileCase):
    FILE = f"config/routines/{ROUTINE}.json"

    def test_sources_prints_the_transport_resolved_from_the_provider_default(self):
        expected = [
            {"provider": "obs", "role": "observability", "source": "metrics", "transport": "mcp", "skipped": []},
            {"provider": "obs", "role": "observability", "source": "monitors", "transport": "api", "skipped": []},
            {"provider": "docs", "role": "document_store", "source": "sources-page", "transport": "api", "skipped": []},
        ]
        self.assertEqual(self.run_command("sources", place="local")[1], state.dump(expected).decode("utf-8"))

    def test_sources_prints_the_provider_default_for_the_place_a_source_leaves_unset(self):
        listed = json.loads(self.run_command("sources", place="cloud")[1])
        self.assertEqual({item["source"]: item["transport"] for item in listed}, {"metrics": "api", "monitors": "api", "sources-page": "mcp"})

    def test_check_env_reads_the_resolved_transports(self):
        with mock.patch.dict(os.environ, {OBS_KEY_VAR: "set"}, clear=True):
            code, out, _ = self.run_command("check-env")
        expected = f"connector sources-page docs-cloud\nmissing metrics {OBS_APP_VAR}\nmissing monitors {OBS_APP_VAR}\n"
        self.assertEqual((code, out), (1, expected))

    def test_fetch_reads_an_api_source_resolved_from_the_provider_default(self):
        code, _, err = self.fetch(source="monitors")
        self.assertEqual((code, err, self.collection()["transport"]), (0, "", "api"))

    def test_fetch_refuses_a_source_resolved_to_mcp(self):
        self.assertEqual(self.fetch(source="metrics", place="local")[0], 2)

    def test_another_routines_broken_file_does_not_stop_sources(self):
        self.write_routine_file("other-routine", "{not json")
        self.assertEqual(self.run_command("sources")[0], 0)

    def test_another_routines_broken_file_does_not_stop_check_env(self):
        self.write_routine_file("other-routine", "{not json")
        with mock.patch.dict(os.environ, {OBS_KEY_VAR: "set", OBS_APP_VAR: "set"}, clear=True):
            self.assertEqual(self.run_command("check-env")[0], 0)

    def test_another_routines_broken_file_does_not_stop_fetch(self):
        self.write_routine_file("other-routine", "{not json")
        self.assertEqual(self.fetch(source="monitors")[0], 0)

    def test_a_pack_error_exits_3(self):
        del self.routine["query_pack"][0]["rule"]
        self.assertEqual(self.fetch()[0], 3)

    def test_a_pack_error_names_the_routine_file_and_the_key_path_inside_it(self):
        del self.routine["query_pack"][0]["rule"]
        self.assertIn(f"{self.FILE}: query_pack[0].rule: missing", self.fetch()[2])

    def test_a_pack_error_prints_no_inline_key_path(self):
        del self.routine["query_pack"][0]["rule"]
        self.assertNotIn(f"routines.{ROUTINE}", self.fetch()[2])

    def test_a_pack_error_naming_a_second_path_locates_both(self):
        self.routine["query_pack"][1]["key"] = self.routine["query_pack"][0]["key"]
        expected = f"{self.FILE}: query_pack[1].key: duplicates {self.FILE}: query_pack[0].key"
        self.assertIn(expected, self.run_command("sources")[2])

    def test_a_source_config_error_exits_2(self):
        del self.routine["sources"]["monitors"]["scope_filter"]
        self.assertEqual(self.fetch()[0], 2)

    def test_a_source_config_error_names_the_routine_file_and_the_key_path_inside_it(self):
        del self.routine["sources"]["monitors"]["scope_filter"]
        self.assertIn(f"{self.FILE}: sources.monitors.scope_filter: missing", self.fetch()[2])

    def test_an_unknown_source_names_the_routine_file(self):
        code, _, err = self.fetch(source="absent")
        self.assertEqual((code, f"{self.FILE}: sources.absent: no such source in the routine" in err), (2, True))

    def test_a_transport_left_unresolved_exits_2_naming_the_routine_file(self):
        del self.config["providers"]["obs"]["transport"]
        code, _, err = self.run_command("sources")
        self.assertEqual((code, f"{self.FILE}: sources.metrics.transport.cloud: " in err), (2, True))

    def test_a_routine_in_neither_form_exits_2(self):
        self.config["routines"] = {}
        os.makedirs(self.path("config/routines"))
        self.assertEqual(self.run_main("sources", "--config", self.write("config.json", self.config), "--routine", "absent", "--place", "cloud")[0], 2)


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
            "skipped": [],
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
            "transport": {"cloud": ["api"], "local": ["api"]},
            "name": "monitors",
            "provider_config": self.config["providers"]["obs"],
        }
        self.assertEqual(self.obs.calls[0]["source"], expected)

    def test_passes_the_window(self):
        self.fetch()
        self.assertEqual(self.obs.calls[0]["window"], {**self.window, **self.added_to_window()})

    def test_passes_the_stored_monitors_cursor(self):
        self.fetch()
        self.assertEqual(self.obs.calls[0]["cursor"], {"events_ts_ms": STORED_TS_MS, "monitors": {MONITOR_ID: "OK"}})

    def test_passes_the_stored_metrics_cursor(self):
        self.fetch(source="metrics")
        self.assertEqual(self.obs.calls[0]["cursor"], {"metrics": {"api-p95": 380.0}})

    def test_passes_the_stored_cursor_of_another_role(self):
        self.state["cursors"]["sources-page"] = {"pages": {page_id(): UTC_EDIT}}
        self.fetch(source="sources-page", place="local")
        self.assertEqual(self.doc.calls[0]["cursor"], {"pages": {page_id(): UTC_EDIT}})

    def test_passes_a_null_cursor_when_the_stored_one_has_the_former_document_store_shape(self):
        self.state["cursors"]["sources-page"] = {"last_edited": UTC_EDIT}
        self.fetch(source="sources-page", place="local")
        self.assertIsNone(self.doc.calls[0]["cursor"])

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
            "--run", self.path(RUN),
        ]
        self.run_main("plan", *common, "--out", self.path("plan.json"))
        self.run_main("parse", *common, "--out", self.path("collection.json"))
        self.assertEqual([self.obs.plans[0]["entries"][-1], self.obs.parses[0]["entries"][-1]], [tracked_entry(), tracked_entry()])


class TribeStateTest(CollectTestCase):
    def setUp(self):
        super().setUp()
        self.config["routines"][ROUTINE]["engine"] = "tribe"
        self.config["routines"][ROUTINE].update(publication_values())
        self.state = make_tribe_state()

    def test_reads_a_tribe_state(self):
        self.assertEqual(self.fetch()[0], 0)

    def test_hands_the_stored_observability_cursor_to_the_adapter(self):
        self.fetch()
        self.assertEqual(self.obs.calls[0]["cursor"], {"events_ts_ms": 1000, "monitors": {"1001": "OK"}})

    def test_hands_a_document_source_its_stored_cursor(self):
        self.state["cursors"]["sources-page"] = {"pages": {page_id(): UTC_EDIT}}
        self.fetch(source="sources-page", place="local")
        self.assertEqual(self.doc.calls[0]["cursor"], {"pages": {page_id(): UTC_EDIT}})

    def test_hands_the_adapter_only_the_pack_entries(self):
        self.state["warnings"][TRACKED_KEY] = make_warning()
        self.fetch()
        self.assertEqual(self.adapter_keys(self.obs), [API_KEY, DB_KEY])

    def test_defers_a_daily_entry_already_read_today(self):
        self.state["run"]["daily_metrics_on"] = PARIS_DAY
        self.fetch(source="metrics")
        self.assertEqual(self.statuses()["db-size"], "deferred")

    def test_rejects_a_watch_state_for_a_tribe_routine_naming_the_schema(self):
        self.state = make_state()
        code, _, err = self.fetch()
        self.assertEqual((code, "state: expected schema tribe-1 at schema" in err), (3, True))

    def test_rejects_a_tribe_state_for_a_watch_routine(self):
        del self.config["routines"][ROUTINE]["engine"]
        code, _, err = self.fetch()
        self.assertEqual((code, "state: expected schema 2 at schema" in err), (3, True))

    def test_rejects_an_invalid_tribe_state_naming_the_key_path(self):
        self.state["warnings"]["queue-depth"]["severity"] = "Critical"
        code, _, err = self.fetch()
        self.assertEqual((code, "warnings.queue-depth.severity" in err), (3, True))

    def test_rejects_an_unknown_engine(self):
        self.config["routines"][ROUTINE]["engine"] = "other"
        code, _, err = self.fetch()
        self.assertEqual((code, "routines.prod-watch.engine" in err), (2, True))


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
        self.assertEqual(self.obs.calls[0]["window"], {**self.window, **self.added_to_window()})

    def test_does_not_hand_a_deferred_lookback_entry_to_the_adapter(self):
        self.config["routines"][ROUTINE]["query_pack"][3]["lookback_days"] = 7
        self.state["run"]["daily_metrics_on"] = PARIS_DAY
        self.fetch(source="metrics")
        self.assertEqual(self.adapter_keys(self.obs), ["api-p95"])


class FirstReadWindowTest(CollectTestCase):
    def handed_window(self, source="metrics", place="cloud"):
        self.fetch(source=source, place=place)
        adapter = self.doc if source == "sources-page" else self.obs
        return adapter.calls[0]["window"]

    def test_sets_the_first_read_start_to_the_window_start_without_first_read_days(self):
        self.assertEqual(self.handed_window()["first_read_from_ts"], self.window["from_ts"])

    def test_sets_the_first_read_start_the_given_days_before_the_window_end(self):
        self.config["routines"][ROUTINE]["first_read_days"] = 7
        self.assertEqual(self.handed_window()["first_read_from_ts"], WINDOW_END - 7 * 86400)

    def test_sets_the_first_read_start_31_days_before_the_window_end(self):
        self.config["routines"][ROUTINE]["first_read_days"] = 31
        self.assertEqual(self.handed_window()["first_read_from_ts"], WINDOW_END - 31 * 86400)

    def test_sets_the_first_read_start_from_the_window_end_of_a_longer_window(self):
        self.window["from_ts"] = WINDOW_END - 5 * 86400
        self.config["routines"][ROUTINE]["first_read_days"] = 1
        self.assertEqual(self.handed_window()["first_read_from_ts"], WINDOW_END - 86400)

    def test_hands_the_first_read_start_to_an_adapter_of_another_role(self):
        self.config["routines"][ROUTINE]["first_read_days"] = 3
        self.assertEqual(self.handed_window("sources-page", "local")["first_read_from_ts"], WINDOW_END - 3 * 86400)

    def test_keeps_the_window_start_and_end_of_the_run(self):
        self.config["routines"][ROUTINE]["first_read_days"] = 7
        window = self.handed_window()
        self.assertEqual((window["from_ts"], window["to_ts"]), (self.window["from_ts"], self.window["to_ts"]))

    def test_hands_the_configured_time_zone_name(self):
        self.assertEqual(self.handed_window()["timezone"], "Europe/Paris")

    def test_hands_a_null_time_zone_to_an_adapter_of_another_role_when_none_is_configured(self):
        del self.config["timezone"]
        self.assertIsNone(self.handed_window("sources-page", "local")["timezone"])

    def test_rejects_zero_first_read_days_with_exit_2_naming_the_key(self):
        self.config["routines"][ROUTINE]["first_read_days"] = 0
        code, _, err = self.fetch(source="metrics")
        self.assertEqual((code, "first_read_days" in err), (2, True))

    def test_rejects_32_first_read_days_with_exit_2(self):
        self.config["routines"][ROUTINE]["first_read_days"] = 32
        self.assertEqual(self.fetch(source="metrics")[0], 2)

    def test_rejects_a_text_first_read_days_with_exit_2(self):
        self.config["routines"][ROUTINE]["first_read_days"] = "7"
        self.assertEqual(self.fetch(source="metrics")[0], 2)


class TrendSpanTest(CollectTestCase):
    START_OF_7_DAYS = 1779487200
    START_OF_30_DAYS = 1777500000
    MIDNIGHT_ENDING_7_DAYS = 1780005600
    SPRING_END = 1775296800
    SPRING_START = 1774738800
    FALL_END = 1793440800
    FALL_START = 1792879200

    def setUp(self):
        super().setUp()
        self.state["run"]["daily_metrics_on"] = UTC_DAY

    def trend(self, days=7, end=WINDOW_END):
        self.config["routines"][ROUTINE]["query_pack"][2]["trend_days"] = days
        self.window.update(from_ts=end - 3600, to_ts=end)
        self.fetch(source="metrics")
        return {item["key"]: item for item in self.obs.calls[0]["entries"]}

    def test_starts_the_span_at_the_local_midnight_of_the_first_of_7_local_days(self):
        self.assertEqual(self.trend(7)["api-p95"]["trend_span"]["from_ts"], self.START_OF_7_DAYS)

    def test_starts_the_span_at_the_local_midnight_of_the_first_of_30_local_days(self):
        self.assertEqual(self.trend(30)["api-p95"]["trend_span"]["from_ts"], self.START_OF_30_DAYS)

    def test_ends_the_span_at_the_window_end(self):
        self.assertEqual(self.trend(7)["api-p95"]["trend_span"]["to_ts"], WINDOW_END)

    def test_ends_the_span_at_the_window_end_of_a_cut_window(self):
        self.window["cut"] = {"from_ts": WINDOW_END - 7200, "to_ts": WINDOW_END - 3600}
        self.assertEqual(self.trend(7)["api-p95"]["trend_span"], {"from_ts": self.START_OF_7_DAYS, "to_ts": WINDOW_END})

    def test_counts_a_window_ending_at_a_local_midnight_in_the_new_local_day(self):
        self.assertEqual(
            self.trend(7, end=self.MIDNIGHT_ENDING_7_DAYS)["api-p95"]["trend_span"]["from_ts"], self.START_OF_7_DAYS
        )

    def test_starts_the_span_at_the_local_midnight_of_a_day_after_a_spring_forward(self):
        self.assertEqual(self.trend(7, end=self.SPRING_END)["api-p95"]["trend_span"]["from_ts"], self.SPRING_START)

    def test_starts_the_span_at_the_local_midnight_of_a_day_before_a_fall_back(self):
        self.assertEqual(self.trend(7, end=self.FALL_END)["api-p95"]["trend_span"]["from_ts"], self.FALL_START)

    def test_keeps_the_trend_days_on_the_entry(self):
        self.assertEqual(self.trend(7)["api-p95"]["trend_days"], 7)

    def test_gives_an_entry_without_trend_days_no_trend_span(self):
        self.assertNotIn("trend_span", self.trend(7)["db-size"])

    def test_gives_a_lookback_entry_its_span_and_no_trend_span(self):
        self.config["routines"][ROUTINE]["query_pack"][3]["lookback_days"] = 7
        entry = self.trend(7)["db-size"]
        self.assertEqual(("span" in entry, "trend_span" in entry), (True, False))

    def test_leaves_the_run_window_of_the_call_with_the_same_end(self):
        self.trend(7)
        self.assertEqual(self.obs.calls[0]["window"]["to_ts"], WINDOW_END)


class ReportedEntriesTest(CollectTestCase):
    OTHER_PAGE = "page-cdcdcdcd"

    def fetch_pages(self, entries):
        records, cursor = RESULTS["document_store"]
        self.doc.result = {"records": records, "cursor": cursor, "entries": entries}
        return self.fetch(source="sources-page", place="local")

    def test_keeps_the_entries_a_document_store_adapter_reports_per_page(self):
        reported = {page_id(): OK, self.OTHER_PAGE: {"status": "deferred", "reason": "unchanged"}}
        self.fetch_pages(reported)
        self.assertEqual(self.collection()["entries"], reported)

    def test_keeps_a_failed_page_entry_with_its_reason(self):
        reported = {page_id(): OK, self.OTHER_PAGE: {"status": "failed", "reason": "not found or not shared"}}
        self.fetch_pages(reported)
        self.assertEqual(self.collection()["entries"][self.OTHER_PAGE], reported[self.OTHER_PAGE])

    def test_rejects_a_reported_ok_entry_carrying_a_reason(self):
        self.fetch_pages({page_id(): {"status": "ok", "reason": "read"}})
        collection = self.collection()
        self.assertEqual(
            (collection["read"], collection["reason"].startswith(f"adapter output invalid: entries.{page_id()}.reason")),
            (False, True),
        )

    def test_reports_no_entry_for_a_document_store_source_not_read(self):
        self.doc.error = SourceUnreadable("HTTP 503")
        self.fetch(source="sources-page", place="local")
        self.assertEqual(self.collection()["entries"], {})

    def test_keeps_ignoring_an_entry_an_observability_adapter_reports_outside_its_selection(self):
        self.adapter_result({API_KEY: OK, DB_KEY: OK, "page-cdcdcdcd": OK})
        self.fetch()
        self.assertEqual(sorted(self.collection()["entries"]), [API_KEY, DB_KEY])

    def test_gives_the_issue_tracker_an_empty_records_shape_its_role_accepts(self):
        probe = {
            "schema": 1, "source": "issues", "role": "issue_tracker", "provider": "tracker", "transport": "api", "place": "cloud",
            "window": {"from_ts": 1, "to_ts": 2}, "read": False, "reason": "not read", "cursor": None,
            "records": collect.EMPTY_RECORDS["issue_tracker"], "entries": {},
        }
        self.assertIsNone(roles.validate_collection(probe))


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


class RecordedFetchTest(CollectTestCase):
    def setUp(self):
        super().setUp()
        self.opener = FakeOpener()
        self.obs.api_client = lambda provider, opener=None, environ=None, sleep=None: make_client(self.opener, sleeps=[])
        self.raw = self.path("run/raw/observability/monitors")

    def reads(self, *calls):
        original = self.obs.fetch

        def fetch(source, window, cursor, entries, http):
            for call in calls:
                call(http)
            return original(source, window, cursor, entries, http)

        self.obs.fetch = fetch

    def recorded(self):
        names = sorted(os.listdir(self.raw))
        return names, [json.loads(self.read_raw(name)) for name in names]

    def read_raw(self, name):
        with open(os.path.join(self.raw, name), "rb") as handle:
            return handle.read()

    def test_writes_one_file_per_call_in_call_order(self):
        self.opener.outcomes = [FakeResponse(b'{"n": 1}'), FakeResponse(b'{"n": 2}')]
        self.reads(lambda http: http.get(HTTP_PATH, {"page": 1}), lambda http: http.post(HTTP_PATH, {"q": "x"}))
        self.assertEqual(self.fetch()[0], 0)
        expected = [
            {"method": "GET", "path": HTTP_PATH, "query": "page=1", "body": None, "status": 200, "link": None, "response": {"n": 1}, "error": None},
            {"method": "POST", "path": HTTP_PATH, "query": "", "body": {"q": "x"}, "status": 200, "link": None, "response": {"n": 2}, "error": None},
        ]
        self.assertEqual(self.recorded(), (["monitors-1.json", "monitors-2.json"], expected))

    def test_writes_canonical_json(self):
        self.opener.outcomes = [FakeResponse(b'{"b": 1, "a": "\\u00e9"}')]
        self.reads(lambda http: http.get(HTTP_PATH))
        self.fetch()
        raw = self.read_raw("monitors-1.json")
        self.assertEqual(raw, state.dump(json.loads(raw)))

    def test_creates_the_folder_and_its_parents(self):
        self.assertEqual((self.fetch()[0], os.listdir(self.raw)), (0, []))

    def test_a_record_holds_no_request_header_and_no_credential_value(self):
        self.opener.outcomes = [FakeResponse(b'{"n": 1}')]
        self.reads(lambda http: http.post(HTTP_PATH, {"q": "x"}))
        self.fetch()
        text = "".join(self.read_raw(name).decode("utf-8") for name in os.listdir(self.raw))
        self.assertEqual((HTTP_SECRET in text, "Authorization" in text, "Bearer" in text), (False, False, False))

    def test_a_failed_call_is_recorded_with_its_status_and_error(self):
        self.opener.outcomes = [http_error(404)]
        self.reads(lambda http: http.get(HTTP_PATH))
        self.fetch()
        error = {"class": "SourceUnreadable", "message": "HTTP 404 GET " + HTTP_PATH, "status": 404}
        record = self.recorded()[1][0]
        self.assertEqual((record["status"], record["response"], record["error"]), (404, None, error))

    def test_a_failed_call_still_fails_the_read(self):
        self.opener.outcomes = [http_error(404)]
        self.reads(lambda http: http.get(HTTP_PATH))
        code, _, _ = self.fetch()
        collection = self.collection()
        self.assertEqual((code, collection["read"], collection["reason"]), (0, False, f"{OBS_HOST}: HTTP 404 GET {HTTP_PATH}"))

    def test_a_fetch_that_fails_midway_keeps_the_records_so_far(self):
        self.opener.outcomes = [FakeResponse(b'{"n": 1}'), http_error(403)]
        self.reads(lambda http: http.get(HTTP_PATH), lambda http: http.get(HTTP_PATH), lambda http: http.get(HTTP_PATH))
        self.fetch()
        names, records = self.recorded()
        self.assertEqual((names, [record["status"] for record in records]), (["monitors-1.json", "monitors-2.json"], [200, 403]))

    def test_a_retried_call_is_one_record_with_its_final_outcome(self):
        self.opener.outcomes = [http_error(503), FakeResponse(b'{"n": 1}')]
        self.reads(lambda http: http.get(HTTP_PATH))
        self.fetch()
        names, records = self.recorded()
        self.assertEqual((names, records[0]["status"], records[0]["response"]), (["monitors-1.json"], 200, {"n": 1}))

    def test_a_lone_surrogate_of_a_response_is_recorded_as_a_replacement_character(self):
        self.opener.outcomes = [FakeResponse(b'{"text": "a\\ud800b"}')]
        self.reads(lambda http: http.get(HTTP_PATH))
        code, _, _ = self.fetch()
        self.assertEqual((code, self.recorded()[1][0]["response"]), (0, {"text": "a\ufffdb"}))

    def test_a_folder_that_holds_a_file_is_refused_with_exit_2_naming_it(self):
        os.makedirs(self.raw)
        with open(os.path.join(self.raw, "monitors-1.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        code, _, stderr = self.fetch()
        self.assertEqual((code, self.raw in stderr, self.obs.calls, os.path.exists(self.path("collection.json"))), (2, True, [], False))

    def test_a_record_that_cannot_be_written_exits_2_naming_the_file(self):
        self.opener.outcomes = [FakeResponse(b"{}")]
        self.reads(lambda http: http.get(HTTP_PATH))
        write_all = state.write_all

        def failing(documents):
            if any(os.path.basename(path) == "monitors-1.json" for path, _ in documents):
                raise state.InputError("cannot write monitors-1.json: disk full")
            return write_all(documents)

        with mock.patch.object(state, "write_all", failing):
            code, _, stderr = self.fetch()
        self.assertEqual((code, stderr, os.path.exists(self.path("collection.json"))), (2, "collect.py: cannot write monitors-1.json: disk full\n", False))


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
    def relay(self, command, out, source, place, extra=()):
        config = self.write("config.json", self.config)
        window = self.write("window.json", self.window)
        stored = self.write("state.json", self.state)
        return self.run_main(
            command, "--config", config, "--routine", ROUTINE, "--source", source, "--place", place,
            "--window", window, "--state", stored, "--run", self.path(RUN), "--out", out, *extra,
        )

    def plan(self, source="sources-page", place="cloud"):
        return self.relay("plan", self.path("plan.json"), source, place)

    def parse(self, source="sources-page", place="cloud"):
        return self.relay("parse", self.path("collection.json"), source, place)

    def parse_in_subprocess(self):
        argv = [
            "parse", "--config", self.path("config.json"), "--routine", ROUTINE, "--source", "sources-page", "--place", "cloud",
            "--window", self.path("window.json"), "--state", self.path("state.json"), "--run", self.path(RUN),
            "--out", self.path("collection.json"),
        ]
        subprocess.run([sys.executable, "-c", FAKE_ADAPTERS_MAIN, HERE, *argv], capture_output=True, timeout=10, check=True)

    def response_path(self, call_id):
        source = call_id.rsplit("-", 1)[0]
        directory = self.raw_path(source) if source in self.config["routines"][ROUTINE]["sources"] else self.path(RESPONSES)
        return os.path.join(directory, call_id + ".txt")

    def respond(self, call_id, text="{}"):
        self.respond_bytes(call_id, text.encode("utf-8"))

    def respond_bytes(self, call_id, data):
        os.makedirs(os.path.dirname(self.response_path(call_id)), exist_ok=True)
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

    def calls_doc(self, source="sources-page"):
        with open(os.path.join(self.raw_path(source), "calls.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def call_ids(self):
        return [call["id"] for call in self.plan_doc()["calls"]]


class RelayParsePreferenceTest(RelayTestCase):
    SKIPPED = [{"transport": "api", "missing": [DOC_TOKEN_VAR]}]

    def setUp(self):
        super().setUp()
        self.config["routines"][ROUTINE]["sources"]["sources-page"]["transport"] = {"cloud": ["api", "mcp"], "local": "api"}

    def listing(self, transport, skipped=()):
        entry = {"source": "sources-page", "role": "document_store", "provider": "docs", "transport": transport, "skipped": list(skipped)}
        return self.write("sources.json", [entry])

    def relay_with(self, command, environ, *extra):
        with mock.patch.dict(os.environ, environ, clear=True):
            return self.relay(command, self.path("collection.json" if command == "parse" else "plan.json"), "sources-page", "cloud", extra)

    def test_plan_reads_the_choice_from_the_sources_file(self):
        self.assertEqual(self.relay_with("plan", {DOC_TOKEN_VAR: "set"}, "--sources", self.listing("mcp", self.SKIPPED))[0], 0)

    def test_plan_chooses_from_the_environment_without_a_sources_file(self):
        self.assertEqual(self.relay_with("plan", {})[0], 0)

    def test_plan_refuses_a_source_the_environment_gives_to_api(self):
        self.assertEqual(self.relay_with("plan", {DOC_TOKEN_VAR: "set"})[0], 2)

    def test_parse_writes_the_skipped_transports_to_the_collection(self):
        listing = self.listing("mcp", self.SKIPPED)
        self.relay_with("plan", {}, "--sources", listing)
        self.respond("sources-page-1")
        self.relay_with("plan", {}, "--sources", listing)
        self.respond("sources-page-2")
        self.relay_with("plan", {}, "--sources", listing)
        code = self.relay_with("parse", {}, "--sources", listing)[0]
        with open(self.path("collection.json"), encoding="utf-8") as handle:
            written = json.load(handle)
        self.assertEqual((code, written["transport"], written["skipped"]), (0, "mcp", self.SKIPPED))


CHAT_CHANNEL = "CHAN1"
CHAT_LISTING = json.dumps({"messages": f"Channel: #room ({CHAT_CHANNEL})\n", "pagination_info": "There are no more messages available."})
CITED_ROOT = "1791990000.000100"
CITED_THREADS = [{"channel": CHAT_CHANNEL, "root_ts": CITED_ROOT}]
CONFIG_THREADS = [{"channel": "CHAN9", "root_ts": "junk"}]
STORED_THREADS = [{**thread, "links": ["https://chat.example.test/archives/cited"]} for thread in CITED_THREADS]
NO_CHAT_RESULT = {"records": {"messages": []}, "cursor": {"ts": {}}, "entries": {}}


class ReplayTest(RelayTestCase):
    def setUp(self):
        super().setUp()
        self.opener = FakeOpener()
        self.obs.api_client = lambda provider, opener=None, environ=None, sleep=None: make_client(self.opener, sleeps=[])
        self.raw = self.path("run/raw")
        os.mkdir(self.path("run"))
        self.adapter_fetch = self.obs.fetch
        self.reads(lambda http: http.get(HTTP_PATH, {"page": 1}))

    def reads(self, *calls):
        def fetch(source, window, cursor, entries, http):
            for call in calls:
                call(http)
            return self.adapter_fetch(source, window, cursor, entries, http)

        self.obs.fetch = fetch

    def record_api_sources(self):
        self.opener.outcomes = [FakeResponse(b'{"n": 1}'), FakeResponse(b'{"n": 2}')]
        for name in ("metrics", "monitors"):
            self.fetch(source=name, out=self.path(f"run/{name}.json"))

    def record_run(self):
        self.record_api_sources()
        self.record_mcp_source()

    def record_mcp_source(self):
        self.loop()
        self.parse()
        os.rename(self.path("collection.json"), self.path("run/sources-page.json"))

    def replay(self, place="cloud", extra=()):
        config = self.write("config.json", self.config)
        window = self.write("window.json", self.window)
        stored = self.write("state.json", self.state)
        return self.run_main(
            "replay", "--config", config, "--routine", ROUTINE, "--place", place,
            "--window", window, "--state", stored, "--run", self.path(RUN), "--out", self.path("replayed"), *extra,
        )

    def bytes_of(self, name, folder="replayed"):
        with open(self.path(f"{folder}/{name}.json"), "rb") as handle:
            return handle.read()

    def test_writes_one_collection_per_source_in_the_out_folder(self):
        self.record_run()
        self.assertEqual((self.replay()[0], sorted(os.listdir(self.path("replayed")))), (0, ["metrics.json", "monitors.json", "sources-page.json"]))

    def test_replays_through_the_first_listed_transport_whatever_the_environment(self):
        self.record_run()
        provider = self.config["routines"][ROUTINE]["sources"]["monitors"]["provider"]
        self.config["providers"][provider].setdefault("mcp", {"connectors": {"cloud": "obs-cloud", "local": "obs-local"}})
        self.config["routines"][ROUTINE]["sources"]["monitors"]["transport"] = {"cloud": ["api", "mcp"], "local": ["api"]}
        with mock.patch.dict(os.environ, {}, clear=True):
            code = self.replay()[0]
        self.assertEqual((code, self.bytes_of("monitors")), (0, self.bytes_of("monitors", "run")))

    def test_rebuilds_an_api_source_byte_identical_to_its_fetch(self):
        self.record_run()
        self.replay()
        self.assertEqual([self.bytes_of(name) for name in ("metrics", "monitors")], [self.bytes_of(name, "run") for name in ("metrics", "monitors")])

    def test_replays_a_source_through_the_transport_of_the_sources_file(self):
        self.config["routines"][ROUTINE]["sources"]["monitors"]["transport"]["cloud"] = ["api", "mcp"]
        self.record_run()
        names = {"metrics": ("observability", "api"), "monitors": ("observability", "api"), "sources-page": ("document_store", "mcp")}
        listing = self.write("sources.json", [
            {"source": name, "role": role, "provider": "obs", "transport": transport, "skipped": []} for name, (role, transport) in names.items()
        ])
        with mock.patch.dict(os.environ, {}, clear=True):
            code = self.replay(extra=("--sources", listing))[0]
        self.assertEqual((code, self.bytes_of("monitors")), (0, self.bytes_of("monitors", "run")))

    def test_rebuilds_an_mcp_source_byte_identical_to_its_parse(self):
        self.reads()
        self.record_mcp_source()
        self.replay()
        self.assertEqual(self.bytes_of("sources-page"), self.bytes_of("sources-page", "run"))

    def test_rebuilds_the_collection_of_an_adapter_refused_config_byte_identical(self):
        def refuse(provider, opener=None, environ=None, sleep=None):
            raise SourceUnreadable("api.credentials: must name api_key")

        self.obs.api_client = refuse
        self.fetch(source="monitors", out=self.path("run/monitors.json"))
        self.record_mcp_source()
        self.replay()
        self.assertEqual((self.bytes_of("monitors"), json.loads(self.bytes_of("monitors"))["read"]), (self.bytes_of("monitors", "run"), False))

    def test_rebuilds_a_recorded_http_error_as_the_same_not_read_collection(self):
        self.opener.outcomes = [http_error(404)]
        self.fetch(source="metrics", out=self.path("run/metrics.json"))
        self.opener.outcomes = [http_error(404)]
        self.fetch(source="monitors", out=self.path("run/monitors.json"))
        self.record_mcp_source()
        self.replay()
        self.assertEqual((self.bytes_of("metrics"), json.loads(self.bytes_of("metrics"))["read"]), (self.bytes_of("metrics", "run"), False))

    def test_rebuilds_a_source_skipped_by_the_run_as_the_same_not_read_collection(self):
        self.config["routines"][ROUTINE]["engine"] = "tribe"
        self.config["routines"][ROUTINE].update(publication_values())
        self.config["routines"][ROUTINE]["sources"] = {
            "sources-page": {"provider": "docs", "transport": {"cloud": "mcp", "local": "api"}, "page_from_state": "previous_page"}
        }
        self.config["routines"][ROUTINE]["query_pack"] = []
        self.state = make_tribe_state()
        self.state["run"]["previous_page"] = None
        self.parse()
        os.rename(self.path("collection.json"), self.path("run/sources-page.json"))
        self.replay()
        self.assertEqual((self.bytes_of("sources-page"), json.loads(self.bytes_of("sources-page"))["reason"]), (self.bytes_of("sources-page", "run"), collect.NO_PREVIOUS_PAGE))

    def test_a_request_that_differs_from_its_record_exits_3_naming_the_source_the_call_and_the_request(self):
        self.record_run()
        self.reads(lambda http: http.get(HTTP_PATH, {"page": 2}))
        code, _, stderr = self.replay()
        expected = f"collect.py: rejected: source metrics call 1 GET {HTTP_PATH}: request differs from its record in query\n"
        self.assertEqual((code, stderr, os.path.exists(self.path("replayed/metrics.json"))), (3, expected, False))

    def test_a_call_past_the_last_record_exits_3_naming_the_source_the_call_and_the_request(self):
        self.record_run()
        self.reads(lambda http: http.get(HTTP_PATH, {"page": 1}), lambda http: http.get(HTTP_PATH, {"page": 1}))
        code, _, stderr = self.replay()
        self.assertEqual((code, stderr), (3, f"collect.py: rejected: source metrics call 2 GET {HTTP_PATH}: no record, 1 recorded\n"))

    def test_a_source_with_no_raw_folder_replays_with_zero_records(self):
        self.reads()
        self.record_mcp_source()
        self.assertEqual((self.replay()[0], os.path.exists(self.path("replayed/monitors.json"))), (0, True))

    def test_a_malformed_record_exits_3_naming_the_file(self):
        os.makedirs(os.path.join(self.raw, "observability", "metrics"))
        with open(os.path.join(self.raw, "observability", "metrics", "metrics-1.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        code, _, stderr = self.replay()
        self.assertEqual((code, stderr), (3, "collect.py: rejected: record metrics-1.json: missing key method\n"))

    def test_an_mcp_source_without_its_saved_responses_exits_2(self):
        self.reads()
        os.makedirs(self.raw)
        self.assertEqual(self.replay()[0], 2)

    def test_an_out_folder_that_cannot_be_created_exits_2_naming_it(self):
        with open(self.path("replayed"), "w", encoding="utf-8") as handle:
            handle.write("")
        code, _, stderr = self.replay()
        self.assertEqual((code, self.path("replayed") in stderr), (2, True))


class TribeChatCase(RelayTestCase):
    def setUp(self):
        super().setUp()
        self.chat = fake_adapter("fakechat", "chat")
        self.chat.result = NO_CHAT_RESULT
        patched = mock.patch.dict(sys.modules, {"providers.fakechat": self.chat})
        patched.start()
        self.addCleanup(patched.stop)
        self.config["providers"]["chat"] = {
            "adapter": "fakechat",
            "api": {"base_url": "https://chat.example.test", "credentials": {"token": "CHAT_TOKEN"}},
            "mcp": {"connectors": {"cloud": "chat-cloud", "local": "chat-local"}},
        }
        self.config["routines"][ROUTINE]["engine"] = "tribe"
        self.config["routines"][ROUTINE].update(publication_values())
        self.config["routines"][ROUTINE]["sources"]["team-chat"] = {
            "provider": "chat",
            "transport": {"cloud": "mcp", "local": "api"},
            "channels": [CHAT_CHANNEL],
        }
        self.state = make_tribe_state()
        self.state["threads"] = {"team-chat": STORED_THREADS}


class TribeChatThreadsTest(TribeChatCase):
    def test_hands_the_adapter_the_cited_threads_of_the_source_over_the_api_transport(self):
        self.fetch(source="team-chat", place="local")
        self.assertEqual(self.chat.calls[0]["source"]["threads"], CITED_THREADS)

    def test_hands_the_adapter_the_cited_threads_of_the_source_when_planning(self):
        self.plan(source="team-chat")
        self.assertEqual(self.chat.plans[0]["source"]["threads"], CITED_THREADS)

    def test_hands_the_adapter_the_cited_threads_of_the_source_when_parsing(self):
        self.loop(source="team-chat")
        self.parse(source="team-chat")
        self.assertEqual(self.chat.parses[0]["source"]["threads"], CITED_THREADS)

    def test_hands_the_adapter_no_thread_of_another_source(self):
        self.state["threads"] = {"other-chat": STORED_THREADS}
        self.fetch(source="team-chat", place="local")
        self.assertEqual(self.chat.calls[0]["source"]["threads"], [])

    def test_hands_the_adapter_no_thread_when_the_state_cites_none(self):
        self.state["threads"] = {}
        self.fetch(source="team-chat", place="local")
        self.assertEqual(self.chat.calls[0]["source"]["threads"], [])

    def test_keeps_the_failed_thread_entries_of_the_adapter(self):
        failed = {f"{CHAT_CHANNEL}:{CITED_ROOT}": {"status": "failed", "reason": "thread_not_found"}}
        self.chat.result = {**NO_CHAT_RESULT, "entries": failed}
        self.fetch(source="team-chat", place="local")
        self.assertEqual(self.collection()["entries"], failed)

    def test_does_not_hand_a_document_source_threads(self):
        self.state["threads"] = {"sources-page": STORED_THREADS}
        self.fetch(source="sources-page", place="local")
        self.assertNotIn("threads", self.doc.calls[0]["source"])

    def test_does_not_hand_a_watch_routine_threads(self):
        del self.config["routines"][ROUTINE]["engine"]
        self.state = make_state()
        self.fetch(source="team-chat", place="local")
        self.assertNotIn("threads", self.chat.calls[0]["source"])

    def test_drops_the_threads_written_in_the_config_of_a_watch_source(self):
        del self.config["routines"][ROUTINE]["engine"]
        self.config["routines"][ROUTINE]["sources"]["team-chat"]["threads"] = CONFIG_THREADS
        self.state = make_state()
        self.fetch(source="team-chat", place="local")
        self.assertNotIn("threads", self.chat.calls[0]["source"])

    def test_replaces_the_threads_written_in_the_config_of_a_tribe_source(self):
        self.config["routines"][ROUTINE]["sources"]["team-chat"]["threads"] = CONFIG_THREADS
        self.state["threads"] = {}
        self.fetch(source="team-chat", place="local")
        self.assertEqual(self.chat.calls[0]["source"]["threads"], [])

    def test_drops_the_threads_written_in_the_config_of_a_document_source(self):
        self.config["routines"][ROUTINE]["sources"]["sources-page"]["threads"] = CONFIG_THREADS
        self.fetch(source="sources-page", place="local")
        self.assertNotIn("threads", self.doc.calls[0]["source"])

    def test_hands_the_adapter_only_the_channel_and_root_of_a_stored_thread(self):
        self.fetch(source="team-chat", place="local")
        self.assertEqual(set(self.chat.calls[0]["source"]["threads"][0]), {"channel", "root_ts"})


class TribeChatCallCapTest(TribeChatCase):
    def setUp(self):
        super().setUp()
        self.config["providers"]["chat"]["adapter"] = "slack"
        self.state["threads"] = {"team-chat": [{**STORED_THREADS[0], "root_ts": f"{1791990000 + n}.000100"} for n in range(60)]}

    def test_cited_thread_reads_reaching_the_response_cap_end_the_plan_partial(self):
        self.plan(source="team-chat")
        answer_planned(self.plan_doc(), CHAT_LISTING)
        for _ in range(2, collect.CALL_CAP + 1):
            self.plan(source="team-chat")
            answer_planned(self.plan_doc(), json.dumps({"ok": False, "error": "thread_not_found"}))
        self.plan(source="team-chat")
        self.assertEqual(self.plan_doc(), {"done": True, "partial": "call cap", "calls": []})


class StoreRelayTest(TribeChatCase):
    TOOL = "mcp__chat-cloud__slack_read_channel"

    def setUp(self):
        super().setUp()
        self.config["providers"]["chat"]["adapter"] = "slack"
        self.state["threads"] = {}

    def first_call(self):
        self.plan(source="team-chat")
        return self.plan_doc()["calls"][0]

    def manifest(self):
        with open(self.path("run/manifest.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def capture_at(self, call, offset, arguments=None):
        document = {"tool_name": self.TOOL, "arguments": call["arguments"] if arguments is None else arguments, "text": CHAT_LISTING, "captured_at_ns": RELAY_START_NS + offset}
        os.makedirs(self.relay_dir, mode=0o700, exist_ok=True)
        relay_capture.write_capture(self.relay_dir, f"{RELAY_START_NS + offset}-toolu_1.json", document)

    def test_names_the_call_by_its_read(self):
        call = self.first_call()
        self.assertEqual((call["id"].split("/")[:2], call["id"].endswith(".team-chat/page-001")), (["kind=history", f"channel={CHAT_CHANNEL}"], True))

    def test_plans_the_call_at_its_read_page(self):
        call = self.first_call()
        self.assertEqual(call["path"], os.path.join(self.path(RUN), "store", "provider=chat", call["id"] + ".txt"))

    def test_keeps_the_relay_files_in_the_relay_folder(self):
        self.first_call()
        self.assertEqual(
            (os.path.exists(self.path("run/relay/team-chat/calls.json")), os.path.exists(self.path("run/raw/chat/team-chat"))), (True, False)
        )

    def test_reads_a_page_saved_by_hand_at_its_path(self):
        answer_planned({"calls": [self.first_call()]}, CHAT_LISTING)
        self.plan(source="team-chat")
        self.parse(source="team-chat")
        self.assertEqual((self.collection()["read"], self.collection()["records"]["messages"]), (True, []))

    def test_writes_the_reads_of_the_source_in_the_manifest(self):
        call = self.first_call()
        answer_planned({"calls": [call]}, CHAT_LISTING)
        self.plan(source="team-chat")
        self.parse(source="team-chat")
        read = "provider=chat/" + call["id"].rsplit("/", 1)[0]
        self.assertEqual(self.manifest()["sources"]["team-chat"], {"fetched": 1, "reads": [read], "reused": 0})

    def test_picks_up_a_captured_result_at_the_read_path(self):
        self.relay_clock.now_ns = RELAY_START_NS
        call = self.first_call()
        self.capture_at(call, 1)
        self.relay_clock.now_ns = RELAY_START_NS + 2
        self.plan(source="team-chat")
        with open(call["path"], encoding="utf-8") as handle:
            self.assertEqual(handle.read(), CHAT_LISTING)

    def test_names_how_a_capture_of_a_store_backed_call_differs(self):
        self.relay_clock.now_ns = RELAY_START_NS
        call = self.first_call()
        self.capture_at(call, 1, {**call["arguments"], "limit": 99})
        self.relay_clock.now_ns = RELAY_START_NS + 2
        _, _, err = self.plan(source="team-chat")
        self.assertIn(f"relay capture mismatch {call['id']}", err)

    def test_reports_no_response_before_any_page_is_saved(self):
        self.first_call()
        self.parse(source="team-chat")
        self.assertEqual(self.collection()["reason"], f"chat-cloud: {collect.NO_RESPONSE}")

    def test_reports_a_plan_not_done_after_a_saved_page(self):
        more = json.dumps({"messages": f"Channel: #room ({CHAT_CHANNEL})\n", "pagination_info": "There are more messages available. To view the next page, use cursor: `c2`"})
        answer_planned({"calls": [self.first_call()]}, more)
        self.plan(source="team-chat")
        self.parse(source="team-chat")
        self.assertEqual(self.collection()["reason"], collect.PLAN_NOT_DONE)

    def shared_read(self, call):
        return self.path(os.path.join("shared", "provider=chat", call["id"].rsplit("/", 1)[0], store.READ_FILE))

    def test_publishes_a_read_to_the_store_dir_of_the_place(self):
        self.config["places"]["cloud"]["store_dir"] = self.path("shared")
        call = self.first_call()
        answer_planned({"calls": [call]}, CHAT_LISTING)
        self.plan(source="team-chat")
        self.parse(source="team-chat")
        self.assertTrue(os.path.isfile(self.shared_read(call)))

    def test_keeps_the_reads_in_the_run_store_without_a_store_dir(self):
        call = self.first_call()
        answer_planned({"calls": [call]}, CHAT_LISTING)
        self.plan(source="team-chat")
        self.parse(source="team-chat")
        self.assertFalse(os.path.exists(self.path("shared")))

    def test_plan_refuses_a_store_dir_inside_a_git_working_tree(self):
        subprocess.run(["git", "init", "--quiet", self.path("repository")], check=True)
        self.config["places"]["cloud"]["store_dir"] = self.path("repository/store")
        code, _, err = self.plan(source="team-chat")
        self.assertEqual((code, "places.cloud.store_dir" in err), (2, True))

    def test_fetches_a_store_backed_source_into_its_reads(self):
        opener = FakeOpener()
        opener.outcomes = [FakeResponse(json.dumps({"ok": True, "messages": [], "has_more": False}).encode("utf-8"))]
        slack = providers.load("slack")
        client = make_client(opener, sleeps=[])
        with mock.patch.dict(os.environ, {"CHAT_TOKEN": "set"}), mock.patch.object(slack, "api_client", lambda provider, opener=None, environ=None, sleep=None: client):
            self.fetch(source="team-chat", place="local")
        pages = [name for _, _, files in os.walk(self.path("run/store/provider=chat/kind=history")) for name in files if name.startswith("page-")]
        self.assertEqual((pages, self.manifest()["sources"]["team-chat"]["fetched"]), (["page-001.json"], 1))


class StoreReplayTest(StoreRelayTest):
    def setUp(self):
        super().setUp()
        routine = self.config["routines"][ROUTINE]
        routine["sources"] = {"team-chat": routine["sources"]["team-chat"]}
        routine["query_pack"] = []

    def record_relay(self):
        call = self.first_call()
        answer_planned({"calls": [call]}, CHAT_LISTING)
        self.plan(source="team-chat")
        self.parse(source="team-chat")
        return call

    def replay(self):
        config = self.write("config.json", self.config)
        return self.run_main(
            "replay", "--config", config, "--routine", ROUTINE, "--place", "cloud", "--window", self.write("window.json", self.window),
            "--state", self.write("state.json", self.state), "--run", self.path(RUN), "--out", self.path("replayed"),
        )

    def read_document_path(self, call):
        return os.path.join(os.path.dirname(call["path"]), store.READ_FILE)

    def test_replays_a_relayed_source_byte_for_byte(self):
        self.record_relay()
        self.assertEqual(self.replay()[0], 0)
        with open(self.path("collection.json"), "rb") as run, open(self.path("replayed/team-chat.json"), "rb") as replayed:
            self.assertEqual(replayed.read(), run.read())

    def test_writes_nothing_into_the_run_folder(self):
        self.record_relay()
        before = sorted(os.path.relpath(os.path.join(folder, name), self.path(RUN)) for folder, _, files in os.walk(self.path(RUN)) for name in files)
        self.replay()
        after = sorted(os.path.relpath(os.path.join(folder, name), self.path(RUN)) for folder, _, files in os.walk(self.path(RUN)) for name in files)
        self.assertEqual(after, before)

    def test_exits_3_on_a_read_the_run_did_not_make(self):
        self.record_relay()
        manifest = self.manifest()
        manifest["sources"]["team-chat"]["reads"] = []
        self.write("run/manifest.json", manifest)
        code, _, err = self.replay()
        self.assertEqual((code, "a read the run did not make" in err, "kind=history/channel=CHAN1/" in err), (3, True, True))

    def test_exits_3_on_a_request_that_differs_from_its_record(self):
        call = self.record_relay()
        with open(self.read_document_path(call), encoding="utf-8") as handle:
            document = json.load(handle)
        document["pages"][0]["request"]["arguments"]["limit"] = 99
        with open(self.read_document_path(call), "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        code, _, err = self.replay()
        self.assertEqual((code, "call 1 slack_read_channel: request differs from its record in arguments" in err), (3, True))

    def test_exits_2_without_a_manifest(self):
        self.record_relay()
        os.remove(self.path("run/manifest.json"))
        code, _, err = self.replay()
        self.assertEqual((code, "holds no manifest.json" in err), (2, True))

    def test_replays_a_fetched_source_from_its_records(self):
        opener = FakeOpener()
        opener.outcomes = [FakeResponse(json.dumps({"ok": True, "messages": [{"type": "message", "user": "U1", "text": "hi", "ts": "1780000100.000100"}], "has_more": False}).encode("utf-8"))]
        client = make_client(opener, sleeps=[])
        with mock.patch.dict(os.environ, {"CHAT_TOKEN": "set"}), mock.patch.object(providers.load("slack"), "api_client", lambda provider, opener=None, environ=None, sleep=None: client):
            self.fetch(source="team-chat", place="local")
            config = self.write("config.json", self.config)
            code, _, _ = self.run_main(
                "replay", "--config", config, "--routine", ROUTINE, "--place", "local", "--window", self.path("window.json"),
                "--state", self.path("state.json"), "--run", self.path(RUN), "--out", self.path("replayed"),
            )
        with open(self.path("collection.json"), "rb") as run, open(self.path("replayed/team-chat.json"), "rb") as replayed:
            self.assertEqual((code, replayed.read()), (0, run.read()))


def answer_planned(plan, text):
    call = plan["calls"][0]
    store.make_folders(os.path.dirname(call["path"]))
    with open(call["path"], "w", encoding="utf-8") as handle:
        handle.write(text)


RECAP_SEARCHES = [{"name": "dms", "filters": "is:dm", "since": "window"}]
RECAP_REREADS = [
    {"kind": "dm", "channel": RECAP_CHANNEL_A, "root_ts": None, "last_ts": RECAP_LAST_TS},
    {"kind": "thread", "channel": RECAP_CHANNEL_B, "root_ts": RECAP_ROOT_TS, "last_ts": RECAP_LAST_TS},
]


class RecapChatCase(RelayTestCase):
    def setUp(self):
        super().setUp()
        self.chat = fake_adapter("fakechat", "chat")
        self.chat.result = NO_CHAT_RESULT
        patched = mock.patch.dict(sys.modules, {"providers.fakechat": self.chat})
        patched.start()
        self.addCleanup(patched.stop)
        self.config["providers"]["chat"] = {
            "adapter": "fakechat",
            "api": {"base_url": "https://chat.example.test", "credentials": {"token": "CHAT_TOKEN"}},
            "mcp": {"connectors": {"cloud": "chat-cloud", "local": "chat-local"}},
        }
        routine = make_recap_routine()
        routine["sources"] = {
            "team-chat": {
                "provider": "chat",
                "transport": {"cloud": "mcp", "local": "api"},
                "owner": RECAP_OWNER,
                "searches": RECAP_SEARCHES,
            }
        }
        self.config["routines"][ROUTINE] = routine
        self.state = make_recap_state()
        self.window = {"from_ts": WINDOW_END - 3600, "to_ts": WINDOW_END, "limited": None, "explicit": False}

    def reread_units(self, **units):
        self.state = make_recap_state(units={key: make_recap_unit(**fields) for key, fields in units.items()})


class RecapChatRereadsTest(RecapChatCase):
    def test_hands_the_adapter_a_reread_per_stored_waiting_or_promise_unit_over_the_api_transport(self):
        self.fetch(source="team-chat", place="local")
        self.assertEqual(self.chat.calls[0]["source"]["rereads"], RECAP_REREADS)

    def test_hands_the_adapter_the_rereads_when_planning(self):
        self.plan(source="team-chat")
        self.assertEqual(self.chat.plans[0]["source"]["rereads"], RECAP_REREADS)

    def test_hands_the_adapter_the_rereads_when_parsing(self):
        self.loop(source="team-chat")
        self.parse(source="team-chat")
        self.assertEqual(self.chat.parses[0]["source"]["rereads"], RECAP_REREADS)

    def test_skips_the_units_that_are_not_waiting_or_promise(self):
        statuses = ("waiting_on_others", "team_ask", "handled", "announcement")
        self.state = make_recap_state(units={f"dm-D{index}": make_recap_unit(channel=f"D{index}", status=status) for index, status in enumerate(statuses)})
        self.fetch(source="team-chat", place="local")
        self.assertEqual(self.chat.calls[0]["source"]["rereads"], [])

    def test_names_the_group_conversation_kind_and_the_thread_root(self):
        self.state = make_recap_state(units={f"dm-{RECAP_CHANNEL_A}": make_recap_unit(kind="group_dm"), f"thread-{RECAP_CHANNEL_B}-{RECAP_ROOT_TS}": make_recap_unit(kind="mention", channel=RECAP_CHANNEL_B)})
        self.fetch(source="team-chat", place="local")
        self.assertEqual([(item["kind"], item["root_ts"]) for item in self.chat.calls[0]["source"]["rereads"]], [("group_dm", None), ("mention", RECAP_ROOT_TS)])

    def since(self, **units):
        self.config["routines"][ROUTINE]["thread_reads"] = "since"
        self.state = make_recap_state(units={key: make_recap_unit(**fields) for key, fields in units.items()})

    def test_hands_the_adapter_the_thread_units_with_a_known_owner_activity_when_reading_since(self):
        self.since(**{f"thread-{RECAP_CHANNEL_B}-{RECAP_ROOT_TS}": {"kind": "thread", "channel": RECAP_CHANNEL_B, "status": "handled", "owner_last_ts": RECAP_LAST_TS}})
        self.fetch(source="team-chat", place="local")
        self.assertEqual(self.chat.calls[0]["source"]["known_threads"], [{"channel": RECAP_CHANNEL_B, "root_ts": RECAP_ROOT_TS, "last_ts": RECAP_LAST_TS}])

    def test_counts_a_null_owner_activity_as_known_when_reading_since(self):
        self.since(**{f"thread-{RECAP_CHANNEL_B}-{RECAP_ROOT_TS}": {"kind": "thread", "channel": RECAP_CHANNEL_B, "owner_last_ts": None}})
        self.fetch(source="team-chat", place="local")
        self.assertEqual(len(self.chat.calls[0]["source"]["known_threads"]), 1)

    def test_leaves_out_a_thread_unit_without_the_owner_activity_key_when_reading_since(self):
        self.since(**{f"thread-{RECAP_CHANNEL_B}-{RECAP_ROOT_TS}": {"kind": "thread", "channel": RECAP_CHANNEL_B}})
        self.fetch(source="team-chat", place="local")
        self.assertEqual(self.chat.calls[0]["source"]["known_threads"], [])

    def test_leaves_out_a_direct_conversation_unit_when_reading_since(self):
        self.since(**{f"dm-{RECAP_CHANNEL_A}": {"owner_last_ts": RECAP_LAST_TS}})
        self.fetch(source="team-chat", place="local")
        self.assertEqual(self.chat.calls[0]["source"]["known_threads"], [])

    def test_hands_the_adapter_the_known_threads_when_planning_since(self):
        self.since(**{f"thread-{RECAP_CHANNEL_B}-{RECAP_ROOT_TS}": {"kind": "thread", "channel": RECAP_CHANNEL_B, "owner_last_ts": RECAP_LAST_TS}})
        self.plan(source="team-chat")
        self.assertEqual(len(self.chat.plans[0]["source"]["known_threads"]), 1)

    def test_hands_the_adapter_no_known_threads_when_reading_in_full(self):
        self.config["routines"][ROUTINE]["thread_reads"] = "full"
        self.state = make_recap_state(units={f"thread-{RECAP_CHANNEL_B}-{RECAP_ROOT_TS}": make_recap_unit(kind="thread", channel=RECAP_CHANNEL_B, owner_last_ts=RECAP_LAST_TS)})
        self.fetch(source="team-chat", place="local")
        self.assertNotIn("known_threads", self.chat.calls[0]["source"])

    def test_hands_the_adapter_no_known_threads_without_the_thread_reads_key(self):
        self.state = make_recap_state(units={f"thread-{RECAP_CHANNEL_B}-{RECAP_ROOT_TS}": make_recap_unit(kind="thread", channel=RECAP_CHANNEL_B, owner_last_ts=RECAP_LAST_TS)})
        self.fetch(source="team-chat", place="local")
        self.assertNotIn("known_threads", self.chat.calls[0]["source"])

    def test_replaces_the_known_threads_written_in_the_config_of_a_source(self):
        self.since()
        self.config["routines"][ROUTINE]["sources"]["team-chat"]["known_threads"] = [{"channel": "junk"}]
        self.fetch(source="team-chat", place="local")
        self.assertEqual(self.chat.calls[0]["source"]["known_threads"], [])

    def test_hands_a_document_source_no_rereads(self):
        source = {"provider": "docs", "page_id": "page-1"}
        self.assertEqual(collect.state_options(self.state, roles.RECAP_ENGINE, "document_store", source, "sources-page"), {})

    def test_hands_a_source_without_searches_no_rereads(self):
        del self.config["routines"][ROUTINE]["sources"]["team-chat"]["searches"]
        self.config["routines"][ROUTINE]["sources"]["team-chat"]["channels"] = [CHAT_CHANNEL]
        self.fetch(source="team-chat", place="local")
        self.assertNotIn("rereads", self.chat.calls[0]["source"])

    def test_replaces_the_rereads_written_in_the_config_of_a_source(self):
        self.config["routines"][ROUTINE]["sources"]["team-chat"]["rereads"] = [{"channel": "junk"}]
        self.state = make_recap_state(units={})
        self.fetch(source="team-chat", place="local")
        self.assertEqual(self.chat.calls[0]["source"]["rereads"], [])

    def test_drops_the_rereads_written_in_the_config_of_a_watch_source(self):
        del self.config["routines"][ROUTINE]["engine"]
        self.config["routines"][ROUTINE]["sources"]["team-chat"]["rereads"] = [{"channel": "junk"}]
        self.state = make_state()
        self.window = make_window()
        self.fetch(source="team-chat", place="local")
        self.assertNotIn("rereads", self.chat.calls[0]["source"])

    def test_hands_the_adapter_no_stored_cursor(self):
        self.fetch(source="team-chat", place="local")
        self.assertIsNone(self.chat.calls[0]["cursor"])

    def test_keeps_the_failed_entries_of_the_adapter(self):
        failed = {"search:dms": {"status": "failed", "reason": "page cap: 3 page(s) read"}}
        self.chat.result = {**NO_CHAT_RESULT, "entries": failed}
        self.fetch(source="team-chat", place="local")
        self.assertEqual(self.collection()["entries"], failed)


class RecapStateTest(RecapChatCase):
    def test_reads_a_recap_state_and_window(self):
        self.assertEqual(self.fetch(source="team-chat", place="local")[0], 0)

    def test_rejects_a_tribe_state_for_a_recap_routine_naming_the_schema(self):
        self.state = make_tribe_state()
        code, _, err = self.fetch(source="team-chat", place="local")
        self.assertEqual((code, "state: " in err), (3, True))

    def test_rejects_an_invalid_recap_state_naming_the_key_path(self):
        self.state["units"][f"dm-{RECAP_CHANNEL_A}"]["status"] = "done"
        code, _, err = self.fetch(source="team-chat", place="local")
        self.assertEqual((code, f"units.dm-{RECAP_CHANNEL_A}.status" in err), (3, True))

    def test_rejects_a_recap_state_for_a_watch_routine(self):
        del self.config["routines"][ROUTINE]["engine"]
        self.window = make_window()
        code, _, err = self.fetch(source="team-chat", place="local")
        self.assertEqual((code, "state: expected schema 2 at schema" in err), (3, True))

    def test_rejects_a_window_without_the_limit_key(self):
        del self.window["limited"]
        code, _, err = self.fetch(source="team-chat", place="local")
        self.assertEqual((code, "window: " in err and "limited" in err), (3, True))

    def test_rejects_a_tribe_window_for_a_recap_routine(self):
        self.window = make_window()
        self.assertEqual(self.fetch(source="team-chat", place="local")[0], 3)


class WeeklyCollectTest(RecapChatCase):
    def setUp(self):
        super().setUp()
        routine = self.config["routines"][ROUTINE]
        for key in ("groups", "announcement", "window", "history"):
            routine.pop(key, None)
        routine.update(engine="weekly", exclude={"channels": []})
        self.state = {"schema": "weekly-1", "digest": ROUTINE, "last_run": None}
        self.window = {"from_ts": WINDOW_END - 3600, "to_ts": WINDOW_END, "week_start": "2025-10-06", "report_only": False}

    def test_reads_a_weekly_state_and_window(self):
        self.assertEqual(self.fetch(source="team-chat", place="local")[0], 0)

    def test_rejects_a_recap_state_for_a_weekly_routine(self):
        self.state = make_recap_state()
        code, _, err = self.fetch(source="team-chat", place="local")
        self.assertEqual((code, "state: " in err), (3, True))


class TribePreviousPageTest(RelayTestCase):
    def setUp(self):
        super().setUp()
        self.config["routines"][ROUTINE]["engine"] = "tribe"
        self.config["routines"][ROUTINE].update(publication_values())
        self.config["routines"][ROUTINE]["sources"]["sources-page"] = {
            "provider": "docs",
            "transport": {"cloud": "mcp", "local": "api"},
            "page_from_state": "previous_page",
        }
        self.state = make_tribe_state()
        self.previous = self.state["run"]["previous_page"]["id"]

    def without_previous_page(self):
        self.state["run"]["previous_page"] = None

    def test_reads_the_previous_digest_page_over_the_api_transport(self):
        self.fetch(source="sources-page", place="local")
        self.assertEqual(self.doc.calls[0]["source"]["page_id"], self.previous)

    def test_reads_the_previous_digest_page_when_planning(self):
        self.plan()
        self.assertEqual(self.doc.plans[0]["source"]["page_id"], self.previous)

    def test_reads_the_previous_digest_page_when_parsing(self):
        self.loop()
        self.parse()
        self.assertEqual(self.doc.parses[0]["source"]["page_id"], self.previous)

    def test_a_run_with_no_previous_page_marks_the_source_not_read(self):
        self.without_previous_page()
        self.fetch(source="sources-page", place="local")
        collection = self.collection()
        self.assertEqual((collection["read"], collection["reason"], collection["records"], collection["entries"]), (False, collect.NO_PREVIOUS_PAGE, {"pages": []}, {}))

    def test_a_run_with_no_previous_page_does_not_call_the_adapter(self):
        self.without_previous_page()
        self.fetch(source="sources-page", place="local")
        self.assertEqual((self.doc.clients, self.doc.calls), ([], []))

    def test_a_planned_run_with_no_previous_page_lists_no_call_and_writes_no_planned_file(self):
        self.without_previous_page()
        self.plan()
        self.assertEqual((self.plan_doc(), os.path.exists(os.path.join(self.path(RESPONSES), "planned.json"))), ({"done": True, "partial": None, "calls": []}, False))

    def test_a_skipped_source_keeps_its_stored_cursor(self):
        self.without_previous_page()
        self.state["cursors"]["sources-page"] = {"pages": {page_id(): UTC_EDIT}}
        self.fetch(source="sources-page", place="local")
        self.assertEqual(self.collection()["cursor"], {"pages": {page_id(): UTC_EDIT}})

    def test_a_skipped_source_needs_no_credential(self):
        self.without_previous_page()
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.fetch(source="sources-page", place="local")[0], 0)

    def test_a_run_with_no_previous_page_plans_no_call(self):
        self.without_previous_page()
        self.assertEqual(self.plan()[0], 0)
        self.assertEqual((self.plan_doc(), self.doc.plans), ({"done": True, "partial": None, "calls": []}, []))

    def test_a_run_with_no_previous_page_parses_a_source_not_read(self):
        self.without_previous_page()
        self.plan()
        self.assertEqual(self.parse()[0], 0)
        collection = self.collection()
        self.assertEqual((collection["read"], collection["reason"], self.doc.parses), (False, collect.NO_PREVIOUS_PAGE, []))

    def test_rejects_the_option_for_a_watch_routine_naming_the_key_path(self):
        del self.config["routines"][ROUTINE]["engine"]
        self.state = make_state()
        code, _, err = self.fetch(source="sources-page", place="local")
        self.assertEqual((code, "routines.prod-watch.sources.sources-page.page_from_state" in err), (2, True))

    def test_rejects_the_option_next_to_a_page_id_naming_the_key_path(self):
        self.config["routines"][ROUTINE]["sources"]["sources-page"]["page_id"] = page_id()
        code, _, err = self.fetch(source="sources-page", place="local")
        self.assertEqual((code, "routines.prod-watch.sources.sources-page" in err), (2, True))


class SavedResultUnwrapTest(RelayTestCase):
    def blocks(self, *texts):
        return json.dumps([{"type": "text", "text": text} for text in texts])

    def plan_sees(self, saved):
        self.plan()
        self.respond("sources-page-1", saved)
        self.plan()
        return self.doc.plans[1]["responses"]["sources-page-1"]

    def parse_sees(self, saved):
        self.plan()
        self.respond("sources-page-1", saved)
        self.plan()
        self.respond("sources-page-2")
        self.plan()
        self.parse()
        return self.doc.parses[0]["responses"]["sources-page-1"]

    def test_plan_hands_over_the_text_of_a_single_text_block(self):
        self.assertEqual(self.plan_sees(self.blocks('{"a": 1}')), '{"a": 1}')

    def test_parse_hands_over_the_text_of_a_single_text_block(self):
        self.assertEqual(self.parse_sees(self.blocks('{"a": 1}')), '{"a": 1}')

    def test_joins_the_texts_of_several_text_blocks_in_order(self):
        self.assertEqual(self.parse_sees(self.blocks('{"a": ', "1}")), '{"a": 1}')

    def test_unwraps_a_block_that_carries_other_keys(self):
        saved = json.dumps([{"type": "text", "text": "body", "annotations": None}])
        self.assertEqual(self.parse_sees(saved), "body")

    def test_unwraps_the_text_of_a_json_array_result(self):
        self.assertEqual(self.parse_sees(self.blocks("[1, 2]")), "[1, 2]")

    def test_keeps_a_raw_response_unchanged(self):
        self.assertEqual(self.parse_sees('{"a": 1}'), '{"a": 1}')

    def test_keeps_a_list_with_a_block_of_another_type_unchanged(self):
        saved = json.dumps([{"type": "text", "text": "a"}, {"type": "image", "data": "b"}])
        self.assertEqual(self.parse_sees(saved), saved)

    def test_keeps_a_list_with_a_block_whose_text_is_not_a_string_unchanged(self):
        saved = json.dumps([{"type": "text", "text": 7}])
        self.assertEqual(self.parse_sees(saved), saved)

    def test_keeps_a_list_with_a_block_without_text_unchanged(self):
        saved = json.dumps([{"type": "text"}])
        self.assertEqual(self.parse_sees(saved), saved)

    def test_keeps_a_list_of_strings_unchanged(self):
        self.assertEqual(self.parse_sees('["text"]'), '["text"]')

    def test_keeps_a_list_with_an_item_that_is_not_an_object_unchanged(self):
        saved = json.dumps([{"type": "text", "text": "a"}, "b"])
        self.assertEqual(self.parse_sees(saved), saved)

    def test_keeps_an_empty_list_unchanged(self):
        self.assertEqual(self.parse_sees("[]"), "[]")

    def test_keeps_a_single_block_object_unchanged(self):
        saved = json.dumps({"type": "text", "text": "a"})
        self.assertEqual(self.parse_sees(saved), saved)

    def test_keeps_text_that_looks_like_a_list_but_is_not_json_unchanged(self):
        self.assertEqual(self.parse_sees("[not json"), "[not json")

    def test_keeps_a_deeply_nested_list_unchanged(self):
        saved = "[" * 200000
        self.assertEqual(self.parse_sees(saved), saved)


class WrappedResponseParityTest(RelayTestCase):
    PAGE_SOURCE = "wiki-page"
    METRICS_SOURCE = "dd-metrics"

    def setUp(self):
        super().setUp()
        sources = self.config["routines"][ROUTINE]["sources"]
        self.config["providers"]["wiki"] = {"adapter": "notion", "mcp": {"connectors": {"cloud": "wiki-cloud", "local": "wiki-local"}}}
        self.config["providers"]["dd"] = {"adapter": "datadog", "mcp": {"connectors": {"cloud": "dd-cloud", "local": "dd-local"}}}
        sources[self.PAGE_SOURCE] = {"provider": "wiki", "transport": {"cloud": "mcp", "local": "mcp"}, "page_id": "sources-page"}
        sources[self.METRICS_SOURCE] = {
            "provider": "dd", "transport": {"cloud": "mcp", "local": "mcp"}, "kind": "metrics", "scope_filter": "",
        }
        self.config["routines"][ROUTINE]["query_pack"].append(
            entry("checkout-p95", self.METRICS_SOURCE, query="avg:checkout.p95{*}", read="scalar", aggregator="avg")
        )

    def parsed(self, source, saved):
        self.plan(source)
        self.respond(f"{source}-1", saved)
        self.plan(source)
        self.parse(source)
        return self.collection()

    def tool_result(self):
        with open(os.path.join(HERE, "providers", "fixtures", "notion", "fetch_page.json"), encoding="utf-8") as handle:
            return handle.read()

    def script_result(self):
        self.plan(self.METRICS_SOURCE)
        digest = self.calls_doc(self.METRICS_SOURCE)["calls"][f"{self.METRICS_SOURCE}-1"]
        with open(os.path.join(HERE, "providers", "fixtures", "datadog", "relay_scalar.json"), encoding="utf-8") as handle:
            payload = handle.read()
        value = {"payload": payload, "checksum": roles.fnv1a32(payload), "digest": digest}
        return json.dumps({"success": True, "outcome": "success", "value": value})

    def wrap(self, text):
        return json.dumps([{"type": "text", "text": text}])

    def test_a_wrapped_tool_call_result_parses_like_the_raw_one(self):
        raw = self.parsed(self.PAGE_SOURCE, self.tool_result())
        wrapped = self.parsed(self.PAGE_SOURCE, self.wrap(self.tool_result()))
        self.assertEqual((raw["read"], wrapped), (True, raw))

    def test_a_wrapped_connector_script_result_parses_like_the_raw_one(self):
        raw = self.parsed(self.METRICS_SOURCE, self.script_result())
        wrapped = self.parsed(self.METRICS_SOURCE, self.wrap(self.script_result()))
        self.assertEqual((raw["read"], wrapped), (True, raw))

    def test_a_wrapped_connector_script_result_keeps_its_value(self):
        wrapped = self.parsed(self.METRICS_SOURCE, self.wrap(self.script_result()))
        self.assertEqual(wrapped["records"]["metrics"][0]["value"], 42.5)

    def test_a_wrapped_connector_script_result_with_a_wrong_checksum_is_not_read(self):
        result = json.loads(self.script_result())
        result["value"]["checksum"] = roles.fnv1a32("other")
        collection = self.parsed(self.METRICS_SOURCE, self.wrap(json.dumps(result)))
        self.assertEqual((collection["read"], collection["reason"].endswith("payload checksum mismatch")), (False, True))

    def test_a_wrapped_connector_script_result_with_a_wrong_digest_is_not_read(self):
        result = json.loads(self.script_result())
        result["value"]["digest"] = roles.fnv1a32("other")
        collection = self.parsed(self.METRICS_SOURCE, self.wrap(json.dumps(result)))
        self.assertEqual((collection["read"], collection["reason"].endswith("plan digest mismatch")), (False, True))


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
            "calls": [
                {"id": "sources-page-1", "connector": "docs-cloud", "tool": "read-page", "arguments": {"page": 1}, "path": self.response_path("sources-page-1")}
            ],
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


class RelayCaptureTest(RelayTestCase):
    TOOL = "mcp__docs-cloud__read-page"

    def at(self, offset):
        self.relay_clock.now_ns = RELAY_START_NS + offset

    def capture(self, page, text, offset, tool=None, arguments=None):
        at = RELAY_START_NS + offset
        document = {"tool_name": tool or self.TOOL, "arguments": {"page": page} if arguments is None else arguments, "text": text, "captured_at_ns": at}
        os.makedirs(self.relay_dir, mode=0o700, exist_ok=True)
        relay_capture.write_capture(self.relay_dir, f"{at}-toolu_{page}.json", document)

    def plan_at(self, offset, source="sources-page", place="cloud"):
        self.at(offset)
        self.assertEqual(self.plan(source, place)[0], 0)

    def plan_err_at(self, offset, source="sources-page", place="cloud"):
        self.at(offset)
        code, out, err = self.plan(source, place)
        self.assertEqual((code, out), (0, ""))
        return err

    def write_planned(self, *call_ids):
        os.makedirs(self.path(RESPONSES), exist_ok=True)
        with open(os.path.join(self.path(RESPONSES), "planned.json"), "wb") as handle:
            handle.write(state.dump({"planned": {call_id: RELAY_START_NS for call_id in call_ids}}))

    def list_calls(self, *calls):
        self.doc.plan_result = {"done": False, "partial": None, "calls": list(calls)}

    def with_arguments(self, page, arguments):
        return {**planned_call("sources-page", page), "arguments": arguments}

    def saved(self, call_id):
        with open(self.response_path(call_id), "rb") as handle:
            return handle.read()

    def planned_doc(self):
        with open(os.path.join(self.path(RESPONSES), "planned.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def kept_captures(self):
        return sorted(os.listdir(self.relay_dir))

    def test_saves_the_result_of_a_planned_call_captured_after_the_listing(self):
        self.plan_at(0)
        self.capture(1, "page one", 1)
        self.plan_at(2)
        self.assertEqual(self.saved("sources-page-1"), b"page one")

    def test_asks_the_next_call_once_the_captured_result_is_saved(self):
        self.plan_at(0)
        self.capture(1, "page one", 1)
        self.plan_at(2)
        self.assertEqual((self.plan_doc()["done"], self.call_ids()), (False, ["sources-page-2"]))

    def test_hands_the_captured_text_to_the_adapter_unchanged(self):
        text = '{"note": "caf\u00e9 \\ud800 ' + chr(0x1F600) + '"}\r\n  '
        self.plan_at(0)
        self.capture(1, text, 1)
        self.plan_at(2)
        self.assertEqual((self.saved("sources-page-1"), self.doc.plans[-1]["responses"]), (text.encode("utf-8"), {"sources-page-1": text}))

    def test_deletes_the_capture_it_took(self):
        self.plan_at(0)
        self.capture(1, "page one", 1)
        self.plan_at(2)
        self.assertEqual(self.kept_captures(), [])

    def test_walks_to_done_through_captures_only(self):
        self.doc.pages = 4
        for page in range(1, 5):
            self.plan_at(10 * page)
            self.capture(page, f"page {page}", 10 * page + 1)
        self.plan_at(100)
        self.assertEqual(
            (self.plan_doc(), [self.saved(f"sources-page-{page}") for page in range(1, 5)]),
            ({"done": True, "partial": None, "calls": []}, [f"page {page}".encode() for page in range(1, 5)]),
        )

    def test_chains_the_pick_ups_of_calls_planned_in_earlier_runs(self):
        os.makedirs(self.path(RESPONSES))
        planned = {"planned": {"sources-page-1": RELAY_START_NS, "sources-page-2": RELAY_START_NS}}
        with open(os.path.join(self.path(RESPONSES), "planned.json"), "wb") as handle:
            handle.write(state.dump(planned))
        self.capture(1, "page one", 1)
        self.capture(2, "page two", 1)
        self.plan_at(2)
        self.assertEqual((self.plan_doc(), self.saved("sources-page-2")), ({"done": True, "partial": None, "calls": []}, b"page two"))

    def test_the_walk_through_captures_parses_into_a_collection(self):
        for page in (1, 2):
            self.plan_at(10 * page)
            self.capture(page, "{}", 10 * page + 1)
        self.plan_at(100)
        self.parse()
        self.assertEqual(self.collection()["read"], True)

    def test_records_every_listed_call_across_a_walk_through_captures(self):
        for page in (1, 2):
            self.plan_at(10 * page)
            self.capture(page, "{}", 10 * page + 1)
        self.plan_at(100)
        expected = {"calls": {"sources-page-1": digest(1), "sources-page-2": digest(2)}, "done": True, "partial": None}
        self.assertEqual(self.calls_doc(), expected)

    def test_records_the_time_each_call_was_first_planned(self):
        self.plan_at(0)
        self.capture(1, "page one", 1)
        self.plan_at(5)
        self.assertEqual(self.planned_doc(), {"planned": {"sources-page-1": RELAY_START_NS, "sources-page-2": RELAY_START_NS + 5}})

    def test_the_planned_file_is_canonical_json(self):
        self.plan_at(0)
        with open(os.path.join(self.path(RESPONSES), "planned.json"), "rb") as handle:
            raw = handle.read()
        self.assertEqual(raw, state.dump(json.loads(raw)))

    def test_keeps_the_first_planned_time_when_a_call_is_listed_again(self):
        self.plan_at(0)
        self.plan_at(5)
        self.assertEqual(self.planned_doc(), {"planned": {"sources-page-1": RELAY_START_NS}})

    def test_ignores_a_capture_taken_before_the_call_was_planned(self):
        self.capture(1, "stale", -1)
        self.plan_at(0)
        self.plan_at(5)
        self.assertEqual((self.call_ids(), os.path.exists(self.response_path("sources-page-1"))), (["sources-page-1"], False))

    def test_picks_up_a_capture_taken_at_the_planned_time(self):
        self.plan_at(0)
        self.capture(1, "page one", 0)
        self.plan_at(5)
        self.assertEqual(self.saved("sources-page-1"), b"page one")

    def test_the_first_listing_of_a_call_takes_nothing(self):
        self.capture(1, "early", 3)
        self.plan_at(0)
        self.assertEqual((self.call_ids(), os.path.exists(self.response_path("sources-page-1"))), (["sources-page-1"], False))

    def test_lists_the_same_call_again_without_a_capture(self):
        self.plan_at(0)
        self.plan_at(5)
        self.assertEqual((self.plan_doc()["done"], self.call_ids()), (False, ["sources-page-1"]))

    def test_a_result_saved_by_hand_still_moves_the_plan_on(self):
        self.plan_at(0)
        self.plan_at(5)
        self.respond("sources-page-1")
        self.plan_at(6)
        self.assertEqual(self.call_ids(), ["sources-page-2"])

    def test_a_result_saved_by_hand_wins_over_a_later_capture(self):
        self.plan_at(0)
        self.respond("sources-page-1", "by hand")
        self.capture(1, "captured", 1)
        self.plan_at(2)
        self.assertEqual((self.saved("sources-page-1"), self.call_ids()), (b"by hand", ["sources-page-2"]))

    def test_ignores_a_capture_with_other_arguments(self):
        self.plan_at(0)
        self.capture(1, "other page", 1, arguments={"page": 2})
        self.plan_at(2)
        self.assertEqual((self.call_ids(), os.path.exists(self.response_path("sources-page-1"))), (["sources-page-1"], False))

    def test_ignores_a_capture_with_an_extra_argument(self):
        self.plan_at(0)
        self.capture(1, "wider", 1, arguments={"page": 1, "size": 5})
        self.plan_at(2)
        self.assertEqual(self.call_ids(), ["sources-page-1"])

    def test_ignores_a_capture_of_another_connector(self):
        self.plan_at(0)
        self.capture(1, "elsewhere", 1, tool="mcp__other__read-page")
        self.plan_at(2)
        self.assertEqual(self.call_ids(), ["sources-page-1"])

    def test_ignores_a_capture_of_another_tool(self):
        self.plan_at(0)
        self.capture(1, "elsewhere", 1, tool="mcp__docs-cloud__list-pages")
        self.plan_at(2)
        self.assertEqual(self.call_ids(), ["sources-page-1"])

    def test_keeps_a_capture_it_did_not_match(self):
        self.plan_at(0)
        self.capture(1, "other page", 1, arguments={"page": 2})
        self.plan_at(2)
        self.assertEqual(len(self.kept_captures()), 1)

    def test_takes_the_newest_of_two_captures_of_a_call(self):
        self.plan_at(0)
        self.capture(1, "first try", 1)
        self.relay_clock.now_ns = RELAY_START_NS + 2
        relay_capture.write_capture(
            self.relay_dir, f"{RELAY_START_NS + 2}-toolu_x.json",
            {"tool_name": self.TOOL, "arguments": {"page": 1}, "text": "second try", "captured_at_ns": RELAY_START_NS + 2},
        )
        self.plan_at(3)
        self.assertEqual((self.saved("sources-page-1"), self.kept_captures()), (b"second try", []))

    def test_takes_the_connector_of_the_place(self):
        self.plan_at(0, source="metrics", place="local")
        self.capture(1, "metric one", 1, tool="mcp__obs-local__read-page")
        self.plan_at(2, source="metrics", place="local")
        self.assertEqual((self.saved("metrics-1"), self.call_ids()), (b"metric one", ["metrics-2"]))

    def test_leaves_a_capture_of_the_connector_of_another_place(self):
        self.plan_at(0, source="metrics", place="local")
        self.capture(1, "metric one", 1, tool="mcp__obs-cloud__read-page")
        self.plan_at(2, source="metrics", place="local")
        self.assertEqual(self.call_ids(), ["metrics-1"])

    def test_reads_no_capture_folder_that_does_not_exist(self):
        shutil.rmtree(self.relay_dir)
        self.plan_at(0)
        self.plan_at(5)
        self.assertEqual((self.call_ids(), os.path.exists(self.relay_dir)), (["sources-page-1"], False))

    def test_reads_the_folder_the_variable_names(self):
        elsewhere = self.path("elsewhere")
        with mock.patch.dict(os.environ, {relay_capture.ENV_DIR: elsewhere}):
            self.plan_at(0)
            self.relay_dir = elsewhere
            self.capture(1, "page one", 1)
            self.plan_at(2)
        self.assertEqual(self.saved("sources-page-1"), b"page one")

    def test_a_planned_file_that_is_not_valid_exits_2_naming_it(self):
        self.plan_at(0)
        with open(os.path.join(self.path(RESPONSES), "planned.json"), "w", encoding="utf-8") as handle:
            handle.write('{"planned": {"sources-page-1": "soon"}}')
        code, _, err = self.plan()
        self.assertEqual((code, "planned" in err), (3, True))

    def test_a_relisted_call_with_a_near_capture_prints_one_mismatch_line(self):
        self.plan_at(0)
        self.capture(1, "other page", 1, arguments={"page": 2})
        self.assertEqual(self.plan_err_at(2), "relay capture mismatch sources-page-1: page changed\n")

    def test_the_mismatch_line_names_the_path_and_the_lengths_but_no_value(self):
        self.list_calls(self.with_arguments(1, {"query": "alpha beta"}))
        self.write_planned("sources-page-1")
        self.capture(1, "result", 1, arguments={"query": "alpha gamma"})
        err = self.plan_err_at(2)
        self.assertEqual((err, "alpha" in err), ("relay capture mismatch sources-page-1: query changed at char 6 (planned 10, called 11)\n", False))

    def test_the_plan_still_lists_the_call_again_after_a_mismatch(self):
        self.plan_at(0)
        self.capture(1, "other page", 1, arguments={"page": 2})
        self.plan_at(2)
        self.assertEqual((self.plan_doc()["done"], self.call_ids()), (False, ["sources-page-1"]))

    def test_keeps_the_near_capture_it_reported(self):
        self.plan_at(0)
        self.capture(1, "other page", 1, arguments={"page": 2})
        self.plan_at(2)
        self.assertEqual(len(self.kept_captures()), 1)

    def test_prints_the_line_again_on_the_next_plan_command(self):
        self.plan_at(0)
        self.capture(1, "other page", 1, arguments={"page": 2})
        self.assertEqual([self.plan_err_at(2), self.plan_err_at(3)], ["relay capture mismatch sources-page-1: page changed\n"] * 2)

    def test_prints_one_line_even_when_the_loop_picks_up_other_calls(self):
        self.write_planned("sources-page-1", "sources-page-2")
        self.list_calls(planned_call("sources-page", 1), planned_call("sources-page", 2))
        self.capture(1, "page one", 1)
        self.capture(2, "other page", 1, arguments={"page": 22})
        err = self.plan_err_at(2)
        self.assertEqual((err, self.saved("sources-page-1"), len(self.doc.plans)), ("relay capture mismatch sources-page-2: page changed\n", b"page one", 2))

    def test_prints_one_line_for_each_relisted_call_in_call_order(self):
        self.write_planned("sources-page-1", "sources-page-2")
        self.list_calls(planned_call("sources-page", 1), planned_call("sources-page", 2))
        self.capture(2, "second", 1, arguments={"page": 22})
        self.capture(1, "first", 1, arguments={"page": 11})
        expected = "relay capture mismatch sources-page-1: page changed\nrelay capture mismatch sources-page-2: page changed\n"
        self.assertEqual(self.plan_err_at(2), expected)

    def test_prints_no_line_for_a_call_printed_for_the_first_time(self):
        self.capture(1, "early", 3, arguments={"page": 9})
        self.assertEqual(self.plan_err_at(0), "")

    def test_prints_no_line_when_no_capture_of_the_tool_exists(self):
        self.plan_at(0)
        self.capture(1, "elsewhere", 1, tool="mcp__other__read-page", arguments={"page": 2})
        self.capture(1, "another tool", 2, tool="mcp__docs-cloud__list-pages", arguments={"page": 2})
        self.assertEqual(self.plan_err_at(3), "")

    def test_prints_no_line_when_there_is_no_capture_folder(self):
        self.plan_at(0)
        shutil.rmtree(self.relay_dir)
        self.assertEqual(self.plan_err_at(2), "")

    def test_prints_no_line_for_a_capture_taken_before_the_call_was_planned(self):
        self.capture(1, "stale", -1, arguments={"page": 2})
        self.plan_at(0)
        self.assertEqual(self.plan_err_at(2), "")

    def test_prints_no_line_for_a_call_whose_capture_matched(self):
        self.plan_at(0)
        self.capture(1, "page one", 1)
        self.assertEqual(self.plan_err_at(2), "")

    def test_prints_no_line_for_a_relisted_call_without_any_capture(self):
        self.plan_at(0)
        self.assertEqual(self.plan_err_at(2), "")

    def test_names_at_most_five_paths_and_counts_the_rest(self):
        keys = "abcdefg"
        self.list_calls(self.with_arguments(1, {key: 1 for key in keys}))
        self.write_planned("sources-page-1")
        self.capture(1, "result", 1, arguments={key: 2 for key in keys})
        expected = "relay capture mismatch sources-page-1: a changed; b changed; c changed; d changed; e changed; +2 more\n"
        self.assertEqual(self.plan_err_at(2), expected)

    def test_names_exactly_five_paths_without_a_count(self):
        keys = "abcde"
        self.list_calls(self.with_arguments(1, {key: 1 for key in keys}))
        self.write_planned("sources-page-1")
        self.capture(1, "result", 1, arguments={key: 2 for key in keys})
        self.assertEqual(self.plan_err_at(2), "relay capture mismatch sources-page-1: a changed; b changed; c changed; d changed; e changed\n")

    def test_counts_a_single_path_over_the_cap(self):
        keys = "abcdef"
        self.list_calls(self.with_arguments(1, {key: 1 for key in keys}))
        self.write_planned("sources-page-1")
        self.capture(1, "result", 1, arguments={key: 2 for key in keys})
        self.assertTrue(self.plan_err_at(2).endswith("e changed; +1 more\n"))

    def test_keeps_the_line_on_one_line_when_a_key_holds_a_line_break(self):
        self.plan_at(0)
        self.capture(1, "result", 1, arguments={"page": 1, "pa\nge": 2})
        self.assertEqual(self.plan_err_at(2), "relay capture mismatch sources-page-1: pa ge extra\n")


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

    def test_ends_at_the_call_cap_of_the_source(self):
        self.config["routines"][ROUTINE]["sources"]["sources-page"]["call_cap"] = 3
        self.doc.pages = 4
        self.fill(3)
        self.assertEqual(self.plan_doc(), {"done": True, "partial": "call cap", "calls": []})

    def test_keeps_listing_calls_past_the_default_cap_when_the_source_raises_it(self):
        self.config["routines"][ROUTINE]["sources"]["sources-page"]["call_cap"] = collect.CALL_CAP + 10
        self.doc.pages = collect.CALL_CAP + 1
        self.fill(collect.CALL_CAP)
        self.assertEqual(self.call_ids(), [f"sources-page-{collect.CALL_CAP + 1}"])

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
            "skipped": [],
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
