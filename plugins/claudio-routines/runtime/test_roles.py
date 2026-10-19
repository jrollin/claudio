import json
import unittest

import roles
import state
from support import publication_values

ROUTINE = "prod-watch"
ADAPTER_ROLES = {
    "obsvendor": "observability",
    "docvendor": "document_store",
    "chatvendor": "chat",
    "codevendor": "code_host",
    "trackervendor": "issue_tracker",
}
WINDOW_END = 1_780_000_000
MONITOR_ID = str(4000 + 2)
OTHER_MONITOR_ID = str(4000 + 3)
UTC_EDIT = "2026-10-01T08:00:00.000Z"


def role_of(adapter):
    if adapter not in ADAPTER_ROLES:
        raise ValueError(f"unknown adapter {adapter}")
    return ADAPTER_ROLES[adapter]


def page_id():
    return "page-" + "ab" * 4


def make_pack():
    return [
        {
            "key": "monitor-" + MONITOR_ID,
            "source": "monitors",
            "monitor": MONITOR_ID,
            "title": "API latency monitor",
            "link": "https://obs.example.test/monitors/" + MONITOR_ID,
            "rule": "Alert is High and now; Warn is Medium and watch.",
            "schedule": "every_run",
        },
        {
            "key": "error-rate",
            "source": "metrics",
            "query": "sum:errors{env:prod}",
            "read": "scalar",
            "aggregator": "avg",
            "title": "Error rate",
            "link": "https://obs.example.test/metrics/error-rate",
            "rule": "Open above 5 errors per second, Medium and watch.",
            "schedule": "every_run",
        },
        {
            "key": "top-endpoints",
            "source": "metrics",
            "query": "sum:requests{env:prod} by {endpoint}",
            "read": "top",
            "aggregator": "sum",
            "top": 3,
            "lookback_days": 7,
            "title": "Busiest endpoints",
            "link": "https://obs.example.test/metrics/top-endpoints",
            "rule": "Open an endpoint that doubled over the week, Low and within months.",
            "schedule": "daily",
        },
        {
            "key": "hourly-queue",
            "source": "metrics",
            "query": "max:queue.depth{env:prod}",
            "read": "hourly",
            "aggregator": "max",
            "excluded_hours": [0, 1, 23],
            "title": "Queue depth",
            "link": "https://obs.example.test/metrics/hourly-queue",
            "rule": "Open below 100 in any hour not excluded, Medium and watch.",
            "schedule": "every_run",
        },
    ]


def make_rules():
    return ["A monitor flapping more than 3 times per hour is Medium.", "A discovered monitor in No Data is Low."]


def make_config():
    return {
        "timezone": "Europe/Paris",
        "places": {
            "cloud": {"runtime_dir": "/opt/routines/claudio-runtime", "state_dir": "/srv/private-config"},
            "local": {"runtime_dir": "/opt/local/claudio-runtime", "state_dir": "/srv/local/private-config"},
        },
        "providers": {
            "obs": {
                "adapter": "obsvendor",
                "api": {
                    "base_url": "https://api.obs.example.test",
                    "credentials": {"api_key": "OBS_API_KEY", "app_key": "OBS_APP_KEY"},
                },
                "mcp": {"connectors": {"cloud": "obs-cloud", "local": "obs-local"}},
            },
            "docs": {
                "adapter": "docvendor",
                "api": {"base_url": "https://api.docs.example.test/v1", "credentials": {"token": "DOCS_TOKEN"}},
                "mcp": {"connectors": {"cloud": "docs-cloud", "local": "docs-local"}},
            },
            "chat": {
                "adapter": "chatvendor",
                "mcp": {"connectors": {"cloud": "chat-cloud", "local": "chat-local"}},
            },
            "code": {
                "adapter": "codevendor",
                "api": {"base_url": "https://api.code.example.test", "credentials": {"token": "CODE_TOKEN"}},
            },
        },
        "routines": {
            ROUTINE: {
                "template": "prod-watch",
                "cron": "0 7 * * *",
                "sources": {
                    "monitors": {
                        "provider": "obs",
                        "transport": {"cloud": "mcp", "local": "api"},
                        "kind": "monitors",
                        "scope_filter": "env:prod",
                        "discovery_query": "status:(alert OR warn OR no data) env:prod",
                    },
                    "metrics": {
                        "provider": "obs",
                        "transport": {"cloud": "api", "local": "api"},
                        "kind": "metrics",
                        "scope_filter": "",
                    },
                    "sources-page": {
                        "provider": "docs",
                        "transport": {"cloud": "mcp", "local": "api"},
                        "page_id": page_id(),
                    },
                    "chat": {
                        "provider": "chat",
                        "transport": {"cloud": "mcp", "local": "mcp"},
                        "channels": ["chan-alerts", "chan-deploys"],
                    },
                    "code": {
                        "provider": "code",
                        "transport": {"cloud": "api", "local": "api"},
                        "repos": ["acme/service", "acme/web.app"],
                        "query": "is:open",
                    },
                },
                "query_pack": make_pack(),
                "rules": make_rules(),
            }
        },
    }


def routine_sources(config):
    return config["routines"][ROUTINE]["sources"]


def pack_sources():
    return {
        "monitors": {"role": "observability", "kind": "monitors", "scope_filter": ""},
        "metrics": {"role": "observability", "kind": "metrics", "scope_filter": ""},
        "chat": {"role": "chat", "channels": ["chan-alerts"]},
    }


def monitors_records():
    return {
        "monitors": [
            {"id": MONITOR_ID, "name": "API latency", "state": "Alert", "priority": 2, "link": "https://obs.example.test/m/a"},
        ],
        "discovered": [
            {"id": OTHER_MONITOR_ID, "name": "Disk", "state": "No Data", "priority": None, "link": "https://obs.example.test/m/b"},
        ],
        "discovery": {"read": True, "reason": None},
        "transitions": [
            {"monitor": MONITOR_ID, "count": 2, "first_ts_ms": WINDOW_END * 1000 - 5000, "last_ts_ms": WINDOW_END * 1000},
        ],
    }


def monitors_cursor():
    return {"events_ts_ms": WINDOW_END * 1000, "monitors": {MONITOR_ID: "Alert"}}


def metrics_records():
    return {
        "metrics": [
            {
                "key": "error-rate",
                "value": 7.5,
                "hourly": [{"ts": WINDOW_END - 3600, "value": 7.5}, {"ts": WINDOW_END, "value": None}],
                "daily": [{"ts": WINDOW_END - 86400, "value": 6.0}, {"ts": WINDOW_END, "value": None}],
                "groups": [{"group": "endpoint:/a", "value": 3}, {"group": "endpoint:/b", "value": None}],
                "trend": [{"day": "2026-09-30", "value": 6.5}, {"day": "2026-10-01", "value": 7.5}],
                "trend_reason": None,
            }
        ]
    }


def pages_records():
    return {
        "pages": [
            {
                "id": page_id(),
                "title": "Sources",
                "last_edited": UTC_EDIT,
                "link": "https://docs.example.test/" + page_id().replace("-", ""),
                "blocks": [
                    {"type": "heading", "text": "Mutes", "rows": None, "checked": None},
                    {"type": "table", "text": "", "rows": [["key", "until"], ["error-rate", "2026-11-01"]], "checked": None},
                    {"type": "list", "text": "Ship the fix", "rows": None, "checked": True},
                ],
            }
        ]
    }


def pages_cursor():
    return {"pages": {page_id(): UTC_EDIT}}


def issues_records():
    return {
        "issues": [
            {
                "key": "PROJ-12",
                "title": "Checkout fails",
                "type": "Bug",
                "status": "In Progress",
                "priority": "High",
                "created": "2026-09-01T08:00:00Z",
                "updated": "2026-10-02T09:30:00Z",
                "link": "https://tracker.example.test/browse/PROJ-12",
                "in_open_sprint": True,
            },
            {
                "key": "PROJ-13",
                "title": "Tidy the backlog",
                "type": "Task",
                "status": "To Do",
                "priority": None,
                "created": "2026-09-02T08:00:00Z",
                "updated": "2026-10-01T09:30:00Z",
                "link": "https://tracker.example.test/browse/PROJ-13",
                "in_open_sprint": False,
            },
        ]
    }


def tracker_config():
    config = make_config()
    config["providers"]["tracker"] = {
        "adapter": "trackervendor",
        "api": {"base_url": "https://api.tracker.example.test", "credentials": {"email": "TRACKER_EMAIL", "token": "TRACKER_TOKEN"}},
    }
    routine_sources(config)["issues"] = {
        "provider": "tracker",
        "transport": {"cloud": "api", "local": "api"},
        "filter": "10042",
        "query": "labels = digest",
        "open_sprints": True,
    }
    return config


def messages_records():
    return {
        "messages": [
            {
                "channel": "chan-alerts",
                "ts": "1780000000.000100",
                "thread_ts": None,
                "author": "someone",
                "text": "deploy done",
                "link": "https://chat.example.test/archives/chan-alerts/p1",
            }
        ]
    }


def code_records():
    return {
        "pull_requests": [
            {
                "repo": "acme/service",
                "number": 42,
                "title": "Fix retry",
                "author": "dev",
                "state": "open",
                "draft": False,
                "created_at": "2026-10-01T08:00:00Z",
                "updated_at": "2026-10-02T08:00:00Z",
                "merged_at": None,
                "link": "https://code.example.test/acme/service/pull/42",
            }
        ],
        "issues": [
            {
                "repo": "acme/service",
                "number": 7,
                "title": "Flaky job",
                "author": "dev",
                "state": "closed",
                "created_at": "2026-09-01T08:00:00Z",
                "updated_at": "2026-10-02T09:00:00Z",
                "link": "https://code.example.test/acme/service/issues/7",
            }
        ],
    }


def make_collection(role, records, cursor, **overrides):
    doc = {
        "schema": 1,
        "source": "monitors",
        "role": role,
        "provider": "obs",
        "transport": "api",
        "place": "local",
        "window": {"from_ts": WINDOW_END - 3600, "to_ts": WINDOW_END},
        "read": True,
        "reason": None,
        "cursor": cursor,
        "records": records,
        "entries": {},
    }
    doc.update(overrides)
    return doc


def monitors_collection(**overrides):
    entries = {"monitor-" + MONITOR_ID: {"status": "ok", "reason": None}}
    doc = make_collection("observability", monitors_records(), monitors_cursor(), entries=entries)
    doc.update(overrides)
    return doc


def unread_collection(**overrides):
    reason = "credentials missing: OBS_API_KEY"
    fields = {
        "read": False,
        "reason": reason,
        "cursor": None,
        "records": {"monitors": [], "transitions": [], "discovered": [], "discovery": None},
        "entries": {
            "monitor-" + MONITOR_ID: {"status": "failed", "reason": reason},
            "monitor-" + OTHER_MONITOR_ID: {"status": "deferred", "reason": "known gap"},
        },
    }
    fields.update(overrides)
    doc = make_collection("observability", None, None)
    doc.update(fields)
    return doc


class ConfigCase(unittest.TestCase):
    def config_error(self, config, place="local", resolver=role_of):
        with self.assertRaises(roles.ConfigError) as caught:
            roles.validate_config(config, ROUTINE, place, resolver)
        return str(caught.exception)

    def assert_config_error(self, config, path, place="local"):
        self.assertEqual(self.config_error(config, place).partition(": ")[0], path)


