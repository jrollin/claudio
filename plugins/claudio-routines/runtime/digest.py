import argparse
import functools
import json
import re
import sys
from datetime import datetime

import state

LEVELS = tuple(reversed(state.SEVERITY))
RECORD_LISTS = (*state.CHANGES, "muted")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MARKS = {"now": "🔴", "within months": "🟠", "watch": "🟡"}
ESCALATED = "⬆️"
SEPARATOR = " · "
OPEN_SHOWN = 3
MONITOR_LINK = re.compile(r"[^?#]*?/monitors/([0-9]+)(?:[/?#]|$)")
DOUBLE_STAR = re.compile(r"\*(?=\*)")
LINK_ESCAPES = (("(", "%28"), (")", "%29"), (" ", "%20"), ("\\", "%5C"))
WEB_SCHEMES = ("https://", "http://")


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
    window = document["run"]["window"]
    if window is not None:
        UNIX_TIME(window["from_ts"], "run.window.from_ts")


def check_base(document):
    state.check(document, BASE_SPEC, "")


def load_input(path, label, checker):
    try:
        return state.load(path, label, checker)
    except state.Rejected as error:
        raise state.InputError(f"{error} (file {path})") from error


def clean(value):
    return state.clean_text(value, state.LABEL_CAP)


def text(value):
    return DOUBLE_STAR.sub("* ", clean(value)).replace("](", "] (")


def value_text(value):
    if value is None:
        return "n/a"
    return text(value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False))


def day_time(moment):
    return f"{state.DAYS[moment.weekday()]} {moment:%H:%M}"


def date_time(moment):
    return f"{moment:%d} {MONTHS[moment.month - 1]} {moment:%H:%M}"


def title_lines(document, run_at):
    city = run_at.tzinfo.key.rsplit("/", 1)[-1].replace("_", " ")
    return [f"**{text(document['digest'])}, {date_time(run_at)} {city}**", window_line(document["run"], run_at.tzinfo)]


def window_line(run, zone):
    if run["previous_at"] is None or run["window"] is None:
        return "(baseline)"
    return f"(since {day_time(datetime.fromtimestamp(run['window']['from_ts'], zone))})"


def since_text(items, run_at, key):
    stored = items[key]["since"] if key in items else None
    try:
        moment = state.parse_time(stored).astimezone(run_at.tzinfo)
    except (OverflowError, ValueError):
        return value_text(stored)
    return f"{moment:%H:%M}" if moment.date() == run_at.date() else date_time(moment)


def link_text(entry):
    link = clean(entry["link"])
    match = MONITOR_LINK.match(link)
    label = f"monitor {match.group(1)}" if match else "metric"
    if not link.lower().startswith(WEB_SCHEMES):
        return label
    for character, escape in LINK_ESCAPES:
        link = link.replace(character, escape)
    return f"[{label}]({link})"


def analysis_lines(entry):
    lines = []
    if "risk" in entry:
        lines.append(f"- **Risk:** {text(entry['risk'])}")
    if entry.get("reason"):
        lines.append("- **Reason:** " + "; ".join(f"{text(claim['claim']).removesuffix('.')} ({claim['tag']})" for claim in entry["reason"]))
    if "mitigation" in entry:
        lines.append("- **Mitigation:** " + "; ".join(text(lead) for lead in entry["mitigation"]))
    if "action" in entry:
        lines.append(f"- **Action:** {text(entry['action'])}")
    return lines


def entry_block(entry, since, prefix=""):
    head = f"{prefix}{MARKS[entry['when']]} **{text(entry['title'])}**"
    detail = SEPARATOR.join([entry["severity"], entry["when"], f"since {since(entry['key'])}", link_text(entry)])
    return "\n".join([head, detail, *analysis_lines(entry)])


def resolved_line(entry):
    return f"✅ **{text(entry['title'])}**{SEPARATOR}{link_text(entry)}{SEPARATOR}last value {value_text(entry['last_value'])}"


def open_line(level, entries):
    titles = [text(entry["title"]) for entry in entries[:OPEN_SHOWN]]
    rest = len(entries) - OPEN_SHOWN
    return f"- {level}: " + ", ".join(titles + ([f"+{rest}"] if rest > 0 else []))


