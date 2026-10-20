import json
import re
from datetime import date
from urllib.parse import urlsplit

from state import (
    LABEL_CAP, MONITOR_PREFIX, PLACES, SOURCES, TRANSPORTS, Nullable, Omittable, is_integer, is_label, is_number, join, parses,
)

ROLES = ("observability", "document_store", "chat", "code_host", "issue_tracker")
KINDS = SOURCES
READS = ("scalar", "top", "hourly")
EMPTY_READS = ("gap", "zero")
SCHEDULES = ("every_run", "daily")
BLOCK_TYPES = ("heading", "paragraph", "list", "table", "code", "other")
STATUSES = ("ok", "deferred", "failed", "missing")
READ_STATUSES = ("ok", "missing")
MONITOR_STATES = ("OK", "Alert", "Warn", "No Data", "Skipped", "Unknown", "Ignored")
RULE_CAP = 500
LOOKBACK_CAP = 31
CALL_CAP_MAX = 300
TREND_MIN = 7
TREND_CAP = 31
FIRST_READ_CAP = 31
CHANNEL_TYPES = ("public_channel", "private_channel", "mpim", "im")
ENGINES = ("watch", "tribe", "recap", "weekly")
DEFAULT_ENGINE = ENGINES[0]
TRIBE_ENGINE = ENGINES[1]
RECAP_ENGINE = ENGINES[2]
WEEKLY_ENGINE = ENGINES[3]
WEEKLY_ROLES = ("issue_tracker", "code_host", "chat", "document_store")
RECAP_LANDINGS = ("waiting", "good_to_know")
THREAD_READS = ("full", "since")
RECAP_LOOKBACK_CAP = 365
PAGE_FROM_STATE = ("previous_page",)
PAGE_OPTIONS = ("page_id", "pages", "page_from_state", "edited_by", "created_by")
EDITED_CAP_MAX = 20
TREND_AGGREGATORS = ("max", "min", "sum", "avg", "last")
COLLECTION_SCHEMA = 1
FNV_OFFSET = 2166136261
FNV_PRIME = 16777619
SOURCE_NAME = re.compile(r"[a-z][a-z0-9-]*")
ENV_VAR = re.compile(r"[A-Z][A-Z0-9_]*")
REPO_SEGMENT = r"[A-Za-z0-9_.-]*[A-Za-z0-9_-][A-Za-z0-9_.-]*"
REPO = re.compile(REPO_SEGMENT + "/" + REPO_SEGMENT)
PAGE_ID = re.compile(r"[A-Za-z0-9-]+")
KEY_PATH_TEXT = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*")
PLACEHOLDER = re.compile(r"\{\{([^{}]*)\}\}")
CALL_VALUES = ("parent", "title", "content", "week", "week_start", "date")
PUBLISH_VALUES = {"create": CALL_VALUES, "poll": (*CALL_VALUES, "task"), "heading": CALL_VALUES}
LINK_VALUES = ("id",)
TITLE_VALUES = ("date",)
DIGITS = re.compile(r"[0-9]+")
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
PLAIN_HOST = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*")
ROUTINE_SLUG = re.compile(r"[a-z0-9-]+")
UTC_Z = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z")


class ConfigError(Exception):
    pass


class PackError(Exception):
    pass


class Rule:
    def __init__(self, test, why):
        self.test = test
        self.why = why


class Choice(Rule):
    def __init__(self, options):
        super().__init__(lambda value: isinstance(value, str) and value in options, "must be one of " + ", ".join(options))


class ListOf:
    def __init__(self, spec, non_empty=False):
        self.spec = spec
        self.non_empty = non_empty


class MapOf:
    def __init__(self, spec, non_empty=False):
        self.spec = spec
        self.non_empty = non_empty


class Exact:
    def __init__(self, spec):
        self.spec = spec


def transports_of(value):
    return [value] if isinstance(value, str) else value


def _is_transport_preference(value):
    items = transports_of(value)
    return (
        isinstance(items, list)
        and bool(items)
        and all(isinstance(item, str) and item in TRANSPORTS for item in items)
        and len(set(items)) == len(items)
    )


def _matches(pattern):
    return lambda value: isinstance(value, str) and pattern.fullmatch(value) is not None


def _is_day(value):
    return _matches(DAY)(value) and parses(date.fromisoformat, value)


def _is_pinned_url(value):
    if not isinstance(value, str) or "?" in value or "#" in value:
        return False
    try:
        parts = urlsplit(value)
        return parts.scheme == "https" and bool(parts.hostname) and "@" not in parts.netloc and parts.port != 0
    except ValueError:
        return False