class ValidateConfigTest(ConfigCase):
    def test_accepts_the_full_example_for_the_local_place(self):
        self.assertIsNone(roles.validate_config(make_config(), ROUTINE, "local", role_of))

    def test_accepts_the_full_example_for_the_cloud_place(self):
        self.assertIsNone(roles.validate_config(make_config(), ROUTINE, "cloud", role_of))

    def test_rejects_a_config_that_is_not_a_mapping(self):
        self.assert_config_error([], "config")

    def test_rejects_an_unknown_place(self):
        self.assert_config_error(make_config(), "places.moon", place="moon")

    def test_rejects_a_missing_places_block(self):
        config = make_config()
        del config["places"]
        self.assert_config_error(config, "places")

    def test_rejects_a_missing_block_for_the_place(self):
        config = make_config()
        del config["places"]["local"]
        self.assert_config_error(config, "places.local")

    def test_rejects_a_relative_runtime_dir(self):
        config = make_config()
        config["places"]["local"]["runtime_dir"] = "claudio-runtime"
        self.assert_config_error(config, "places.local.runtime_dir")

    def test_rejects_a_missing_state_dir(self):
        config = make_config()
        del config["places"]["local"]["state_dir"]
        self.assert_config_error(config, "places.local.state_dir")

    def test_checks_only_the_block_of_the_requested_place(self):
        config = make_config()
        del config["places"]["cloud"]
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_rejects_a_missing_providers_block(self):
        config = make_config()
        del config["providers"]
        self.assert_config_error(config, "providers")

    def test_rejects_an_unknown_routine(self):
        config = make_config()
        del config["routines"][ROUTINE]
        self.assert_config_error(config, "routines.prod-watch")

    def test_rejects_a_routine_without_sources(self):
        config = make_config()
        del config["routines"][ROUTINE]["sources"]
        self.assert_config_error(config, "routines.prod-watch.sources")

    def test_rejects_a_routine_with_empty_sources(self):
        config = make_config()
        config["routines"][ROUTINE]["sources"] = {}
        self.assert_config_error(config, "routines.prod-watch.sources")

    def test_accepts_a_source_name_with_digits_and_hyphens(self):
        config = make_config()
        routine_sources(config)["chat-2"] = routine_sources(config).pop("chat")
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_rejects_a_source_name_that_climbs_out_of_the_collections_dir(self):
        config = make_config()
        routine_sources(config)["../x"] = routine_sources(config).pop("chat")
        self.assert_config_error(config, "routines.prod-watch.sources.../x")

    def test_rejects_a_source_name_with_uppercase(self):
        config = make_config()
        routine_sources(config)["Upper"] = routine_sources(config).pop("chat")
        self.assert_config_error(config, "routines.prod-watch.sources.Upper")

    def test_rejects_a_source_name_with_an_underscore(self):
        config = make_config()
        routine_sources(config)["chat_alerts"] = routine_sources(config).pop("chat")
        self.assert_config_error(config, "routines.prod-watch.sources.chat_alerts")

    def test_rejects_a_source_that_is_not_a_mapping(self):
        config = make_config()
        routine_sources(config)["chat"] = "chat"
        self.assert_config_error(config, "routines.prod-watch.sources.chat")

    def test_rejects_a_source_without_provider(self):
        config = make_config()
        del routine_sources(config)["chat"]["provider"]
        self.assert_config_error(config, "routines.prod-watch.sources.chat.provider")

    def test_rejects_a_provider_absent_from_providers(self):
        config = make_config()
        routine_sources(config)["chat"]["provider"] = "nowhere"
        self.assert_config_error(config, "routines.prod-watch.sources.chat.provider")

    def test_rejects_a_local_transport_outside_api_and_mcp(self):
        config = make_config()
        routine_sources(config)["metrics"]["transport"]["local"] = "ftp"
        self.assert_config_error(config, "routines.prod-watch.sources.metrics.transport.local")

    def test_rejects_a_cloud_transport_outside_api_and_mcp_on_a_local_run(self):
        config = make_config()
        routine_sources(config)["metrics"]["transport"]["cloud"] = "auto"
        self.assert_config_error(config, "routines.prod-watch.sources.metrics.transport.cloud")

    def test_rejects_a_missing_transport_for_a_place(self):
        config = make_config()
        del routine_sources(config)["metrics"]["transport"]["cloud"]
        self.assert_config_error(config, "routines.prod-watch.sources.metrics.transport.cloud")

    def test_rejects_a_provider_without_adapter(self):
        config = make_config()
        del config["providers"]["chat"]["adapter"]
        self.assert_config_error(config, "providers.chat.adapter")

    def test_rejects_an_api_transport_without_api_block(self):
        config = make_config()
        routine_sources(config)["chat"]["transport"]["local"] = "api"
        self.assert_config_error(config, "providers.chat.api")

    def test_rejects_an_http_base_url(self):
        config = make_config()
        config["providers"]["code"]["api"]["base_url"] = "http://api.code.example.test"
        self.assert_config_error(config, "providers.code.api.base_url")

    def test_rejects_a_base_url_with_user_info(self):
        config = make_config()
        config["providers"]["code"]["api"]["base_url"] = "https://reader@api.code.example.test"
        self.assert_config_error(config, "providers.code.api.base_url")

    def test_never_echoes_a_password_carried_in_the_base_url(self):
        config = make_config()
        password = "pw" + "x" * 8
        config["providers"]["code"]["api"]["base_url"] = f"https://reader:{password}@api.code.example.test"
        self.assertNotIn(password, self.config_error(config))

    def test_rejects_a_base_url_with_a_query(self):
        config = make_config()
        config["providers"]["code"]["api"]["base_url"] = "https://api.code.example.test/?token=x"
        self.assert_config_error(config, "providers.code.api.base_url")

    def test_rejects_a_base_url_with_an_empty_query(self):
        config = make_config()
        config["providers"]["code"]["api"]["base_url"] = "https://api.code.example.test/?"
        self.assert_config_error(config, "providers.code.api.base_url")

    def test_rejects_a_base_url_with_a_fragment(self):
        config = make_config()
        config["providers"]["code"]["api"]["base_url"] = "https://api.code.example.test/#top"
        self.assert_config_error(config, "providers.code.api.base_url")

    def test_rejects_a_base_url_without_host(self):
        config = make_config()
        config["providers"]["code"]["api"]["base_url"] = "https:///v1"
        self.assert_config_error(config, "providers.code.api.base_url")

    def test_rejects_a_base_url_with_an_invalid_port(self):
        config = make_config()
        config["providers"]["code"]["api"]["base_url"] = "https://api.code.example.test:port"
        self.assert_config_error(config, "providers.code.api.base_url")

    def test_rejects_a_base_url_with_port_zero(self):
        config = make_config()
        config["providers"]["code"]["api"]["base_url"] = "https://api.code.example.test:0"
        self.assert_config_error(config, "providers.code.api.base_url")

    def test_rejects_an_api_block_without_credentials(self):
        config = make_config()
        del config["providers"]["code"]["api"]["credentials"]
        self.assert_config_error(config, "providers.code.api.credentials")

    def test_rejects_a_credential_that_is_not_an_environment_variable_name(self):
        config = make_config()
        config["providers"]["code"]["api"]["credentials"]["token"] = "code_token"
        self.assert_config_error(config, "providers.code.api.credentials.token")

    def test_never_echoes_a_credential_value_written_in_place_of_its_variable(self):
        config = make_config()
        value = "tok" + "q" * 20
        config["providers"]["code"]["api"]["credentials"]["token"] = value
        self.assertNotIn(value, self.config_error(config))

    def test_rejects_an_mcp_transport_without_connector_for_the_place(self):
        config = make_config()
        del config["providers"]["chat"]["mcp"]["connectors"]["local"]
        self.assert_config_error(config, "providers.chat.mcp.connectors.local")

    def test_rejects_an_mcp_transport_without_mcp_block(self):
        config = make_config()
        routine_sources(config)["code"]["transport"]["local"] = "mcp"
        self.assert_config_error(config, "providers.code.mcp")

    def test_checks_only_the_connector_of_the_requested_place(self):
        config = make_config()
        del config["providers"]["chat"]["mcp"]["connectors"]["cloud"]
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_rejects_an_adapter_the_resolver_cannot_load(self):
        config = make_config()
        config["providers"]["chat"]["adapter"] = "missing"
        self.assert_config_error(config, "providers.chat.adapter")

    def test_rejects_an_adapter_module_without_role(self):
        config = make_config()

        def missing_role(adapter):
            raise AttributeError("adapter module has no attribute ROLE")

        message = self.config_error(config, resolver=missing_role)
        self.assertEqual(message.partition(": ")[0], "providers.chat.adapter")

    def test_rejects_an_adapter_whose_role_is_unknown(self):
        config = make_config()
        message = self.config_error(config, resolver=lambda adapter: "pager")
        self.assertEqual(message.partition(": ")[0], "providers.chat.adapter")

    def test_skips_role_options_without_a_resolver(self):
        config = make_config()
        del routine_sources(config)["chat"]["channels"]
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local"))


class LinksBaseTest(ConfigCase):
    def with_links_base(self, value):
        config = make_config()
        config["providers"]["obs"]["links_base"] = value
        return config

    def test_accepts_an_https_links_base(self):
        config = self.with_links_base("https://app.obs.example.test:8443/base")
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_rejects_an_http_links_base(self):
        self.assert_config_error(self.with_links_base("http://app.obs.example.test"), "providers.obs.links_base")

    def test_rejects_a_links_base_with_user_info(self):
        self.assert_config_error(self.with_links_base("https://reader@app.obs.example.test"), "providers.obs.links_base")

    def test_rejects_a_links_base_with_a_query(self):
        self.assert_config_error(self.with_links_base("https://app.obs.example.test/?org=1"), "providers.obs.links_base")

    def test_rejects_a_links_base_with_a_fragment(self):
        self.assert_config_error(self.with_links_base("https://app.obs.example.test/#top"), "providers.obs.links_base")

    def test_rejects_a_links_base_without_host(self):
        self.assert_config_error(self.with_links_base("https:///base"), "providers.obs.links_base")

    def test_rejects_a_links_base_with_an_invalid_port(self):
        self.assert_config_error(self.with_links_base("https://app.obs.example.test:port"), "providers.obs.links_base")

    def test_rejects_a_links_base_that_is_not_a_string(self):
        self.assert_config_error(self.with_links_base(7), "providers.obs.links_base")


class RoleOptionsTest(ConfigCase):
    def test_rejects_an_observability_kind_outside_monitors_and_metrics(self):
        config = make_config()
        routine_sources(config)["metrics"]["kind"] = "logs"
        self.assert_config_error(config, "routines.prod-watch.sources.metrics.kind")

    def test_rejects_an_observability_source_without_scope_filter(self):
        config = make_config()
        del routine_sources(config)["metrics"]["scope_filter"]
        self.assert_config_error(config, "routines.prod-watch.sources.metrics.scope_filter")

    def test_rejects_a_scope_filter_that_is_not_a_string(self):
        config = make_config()
        routine_sources(config)["metrics"]["scope_filter"] = None
        self.assert_config_error(config, "routines.prod-watch.sources.metrics.scope_filter")

    def test_rejects_a_page_id_outside_letters_digits_and_dashes(self):
        config = make_config()
        routine_sources(config)["sources-page"]["page_id"] = "../v1/users"
        self.assert_config_error(config, "routines.prod-watch.sources.sources-page.page_id")

    def test_rejects_an_empty_page_id(self):
        config = make_config()
        routine_sources(config)["sources-page"]["page_id"] = ""
        self.assert_config_error(config, "routines.prod-watch.sources.sources-page.page_id")

    def test_rejects_an_empty_channel_list(self):
        config = make_config()
        routine_sources(config)["chat"]["channels"] = []
        self.assert_config_error(config, "routines.prod-watch.sources.chat.channels")

    def test_rejects_a_channel_that_is_not_a_string(self):
        config = make_config()
        routine_sources(config)["chat"]["channels"] = ["chan-alerts", 7]
        self.assert_config_error(config, "routines.prod-watch.sources.chat.channels[1]")

    def test_rejects_an_empty_repo_list(self):
        config = make_config()
        routine_sources(config)["code"]["repos"] = []
        self.assert_config_error(config, "routines.prod-watch.sources.code.repos")

    def test_rejects_a_repo_without_owner(self):
        config = make_config()
        routine_sources(config)["code"]["repos"] = ["service"]
        self.assert_config_error(config, "routines.prod-watch.sources.code.repos[0]")

    def test_rejects_a_repo_owner_made_only_of_dots(self):
        config = make_config()
        routine_sources(config)["code"]["repos"] = ["../service"]
        self.assert_config_error(config, "routines.prod-watch.sources.code.repos[0]")

    def test_rejects_a_repo_name_made_only_of_a_dot(self):
        config = make_config()
        routine_sources(config)["code"]["repos"] = ["acme/."]
        self.assert_config_error(config, "routines.prod-watch.sources.code.repos[0]")

    def test_accepts_a_repo_with_dots_inside_a_segment(self):
        config = make_config()
        routine_sources(config)["code"]["repos"] = [".config-repo/web.app"]
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_rejects_a_code_host_query_that_is_not_a_string(self):
        config = make_config()
        routine_sources(config)["code"]["query"] = ["is:open"]
        self.assert_config_error(config, "routines.prod-watch.sources.code.query")

    def test_accepts_a_code_host_source_without_query(self):
        config = make_config()
        del routine_sources(config)["code"]["query"]
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_accepts_a_monitors_source_without_discovery_query(self):
        config = make_config()
        del routine_sources(config)["monitors"]["discovery_query"]
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_accepts_an_empty_discovery_query(self):
        config = make_config()
        routine_sources(config)["monitors"]["discovery_query"] = ""
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_rejects_a_discovery_query_that_is_not_a_string(self):
        config = make_config()
        routine_sources(config)["monitors"]["discovery_query"] = None
        self.assert_config_error(config, "routines.prod-watch.sources.monitors.discovery_query")

    def test_rejects_a_discovery_query_on_a_metrics_source(self):
        config = make_config()
        routine_sources(config)["metrics"]["discovery_query"] = "status:alert"
        self.assert_config_error(config, "routines.prod-watch.sources.metrics.discovery_query")


class CodeHostSearchesTest(ConfigCase):
    SOURCE_PATH = "routines.prod-watch.sources.code"

    def searches_config(self, searches=None, transport=None):
        config = make_config()
        source = routine_sources(config)["code"]
        del source["repos"]
        source["searches"] = ["is:pr org:example-org author:dev"] if searches is None else searches
        if transport is not None:
            config["providers"]["code"]["mcp"] = {"connectors": {"cloud": "code-cloud", "local": "code-local"}}
            source["transport"] = transport
        return config

    def test_accepts_searches_in_place_of_repos(self):
        self.assertIsNone(roles.validate_config(self.searches_config(), ROUTINE, "local", role_of))

    def test_accepts_excluded_authors(self):
        config = self.searches_config()
        routine_sources(config)["code"]["exclude_authors"] = ["release-manager"]
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_rejects_repos_next_to_searches(self):
        config = self.searches_config()
        routine_sources(config)["code"]["repos"] = ["acme/service"]
        self.assert_config_error(config, self.SOURCE_PATH)

    def test_rejects_a_source_with_neither_repos_nor_searches(self):
        config = make_config()
        del routine_sources(config)["code"]["repos"]
        self.assert_config_error(config, self.SOURCE_PATH)

    def test_rejects_an_empty_search_list(self):
        self.assert_config_error(self.searches_config([]), self.SOURCE_PATH + ".searches")

    def test_rejects_a_blank_search(self):
        self.assert_config_error(self.searches_config(["is:pr", "  "]), self.SOURCE_PATH + ".searches[1]")

    def test_rejects_a_search_that_is_not_a_string(self):
        self.assert_config_error(self.searches_config([7]), self.SOURCE_PATH + ".searches[0]")

    def test_rejects_excluded_authors_that_is_not_a_list(self):
        config = self.searches_config()
        routine_sources(config)["code"]["exclude_authors"] = "release-manager"
        self.assert_config_error(config, self.SOURCE_PATH + ".exclude_authors")

    def test_rejects_searches_over_an_mcp_transport_for_the_place(self):
        config = self.searches_config(transport={"cloud": "api", "local": "mcp"})
        self.assert_config_error(config, self.SOURCE_PATH + ".searches")

    def test_rejects_searches_over_an_mcp_transport_for_the_other_place(self):
        config = self.searches_config(transport={"cloud": "mcp", "local": "api"})
        self.assert_config_error(config, self.SOURCE_PATH + ".searches")


class DocumentPagesOptionTest(ConfigCase):
    SOURCE_PATH = "routines.prod-watch.sources.sources-page"

    def pages_config(self, pages):
        config = make_config()
        source = routine_sources(config)["sources-page"]
        del source["page_id"]
        source["pages"] = pages
        return config

    def test_accepts_a_source_listing_pages(self):
        self.assertIsNone(roles.validate_config(self.pages_config([page_id(), "page-cdcdcdcd"]), ROUTINE, "local", role_of))

    def test_rejects_a_source_setting_both_page_id_and_pages(self):
        config = self.pages_config([page_id()])
        routine_sources(config)["sources-page"]["page_id"] = page_id()
        self.assert_config_error(config, self.SOURCE_PATH)

    def test_rejects_a_source_setting_neither_page_id_nor_pages(self):
        config = make_config()
        del routine_sources(config)["sources-page"]["page_id"]
        self.assert_config_error(config, self.SOURCE_PATH)

    def test_rejects_an_empty_page_list(self):
        self.assert_config_error(self.pages_config([]), self.SOURCE_PATH + ".pages")

    def test_rejects_pages_that_is_not_a_list(self):
        self.assert_config_error(self.pages_config(page_id()), self.SOURCE_PATH + ".pages")

    def test_rejects_a_listed_page_id_outside_letters_digits_and_dashes(self):
        self.assert_config_error(self.pages_config([page_id(), "../v1/users"]), self.SOURCE_PATH + ".pages[1]")

    def test_rejects_a_listed_page_id_that_is_not_a_string(self):
        self.assert_config_error(self.pages_config([7]), self.SOURCE_PATH + ".pages[0]")


class PageFromStateOptionTest(ConfigCase):
    SOURCE_PATH = "routines.prod-watch.sources.sources-page"

    def state_page_config(self, engine="tribe", value="previous_page"):
        config = make_config()
        config["routines"][ROUTINE]["engine"] = engine
        config["routines"][ROUTINE].update(publication_values())
        source = routine_sources(config)["sources-page"]
        del source["page_id"]
        source["page_from_state"] = value
        return config

    def test_accepts_the_previous_page_for_a_tribe_routine(self):
        self.assertIsNone(roles.validate_config(self.state_page_config(), ROUTINE, "local", role_of))

    def test_rejects_a_value_other_than_previous_page(self):
        self.assert_config_error(self.state_page_config(value="next_page"), self.SOURCE_PATH + ".page_from_state")

    def test_rejects_a_value_that_is_not_a_string(self):
        self.assert_config_error(self.state_page_config(value=True), self.SOURCE_PATH + ".page_from_state")

    def test_rejects_the_option_next_to_page_id(self):
        config = self.state_page_config()
        routine_sources(config)["sources-page"]["page_id"] = page_id()
        self.assert_config_error(config, self.SOURCE_PATH)

    def test_rejects_the_option_next_to_pages(self):
        config = self.state_page_config()
        routine_sources(config)["sources-page"]["pages"] = [page_id()]
        self.assert_config_error(config, self.SOURCE_PATH)

    def test_rejects_the_option_for_a_watch_routine(self):
        self.assert_config_error(self.state_page_config(engine="watch"), self.SOURCE_PATH + ".page_from_state")

    def test_rejects_the_option_for_a_routine_without_an_engine(self):
        config = self.state_page_config()
        del config["routines"][ROUTINE]["engine"]
        self.assert_config_error(config, self.SOURCE_PATH + ".page_from_state")


