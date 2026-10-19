import argparse
import re
import sys

import recap_judgment
import state
import weekly_features
import weekly_message
import weekly_state
import weekly_window
from state import Rejected

RECORD_SCHEMA_VERSION = 1
SECTIONS = weekly_features.SECTIONS
FIELDS = {"accomplishments": ("text", "cites"), "decisions": ("text", "cites"), "open": ("text", "owner", "cites")}
LIMITS = {"accomplishments": 6, "decisions": 6, "open": 8}
TEXT_CHARS = 200
OWNER_CHARS = 60
TOTAL_WORDS = 220
URL = re.compile(r"https?://|www\.", re.IGNORECASE)
SUMMARY_CONTEXT = ("window", "week_start", "recap_counts", "sources")
SOURCE_FIELDS = ("source", "read", "reason")


def run_init(args):
    weekly_state.write(args.out, weekly_state.initial_state(args.digest))
    return 0


def run_window(args):
    zone = state.load_zone(args.tz)
    now = weekly_window.load_now(args.now)
    weekly_state.load(args.state)
    window = weekly_window.compute_window(now, zone, args.report_only)
    state.write_all([(args.out, state.dump(window))])
    return 0


def check_string(value, path, cap):
    if not isinstance(value, str):
        recap_judgment.reject(path, "expected a string")
    if state.has_barred(value):
        recap_judgment.reject(path, "must not contain a line break, control, format or separator character")
    if not value.strip():
        recap_judgment.reject(path, "must not be empty")
    if any(len(form) > cap for form in recap_judgment.forms(value)):
        recap_judgment.reject(path, f"must be at most {cap} characters")


def check_text(value, path):
    check_string(value, path, TEXT_CHARS)
    if any(URL.search(form) for form in recap_judgment.forms(value)):
        recap_judgment.reject(path, "must not contain a URL, the links come from the cited items")


def check_cites(value, path, items):
    if not isinstance(value, list) or not value:
        recap_judgment.reject(path, "expected at least 1 item key")
    seen = set()
    for index, cite in enumerate(value):
        if not isinstance(cite, str) or cite not in items:
            recap_judgment.reject(f"{path}[{index}]", f"{recap_judgment.named(cite)} is not an item of the features")
        if cite in seen:
            recap_judgment.reject(f"{path}[{index}]", f"{recap_judgment.named(cite)} is cited twice in this bullet")
        seen.add(cite)


def check_entry(entry, section, path, items):
    recap_judgment.check_fields(entry, FIELDS[section], path)
    check_text(entry["text"], f"{path}.text")
    if section == "open" and entry["owner"] is not None:
        check_string(entry["owner"], f"{path}.owner", OWNER_CHARS)
    check_cites(entry["cites"], f"{path}.cites", items)


def check_section(entries, section, items):
    if not isinstance(entries, list):
        recap_judgment.reject(section, "expected a list")
    low = 1 if section == "accomplishments" and items else 0
    high = 0 if section == "accomplishments" and not items else LIMITS[section]
    if not low <= len(entries) <= high:
        recap_judgment.reject(section, f"expected {low} to {high} entries, got {len(entries)}")
    for index, entry in enumerate(entries):
        check_entry(entry, section, f"{section}[{index}]", items)


def check_words(document):
    total = 0
    for section in SECTIONS:
        for index, entry in enumerate(document[section]):
            total += len(entry["text"].split())
            if total > TOTAL_WORDS:
                recap_judgment.reject(f"{section}[{index}].text", f"brings all texts to {total} words, at most {TOTAL_WORDS}")


def check_judgment(document, items):
    recap_judgment.check_fields(document, ("schema", *SECTIONS), "")
    weekly_features.SCHEMA(document["schema"], "schema")
    for section in SECTIONS:
        check_section(document[section], section, items)
    check_words(document)


def load_judgment(path, items):
    try:
        return state.load(path, "judgment", lambda document: check_judgment(document, items))
    except state.InvalidJson as error:
        raise Rejected(str(error)) from error


def run_judge(args):
    features = weekly_features.load_features(args.features)
    judged = load_judgment(args.judgment, features["items"])
    summary = {**{name: features[name] for name in SUMMARY_CONTEXT}, **judged}
    state.write_all([(args.out, state.dump(summary))])
    return 0


def build_record(summary, window):
    cited = sorted({key for section in SECTIONS for entry in summary[section] for key in entry["cites"]})
    roles = [weekly_features.ROLE_OF_PREFIX[key.partition(":")[0]] for key in cited]
    return {
        "schema": RECORD_SCHEMA_VERSION,
        "run_at": state.utc_text(window["to_ts"]),
        "window": window,
        "week_start": window["week_start"],
        "report_only": window["report_only"],
        "counts": {
            "items": {role: roles.count(role) for role in weekly_features.ROLE_OF_PREFIX.values()},
            "sections": {section: len(summary[section]) for section in SECTIONS},
        },
        "cited": cited,
        "sources": [{name: row[name] for name in SOURCE_FIELDS} for row in summary["sources"]],
    }


def next_state(previous, record):
    last_run = {"run_at": record["run_at"], "week_start": record["week_start"]}
    return {"schema": previous["schema"], "digest": previous["digest"], "last_run": last_run}


def run_apply(args):
    raw, previous = state.load_raw(args.state, "state", weekly_state.check_state)
    summary = weekly_features.load_summary(args.summary)
    window = state.load(args.window, "window", weekly_window.check_window)
    record = build_record(summary, window)
    written = raw if window["report_only"] else state.dump(next_state(previous, record))
    state.write_all([(args.out, written), (args.record, state.dump(record))])
    return 0


COMMANDS = {
    "init": run_init,
    "window": run_window,
    "features": weekly_features.run_features,
    "judge": run_judge,
    "apply": run_apply,
    "message": weekly_message.run_message,
}


def build_parser():
    parser = argparse.ArgumentParser(prog="weekly.py", description="Weekly status engine")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="write the empty state of a weekly routine that has none")
    for flag in ("--digest", "--out"):
        init.add_argument(flag, required=True)
    window = commands.add_parser("window", help="compute the week of --now, from Monday 00:00 in --tz")
    for flag in ("--state", "--now", "--tz", "--out"):
        window.add_argument(flag, required=True)
    window.add_argument("--report-only", action="store_true", help="marks the window, which keeps no cursor and so changes nothing else")
    features = commands.add_parser("features", help="write the items of the week and the sources read; decides nothing")
    for flag in ("--config", "--routine", "--window", "--collections", "--out"):
        features.add_argument(flag, required=True)
    features.add_argument("--recap", help="folder holding the recap routine's state.json and its runs/ records")
    judge = commands.add_parser("judge", help="check the judgment against the features and write the summary")
    for flag in ("--features", "--judgment", "--out"):
        judge.add_argument(flag, required=True)
    apply = commands.add_parser("apply", help="write the next state and the run record from the summary")
    for flag in ("--state", "--summary", "--window", "--out", "--record"):
        apply.add_argument(flag, required=True)
    message = commands.add_parser("message", help="render the status message from the summary and the features")
    for flag in ("--summary", "--features", "--out"):
        message.add_argument(flag, required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except state.InputError as error:
        print(f"weekly.py: {error}", file=sys.stderr)
        return 2
    except state.Rejected as error:
        print(f"weekly.py: rejected: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