ANY = Rule(lambda value: True, "")
STRING = Rule(lambda value: isinstance(value, str), "must be a string")
TEXT = Rule(lambda value: isinstance(value, str) and value != "", "must be a non-empty string")
NON_BLANK = Rule(lambda value: isinstance(value, str) and value.strip() != "", "must be non-blank text")
INTEGER = Rule(is_integer, "must be an integer")
NUMBER = Rule(is_number, "must be a finite number")
BOOLEAN = Rule(lambda value: isinstance(value, bool), "must be a boolean")
ABSOLUTE = Rule(lambda value: isinstance(value, str) and value.startswith("/"), "must be an absolute path")
UTC_TIME = Rule(_matches(UTC_Z), "must be a UTC timestamp ending in Z")
DAY_TEXT = Rule(_is_day, "must be a day like 2026-01-31")
PAGE_ID_TEXT = Rule(_matches(PAGE_ID), "must match ^[A-Za-z0-9-]+$")

CHANNEL_TYPES_TEXT = Rule(
    lambda value: isinstance(value, str) and all(part in CHANNEL_TYPES for part in value.split(",")),
    "must be a comma list of " + ", ".join(CHANNEL_TYPES),
)

HOST = Rule(_matches(PLAIN_HOST), "must be a plain host name such as api.example.test")
PLACE = {"runtime_dir": ABSOLUTE, "state_dir": ABSOLUTE, "injected_hosts": Omittable(ListOf(HOST))}
TRANSPORT_PREFERENCE = Rule(_is_transport_preference, "must be api, mcp or a non-empty list of them without repeats")
SOURCE = {"provider": TEXT, "transport": {"cloud": TRANSPORT_PREFERENCE, "local": TRANSPORT_PREFERENCE}}
PINNED_URL = Rule(_is_pinned_url, "must be an https URL with a host, a valid port and no user info, query or fragment")
PROVIDER = {"adapter": TEXT, "links_base": Omittable(PINNED_URL)}
API = {
    "api": {
        "base_url": PINNED_URL,
        "credentials": MapOf(Rule(_matches(ENV_VAR), "must be an environment variable name matching ^[A-Z][A-Z0-9_]*$")),
    }
}
ROLE_OPTIONS = {
    "observability": {"kind": Choice(KINDS), "scope_filter": STRING, "discovery_query": Omittable(STRING)},
    "document_store": {
        "page_id": Omittable(PAGE_ID_TEXT),
        "pages": Omittable(ListOf(PAGE_ID_TEXT, non_empty=True)),
        "page_from_state": Omittable(Choice(PAGE_FROM_STATE)),
        "edited_by": Omittable(Rule(lambda value: isinstance(value, str) and value.strip() != "", "must be non-blank text")),
        "created_by": Omittable(NON_BLANK),
        "exclude_paths": Omittable(ListOf(NON_BLANK)),
        "edited_cap": Omittable(
            Rule(lambda value: is_integer(value) and 1 <= value <= EDITED_CAP_MAX, f"must be an integer from 1 to {EDITED_CAP_MAX}")
        ),
    },
    "chat": {
        "channels": Omittable(ListOf(TEXT, non_empty=True)),
        "owner": Omittable(TEXT),
        "searches": Omittable(ListOf(ANY, non_empty=True)),
        "reactions": Omittable(BOOLEAN),
        "search_page_cap": Omittable(Rule(lambda value: is_integer(value) and value >= 1, "must be an integer of at least 1")),
        "call_cap": Omittable(Rule(lambda value: is_integer(value) and 1 <= value <= CALL_CAP_MAX, f"must be an integer from 1 to {CALL_CAP_MAX}")),
    },
    "code_host": {
        "repos": Omittable(ListOf(Rule(_matches(REPO), "must be an owner/name repository"), non_empty=True)),
        "searches": Omittable(ListOf(NON_BLANK, non_empty=True)),
        "exclude_authors": Omittable(ListOf(TEXT)),
        "query": Omittable(STRING),
    },
    "issue_tracker": {
        "filter": Omittable(Rule(_matches(DIGITS), "must be a filter id of digits only")),
        "jql": Omittable(NON_BLANK),
        "query": Omittable(STRING),
        "open_sprints": Omittable(BOOLEAN),
    },
}