class DocumentEditedByOptionTest(ConfigCase):
    SOURCE_PATH = "routines.prod-watch.sources.sources-page"

    def edited_config(self, transport=None, **options):
        config = make_config()
        source = routine_sources(config)["sources-page"]
        del source["page_id"]
        source["transport"] = transport or {"cloud": "api", "local": "api"}
        source.update({"edited_by": "user-ab12", **options})
        return config

    def test_accepts_a_source_reading_the_pages_a_user_edited(self):
        self.assertIsNone(roles.validate_config(self.edited_config(), ROUTINE, "local", role_of))

    def test_accepts_an_edited_cap_from_1_to_20(self):
        for cap in (1, 20):
            with self.subTest(cap=cap):
                self.assertIsNone(roles.validate_config(self.edited_config(edited_cap=cap), ROUTINE, "local", role_of))

    def test_rejects_a_blank_edited_by(self):
        self.assert_config_error(self.edited_config(edited_by="  "), self.SOURCE_PATH + ".edited_by")

    def test_rejects_an_edited_by_that_is_not_a_string(self):
        self.assert_config_error(self.edited_config(edited_by=7), self.SOURCE_PATH + ".edited_by")

    def test_rejects_edited_by_next_to_pages(self):
        self.assert_config_error(self.edited_config(pages=[page_id()]), self.SOURCE_PATH)

    def test_rejects_edited_by_next_to_page_id(self):
        self.assert_config_error(self.edited_config(page_id=page_id()), self.SOURCE_PATH)

    def test_rejects_an_edited_cap_without_edited_by(self):
        config = make_config()
        routine_sources(config)["sources-page"]["edited_cap"] = 5
        self.assert_config_error(config, self.SOURCE_PATH + ".edited_cap")

    def test_rejects_an_edited_cap_below_1(self):
        self.assert_config_error(self.edited_config(edited_cap=0), self.SOURCE_PATH + ".edited_cap")

    def test_rejects_an_edited_cap_above_20(self):
        self.assert_config_error(self.edited_config(edited_cap=21), self.SOURCE_PATH + ".edited_cap")

    def test_rejects_an_edited_cap_that_is_not_an_integer(self):
        self.assert_config_error(self.edited_config(edited_cap=True), self.SOURCE_PATH + ".edited_cap")

    def test_rejects_edited_by_over_the_mcp_transport_of_the_place_checked(self):
        config = self.edited_config(transport={"cloud": "api", "local": "mcp"})
        self.assert_config_error(config, self.SOURCE_PATH + ".edited_by")

    def test_rejects_edited_by_over_the_mcp_transport_of_the_other_place(self):
        config = self.edited_config(transport={"cloud": "mcp", "local": "api"})
        self.assert_config_error(config, self.SOURCE_PATH + ".edited_by")


class FirstReadDaysTest(ConfigCase):
    KEY_PATH = "routines.prod-watch.first_read_days"

    def with_days(self, days):
        config = make_config()
        config["routines"][ROUTINE]["first_read_days"] = days
        return config

    def test_accepts_a_routine_without_first_read_days(self):
        self.assertIsNone(roles.validate_config(make_config(), ROUTINE, "local", role_of))

    def test_accepts_one_day(self):
        self.assertIsNone(roles.validate_config(self.with_days(1), ROUTINE, "local", role_of))

    def test_accepts_31_days(self):
        self.assertIsNone(roles.validate_config(self.with_days(31), ROUTINE, "local", role_of))

    def test_rejects_zero_days(self):
        self.assert_config_error(self.with_days(0), self.KEY_PATH)

    def test_rejects_32_days(self):
        self.assert_config_error(self.with_days(32), self.KEY_PATH)

    def test_rejects_a_boolean(self):
        self.assert_config_error(self.with_days(True), self.KEY_PATH)

    def test_rejects_a_fractional_number_of_days(self):
        self.assert_config_error(self.with_days(7.5), self.KEY_PATH)

    def test_rejects_a_string(self):
        self.assert_config_error(self.with_days("7"), self.KEY_PATH)

    def test_rejects_null(self):
        self.assert_config_error(self.with_days(None), self.KEY_PATH)


class EngineTest(ConfigCase):
    KEY_PATH = "routines.prod-watch.engine"

    def with_engine(self, engine):
        config = make_config()
        config["routines"][ROUTINE]["engine"] = engine
        config["routines"][ROUTINE].update(publication_values())
        return config

    def test_accepts_a_routine_without_an_engine(self):
        self.assertIsNone(roles.validate_config(make_config(), ROUTINE, "local", role_of))

    def test_accepts_the_watch_engine(self):
        self.assertIsNone(roles.validate_config(self.with_engine("watch"), ROUTINE, "local", role_of))

    def test_accepts_the_tribe_engine(self):
        self.assertIsNone(roles.validate_config(self.with_engine("tribe"), ROUTINE, "local", role_of))

    def test_rejects_an_unknown_engine(self):
        self.assert_config_error(self.with_engine("legacy"), self.KEY_PATH)

    def test_rejects_a_capitalised_engine(self):
        self.assert_config_error(self.with_engine("Tribe"), self.KEY_PATH)

    def test_rejects_a_boolean(self):
        self.assert_config_error(self.with_engine(True), self.KEY_PATH)

    def test_rejects_null(self):
        self.assert_config_error(self.with_engine(None), self.KEY_PATH)


RECAP = "chat-recap"
RECAP_OWNER = "U" + "1" * 6


def make_recap_config(**changes):
    config = make_config()
    chat = config["routines"][ROUTINE]["sources"]["chat"]
    chat.update(owner=RECAP_OWNER, searches=[{"name": "dms", "filters": "is:dm", "since": "window"}], reactions=True)
    routine = {
        "template": "chat-recap",
        "cron": "0 9 * * 1-5",
        "engine": "recap",
        "owner": RECAP_OWNER,
        "workspace": "chat.example.test",
        "groups": [{"id": "S" + "1" * 6, "label": "Core team", "lands_in": "waiting"}],
        "announcement": {"channels": ["C" + "2" * 6], "topics": ["releases"]},
        "window": {"lookback_working_days": 3},
        "exclude": {"authors": ["U" + "3" * 6], "channels": ["C" + "3" * 6], "keep_bots": []},
        "history": {"late_after_working_days": 3, "drop_after_days": 14},
        "rules": ["An ask needs a reply from the owner."],
        "sources": {"chat": chat},
    }
    routine.update(changes)
    for key in [key for key, value in changes.items() if value is None]:
        del routine[key]
    config["routines"] = {RECAP: routine}
    return config


class RecapConfigTest(unittest.TestCase):
    def path_of(self, config, place="local"):
        with self.assertRaises(roles.ConfigError) as caught:
            roles.validate_config(config, RECAP, place, role_of)
        return str(caught.exception).partition(": ")[0]

    def rejected(self, path, **changes):
        self.assertEqual(self.path_of(make_recap_config(**changes)), f"routines.{RECAP}.{path}")

    def test_accepts_a_complete_recap_routine_for_both_places(self):
        for place in ("cloud", "local"):
            with self.subTest(place=place):
                self.assertIsNone(roles.validate_config(make_recap_config(), RECAP, place, role_of))

    def test_accepts_a_routine_without_history(self):
        self.assertIsNone(roles.validate_config(make_recap_config(history=None), RECAP, "local", role_of))

    def test_accepts_a_history_with_one_key(self):
        config = make_recap_config(history={"drop_after_days": 30})
        self.assertIsNone(roles.validate_config(config, RECAP, "local", role_of))

    def test_accepts_announcement_and_exclude_lists_left_out(self):
        config = make_recap_config(announcement={}, exclude={}, groups=[])
        self.assertIsNone(roles.validate_config(config, RECAP, "local", role_of))

    def test_rejects_a_missing_key_naming_it(self):
        for key in ("owner", "workspace", "groups", "announcement", "window", "exclude", "rules"):
            with self.subTest(key=key):
                self.rejected(key, **{key: None})

    def test_rejects_an_empty_owner(self):
        self.rejected("owner", owner="")

    def test_rejects_a_workspace_that_is_not_a_plain_host(self):
        for value in ("", "https://chat.example.test", "chat.example.test/path", "chat example.test", 3):
            with self.subTest(value=value):
                self.rejected("workspace", workspace=value)

    def test_rejects_groups_that_are_not_a_list(self):
        self.rejected("groups", groups={})

    def test_rejects_a_group_landing_outside_the_two_sections(self):
        self.rejected("groups[0].lands_in", groups=[{"id": "S1", "label": "Core", "lands_in": "elsewhere"}])

    def test_rejects_a_group_without_a_label_naming_its_index(self):
        groups = [{"id": "S1", "label": "Core", "lands_in": "waiting"}, {"id": "S2", "lands_in": "waiting"}]
        self.rejected("groups[1].label", groups=groups)

    def test_rejects_a_group_without_an_id(self):
        self.rejected("groups[0].id", groups=[{"label": "Core", "lands_in": "waiting"}])

    def test_rejects_announcement_channels_that_are_not_a_list(self):
        self.rejected("announcement.channels", announcement={"channels": "C1"})

    def test_rejects_an_announcement_topic_that_is_not_text(self):
        self.rejected("announcement.topics[1]", announcement={"topics": ["releases", 3]})

    def test_rejects_an_excluded_author_that_is_not_text(self):
        self.rejected("exclude.authors[0]", exclude={"authors": [7]})

    def test_rejects_excluded_channels_that_are_not_a_list(self):
        self.rejected("exclude.channels", exclude={"channels": "C1"})

    def test_rejects_kept_bots_that_are_not_a_list(self):
        self.rejected("exclude.keep_bots", exclude={"keep_bots": "B1"})

    def test_rejects_a_lookback_outside_1_to_365(self):
        for value in (0, 366, "3", True, 2.5, None):
            with self.subTest(value=value):
                self.rejected("window.lookback_working_days", window={"lookback_working_days": value})

    def test_rejects_unexpected_keys_in_nested_mappings_naming_their_path(self):
        cases = {
            "announcement.channel": {"announcement": {"channel": []}},
            "window.thread_lookback_days": {"window": {"lookback_working_days": 3, "thread_lookback_days": 7}},
            "exclude.author": {"exclude": {"author": []}},
            "history.drop_after_day": {"history": {"drop_after_day": 14}},
            "groups[0].landing": {"groups": [{"id": "S1", "label": "Core", "lands_in": "waiting", "landing": "x"}]},
        }
        for path, changes in cases.items():
            with self.subTest(path=path):
                self.rejected(path, **changes)

    def test_names_the_second_group_holding_an_unexpected_key(self):
        groups = [
            {"id": "S1", "label": "Core", "lands_in": "waiting"},
            {"id": "S2", "label": "All", "lands_in": "good_to_know", "color": "red"},
        ]
        self.rejected("groups[1].color", groups=groups)

    def test_accepts_other_keys_beside_the_recap_keys_in_the_routine(self):
        config = make_recap_config()
        config["routines"][RECAP]["values"] = {"digest": {"slug": "x"}}
        self.assertIsNone(roles.validate_config(config, RECAP, "local", role_of))

    def test_rejects_late_after_outside_0_to_365(self):
        for value in (-1, 366, "3", True):
            with self.subTest(value=value):
                self.rejected("history.late_after_working_days", history={"late_after_working_days": value})

    def test_rejects_drop_after_outside_1_to_365(self):
        for value in (0, 366, "14", False):
            with self.subTest(value=value):
                self.rejected("history.drop_after_days", history={"drop_after_days": value})

    def test_accepts_late_after_of_zero(self):
        config = make_recap_config(history={"late_after_working_days": 0})
        self.assertIsNone(roles.validate_config(config, RECAP, "local", role_of))

    def test_rejects_history_that_is_not_a_mapping(self):
        self.rejected("history", history=[])

    def test_rejects_empty_rules(self):
        self.rejected("rules", rules=[])

    def test_rejects_a_rule_that_is_not_text(self):
        self.rejected("rules[1]", rules=["An ask needs a reply.", 5])

    def test_rejects_a_source_of_another_role(self):
        config = make_recap_config()
        config["routines"][RECAP]["sources"]["docs"] = make_config()["routines"][ROUTINE]["sources"]["sources-page"]
        self.assertEqual(self.path_of(config), f"routines.{RECAP}.sources.docs.provider")

    def test_rejects_a_chat_source_of_another_owner(self):
        config = make_recap_config()
        config["routines"][RECAP]["sources"]["chat"]["owner"] = "U" + "9" * 6
        self.assertEqual(self.path_of(config), f"routines.{RECAP}.sources.chat.owner")

    def test_rejects_a_chat_source_without_an_owner(self):
        config = make_recap_config()
        del config["routines"][RECAP]["sources"]["chat"]["owner"]
        del config["routines"][RECAP]["sources"]["chat"]["searches"]
        del config["routines"][RECAP]["sources"]["chat"]["reactions"]
        config["routines"][RECAP]["sources"]["chat"]["channels"] = ["C" + "1" * 6]
        self.assertEqual(self.path_of(config), f"routines.{RECAP}.sources.chat.owner")

    def test_checks_no_recap_key_on_another_engine(self):
        config = make_recap_config(engine="watch", owner=None, rules=None)
        self.assertIsNone(roles.validate_config(config, RECAP, "local", role_of))


WEEKLY = "weekly-status"


def make_weekly_config(**changes):
    config = make_config()
    config["providers"]["tracker"] = {
        "adapter": "trackervendor",
        "api": {"base_url": "https://api.tracker.example.test", "credentials": {"email": "TRACKER_EMAIL", "token": "TRACKER_TOKEN"}},
    }
    sources = config["routines"][ROUTINE]["sources"]
    api = {"cloud": "api", "local": "api"}
    routine = {
        "template": "weekly-status",
        "cron": "0 16 * * 5",
        "engine": "weekly",
        "owner": RECAP_OWNER,
        "workspace": "chat.example.test",
        "recap": RECAP,
        "exclude": {"channels": ["C" + "3" * 6]},
        "values": {"digest": {"name": "Weekly status", "slug": WEEKLY}},
        "sources": {
            "issues": {"provider": "tracker", "transport": api, "jql": "assignee = currentUser()"},
            "code": {"provider": "code", "transport": api, "searches": ["is:pr org:example-org author:dev"]},
            "chat": {
                "provider": "chat",
                "transport": {"cloud": "mcp", "local": "mcp"},
                "owner": RECAP_OWNER,
                "searches": [{"name": "dms", "filters": "is:dm", "since": "window"}],
            },
            "docs": {"provider": "docs", "transport": api, "edited_by": "user-ab12"},
        },
    }
    routine.update(changes)
    for key in [key for key, value in changes.items() if value is None]:
        del routine[key]
    config["routines"] = {WEEKLY: routine}
    return config


