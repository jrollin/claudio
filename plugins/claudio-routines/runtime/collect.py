import argparse
import errno
import itertools
import json
import os
import re
import stat
import sys
from datetime import datetime, time, timedelta
from urllib.parse import urlsplit

import config_tree
import providers
import recap_state
import recap_window
import roles
import state
import tribe_state
import weekly_state
import weekly_window
from config import adapter_role, config_directory, load_zone, read_routine
from providers._common import ended
from providers._http import BODY_CAP
from providers._replay import OFFLINE, ReplayClient, ReplayMismatch
from providers._errors import CALL_CAP, CALL_CAP_PARTIAL, CredentialsMissing, PartialRead, SourceUnreadable

NOT_REPORTED = "not reported by the adapter"
NO_NEW_CALL = "no new call"
NO_PREVIOUS_PAGE = "no previous digest page in the state"
PLAN_NOT_DONE = "plan not done"
NO_RESPONSE = "no response saved (connector missing or relay not run)"
CALLS_FILE = "calls.json"
DAY_SECONDS = 86400
RESPONSE_SUFFIX = ".txt"
RECORD_SUFFIX = ".json"
COLLECTION_SUFFIX = ".json"
LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")
REPLACEMENT = "\ufffd"
SPACE_RUN = re.compile(r" {2,}")
REASON_CAP = 200
EMPTY_RECORDS = {
    "monitors": {"monitors": [], "transitions": [], "discovered": [], "discovery": None},
    "metrics": {"metrics": []},
    "document_store": {"pages": []},
    "chat": {"messages": []},
    "code_host": {"pull_requests": [], "issues": []},
    "issue_tracker": {"issues": []},
}

STATE_CHECKERS = {
    roles.DEFAULT_ENGINE: state.check_state,
    roles.TRIBE_ENGINE: tribe_state.check_state,
    roles.RECAP_ENGINE: recap_state.check_state,
    roles.WEEKLY_ENGINE: weekly_state.check_state,
}

STEP_SPEC = {
    "done": state.BOOLEAN,
    "partial": state.Nullable(state.TEXT),
    "calls": [{"id": state.TEXT, "tool": state.TEXT, "arguments": {}, "digest": state.Nullable(state.TEXT)}],
}
CALLS_SPEC = {"calls": {"*": state.Nullable(state.TEXT)}, "done": state.BOOLEAN, "partial": state.Nullable(state.TEXT)}
RECORD_SPEC = {
    "method": state.TEXT,
    "path": state.TEXT,
    "query": state.TEXT,
    "body": state.PRESENT,
    "status": state.PRESENT,
    "link": state.Nullable(state.TEXT),
    "response": state.PRESENT,
    "error": state.Nullable({"class": state.TEXT, "message": state.TEXT, "status": state.PRESENT}),
}


def load_routine(args):
    config, routine, sources = read_routine(args.config, args.routine, args.place, adapter_role)
    roles.validate_pack(routine.get("query_pack", []), sources, routine=args.routine, rules=routine.get("rules", []))
    return config, routine, {name: source["role"] for name, source in sources.items()}


def run_sources(args):
    _, routine, role_by_source = load_routine(args)
    listing = [
        {"source": name, "role": role_by_source[name], "provider": source["provider"], "transport": source["transport"][args.place]}
        for name, source in sorted(routine["sources"].items())
    ]
    sys.stdout.write(state.dump(listing).decode("utf-8"))
    return 0


def env_lines(name, source, provider, place):
    if source["transport"][place] == "mcp":
        return [f"connector {name} {provider['mcp']['connectors'][place]}"]
    return [f"missing {name} {var}" for var in provider["api"]["credentials"].values() if not os.environ.get(var)]


def run_check_env(args):
    config, routine, _ = load_routine(args)
    lines = sorted(
        {
            line
            for name, source in routine["sources"].items()
            for line in env_lines(name, source, config["providers"][source["provider"]], args.place)
        }
    )
    for line in lines:
        print(line)
    return 1 if any(line.startswith("missing ") for line in lines) else 0