FIRST_READ_DAYS = Omittable(
    Rule(lambda value: is_integer(value) and 1 <= value <= FIRST_READ_CAP, f"must be an integer from 1 to {FIRST_READ_CAP}")
)
ENGINE = Omittable(Choice(ENGINES))
RULE = Rule(
    lambda value: isinstance(value, str) and value.strip() != "" and len(value) <= RULE_CAP,
    f"must be non-blank text of at most {RULE_CAP} characters",
)
LABEL = Rule(
    lambda value: is_label(value) and value != "",
    f"must be a non-empty string of at most {LABEL_CAP} characters without control characters",
)
SEARCH = {
    "name": LABEL,
    "filters": TEXT,
    "channel_types": Omittable(CHANNEL_TYPES_TEXT),
    "keywords": Omittable(ListOf(TEXT, non_empty=True)),
    "since": ANY,
}
SINCE_LOOKBACK = {
    "lookback_days": Rule(lambda value: is_integer(value) and 1 <= value <= LOOKBACK_CAP, f"must be an integer from 1 to {LOOKBACK_CAP}")
}


def _whole_days(low, high):
    return Rule(lambda value: is_integer(value) and low <= value <= high, f"must be an integer from {low} to {high}")


WORKSPACE = Rule(_matches(PLAIN_HOST), "must be a plain host name such as chat.example.test")
SLUG = Rule(_matches(ROUTINE_SLUG), "must be a routine slug of lowercase letters, digits and dashes")
WEEKLY_KEYS = {
    "owner": NON_BLANK,
    "workspace": WORKSPACE,
    "recap": Omittable(SLUG),
    "exclude": Omittable(Exact({"channels": Omittable(ListOf(TEXT))})),
}
RECAP_KEYS = {
    "owner": TEXT,
    "workspace": WORKSPACE,
    "groups": ListOf(Exact({"id": TEXT, "label": TEXT, "lands_in": Choice(RECAP_LANDINGS)})),
    "announcement": Exact({"channels": Omittable(ListOf(TEXT)), "topics": Omittable(ListOf(TEXT))}),
    "window": Exact({"lookback_working_days": _whole_days(1, RECAP_LOOKBACK_CAP)}),
    "exclude": Exact({"authors": Omittable(ListOf(TEXT)), "channels": Omittable(ListOf(TEXT)), "keep_bots": Omittable(ListOf(TEXT))}),
    "history": Omittable(
        Exact(
            {
                "late_after_working_days": Omittable(_whole_days(0, RECAP_LOOKBACK_CAP)),
                "drop_after_days": Omittable(_whole_days(1, RECAP_LOOKBACK_CAP)),
            }
        )
    ),
    "rules": ListOf(TEXT, non_empty=True),
    "thread_reads": Omittable(Choice(THREAD_READS)),
}
KEY_PATH = Rule(_matches(KEY_PATH_TEXT), "must be a dotted path of object keys")
PAGE_LINK = Rule(
    lambda value: isinstance(value, str) and "{{id}}" in value, "must be a string holding the placeholder {{id}}"
)
PAGE_VALUES = {"how_built": ListOf(STRING), "key_callout": ListOf(STRING), "state_path": TEXT, "link": PAGE_LINK, "title": LABEL}
PUBLISH_CALL = {"tool": TEXT, "arguments": MapOf(ANY)}
PUBLISH = {
    "provider": TEXT,
    "week_start_format": Omittable(TEXT),
    "parent": PAGE_ID_TEXT,
    "create": PUBLISH_CALL,
    "poll": PUBLISH_CALL,
    "heading": PUBLISH_CALL,
    "results": {
        "task": KEY_PATH,
        "status": KEY_PATH,
        "page": KEY_PATH,
        "heading": KEY_PATH,
        "done": ListOf(TEXT, non_empty=True),
        "failed": ListOf(TEXT, non_empty=True),
    },
}
MONITOR_ID = Rule(_matches(re.compile(r"[0-9]+")), "must be a monitor id of digits only")
ENTRY = {
    "key": TEXT,
    "source": TEXT,
    "title": LABEL,
    "link": LABEL,
    "rule": RULE,
    "schedule": Choice(SCHEDULES),
}
MONITOR_ENTRY = {"monitor": MONITOR_ID}
METRIC_ENTRY = {"query": TEXT, "read": Choice(READS), "aggregator": TEXT}
TREND_DAYS = Omittable(
    Rule(lambda value: is_integer(value) and TREND_MIN <= value <= TREND_CAP, f"must be an integer from {TREND_MIN} to {TREND_CAP}")
)
EMPTY = Omittable(Choice(EMPTY_READS))
READ_FIELDS = {
    "scalar": {"trend_days": TREND_DAYS, "empty": EMPTY},
    "top": {"top": Rule(lambda value: is_integer(value) and value >= 1, "must be an integer of at least 1"), "empty": EMPTY},
    "hourly": {
        "excluded_hours": Omittable(
            ListOf(Rule(lambda value: is_integer(value) and 0 <= value <= 23, "must be a local hour from 0 to 23"))
        ),
        "trend_days": TREND_DAYS,
    },
}
SCHEDULE_FIELDS = {
    "every_run": {},
    "daily": {
        "lookback_days": Omittable(
            Rule(lambda value: is_integer(value) and 1 <= value <= LOOKBACK_CAP, f"must be an integer from 1 to {LOOKBACK_CAP}")
        )
    },
}

