import json
import re
import sys

import collect
import config_tree
import providers
import roles
import state
import tribe_state
from config import adapter_role, config_directory
from state import Nullable, Omittable, leaf

RUN_STATE_SCHEMA = 1
RUN_STATE_HEADING = re.compile(r"^## Run state(?: \{[^\n]*\})?[ \t]*$", re.MULTILINE)
NEXT_SECTION = re.compile(r"^## ", re.MULTILINE)
JSON_BLOCK = re.compile(r"^[ \t]*```json[ \t]*\n(.*?)\n[ \t]*```[ \t]*$", re.MULTILINE | re.DOTALL)
WHEN_ALIASES = {"months": "within months"}
DEFAULT_STATUS = "open"
STATUS_CAP = 60
NOTE_CAP = 60

RUN_STATE_WHEN = leaf(
    lambda value: isinstance(value, str) and (value in tribe_state.WHENS or value in WHEN_ALIASES),
    "one of " + ", ".join(tribe_state.WHENS + tuple(WHEN_ALIASES)),
)
RUN_STATE_STATUS = leaf(lambda value: isinstance(value, str), "a string")
RUN_STATE_METRIC = leaf(lambda value: value is None or isinstance(value, (str, dict)), "a pack entry key, a metric snapshot or null")
RUN_STATE_PAGE = leaf(
    lambda value: isinstance(value, str) and roles.PAGE_ID.fullmatch(value) is not None, "a page id of letters, digits and dashes"
)
CURSOR_TIME = leaf(lambda value: isinstance(value, str) and roles.UTC_Z.fullmatch(value) is not None, "a UTC time ending in Z")
RUN_STATE_SPEC = {
    "digest": tribe_state.NAME,
    "run": {"at": tribe_state.UTC_TIME, "written_at": tribe_state.UTC_TIME, "page": RUN_STATE_PAGE},
    "warnings": {
        "*": {
            "title": tribe_state.TITLE,
            "topic": tribe_state.TITLE,
            "severity": tribe_state.SEVERITY_LEVEL,
            "when": RUN_STATE_WHEN,
            "status": RUN_STATE_STATUS,
            "confidence": tribe_state.CONFIDENCE_LEVEL,
            "metric": RUN_STATE_METRIC,
            "runway": Omittable(tribe_state.LABEL),
            "risk": Omittable(tribe_state.LABEL),
            "impact": Omittable(tribe_state.LABEL),
            "mitigation": Omittable(tribe_state.check_mitigation),
            "cites": Omittable([tribe_state.check_cite]),
        }
    },
    "checks": {
        "*": {
            "text": tribe_state.TITLE,
            "topic": tribe_state.TITLE,
            "done": state.BOOLEAN,
            "group": Omittable(tribe_state.CHECK_GROUP),
        }
    },
    "cursors": {},
    "blind_spot_runs": Omittable([tribe_state.BLIND_SPOT]),
}


class Skipped(Exception):
    pass


def page_text(path):
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as error:
        raise Skipped(f"cannot read the file: {error.strerror}") from error
    try:
        fetched = json.loads(collect.unwrapped(raw.decode("utf-8")))
    except ValueError as error:
        raise Skipped(f"not a saved fetch result: {error}") from error
    text = fetched.get("text") if isinstance(fetched, dict) else None
    if not isinstance(text, str):
        raise Skipped("not a saved fetch result: no text")
    return text


def run_state_block(text):
    heading = RUN_STATE_HEADING.search(text)
    if heading is None:
        raise Skipped("no Run state section")
    section = text[heading.end() :]
    following = NEXT_SECTION.search(section)
    block = JSON_BLOCK.search(section[: following.start()] if following else section)
    if block is None:
        raise Skipped("the Run state section holds no json block")
    return block.group(1)


def read_run_state(path):
    try:
        document = json.loads(run_state_block(page_text(path)))
    except ValueError as error:
        raise Skipped(f"the Run state is not valid JSON: {error}") from error
    if not isinstance(document, dict) or not state.is_integer(document.get("schema")) or document["schema"] != RUN_STATE_SCHEMA:
        raise Skipped(f"the Run state has no schema {RUN_STATE_SCHEMA}")
    return document


