import json
import re
from urllib.parse import urlsplit

from state import (
    LABEL_CAP, MONITOR_PREFIX, PLACES, SOURCES, TRANSPORTS, Nullable, Omittable, is_integer, is_label, is_number, join,
)

ROLES = ("observability", "document_store", "chat", "code_host")
KINDS = SOURCES
READS = ("scalar", "top", "hourly")
SCHEDULES = ("every_run", "daily")
BLOCK_TYPES = ("heading", "paragraph", "list", "table", "code", "other")
STATUSES = ("ok", "deferred", "failed", "missing")
READ_STATUSES = ("ok", "missing")
MONITOR_STATES = ("OK", "Alert", "Warn", "No Data", "Skipped", "Unknown", "Ignored")
RULE_CAP = 500
LOOKBACK_CAP = 31
COLLECTION_SCHEMA = 1
FNV_OFFSET = 2166136261
FNV_PRIME = 16777619
SOURCE_NAME = re.compile(r"[a-z][a-z0-9-]*")
ENV_VAR = re.compile(r"[A-Z][A-Z0-9_]*")
REPO_SEGMENT = r"[A-Za-z0-9_.-]*[A-Za-z0-9_-][A-Za-z0-9_.-]*"
REPO = re.compile(REPO_SEGMENT + "/" + REPO_SEGMENT)
PAGE_ID = re.compile(r"[A-Za-z0-9-]+")
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
    def __init__(self, spec):
        self.spec = spec


def _matches(pattern):
    return lambda value: isinstance(value, str) and pattern.fullmatch(value) is not None


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
INTEGER = Rule(is_integer, "must be an integer")
NUMBER = Rule(is_number, "must be a finite number")
BOOLEAN = Rule(lambda value: isinstance(value, bool), "must be a boolean")
ABSOLUTE = Rule(lambda value: isinstance(value, str) and value.startswith("/"), "must be an absolute path")
UTC_TIME = Rule(_matches(UTC_Z), "must be a UTC timestamp ending in Z")

PLACE = {"runtime_dir": ABSOLUTE, "state_dir": ABSOLUTE}
SOURCE = {"provider": TEXT, "transport": {"cloud": Choice(TRANSPORTS), "local": Choice(TRANSPORTS)}}
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
    "document_store": {"page_id": Rule(_matches(PAGE_ID), "must match ^[A-Za-z0-9-]+$")},
    "chat": {"channels": ListOf(TEXT, non_empty=True)},
    "code_host": {
        "repos": ListOf(Rule(_matches(REPO), "must be an owner/name repository"), non_empty=True),
        "query": Omittable(STRING),
    },
}

RULE = Rule(
    lambda value: isinstance(value, str) and value.strip() != "" and len(value) <= RULE_CAP,
    f"must be non-blank text of at most {RULE_CAP} characters",
)
LABEL = Rule(
    lambda value: is_label(value) and value != "",
    f"must be a non-empty string of at most {LABEL_CAP} characters without control characters",
)
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
READ_FIELDS = {
    "scalar": {},
    "top": {"top": Rule(lambda value: is_integer(value) and value >= 1, "must be an integer of at least 1")},
    "hourly": {
        "excluded_hours": Omittable(
            ListOf(Rule(lambda value: is_integer(value) and 0 <= value <= 23, "must be a local hour from 0 to 23"))
        )
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
        "events": ListOf({"ts_ms": INTEGER, "link": STRING, "monitor": Nullable(STRING)}),
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
            }
        )
    },
    {"metrics": MapOf(Nullable(NUMBER))},
)
OBSERVABILITY_SCHEMAS = ((frozenset(("monitors", "events")), MONITORS_SCHEMA), (frozenset(("metrics",)), METRICS_SCHEMA))
ROLE_SCHEMAS = {
    "document_store": (
        {
            "pages": ListOf(
                {
                    "id": STRING,
                    "title": STRING,
                    "last_edited": UTC_TIME,
                    "blocks": ListOf({"type": Choice(BLOCK_TYPES), "text": STRING, "rows": Nullable(ListOf(ListOf(STRING)))}),
                }
            )
        },
        {"last_edited": Nullable(UTC_TIME)},
    ),
    "chat": (
        {
            "messages": ListOf(
                {
                    "channel": STRING,
                    "ts": STRING,
                    "author": STRING,
                    "text": STRING,
                    "link": STRING,
                }
            )
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
        },
        {"updated_at": Nullable(STRING)},
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
        for key in sorted(value):
            _conform(value[key], spec.spec, join(path, key), error, exact)
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


def _config_field(mapping, path, key, spec):
    _conform_fields(mapping, {key: spec}, path, ConfigError, exact=False)
    return mapping[key]


def validate_config(config, routine, place, role_of=None):
    if not isinstance(config, dict):
        raise ConfigError("config: must be a mapping")
    places = _config_field(config, "", "places", {})
    if place not in PLACES:
        raise ConfigError(f"places.{place}: the place must be one of " + ", ".join(PLACES))
    _config_field(places, "places", place, PLACE)
    providers = _config_field(config, "", "providers", {})
    routines = _config_field(config, "", "routines", {})
    routine_path = f"routines.{routine}"
    sources = _config_field(_config_field(routines, "routines", routine, {}), routine_path, "sources", MapOf({}))
    for name in sorted(sources):
        if SOURCE_NAME.fullmatch(name) is None:
            raise ConfigError(f"{routine_path}.sources.{name}: the source name must match ^[a-z][a-z0-9-]*$")
    for name in sorted(sources):
        _validate_source(sources[name], f"{routine_path}.sources.{name}", providers, place, role_of)


def _validate_source(source, path, providers, place, role_of):
    _conform(source, SOURCE, path, ConfigError, exact=False)
    name = source["provider"]
    if name not in providers:
        raise ConfigError(f"{path}.provider: names no entry of providers")
    provider_path = f"providers.{name}"
    provider = _config_field(providers, "providers", name, PROVIDER)
    if source["transport"][place] == "api":
        _conform(provider, API, provider_path, ConfigError, exact=False)
    else:
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
    if role == "observability" and source["kind"] != "monitors" and "discovery_query" in source:
        raise ConfigError(f"{path}.discovery_query: only a monitors source takes a discovery query")


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
    raise ValueError("records: must hold monitors and events, or metrics")


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
            if (block["type"] == "table") != (block["rows"] is not None):
                raise ValueError(
                    f"records.pages[{page_index}].blocks[{block_index}].rows: must be a list for a table block, null otherwise"
                )


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
