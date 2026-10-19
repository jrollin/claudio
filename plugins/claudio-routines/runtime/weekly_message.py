from datetime import date, timedelta

import digest
import recap_judgment
import state
import weekly_features
from state import InputError

ROLE_NAMES = {"issue_tracker": "issue tracker", "code_host": "code host", "chat": "chat", "document_store": "document store"}
HEADINGS = (("accomplishments", "Key accomplishments", "None"), ("decisions", "Decisions", "None recorded"), ("open", "Still open / next week", "None"))
PAGE_LABEL_WORDS = 6


def title_line(week_start):
    day = date.fromisoformat(week_start)
    monday = day - timedelta(days=day.weekday())
    return f"**Weekly status, week of {state.DAYS[0]} {monday:%d} {digest.MONTHS[monday.month - 1]}**"


def pull_request_label(key):
    repo, _, number = key.partition(":")[2].rpartition("#")
    return f"{repo.rpartition('/')[2]}#{number}"


def link_label(key, item):
    kind = item["kind"]
    if kind == "issue":
        return digest.text(key.partition(":")[2])
    if kind == "pull_request":
        return digest.text(pull_request_label(key))
    if kind == "dm":
        return "DM"
    if kind == "thread":
        name = (item.get("channel_name") or "").lstrip("#").strip()
        return f"thread in #{digest.text(name)}" if name else "thread"
    return digest.text(" ".join(item["title"].split()[:PAGE_LABEL_WORDS]))


def link_markup(key, item):
    label = link_label(key, item)
    url = digest.clean(item["link"])
    if not url.lower().startswith(digest.WEB_SCHEMES):
        return label
    for character, escape in digest.LINK_ESCAPES:
        url = url.replace(character, escape)
    return f"[{label}]({url})"


def cited_item(key, items, path):
    if key not in items:
        raise InputError(f"message: {path}: {recap_judgment.named(key)} is not an item of the features")
    return items[key]


def bullet_line(entry, path, items):
    parts = [digest.text(entry["text"])]
    owner = digest.text(entry.get("owner") or "").strip()
    if owner:
        parts.append(f"(owner: {owner})")
    links = [link_markup(key, cited_item(key, items, f"{path}.cites[{index}]")) for index, key in enumerate(entry["cites"])]
    parts.append(f"({', '.join(links)})")
    return "- " + " ".join(parts)


def section_text(heading, lines):
    return digest.section(heading, "\n".join(lines))


def sources_lines(summary, items):
    read = {row["role"] for row in summary["sources"] if row["read"]} | {item["role"] for item in items.values()}
    checked = ", ".join(name for role, name in ROLE_NAMES.items() if role in read) or "none"
    lines = [f"_Sources checked: {checked}._"]
    for row in summary["sources"]:
        if not row["read"]:
            reason = f" ({digest.text(row['reason'])})" if row["reason"] else ""
            lines.append(f"Not read: {digest.text(row['source'])}{reason}")
    return lines


def render(summary, items):
    parts = [title_line(summary["week_start"])]
    for section, heading, empty in HEADINGS:
        lines = [bullet_line(entry, f"{section}[{index}]", items) for index, entry in enumerate(summary[section])]
        parts.append(section_text(heading, lines or [f"- {empty}"]))
    parts.append("\n".join(sources_lines(summary, items)))
    return "\n\n".join(parts) + "\n"


def run_message(args):
    summary = weekly_features.load_summary(args.summary)
    features = weekly_features.load_features(args.features)
    state.write_all([(args.out, render(summary, features["items"]).encode("utf-8"))])
    return 0