class WeeklyConfigTest(unittest.TestCase):
    def path_of(self, config, place="local"):
        with self.assertRaises(roles.ConfigError) as caught:
            roles.validate_config(config, WEEKLY, place, role_of)
        return str(caught.exception).partition(": ")[0]

    def rejected(self, path, **changes):
        self.assertEqual(self.path_of(make_weekly_config(**changes)), f"routines.{WEEKLY}.{path}")

    def rejected_source(self, path, mutate):
        config = make_weekly_config()
        mutate(config["routines"][WEEKLY]["sources"])
        self.assertEqual(self.path_of(config), f"routines.{WEEKLY}.sources.{path}")

    def test_lists_weekly_among_the_engines(self):
        self.assertEqual(roles.WEEKLY_ENGINE, "weekly")
        self.assertIn("weekly", roles.ENGINES)

    def test_accepts_a_complete_weekly_routine_for_both_places(self):
        for place in ("cloud", "local"):
            with self.subTest(place=place):
                self.assertIsNone(roles.validate_config(make_weekly_config(), WEEKLY, place, role_of))

    def test_accepts_a_routine_without_a_recap_or_exclude(self):
        config = make_weekly_config(recap=None, exclude=None)
        self.assertIsNone(roles.validate_config(config, WEEKLY, "local", role_of))

    def test_accepts_an_exclude_without_channels(self):
        self.assertIsNone(roles.validate_config(make_weekly_config(exclude={}), WEEKLY, "local", role_of))

    def test_accepts_a_routine_without_a_chat_source(self):
        config = make_weekly_config()
        del config["routines"][WEEKLY]["sources"]["chat"]
        self.assertIsNone(roles.validate_config(config, WEEKLY, "local", role_of))

    def test_rejects_a_missing_key_naming_it(self):
        for key in ("owner", "workspace"):
            with self.subTest(key=key):
                self.rejected(key, **{key: None})

    def test_rejects_a_blank_owner(self):
        for value in ("", "  ", 7):
            with self.subTest(value=value):
                self.rejected("owner", owner=value)

    def test_rejects_a_workspace_that_is_not_a_plain_host(self):
        for value in ("", "https://chat.example.test", "chat.example.test/path", 3):
            with self.subTest(value=value):
                self.rejected("workspace", workspace=value)

    def test_rejects_a_recap_that_is_not_a_routine_slug(self):
        for value in ("", "Chat Recap", 3):
            with self.subTest(value=value):
                self.rejected("recap", recap=value)

    def test_rejects_excluded_channels_that_are_not_a_list(self):
        self.rejected("exclude.channels", exclude={"channels": "C1"})

    def test_rejects_an_excluded_channel_that_is_not_text(self):
        self.rejected("exclude.channels[1]", exclude={"channels": ["C1", 4]})

    def test_rejects_an_unexpected_exclude_key(self):
        self.rejected("exclude.authors", exclude={"authors": []})

    def test_rejects_an_observability_source_naming_its_path(self):
        def add(sources):
            sources["monitors"] = {"provider": "obs", "transport": {"cloud": "api", "local": "api"}, "kind": "monitors", "scope_filter": ""}

        self.rejected_source("monitors.provider", add)

    def test_rejects_a_chat_source_without_searches(self):
        def drop(sources):
            del sources["chat"]["searches"]
            sources["chat"]["channels"] = ["chan-alerts"]

        self.rejected_source("chat.searches", drop)

    def test_rejects_a_chat_source_of_another_owner(self):
        self.rejected_source("chat.owner", lambda sources: sources["chat"].update(owner="U" + "9" * 6))

    def test_rejects_a_chat_source_without_an_owner(self):
        self.rejected_source("chat.owner", lambda sources: sources["chat"].pop("owner"))

    def test_rejects_a_source_option_of_its_role_naming_its_path(self):
        self.rejected_source("issues", lambda sources: sources["issues"].update(filter="10042"))

    def test_checks_no_weekly_key_on_another_engine(self):
        config = make_weekly_config(engine="watch", owner=None)
        self.assertIsNone(roles.validate_config(config, WEEKLY, "local", role_of))


class PublicationConfigTest(ConfigCase):
    ROUTINE_PATH = "routines.prod-watch"

    def tribe_config(self, engine="tribe"):
        config = make_config()
        routine = config["routines"][ROUTINE]
        routine["engine"] = engine
        routine.update(publication_values())
        return config

    def rejected(self, path, change, key="publish"):
        config = self.tribe_config()
        routine = config["routines"][ROUTINE]
        change(routine[key])
        self.assert_config_error(config, f"{self.ROUTINE_PATH}.{path}")

    def replaced(self, key, value):
        config = self.tribe_config()
        config["routines"][ROUTINE][key] = value
        self.assert_config_error(config, f"{self.ROUTINE_PATH}.{key}")

    def test_accepts_the_page_and_publish_keys_of_a_tribe_routine(self):
        self.assertIsNone(roles.validate_config(self.tribe_config(), ROUTINE, "local", role_of))

    def test_rejects_a_tribe_routine_without_page_values(self):
        config = self.tribe_config()
        del config["routines"][ROUTINE]["page"]
        self.assert_config_error(config, f"{self.ROUTINE_PATH}.page")

    def test_rejects_a_tribe_routine_without_publish_values(self):
        config = self.tribe_config()
        del config["routines"][ROUTINE]["publish"]
        self.assert_config_error(config, f"{self.ROUTINE_PATH}.publish")

    def test_rejects_a_publish_provider_that_is_not_configured(self):
        self.rejected("publish.provider", lambda publish: publish.update(provider="absent"))

    def test_ignores_the_keys_of_a_routine_with_the_watch_engine(self):
        config = self.tribe_config("watch")
        config["routines"][ROUTINE]["page"] = 5
        config["routines"][ROUTINE]["publish"] = []
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_accepts_the_task_placeholder_in_the_poll_arguments(self):
        config = self.tribe_config()
        self.assertEqual(config["routines"][ROUTINE]["publish"]["poll"]["arguments"]["task"], "{{task}}")
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_rejects_page_that_is_not_a_mapping(self):
        self.replaced("page", [])

    def test_rejects_how_built_that_is_a_string(self):
        self.rejected("page.how_built", lambda page: page.update({"how_built": "text"}), key="page")

    def test_rejects_a_key_callout_line_that_is_not_a_string(self):
        self.rejected("page.key_callout[1]", lambda page: page.update({"key_callout": ["a", 2]}), key="page")

    def test_rejects_an_empty_state_path(self):
        self.rejected("page.state_path", lambda page: page.update({"state_path": ""}), key="page")

    def test_rejects_a_page_without_a_link(self):
        self.rejected("page.link", lambda page: page.pop("link"), key="page")

    def test_rejects_a_link_without_the_id_placeholder(self):
        self.rejected("page.link", lambda page: page.update({"link": "https://example.test/p"}), key="page")

    def test_rejects_a_link_with_an_unknown_placeholder(self):
        self.rejected("page.link", lambda page: page.update({"link": "https://example.test/{{id}}/{{space}}"}), key="page")

    def test_rejects_a_link_that_is_not_a_string(self):
        self.rejected("page.link", lambda page: page.update({"link": 7}), key="page")

    def test_rejects_a_page_without_a_title(self):
        self.rejected("page.title", lambda page: page.pop("title"), key="page")

    def test_rejects_a_title_with_a_control_character(self):
        self.rejected("page.title", lambda page: page.update({"title": "Digest\x07 {{date}}"}), key="page")

    def test_rejects_an_empty_title(self):
        self.rejected("page.title", lambda page: page.update({"title": ""}), key="page")

    def test_rejects_a_title_with_a_placeholder_other_than_the_date(self):
        self.rejected("page.title", lambda page: page.update({"title": "Digest {{week}}"}), key="page")

    def test_rejects_a_title_placeholder_with_spaces(self):
        self.rejected("page.title", lambda page: page.update({"title": "Digest {{ date }}"}), key="page")

    def test_rejects_the_date_placeholder_in_the_link(self):
        self.rejected("page.link", lambda page: page.update({"link": "https://example.test/{{id}}/{{date}}"}), key="page")

    def test_accepts_the_date_and_week_start_placeholders_in_every_call(self):
        config = self.tribe_config()
        publish = config["routines"][ROUTINE]["publish"]
        for call in ("create", "poll", "heading"):
            publish[call]["arguments"]["extra"] = "{{date}} {{week_start}} {{week}} {{title}}"
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_accepts_a_week_start_format(self):
        config = self.tribe_config()
        config["routines"][ROUTINE]["publish"]["week_start_format"] = "%d %b %Y"
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_rejects_a_week_start_format_that_is_not_a_string(self):
        self.rejected("publish.week_start_format", lambda publish: publish.update({"week_start_format": 3}))

    def test_rejects_an_empty_week_start_format(self):
        self.rejected("publish.week_start_format", lambda publish: publish.update({"week_start_format": ""}))

    def test_accepts_a_digit_segment_in_a_result_path(self):
        config = self.tribe_config()
        config["routines"][ROUTINE]["publish"]["results"]["page"] = "result.pages.0.id"
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_rejects_publish_that_is_not_a_mapping(self):
        self.replaced("publish", "create")

    def test_rejects_a_missing_provider(self):
        self.rejected("publish.provider", lambda publish: publish.pop("provider"))

    def test_rejects_a_parent_that_is_not_a_page_id(self):
        self.rejected("publish.parent", lambda publish: publish.update({"parent": "a/b"}))

    def test_rejects_a_missing_call(self):
        self.rejected("publish.poll", lambda publish: publish.pop("poll"))

    def test_rejects_a_tool_that_is_not_a_string(self):
        self.rejected("publish.create.tool", lambda publish: publish["create"].update({"tool": 3}))

    def test_rejects_arguments_that_are_not_a_mapping(self):
        self.rejected("publish.heading.arguments", lambda publish: publish["heading"].update({"arguments": ["x"]}))

    def test_rejects_results_that_are_not_a_mapping(self):
        self.rejected("publish.results", lambda publish: publish.update({"results": "task.id"}))

    def test_rejects_a_result_path_with_an_empty_segment(self):
        self.rejected("publish.results.task", lambda publish: publish["results"].update({"task": "task..id"}))

    def test_rejects_a_result_path_that_is_not_a_string(self):
        self.rejected("publish.results.page", lambda publish: publish["results"].update({"page": ["task", "id"]}))

    def test_rejects_an_empty_done_list(self):
        self.rejected("publish.results.done", lambda publish: publish["results"].update({"done": []}))

    def test_rejects_a_failed_list_with_a_non_string(self):
        self.rejected("publish.results.failed[1]", lambda publish: publish["results"].update({"failed": ["failed", 4]}))

    def test_rejects_a_missing_failed_list(self):
        self.rejected("publish.results.failed", lambda publish: publish["results"].pop("failed"))

    def test_rejects_an_unknown_placeholder_naming_the_argument(self):
        self.rejected("publish.create.arguments.title", lambda publish: publish["create"]["arguments"].update({"title": "{{name}}"}))

    def test_rejects_a_placeholder_with_spaces(self):
        self.rejected("publish.heading.arguments.text", lambda publish: publish["heading"]["arguments"].update({"text": "## {{ week }}"}))

    def test_rejects_a_placeholder_inside_a_nested_list(self):
        self.rejected("publish.create.arguments.rows[0].c", lambda publish: publish["create"]["arguments"].update({"rows": [{"c": "{{nope}}"}]}))

    def test_rejects_the_task_placeholder_outside_the_poll(self):
        self.rejected("publish.create.arguments.title", lambda publish: publish["create"]["arguments"].update({"title": "{{task}}"}))

    def test_rejects_the_link_placeholder_in_a_call(self):
        self.rejected("publish.heading.arguments.text", lambda publish: publish["heading"]["arguments"].update({"text": "{{id}}"}))


class PackCase(unittest.TestCase):
    def assert_pack_error(self, pack, path, rules=None):
        with self.assertRaises(roles.PackError) as caught:
            roles.validate_pack(pack, pack_sources(), routine=ROUTINE, rules=[] if rules is None else rules)
        self.assertEqual(str(caught.exception).partition(": ")[0], path)

    def assert_pack_accepted(self, pack, rules=None):
        self.assertIsNone(
            roles.validate_pack(pack, pack_sources(), routine=ROUTINE, rules=[] if rules is None else rules)
        )


class ValidatePackTest(PackCase):
    def test_accepts_the_full_example_pack(self):
        self.assertIsNone(roles.validate_pack(make_pack(), pack_sources(), routine=ROUTINE, rules=[]))

    def test_accepts_an_empty_pack(self):
        self.assertIsNone(roles.validate_pack([], pack_sources(), routine=ROUTINE, rules=[]))

    def test_names_the_pack_path_alone_without_a_routine(self):
        pack = make_pack()
        pack[2]["top"] = 0
        with self.assertRaises(roles.PackError) as caught:
            roles.validate_pack(pack, pack_sources(), rules=[])
        self.assertEqual(str(caught.exception).partition(": ")[0], "query_pack[2].top")

    def test_rejects_a_key_equal_to_a_source_name(self):
        pack = make_pack()
        sources = {**pack_sources(), pack[0]["key"]: {"role": "chat", "channels": ["chan-ops"]}}
        with self.assertRaises(roles.PackError) as caught:
            roles.validate_pack(pack, sources, routine=ROUTINE, rules=[])
        self.assertEqual(str(caught.exception).partition(": ")[0], f"routines.{ROUTINE}.query_pack[0].key")

    def test_requires_the_rules_keyword(self):
        with self.assertRaises(TypeError):
            roles.validate_pack(make_pack(), pack_sources(), routine=ROUTINE)

    def test_pack_error_is_not_a_config_error(self):
        self.assertFalse(issubclass(roles.PackError, roles.ConfigError))

    def test_rejects_a_pack_that_is_not_a_list(self):
        self.assert_pack_error({"key": "x"}, "routines.prod-watch.query_pack")

    def test_rejects_an_entry_that_is_not_a_mapping(self):
        pack = make_pack()
        pack[1] = "error-rate"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1]")

    def test_rejects_an_entry_without_key(self):
        pack = make_pack()
        del pack[1]["key"]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].key")

    def test_rejects_a_duplicate_key(self):
        pack = make_pack()
        pack[3]["key"] = "error-rate"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].key")

    def test_rejects_a_source_that_is_not_configured(self):
        pack = make_pack()
        pack[1]["source"] = "logs"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].source")

    def test_rejects_a_source_outside_the_observability_role(self):
        pack = make_pack()
        pack[1]["source"] = "chat"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].source")

    def test_rejects_a_monitor_entry_key_without_monitor_prefix(self):
        pack = make_pack()
        pack[0]["key"] = "latency"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[0].key")

    def test_rejects_a_monitor_entry_without_monitor(self):
        pack = make_pack()
        del pack[0]["monitor"]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[0].monitor")

    def test_rejects_a_monitor_id_with_letters(self):
        pack = make_pack()
        pack[0]["monitor"] = "ab" + MONITOR_ID
        pack[0]["key"] = "monitor-" + pack[0]["monitor"]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[0].monitor")

    def test_rejects_an_empty_monitor_id(self):
        pack = make_pack()
        pack[0]["monitor"] = ""
        pack[0]["key"] = "monitor-"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[0].monitor")

    def test_rejects_a_monitor_id_with_a_trailing_newline(self):
        pack = make_pack()
        pack[0]["monitor"] = MONITOR_ID + "\n"
        pack[0]["key"] = "monitor-" + pack[0]["monitor"]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[0].monitor")

    def test_rejects_a_monitor_id_with_non_ascii_digits(self):
        pack = make_pack()
        pack[0]["monitor"] = "\u0664\u0662"
        pack[0]["key"] = "monitor-" + pack[0]["monitor"]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[0].monitor")

    def test_rejects_a_monitor_id_that_is_not_a_string(self):
        pack = make_pack()
        pack[0]["monitor"] = int(MONITOR_ID)
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[0].monitor")

    def test_rejects_a_monitor_entry_on_a_metrics_source(self):
        pack = make_pack()
        pack[0]["source"] = "metrics"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[0].key")

    def test_rejects_a_metric_entry_on_a_monitors_source(self):
        pack = make_pack()
        pack[1]["source"] = "monitors"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].key")

    def test_rejects_a_metric_entry_key_with_monitor_prefix(self):
        pack = make_pack()
        pack[1]["key"] = "monitor-error-rate"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].key")

    def test_rejects_a_top_entry_whose_group_keys_would_start_with_monitor_prefix(self):
        pack = [entry for entry in make_pack() if entry["source"] != "monitors"]
        pack[1]["key"] = "monitor"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].key")

    def test_accepts_a_scalar_entry_keyed_monitor_without_a_dash(self):
        pack = [entry for entry in make_pack() if entry["source"] != "monitors"]
        pack[0]["key"] = "monitor"
        self.assert_pack_accepted(pack)

    def test_rejects_a_metric_entry_without_query(self):
        pack = make_pack()
        del pack[1]["query"]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].query")

    def test_rejects_a_read_mode_outside_scalar_top_and_hourly(self):
        pack = make_pack()
        pack[1]["read"] = "sum"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].read")

    def test_rejects_an_empty_aggregator(self):
        pack = make_pack()
        pack[1]["aggregator"] = ""
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].aggregator")

    def test_rejects_a_top_entry_without_top(self):
        pack = make_pack()
        del pack[2]["top"]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[2].top")

    def test_rejects_a_top_below_one(self):
        pack = make_pack()
        pack[2]["top"] = 0
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[2].top")

    def test_rejects_a_boolean_top(self):
        pack = make_pack()
        pack[2]["top"] = True
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[2].top")

    def test_rejects_an_entry_without_title(self):
        pack = make_pack()
        del pack[3]["title"]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].title")

    def test_rejects_an_entry_without_link(self):
        pack = make_pack()
        del pack[3]["link"]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].link")

    def test_accepts_a_title_and_a_link_of_300_characters(self):
        pack = make_pack()
        pack[3]["title"] = "t" * 300
        pack[3]["link"] = "https://obs.example.test/" + "x" * 275
        self.assert_pack_accepted(pack)

    def test_rejects_a_metric_title_over_300_characters(self):
        pack = make_pack()
        pack[3]["title"] = "t" * 301
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].title")

    def test_rejects_a_monitor_title_over_300_characters(self):
        pack = make_pack()
        pack[0]["title"] = "t" * 301
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[0].title")

    def test_rejects_a_link_over_300_characters(self):
        pack = make_pack()
        pack[3]["link"] = "https://obs.example.test/" + "x" * 276
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].link")

    def test_rejects_a_title_with_a_line_break(self):
        pack = make_pack()
        pack[3]["title"] = "Queue\ndepth"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].title")

    def test_rejects_a_title_with_a_line_separator(self):
        pack = make_pack()
        pack[3]["title"] = "Queue\u2028depth"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].title")

    def test_rejects_a_link_with_a_bidirectional_override(self):
        pack = make_pack()
        pack[3]["link"] = "https://obs.example.test/\u202e"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].link")

    def test_rejects_an_empty_title(self):
        pack = make_pack()
        pack[3]["title"] = ""
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].title")

    def test_rejects_a_title_that_is_not_text(self):
        pack = make_pack()
        pack[3]["title"] = 5
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].title")

    def test_rejects_a_schedule_outside_every_run_and_daily(self):
        pack = make_pack()
        pack[3]["schedule"] = "weekly"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].schedule")