def transport_source(routine, args, transport):
    path = f"routines.{args.routine}.sources.{args.source}"
    if args.source not in routine["sources"]:
        raise roles.ConfigError(f"{path}: no such source in the routine")
    source = routine["sources"][args.source]
    actual = source["transport"][args.place]
    if actual != transport:
        raise roles.ConfigError(
            f"{path}.transport.{args.place}: source {args.source} uses the {actual} transport at place {args.place}; "
            f"{args.command} reads {transport} sources only"
        )
    return source


def check_fetch_window(document):
    state.check_window(document)
    if not isinstance(document.get("retry_known_gaps"), bool):
        raise state.Rejected("expected a boolean at retry_known_gaps")


WINDOW_CHECKERS = {
    roles.DEFAULT_ENGINE: check_fetch_window,
    roles.TRIBE_ENGINE: check_fetch_window,
    roles.RECAP_ENGINE: recap_window.check_window,
    roles.WEEKLY_ENGINE: weekly_window.check_window,
}


def config_zone(config):
    name = config.get("timezone")
    if not isinstance(name, str):
        raise roles.ConfigError("timezone: must be a time zone name")
    return load_zone(name, f"timezone: unknown time zone {name}")


def first_read_from(routine, window):
    days = routine.get("first_read_days")
    return window["from_ts"] if days is None else window["to_ts"] - days * DAY_SECONDS


def trend_from(zone, end_ts, days):
    first_day = state.local_date(end_ts, zone) - timedelta(days=days - 1)
    return int(datetime.combine(first_day, time.min, tzinfo=zone).timestamp())


def select_entries(entries, run_state, window, today):
    known_gaps = {spot["key"] for spot in run_state["blind_spots"] if state.is_known(spot)}
    selected, deferred = [], {}
    for entry in entries:
        if entry.get("schedule") == "daily" and run_state["run"]["daily_metrics_on"] == today:
            deferred[entry["key"]] = {"status": "deferred", "reason": "not due"}
        elif not window["retry_known_gaps"] and entry["key"] in known_gaps:
            deferred[entry["key"]] = {"status": "deferred", "reason": "known gap"}
        else:
            selected.append(entry)
    return selected, deferred


def recap_rereads(run_state):
    rereads = []
    for key, unit in sorted(run_state["units"].items()):
        if unit["status"] in recap_state.HELD_STATUSES:
            thread = recap_state.THREAD_KEY.fullmatch(key)
            rereads.append({"kind": unit["kind"], "channel": unit["channel"], "root_ts": thread.group(2) if thread else None, "last_ts": unit["last_ts"]})
    return rereads


def state_options(run_state, engine, role, source, name):
    if engine == roles.RECAP_ENGINE:
        return {"rereads": recap_rereads(run_state)} if role == "chat" and source.get("searches") else {}
    if engine != roles.TRIBE_ENGINE:
        return {}
    if role == "chat":
        threads = run_state["threads"].get(name, [])
        return {"threads": [{"channel": thread["channel"], "root_ts": thread["root_ts"]} for thread in threads]}
    previous = run_state["run"]["previous_page"]
    if "page_from_state" in source and previous is not None:
        return {"page_id": previous["id"]}
    return {}


def skipped_reason(run_state, engine, source):
    if engine == roles.TRIBE_ENGINE and "page_from_state" in source and run_state["run"]["previous_page"] is None:
        return NO_PREVIOUS_PAGE
    return None


def tracked_items(run_state, engine):
    return run_state["items"] if engine == roles.DEFAULT_ENGINE else {}


def tracked_monitors(items, pack):
    listed = {entry["key"] for entry in pack}
    keys = sorted(key for key in items if state.is_tracked_monitor(key) and key not in listed)
    return [{"key": key, "monitor": key[len(state.MONITOR_PREFIX) :]} for key in keys]


def first_monitors_source(routine, role_by_source):
    names = [
        name for name, source in routine["sources"].items() if role_by_source[name] == "observability" and source["kind"] == "monitors"
    ]
    return min(names, default=None)


