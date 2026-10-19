import copy
import json
import os
import re
from collections import namedtuple
from datetime import timedelta

import collect
import evaluate
import roles
import state
import tribe_page
import tribe_state
from config import accept_any, adapter_role
from providers._errors import SourceUnreadable
from state import InputError, Nullable, Rejected

POLL_CAP = 20
CALL_NAME = re.compile(r"publish-([1-9][0-9]*)")
TASK_ID = re.compile(r"[A-Za-z0-9_.:-]{1,200}")
DUMMY_TASK = "task"
DEFAULT_WEEK_START = "%Y-%m-%d"
STATUSES = ("created", "failed", "report-only")
HEADINGS = ("written", "failed", "skipped")
FAILURE_CAP = 400

SUMMARY_SPEC = {"run_at": tribe_state.UTC_TIME, "report_only": state.BOOLEAN}
RESULT_SPEC = {
    "status": tribe_state.one_of(STATUSES),
    "page": Nullable(tribe_state.PAGE),
    "reason": Nullable(state.TEXT),
    "heading": tribe_state.one_of(HEADINGS),
    "heading_reason": Nullable(state.TEXT),
}

Progress = namedtuple("Progress", "pending task page failure heading heading_reason", defaults=(None,) * 6)
Target = namedtuple("Target", "spec connector zone title")


def clean(value, cap=state.LABEL_CAP):
    return state.clean_text(value, cap)


def load_config(args):
    config, routine, _ = evaluate.load_config(args.config, args.routine, args.place, adapter_role)
    if routine.get("engine") != roles.TRIBE_ENGINE:
        raise InputError(f"config: routine {args.routine} is not a tribe routine")
    return config, routine


def present(routine, slug, name):
    if name not in routine:
        raise InputError(f"config: routines.{slug}.{name}: missing")
    return routine[name]


def load_page(args):
    config, routine = load_config(args)
    return present(routine, args.routine, "page"), evaluate.config_zone(config)


def run_values(run_at, zone, week_start_format=DEFAULT_WEEK_START):
    local = state.parse_time(run_at).astimezone(zone)
    return {
        "date": local.date().isoformat(),
        "week": tribe_state.iso_week(local),
        "week_start": (local.date() - timedelta(days=local.weekday())).strftime(week_start_format),
    }


def rendered_title(page, run_at, zone, slug):
    return fill(page["title"], {"date": run_values(run_at, zone)["date"]}, f"routines.{slug}.page.title")


def step_into(document, key):
    if isinstance(document, dict):
        return document.get(key)
    if isinstance(document, list) and key.isdigit() and int(key) < len(document):
        return document[int(key)]
    return None


def at_path(document, path):
    for key in path.split("."):
        document = step_into(document, key)
        if document is None:
            return None
    return document


def publish_target(args):
    config, routine = load_config(args)
    spec = present(routine, args.routine, "publish")
    connector = at_path(config, f"providers.{spec['provider']}.mcp.connectors.{args.place}")
    if not isinstance(connector, str) or not connector:
        raise InputError(
            f"config: routines.{args.routine}.publish.provider: provider {spec['provider']} has no mcp connector for place {args.place}"
        )
    page, zone = load_page(args)
    return Target(spec, connector, zone, page["title"])


def fill(template, values, path):
    if isinstance(template, str):
        return roles.PLACEHOLDER.sub(lambda found: placeholder(found.group(1), values, path), template)
    if isinstance(template, list):
        return [fill(item, values, f"{path}[{index}]") for index, item in enumerate(template)]
    if isinstance(template, dict):
        return {key: fill(item, values, f"{path}.{key}") for key, item in template.items()}
    return template


def placeholder(name, values, path):
    if name not in values:
        raise InputError("config: " + path + ": unknown placeholder {{" + name + "}}")
    return values[name]


def filled_arguments(spec, slug, call, values):
    return fill(spec[call]["arguments"], values, f"routines.{slug}.publish.{call}.arguments")


def check_templates(spec, slug, values):
    for call, names in roles.PUBLISH_VALUES.items():
        filled_arguments(spec, slug, call, {name: values.get(name, DUMMY_TASK) for name in names})


def checked_page(page):
    failures = tribe_page.check(page)
    if failures:
        raise Rejected("page: structure check failed: " + clean("; ".join(failures), FAILURE_CAP))
    return page


def run_render(args):
    values, zone = load_page(args)
    summary = state.load(args.summary, "summary", accept_any)
    try:
        page = tribe_page.render(summary, values, zone)
    except (AttributeError, KeyError, OSError, OverflowError, TypeError, ValueError) as error:
        raise InputError(f"summary: cannot render {args.summary}: {type(error).__name__} {clean(str(error), 200)}") from error
    state.write_all([(args.out, checked_page(page).encode("utf-8"))])
    return 0


def read_page(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError) as error:
        raise InputError(f"page: cannot read {path}: {getattr(error, 'strerror', None) or type(error).__name__}") from error


def load_responses(directory):
    found = {}
    for name in collect.response_ids(directory):
        match = CALL_NAME.fullmatch(name)
        if match is None or int(match.group(1)) > POLL_CAP + 2:
            continue
        try:
            found[int(match.group(1))] = collect.read_response(directory, name)
        except SourceUnreadable:
            found[int(match.group(1))] = ""
    return found


def call_id(number):
    return f"publish-{number}"


def result_text(responses, number, path):
    try:
        document = json.loads(responses[number])
    except (ValueError, RecursionError):
        return None
    value = at_path(document, path)
    return value if isinstance(value, str) and value else None


