import re

import state
import tribe_page
import tribe_publish
import tribe_state
from state import InputError

RUNWAY = re.compile(r"(\d+(?:\.\d+)?)\s*(minute|hour|day|week|month)s?\b", re.IGNORECASE)
UNIT_DAYS = {"minute": 1 / 1440, "hour": 1 / 24, "day": 1, "week": 7, "month": 30}
URGENT_RUNWAY_DAYS = 14
IMPORTANT_MOVES = ("severity", "when")
CHANGES = ("new", "moved", "same")
DEGRADED = {"judgment": "judgment rejected, no page written", "structure": "structure check failed, no page written"}
CAUSES = tuple(DEGRADED)
SUMMARY_FLAGS = ("summary", "config", "routine", "place")

WARNING_SPEC = {
    "title": tribe_state.TITLE,
    "severity": tribe_state.SEVERITY_LEVEL,
    "when": tribe_state.WHEN_LEVEL,
    "runway": tribe_state.LABEL,
    "metric": tribe_state.METRIC,
    "change": tribe_state.one_of(CHANGES),
}
MESSAGE_SPEC = {
    **tribe_publish.SUMMARY_SPEC,
    "baseline": state.BOOLEAN,
    "window": {"from_ts": state.INTEGER, "to_ts": state.INTEGER},
    "warnings": {"*": WARNING_SPEC},
    "moved": [{"key": state.TEXT, "field": state.TEXT, "from": state.TEXT, "to": state.TEXT}],
    "resolved": [{"title": state.TEXT, "reason": state.TEXT}],
    "done": [{"text": state.TEXT}],
    "decisions": [{"decision": state.TEXT, "deadline": state.TEXT}],
    "blind_spots": [{"key": state.TEXT, "gap": state.TEXT}],
    "blind_spots_dropped": state.INTEGER,
    "coverage_notes": [{"source": state.TEXT}],
    "sources": [{"read": state.BOOLEAN}],
}

clean = tribe_publish.clean


def runway_days(text):
    found = RUNWAY.search(text)
    return None if found is None else float(found.group(1)) * UNIT_DAYS[found.group(2).lower()]


def is_urgent(warning):
    days = runway_days(warning["runway"])
    return warning["when"] == "now" or (days is not None and days < URGENT_RUNWAY_DAYS)


def is_monitor_change(warning):
    return (warning["metric"] or "").startswith(state.MONITOR_PREFIX) and warning["change"] != "same"


def since_lines(summary):
    if summary["baseline"]:
        return ["- Baseline run: no earlier digest to compare with."]
    lines = [
        f"- New: {clean(warning['title'])}, {clean(warning['severity'])}, {clean(warning['when'])}."
        for _, warning in sorted(summary["warnings"].items())
        if warning["change"] == "new"
    ]
    lines += [tribe_page.bullet(f"Resolved: {clean(entry['title'])}, {clean(entry['reason'])}") for entry in summary["resolved"]]
    return lines + [tribe_page.bullet(f"Ticked: {clean(entry['text'])}") for entry in summary["done"]]


def urgent_line(warning):
    return tribe_page.bullet(
        f"Urgent: {clean(warning['title'])}, {clean(warning['severity'])}, {clean(warning['when'])}, runway {clean(warning['runway'])}"
    )


def move_line(move, warnings):
    title = clean(warnings[move["key"]]["title"]) if move["key"] in warnings else clean(move["key"])
    return f"- Moved: {title}, {clean(move['field'])} from {clean(move['from'])} to {clean(move['to'])}."


def important_lines(summary):
    warnings = summary["warnings"]
    keys = sorted(warnings)
    lines = [urgent_line(warnings[key]) for key in keys if is_urgent(warnings[key])]
    lines += [move_line(move, warnings) for move in summary["moved"] if move["field"] in IMPORTANT_MOVES]
    lines += [f"- Monitor: {clean(warnings[key]['title'])}, {clean(warnings[key]['change'])}." for key in keys if is_monitor_change(warnings[key])]
    return lines + [tribe_page.bullet(f"Decision: {clean(entry['decision'])}, {clean(entry['deadline'])}") for entry in summary["decisions"]]


def run_line(summary):
    kind = "report-only" if summary["report_only"] else "baseline" if summary["baseline"] else "regular"
    read = sum(row["read"] for row in summary["sources"])
    return f"Run: {kind} run, window {tribe_page.window_text(summary['window'])}, {read} of {len(summary['sources'])} sources read."


def blind_spots_line(summary):
    names = [f"{clean(spot['key'])} ({clean(spot['gap'])})" for spot in summary["blind_spots"]]
    names += [clean(note["source"], tribe_state.COVERAGE_SOURCE_CAP) for note in summary["coverage_notes"]]
    spots = names[: state.BLIND_SPOT_CAP]
    unlisted = summary["blind_spots_dropped"] + len(names) - len(spots)
    if unlisted:
        spots.append(f"{unlisted} more not listed")
    return f"Blind spots: {', '.join(spots) if spots else 'none'}."


def page_lines(result, link):
    shown = "not written, report-only run." if result["status"] == "report-only" else tribe_page.page_link(link, result["page"])
    lines = [f"Page: {shown}"]
    if result["heading"] == "failed":
        lines.append("Weekly heading: not written, tried again on the next run.")
    return lines


def block(heading, lines):
    return "\n".join([heading, *lines]) if lines else ""


def degraded_create(result):
    return f"degraded: page create failed, {clean(result['reason'] or 'no reason recorded')}\n"


def chat_message(summary, result, title, link):
    parts = [
        f"# {clean(title)}\n{run_line(summary)}",
        block("## Since last run", since_lines(summary)),
        block("## Important", important_lines(summary)),
        "\n".join([blind_spots_line(summary), *page_lines(result, link)]),
    ]
    return "\n\n".join(part for part in parts if part) + "\n"


def check_message_inputs(args):
    given = [flag for flag in (*SUMMARY_FLAGS, "result") if getattr(args, flag) is not None]
    if args.degraded is not None and given:
        raise InputError("message: --degraded excludes " + ", ".join(f"--{flag}" for flag in given))
    if args.degraded is None and args.result is None:
        raise InputError("message: needs --result, or --degraded")


def check_summary_inputs(args):
    missing = [f"--{flag}" for flag in SUMMARY_FLAGS if getattr(args, flag) is None]
    if missing:
        raise InputError("message: a created or report-only result also needs " + ", ".join(missing))


def message_text(args):
    if args.degraded is not None:
        return f"degraded: {DEGRADED[args.degraded]}\n"
    result = tribe_publish.load_result(args.result)
    if result["status"] == "failed":
        return degraded_create(result)
    check_summary_inputs(args)
    summary = tribe_state.load_input(args.summary, "summary", MESSAGE_SPEC)
    page, zone = tribe_publish.load_page(args)
    title = tribe_publish.rendered_title(page, summary["run_at"], zone, args.routine)
    try:
        return chat_message(summary, result, title, page["link"])
    except (OSError, OverflowError, ValueError) as error:
        raise InputError(f"summary: cannot render the message from {args.summary}: {type(error).__name__}") from error


def run_message(args):
    check_message_inputs(args)
    state.write_all([(args.out, message_text(args).encode("utf-8"))])
    return 0
