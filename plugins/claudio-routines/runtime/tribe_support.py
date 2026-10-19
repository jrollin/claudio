import contextlib
import copy
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from datetime import date, timedelta

import state
import tribe
import tribe_features
import tribe_state
from support import ts

SLUG = "tribe-digest"
LONG = "x" * (state.LABEL_CAP + 1)
TZ = "Europe/Paris"
PREVIOUS = "2026-10-15T07:45:00Z"
WRITTEN = "2026-10-15T07:53:00Z"
NOW = "2026-10-16T07:45:00Z"
PAGE_ID = "ab" * 16
CHANNEL_A = "CHAN" + "1" * 6
CHANNEL_B = "CHAN" + "2" * 6
CHANNEL_C = "CHAN" + "3" * 6
SLACK_TS = "1791990730.002679"
THREAD_TS = "1791990000.000100"
NOTION_A = "a1" * 16
NOTION_B = "b2" * 16
NOTION_C = "c3" * 16
FILTER_ID = 10321
UPDATED_MAX = "2026-10-15T07:23:59Z"
EDITED_A = "2026-10-12T14:20:59Z"
EDITED_B = "2026-10-05T13:08:27Z"


def dashed(identifier):
    return "-".join((identifier[:8], identifier[8:12], identifier[12:16], identifier[16:20], identifier[20:]))


def make_warning(**fields):
    warning = {
        "title": "Queue depth rises",
        "topic": "Capacity",
        "severity": "Medium",
        "when": "watch",
        "runway": "about two weeks",
        "status": "open",
        "confidence": "measured",
        "risk": "jobs start late",
        "impact": "reports arrive late",
        "mitigation": ["add a worker"],
        "cites": [{"source": "channels", "link": "https://example.test/c/1"}, {"feature": "metric:queue-depth", "name": "value"}],
        "metric": "queue-depth",
        "runs_under": 0,
        "since": PREVIOUS,
    }
    return {**warning, **fields}


def make_check(**fields):
    check = {"text": "Ask for the export", "topic": "Capacity", "group": "This week", "since": PREVIOUS}
    return {**check, **fields}


def make_state(at=PREVIOUS, **sections):
    document = tribe_state.initial_state("example")
    document["run"].update(
        {
            "at": at,
            "window": {"from_ts": ts(at) - 3600, "to_ts": ts(at)},
            "daily_metrics_on": "2026-10-15",
            "previous_page": {"id": PAGE_ID, "written_at": WRITTEN},
            "weekly_heading_week": "2026-W42",
            "models": {"collect": "model-a"},
            "posted": True,
        }
    )
    document.update(
        {
            "warnings": {"queue-depth": make_warning()},
            "checks": {"ask-export": make_check()},
            "cursors": {
                "observability": {"events_ts_ms": 1_000, "monitors": {"1001": "OK"}, "metrics": {"queue-depth": 5}},
                "channels": {"ts": {CHANNEL_A: SLACK_TS}},
            },
            "threads": {"channels": [{"channel": CHANNEL_A, "root_ts": THREAD_TS, "links": ["https://example.test/c/1"]}]},
            "blind_spots": [{"key": "channels", "gap": "no history", "runs": 1}],
            "retired": {"old-warning": "Old title"},
        }
    )
    document.update(sections)
    return document


def make_run_state():
    return {
        "schema": 1,
        "digest": "example",
        "run": {
            "at": PREVIOUS,
            "written_at": WRITTEN,
            "page": PAGE_ID,
            "previous": "ef" * 16,
            "window": {"from": "2026-10-14T05:55:00Z", "to": PREVIOUS, "from_ts": 1_791_957_300_000, "to_ts": 1_792_050_300_000},
            "layout_version": 1,
            "models": {"collect": "model-a", "analyse": "model-b"},
        },
        "cursors": {
            "slack": {
                CHANNEL_A: {"name": "#channel-a", "ts": SLACK_TS},
                CHANNEL_B: {"name": "#channel-b", "ts": None, "read_to": PREVIOUS},
                "threads": [f"{CHANNEL_A}/{THREAD_TS}"],
                "unreadable": [],
            },
            "jira": {"board": 70, "filter": FILTER_ID, "sprint": {"id": 1, "name": "Sprint 1"}, "updated_max": UPDATED_MAX},
            "notion": {NOTION_A: EDITED_A, NOTION_B: EDITED_B, NOTION_C: "2026-10-01T09:00:00Z"},
            "github": {"example/repo#1": {"state": "open", "sha": "0" * 7}},
            "datadog": {"dashboards_modified_at": EDITED_A, "monitors": {"1001": "OK, cannot fire", "1002": "Alert"}},
        },
        "warnings": {
            "queue-depth": {
                "title": "Queue depth rises",
                "topic": "Capacity",
                "severity": "High",
                "when": "now",
                "status": "open",
                "confidence": "measured",
                "metric": {"value": 4764, "limit": 5000, "at": PREVIOUS},
            },
            "disk-usage": {
                "title": "Disk usage grows",
                "topic": "Capacity",
                "severity": "Low",
                "when": "months",
                "status": "in progress",
                "confidence": "reported",
                "metric": None,
            },
        },
        "checks": {
            "ask-export": {"text": "Ask for the export", "topic": "Capacity", "done": False},
            "close-ticket": {"text": "Close the ticket", "topic": "Capacity", "done": True},
        },
    }


