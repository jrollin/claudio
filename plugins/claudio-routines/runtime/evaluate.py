import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date

import features
import judgment
import roles
import state
from config import accept_any, adapter_role, load_zone, read_routine

KIND_RECORDS = {"monitors": {"monitors", "events"}, "metrics": {"metrics"}}
MUTES_HEADING = "Mutes"
UNTIL_HEADERS = ("until", "silence until")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
NO_COLLECTION = "no collection"
GIT_TIMEOUT = 10


def run_git(directory, args):
    try:
        result = subprocess.run(
            ["git", "-C", directory, *args], capture_output=True, text=True, timeout=GIT_TIMEOUT, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def check_window(document):
    state.check_window(document)
    state.check(document, {"retry_known_gaps": state.BOOLEAN}, "")


def load_config(path, routine, place, role_of):
    try:
        return read_routine(path, routine, place, role_of)
    except roles.ConfigError as error:
        raise state.InputError(f"config: {error}") from error


def check_pack(routine, sources, slug):
    try:
        roles.validate_pack(routine.get("query_pack"), sources, routine=slug, rules=routine.get("rules", []))
    except roles.PackError as error:
        raise state.Rejected(f"config: {error}") from error


def config_zone(config):
    name = config.get("timezone")
    return load_zone(name, f"config: timezone: unknown time zone {name!r}")


def check_collection_source(doc, name, source, place, window):
    expected = {
        "source": name,
        "role": source["role"],
        "place": place,
        "transport": source["transport"][place],
        "window": {"from_ts": window["from_ts"], "to_ts": window["to_ts"]},
    }
    for key, value in expected.items():
        if doc[key] != value:
            raise ValueError(f"{key}: is {json.dumps(doc[key], sort_keys=True)}, expected {json.dumps(value, sort_keys=True)} for this run")
    if source["role"] == "observability" and not KIND_RECORDS[source["kind"]] <= set(doc["records"]):
        raise ValueError(f"records: must hold the records of kind {source['kind']}")


def missing_collection(name, source, place):
    return {
        "source": name,
        "role": source["role"],
        "transport": source["transport"][place],
        "read": False,
        "reason": NO_COLLECTION,
        "cursor": None,
        "records": None,
        "entries": {},
    }


def read_collection(directory, name, source, place, window):
    path = os.path.join(directory, f"{name}.json")
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except FileNotFoundError:
        return missing_collection(name, source, place)
    except OSError as error:
        raise state.InputError(f"collection {path}: cannot read: {error.strerror}") from error
    try:
        doc = json.loads(raw.decode("utf-8"))
        roles.validate_collection(doc)
        check_collection_source(doc, name, source, place, window)
    except ValueError as error:
        raise state.InputError(f"collection {path}: {error}") from error
    return doc


def is_date(text):
    if not ISO_DATE.fullmatch(text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def cell(row, index):
    return row[index].strip() if index < len(row) else ""


def mutes_section(blocks):
    section = []
    inside = False
    for block in blocks:
        if block["type"] == "heading":
            if inside:
                break
            inside = block["text"].strip() == MUTES_HEADING
        elif inside:
            section.append(block)
    return section


def mutes_table(blocks):
    tables = [block for block in mutes_section(blocks) if block["type"] == "table"]
    if not tables:
        return []
    rows = tables[0]["rows"]
    header = [text.strip().lower() for text in rows[0]] if rows else []
    until_columns = [header.index(name) for name in UNTIL_HEADERS if name in header]
    if "key" not in header or len(until_columns) != 1:
        return None
    key_at, until_at = header.index("key"), until_columns[0]
    mutes = [{"key": cell(row, key_at), "until": cell(row, until_at)} for row in rows[1:]]
    return [mute for mute in mutes if mute["key"] and is_date(mute["until"])]


def sources_page(sources, collections):
    names = [name for name, source in sources.items() if source["role"] == "document_store"]
    collection = collections[names[0]] if names else None
    if collection is None or not collection["read"] or not collection["records"]["pages"]:
        return None, None
    return names[0], collection["records"]["pages"][0]


def page_facts(sources, collections):
    name, page = sources_page(sources, collections)
    if page is None:
        return None
    return {"source": name, "last_edited": page["last_edited"], "mutes": mutes_table(page["blocks"])}


def run_context(args, collections, git):
    directory = os.path.dirname(os.path.abspath(args.config))
    commit = git(directory, ["rev-parse", "HEAD"])
    status = git(directory, ["status", "--porcelain", "--", os.path.basename(args.config)])
    return {
        "place": args.place,
        "runtime": args.runtime,
        "config": None if commit is None else commit.strip(),
        "config_dirty": None if status is None else status.strip() != "",
        "collected": {
            name: {key: collection[key] for key in ("role", "transport", "read", "reason")}
            for name, collection in collections.items()
        },
    }


def run_features(args, role_of, git):
    config, routine, sources = load_config(args.config, args.routine, args.place, role_of)
    check_pack(routine, sources, args.routine)
    zone = config_zone(config)
    stored = state.load(args.state, "state", state.check_state)
    window = state.load(args.window, "window", check_window)
    collections = {
        name: read_collection(args.collections, name, source, args.place, window) for name, source in sources.items()
    }
    features_doc, base, rules = features.compute(
        routine, sources, collections, stored, window, zone, page_facts(sources, collections)
    )
    base["run_context"] = run_context(args, collections, git)
    try:
        state.check_facts({**base, "observations": {}})
    except state.Rejected as error:
        raise state.InputError(f"base {args.base_out}: {error}") from error
    state.write_all(
        [
            (args.out, features.compact_dump(features_doc)),
            (args.base_out, state.dump(base)),
            (args.rules_out, features.compact_dump(rules)),
        ]
    )


def load_input(path, label, checker):
    try:
        return state.load(path, label, checker)
    except state.Rejected as error:
        raise state.InputError(str(error)) from error


def load_model_output(path, label):
    try:
        return state.load(path, label, accept_any)
    except state.InvalidJson as error:
        raise state.Rejected(str(error)) from error


def check_as(label, function, *args):
    try:
        return function(*args)
    except state.Rejected as error:
        raise state.Rejected(f"{label}: {error}") from error


def run_judge(args):
    features_doc = load_input(args.features, "features", judgment.check_features)
    base = load_input(args.base, "base", judgment.check_base)
    document = load_model_output(args.judgment, "judgment")
    facts = check_as("judgment", judgment.judge, features_doc, base, document)
    state.write_all([(args.out, state.dump(facts))])


def run_annotate(args):
    features_doc = load_input(args.features, "features", judgment.check_features)
    facts = load_input(args.facts, "facts", state.check_facts)
    summary = load_input(args.preview, "preview", judgment.check_summary)
    document = load_model_output(args.analysis, "analysis")
    annotated = check_as("analysis", judgment.annotate, features_doc, facts, document, summary)
    state.write_all([(args.out, state.dump(annotated))])


MERGE_COMMANDS = {"judge": run_judge, "annotate": run_annotate}


def build_parser():
    parser = argparse.ArgumentParser(prog="evaluate.py", description="Prod watch features, judgment merge and analysis")
    commands = parser.add_subparsers(dest="command", required=True)
    compute = commands.add_parser("features", help="write the features, base and rules files; decides nothing")
    for flag in ("--config", "--routine", "--state", "--window", "--collections", "--place", "--runtime", "--out", "--base-out", "--rules-out"):
        compute.add_argument(flag, required=True)
    judge = commands.add_parser("judge", help="check the judgment against the features and merge it into the facts")
    for flag in ("--features", "--base", "--judgment", "--out"):
        judge.add_argument(flag, required=True)
    annotate = commands.add_parser("annotate", help="check the analysis and add it to the pass-1 facts")
    for flag in ("--features", "--facts", "--analysis", "--preview", "--out"):
        annotate.add_argument(flag, required=True)
    return parser


def main(argv=None, role_of=None, git=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "features":
            run_features(args, role_of or adapter_role, git or run_git)
        else:
            MERGE_COMMANDS[args.command](args)
    except state.InputError as error:
        print(f"evaluate.py: {error}", file=sys.stderr)
        return 2
    except state.Rejected as error:
        print(f"evaluate.py: rejected: {error}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