def with_span(entry, window, zone):
    spans = {}
    if "lookback_days" in entry:
        spans["span"] = {"from_ts": window["to_ts"] - entry["lookback_days"] * DAY_SECONDS, "to_ts": window["to_ts"]}
    if "trend_days" in entry:
        spans["trend_span"] = {"from_ts": trend_from(zone, window["to_ts"], entry["trend_days"]), "to_ts": window["to_ts"]}
    return {**entry, **spans}


def stored_cursor(cursors, name, role, kind):
    if role != "observability":
        return cursors.get(name)
    observability = cursors["observability"]
    if kind == "monitors":
        return {"events_ts_ms": observability["events_ts_ms"], "monitors": observability["monitors"]}
    return {"metrics": observability["metrics"]}


def conforming_cursor(base, empty_records, cursor):
    probe = {**base, "read": False, "reason": "stored cursor", "records": empty_records, "cursor": cursor, "entries": {}}
    try:
        roles.validate_collection(probe)
    except ValueError:
        return None
    return cursor


class Draft:
    def __init__(self, base, empty_records, cursor, selected, deferred, skipped=None):
        self.base = base
        self.skipped = skipped
        self.empty_records = empty_records
        self.cursor = cursor
        self.selected = selected
        self.deferred = deferred

    def not_read(self, reason):
        failed = {entry["key"]: {"status": "failed", "reason": reason} for entry in self.selected}
        return {
            **self.base,
            "read": False,
            "reason": reason,
            "records": self.empty_records,
            "cursor": self.cursor,
            "entries": {**failed, **self.deferred},
        }

    def read_entries(self, reported):
        if self.base["role"] != "observability":
            return reported
        missing = {"status": "failed", "reason": NOT_REPORTED}
        return {entry["key"]: reported[entry["key"]] if entry["key"] in reported else missing for entry in self.selected}

    def read(self, result):
        entries = self.read_entries(result["entries"])
        return {
            **self.base,
            "read": True,
            "reason": None,
            "records": result["records"],
            "cursor": result["cursor"],
            "entries": {**entries, **self.deferred},
        }


def failure_reason(error, host):
    reason = str(error)
    if isinstance(error, (PartialRead, CredentialsMissing)):
        return reason
    return f"{host}: {reason}"


def read_source(draft, where, read):
    try:
        collection = draft.read(read())
    except SourceUnreadable as error:
        return draft.not_read(failure_reason(error, where))
    except (state.InputError, ReplayMismatch):
        raise
    except Exception as error:
        return draft.not_read(f"{where}: adapter error: {type(error).__name__}")
    try:
        roles.validate_collection(collection)
    except ValueError as error:
        return draft.not_read(f"adapter output invalid: {error}")
    return collection


def prepare(args, transport):
    config, routine, role_by_source = load_routine(args)
    source = transport_source(routine, args, transport)
    engine = routine.get("engine", roles.DEFAULT_ENGINE)
    window = state.load(args.window, "window", WINDOW_CHECKERS[engine])
    window = {**window, "first_read_from_ts": first_read_from(routine, window), "timezone": config.get("timezone")}
    run_state = state.load(args.state, "state", STATE_CHECKERS[engine])
    role = role_by_source[args.source]
    selected, deferred, kind = [], {}, role
    if role == "observability":
        kind = source["kind"]
        pack = routine.get("query_pack", [])
        entries = [entry for entry in pack if entry["source"] == args.source]
        if args.source == first_monitors_source(routine, role_by_source):
            entries += tracked_monitors(tracked_items(run_state, engine), pack)
        zone = config_zone(config)
        selected, deferred = select_entries(entries, run_state, window, state.local_date(window["to_ts"], zone).isoformat())
        selected = [with_span(entry, window, zone) for entry in selected]
    base = {
        "schema": roles.COLLECTION_SCHEMA,
        "source": args.source,
        "role": role,
        "provider": source["provider"],
        "transport": transport,
        "place": args.place,
        "window": {"from_ts": window["from_ts"], "to_ts": window["to_ts"]},
    }
    cursor = conforming_cursor(base, EMPTY_RECORDS[kind], stored_cursor(run_state.get("cursors", {}), args.source, role, kind))
    draft = Draft(base, EMPTY_RECORDS[kind], cursor, selected, deferred, skipped_reason(run_state, engine, source))
    provider = config["providers"][source["provider"]]
    options = state_options(run_state, engine, role, source, args.source)
    configured = {key: value for key, value in source.items() if key not in ("threads", "rereads")}
    return provider, {**configured, "name": args.source, "provider_config": provider, **options}, window, draft


