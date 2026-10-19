import calendar
import re
from datetime import date, datetime, timezone

import roles
import state
import tribe_state

H2 = (
    "Since last run",
    "Decisions this week",
    "Warnings",
    "What to check",
    "Details",
    "Blind spots",
    "Corrections to earlier numbers",
    "Sources",
    "How this digest is built",
    "Run state",
)
TOGGLE = ' {toggle="true"}'
FOCUS = "### Focus"
FOCUS_COLUMNS = ("Topic", "Severity", "When", "Warnings")
TOPIC_COLUMNS = ("Warning", "Severity", "Risk", "Impact", "Mitigation leads", "Evidence")
DECISION_COLUMNS = ("Decision", "Deadline", "Options, from the leads", "Topic")
SOURCE_COLUMNS = ("Source", "Role", "Read", "Window")
WHEN_ICONS = {"now": "🔴", "within months": "🟠", "watch": "🟡"}
WARNING_MARKER = re.compile(rf'<span color="gray">key: ({tribe_state.KEY.pattern})</span>$')
TODO = re.compile(r"^- \[( |x)\] (.*)$")
TODO_TAG = re.compile(r'^<span color="gray_bg">.*?</span> ')
TODO_MARKER = re.compile(rf' <span color="gray">({tribe_state.KEY.pattern})</span>\s*$')
TABLE_START = re.compile(r"^<table[ >]")
DATED_MONTH_END = re.compile(r"Before the ([0-9]{4}-[0-9]{2}-[0-9]{2}) month-end")