COLLECTION = {
    "schema": Rule(lambda value: is_integer(value) and value == COLLECTION_SCHEMA, f"must be {COLLECTION_SCHEMA}"),
    "source": STRING,
    "role": Choice(ROLES),
    "provider": STRING,
    "transport": Choice(TRANSPORTS),
    "skipped": Omittable(ListOf({"transport": Choice(TRANSPORTS), "missing": ListOf(STRING)})),
    "place": Choice(PLACES),
    "window": {"from_ts": INTEGER, "to_ts": INTEGER},
    "read": BOOLEAN,
    "reason": Nullable(STRING),
    "cursor": ANY,
    "records": ANY,
    "entries": MapOf({"status": Choice(STATUSES), "reason": Nullable(STRING)}),
}
MONITOR = {"id": STRING, "name": STRING, "state": STRING, "priority": Nullable(INTEGER), "link": STRING}
BUCKET = {"ts": INTEGER, "value": Nullable(NUMBER)}
MONITORS_SCHEMA = (
    {
        "monitors": ListOf(MONITOR),
        "transitions": ListOf({"monitor": STRING, "count": INTEGER, "first_ts_ms": INTEGER, "last_ts_ms": INTEGER}),
        "discovered": ListOf(MONITOR),
        "discovery": Nullable({"read": BOOLEAN, "reason": Nullable(STRING), "event_monitors_capped": Omittable(BOOLEAN)}),
    },
    {"events_ts_ms": Nullable(INTEGER), "monitors": MapOf(STRING)},
)
METRICS_SCHEMA = (
    {
        "metrics": ListOf(
            {
                "key": STRING,
                "value": Nullable(NUMBER),
                "hourly": ListOf(BUCKET),
                "daily": Omittable(ListOf(BUCKET)),
                "groups": ListOf({"group": STRING, "value": Nullable(NUMBER)}),
                "trend": Omittable(Nullable(ListOf({"day": DAY_TEXT, "value": NUMBER}))),
                "trend_reason": Omittable(Nullable(STRING)),
            }
        )
    },
    {"metrics": MapOf(Nullable(NUMBER))},
)
OBSERVABILITY_SCHEMAS = ((frozenset(("monitors", "transitions")), MONITORS_SCHEMA), (frozenset(("metrics",)), METRICS_SCHEMA))
ROLE_SCHEMAS = {
    "document_store": (
        {
            "pages": ListOf(
                {
                    "id": STRING,
                    "title": STRING,
                    "last_edited": UTC_TIME,
                    "link": STRING,
                    "blocks": ListOf(
                        {
                            "type": Choice(BLOCK_TYPES),
                            "text": STRING,
                            "rows": Nullable(ListOf(ListOf(STRING))),
                            "checked": Omittable(Nullable(BOOLEAN)),
                        }
                    ),
                }
            )
        },
        {"pages": MapOf(UTC_TIME)},
    ),
    "chat": (
        {
            "messages": ListOf(
                {
                    "channel": STRING,
                    "ts": STRING,
                    "thread_ts": Nullable(STRING),
                    "author": STRING,
                    "text": STRING,
                    "link": STRING,
                }
            ),
            "units": Omittable(
                ListOf(
                    {
                        "channel": STRING,
                        "name": STRING,
                        "participants": ListOf({"id": STRING, "name": STRING}),
                        "messages": ListOf(
                            {
                                "user": STRING,
                                "name": STRING,
                                "bot": BOOLEAN,
                                "ts": STRING,
                                "root_ts": Nullable(STRING),
                                "mentions": ListOf(STRING),
                                "group_mentions": ListOf(STRING),
                                "text": STRING,
                                "owner_reacted": Omittable(BOOLEAN),
                            }
                        ),
                    }
                )
            ),
        },
        {"ts": MapOf(STRING)},
    ),
    "code_host": (
        {
            "pull_requests": ListOf(
                {
                    "repo": STRING,
                    "number": INTEGER,
                    "title": STRING,
                    "author": STRING,
                    "state": STRING,
                    "draft": BOOLEAN,
                    "created_at": STRING,
                    "updated_at": STRING,
                    "merged_at": Nullable(STRING),
                    "link": STRING,
                }
            ),
            "issues": ListOf(
                {
                    "repo": STRING,
                    "number": INTEGER,
                    "title": STRING,
                    "author": STRING,
                    "state": STRING,
                    "created_at": STRING,
                    "updated_at": STRING,
                    "link": STRING,
                }
            ),
            "activity": Omittable(
                ListOf(
                    {
                        "repo": STRING,
                        "number": INTEGER,
                        "kind": STRING,
                        "author": STRING,
                        "at": UTC_TIME,
                        "state": Nullable(STRING),
                        "text": STRING,
                    }
                )
            ),
        },
        {"updated_at": Nullable(STRING)},
    ),
    "issue_tracker": (
        {
            "issues": ListOf(
                {
                    "key": STRING,
                    "title": STRING,
                    "type": STRING,
                    "status": STRING,
                    "priority": Nullable(STRING),
                    "created": UTC_TIME,
                    "updated": UTC_TIME,
                    "link": STRING,
                    "in_open_sprint": BOOLEAN,
                }
            )
        },
        {"updated": Nullable(UTC_TIME)},
    ),
}