class PackSchemaTest(PackCase):
    def test_rejects_a_metric_entry_carrying_a_severity(self):
        pack = make_pack()
        pack[3]["severity"] = "Medium"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].severity")

    def test_rejects_a_monitor_entry_carrying_an_urgency(self):
        pack = make_pack()
        pack[0]["urgency"] = "now"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[0].urgency")

    def test_rejects_a_metric_entry_carrying_a_threshold(self):
        pack = make_pack()
        pack[1]["threshold"] = {"op": ">", "value": 5}
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].threshold")

    def test_rejects_an_unknown_entry_field(self):
        pack = make_pack()
        pack[1]["note"] = "x"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].note")

    def test_rejects_a_monitor_entry_carrying_a_metric_field(self):
        pack = make_pack()
        pack[0]["query"] = "sum:errors{env:prod}"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[0].query")

    def test_rejects_an_entry_without_rule(self):
        pack = make_pack()
        del pack[1]["rule"]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].rule")

    def test_rejects_a_monitor_entry_without_rule(self):
        pack = make_pack()
        del pack[0]["rule"]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[0].rule")

    def test_rejects_an_empty_rule(self):
        pack = make_pack()
        pack[1]["rule"] = ""
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].rule")

    def test_rejects_a_whitespace_only_rule(self):
        pack = make_pack()
        pack[1]["rule"] = " \t\n"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].rule")

    def test_rejects_a_rule_that_is_not_a_string(self):
        pack = make_pack()
        pack[1]["rule"] = ["Open above 5"]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].rule")

    def test_accepts_a_rule_of_500_characters(self):
        pack = make_pack()
        pack[1]["rule"] = "r" * 500
        self.assert_pack_accepted(pack)

    def test_rejects_a_rule_of_501_characters(self):
        pack = make_pack()
        pack[1]["rule"] = "r" * 501
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].rule")

    def test_rejects_top_on_an_entry_that_is_not_a_top_read(self):
        pack = make_pack()
        pack[1]["top"] = 3
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].top")

    def test_rejects_a_monitor_key_other_than_the_key_of_its_monitor(self):
        pack = make_pack()
        pack[0]["key"] = "monitor-" + OTHER_MONITOR_ID
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[0].key")

    def test_rejects_a_monitor_key_with_a_suffix_after_its_monitor(self):
        pack = make_pack()
        pack[0]["key"] = "monitor-" + MONITOR_ID + "-latency"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[0].key")


class ExcludedHoursTest(PackCase):
    def test_accepts_an_hourly_entry_without_excluded_hours(self):
        pack = make_pack()
        del pack[3]["excluded_hours"]
        self.assert_pack_accepted(pack)

    def test_accepts_the_first_and_last_local_hours(self):
        pack = make_pack()
        pack[3]["excluded_hours"] = [0, 23]
        self.assert_pack_accepted(pack)

    def test_accepts_empty_excluded_hours(self):
        pack = make_pack()
        pack[3]["excluded_hours"] = []
        self.assert_pack_accepted(pack)

    def test_accepts_excluded_hours_on_a_daily_hourly_entry_without_lookback(self):
        pack = make_pack()
        pack[3]["schedule"] = "daily"
        self.assert_pack_accepted(pack)

    def test_rejects_excluded_hours_together_with_a_lookback(self):
        pack = make_pack()
        pack[3]["schedule"] = "daily"
        pack[3]["lookback_days"] = 7
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].excluded_hours")

    def test_rejects_excluded_hours_on_a_scalar_entry(self):
        pack = make_pack()
        pack[1]["excluded_hours"] = [2]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].excluded_hours")

    def test_rejects_excluded_hours_on_a_top_entry(self):
        pack = make_pack()
        pack[2]["excluded_hours"] = [2]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[2].excluded_hours")

    def test_rejects_excluded_hours_on_a_monitor_entry(self):
        pack = make_pack()
        pack[0]["excluded_hours"] = [2]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[0].excluded_hours")

    def test_rejects_excluded_hours_that_are_not_a_list(self):
        pack = make_pack()
        pack[3]["excluded_hours"] = 2
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].excluded_hours")

    def test_rejects_an_excluded_hour_of_24(self):
        pack = make_pack()
        pack[3]["excluded_hours"] = [0, 24]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].excluded_hours[1]")

    def test_rejects_a_negative_excluded_hour(self):
        pack = make_pack()
        pack[3]["excluded_hours"] = [-1]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].excluded_hours[0]")

    def test_rejects_a_boolean_excluded_hour(self):
        pack = make_pack()
        pack[3]["excluded_hours"] = [True]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].excluded_hours[0]")

    def test_rejects_a_fractional_excluded_hour(self):
        pack = make_pack()
        pack[3]["excluded_hours"] = [1.5]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].excluded_hours[0]")


class LookbackDaysTest(PackCase):
    def test_accepts_a_daily_entry_without_lookback(self):
        pack = make_pack()
        del pack[2]["lookback_days"]
        self.assert_pack_accepted(pack)

    def test_accepts_a_lookback_of_one_day(self):
        pack = make_pack()
        pack[2]["lookback_days"] = 1
        self.assert_pack_accepted(pack)

    def test_accepts_a_lookback_of_31_days(self):
        pack = make_pack()
        pack[2]["lookback_days"] = 31
        self.assert_pack_accepted(pack)

    def test_accepts_a_lookback_on_a_daily_hourly_entry(self):
        pack = make_pack()
        pack[3]["schedule"] = "daily"
        del pack[3]["excluded_hours"]
        pack[3]["lookback_days"] = 7
        self.assert_pack_accepted(pack)

    def test_accepts_a_lookback_on_a_daily_scalar_entry(self):
        pack = make_pack()
        pack[1]["schedule"] = "daily"
        pack[1]["lookback_days"] = 7
        self.assert_pack_accepted(pack)

    def test_rejects_a_lookback_of_zero_days(self):
        pack = make_pack()
        pack[2]["lookback_days"] = 0
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[2].lookback_days")

    def test_rejects_a_lookback_of_32_days(self):
        pack = make_pack()
        pack[2]["lookback_days"] = 32
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[2].lookback_days")

    def test_rejects_a_boolean_lookback(self):
        pack = make_pack()
        pack[2]["lookback_days"] = True
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[2].lookback_days")

    def test_rejects_a_fractional_lookback(self):
        pack = make_pack()
        pack[2]["lookback_days"] = 1.5
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[2].lookback_days")

    def test_rejects_a_lookback_on_an_every_run_entry(self):
        pack = make_pack()
        pack[1]["lookback_days"] = 7
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].lookback_days")

    def test_rejects_a_lookback_on_a_daily_monitor_entry(self):
        pack = make_pack()
        pack[0]["schedule"] = "daily"
        pack[0]["lookback_days"] = 7
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[0].lookback_days")


class TrendDaysTest(PackCase):
    def with_trend(self, index, days=7, **fields):
        pack = make_pack()
        pack[index].update(trend_days=days, **fields)
        return pack

    def test_accepts_the_smallest_trend_on_a_scalar_entry(self):
        self.assert_pack_accepted(self.with_trend(1, 7))

    def test_accepts_the_largest_trend_on_a_scalar_entry(self):
        self.assert_pack_accepted(self.with_trend(1, 31))

    def test_accepts_a_trend_on_an_hourly_entry(self):
        self.assert_pack_accepted(self.with_trend(3, 30))

    def test_accepts_a_trend_on_a_daily_entry_without_lookback(self):
        self.assert_pack_accepted(self.with_trend(1, 30, schedule="daily"))

    def test_accepts_the_max_aggregator(self):
        self.assert_pack_accepted(self.with_trend(1, aggregator="max"))

    def test_accepts_the_min_aggregator(self):
        self.assert_pack_accepted(self.with_trend(1, aggregator="min"))

    def test_accepts_the_sum_aggregator(self):
        self.assert_pack_accepted(self.with_trend(1, aggregator="sum"))

    def test_accepts_the_avg_aggregator(self):
        self.assert_pack_accepted(self.with_trend(1, aggregator="avg"))

    def test_accepts_the_last_aggregator(self):
        self.assert_pack_accepted(self.with_trend(1, aggregator="last"))

    def test_accepts_any_aggregator_without_a_trend(self):
        pack = make_pack()
        pack[1]["aggregator"] = "p95"
        self.assert_pack_accepted(pack)

    def test_rejects_a_trend_of_6_days(self):
        self.assert_pack_error(self.with_trend(1, 6), "routines.prod-watch.query_pack[1].trend_days")

    def test_rejects_a_trend_of_32_days(self):
        self.assert_pack_error(self.with_trend(1, 32), "routines.prod-watch.query_pack[1].trend_days")

    def test_rejects_a_boolean_trend(self):
        self.assert_pack_error(self.with_trend(1, True), "routines.prod-watch.query_pack[1].trend_days")

    def test_rejects_a_fractional_trend(self):
        self.assert_pack_error(self.with_trend(1, 7.5), "routines.prod-watch.query_pack[1].trend_days")

    def test_rejects_a_trend_on_a_top_entry(self):
        pack = self.with_trend(2, 7)
        del pack[2]["lookback_days"]
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[2].trend_days")

    def test_rejects_a_trend_on_a_monitor_entry(self):
        self.assert_pack_error(self.with_trend(0, 7), "routines.prod-watch.query_pack[0].trend_days")

    def test_rejects_a_trend_next_to_a_lookback(self):
        pack = self.with_trend(1, 7, schedule="daily", lookback_days=7)
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].trend_days")

    def test_rejects_a_trend_with_an_aggregator_outside_the_five(self):
        self.assert_pack_error(self.with_trend(1, 7, aggregator="p95"), "routines.prod-watch.query_pack[1].aggregator")


class EmptyReadTest(PackCase):
    def with_empty(self, index, value):
        pack = make_pack()
        pack[index]["empty"] = value
        return pack

    def test_accepts_zero_on_a_scalar_entry(self):
        self.assert_pack_accepted(self.with_empty(1, "zero"))

    def test_accepts_gap_on_a_scalar_entry(self):
        self.assert_pack_accepted(self.with_empty(1, "gap"))

    def test_accepts_zero_on_a_top_entry(self):
        self.assert_pack_accepted(self.with_empty(2, "zero"))

    def test_accepts_zero_next_to_a_trend(self):
        pack = self.with_empty(1, "zero")
        pack[1]["trend_days"] = 7
        self.assert_pack_accepted(pack)

    def test_rejects_a_value_outside_gap_and_zero(self):
        self.assert_pack_error(self.with_empty(1, "none"), "routines.prod-watch.query_pack[1].empty")

    def test_rejects_a_boolean_value(self):
        self.assert_pack_error(self.with_empty(1, True), "routines.prod-watch.query_pack[1].empty")

    def test_rejects_a_value_on_a_top_entry_outside_gap_and_zero(self):
        self.assert_pack_error(self.with_empty(2, "ignore"), "routines.prod-watch.query_pack[2].empty")

    def test_rejects_the_option_on_an_hourly_entry(self):
        self.assert_pack_error(self.with_empty(3, "zero"), "routines.prod-watch.query_pack[3].empty")

    def test_rejects_the_default_on_an_hourly_entry(self):
        self.assert_pack_error(self.with_empty(3, "gap"), "routines.prod-watch.query_pack[3].empty")

    def test_rejects_the_option_on_a_monitor_entry(self):
        self.assert_pack_error(self.with_empty(0, "zero"), "routines.prod-watch.query_pack[0].empty")


class GroupKeyPrefixTest(PackCase):
    def test_rejects_a_key_after_a_top_entry_that_starts_with_its_key_and_a_dash(self):
        pack = make_pack()
        pack[3]["key"] = "top-endpoints-queue"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].key")

    def test_rejects_a_key_before_a_top_entry_that_starts_with_its_key_and_a_dash(self):
        pack = make_pack()
        pack[1]["key"] = "top-endpoints-errors"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[1].key")

    def test_rejects_a_top_entry_key_under_another_top_entry_key(self):
        pack = make_pack()
        pack[3]["read"] = "top"
        pack[3]["top"] = 5
        del pack[3]["excluded_hours"]
        pack[3]["key"] = "top-endpoints-slow"
        self.assert_pack_error(pack, "routines.prod-watch.query_pack[3].key")

    def test_accepts_a_key_that_extends_a_top_entry_key_without_a_dash(self):
        pack = make_pack()
        pack[3]["key"] = "top-endpoints2"
        self.assert_pack_accepted(pack)

    def test_accepts_a_key_that_starts_with_a_scalar_entry_key_and_a_dash(self):
        pack = make_pack()
        pack[3]["key"] = "error-rate-queue"
        self.assert_pack_accepted(pack)