def newest_run_state(paths):
    for path in paths:
        try:
            return path, read_run_state(path)
        except Skipped as error:
            print(f"tribe.py: skipped page {path}: {error}", file=sys.stderr)
    raise state.InputError("seed: no page holds a Run state with schema 1; read " + ", ".join(paths))


def routine_sources(config_path, slug):
    config = config_tree.load(config_path, routine=slug)
    routine = config["routines"].get(slug)
    path = f"routines.{slug}"
    if not isinstance(routine, dict) or not isinstance(routine.get("sources"), dict):
        raise roles.ConfigError(f"{path}.sources: the routine has no sources")
    providers = config.get("providers") if isinstance(config.get("providers"), dict) else {}
    sources = {}
    for name, source in sorted(routine["sources"].items()):
        name_of_provider = source.get("provider") if isinstance(source, dict) else None
        provider = providers.get(name_of_provider) if isinstance(name_of_provider, str) else None
        if not isinstance(provider, dict):
            raise roles.ConfigError(f"{path}.sources.{name}.provider: names no entry of providers")
        try:
            role = adapter_role(provider.get("adapter"))
        except ValueError as error:
            raise roles.ConfigError(f"{path}.sources.{name}: {error}") from error
        sources[name] = {**source, "role": role, "adapter": provider["adapter"], "provider_config": provider}
    return config, sources


def read_status(status):
    text = status.strip().lower()
    for word in tribe_state.STATUSES:
        if text.startswith(word) and not text[len(word) :][:1].isalnum():
            return word
    return DEFAULT_STATUS


def seed_warning(key, warning, at):
    metric = warning["metric"]
    status = read_status(warning["status"])
    if status != warning["status"]:
        original = state.clean_text(warning["status"], STATUS_CAP)
        print(f'seed: warnings.{state.clean_text(key, STATUS_CAP)}.status "{original}" read as {status}', file=sys.stderr)
    return {
        "title": warning["title"],
        "topic": warning["topic"],
        "severity": warning["severity"],
        "when": WHEN_ALIASES.get(warning["when"], warning["when"]),
        "runway": warning.get("runway", ""),
        "status": status,
        "confidence": warning["confidence"],
        "risk": warning.get("risk", ""),
        "impact": warning.get("impact", ""),
        "mitigation": warning.get("mitigation", []),
        "cites": warning.get("cites", []),
        "metric": metric if isinstance(metric, str) else None,
        "runs_under": 0,
        "since": at,
    }


def seed_check(check, at):
    return {"text": check["text"], "topic": check["topic"], "group": check.get("group", "Investigate"), "since": at}


def strings(value):
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def live_section(cursors, name):
    live = cursors.get(name, {})
    state.check(live, {}, f"cursors.{name}")
    return f"cursors.{name}", live


def chat_cursor(path, live, source):
    stamps = {}
    for channel in strings(source.get("channels")):
        if channel in live:
            state.check(live[channel], {"ts": Nullable(state.TEXT)}, f"{path}.{channel}")
            if live[channel]["ts"] is not None:
                stamps[channel] = live[channel]["ts"]
    return {"ts": stamps} if stamps else None


def issue_tracker_cursor(path, live, source, sole_tracker):
    state.check(live, {"filter": Omittable(state.PRESENT), "updated_max": Omittable(Nullable(CURSOR_TIME))}, path)
    if live.get("updated_max") is None:
        return None
    matches = str(live["filter"]) == source.get("filter") if "filter" in live else sole_tracker
    return {"updated": live["updated_max"]} if matches else None


def document_store_cursor(path, live, source):
    live_keys = {tribe_state.page_key(key): key for key in live}
    edited = {}
    for page_id in strings(source.get("pages", [source.get("page_id")])):
        key = live_keys.get(tribe_state.page_key(page_id))
        if key is not None:
            state.check(live[key], CURSOR_TIME, f"{path}.{key}")
            edited[page_id] = live[key]
    return {"pages": edited} if edited else None