def _conform(value, spec, path, error, exact):
    if isinstance(spec, Nullable):
        if value is not None:
            _conform(value, spec.spec, path, error, exact)
    elif isinstance(spec, Rule):
        if not spec.test(value):
            raise error(f"{path}: {spec.why}")
    elif isinstance(spec, ListOf):
        if not isinstance(value, list):
            raise error(f"{path}: must be a list")
        if spec.non_empty and not value:
            raise error(f"{path}: must be a non-empty list")
        for index, item in enumerate(value):
            _conform(item, spec.spec, f"{path}[{index}]", error, exact)
    elif isinstance(spec, MapOf):
        if not isinstance(value, dict):
            raise error(f"{path}: must be a mapping")
        if spec.non_empty and not value:
            raise error(f"{path}: must be a non-empty mapping")
        for key in sorted(value):
            _conform(value[key], spec.spec, join(path, key), error, exact)
    elif isinstance(spec, Exact):
        _conform_fields(value, spec.spec, path, error, True)
    else:
        _conform_fields(value, spec, path, error, exact)


def _conform_fields(value, spec, path, error, exact):
    if not isinstance(value, dict):
        raise error(f"{path}: must be a mapping")
    for key, sub in spec.items():
        if key in value:
            _conform(value[key], sub.spec if isinstance(sub, Omittable) else sub, join(path, key), error, exact)
        elif not isinstance(sub, Omittable):
            raise error(f"{join(path, key)}: missing")
    unexpected = sorted(set(value) - set(spec)) if exact else []
    if unexpected:
        raise error(f"{join(path, unexpected[0])}: unexpected key")