class RoutineRulesTest(PackCase):
    def test_accepts_routine_rules(self):
        self.assert_pack_accepted(make_pack(), rules=make_rules())

    def test_accepts_an_empty_rule_list(self):
        self.assert_pack_accepted(make_pack(), rules=[])

    def test_accepts_a_routine_rule_of_500_characters(self):
        self.assert_pack_accepted(make_pack(), rules=["r" * 500])

    def test_rejects_routine_rules_that_are_not_a_list(self):
        self.assert_pack_error(make_pack(), "routines.prod-watch.rules", rules="A monitor in Alert is High.")

    def test_rejects_null_routine_rules(self):
        with self.assertRaises(roles.PackError) as caught:
            roles.validate_pack(make_pack(), pack_sources(), routine=ROUTINE, rules=None)
        self.assertEqual(str(caught.exception), "routines.prod-watch.rules: must be a list")

    def test_rejects_a_whitespace_only_routine_rule(self):
        self.assert_pack_error(make_pack(), "routines.prod-watch.rules[1]", rules=[make_rules()[0], " \n\t"])

    def test_rejects_an_empty_routine_rule(self):
        self.assert_pack_error(make_pack(), "routines.prod-watch.rules[1]", rules=[make_rules()[0], ""])

    def test_rejects_a_routine_rule_that_is_not_a_string(self):
        self.assert_pack_error(make_pack(), "routines.prod-watch.rules[0]", rules=[{"rule": "x"}])

    def test_rejects_a_routine_rule_of_501_characters(self):
        self.assert_pack_error(make_pack(), "routines.prod-watch.rules[0]", rules=["r" * 501])

    def test_names_the_rules_path_alone_without_a_routine(self):
        with self.assertRaises(roles.PackError) as caught:
            roles.validate_pack(make_pack(), pack_sources(), rules=["r" * 501])
        self.assertEqual(str(caught.exception).partition(": ")[0], "rules[0]")


class CollectionCase(unittest.TestCase):
    def assert_collection_error(self, doc, path):
        with self.assertRaises(ValueError) as caught:
            roles.validate_collection(doc)
        self.assertEqual(str(caught.exception).partition(": ")[0], path)


class ValidateCollectionTest(CollectionCase):
    def test_accepts_a_monitors_collection(self):
        self.assertIsNone(roles.validate_collection(monitors_collection()))

    def test_accepts_a_metrics_collection(self):
        doc = make_collection("observability", metrics_records(), {"metrics": {"error-rate": 7.5, "hourly-queue": None}})
        self.assertIsNone(roles.validate_collection(doc))

    def test_accepts_a_document_store_collection(self):
        doc = make_collection("document_store", pages_records(), pages_cursor(), transport="mcp")
        self.assertIsNone(roles.validate_collection(doc))

    def test_accepts_a_chat_collection(self):
        doc = make_collection("chat", messages_records(), {"ts": {"chan-alerts": "1780000000.000100"}}, place="cloud")
        self.assertIsNone(roles.validate_collection(doc))

    def test_accepts_a_code_host_collection(self):
        doc = make_collection("code_host", code_records(), {"updated_at": "2026-10-02T09:00:00Z"})
        self.assertIsNone(roles.validate_collection(doc))

    def test_accepts_a_source_not_read_with_empty_records_and_no_stored_cursor(self):
        self.assertIsNone(roles.validate_collection(unread_collection()))

    def test_accepts_a_source_not_read_that_keeps_its_stored_cursor(self):
        self.assertIsNone(roles.validate_collection(unread_collection(cursor=monitors_cursor())))

    def test_accepts_a_metrics_source_not_read(self):
        reason = "partial: page cap"
        doc = make_collection(
            "observability",
            {"metrics": []},
            {"metrics": {"error-rate": 7.5}},
            source="metrics",
            read=False,
            reason=reason,
            entries={
                "error-rate": {"status": "failed", "reason": reason},
                "top-endpoints": {"status": "deferred", "reason": "not due"},
            },
        )
        self.assertIsNone(roles.validate_collection(doc))

    def test_rejects_a_collection_that_is_not_a_mapping(self):
        self.assert_collection_error([], "collection")

    def test_rejects_a_schema_other_than_one(self):
        self.assert_collection_error(monitors_collection(schema=2), "schema")

    def test_rejects_a_boolean_schema(self):
        self.assert_collection_error(monitors_collection(schema=True), "schema")

    def test_rejects_a_missing_top_level_key(self):
        doc = monitors_collection()
        del doc["provider"]
        self.assert_collection_error(doc, "provider")

    def test_rejects_an_unexpected_top_level_key(self):
        self.assert_collection_error(monitors_collection(kind="monitors"), "kind")

    def test_rejects_an_unknown_role(self):
        self.assert_collection_error(monitors_collection(role="pager"), "role")

    def test_rejects_a_transport_outside_api_and_mcp(self):
        self.assert_collection_error(monitors_collection(transport="ftp"), "transport")

    def test_rejects_a_place_outside_cloud_and_local(self):
        self.assert_collection_error(monitors_collection(place="moon"), "place")

    def test_rejects_a_window_bound_that_is_not_an_integer(self):
        doc = monitors_collection()
        doc["window"]["from_ts"] = "2026-10-01T08:00:00Z"
        self.assert_collection_error(doc, "window.from_ts")

    def test_rejects_a_read_flag_that_is_not_a_boolean(self):
        self.assert_collection_error(monitors_collection(read=1), "read")

    def test_rejects_a_reason_on_a_source_read(self):
        self.assert_collection_error(monitors_collection(reason="slow"), "reason")

    def test_rejects_a_source_not_read_without_reason(self):
        self.assert_collection_error(unread_collection(reason=None), "reason")

    def test_rejects_an_empty_reason_on_a_source_not_read(self):
        self.assert_collection_error(unread_collection(reason=""), "reason")

    def test_rejects_records_on_a_source_not_read(self):
        records = {"monitors": [], "transitions": monitors_records()["transitions"], "discovered": [], "discovery": None}
        self.assert_collection_error(unread_collection(records=records), "records.transitions")

    def test_rejects_a_null_cursor_on_a_source_read(self):
        self.assert_collection_error(monitors_collection(cursor=None), "cursor")

    def test_rejects_an_ok_entry_on_a_source_not_read(self):
        doc = unread_collection()
        doc["entries"]["monitor-" + MONITOR_ID] = {"status": "ok", "reason": None}
        self.assert_collection_error(doc, "entries.monitor-" + MONITOR_ID + ".status")

    def test_rejects_an_entry_status_outside_ok_deferred_failed_and_missing(self):
        doc = monitors_collection()
        doc["entries"]["monitor-" + MONITOR_ID]["status"] = "skipped"
        self.assert_collection_error(doc, "entries.monitor-" + MONITOR_ID + ".status")

    def test_rejects_an_unexpected_key_inside_an_entry(self):
        doc = monitors_collection()
        doc["entries"]["monitor-" + MONITOR_ID]["note"] = "x"
        self.assert_collection_error(doc, "entries.monitor-" + MONITOR_ID + ".note")

    def test_rejects_a_reason_on_an_ok_entry(self):
        doc = monitors_collection()
        doc["entries"]["monitor-" + MONITOR_ID]["reason"] = "fine"
        self.assert_collection_error(doc, "entries.monitor-" + MONITOR_ID + ".reason")

    def test_rejects_a_failed_entry_without_reason(self):
        doc = monitors_collection()
        doc["entries"]["monitor-" + MONITOR_ID] = {"status": "failed", "reason": None}
        self.assert_collection_error(doc, "entries.monitor-" + MONITOR_ID + ".reason")

    def test_accepts_a_missing_entry_on_a_source_read(self):
        doc = monitors_collection()
        doc["entries"]["monitor-" + OTHER_MONITOR_ID] = {"status": "missing", "reason": "not found"}
        self.assertIsNone(roles.validate_collection(doc))

    def test_rejects_a_missing_entry_on_a_source_not_read(self):
        doc = unread_collection()
        doc["entries"]["monitor-" + MONITOR_ID] = {"status": "missing", "reason": "not found"}
        self.assert_collection_error(doc, "entries.monitor-" + MONITOR_ID + ".status")

    def test_rejects_a_missing_entry_without_reason(self):
        doc = monitors_collection()
        doc["entries"]["monitor-" + MONITOR_ID] = {"status": "missing", "reason": None}
        self.assert_collection_error(doc, "entries.monitor-" + MONITOR_ID + ".reason")


class ObservabilityRecordsTest(CollectionCase):
    def metrics_collection(self):
        return make_collection("observability", metrics_records(), {"metrics": {"error-rate": 7.5}})

    def test_rejects_observability_records_of_neither_kind(self):
        self.assert_collection_error(monitors_collection(records={"monitors": []}), "records")

    def test_rejects_a_monitor_state_that_is_not_a_string(self):
        doc = monitors_collection()
        doc["records"]["monitors"][0]["state"] = None
        self.assert_collection_error(doc, "records.monitors[0].state")

    def test_rejects_an_unexpected_monitor_field(self):
        doc = monitors_collection()
        doc["records"]["monitors"][0]["tags"] = []
        self.assert_collection_error(doc, "records.monitors[0].tags")

    def test_accepts_a_metric_with_a_trend_of_days(self):
        doc = make_collection("observability", metrics_records(), {"metrics": {"error-rate": 7.5}})
        self.assertIsNone(roles.validate_collection(doc))

    def test_accepts_a_metric_with_no_trend_and_a_reason(self):
        doc = self.metrics_collection()
        doc["records"]["metrics"][0].update(trend=None, trend_reason="HTTP 503 POST /timeseries")
        self.assertIsNone(roles.validate_collection(doc))

    def test_accepts_a_metric_with_an_empty_trend(self):
        doc = self.metrics_collection()
        doc["records"]["metrics"][0]["trend"] = []
        self.assertIsNone(roles.validate_collection(doc))

    def test_accepts_a_metric_without_trend_and_trend_reason(self):
        doc = self.metrics_collection()
        del doc["records"]["metrics"][0]["trend"]
        del doc["records"]["metrics"][0]["trend_reason"]
        self.assertIsNone(roles.validate_collection(doc))

    def test_rejects_a_trend_that_is_not_a_list(self):
        doc = self.metrics_collection()
        doc["records"]["metrics"][0]["trend"] = {"2026-10-01": 7.5}
        self.assert_collection_error(doc, "records.metrics[0].trend")

    def test_rejects_a_trend_day_that_is_not_a_calendar_day(self):
        doc = self.metrics_collection()
        doc["records"]["metrics"][0]["trend"][0]["day"] = "2026-13-01"
        self.assert_collection_error(doc, "records.metrics[0].trend[0].day")

    def test_rejects_a_trend_day_with_a_time(self):
        doc = self.metrics_collection()
        doc["records"]["metrics"][0]["trend"][1]["day"] = "2026-10-01T00:00:00Z"
        self.assert_collection_error(doc, "records.metrics[0].trend[1].day")

    def test_rejects_a_trend_value_that_is_null(self):
        doc = self.metrics_collection()
        doc["records"]["metrics"][0]["trend"][1]["value"] = None
        self.assert_collection_error(doc, "records.metrics[0].trend[1].value")

    def test_rejects_a_trend_point_with_an_extra_field(self):
        doc = self.metrics_collection()
        doc["records"]["metrics"][0]["trend"][0]["count"] = 3
        self.assert_collection_error(doc, "records.metrics[0].trend[0].count")

    def test_rejects_a_trend_reason_that_is_not_a_string(self):
        doc = self.metrics_collection()
        doc["records"]["metrics"][0]["trend_reason"] = 5
        self.assert_collection_error(doc, "records.metrics[0].trend_reason")

    def test_rejects_a_boolean_transition_time(self):
        doc = monitors_collection()
        doc["records"]["transitions"][0]["first_ts_ms"] = True
        self.assert_collection_error(doc, "records.transitions[0].first_ts_ms")

    def test_rejects_a_transition_title(self):
        doc = monitors_collection()
        doc["records"]["transitions"][0]["title"] = "Deploy"
        self.assert_collection_error(doc, "records.transitions[0].title")

    def test_rejects_a_transition_without_a_monitor(self):
        doc = monitors_collection()
        del doc["records"]["transitions"][0]["monitor"]
        self.assert_collection_error(doc, "records.transitions[0].monitor")

    def test_rejects_a_transition_count_that_is_not_an_integer(self):
        doc = monitors_collection()
        doc["records"]["transitions"][0]["count"] = "2"
        self.assert_collection_error(doc, "records.transitions[0].count")

    def test_rejects_raw_events_in_the_records(self):
        doc = monitors_collection()
        doc["records"]["events"] = []
        self.assert_collection_error(doc, "records")

    def test_rejects_a_monitors_cursor_timestamp_that_is_not_an_integer(self):
        doc = monitors_collection()
        doc["cursor"]["events_ts_ms"] = "now"
        self.assert_collection_error(doc, "cursor.events_ts_ms")

    def test_rejects_a_monitors_cursor_state_that_is_not_a_string(self):
        doc = monitors_collection()
        doc["cursor"]["monitors"][MONITOR_ID] = 1
        self.assert_collection_error(doc, "cursor.monitors." + MONITOR_ID)

    def test_rejects_a_metric_value_that_is_not_a_number(self):
        doc = make_collection("observability", metrics_records(), {"metrics": {}})
        doc["records"]["metrics"][0]["value"] = "7.5"
        self.assert_collection_error(doc, "records.metrics[0].value")

    def test_rejects_an_hourly_bucket_without_integer_ts(self):
        doc = make_collection("observability", metrics_records(), {"metrics": {}})
        doc["records"]["metrics"][0]["hourly"][0]["ts"] = 1.5
        self.assert_collection_error(doc, "records.metrics[0].hourly[0].ts")

    def test_rejects_a_group_name_that_is_not_a_string(self):
        doc = make_collection("observability", metrics_records(), {"metrics": {}})
        doc["records"]["metrics"][0]["groups"][1]["group"] = None
        self.assert_collection_error(doc, "records.metrics[0].groups[1].group")

    def test_accepts_a_metric_record_without_daily_buckets(self):
        doc = make_collection("observability", metrics_records(), {"metrics": {}})
        del doc["records"]["metrics"][0]["daily"]
        self.assertIsNone(roles.validate_collection(doc))

    def test_rejects_daily_buckets_that_are_not_a_list(self):
        doc = make_collection("observability", metrics_records(), {"metrics": {}})
        doc["records"]["metrics"][0]["daily"] = None
        self.assert_collection_error(doc, "records.metrics[0].daily")

    def test_rejects_a_daily_bucket_without_integer_ts(self):
        doc = make_collection("observability", metrics_records(), {"metrics": {}})
        doc["records"]["metrics"][0]["daily"][0]["ts"] = "2026-10-01"
        self.assert_collection_error(doc, "records.metrics[0].daily[0].ts")

    def test_rejects_a_daily_bucket_value_that_is_not_a_number(self):
        doc = make_collection("observability", metrics_records(), {"metrics": {}})
        doc["records"]["metrics"][0]["daily"][0]["value"] = "6"
        self.assert_collection_error(doc, "records.metrics[0].daily[0].value")

    def test_rejects_an_unexpected_daily_bucket_field(self):
        doc = make_collection("observability", metrics_records(), {"metrics": {}})
        doc["records"]["metrics"][0]["daily"][0]["count"] = 1
        self.assert_collection_error(doc, "records.metrics[0].daily[0].count")

    def test_rejects_discovered_records_on_a_metrics_collection(self):
        records = {**metrics_records(), "discovered": []}
        self.assert_collection_error(make_collection("observability", records, {"metrics": {}}), "records")

    def test_rejects_a_metrics_cursor_value_that_is_not_a_number(self):
        doc = make_collection("observability", metrics_records(), {"metrics": {"error-rate": "high"}})
        self.assert_collection_error(doc, "cursor.metrics.error-rate")

    def test_rejects_a_monitors_cursor_on_metrics_records(self):
        doc = make_collection("observability", metrics_records(), monitors_cursor())
        self.assert_collection_error(doc, "cursor.metrics")