def clean_reason(reason):
    return SPACE_RUN.sub(" ", state.blank_controls(reason))[:REASON_CAP] if isinstance(reason, str) else reason


def without_lone_surrogates(value):
    if isinstance(value, str):
        return LONE_SURROGATE.sub(REPLACEMENT, value)
    if isinstance(value, list):
        return [without_lone_surrogates(item) for item in value]
    if isinstance(value, dict):
        return {without_lone_surrogates(key): without_lone_surrogates(item) for key, item in value.items()}
    return value


def cleaned(collection):
    collection = without_lone_surrogates(collection)
    entries = {key: {**status, "reason": clean_reason(status["reason"])} for key, status in collection["entries"].items()}
    return {**collection, "reason": clean_reason(collection["reason"]), "entries": entries}


def write_collection(args, collection):
    try:
        roles.validate_collection(collection)
    except ValueError as error:
        raise state.Rejected(f"collection of source {args.source}: {error}") from None
    state.write_all([(args.out, state.dump(cleaned(collection)))])


def open_records(directory):
    try:
        os.makedirs(directory, exist_ok=True)
        held = sorted(os.listdir(directory))
    except OSError as error:
        raise state.InputError(f"responses: cannot create {directory}: {error.strerror}") from error
    if held:
        raise state.InputError(f"responses: {directory} already holds {held[0]}")


def record_writer(directory, name):
    numbers = itertools.count(1)

    def write(record):
        path = os.path.join(directory, f"{name}-{next(numbers)}{RECORD_SUFFIX}")
        state.write_all([(path, state.dump(without_lone_surrogates(record)))])

    return write


def recording_client(adapter, provider, args):
    client = adapter.api_client(provider)
    if args.responses is not None:
        client.recorder = record_writer(args.responses, args.source)
    return client


def fetch_collection(provider, source, window, draft, client_of):
    if draft.skipped is not None:
        return draft.not_read(draft.skipped)
    adapter = providers.load(provider["adapter"])
    host = urlsplit(provider["api"]["base_url"]).hostname
    return read_source(draft, host, lambda: adapter.fetch(source, window, draft.cursor, draft.selected, client_of(adapter)))


def run_fetch(args):
    provider, source, window, draft = prepare(args, "api")
    if args.responses is not None:
        open_records(args.responses)
    write_collection(args, fetch_collection(provider, source, window, draft, lambda adapter: recording_client(adapter, provider, args)))
    return 0


def call_id_pattern(name):
    return re.compile(re.escape(name) + r"-[1-9][0-9]*")


def response_ids(directory):
    try:
        names = os.listdir(directory)
    except OSError as error:
        raise state.InputError(f"responses: cannot list {directory}: {error.strerror}") from error
    return sorted(name[: -len(RESPONSE_SUFFIX)] for name in names if name.endswith(RESPONSE_SUFFIX))


def read_response(directory, call_id):
    path = os.path.join(directory, call_id + RESPONSE_SUFFIX)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise SourceUnreadable(f"response {call_id} is not a regular file") from None
        raise state.InputError(f"responses: cannot read {path}: {error.strerror}") from error
    try:
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise SourceUnreadable(f"response {call_id} is not a regular file")
            if info.st_size > BODY_CAP:
                raise PartialRead(f"response over 10 MB {call_id}")
            data = handle.read()
    except OSError as error:
        raise state.InputError(f"responses: cannot read {path}: {error.strerror}") from error
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise SourceUnreadable(f"response {call_id} is not UTF-8 text") from None
    return unwrapped(text)


def unwrapped(text):
    if not text.lstrip().startswith("["):
        return text
    try:
        blocks = json.loads(text)
    except (ValueError, RecursionError):
        return text
    if isinstance(blocks, list) and blocks and all(is_text_block(block) for block in blocks):
        return "".join(block["text"] for block in blocks)
    return text


