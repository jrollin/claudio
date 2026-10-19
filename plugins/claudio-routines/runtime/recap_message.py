import re
from collections import namedtuple
from datetime import datetime
from decimal import Decimal
from urllib.parse import quote

import config_tree
import digest
import evaluate
import recap_lifecycle
import recap_state
import recap_window
import roles
import state
import tribe_state
from config import adapter_role, config_directory
from state import InputError, Nullable

DEGRADED = {"judgment": "judgment rejected twice, no recap this run", "structure": "structure check failed, no recap this run"}
CAUSES = tuple(DEGRADED)
SUMMARY_FLAGS = ("summary", "config", "routine", "place", "tz")
COUNTS = ("waiting", "late", "new", "resolved", "waiting_on_others")
HANDLED_SHOWN = 5
LATE_MARK = "⏰ "
KIND_RANK = {"dm": 0, "group_dm": 0, "mention": 1, "group": 2, "thread": 3}
CONVERSATION_LABELS = {"dm": "DM", "group_dm": "group DM"}
PLAIN_HOST = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*")

Context = namedtuple("Context", "run_at zone host")

LINE_SPEC = {
    "kind": recap_state.UNIT_KIND,
    "status": recap_state.UNIT_STATUS,
    "channel": recap_state.NAME,
    "channel_name": Nullable(state.TEXT),
    "ts": recap_state.MESSAGE_TS,
    "root_ts": Nullable(recap_state.MESSAGE_TS),
    "person": Nullable({"name": state.TEXT}),
    "title": state.TEXT,
    "summary": state.TEXT,
    "blocking": state.BOOLEAN,
    "due": Nullable(recap_state.UTC_TIME),
    "late": Nullable(recap_state.COUNT),
    "unanswered_from": Nullable(recap_state.MESSAGE_TS),
    "resolved": state.BOOLEAN,
}
SUMMARY_SPEC = {
    "digest": state.TEXT,
    "run_at": recap_state.UTC_TIME,
    "window": {"from_ts": state.INTEGER},
    "limited": Nullable(recap_state.one_of(recap_window.LIMITS)),
    **{name: [LINE_SPEC] for name in recap_lifecycle.SECTIONS},
    "reading": [{"text": state.TEXT}],
    "counts": {name: recap_state.COUNT for name in COUNTS},
    "blind_spots": [{"gap": state.TEXT}],
}


def stamp_seconds(stamp):
    return int(stamp.partition(".")[0])


def age_stamp(line):
    return line["unanswered_from"] or line["ts"]


def when(moment, run_at):
    if moment.isocalendar()[:2] == run_at.isocalendar()[:2]:
        return digest.day_time(moment)
    return f"{state.DAYS[moment.weekday()]} {digest.date_time(moment)}"


def stamp_when(stamp, context):
    return when(datetime.fromtimestamp(stamp_seconds(stamp), context.zone), context.run_at)


def due_when(due, context):
    return when(state.parse_time(due).astimezone(context.zone), context.run_at)


def link_label(line):
    if line["kind"] in CONVERSATION_LABELS:
        return CONVERSATION_LABELS[line["kind"]]
    name = "" if line["channel_name"] is None else digest.text(line["channel_name"]).lstrip("#").strip()
    return f"{line['kind']} in #{name}" if name else line["kind"]


def link_url(line, host):
    channel = quote(line["channel"], safe="")
    url = f"https://{host}/archives/{channel}/p{line['ts'].replace('.', '')}"
    if line["root_ts"] and line["root_ts"] != line["ts"]:
        url += f"?thread_ts={line['root_ts']}&cid={channel}"
    return url


def link_text(line, context):
    label = link_label(line)
    return label if context.host is None else f"[{label}]({link_url(line, context.host)})"


def person_name(line):
    person = line["person"]
    return "" if person is None else digest.text(person["name"]).strip()


def waiting_line(line, context):
    mark = LATE_MARK if line["late"] is not None else ""
    summary = digest.text(line["summary"])
    if line["status"] == "promise":
        by = "no date given" if line["due"] is None else f"by {due_when(line['due'], context)}"
        head = f"**You** promised {summary}, {by}"
    else:
        name = person_name(line)
        head = f"**{name}** {summary}" if name else summary
    since = f"since {stamp_when(age_stamp(line), context)}"
    return f"- {mark}{head}{digest.SEPARATOR}{since}{digest.SEPARATOR}{link_text(line, context)}"


def good_to_know_line(line, context):
    summary = digest.text(line["summary"])
    head = f"Team ask, no answer: {summary}" if line["status"] == "team_ask" else summary
    return f"- {head}{digest.SEPARATOR}{link_text(line, context)}"


def waiting_on_others_line(line, context):
    name = person_name(line)
    owes = f"**{name}** owes " if name else ""
    since = f"since {stamp_when(age_stamp(line), context)}"
    return f"- {owes}{digest.text(line['summary'])} {since}{digest.SEPARATOR}{link_text(line, context)}"


def handled_line(line, context):
    return f"- {digest.text(line['title'])}{digest.SEPARATOR}{link_text(line, context)}"


def waiting_order(line):
    return (not line["blocking"], KIND_RANK[line["kind"]], Decimal(age_stamp(line)))