class DiscoveryRecordsTest(CollectionCase):
    def test_rejects_a_monitor_without_priority(self):
        doc = monitors_collection()
        del doc["records"]["monitors"][0]["priority"]
        self.assert_collection_error(doc, "records.monitors[0].priority")

    def test_rejects_a_monitors_collection_without_discovered(self):
        doc = monitors_collection()
        del doc["records"]["discovered"]
        self.assert_collection_error(doc, "records.discovered")

    def test_rejects_a_monitors_collection_without_discovery(self):
        doc = monitors_collection()
        del doc["records"]["discovery"]
        self.assert_collection_error(doc, "records.discovery")

    def test_rejects_a_source_not_read_without_discovered(self):
        records = {"monitors": [], "transitions": [], "discovery": None}
        self.assert_collection_error(unread_collection(records=records), "records.discovered")

    def test_rejects_a_source_not_read_without_discovery(self):
        records = {"monitors": [], "transitions": [], "discovered": []}
        self.assert_collection_error(unread_collection(records=records), "records.discovery")

    def test_accepts_an_empty_discovered_list_with_a_discovery_read(self):
        doc = monitors_collection()
        doc["records"]["discovered"] = []
        self.assertIsNone(roles.validate_collection(doc))

    def test_accepts_a_monitor_without_priority_value(self):
        doc = monitors_collection()
        doc["records"]["monitors"][0]["priority"] = None
        self.assertIsNone(roles.validate_collection(doc))

    def test_rejects_a_monitor_priority_that_is_not_an_integer(self):
        doc = monitors_collection()
        doc["records"]["monitors"][0]["priority"] = "P2"
        self.assert_collection_error(doc, "records.monitors[0].priority")

    def test_rejects_a_boolean_monitor_priority(self):
        doc = monitors_collection()
        doc["records"]["monitors"][0]["priority"] = True
        self.assert_collection_error(doc, "records.monitors[0].priority")

    def test_rejects_discovered_records_that_are_not_a_list(self):
        doc = monitors_collection()
        doc["records"]["discovered"] = None
        self.assert_collection_error(doc, "records.discovered")

    def test_rejects_a_discovered_monitor_without_priority(self):
        doc = monitors_collection()
        del doc["records"]["discovered"][0]["priority"]
        self.assert_collection_error(doc, "records.discovered[0].priority")

    def test_rejects_a_discovered_monitor_priority_that_is_not_an_integer(self):
        doc = monitors_collection()
        doc["records"]["discovered"][0]["priority"] = 1.5
        self.assert_collection_error(doc, "records.discovered[0].priority")

    def test_rejects_a_discovered_monitor_state_that_is_not_a_string(self):
        doc = monitors_collection()
        doc["records"]["discovered"][0]["state"] = None
        self.assert_collection_error(doc, "records.discovered[0].state")

    def test_rejects_a_discovered_monitor_without_link(self):
        doc = monitors_collection()
        del doc["records"]["discovered"][0]["link"]
        self.assert_collection_error(doc, "records.discovered[0].link")

    def test_rejects_an_unexpected_discovered_monitor_field(self):
        doc = monitors_collection()
        doc["records"]["discovered"][0]["tags"] = []
        self.assert_collection_error(doc, "records.discovered[0].tags")

    def test_accepts_a_discovery_not_read_with_a_reason(self):
        doc = monitors_collection()
        doc["records"]["discovery"] = {"read": False, "reason": "page cap"}
        self.assertIsNone(roles.validate_collection(doc))

    def test_accepts_a_discovery_marking_the_event_monitors_capped(self):
        doc = monitors_collection()
        doc["records"]["discovery"]["event_monitors_capped"] = True
        self.assertIsNone(roles.validate_collection(doc))

    def test_rejects_an_event_monitors_cap_flag_that_is_not_a_boolean(self):
        doc = monitors_collection()
        doc["records"]["discovery"]["event_monitors_capped"] = "yes"
        self.assert_collection_error(doc, "records.discovery.event_monitors_capped")

    def test_rejects_a_discovery_that_is_not_a_mapping(self):
        doc = monitors_collection()
        doc["records"]["discovery"] = True
        self.assert_collection_error(doc, "records.discovery")

    def test_rejects_a_null_discovery_on_a_source_read(self):
        doc = monitors_collection()
        doc["records"]["discovery"] = None
        self.assert_collection_error(doc, "records.discovery")

    def test_rejects_a_discovery_read_flag_that_is_not_a_boolean(self):
        doc = monitors_collection()
        doc["records"]["discovery"]["read"] = "yes"
        self.assert_collection_error(doc, "records.discovery.read")

    def test_rejects_a_discovery_without_reason(self):
        doc = monitors_collection()
        del doc["records"]["discovery"]["reason"]
        self.assert_collection_error(doc, "records.discovery.reason")

    def test_rejects_an_unexpected_discovery_field(self):
        doc = monitors_collection()
        doc["records"]["discovery"]["pages"] = 2
        self.assert_collection_error(doc, "records.discovery.pages")

    def test_rejects_a_reason_on_a_discovery_read(self):
        doc = monitors_collection()
        doc["records"]["discovery"]["reason"] = "slow"
        self.assert_collection_error(doc, "records.discovery.reason")

    def test_rejects_a_discovery_not_read_without_reason(self):
        doc = monitors_collection()
        doc["records"]["discovery"] = {"read": False, "reason": None}
        self.assert_collection_error(doc, "records.discovery.reason")

    def test_rejects_a_discovery_not_read_with_an_empty_reason(self):
        doc = monitors_collection()
        doc["records"]["discovery"] = {"read": False, "reason": ""}
        self.assert_collection_error(doc, "records.discovery.reason")

    def test_accepts_a_null_discovery_and_no_discovered_monitor_on_a_source_not_read(self):
        records = {"monitors": [], "transitions": [], "discovered": [], "discovery": None}
        self.assertIsNone(roles.validate_collection(unread_collection(records=records)))

    def test_rejects_a_discovery_on_a_source_not_read(self):
        records = {"monitors": [], "transitions": [], "discovered": [], "discovery": {"read": False, "reason": "skipped"}}
        self.assert_collection_error(unread_collection(records=records), "records.discovery")

    def test_rejects_discovered_monitors_on_a_source_not_read(self):
        records = {"monitors": [], "transitions": [], "discovered": monitors_records()["discovered"], "discovery": None}
        self.assert_collection_error(unread_collection(records=records), "records.discovered")

    def test_rejects_an_unknown_records_key_beside_monitors_and_transitions(self):
        doc = monitors_collection()
        doc["records"]["alerts"] = []
        self.assert_collection_error(doc, "records")


class DocumentStoreRecordsTest(CollectionCase):
    def pages_collection(self):
        return make_collection("document_store", pages_records(), pages_cursor())

    def test_rejects_a_last_edited_without_utc_z(self):
        doc = self.pages_collection()
        doc["records"]["pages"][0]["last_edited"] = "2026-10-01T08:00:00+02:00"
        self.assert_collection_error(doc, "records.pages[0].last_edited")

    def test_rejects_a_block_type_outside_the_six_types(self):
        doc = self.pages_collection()
        doc["records"]["pages"][0]["blocks"][0]["type"] = "callout"
        self.assert_collection_error(doc, "records.pages[0].blocks[0].type")

    def test_rejects_a_table_block_without_rows(self):
        doc = self.pages_collection()
        doc["records"]["pages"][0]["blocks"][1]["rows"] = None
        self.assert_collection_error(doc, "records.pages[0].blocks[1].rows")

    def test_rejects_rows_on_a_block_that_is_not_a_table(self):
        doc = self.pages_collection()
        doc["records"]["pages"][0]["blocks"][0]["rows"] = [["Mutes"]]
        self.assert_collection_error(doc, "records.pages[0].blocks[0].rows")

    def test_accepts_a_to_do_block_with_either_checked_state(self):
        doc = self.pages_collection()
        doc["records"]["pages"][0]["blocks"][2]["checked"] = False
        self.assertIsNone(roles.validate_collection(doc))

    def test_accepts_a_block_without_checked(self):
        doc = self.pages_collection()
        del doc["records"]["pages"][0]["blocks"][2]["checked"]
        self.assertIsNone(roles.validate_collection(doc))

    def test_rejects_a_checked_that_is_not_a_boolean(self):
        doc = self.pages_collection()
        doc["records"]["pages"][0]["blocks"][2]["checked"] = "yes"
        self.assert_collection_error(doc, "records.pages[0].blocks[2].checked")

    def test_rejects_checked_on_a_block_that_is_not_a_list(self):
        doc = self.pages_collection()
        doc["records"]["pages"][0]["blocks"][0]["checked"] = True
        self.assert_collection_error(doc, "records.pages[0].blocks[0].checked")

    def test_rejects_a_table_cell_that_is_not_a_string(self):
        doc = self.pages_collection()
        doc["records"]["pages"][0]["blocks"][1]["rows"][1][1] = None
        self.assert_collection_error(doc, "records.pages[0].blocks[1].rows[1][1]")

    def test_rejects_a_cursor_edit_time_without_utc_z(self):
        doc = self.pages_collection()
        doc["cursor"]["pages"][page_id()] = "2026-10-01"
        self.assert_collection_error(doc, "cursor.pages." + page_id())

    def test_rejects_the_former_single_edit_time_cursor(self):
        doc = self.pages_collection()
        doc["cursor"] = {"last_edited": UTC_EDIT}
        self.assert_collection_error(doc, "cursor.pages")

    def test_rejects_a_page_without_a_link(self):
        doc = self.pages_collection()
        del doc["records"]["pages"][0]["link"]
        self.assert_collection_error(doc, "records.pages[0].link")

    def test_rejects_a_link_that_is_not_a_string(self):
        doc = self.pages_collection()
        doc["records"]["pages"][0]["link"] = None
        self.assert_collection_error(doc, "records.pages[0].link")

    def test_accepts_a_cursor_with_an_edit_time_per_page(self):
        doc = self.pages_collection()
        doc["cursor"] = {"pages": {page_id(): UTC_EDIT, "page-cdcdcdcd": "2026-10-02T08:00:00Z"}}
        self.assertIsNone(roles.validate_collection(doc))

    def test_accepts_one_entry_per_page_with_the_existing_statuses(self):
        doc = self.pages_collection()
        doc["entries"] = {
            page_id(): {"status": "ok", "reason": None},
            "page-cdcdcdcd": {"status": "deferred", "reason": "unchanged"},
            "page-efefefef": {"status": "failed", "reason": "not found or not shared"},
        }
        self.assertIsNone(roles.validate_collection(doc))

    def test_rejects_an_ok_page_entry_with_a_reason(self):
        doc = self.pages_collection()
        doc["entries"] = {page_id(): {"status": "ok", "reason": "read"}}
        self.assert_collection_error(doc, f"entries.{page_id()}.reason")

    def test_rejects_a_failed_page_entry_without_a_reason(self):
        doc = self.pages_collection()
        doc["entries"] = {page_id(): {"status": "failed", "reason": None}}
        self.assert_collection_error(doc, f"entries.{page_id()}.reason")

    def test_rejects_an_ok_page_entry_when_the_source_was_not_read(self):
        doc = self.pages_collection()
        doc.update(read=False, reason="HTTP 503", records={"pages": []})
        doc["entries"] = {page_id(): {"status": "ok", "reason": None}}
        self.assert_collection_error(doc, f"entries.{page_id()}.status")


class ChatRecordsTest(CollectionCase):
    def messages_collection(self):
        return make_collection("chat", messages_records(), {"ts": {"chan-alerts": "1780000000.000100"}})

    def test_rejects_a_message_carrying_a_reply_count(self):
        doc = self.messages_collection()
        doc["records"]["messages"][0]["replies"] = 2
        self.assert_collection_error(doc, "records.messages[0].replies")

    def test_accepts_a_reply_carrying_the_ts_of_its_root(self):
        doc = self.messages_collection()
        doc["records"]["messages"][0]["thread_ts"] = "1779999000.000100"
        self.assertIsNone(roles.validate_collection(doc))

    def test_rejects_a_message_without_a_thread_ts(self):
        doc = self.messages_collection()
        del doc["records"]["messages"][0]["thread_ts"]
        self.assert_collection_error(doc, "records.messages[0].thread_ts")

    def test_rejects_a_thread_ts_that_is_not_a_string(self):
        doc = self.messages_collection()
        doc["records"]["messages"][0]["thread_ts"] = 1779999000
        self.assert_collection_error(doc, "records.messages[0].thread_ts")

    def test_accepts_one_entry_per_channel_with_the_existing_statuses(self):
        doc = self.messages_collection()
        doc["entries"] = {
            "chan-alerts": {"status": "ok", "reason": None},
            "chan-deploys": {"status": "failed", "reason": "channel_not_found"},
            "chan-old": {"status": "deferred", "reason": "archived"},
        }
        self.assertIsNone(roles.validate_collection(doc))

    def test_rejects_an_ok_channel_entry_with_a_reason(self):
        doc = self.messages_collection()
        doc["entries"] = {"chan-alerts": {"status": "ok", "reason": "read"}}
        self.assert_collection_error(doc, "entries.chan-alerts.reason")

    def test_rejects_a_failed_channel_entry_without_a_reason(self):
        doc = self.messages_collection()
        doc["entries"] = {"chan-alerts": {"status": "failed", "reason": None}}
        self.assert_collection_error(doc, "entries.chan-alerts.reason")

    def test_rejects_a_channel_status_outside_the_existing_four(self):
        doc = self.messages_collection()
        doc["entries"] = {"chan-alerts": {"status": "archived", "reason": "archived"}}
        self.assert_collection_error(doc, "entries.chan-alerts.status")

    def test_rejects_a_missing_channel_entry_when_the_source_was_not_read(self):
        doc = self.messages_collection()
        doc.update(read=False, reason="HTTP 503", records={"messages": []})
        doc["entries"] = {"chan-alerts": {"status": "missing", "reason": "not found"}}
        self.assert_collection_error(doc, "entries.chan-alerts.status")

    def test_rejects_a_cursor_ts_that_is_not_a_string(self):
        doc = self.messages_collection()
        doc["cursor"]["ts"]["chan-alerts"] = 17
        self.assert_collection_error(doc, "cursor.ts.chan-alerts")


class CodeHostRecordsTest(CollectionCase):
    def code_collection(self):
        return make_collection("code_host", code_records(), {"updated_at": "2026-10-02T09:00:00Z"})

    def test_rejects_a_draft_flag_that_is_not_a_boolean(self):
        doc = self.code_collection()
        doc["records"]["pull_requests"][0]["draft"] = "no"
        self.assert_collection_error(doc, "records.pull_requests[0].draft")

    def test_rejects_a_pull_request_number_that_is_not_an_integer(self):
        doc = self.code_collection()
        doc["records"]["pull_requests"][0]["number"] = "42"
        self.assert_collection_error(doc, "records.pull_requests[0].number")

    def test_rejects_an_issue_carrying_closed_at(self):
        doc = self.code_collection()
        doc["records"]["issues"][0]["closed_at"] = "2026-10-02T09:00:00Z"
        self.assert_collection_error(doc, "records.issues[0].closed_at")

    def test_rejects_an_issue_with_a_merged_at(self):
        doc = self.code_collection()
        doc["records"]["issues"][0]["merged_at"] = None
        self.assert_collection_error(doc, "records.issues[0].merged_at")

    def test_rejects_a_cursor_updated_at_that_is_not_a_string(self):
        doc = self.code_collection()
        doc["cursor"]["updated_at"] = 0
        self.assert_collection_error(doc, "cursor.updated_at")

    def activity_collection(self, **changes):
        doc = self.code_collection()
        entry = {
            "repo": "acme/service",
            "number": 42,
            "kind": "review",
            "author": "reviewer",
            "at": "2026-10-02T08:30:00Z",
            "state": "APPROVED",
            "text": "Looks good",
        }
        doc["records"]["activity"] = [{**entry, **changes}]
        return doc

    def test_accepts_the_activity_of_a_pull_request(self):
        self.assertIsNone(roles.validate_collection(self.activity_collection()))

    def test_accepts_an_activity_without_a_state(self):
        self.assertIsNone(roles.validate_collection(self.activity_collection(kind="comment", state=None)))

    def test_rejects_an_activity_time_without_the_utc_suffix(self):
        self.assert_collection_error(self.activity_collection(at="2026-10-02 08:30"), "records.activity[0].at")

    def test_rejects_an_activity_text_that_is_not_a_string(self):
        self.assert_collection_error(self.activity_collection(text=None), "records.activity[0].text")