def observability_cursor(cursors, sources):
    monitors = {}
    for adapter in sorted({source["adapter"] for source in sources.values() if source["role"] == "observability"}):
        path, live = live_section(cursors, adapter)
        section = live.get("monitors", {})
        state.check(section, {"*": state.TEXT}, f"{path}.monitors")
        monitors.update(section)
    return {"events_ts_ms": None, "monitors": monitors, "metrics": {}}


def source_cursor(cursors, source, sole_tracker):
    role = source["role"]
    if role == "chat":
        return chat_cursor(*live_section(cursors, source["adapter"]), source)
    if role == "issue_tracker":
        return issue_tracker_cursor(*live_section(cursors, source["adapter"]), source, sole_tracker)
    if role == "document_store":
        return document_store_cursor(*live_section(cursors, source["adapter"]), source)
    return None


def seed_cursors(cursors, sources):
    sole_tracker = sum(source["role"] == "issue_tracker" for source in sources.values()) == 1
    seeded = {}
    for name, source in sources.items():
        cursor = source_cursor(cursors, source, sole_tracker)
        if cursor is not None:
            seeded[name] = cursor
    return {**seeded, "observability": observability_cursor(cursors, sources)}


def thread_parts(entry):
    channel, separator, root = entry.partition("/") if isinstance(entry, str) else ("", "", "")
    return (channel, root) if separator and channel and root and "/" not in root else None


def skip_thread(path, index, entry, reason):
    print(f'seed: {path}.threads[{index}] "{state.clean_text(str(entry), NOTE_CAP)}" skipped: {reason}', file=sys.stderr)


def seed_threads(cursors, sources):
    chat = {name: source for name, source in sources.items() if source["role"] == "chat"}
    threads = {}
    for adapter_name in sorted({source["adapter"] for source in chat.values()}):
        adapter = providers.load(adapter_name)
        path, live = live_section(cursors, adapter_name)
        state.check(live, {"threads": Omittable([state.PRESENT])}, path)
        owners = {name: source for name, source in chat.items() if source["adapter"] == adapter_name}
        for index, entry in enumerate(live.get("threads", [])):
            parts = thread_parts(entry)
            if parts is None:
                skip_thread(path, index, entry, "not <channel>/<root ts>")
                continue
            channel, root = parts
            listing = {name: source for name, source in owners.items() if channel in strings(source.get("channels"))}
            if not listing:
                skip_thread(path, index, entry, "channel not listed by a chat source")
                continue
            if adapter.ROOT_TS.fullmatch(root) is None:
                skip_thread(path, index, entry, "invalid root ts")
                continue
            for name, source in listing.items():
                thread = {"channel": channel, "root_ts": root, "links": [adapter.message_link(source, channel, root)]}
                if thread not in threads.setdefault(name, []):
                    threads[name].append(thread)
    return threads


def seed_state(run_state, sources, zone):
    state.check(run_state, RUN_STATE_SPEC, "")
    run, at = run_state["run"], run_state["run"]["at"]
    document = {
        **tribe_state.initial_state(run_state["digest"]),
        "warnings": {key: seed_warning(key, warning, at) for key, warning in run_state["warnings"].items()},
        "checks": {key: seed_check(check, at) for key, check in run_state["checks"].items() if not check["done"]},
        "cursors": seed_cursors(run_state["cursors"], sources),
        "threads": seed_threads(run_state["cursors"], sources),
        "blind_spots": run_state.get("blind_spot_runs", []),
    }
    document["run"].update(
        {
            "at": at,
            "previous_page": {"id": tribe_state.page_key(run["page"]), "written_at": run["written_at"]},
            "weekly_heading_week": tribe_state.iso_week(state.parse_time(at).astimezone(zone)),
            "posted": True,
        }
    )
    tribe_state.check_state(document)
    return document


def seed(pages, config_path, routine):
    try:
        config, sources = routine_sources(config_path, routine)
        zone = collect.config_zone(config)
    except roles.ConfigError as error:
        raise state.InputError(config_tree.locate(str(error), config_directory(config_path))) from error
    path, run_state = newest_run_state(pages)
    try:
        return seed_state(run_state, sources, zone)
    except state.Rejected as error:
        raise state.Rejected(f"seed: page {path}: {error}") from error
