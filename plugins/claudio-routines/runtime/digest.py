import argparse
import json
import sys

import state

LEVELS = tuple(reversed(state.SEVERITY))
RECORD_LISTS = (*state.CHANGES, "muted")


def is_unix_time(value):
    if not state.is_integer(value):
        return False
    try:
        state.utc_text(value)
    except (OverflowError, OSError, ValueError):
        return False
    return True


UNIX_TIME = state.leaf(is_unix_time, "a Unix time in seconds")
ENTRY_SPEC = {
    "key": state.TEXT,
    "rank": state.Nullable(state.RANK),
    "title": state.LABEL,
    "severity": state.SEVERITY_LEVEL,
    "when": state.URGENCY_LEVEL,
    "link": state.LABEL,
    "last_value": state.PRESENT,
    **state.ANALYSIS_SPEC,
}
SUMMARY_SPEC = {
    "new": [ENTRY_SPEC],
    "escalated": [ENTRY_SPEC],
    "resolved": [ENTRY_SPEC],
    "still_open": {level: [{"key": state.TEXT, "title": state.LABEL}] for level in LEVELS},
    "muted_changes": state.INTEGER,
    "blind_spots": [{"key": state.TEXT, "gap": state.LABEL, "runs": state.INTEGER}],
    "blind_spots_dropped": state.INTEGER,
    "overrides": [{"key": state.TEXT, "title": state.LABEL, "state": state.LABEL}],
    "cut": state.Nullable({"from_ts": UNIX_TIME, "to_ts": UNIX_TIME}),
}
RUN_AT = state.leaf(lambda value: state.parses(state.parse_time, value), "a UTC time like 2026-01-31T08:00:00Z")
RECORD_SPEC = {"run_at": RUN_AT, **{name: [state.TEXT] for name in RECORD_LISTS}}
BASE_SPEC = {"run_context": {"collected": state.RUN_CONTEXT_SPEC["collected"]}}


def check_summary(document):
    state.check(document, SUMMARY_SPEC, "")


def check_record(document):
    state.check(document, RECORD_SPEC, "")


def check_next_state(document):
    state.check_state(document)
    state.TEXT(document["digest"], "digest")


def check_base(document):
    state.check(document, BASE_SPEC, "")


def load_input(path, label, checker):
    try:
        return state.load(path, label, checker)
    except state.Rejected as error:
        raise state.InputError(f"{error} (file {path})") from error


def text(value):
    return state.clean_text(value, state.LABEL_CAP)


def value_text(value):
    if value is None:
        return "n/a"
    return text(value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False))


def block(heading, lines):
    return "\n".join([heading, "", *lines]) if lines else ""


def item_head(entry):
    return [f"- {text(entry['title'])} ({entry['severity']}, {entry['when']})", f"  - Link: {text(entry['link'])}"]


def analysis_lines(entry):
    lines = []
    if "risk" in entry:
        lines.append(f"  - Risk: {text(entry['risk'])}")
    if entry.get("reason"):
        lines.append("  - Reason:")
        lines += [f"    - {claim['tag']}: {text(claim['claim'])}" for claim in entry["reason"]]
    if "mitigation" in entry:
        lines.append("  - Mitigation:")
        lines += [f"    - {text(lead)}" for lead in entry["mitigation"]]
    if "action" in entry:
        lines.append(f"  - Action: {text(entry['action'])}")
    return lines


def analysed_lines(entry):
    return item_head(entry) + analysis_lines(entry)


def open_lines(entry, item):
    head = f"- {text(entry['title'])}: since {value_text(item['since'])}, last value {value_text(item['last_value'])}, {text(item['link'])}"
    return [head] + ([f"  - Action: {text(item['action'])}"] if "action" in item else [])


def stored_item(document, key):
    if key not in document["items"]:
        raise state.InputError(f"summary: still_open key {key} is not in the state items")
    return document["items"][key]


def still_open_section(summary, document):
    groups = []
    for level in LEVELS:
        lines = [line for entry in summary["still_open"][level] for line in open_lines(entry, stored_item(document, entry["key"]))]
        if lines:
            groups.append(block(f"### {level}", lines))
    return "\n\n".join(["## Still open", *groups]) if groups else ""


def count_lines(summary):
    counts = (("Muted changes", summary["muted_changes"]), ("Blind spots dropped", summary["blind_spots_dropped"]))
    return [f"- {label}: {count}" for label, count in counts if count]


def cut_lines(summary):
    cut = summary["cut"]
    return [] if cut is None else [f"- Not read: {state.utc_text(cut['from_ts'])} to {state.utc_text(cut['to_ts'])}"]


def unread_sources(base):
    collected = base["run_context"]["collected"]
    return {name: source for name, source in sorted(collected.items()) if not source["read"]}


def unread_lines(unread):
    return [f"- {text(name)}: {text(source['reason'] or 'no reason recorded')}" for name, source in unread.items()]


def blind_spot_lines(summary, unread):
    return [f"- {text(spot['key'])}: {text(spot['gap'])} (runs: {spot['runs']})" for spot in summary["blind_spots"] if spot["key"] not in unread]


def title_line(document, record):
    return f"# {text(document['digest'])}, {text(record['run_at'])}"


def render(summary, document, record, base):
    unread = unread_sources(base)
    sections = [
        block("## New", [line for entry in summary["new"] for line in analysed_lines(entry)]),
        block("## Escalated", [line for entry in summary["escalated"] for line in analysed_lines(entry)]),
        block("## Resolved", [line for entry in summary["resolved"] for line in item_head(entry)]),
        still_open_section(summary, document),
        block("## Not shown", count_lines(summary)),
        block("## Blind spots", blind_spot_lines(summary, unread)),
        block("## Cut", cut_lines(summary)),
        block("## Unread sources", unread_lines(unread)),
        block("## Overrides", [f"- {text(item['key'])}: {text(item['title'])}, state {text(item['state'])}" for item in summary["overrides"]]),
    ]
    return "\n\n".join([title_line(document, record), *[section for section in sections if section]]) + "\n"


def run(args):
    summary = load_input(args.summary, "summary", check_summary)
    document = load_input(args.state, "state", check_next_state)
    record = load_input(args.record, "record", check_record)
    base = load_input(args.base, "base", check_base)
    state.write_all([(args.out, render(summary, document, record, base).encode("utf-8"))])


def build_parser():
    parser = argparse.ArgumentParser(prog="digest.py", description="Prod watch digest, rendered from the change summary")
    for flag in ("--summary", "--state", "--record", "--base", "--out"):
        parser.add_argument(flag, required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except state.InputError as error:
        print(f"digest.py: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