def page_markdown(run_state):
    lines = [
        'Here is the result of "fetch" for the Page as of 2026-10-15T07:51:34.487Z:',
        '<page url="https://example.test/p/1">',
        "<content>",
        "<callout>",
        "\t- Run state: the last toggle of this page, read by the next run instead of the tables.",
        "</callout>",
        "## Since last run",
        "- Nothing changed.",
        "## Warnings",
        "### Capacity",
        "- A warning row.",
    ]
    if run_state is not None:
        lines += [
            '## Run state {toggle="true"}',
            "\t- Read by the next run instead of the tables. Edit it only to fix a cursor.",
            "\t```json",
            json.dumps(run_state, indent=0),
            "\t```",
        ]
    return "\n".join(lines + ["</content>", "</page>"]) + "\n"


def make_page(run_state):
    return {"metadata": {"type": "page"}, "title": "Digest", "text": page_markdown(run_state)}


def make_config():
    transport = {"cloud": "api", "local": "api"}
    return {
        "timezone": TZ,
        "places": {
            "cloud": {"runtime_dir": "/opt/runtime", "state_dir": "/opt/state"},
            "local": {"runtime_dir": "/srv/runtime", "state_dir": "/srv/state"},
        },
        "providers": {
            "chat": {"adapter": "slack", "transport": transport},
            "issue-tracker": {"adapter": "jira", "transport": transport},
            "document-store": {"adapter": "notion", "transport": transport},
            "observability": {"adapter": "datadog", "transport": transport},
        },
        "routines": {
            SLUG: {
                "engine": "tribe",
                "page": fixture_json("page_values.json"),
                "publish": make_publish(),
                "sources": {
                    "channels": {"provider": "chat", "channels": [CHANNEL_A, CHANNEL_B]},
                    "other-channels": {"provider": "chat", "channels": [CHANNEL_C]},
                    "issues": {"provider": "issue-tracker", "filter": str(FILTER_ID)},
                    "other-issues": {"provider": "issue-tracker", "filter": "20999"},
                    "pages": {"provider": "document-store", "pages": [dashed(NOTION_A), NOTION_B]},
                    "monitors": {"provider": "observability", "kind": "monitors", "scope_filter": ""},
                },
            }
        },
    }


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = tribe.main(list(argv))
        except SystemExit as error:
            code = error.code
    return code, out.getvalue(), err.getvalue()


class FileCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def path(self, name):
        return os.path.join(self.dir, name)

    def write(self, name, document):
        with open(self.path(name), "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        return self.path(name)

    def read(self, name):
        with open(self.path(name), encoding="utf-8") as handle:
            return json.load(handle)

    def assert_canonical(self, name):
        with open(self.path(name), "rb") as handle:
            raw = handle.read()
        self.assertEqual(raw, state.dump(json.loads(raw)))


HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures", "tribe")
CONNECTOR = "docs-connector"
PARENT = "cd" * 16
NEW_PAGE = "ef" * 16
RUN_WEEK = "2026-W11"
CREATE = {
    "tool": "page_create",
    "arguments": {"parent": "{{parent}}", "title": "{{title}}", "content": "{{content}}", "day": "{{date}}", "background": True},
}
POLL = {"tool": "task_poll", "arguments": {"task": "{{task}}"}}
HEADING = {"tool": "page_append", "arguments": {"parent": "{{parent}}", "content": "## {{week}} from {{week_start}}"}}
RESULTS = {
    "task": "task.id",
    "status": "task.status",
    "page": "task.page.id",
    "heading": "block.id",
    "done": ["completed"],
    "failed": ["failed", "cancelled"],
}
TO_TS = ts(NOW)
FROM_TS = ts(PREVIOUS)
WINDOW = {"from_ts": FROM_TS, "to_ts": TO_TS, "retry_known_gaps": False}
ZONE = state.load_zone(TZ)
TO_DAY = date(2026, 10, 16)
TRANSPORT = {"cloud": "api", "local": "api"}
LINK_ROOT = "https://example.test/c/1"
LINK_REPLY = "https://example.test/c/2"
LINK_ISSUE = "https://example.test/i/ABC-1"
LINK_PAGE = "https://example.test/p/2"
PAGE_TWO = "cd" * 16
PACK_ENTRY = {
    "key": "queue-depth",
    "source": "metrics",
    "title": "Queue depth",
    "link": "https://example.test/m/1",
    "rule": "Warn when the queue grows for a month.",
    "schedule": "every_run",
    "query": "avg:queue.depth{*}",
    "read": "scalar",
    "aggregator": "avg",
    "trend_days": 30,
}
TOKENS = {
    "NOTION_A_DASHED": dashed(NOTION_A),
    "NOTION_A": NOTION_A,
    "NOTION_B": NOTION_B,
    "NOTION_C": NOTION_C,
    "CHANNEL_A": CHANNEL_A,
    "CHANNEL_B": CHANNEL_B,
    "CHANNEL_C": CHANNEL_C,
    "PAGE_ID": PAGE_ID,
    "PAGE_TWO": PAGE_TWO,
    "NEW_PAGE": NEW_PAGE,
}


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        text = handle.read()
    for token, value in TOKENS.items():
        text = text.replace(f"@{token}@", value)
    return text


def fixture_json(name):
    return json.loads(fixture(name))


def make_publish():
    return {
        "provider": "document-store",
        "parent": PARENT,
        "create": copy.deepcopy(CREATE),
        "poll": copy.deepcopy(POLL),
        "heading": copy.deepcopy(HEADING),
        "results": copy.deepcopy(RESULTS),
    }


def publish_config():
    config = make_config()
    for provider in config["providers"].values():
        provider["api"] = {"base_url": "https://api.example.com", "credentials": {"token": "EXAMPLE_TOKEN"}}
    config["providers"]["document-store"]["mcp"] = {"connectors": {"cloud": CONNECTOR, "local": CONNECTOR}}
    return config


def tick(page, text):
    ticked, count = re.subn(
        rf'- \[ \] (<span color="gray_bg">[^<]*</span> {re.escape(text)} )', r"- [x] \1", page, count=1
    )
    assert count == 1, f"no open to-do reads {text!r}"
    return ticked


class PublishCase(FileCase):
    def setUp(self):
        super().setUp()
        self.config = self.write("config.json", publish_config())
        self.summary_doc = fixture_json("page_summary.json")
        self.summary = self.write("summary.json", self.summary_doc)
        self.use_state(weekly_heading_week=RUN_WEEK)
        self.responses = self.path("responses")
        os.mkdir(self.responses)

    def use_config(self, change):
        document = publish_config()
        change(document["routines"][SLUG])
        self.config = self.write("config.json", document)

    def use_summary(self, **fields):
        self.summary = self.write("summary.json", {**self.summary_doc, **fields})

    def due_heading(self):
        self.use_state(weekly_heading_week="2026-W10")

    def stored(self, **run):
        document = make_state()
        document["run"].update(run)
        return document

    def use_state(self, **run):
        self.state = self.write("state.json", self.stored(**run))

    def save(self, number, text):
        with open(os.path.join(self.responses, f"publish-{number}.txt"), "w", encoding="utf-8") as handle:
            handle.write(text)

    def render(self):
        code, _, err = run_cli(
            "render", "--config", self.config, "--routine", SLUG, "--place", "cloud", "--summary", self.summary, "--out", self.path("page.md")
        )
        return code, err

    def page(self):
        with open(self.path("page.md"), encoding="utf-8") as handle:
            return handle.read()

    def plan(self):
        if not os.path.exists(self.path("page.md")):
            self.assertEqual(self.render(), (0, ""))
        code, _, err = run_cli(
            "publish-plan", "--config", self.config, "--routine", SLUG, "--place", "cloud", "--summary", self.summary,
            "--state", self.state, "--page", self.path("page.md"), "--responses", self.responses, "--out", self.path("plan.json"),
        )
        return code, err

    def planned(self):
        self.assertEqual(self.plan(), (0, ""))
        return self.read("plan.json")

    def parse(self, now=NOW):
        code, _, err = run_cli(
            "publish-parse", "--config", self.config, "--routine", SLUG, "--place", "cloud", "--summary", self.summary,
            "--state", self.state, "--responses", self.responses, "--now", now, "--out", self.path("next.json"),
            "--result", self.path("result.json"),
        )
        return code, err

    def parsed(self):
        self.assertEqual(self.parse(), (0, ""))
        return self.read("next.json"), self.read("result.json")

    def raw(self, name):
        with open(self.path(name), "rb") as handle:
            return handle.read()

    def result(self, **fields):
        document = {"status": "created", "page": NEW_PAGE, "reason": None, "heading": "written", "heading_reason": None}
        return self.write("result.json", {**document, **fields})


def source(role, **options):
    return {"provider": role, "transport": TRANSPORT, "role": role, **options}


def collection(name, records, cursor=None, read=True, reason=None, entries=None):
    return {
        "schema": 1,
        "source": name,
        "role": SOURCES[name]["role"],
        "provider": SOURCES[name]["provider"],
        "transport": "api",
        "place": "cloud",
        "window": {"from_ts": FROM_TS, "to_ts": TO_TS},
        "read": read,
        "reason": reason,
        "cursor": cursor,
        "records": records,
        "entries": entries or {},
    }


def unread(name, records, reason="provider unreachable"):
    return collection(name, records, read=False, reason=reason)


def message(ts_value, text, thread=None, author="usr_aaa01", link=LINK_ROOT):
    return {"channel": CHANNEL_A, "ts": ts_value, "thread_ts": thread, "author": author, "text": text, "link": link}


def issue(key="ABC-1", **fields):
    record = {
        "key": key,
        "title": "Upgrade the queue",
        "type": "Task",
        "status": "In Progress",
        "priority": "High",
        "created": "2026-10-01T08:00:00Z",
        "updated": "2026-10-15T09:00:00Z",
        "link": LINK_ISSUE,
        "in_open_sprint": True,
    }
    return {**record, **fields}


def block(kind, text, checked=None, rows=None):
    return {"type": kind, "text": text, "rows": rows, "checked": checked}


def page(page_id, title, blocks, last_edited="2026-10-15T07:51:34.487Z", link=LINK_PAGE):
    return {"id": page_id, "title": title, "last_edited": last_edited, "link": link, "blocks": blocks}


def trend_points(first, second, span=30):
    start = TO_DAY - timedelta(days=span - 1)
    return [{"day": (start + timedelta(days=index)).isoformat(), "value": first if index < span / 2 else second} for index in range(span)]


def metric_record(value=12, **extra):
    return {"key": "queue-depth", "value": value, "hourly": [], "groups": [], **extra}


def collections_for(**overrides):
    chat = {"messages": [message("1791990730.002679", "Queue is slow <@usr_aaa01>"), message("1791990731.000100", "Same here", thread="1791990730.002679", author="usr_bbb02", link=LINK_REPLY)]}
    parts = {
        "channels": collection("channels", chat, cursor={"ts": {CHANNEL_A: "1791990731.000100"}}),
        "issues": collection("issues", {"issues": [issue()]}, cursor={"updated": "2026-10-15T09:00:00Z"}),
        "pages": collection("pages", {"pages": [page(PAGE_TWO, "Runbook", [block("heading", "Queue"), block("paragraph", "Drain first"), block("table", "", rows=[["a", "b"]]), block("other", "")])]}, cursor={"pages": {PAGE_TWO: "2026-10-15T07:51:34.487Z"}}),
        "previous-digest": collection("previous-digest", {"pages": []}),
        "monitors": collection(
            "monitors",
            {
                "monitors": [],
                "transitions": [{"monitor": "1001", "count": 1, "first_ts_ms": (TO_TS - 1800) * 1000, "last_ts_ms": (TO_TS - 1800) * 1000}],
                "discovered": [{"id": "1001", "name": "Queue alert", "state": "Alert", "priority": 2, "link": "https://example.test/mon/1001"}],
                "discovery": {"read": True, "reason": None},
            },
            cursor={"events_ts_ms": (TO_TS - 1800) * 1000, "monitors": {"1001": "Alert"}},
        ),
        "metrics": collection(
            "metrics",
            {"metrics": [metric_record(trend=trend_points(10, 20))]},
            cursor={"metrics": {"queue-depth": 12}},
            entries={"queue-depth": {"status": "ok", "reason": None}},
        ),
    }
    parts.update(overrides)
    return parts


def compute(collections=None, stored=None, routine=None, sources=None):
    return tribe_features.compute(
        routine or ROUTINE, sources or SOURCES, collections or collections_for(), stored or make_state(), WINDOW, ZONE
    )


SOURCES = {
    "channels": source("chat", channels=[CHANNEL_A]),
    "issues": source("issue_tracker", filter="10321"),
    "pages": source("document_store", pages=[PAGE_TWO]),
    "previous-digest": source("document_store", page_from_state="previous_page"),
    "monitors": source("observability", kind="monitors", scope_filter=""),
    "metrics": source("observability", kind="metrics", scope_filter=""),


}

ROUTINE = {"engine": "tribe", "query_pack": [PACK_ENTRY], "rules": ["A warning needs two weeks of growth."], "models": {"judge": "model-a"}}