def is_text_block(block):
    return isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)


def read_responses(directory, call_ids):
    return {call_id: read_response(directory, call_id) for call_id in call_ids}


def check_calls(document):
    state.check(document, CALLS_SPEC, "")


def check_step(step, name):
    state.check(step, STEP_SPEC, "plan")
    if step["done"] and step["calls"]:
        raise state.Rejected("plan.calls: must be empty when done")
    if not step["done"] and step["partial"] is not None:
        raise state.Rejected("plan.partial: must be null when not done")
    call_id = call_id_pattern(name)
    seen = set()
    for index, call in enumerate(step["calls"]):
        if not call_id.fullmatch(call["id"]):
            raise state.Rejected(f"plan.calls[{index}].id: must be {name}-<n> with n from 1")
        if call["id"] in seen:
            raise state.Rejected(f"plan.calls[{index}].id: duplicate id {call['id']}")
        seen.add(call["id"])


def adapter_step(adapter, source, window, draft, responses, connector):
    try:
        step = adapter.plan(source, window, draft.cursor, draft.selected, responses, connector)
    except SourceUnreadable as error:
        return ended(failure_reason(error, connector))
    except Exception as error:
        return ended(f"adapter error: {type(error).__name__}")
    try:
        check_step(step, source["name"])
    except state.Rejected as error:
        return ended(f"adapter output invalid: {error}")
    return step


def next_step(step, responses, cap=CALL_CAP):
    if step["done"]:
        return ended(step["partial"])
    if len(responses) >= cap:
        return ended(CALL_CAP_PARTIAL)
    fresh = [call for call in step["calls"] if call["id"] not in responses]
    if not fresh:
        return ended(NO_NEW_CALL)
    return {"done": False, "partial": None, "calls": fresh}


def plan_step(adapter, source, window, draft, directory, connector):
    call_id = call_id_pattern(source["name"])
    try:
        responses = read_responses(directory, [item for item in response_ids(directory) if call_id.fullmatch(item)])
    except SourceUnreadable as error:
        return ended(failure_reason(error, connector))
    return next_step(adapter_step(adapter, source, window, draft, responses, connector), responses, source.get("call_cap", CALL_CAP))


def run_plan(args):
    provider, source, window, draft = prepare(args, "mcp")
    connector = provider["mcp"]["connectors"][args.place]
    calls_path = os.path.join(args.responses, CALLS_FILE)
    try:
        os.makedirs(args.responses, exist_ok=True)
    except OSError as error:
        raise state.InputError(f"responses: cannot create {args.responses}: {error.strerror}") from error
    known = state.load(calls_path, "calls", check_calls) if os.path.exists(calls_path) else {"calls": {}}
    step = ended() if draft.skipped is not None else plan_step(providers.load(provider["adapter"]), source, window, draft, args.responses, connector)
    step = {**step, "partial": clean_reason(step["partial"])}
    recorded = {
        "calls": {**known["calls"], **{call["id"]: call["digest"] for call in step["calls"]}},
        "done": step["done"],
        "partial": step["partial"],
    }
    calls = [{"id": call["id"], "connector": connector, "tool": call["tool"], "arguments": call["arguments"]} for call in step["calls"]]
    state.write_all([(calls_path, state.dump(recorded)), (args.out, state.dump({**step, "calls": calls}))])
    return 0


def relay_gap(known, call_ids, name, connector):
    if not known["done"] and not any(call_id_pattern(name).fullmatch(call_id) for call_id in call_ids):
        return f"{connector}: {NO_RESPONSE}"
    if not known["done"]:
        return PLAN_NOT_DONE
    missing = sorted(set(known["calls"]) - set(call_ids))
    if missing:
        return f"missing response {missing[0]}"
    unplanned = sorted(set(call_ids) - set(known["calls"]))
    if unplanned:
        return f"unplanned response {unplanned[0]}"
    return None