class IssueTrackerContractTest(ConfigCase, CollectionCase):
    SOURCE_PATH = "routines.prod-watch.sources.issues"

    def invalid_option(self, option, value):
        config = tracker_config()
        routine_sources(config)["issues"][option] = value
        return config

    def jql_config(self):
        config = tracker_config()
        source = routine_sources(config)["issues"]
        del source["filter"], source["open_sprints"]
        source["jql"] = "project = PROJ"
        return config

    def test_accepts_a_source_with_a_filter_a_query_and_open_sprints(self):
        self.assertIsNone(roles.validate_config(tracker_config(), ROUTINE, "local", role_of))

    def test_accepts_a_source_with_only_a_filter(self):
        config = tracker_config()
        del routine_sources(config)["issues"]["query"], routine_sources(config)["issues"]["open_sprints"]
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_rejects_a_filter_that_is_not_digits_only(self):
        self.assert_config_error(self.invalid_option("filter", "10042; drop"), self.SOURCE_PATH + ".filter")

    def test_rejects_an_empty_filter(self):
        self.assert_config_error(self.invalid_option("filter", ""), self.SOURCE_PATH + ".filter")

    def test_rejects_a_numeric_filter(self):
        self.assert_config_error(self.invalid_option("filter", 10042), self.SOURCE_PATH + ".filter")

    def test_rejects_a_source_with_neither_a_filter_nor_a_jql(self):
        config = tracker_config()
        del routine_sources(config)["issues"]["filter"]
        self.assert_config_error(config, self.SOURCE_PATH)

    def test_rejects_a_source_with_both_a_filter_and_a_jql(self):
        self.assert_config_error(self.invalid_option("jql", "project = PROJ"), self.SOURCE_PATH)

    def test_accepts_a_source_with_a_jql_and_a_query(self):
        self.assertIsNone(roles.validate_config(self.jql_config(), ROUTINE, "local", role_of))

    def test_accepts_a_jql_source_with_open_sprints_off(self):
        config = self.jql_config()
        routine_sources(config)["issues"]["open_sprints"] = False
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_rejects_open_sprints_on_a_jql_source(self):
        config = self.jql_config()
        routine_sources(config)["issues"]["open_sprints"] = True
        self.assert_config_error(config, self.SOURCE_PATH + ".open_sprints")

    def test_rejects_a_blank_jql(self):
        config = self.jql_config()
        routine_sources(config)["issues"]["jql"] = "  "
        self.assert_config_error(config, self.SOURCE_PATH + ".jql")

    def test_rejects_a_jql_that_is_not_a_string(self):
        config = self.jql_config()
        routine_sources(config)["issues"]["jql"] = ["project = PROJ"]
        self.assert_config_error(config, self.SOURCE_PATH + ".jql")

    def test_rejects_a_query_that_is_not_a_string(self):
        self.assert_config_error(self.invalid_option("query", ["labels = digest"]), self.SOURCE_PATH + ".query")

    def test_rejects_open_sprints_that_is_not_a_boolean(self):
        self.assert_config_error(self.invalid_option("open_sprints", "yes"), self.SOURCE_PATH + ".open_sprints")

    def issues_collection(self, **overrides):
        doc = make_collection("issue_tracker", issues_records(), {"updated": "2026-10-02T09:30:00Z"})
        doc.update(overrides)
        return doc

    def test_accepts_an_issue_collection_with_and_without_a_priority(self):
        self.assertIsNone(roles.validate_collection(self.issues_collection()))

    def test_accepts_a_null_cursor_updated(self):
        self.assertIsNone(roles.validate_collection(self.issues_collection(cursor={"updated": None})))

    def test_accepts_a_source_not_read_with_no_issues(self):
        doc = self.issues_collection(read=False, reason="HTTP 503", records={"issues": []}, cursor=None)
        self.assertIsNone(roles.validate_collection(doc))

    def test_rejects_an_issue_without_a_type(self):
        doc = self.issues_collection()
        del doc["records"]["issues"][0]["type"]
        self.assert_collection_error(doc, "records.issues[0].type")

    def test_rejects_an_issue_with_a_numeric_priority(self):
        doc = self.issues_collection()
        doc["records"]["issues"][0]["priority"] = 2
        self.assert_collection_error(doc, "records.issues[0].priority")

    def test_rejects_a_created_time_without_utc_z(self):
        doc = self.issues_collection()
        doc["records"]["issues"][1]["created"] = "2026-09-02T10:00:00+02:00"
        self.assert_collection_error(doc, "records.issues[1].created")

    def test_rejects_an_updated_time_without_utc_z(self):
        doc = self.issues_collection()
        doc["records"]["issues"][0]["updated"] = "2026-10-02"
        self.assert_collection_error(doc, "records.issues[0].updated")

    def test_rejects_an_open_sprint_flag_that_is_not_a_boolean(self):
        doc = self.issues_collection()
        doc["records"]["issues"][0]["in_open_sprint"] = "yes"
        self.assert_collection_error(doc, "records.issues[0].in_open_sprint")

    def test_rejects_an_issue_carrying_an_assignee(self):
        doc = self.issues_collection()
        doc["records"]["issues"][0]["assignee"] = "someone"
        self.assert_collection_error(doc, "records.issues[0].assignee")

    def test_rejects_a_cursor_updated_without_utc_z(self):
        self.assert_collection_error(self.issues_collection(cursor={"updated": "2026-10-02"}), "cursor.updated")

    def test_rejects_a_cursor_without_updated(self):
        self.assert_collection_error(self.issues_collection(cursor={}), "cursor.updated")


SEARCH_PATH = "routines.prod-watch.sources.chat.searches"


def unit_records():
    message = {
        "user": "U000002",
        "name": "Peer Name",
        "bot": False,
        "ts": "1780000000.000100",
        "root_ts": None,
        "mentions": [],
        "group_mentions": [],
        "text": "hello",
    }
    unit = {"channel": "D000001", "name": "DM", "participants": [{"id": "U000002", "name": "Peer Name"}], "messages": [message]}
    return {**messages_records(), "units": [unit]}


def chat_search(**overrides):
    return {"name": "dms", "filters": "is:dm", "since": "window", **overrides}


def searching_config(*searches, **options):
    config = make_config()
    source = routine_sources(config)["chat"]
    del source["channels"]
    source.update({"owner": "U000001", "searches": list(searches) or [chat_search()], **options})
    return config


class ChatSearchOptionsTest(ConfigCase):
    def test_accepts_a_chat_source_with_searches_only(self):
        self.assertIsNone(roles.validate_config(searching_config(), ROUTINE, "local", role_of))

    def test_accepts_a_search_with_every_option(self):
        search = chat_search(channel_types="im,mpim", keywords=["deploy"], since={"lookback_days": 7})
        config = searching_config(search, chat_search(name="mentions"), reactions=True, search_page_cap=3)
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_accepts_searches_next_to_channels(self):
        config = searching_config()
        routine_sources(config)["chat"]["channels"] = ["chan-alerts"]
        self.assertIsNone(roles.validate_config(config, ROUTINE, "local", role_of))

    def test_rejects_a_chat_source_with_neither_channels_nor_searches(self):
        config = make_config()
        del routine_sources(config)["chat"]["channels"]
        self.assert_config_error(config, "routines.prod-watch.sources.chat")

    def test_rejects_searches_without_an_owner(self):
        config = searching_config()
        del routine_sources(config)["chat"]["owner"]
        self.assert_config_error(config, "routines.prod-watch.sources.chat.owner")

    def test_rejects_reactions_without_an_owner(self):
        config = make_config()
        routine_sources(config)["chat"]["reactions"] = True
        self.assert_config_error(config, "routines.prod-watch.sources.chat.owner")

    def test_rejects_an_empty_search_list(self):
        config = searching_config()
        routine_sources(config)["chat"]["searches"] = []
        self.assert_config_error(config, SEARCH_PATH)

    def test_rejects_a_search_that_is_not_a_mapping(self):
        config = searching_config()
        routine_sources(config)["chat"]["searches"] = ["is:dm"]
        self.assert_config_error(config, SEARCH_PATH + "[0]")

    def test_rejects_a_search_without_a_name(self):
        config = searching_config({"filters": "is:dm", "since": "window"})
        self.assert_config_error(config, SEARCH_PATH + "[0].name")

    def test_rejects_a_duplicate_search_name(self):
        config = searching_config(chat_search(), chat_search())
        self.assert_config_error(config, SEARCH_PATH + "[1].name")

    def test_rejects_a_search_without_filters(self):
        config = searching_config({"name": "dms", "since": "window"})
        self.assert_config_error(config, SEARCH_PATH + "[0].filters")

    def test_rejects_filters_that_are_not_a_string(self):
        config = searching_config(chat_search(filters=["is:dm"]))
        self.assert_config_error(config, SEARCH_PATH + "[0].filters")

    def test_rejects_an_unknown_channel_type(self):
        config = searching_config(chat_search(channel_types="im,thread"))
        self.assert_config_error(config, SEARCH_PATH + "[0].channel_types")

    def test_rejects_keywords_that_are_not_a_list_of_strings(self):
        config = searching_config(chat_search(keywords=["deploy", 7]))
        self.assert_config_error(config, SEARCH_PATH + "[0].keywords[1]")

    def test_rejects_a_search_without_since(self):
        config = searching_config({"name": "dms", "filters": "is:dm"})
        self.assert_config_error(config, SEARCH_PATH + "[0].since")

    def test_rejects_a_since_that_is_neither_window_nor_a_mapping(self):
        config = searching_config(chat_search(since="week"))
        self.assert_config_error(config, SEARCH_PATH + "[0].since")

    def test_rejects_a_lookback_of_zero_days(self):
        config = searching_config(chat_search(since={"lookback_days": 0}))
        self.assert_config_error(config, SEARCH_PATH + "[0].since.lookback_days")

    def test_rejects_a_since_without_lookback_days(self):
        config = searching_config(chat_search(since={}))
        self.assert_config_error(config, SEARCH_PATH + "[0].since.lookback_days")

    def test_rejects_an_unknown_search_key(self):
        config = searching_config(chat_search(keyword=["deploy"]))
        self.assert_config_error(config, SEARCH_PATH + "[0].keyword")

    def test_rejects_reactions_that_are_not_a_boolean(self):
        config = searching_config(reactions="yes")
        self.assert_config_error(config, "routines.prod-watch.sources.chat.reactions")

    def test_rejects_a_search_page_cap_of_zero(self):
        config = searching_config(search_page_cap=0)
        self.assert_config_error(config, "routines.prod-watch.sources.chat.search_page_cap")

    def test_accepts_the_largest_call_cap(self):
        self.assertIsNone(roles.validate_config(searching_config(call_cap=300), ROUTINE, "local", role_of))

    def test_rejects_a_call_cap_of_zero(self):
        self.assert_config_error(searching_config(call_cap=0), "routines.prod-watch.sources.chat.call_cap")

    def test_rejects_a_call_cap_above_300(self):
        self.assert_config_error(searching_config(call_cap=301), "routines.prod-watch.sources.chat.call_cap")

    def test_rejects_a_call_cap_that_is_not_an_integer(self):
        self.assert_config_error(searching_config(call_cap="50"), "routines.prod-watch.sources.chat.call_cap")

    def test_rejects_an_owner_that_is_not_a_string(self):
        config = searching_config(owner=7)
        self.assert_config_error(config, "routines.prod-watch.sources.chat.owner")

    def test_accepts_a_chat_collection_with_units(self):
        doc = make_collection("chat", unit_records(), {"ts": {}}, place="cloud")
        self.assertIsNone(roles.validate_collection(doc))

    def test_accepts_a_unit_message_with_the_owner_reaction(self):
        records = unit_records()
        records["units"][0]["messages"][0]["owner_reacted"] = False
        self.assertIsNone(roles.validate_collection(make_collection("chat", records, {"ts": {}})))

    def test_rejects_a_unit_message_without_its_bot_flag(self):
        records = unit_records()
        del records["units"][0]["messages"][0]["bot"]
        with self.assertRaises(ValueError) as caught:
            roles.validate_collection(make_collection("chat", records, {"ts": {}}))
        self.assertEqual(str(caught.exception).partition(": ")[0], "records.units[0].messages[0].bot")

    def test_rejects_a_unit_message_without_its_user_mentions(self):
        records = unit_records()
        del records["units"][0]["messages"][0]["mentions"]
        with self.assertRaises(ValueError) as caught:
            roles.validate_collection(make_collection("chat", records, {"ts": {}}))
        self.assertEqual(str(caught.exception).partition(": ")[0], "records.units[0].messages[0].mentions")

    def test_rejects_a_unit_message_with_group_mentions_that_are_not_a_list(self):
        records = unit_records()
        records["units"][0]["messages"][0]["group_mentions"] = "S000001"
        with self.assertRaises(ValueError) as caught:
            roles.validate_collection(make_collection("chat", records, {"ts": {}}))
        self.assertEqual(str(caught.exception).partition(": ")[0], "records.units[0].messages[0].group_mentions")


class DumpTest(unittest.TestCase):
    def test_writes_sorted_indented_utf8_json_with_a_trailing_newline(self):
        expected = '{\n  "a": [\n    1\n  ],\n  "b": "café"\n}\n'.encode("utf-8")
        self.assertEqual(state.dump({"b": "café", "a": [1]}), expected)

    def test_round_trips_through_json(self):
        doc = monitors_collection()
        self.assertEqual(json.loads(state.dump(doc).decode("utf-8")), doc)


class ChecksumTest(unittest.TestCase):
    def test_hashes_a_payload_with_escaped_non_ascii_characters(self):
        payload = '{"ok":true,"note":"caf\\u00e9 \\ud83d\\ude00"}'
        self.assertEqual(roles.fnv1a32(payload), "6bf244b6")

    def test_hashes_a_parameter_text(self):
        text = '{"window":{"from_ts":1,"to_ts":2},"note":"caf\\u00e9 \\ud83d\\ude00"}'
        self.assertEqual(roles.fnv1a32(text), "36619652")

    def test_hashes_a_text_carrying_an_escaped_lone_surrogate(self):
        self.assertEqual(roles.fnv1a32('{"text":"\\ud800"}'), "2e563329")

    def test_hashes_the_empty_string_to_the_offset_basis(self):
        self.assertEqual(roles.fnv1a32(""), "811c9dc5")

    def test_rejects_non_ascii_text(self):
        with self.assertRaises(ValueError):
            roles.fnv1a32("café")


class ParamsTextTest(unittest.TestCase):
    def test_writes_sorted_compact_ascii_json(self):
        params = {"window": {"to_ts": 2, "from_ts": 1}, "note": "café 😀"}
        expected = '{"note":"caf\\u00e9 \\ud83d\\ude00","window":{"from_ts":1,"to_ts":2}}'
        self.assertEqual(roles.params_text(params), expected)

    def test_escapes_a_lone_surrogate(self):
        self.assertEqual(roles.params_text({"text": "\ud800"}), '{"text":"\\ud800"}')


if __name__ == "__main__":
    unittest.main()
