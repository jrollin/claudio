import re

import state
import tribe_page
import tribe_publish
import tribe_state
from state import InputError

RUNWAY = re.compile(r"(\d+(?:\.\d+)?)\s*(minute|hour|day|week|month)s?\b", re.IGNORECASE)
UNIT_DAYS = {"minute": 1 / 1440, "hour": 1 / 24, "day": 1, "week": 7, "month": 30}
URGENT_RUNWAY_DAYS = 14
URGENT_SHOWN = 5
CHECKS_SHOWN = 5
NAMES_SHOWN = 3
CHANGES = ("new", "moved", "same")
TOP_SEVERITY = tribe_state.SEVERITIES[-1]
WEEK_GROUP, MONTH_END_GROUP, INVESTIGATE_GROUP = tribe_state.CHECK_GROUPS
LATER_WHENS = ("within months", "watch")
DEGRADED = {"judgment": "judgment rejected, no page written", "structure": "structure check failed, no page written"}
CAUSES = tuple(DEGRADED)
SUMMARY_FLAGS = ("summary", "config", "routine", "place")

WARNING_SPEC = {
    "title": tribe_state.TITLE,
    "severity": tribe_state.SEVERITY_LEVEL,
    "when": tribe_state.WHEN_LEVEL,
    "runway": tribe_state.LABEL,
    "change": tribe_state.one_of(CHANGES),
    "mitigation": [state.TEXT],
}
CHECK_SPEC = {"text": state.TEXT, "group": tribe_state.CHECK_GROUP, "since": tribe_state.UTC_TIME}
MESSAGE_SPEC = {
    **tribe_publish.SUMMARY_SPEC,
    "baseline": state.BOOLEAN,
    "window": {"from_ts": state.INTEGER, "to_ts": state.INTEGER},
    "warnings": {"*": WARNING_SPEC},
    "checks": {"*": CHECK_SPEC},
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


def phrase(text):
    return clean(text).rstrip(".")


def urgent_order(entry):
    key, warning = entry
    return (-tribe_state.SEVERITIES.index(warning["severity"]), CHANGES.index(warning["change"]), key)


def counts_line(summary, urgent):
    high = sum(warning["severity"] == TOP_SEVERITY for _, warning in urgent)
    head = f"{len(urgent)} urgent" + (f" ({high} High)" if high else "")
    if summary["baseline"]:
        return f"{head}. Baseline run: no earlier digest to compare with."
    new = sum(warning["change"] == "new" for warning in summary["warnings"].values())
    parts = [head, f"{new} new", f"{len({move['key'] for move in summary['moved']})} moved", f"{len(summary['resolved'])} resolved"]
    if summary["done"]:
        parts.append(f"{len(summary['done'])} ticked")
    return ", ".join(parts) + "."


def more_line(count, what):
    return tribe_page.bullet(f"+{count} more {what}, see the page")


def do_now_line(warning):
    head = f"{clean(warning['severity'])}: {phrase(warning['title'])}"
    leads = "; ".join(phrase(lead) for lead in warning["mitigation"])
    return tribe_page.bullet(f"{head}. Next: {leads}" if leads else head)


def do_now_lines(urgent):
    lines = [do_now_line(warning) for _, warning in urgent[:URGENT_SHOWN]]
    return lines + ([more_line(len(urgent) - URGENT_SHOWN, "urgent")] if len(urgent) > URGENT_SHOWN else [])


def this_week_lines(summary):
    lines = [tribe_page.bullet(f"Decision: {clean(entry['decision'])}, {clean(entry['deadline'])}") for entry in summary["decisions"]]
    # Newest first: fresh checks belong to this run's warnings; the stale ones stay on the page.
    due = sorted((item for item in summary["checks"].items() if item[1]["group"] == WEEK_GROUP), key=lambda item: item[0])
    due.sort(key=lambda item: item[1]["since"], reverse=True)
    lines += [tribe_page.bullet(f"Check: {clean(check['text'])}") for _, check in due[:CHECKS_SHOWN]]
    return lines + ([more_line(len(due) - CHECKS_SHOWN, "checks")] if len(due) > CHECKS_SHOWN else [])


def names(titles):
    shown = [phrase(title) for title in titles[:NAMES_SHOWN]]
    return ", ".join(shown + ([f"+{len(titles) - NAMES_SHOWN}"] if len(titles) > NAMES_SHOWN else []))


def horizon_lines(calm):
    counts = [(sum(warning["when"] == when for _, warning in calm), when) for when in LATER_WHENS]
    parts = [f"{count} {when}" for count, when in counts if count]
    return [tribe_page.bullet(", ".join(parts))] if parts else []


def later_check_lines(summary):
    groups = ((MONTH_END_GROUP, "before the month-end"), (INVESTIGATE_GROUP, "to investigate"))
    counts = [(sum(check["group"] == group for check in summary["checks"].values()), label) for group, label in groups]
    parts = [f"{count} {label}" for count, label in counts if count]
    return [tribe_page.bullet("Checks: " + ", ".join(parts))] if parts else []


def change_lines(summary, calm):
    if summary["baseline"]:
        return []
    new = [warning["title"] for _, warning in calm if warning["change"] == "new"]
    resolved = [entry["title"] for entry in summary["resolved"]]
    parts = [f"{label}: {names(titles)}" for label, titles in (("New", new), ("Resolved", resolved)) if titles]
    return [tribe_page.bullet(". ".join(parts))] if parts else []


def later_lines(summary, calm):
    return horizon_lines(calm) + later_check_lines(summary) + change_lines(summary, calm)


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
    entries = sorted(summary["warnings"].items(), key=urgent_order)
    urgent = [entry for entry in entries if is_urgent(entry[1])]
    calm = [entry for entry in entries if not is_urgent(entry[1])]
    parts = [
        f"# {clean(title)}\n{run_line(summary)}\n{counts_line(summary, urgent)}",
        block("## Do now", do_now_lines(urgent)),
        block("## This week", this_week_lines(summary)),
        block("## Later", later_lines(summary, calm)),
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