def parse_collection(args, provider, source, window, draft):
    if draft.skipped is not None:
        return draft.not_read(draft.skipped)
    connector = provider["mcp"]["connectors"][args.place]
    known = state.load(os.path.join(args.responses, CALLS_FILE), "calls", check_calls)
    call_ids = response_ids(args.responses)
    gap = relay_gap(known, call_ids, source["name"], connector)
    if gap is not None:
        return draft.not_read(gap)
    try:
        responses = read_responses(args.responses, call_ids)
    except SourceUnreadable as error:
        return draft.not_read(failure_reason(error, connector))
    if known["partial"] is not None:
        return draft.not_read(f"partial: {known['partial']}")
    adapter = providers.load(provider["adapter"])
    return read_source(draft, connector, lambda: adapter.parse(source, window, draft.cursor, draft.selected, responses, known["calls"]))


def run_parse(args):
    provider, source, window, draft = prepare(args, "mcp")
    write_collection(args, parse_collection(args, provider, source, window, draft))
    return 0


def check_record(document):
    state.check(document, RECORD_SPEC, "")


def read_records(directory, name):
    records = []
    for number in itertools.count(1):
        file = f"{name}-{number}{RECORD_SUFFIX}"
        path = os.path.join(directory, file)
        if not os.path.exists(path):
            return records
        records.append(state.load(path, f"record {file}", check_record))


def replaying_client(adapter, provider, name, records):
    adapter.api_client(provider, opener=OFFLINE, environ={})
    return ReplayClient(provider, name, records)


def run_replay_fetch(args):
    provider, source, window, draft = prepare(args, "api")
    records = read_records(args.responses, args.source)
    write_collection(args, fetch_collection(provider, source, window, draft, lambda adapter: replaying_client(adapter, provider, args.source, records)))
    return 0


REPLAYERS = {"api": run_replay_fetch, "mcp": run_parse}


def run_replay(args):
    _, routine, role_by_source = load_routine(args)
    try:
        os.makedirs(args.out, exist_ok=True)
    except OSError as error:
        raise state.InputError(f"out: cannot create {args.out}: {error.strerror}") from error
    for name, source in sorted(routine["sources"].items()):
        replayed = argparse.Namespace(
            **{**vars(args), "source": name, "responses": os.path.join(args.raw, role_by_source[name], name), "out": os.path.join(args.out, name + COLLECTION_SUFFIX)}
        )
        REPLAYERS[source["transport"][args.place]](replayed)
    return 0


COMMANDS = {"sources": run_sources, "check-env": run_check_env, "fetch": run_fetch, "plan": run_plan, "parse": run_parse, "replay": run_replay}
RELAY_FLAGS = ("--source", "--window", "--state", "--responses", "--out")


def build_parser():
    parser = argparse.ArgumentParser(prog="collect.py", description="Collect one source of a routine")
    commands = parser.add_subparsers(dest="command", required=True)
    specs = (
        ("sources", "list the routine's sources with their role, provider and transport", ()),
        ("check-env", "list missing credential variables and connector names for the place", ()),
        ("fetch", "read one api source and write its collection", ("--source", "--window", "--state", "--out")),
        ("plan", "write the next connector calls of one mcp source", RELAY_FLAGS),
        ("parse", "parse the saved connector responses of one mcp source into its collection", RELAY_FLAGS),
        ("replay", "rebuild every collection of a run offline from its raw folder", ("--window", "--state", "--raw", "--out")),
    )
    for name, help_text, flags in specs:
        command = commands.add_parser(name, help=help_text)
        for flag in ("--config", "--routine", *flags):
            command.add_argument(flag, required=True)
        command.add_argument("--place", required=True, choices=roles.PLACES)
    commands.choices["fetch"].add_argument("--responses")
    return parser


def fail(message, code):
    print(f"collect.py: {message}", file=sys.stderr)
    return code


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except roles.ConfigError as error:
        return fail(config_tree.locate(str(error), config_directory(args.config)), 2)
    except state.InputError as error:
        return fail(str(error), 2)
    except roles.PackError as error:
        return fail("rejected: " + config_tree.locate(str(error), config_directory(args.config)), 3)
    except state.Rejected as error:
        return fail(f"rejected: {error}", 3)


if __name__ == "__main__":
    sys.exit(main())