def heading_progress(results, responses):
    if 1 not in responses:
        return Progress(pending=(1, "heading"))
    if result_text(responses, 1, results["heading"]) is not None:
        return Progress(heading="written")
    return Progress(heading="failed", heading_reason=f"{call_id(1)}: no {results['heading']} in the result")


def finished_progress(results, responses, number, base):
    page = result_text(responses, number, results["page"])
    key = None if page is None or roles.PAGE_ID.fullmatch(page) is None else tribe_state.page_key(page)
    if not key:
        return base._replace(failure=f"{call_id(number)}: no page id at {results['page']} in the result")
    return base._replace(page=key)


def create_progress(spec, responses, number, base):
    results = spec["results"]
    if number not in responses:
        return base._replace(pending=(number, "create"))
    task = result_text(responses, number, results["task"])
    if task is None or TASK_ID.fullmatch(task) is None:
        return base._replace(failure=f"{call_id(number)}: no task id at {results['task']} in the result")
    for poll in range(number + 1, number + POLL_CAP + 1):
        if poll not in responses:
            return base._replace(pending=(poll, "poll"), task=task)
        status = result_text(responses, poll, results["status"])
        if status in results["done"]:
            return finished_progress(results, responses, poll, base)
        if status is None:
            return base._replace(failure=f"{call_id(poll)}: task {task} has no status at {results['status']}")
        if status in results["failed"]:
            return base._replace(failure=f"{call_id(poll)}: task {task} {status}")
    return base._replace(failure=f"task {task} not ended after {POLL_CAP} polls")


def walk(spec, responses, week_due):
    if not week_due:
        return create_progress(spec, responses, 1, Progress(heading="skipped"))
    heading = heading_progress(spec["results"], responses)
    if heading.pending is not None:
        return heading
    return create_progress(spec, responses, 2, heading)


def settled(progress):
    if progress.pending is None:
        return progress
    number, _ = progress.pending
    reason = f"{call_id(number)}: no result saved"
    if progress.heading is None:
        return Progress(failure=reason)
    return progress._replace(pending=None, failure=reason)


def planned_call(spec, connector, slug, progress, values):
    number, call = progress.pending
    if call == "poll":
        values = {**values, "task": progress.task}
    return {"id": call_id(number), "connector": connector, "tool": spec[call]["tool"], "arguments": filled_arguments(spec, slug, call, values)}


def call_values(target, summary, slug, content=""):
    spec = target.spec
    run = run_values(summary["run_at"], target.zone, spec.get("week_start_format", DEFAULT_WEEK_START))
    title = fill(target.title, {"date": run["date"]}, f"routines.{slug}.page.title")
    return {"parent": spec["parent"], "title": title, "content": content, **run}


def run_publish_plan(args):
    target = publish_target(args)
    summary = tribe_state.load_input(args.summary, "summary", SUMMARY_SPEC)
    document = tribe_state.load(args.state)
    values = call_values(target, summary, args.routine)
    check_templates(target.spec, args.routine, values)
    step = {"done": True, "partial": None, "calls": []}
    if not summary["report_only"]:
        values["content"] = checked_page(read_page(args.page))
        os.makedirs(args.responses, exist_ok=True)
        progress = walk(target.spec, load_responses(args.responses), document["run"]["weekly_heading_week"] != values["week"])
        if progress.pending is not None:
            step = {"done": False, "partial": None, "calls": [planned_call(target.spec, target.connector, args.routine, progress, values)]}
        else:
            step["partial"] = progress.failure
    state.write_all([(args.out, state.dump(step))])
    return 0


def report_only_result():
    return {"status": "report-only", "page": None, "reason": None, "heading": "skipped", "heading_reason": None}


def result_of(progress):
    heading = {"heading": progress.heading or "skipped", "heading_reason": progress.heading_reason}
    if progress.failure is not None:
        return {"status": "failed", "page": None, "reason": progress.failure, **heading}
    return {"status": "created", "page": progress.page, "reason": None, **heading}


def next_state(document, progress, week, written_at):
    following = copy.deepcopy(document)
    following["run"]["previous_page"] = {"id": progress.page, "written_at": written_at}
    if progress.heading == "written":
        following["run"]["weekly_heading_week"] = week
    tribe_state.check_state(following)
    return state.dump(following)


def saved_responses(directory):
    return load_responses(directory) if os.path.isdir(directory) else {}


def run_publish_parse(args):
    now = state.load_time(args.now, "--now")
    target = publish_target(args)
    summary = tribe_state.load_input(args.summary, "summary", SUMMARY_SPEC)
    raw, document = state.load_raw(args.state, "state", tribe_state.check_state)
    values = call_values(target, summary, args.routine)
    check_templates(target.spec, args.routine, values)
    if summary["report_only"]:
        result, data = report_only_result(), raw
    else:
        progress = settled(walk(target.spec, saved_responses(args.responses), document["run"]["weekly_heading_week"] != values["week"]))
        result = result_of(progress)
        written_at = state.utc_text(int(now.timestamp()))
        data = raw if progress.failure is not None else next_state(document, progress, values["week"], written_at)
    state.write_all([(args.out, data), (args.result, state.dump(result))])
    return 0


def load_result(path):
    result = tribe_state.load_input(path, "result", RESULT_SPEC)
    if result["status"] == "created" and result["page"] is None:
        raise InputError(f"result: status created without a page in {path}")
    return result