def clock(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def at(text):
    return clock(state.parse_time(text))


def at_ts(timestamp):
    return clock(datetime.fromtimestamp(timestamp, timezone.utc))


def window_text(window):
    return f"{at_ts(window['from_ts'])} to {at_ts(window['to_ts'])}"


def severity_rank(warning):
    return tribe_state.SEVERITIES.index(warning["severity"])


def urgency_rank(warning):
    return state.URGENCY.index(warning["when"])


def by_topic(warnings):
    topics = {}
    for key in sorted(warnings):
        topics.setdefault(warnings[key]["topic"], []).append(key)

    def topic_rank(topic):
        entries = [warnings[key] for key in topics[topic]]
        return (-max(map(severity_rank, entries)), -max(map(urgency_rank, entries)), topic)

    def warning_rank(key):
        return (-severity_rank(warnings[key]), -urgency_rank(warnings[key]), key)

    return [(topic, sorted(topics[topic], key=warning_rank)) for topic in sorted(topics, key=topic_rank)]


def bullets(items):
    return "<br>".join(f"  • {item}" for item in items)


def listed(value):
    items = [value] if isinstance(value, str) else list(value)
    return items[0] if len(items) == 1 else bullets(items)


def cited(text, cites):
    links = {cite["link"]: cite["source"] for cite in cites if "link" in cite}
    return text + "".join(f" [{source}]({link})" for link, source in links.items())


def table(header, rows):
    lines = ['<table header-row="true">']
    for cells in (header, *rows):
        lines += ["<tr>", *(f"<td>{cell}</td>" for cell in cells), "</tr>"]
    return [*lines, "</table>"]


def tabbed(lines):
    return [f"\t{line}" for line in lines]


def ended(text):
    return text if text.endswith(".") else text + "."


def bullet(text):
    return f"- {ended(text)}"


def gray_bg(text):
    return f'<span color="gray_bg">{text}</span>'


def gray(text):
    return f'<span color="gray">{text}</span>'


def page_link(template, page_id):
    return roles.PLACEHOLDER.sub(lambda found: page_id if found.group(1) in roles.LINK_VALUES else found.group(0), template)


def header_callout(summary, link):
    previous = summary["previous_page"]
    previous_line = "- Previous run: none, this is the first digest."
    if previous:
        mention = f'<mention-page url="{page_link(link, previous["id"])}"/>'
        previous_line = f"- Previous run: {mention}, written {at(previous['written_at'])}."
    lines = [f"- Run: {at(summary['run_at'])}, window {window_text(summary['window'])}.", previous_line]
    lines.append("- Format: layout version 1. Run state: the last toggle of this page, never the state itself.")
    return ['<callout icon="🗓️" color="gray_bg">', *tabbed(lines), "</callout>"]


def since_last_run(summary):
    titles = {key: warning["title"] for key, warning in summary["warnings"].items()}
    lines = []
    if summary["baseline"]:
        lines.append("- Baseline run: no earlier digest to compare with.")
    else:
        lines += [
            f"- New: {warning['title']}, {warning['severity']}, {warning['when']}."
            for _, warning in sorted(summary["warnings"].items())
            if warning["change"] == "new"
        ]
        lines += [bullet(f"Resolved: {entry['title']}, {entry['reason']}") for entry in summary["resolved"]]
        lines += [
            f"- Moved: {titles.get(move['key'], move['key'])}, {move['field']} from {move['from']} to {move['to']}."
            for move in summary["moved"]
        ]
        lines += [bullet(f"Ticked: {entry['text']}") for entry in summary["done"]]
    lines += [f"- {cited(entry['text'], entry['cites'])}" for entry in summary["highlights"]]
    lines += [f"- Page edit ignored: {entry['where']}, {entry['why']}." for entry in summary["edits_ignored"]]
    return lines or ["- No change since the previous run."]


def decisions_lines(decisions):
    if not decisions:
        return ["- None this week."]
    rows = [[entry["decision"], entry["deadline"], entry["options"], entry["topic"]] for entry in decisions]
    return table(DECISION_COLUMNS, rows)


def warning_row(key, warning):
    evidence = [f"confidence: {warning['confidence']}"]
    evidence += [f"  • {cited(entry['claim'], entry['cites'])}" for entry in warning["evidence"]]
    return [
        f'{warning["title"]}<br>status: {warning["status"]}<br>{gray("key: " + key)}',
        f'{warning["severity"]}<br>{WHEN_ICONS[warning["when"]]} {warning["when"]}<br>runway: {warning["runway"]}',
        listed(warning["risk"]),
        listed(warning["impact"]),
        listed(warning["mitigation"]),
        "<br>".join(evidence),
    ]


def focus_row(topic, keys, warnings):
    entries = [warnings[key] for key in keys]
    top = max(entries, key=severity_rank)
    soonest = max(entries, key=urgency_rank)
    return [topic, top["severity"], f"{WHEN_ICONS[soonest['when']]} {soonest['when']}", str(len(keys))]


def warnings_lines(summary, values):
    warnings = summary["warnings"]
    topics = by_topic(warnings)
    lines = ['<callout icon="📏" color="gray_bg">', *tabbed(values["key_callout"]), "</callout>", FOCUS]
    if topics:
        lines += table(FOCUS_COLUMNS, [focus_row(topic, keys, warnings) for topic, keys in topics])
    else:
        lines.append("- No open warning.")
    for topic, keys in topics:
        lines.append(f"### {topic}")
        lines += table(TOPIC_COLUMNS, [warning_row(key, warnings[key]) for key in keys])
    return lines


def topic_position(topics):
    order = {topic: position for position, (topic, _) in enumerate(topics)}
    return lambda topic: (order.get(topic, len(order)), topic)


def month_end(run_at, zone):
    local = state.parse_time(run_at).astimezone(zone)
    return date(local.year, local.month, calendar.monthrange(local.year, local.month)[1])


def is_month_end(text):
    try:
        day = date.fromisoformat(text)
    except ValueError:
        return False
    return day.day == calendar.monthrange(day.year, day.month)[1]


def group_heading(group, last_day):
    return f"Before the {last_day.isoformat()} month-end" if group == tribe_state.MONTH_END_GROUP else group


def stored_group(heading):
    dated = DATED_MONTH_END.fullmatch(heading)
    return tribe_state.MONTH_END_GROUP if dated and is_month_end(dated.group(1)) else heading


def todo_line(key, check):
    return f'- [ ] {gray_bg(check["topic"])} {check["text"]} {gray(key)}'


def checks_lines(summary, topics, zone):
    position = topic_position(topics)
    last_day = month_end(summary["run_at"], zone)
    checks = summary["checks"]
    for key in sorted(checks):
        if checks[key]["group"] not in tribe_state.CHECK_GROUPS:
            raise ValueError(f"check {key}: group {checks[key]['group']} is not one of {', '.join(tribe_state.CHECK_GROUPS)}")
    lines = []
    for group in tribe_state.CHECK_GROUPS:
        keys = sorted((k for k in checks if checks[k]["group"] == group), key=lambda k: (position(checks[k]["topic"]), k))
        if keys:
            lines.append(f"### {group_heading(group, last_day)}")
            lines += [todo_line(key, checks[key]) for key in keys]
    return lines or ["- No open check."]


def details_lines(summary, topics):
    lines = []
    for topic in sorted(summary["details"], key=topic_position(topics)):
        lines.append(f"### {topic}")
        lines += [f"- {cited(entry['text'], entry['cites'])}" for entry in summary["details"][topic]]
    return lines or ["- Nothing new."]


def coverage_note_line(note):
    source = state.clean_text(note["source"], tribe_state.COVERAGE_SOURCE_CAP)
    return bullet(f"{source}: {state.clean_text(note['text'], state.LABEL_CAP)}")


def blind_spots_lines(summary):
    lines = [f"- {spot['key']}: {spot['gap']} (runs: {spot['runs']})." for spot in summary["blind_spots"]]
    if summary["blind_spots_dropped"]:
        lines.append(f"- More gaps not listed: {summary['blind_spots_dropped']}.")
    lines += [coverage_note_line(note) for note in summary["coverage_notes"]]
    return lines or ["- None."]


def corrections_lines(summary):
    lines = [bullet(f"Was: {ended(entry['was'])} Now: {cited(entry['now'], entry['cites'])}") for entry in summary["corrections"]]
    return lines or ["- None."]


def sources_lines(summary):
    rows = []
    for entry in summary["sources"]:
        reason = state.clean_text(entry["reason"], state.LABEL_CAP) if entry["reason"] else ""
        read = "yes" if entry["read"] else f"no, {reason}" if reason else "no"
        span = window_text(entry) if entry["from_ts"] is not None and entry["to_ts"] is not None else "none"
        rows.append([entry["source"], entry["role"], read, span])
    return table(SOURCE_COLUMNS, rows) if rows else ["- None."]


def run_state_lines(summary, values):
    previous = summary["previous_page"]
    previous_id = previous["id"] if previous else "none"
    return tabbed(
        [
            f"- Window: {window_text(summary['window'])}.",
            f"- Pages: previous {previous_id}; the id of this page is saved in the state once it is created.",
            f"- State: {values['state_path']}, read by the next run instead of this page.",
        ]
    )


def render(summary, routine_values, zone):
    topics = by_topic(summary["warnings"])
    sections = {
        "Since last run": since_last_run(summary),
        "Decisions this week": decisions_lines(summary["decisions"]),
        "Warnings": warnings_lines(summary, routine_values),
        "What to check": checks_lines(summary, topics, zone),
        "Details": details_lines(summary, topics),
        "Blind spots": blind_spots_lines(summary),
        "Corrections to earlier numbers": corrections_lines(summary),
        "Sources": sources_lines(summary),
        "How this digest is built": tabbed(routine_values["how_built"]),
        "Run state": run_state_lines(summary, routine_values),
    }
    lines = [*header_callout(summary, routine_values["link"]), "<table_of_contents/>"]
    for heading in H2:
        suffix = TOGGLE if heading in ("How this digest is built", "Run state") else ""
        lines += [f"## {heading}{suffix}", *sections[heading]]
    return "\n".join(lines) + "\n"


def section(lines, name):
    found, inside = [], False
    for line in lines:
        if line.startswith("## "):
            inside = line[3:].removesuffix(TOGGLE) == name
        elif inside:
            found.append(line)
    return found


def read_tables(lines):
    tables, heading, rows, cells = [], "", None, None
    for line in lines:
        if line.startswith("### "):
            heading = line
        elif TABLE_START.match(line):
            rows = []
        elif line == "<tr>" and rows is not None:
            cells = []
        elif line.startswith("<td>") and line.endswith("</td>") and cells is not None:
            cells.append(line[4:-5])
        elif line == "</tr>" and cells is not None:
            rows.append(cells)
            cells = None
        elif line == "</table>" and rows is not None:
            tables.append((heading, rows))
            rows = None
    return tables


def topic_rows(lines):
    return [row for heading, rows in read_tables(lines) if heading != FOCUS for row in rows[1:]]


def marker_key(marker):
    return marker.group(1) if marker and len(marker.group(1)) <= tribe_state.KEY_CAP else None


def cell(row, index):
    return row[index] if index < len(row) else ""


def header_text(rows):
    return "|".join(rows[0]) if rows else ""


def has_row_markers(row):
    return (
        "<br>status: " in cell(row, 0)
        and "<br>runway: " in cell(row, 1)
        and cell(row, 5).startswith("confidence: ")
    )


def check_focus(focus, topics):
    failures = []
    bad_headers = [header_text(rows) for rows in focus if rows[:1] != [list(FOCUS_COLUMNS)]]
    if bad_headers:
        failures.append(f"Focus table header: {bad_headers[0]}")
    listed_counts = sorted(tuple(row[:1] + row[3:4]) for rows in focus for row in rows[1:])
    table_counts = sorted((heading[4:], str(len(rows) - 1)) for heading, rows in topics)
    if listed_counts != table_counts:
        failures.append(f"Focus counts: {pairs(listed_counts)} vs tables {pairs(table_counts)}")
    return failures


def pairs(items):
    return ", ".join("=".join(item) for item in items)


def check_topics(topics):
    failures = []
    bad_headers = [heading for heading, rows in topics if rows[:1] != [list(TOPIC_COLUMNS)]]
    if bad_headers:
        failures.append(f"topic table headers: {', '.join(bad_headers)}")
    rows = [row for _, table_rows in topics for row in table_rows[1:]]
    for name, bad in (
        ("row cells", sum(len(row) != len(TOPIC_COLUMNS) for row in rows)),
        ("row markers", sum(not has_row_markers(row) for row in rows)),
        ("key markers", sum(marker_key(WARNING_MARKER.search(cell(row, 0))) is None for row in rows)),
    ):
        if bad:
            failures.append(f"{name}: {bad} of {len(rows)} rows")
    return failures


def check_warnings(lines):
    failures = []
    headings = [line for line in lines if line.startswith("### ")]
    first = headings[0] if headings else ""
    if first != FOCUS:
        failures.append(f"first h3 under Warnings: {first}")
    tables = read_tables(lines)
    focus = [rows for heading, rows in tables if heading == FOCUS]
    topics = [(heading, rows) for heading, rows in tables if heading != FOCUS]
    return failures + check_focus(focus, topics) + check_topics(topics)


def check_decisions(lines):
    failures = []
    bad_headers = [header_text(rows) for _, rows in read_tables(lines) if rows[:1] != [list(DECISION_COLUMNS)]]
    if bad_headers:
        failures.append(f"decisions header: {bad_headers[0]}")
    count = max(sum(line == "<tr>" for line in lines) - 1, 0)
    if count > tribe_state.DECISION_CAP:
        failures.append(f"decisions: {count} rows")
    return failures


def check_todos(lines):
    failures = []
    groups = [line[4:] for line in lines if line.startswith("### ")]
    bad_groups = [group for group in groups if stored_group(group) not in tribe_state.CHECK_GROUPS]
    if bad_groups:
        failures.append(f"check groups: {', '.join(bad_groups)}")
    untagged = sum('<span color="gray_bg">' not in line for line in lines if TODO.match(line))
    if untagged:
        failures.append(f"untagged checks: {untagged}")
    return failures


def check(markdown, with_state=True):
    lines = markdown.split("\n")
    expected = H2 if with_state else H2[:-1]
    actual = tuple(line[3:].removesuffix(TOGGLE) for line in lines if line.startswith("## "))
    failures = [] if actual == expected else [f"h2 order: {'|'.join(actual)}"]
    failures += check_warnings(section(lines, "Warnings"))
    failures += check_decisions(section(lines, "Decisions this week"))
    failures += check_todos(section(lines, "What to check"))
    return failures


def minute(text):
    return state.parse_time(text).astimezone(timezone.utc).replace(second=0, microsecond=0)


def merge_warning_rows(lines, stored, edits):
    seen = set()
    for number, row in enumerate(topic_rows(section(lines, "Warnings")), 1):
        segments = row[0].split("<br>") if row else [""]
        key = marker_key(WARNING_MARKER.search(segments[-1]))
        if key is None:
            edits["ignored"].append({"where": f"warning row {number}", "why": "no key marker"})
        elif key not in stored["warnings"]:
            edits["ignored"].append({"where": f"warning row {number}", "why": "key matches no stored warning"})
        elif key in seen:
            edits["ignored"].append({"where": f"warning {key}", "why": "key repeated"})
        else:
            seen.add(key)
            merge_warning(key, segments, stored["warnings"][key], edits)


def merge_warning(key, segments, current, edits):
    where = f"warning {key}"
    if segments[0] != current["title"]:
        edits["ignored"].append({"where": where, "why": "title edited"})
    status = next((segment[len("status: "):].strip() for segment in segments if segment.startswith("status: ")), None)
    if status is None:
        edits["ignored"].append({"where": where, "why": "no status line"})
    elif status in tribe_state.STATUSES:
        if status != current["status"]:
            edits["statuses"][key] = status
    else:
        edits["ignored"].append({"where": where, "why": "status outside the allowed values"})


def merge_todos(lines, stored, edits):
    seen = set()
    todos = [TODO.match(line) for line in section(lines, "What to check")]
    for number, todo in enumerate((match for match in todos if match), 1):
        body = todo.group(2)
        tag = TODO_TAG.match(body)
        body = body[tag.end():] if tag else body
        marker = TODO_MARKER.search(body)
        key = marker_key(marker)
        if key is None:
            edits["ignored"].append({"where": f"check {number}", "why": "no key marker"})
        elif key not in stored["checks"]:
            edits["ignored"].append({"where": f"check {number}", "why": "key matches no stored check"})
        elif key in seen:
            edits["ignored"].append({"where": f"check {key}", "why": "key repeated"})
        else:
            seen.add(key)
            if body[: marker.start()] != stored["checks"][key]["text"]:
                edits["ignored"].append({"where": f"check {key}", "why": "text edited"})
            edits["ticked" if todo.group(1) == "x" else "unticked"].append(key)


def parse_edits(page_text, stored, written_at, edited_at, page_id=None):
    after_written = minute(edited_at) > minute(written_at)
    edits = {
        "page_id": page_id,
        "edited_at": edited_at,
        "after_written": after_written,
        "statuses": {},
        "ticked": [],
        "unticked": [],
        "ignored": [],
    }
    if after_written:
        lines = page_text.split("\n")
        merge_warning_rows(lines, stored, edits)
        merge_todos(lines, stored, edits)
        edits["ticked"].sort()
        edits["unticked"].sort()
    return edits