def check_placeholders(value, names, path):
    if isinstance(value, str):
        for name in PLACEHOLDER.findall(value):
            if name not in names:
                raise ConfigError(f"{path}: unknown placeholder {{{{{name}}}}}, expected one of " + ", ".join(names))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            check_placeholders(item, names, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key in sorted(value):
            check_placeholders(value[key], names, join(path, key))


def _validate_publication(chosen, routine_path, providers):
    _conform(chosen, {"page": PAGE_VALUES, "publish": PUBLISH}, routine_path, ConfigError, exact=False)
    check_placeholders(chosen["page"]["link"], LINK_VALUES, f"{routine_path}.page.link")
    check_placeholders(chosen["page"]["title"], TITLE_VALUES, f"{routine_path}.page.title")
    for call, names in PUBLISH_VALUES.items():
        check_placeholders(chosen["publish"][call]["arguments"], names, f"{routine_path}.publish.{call}.arguments")
    if chosen["publish"]["provider"] not in providers:
        raise ConfigError(f"{routine_path}.publish.provider: names no entry of providers")


def _config_field(mapping, path, key, spec):
    _conform_fields(mapping, {key: spec}, path, ConfigError, exact=False)
    return mapping[key]


def injected_hosts(config, place):
    return {host.lower() for host in config["places"][place].get("injected_hosts", [])}


def validate_config(config, routine, place, role_of=None):
    if not isinstance(config, dict):
        raise ConfigError("config: must be a mapping")
    places = _config_field(config, "", "places", {})
    if place not in PLACES:
        raise ConfigError(f"places.{place}: the place must be one of " + ", ".join(PLACES))
    _config_field(places, "places", place, PLACE)
    injected = injected_hosts(config, place)
    providers = _config_field(config, "", "providers", {})
    routines = _config_field(config, "", "routines", {})
    routine_path = f"routines.{routine}"
    chosen = _config_field(routines, "routines", routine, {})
    _conform(chosen, {"first_read_days": FIRST_READ_DAYS, "engine": ENGINE}, routine_path, ConfigError, exact=False)
    engine = chosen.get("engine", DEFAULT_ENGINE)
    if engine == RECAP_ENGINE:
        _conform(chosen, RECAP_KEYS, routine_path, ConfigError, exact=False)
    if engine == WEEKLY_ENGINE:
        _conform(chosen, WEEKLY_KEYS, routine_path, ConfigError, exact=False)
    sources = _config_field(chosen, routine_path, "sources", MapOf({}, non_empty=True))
    for name in sorted(sources):
        if SOURCE_NAME.fullmatch(name) is None:
            raise ConfigError(f"{routine_path}.sources.{name}: the source name must match ^[a-z][a-z0-9-]*$")
    for name in sorted(sources):
        _validate_source(sources[name], f"{routine_path}.sources.{name}", providers, place, role_of, engine, chosen.get("owner"), injected)
    if chosen.get("engine") == TRIBE_ENGINE:
        _validate_publication(chosen, routine_path, providers)


def _validate_source(source, path, providers, place, role_of, engine, owner=None, injected=()):
    _conform(source, SOURCE, path, ConfigError, exact=False)
    name = source["provider"]
    if name not in providers:
        raise ConfigError(f"{path}.provider: names no entry of providers")
    provider_path = f"providers.{name}"
    provider = _config_field(providers, "providers", name, PROVIDER)
    transports = transports_of(source["transport"][place])
    if "api" in transports:
        _conform(provider, API, provider_path, ConfigError, exact=False)
    if "mcp" in transports:
        _conform(provider, {"mcp": {"connectors": {place: TEXT}}}, provider_path, ConfigError, exact=False)
    if role_of is None:
        return
    try:
        role = role_of(provider["adapter"])
    except (AttributeError, ValueError) as exc:
        raise ConfigError(f"{provider_path}.adapter: {exc}") from exc
    if role not in ROLES:
        raise ConfigError(f"{provider_path}.adapter: the adapter role must be one of " + ", ".join(ROLES))
    _conform(source, ROLE_OPTIONS[role], path, ConfigError, exact=False)
    if engine == RECAP_ENGINE:
        _validate_recap_source(source, path, role, owner)
    if engine == WEEKLY_ENGINE:
        _validate_weekly_source(source, path, role, owner)
    if role == "observability" and source["kind"] != "monitors" and "discovery_query" in source:
        raise ConfigError(f"{path}.discovery_query: only a monitors source takes a discovery query")
    if role == "document_store":
        _validate_page_options(source, path, engine)
    if role == "chat":
        _validate_chat_options(source, path)
    if role == "issue_tracker":
        _validate_issue_options(source, path)
    if role == "code_host":
        _validate_code_host_options(source, path)
        if "api" in transports:
            _refuse_injected_code_host(provider, place, injected)


def _refuse_injected_code_host(provider, place, injected):
    host = urlsplit(provider["api"]["base_url"]).hostname
    if host in injected:
        raise ConfigError(f"places.{place}.injected_hosts: {host} is the host of a code host provider, which the proxy never injects")


def _validate_code_host_options(source, path):
    if ("repos" in source) == ("searches" in source):
        raise ConfigError(f"{path}: a code host source sets exactly one of repos and searches")
    mcp_places = [place for place in PLACES if "mcp" in transports_of(source["transport"][place])]
    if "searches" in source and mcp_places:
        raise ConfigError(f"{path}.searches: read over api only, but {path}.transport.{mcp_places[0]} lists mcp")


def _validate_recap_source(source, path, role, owner):
    if role != "chat":
        raise ConfigError(f"{path}.provider: a {RECAP_ENGINE} routine takes chat sources only, this adapter's role is {role}")
    if source.get("owner") != owner:
        raise ConfigError(f"{path}.owner: must equal the routine owner")


def _validate_weekly_source(source, path, role, owner):
    if role not in WEEKLY_ROLES:
        raise ConfigError(f"{path}.provider: a {WEEKLY_ENGINE} routine takes {', '.join(WEEKLY_ROLES)} sources, this adapter's role is {role}")
    if role == "chat" and "searches" not in source:
        raise ConfigError(f"{path}.searches: missing, a chat source of a {WEEKLY_ENGINE} routine reads searches")
    if role == "chat" and source.get("owner") != owner:
        raise ConfigError(f"{path}.owner: must equal the routine owner")


def _validate_chat_options(source, path):
    if "channels" not in source and "searches" not in source:
        raise ConfigError(f"{path}: a chat source sets channels or searches")
    if ("searches" in source or source.get("reactions") is True) and "owner" not in source:
        raise ConfigError(f"{path}.owner: missing, a chat source with searches or reactions names its owner")
    seen = {}
    for index, search in enumerate(source.get("searches", [])):
        search_path = f"{path}.searches[{index}]"
        _conform(search, SEARCH, search_path, ConfigError, exact=True)
        if search["name"] in seen:
            raise ConfigError(f"{search_path}.name: duplicates {path}.searches[{seen[search['name']]}].name")
        seen[search["name"]] = index
        if search["since"] != "window":
            _validate_since(search["since"], f"{search_path}.since")


def _validate_issue_options(source, path):
    if ("filter" in source) == ("jql" in source):
        raise ConfigError(f"{path}: an issue tracker source sets exactly one of filter and jql")
    if "jql" in source and source.get("open_sprints") is True:
        raise ConfigError(f"{path}.open_sprints: needs filter, a jql source reads no open sprint")


def _validate_since(since, path):
    if not isinstance(since, dict):
        raise ConfigError(f'{path}: must be "window" or a mapping with lookback_days')
    _conform(since, SINCE_LOOKBACK, path, ConfigError, exact=True)


def _validate_page_options(source, path, engine):
    if sum(option in source for option in PAGE_OPTIONS) != 1:
        raise ConfigError(f"{path}: a document store source sets exactly one of " + ", ".join(PAGE_OPTIONS))
    if "page_from_state" in source and engine != TRIBE_ENGINE:
        raise ConfigError(f"{path}.page_from_state: only a routine with the {TRIBE_ENGINE} engine keeps a previous page")
    if "edited_cap" in source and "edited_by" not in source:
        raise ConfigError(f"{path}.edited_cap: needs edited_by")
    if "exclude_paths" in source and "created_by" not in source:
        raise ConfigError(f"{path}.exclude_paths: needs created_by")
    relayed = _place_listing(source, "mcp")
    if "edited_by" in source and relayed is not None:
        raise ConfigError(f"{path}.edited_by: reads over api only, the {relayed} transport lists mcp")
    direct = _place_listing(source, "api")
    if "created_by" in source and direct is not None:
        raise ConfigError(f"{path}.created_by: reads over mcp only, the {direct} transport lists api")


def _place_listing(source, transport):
    return next((place for place in PLACES if transport in transports_of(source["transport"][place])), None)


def validate_pack(pack, sources, routine=None, *, rules):
    prefix = f"routines.{routine}." if routine is not None else ""
    path = prefix + "query_pack"
    _conform(pack, ListOf({}), path, PackError, exact=False)
    seen = {}
    for index, entry in enumerate(pack):
        entry_path = f"{path}[{index}]"
        _conform(entry, ENTRY, entry_path, PackError, exact=False)
        key = entry["key"]
        if key in seen:
            raise PackError(f"{entry_path}.key: duplicates {path}[{seen[key]}].key")
        seen[key] = index
        if key in sources:
            raise PackError(
                f"{entry_path}.key: equals the source name {key}, and source names and pack keys share the blind spot keys"
            )
        kind = _observability_kind(sources.get(entry["source"]))
        if kind is None:
            raise PackError(f"{entry_path}.source: must name a configured observability source")
        if kind == "monitors":
            _validate_monitor_entry(entry, entry_path)
        else:
            _validate_metric_entry(entry, entry_path)
    _validate_group_prefixes(pack, path)
    _conform(rules, ListOf(RULE), prefix + "rules", PackError, exact=False)


def _observability_kind(source):
    if not isinstance(source, dict) or source.get("role") != "observability":
        return None
    kind = source.get("kind")
    return kind if kind in KINDS else None


def _validate_monitor_entry(entry, path):
    if not entry["key"].startswith(MONITOR_PREFIX):
        raise PackError(f"{path}.key: must start with {MONITOR_PREFIX} for a monitors source")
    _conform(entry, {**ENTRY, **MONITOR_ENTRY}, path, PackError, exact=True)
    if entry["key"] != MONITOR_PREFIX + entry["monitor"]:
        raise PackError(f"{path}.key: must be {MONITOR_PREFIX}{entry['monitor']}, the key of its monitor")


def _validate_metric_entry(entry, path):
    if entry["key"].startswith(MONITOR_PREFIX):
        raise PackError(f"{path}.key: must not start with {MONITOR_PREFIX} for a metrics source")
    _conform(entry, METRIC_ENTRY, path, PackError, exact=False)
    if entry["read"] == "top" and (entry["key"] + "-").startswith(MONITOR_PREFIX):
        raise PackError(f"{path}.key: its group keys would start with {MONITOR_PREFIX} for a top read")
    spec = {**ENTRY, **METRIC_ENTRY, **READ_FIELDS[entry["read"]], **SCHEDULE_FIELDS[entry["schedule"]]}
    _conform(entry, spec, path, PackError, exact=True)
    if "excluded_hours" in entry and "lookback_days" in entry:
        raise PackError(f"{path}.excluded_hours: must be absent when lookback_days is set: a daily rollup has no hours")
    if "trend_days" in entry:
        _validate_trend_entry(entry, path)


def _validate_trend_entry(entry, path):
    if "lookback_days" in entry:
        raise PackError(f"{path}.trend_days: must be absent when lookback_days is set: a trend sits next to the window value")
    if entry["aggregator"] not in TREND_AGGREGATORS:
        raise PackError(f"{path}.aggregator: must be one of " + ", ".join(TREND_AGGREGATORS) + " when trend_days is set")


def _validate_group_prefixes(pack, path):
    tops = [(index, entry["key"] + "-") for index, entry in enumerate(pack) if entry.get("read") == "top"]
    for index, entry in enumerate(pack):
        for top_index, group_prefix in tops:
            if entry["key"].startswith(group_prefix):
                raise PackError(
                    f"{path}[{index}].key: starts with {group_prefix}, the group key prefix of {path}[{top_index}]"
                )


def validate_collection(doc):
    if not isinstance(doc, dict):
        raise ValueError("collection: must be a mapping")
    _conform(doc, COLLECTION, "", ValueError, exact=True)
    read = doc["read"]
    if read and doc["reason"] is not None:
        raise ValueError("reason: must be null when the source was read")
    if not read and not doc["reason"]:
        raise ValueError("reason: must be a non-empty string when the source was not read")
    records_spec, cursor_spec = _role_schema(doc["role"], doc["records"])
    _conform(doc["records"], records_spec, "records", ValueError, exact=True)
    if read or doc["cursor"] is not None:
        _conform(doc["cursor"], cursor_spec, "cursor", ValueError, exact=True)
    if doc["role"] == "document_store":
        _validate_blocks(doc["records"]["pages"])
    if "discovery" in doc["records"]:
        _validate_discovery(doc["records"]["discovery"], read)
    if not read:
        _validate_unread_records(doc["records"])
    for key in sorted(doc["entries"]):
        _validate_entry_status(doc["entries"][key], f"entries.{key}", read)


def _role_schema(role, records):
    if role != "observability":
        return ROLE_SCHEMAS[role]
    if isinstance(records, dict):
        for required, schema in OBSERVABILITY_SCHEMAS:
            if required.issubset(records) and set(records).issubset(schema[0]):
                return schema
    raise ValueError("records: must hold monitors and transitions, or metrics")


def _validate_discovery(discovery, read):
    if read and discovery is None:
        raise ValueError("records.discovery: must be a mapping when the source was read")
    if not read and discovery is not None:
        raise ValueError("records.discovery: must be null when the source was not read")
    if discovery is None:
        return
    if discovery["read"] and discovery["reason"] is not None:
        raise ValueError("records.discovery.reason: must be null when the discovery was read")
    if not discovery["read"] and not discovery["reason"]:
        raise ValueError("records.discovery.reason: must be a non-empty string when the discovery was not read")


def _validate_blocks(pages):
    for page_index, page in enumerate(pages):
        for block_index, block in enumerate(page["blocks"]):
            where = f"records.pages[{page_index}].blocks[{block_index}]"
            if (block["type"] == "table") != (block["rows"] is not None):
                raise ValueError(f"{where}.rows: must be a list for a table block, null otherwise")
            if block.get("checked") is not None and block["type"] != "list":
                raise ValueError(f"{where}.checked: must be null unless the block is a list")


def _validate_unread_records(records):
    for key in sorted(records):
        if records[key]:
            raise ValueError(f"records.{key}: must be empty when the source was not read")


def _validate_entry_status(entry, path, read):
    status = entry["status"]
    if status in READ_STATUSES and not read:
        raise ValueError(f"{path}.status: must not be {status} when the source was not read")
    if status == "ok" and entry["reason"] is not None:
        raise ValueError(f"{path}.reason: must be null for an ok entry")
    if status != "ok" and not entry["reason"]:
        raise ValueError(f"{path}.reason: must be a non-empty string for an entry that is not ok")


def fnv1a32(text):
    if not text.isascii():
        raise ValueError("fnv1a32: text must be ASCII only")
    value = FNV_OFFSET
    for character in text:
        value = ((value ^ ord(character)) * FNV_PRIME) & 0xFFFFFFFF
    return f"{value:08x}"


def params_text(params):
    return json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