def handled_lines(summary, context):
    ordered = sorted(summary["handled"], key=lambda line: not line["resolved"])
    lines = [handled_line(line, context) for line in ordered[:HANDLED_SHOWN]]
    return lines + ([f"- +{len(ordered) - HANDLED_SHOWN}"] if len(ordered) > HANDLED_SHOWN else [])


def lines_section(heading, lines):
    return digest.section(heading, "\n".join(lines))


def city_of(zone):
    return zone.key.rsplit("/", 1)[-1].replace("_", " ")


def window_line(summary, zone, lookback):
    days = digest.counted(lookback, "working day")
    if summary["limited"] == "baseline":
        return f"(baseline, last {days})"
    since = digest.day_time(datetime.fromtimestamp(summary["window"]["from_ts"], zone))
    return f"(since {since}, limited to the last {days})" if summary["limited"] == "gap" else f"(since {since})"


def title_lines(summary, run_at, lookback):
    head = f"**{digest.text(summary['digest'])}, {digest.date_time(run_at)} {city_of(run_at.tzinfo)}**"
    return [head, window_line(summary, run_at.tzinfo, lookback)]


def summary_section(summary):
    counts = summary["counts"]
    lines = [
        f"- {counts['waiting']} waiting on you ({counts['late']} late), {counts['new']} new, "
        f"{counts['resolved']} resolved, {counts['waiting_on_others']} you're waiting on"
    ]
    gaps = [digest.text(spot["gap"]) for spot in summary["blind_spots"]]
    return lines_section("Summary", lines + ([f"- Limits: {'; '.join(gaps)}"] if gaps else []))


def host_of(workspace):
    return workspace if PLAIN_HOST.fullmatch(workspace) else None


def render(summary, workspace, zone, lookback_working_days):
    run_at = state.parse_time(summary["run_at"]).astimezone(zone)
    context = Context(run_at, zone, host_of(workspace))
    waiting = sorted(summary["waiting"], key=waiting_order)
    good_to_know = sorted(summary["good_to_know"], key=lambda line: line["status"] != "team_ask")
    parts = [
        "\n".join(title_lines(summary, run_at, lookback_working_days)),
        summary_section(summary),
        lines_section("Waiting on you", [waiting_line(line, context) for line in waiting]),
        lines_section("Good to know", [good_to_know_line(line, context) for line in good_to_know]),
        lines_section("You're waiting on", [waiting_on_others_line(line, context) for line in summary["waiting_on_others"]]),
        lines_section("Already handled", handled_lines(summary, context)),
        lines_section("Reading", [f"- {digest.text(entry['text'])}" for entry in summary["reading"]]),
    ]
    return "\n\n".join(part for part in parts if part) + "\n"


def degraded(cause):
    if cause not in DEGRADED:
        raise InputError(f"message: unknown degraded cause {cause}, expected one of {', '.join(CAUSES)}")
    return f"degraded: {DEGRADED[cause]}\n"


def load_routine_settings(args):
    _, routine, _ = evaluate.load_config(args.config, args.routine, args.place, adapter_role)
    if routine.get("engine") != roles.RECAP_ENGINE:
        raise InputError(f"config: routine {args.routine} is not a recap routine")

    def read(path, valid, expected):
        value = routine
        for name in path.split("."):
            value = value.get(name) if isinstance(value, dict) else None
        if not valid(value):
            reason = f"config: routines.{args.routine}.{path}: missing, or not {expected}"
            raise InputError(config_tree.locate(reason, config_directory(args.config)))
        return value

    top = recap_window.MAX_LOOKBACK_WORKING_DAYS
    workspace = read("workspace", lambda value: isinstance(value, str) and value != "", "a non-empty string")
    lookback = read("window.lookback_working_days", lambda value: state.is_integer(value) and 1 <= value <= top, f"an integer from 1 to {top}")
    return workspace, lookback


def check_message_inputs(args):
    given = [f"--{flag}" for flag in SUMMARY_FLAGS if getattr(args, flag) is not None]
    missing = [f"--{flag}" for flag in SUMMARY_FLAGS if getattr(args, flag) is None]
    if args.degraded is not None and given:
        raise InputError("message: --degraded excludes " + ", ".join(given))
    if args.degraded is None and missing:
        raise InputError("message: needs " + ", ".join(missing) + ", or --degraded")


def message_text(args):
    if args.degraded is not None:
        return degraded(args.degraded)
    zone = state.load_zone(args.tz)
    summary = tribe_state.load_input(args.summary, "summary", SUMMARY_SPEC)
    workspace, lookback = load_routine_settings(args)
    try:
        return render(summary, workspace, zone, lookback)
    except (OSError, OverflowError, ValueError) as error:
        raise InputError(f"summary: cannot render the message from {args.summary}: {type(error).__name__}") from error


def add_message_arguments(parser):
    parser.add_argument("--out", required=True)
    parser.add_argument("--degraded", choices=CAUSES, help="cause of a run that posts no recap")
    for flag in ("--summary", "--config", "--routine", "--tz"):
        parser.add_argument(flag)
    parser.add_argument("--place", choices=roles.PLACES)


def run_message(args):
    check_message_inputs(args)
    state.write_all([(args.out, message_text(args).encode("utf-8"))])
    return 0