def section(heading, body):
    return f"**{heading}**\n{body}" if body else ""


def counted(count, noun):
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def labelled(label, parts, separator):
    return f"**{label}:** {separator.join(parts)}" if parts else ""


def open_total(summary):
    return sum(len(entries) for entries in summary["still_open"].values())


def summary_line(summary, total):
    counts = (len(summary["new"]), "new"), (len(summary["escalated"]), "escalated"), (len(summary["resolved"]), "resolved"), (total, "still open")
    return "- " + ", ".join(f"{count} {name}" for count, name in counts)


def change_section(heading, entries, since, prefix=""):
    return section(heading, "\n\n".join(entry_block(entry, since, prefix) for entry in entries))


def still_open_section(summary, total):
    levels = [(level, summary["still_open"][level]) for level in LEVELS]
    return section(f"Still open ({total})", "\n".join(open_line(level, entries) for level, entries in levels if entries))


def unread_sources(base):
    collected = base["run_context"]["collected"]
    return {name: source for name, source in sorted(collected.items()) if not source["read"]}


def blind_spot_parts(summary, unread, items, zone):
    spots = [spot for spot in summary["blind_spots"] if spot["key"] not in unread]
    parts = [f"{text(items[spot['key']]['title'] if spot['key'] in items else spot['key'])} {text(spot['gap'])} ({counted(spot['runs'], 'run')})" for spot in spots]
    parts += [f"{text(name)} not read ({text(source['reason'] or 'no reason recorded')})" for name, source in unread.items()]
    cut = summary["cut"]
    if cut is not None:
        parts.append(f"metrics before {day_time(datetime.fromtimestamp(cut['to_ts'], zone))} not read")
    return parts


def not_shown_parts(summary):
    muted, dropped = summary["muted_changes"], summary["blind_spots_dropped"]
    return ([counted(muted, "muted change")] if muted else []) + ([f"{counted(dropped, 'blind spot')} dropped"] if dropped else [])


def override_parts(summary):
    return [f"{text(item['title'])} ({text(item['state'])})" for item in summary["overrides"]]


def render(summary, document, record, base, zone):
    run_at = state.parse_time(record["run_at"]).astimezone(zone)
    since = functools.partial(since_text, document["items"], run_at)
    total = open_total(summary)
    gaps = [
        labelled("Blind spots", blind_spot_parts(summary, unread_sources(base), document["items"], zone), "; "),
        labelled("Not shown", not_shown_parts(summary), ", "),
        labelled("Overrides", override_parts(summary), "; "),
    ]
    sections = [
        "\n".join(title_lines(document, run_at)),
        section("Summary", summary_line(summary, total)),
        change_section("New", summary["new"], since),
        change_section("Escalated", summary["escalated"], since, ESCALATED),
        section("Resolved", "\n".join(resolved_line(entry) for entry in summary["resolved"])),
        still_open_section(summary, total),
        "\n".join(line for line in gaps if line),
    ]
    return "\n\n".join(part for part in sections if part) + "\n"


def check_still_open_keys(summary, document):
    for level in LEVELS:
        for entry in summary["still_open"][level]:
            if entry["key"] not in document["items"]:
                raise state.InputError(f"summary: still_open key {entry['key']} is not in the state items")


def rendered(summary, document, record, base, zone):
    try:
        return render(summary, document, record, base, zone).encode("utf-8")
    except OverflowError as error:
        raise state.InputError(f"--tz {zone.key}: a time of the message is out of range ({error})") from error


def run(args):
    zone = state.load_zone(args.tz)
    summary = load_input(args.summary, "summary", check_summary)
    document = load_input(args.state, "state", check_next_state)
    record = load_input(args.record, "record", check_record)
    base = load_input(args.base, "base", check_base)
    check_still_open_keys(summary, document)
    state.write_all([(args.out, rendered(summary, document, record, base, zone))])


def build_parser():
    parser = argparse.ArgumentParser(prog="digest.py", description="Prod watch digest, rendered from the change summary")
    for flag in ("--summary", "--state", "--record", "--base", "--tz", "--out"):
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
