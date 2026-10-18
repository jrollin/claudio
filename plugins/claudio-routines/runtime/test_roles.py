import json
import unittest

import roles
import state

ROUTINE = "prod-watch"
ADAPTER_ROLES = {
    "obsvendor": "observability",
    "docvendor": "document_store",
    "chatvendor": "chat",
    "codevendor": "code_host",
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
        "events": [
            {"ts_ms": WINDOW_END * 1000 - 5000, "link": "https://obs.example.test/e/a", "monitor": None},
            {"ts_ms": WINDOW_END * 1000, "link": "https://obs.example.test/e/b", "monitor": MONITOR_ID},
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
                "blocks": [
                    {"type": "heading", "text": "Mutes", "rows": None},
                    {"type": "table", "text": "", "rows": [["key", "until"], ["error-rate", "2026-11-01"]]},
                ],
            }
        ]
    }


def messages_records():
    return {
        "messages": [
            {
                "channel": "chan-alerts",
                "ts": "1780000000.000100",
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
        "records": {"monitors": [], "events": [], "discovered": [], "discovery": None},
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
        doc = make_collection("document_store", pages_records(), {"last_edited": UTC_EDIT}, transport="mcp")
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
        records = {"monitors": [], "events": monitors_records()["events"], "discovered": [], "discovery": None}
        self.assert_collection_error(unread_collection(records=records), "records.events")

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

    def test_rejects_a_boolean_event_timestamp(self):
        doc = monitors_collection()
        doc["records"]["events"][1]["ts_ms"] = True
        self.assert_collection_error(doc, "records.events[1].ts_ms")

    def test_rejects_an_event_title(self):
        doc = monitors_collection()
        doc["records"]["events"][0]["title"] = "Deploy"
        self.assert_collection_error(doc, "records.events[0].title")

    def test_rejects_an_event_without_monitor_field(self):
        doc = monitors_collection()
        del doc["records"]["events"][0]["monitor"]
        self.assert_collection_error(doc, "records.events[0].monitor")

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
        records = {"monitors": [], "events": [], "discovery": None}
        self.assert_collection_error(unread_collection(records=records), "records.discovered")

    def test_rejects_a_source_not_read_without_discovery(self):
        records = {"monitors": [], "events": [], "discovered": []}
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
        records = {"monitors": [], "events": [], "discovered": [], "discovery": None}
        self.assertIsNone(roles.validate_collection(unread_collection(records=records)))

    def test_rejects_a_discovery_on_a_source_not_read(self):
        records = {"monitors": [], "events": [], "discovered": [], "discovery": {"read": False, "reason": "skipped"}}
        self.assert_collection_error(unread_collection(records=records), "records.discovery")

    def test_rejects_discovered_monitors_on_a_source_not_read(self):
        records = {"monitors": [], "events": [], "discovered": monitors_records()["discovered"], "discovery": None}
        self.assert_collection_error(unread_collection(records=records), "records.discovered")

    def test_rejects_an_unknown_records_key_beside_monitors_and_events(self):
        doc = monitors_collection()
        doc["records"]["alerts"] = []
        self.assert_collection_error(doc, "records")


class DocumentStoreRecordsTest(CollectionCase):
    def pages_collection(self):
        return make_collection("document_store", pages_records(), {"last_edited": UTC_EDIT})

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

    def test_rejects_a_table_cell_that_is_not_a_string(self):
        doc = self.pages_collection()
        doc["records"]["pages"][0]["blocks"][1]["rows"][1][1] = None
        self.assert_collection_error(doc, "records.pages[0].blocks[1].rows[1][1]")

    def test_rejects_a_cursor_last_edited_without_utc_z(self):
        doc = self.pages_collection()
        doc["cursor"]["last_edited"] = "2026-10-01"
        self.assert_collection_error(doc, "cursor.last_edited")


class ChatRecordsTest(CollectionCase):
    def messages_collection(self):
        return make_collection("chat", messages_records(), {"ts": {"chan-alerts": "1780000000.000100"}})

    def test_rejects_a_message_carrying_a_reply_count(self):
        doc = self.messages_collection()
        doc["records"]["messages"][0]["replies"] = 2
        self.assert_collection_error(doc, "records.messages[0].replies")

    def test_rejects_a_message_carrying_a_thread_ts(self):
        doc = self.messages_collection()
        doc["records"]["messages"][0]["thread_ts"] = None
        self.assert_collection_error(doc, "records.messages[0].thread_ts")

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
