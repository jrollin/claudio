import contextlib
import copy
import io
import os
import re
import unittest

import weekly
from support import ts
from test_recap_state import FileCase, make_unit

SLUG = "weekly-status"
TZ = "Europe/Paris"
NOW = "2026-10-16T14:00:00Z"
WEEK_START = "2026-10-11T22:00:00Z"
OWNER = "U" + "1" * 6
PEER = "U" + "2" * 6
NAMES = {OWNER: "Owner Name", PEER: "Peer Name"}
CHAN = "C" + "1" * 6
EXCLUDED = "C" + "3" * 6
DM = "D" + "1" * 6
HOST = "chat.example.test"
ROOT = "1791990000.000100"
RECAP_FRESH = {"first_seen": "2026-10-13T08:00:00Z", "last_ts": f"{ts('2026-10-14T09:00:00Z')}.000200"}
RECAP_STALE = {"first_seen": "2026-10-01T08:00:00Z", "last_ts": f"{ts('2026-10-02T09:00:00Z')}.000200"}
EMPTY_RECORDS = {
    "issue_tracker": {"issues": []},
    "code_host": {"pull_requests": [], "issues": []},
    "chat": {"messages": [], "units": []},
    "document_store": {"pages": []},
}
CURSORS = {"issue_tracker": {"updated": None}, "code_host": {"updated_at": None}, "chat": {"ts": {}}, "document_store": {"pages": {}}}
SOURCE_ROLES = {"issues": "issue_tracker", "code": "code_host", "chat": "chat", "docs": "document_store"}


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = weekly.main(list(argv))
        except SystemExit as error:
            code = error.code
    return code, out.getvalue(), err.getvalue()


def stamp(text, fraction=100):
    return f"{ts(text)}.{fraction:06d}"


def make_config(**changes):
    api = {"cloud": "api", "local": "api"}
    routine = {
        "engine": "weekly",
        "owner": OWNER,
        "workspace": HOST,
        "recap": "chat-recap",
        "exclude": {"channels": [EXCLUDED]},
        "values": {"digest": {"name": "Weekly status", "slug": SLUG}},
        "sources": {
            "issues": {"provider": "tracker", "transport": api, "jql": "assignee = currentUser()"},
            "code": {"provider": "code", "transport": api, "searches": ["is:pr org:example-org author:dev"]},
            "chat": {"provider": "chat", "transport": api, "owner": OWNER, "searches": [{"name": "dms", "filters": "is:dm", "since": "window"}]},
            "docs": {"provider": "docs", "transport": api, "edited_by": "user-ab12"},
        },
    }
    routine.update(changes)
    credentials = {"token": "EXAMPLE_TOKEN"}
    return {
        "timezone": TZ,
        "places": {"cloud": {"runtime_dir": "/opt/runtime", "state_dir": "/opt/state"}, "local": {"runtime_dir": "/srv/runtime", "state_dir": "/srv/state"}},
        "providers": {
            "tracker": {"adapter": "jira", "api": {"base_url": "https://tracker.example.test", "credentials": credentials}},
            "code": {"adapter": "github", "api": {"base_url": "https://code.example.test", "credentials": credentials}},
            "chat": {"adapter": "slack", "api": {"base_url": "https://" + HOST, "credentials": credentials}},
            "docs": {"adapter": "notion", "api": {"base_url": "https://docs.example.test/v1", "credentials": credentials}},
        },
        "routines": {SLUG: routine},
    }


def make_window(**fields):
    return {"from_ts": ts(WEEK_START), "to_ts": ts(NOW), "week_start": "2026-10-12", "report_only": False, **fields}


def make_collection(name, window, records=None, read=True, reason=None):
    role = SOURCE_ROLES[name]
    return {
        "schema": 1,
        "source": name,
        "role": role,
        "provider": name,
        "transport": "api",
        "place": "cloud",
        "window": {"from_ts": window["from_ts"], "to_ts": window["to_ts"]},
        "read": read,
        "reason": reason,
        "cursor": CURSORS[role] if read else None,
        "records": {**EMPTY_RECORDS[role], **(records or {})} if read else EMPTY_RECORDS[role],
        "entries": {},
    }


def make_issue(key="PROJ-12", updated="2026-10-14T09:30:00Z", **fields):
    issue = {
        "key": key,
        "title": "Checkout fails",
        "type": "Bug",
        "status": "In Progress",
        "priority": None,
        "created": "2026-09-01T08:00:00Z",
        "updated": updated,
        "link": f"https://tracker.example.test/browse/{key}",
        "in_open_sprint": False,
    }
    return {**issue, **fields}


def make_request(number=7, updated_at="2026-10-14T09:30:00Z", **fields):
    request = {
        "repo": "example-org/service",
        "number": number,
        "title": "Fix the export",
        "author": "dev",
        "state": "open",
        "draft": False,
        "created_at": "2026-09-01T08:00:00Z",
        "updated_at": updated_at,
        "merged_at": None,
        "link": f"https://code.example.test/example-org/service/pull/{number}",
    }
    return {**request, **fields}


def make_activity(at, number=7, author="reviewer", text="Looks good", **fields):
    entry = {"repo": "example-org/service", "number": number, "kind": "comment", "author": author, "at": at, "state": None, "text": text}
    return {**entry, **fields}


def make_page(page_id="page-ab12", last_edited="2026-10-15T08:00:00Z", texts=("Plan", "Ship it")):
    blocks = [{"type": "paragraph", "text": text, "rows": None, "checked": None} for text in texts]
    return {"id": page_id, "title": "Launch plan", "last_edited": last_edited, "link": f"https://docs.example.test/{page_id}", "blocks": blocks}


def make_message(user, at, text="hello", root=None):
    return {"user": user, "name": NAMES[user], "bot": False, "ts": at, "root_ts": root, "mentions": [], "group_mentions": [], "text": text}


def make_chat_unit(channel, name, *messages):
    return {"channel": channel, "name": name, "participants": [], "messages": list(messages)}


def make_record(run_at, new=(), resolved=(), handled=()):
    return {"run_at": run_at, "new": list(new), "resolved": list(resolved), "handled": list(handled)}


def make_stored(**units):
    return {
        "schema": 1,
        "digest": "chat-recap",
        "run": {"at": "2026-10-15T07:45:00Z", "previous_at": None, "window": None},
        "units": units,
        "blind_spots": [],
    }


THREAD_KEY = f"thread-{CHAN}-{ROOT}"
DM_KEY = f"dm-{DM}"

ISSUE_KEY = "issue:PROJ-12"
PR_KEY = "pr:example-org/service#7"
THREAD_ITEM = f"chat:{THREAD_KEY}"
DM_ITEM = f"chat:{DM_KEY}"
PAGE_KEY = "page:page-ab12"
OWNER_NAME = "Ada Lovelace"


def make_item_document(source, role, kind, title, link):
    return {"source": source, "role": role, "kind": kind, "title": title, "status": None, "link": link, "when": "2026-10-14T09:30:00Z", "people": [], "excerpts": []}


def make_features_items():
    return {
        ISSUE_KEY: make_item_document("issues", "issue_tracker", "issue", "Checkout fails", "https://tracker.example.test/browse/PROJ-12"),
        PR_KEY: make_item_document("code", "code_host", "pull_request", "Fix the export", "https://code.example.test/example-org/service/pull/7"),
        THREAD_ITEM: make_item_document("recap", "chat", "thread", "Review the rollout plan", f"https://{HOST}/archives/{CHAN}/p1791990000000100"),
        DM_ITEM: make_item_document("recap", "chat", "dm", "Question about the launch", f"https://{HOST}/archives/{DM}/p1791990000000200"),
        PAGE_KEY: make_item_document("docs", "document_store", "page", "Launch plan for the autumn release of the export", "https://docs.example.test/page-ab12"),
    }


def make_source_rows(**changes):
    rows = {
        "chat": {"source": "chat", "role": "chat", "read": True, "reason": None},
        "code": {"source": "code", "role": "code_host", "read": True, "reason": None},
        "docs": {"source": "docs", "role": "document_store", "read": True, "reason": None},
        "issues": {"source": "issues", "role": "issue_tracker", "read": True, "reason": None},
    }
    for name, fields in changes.items():
        rows[name] = {**rows[name], **fields}
    return list(rows.values())


def make_features_document(items=None, sources=None):
    return {
        "schema": 1,
        "window": make_window(),
        "week_start": "2026-10-12",
        "items": make_features_items() if items is None else items,
        "recap_counts": {"new": 2, "resolved": 1, "handled": 3},
        "sources": make_source_rows() if sources is None else sources,
    }


def make_judgment():
    return {
        "schema": 1,
        "accomplishments": [{"text": "Fixed the checkout failure and the export.", "cites": [ISSUE_KEY, PR_KEY]}],
        "decisions": [{"text": "Ship the export behind a flag.", "cites": [PAGE_KEY]}],
        "open": [{"text": "Review the rollout plan.", "owner": OWNER_NAME, "cites": [THREAD_ITEM]}],
    }


def make_summary(judgment=None, features=None):
    features = features or make_features_document()
    return {**{name: features[name] for name in ("window", "week_start", "recap_counts", "sources")}, **(judgment or make_judgment())}


def words(count):
    return " ".join(["w"] * count)


class WeeklyCase(FileCase):
    def run_weekly(self, *argv):
        return run_cli(*argv)

    def window_of(self, now=NOW, *flags, document=None, tz=TZ):
        state_path = self.write("state.json", document or {"schema": "weekly-1", "digest": SLUG, "last_run": None})
        return self.run_weekly("window", "--state", state_path, "--now", now, "--tz", tz, "--out", self.path("window.json"), *flags)

    def computed_window(self, now=NOW, *flags):
        code, _, err = self.window_of(now, *flags)
        self.assertEqual((code, err), (0, ""))
        return self.read("window.json")


class InitTest(WeeklyCase):
    def test_init_writes_the_empty_state(self):
        code, _, err = self.run_weekly("init", "--digest", SLUG, "--out", self.path("state.json"))

        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.read("state.json"), {"schema": "weekly-1", "digest": SLUG, "last_run": None})
        self.assert_canonical("state.json")


class WindowTest(WeeklyCase):
    def test_starts_on_monday_midnight_of_the_zone(self):
        window = self.computed_window(NOW)

        self.assertEqual(window, {"from_ts": ts(WEEK_START), "to_ts": ts(NOW), "week_start": "2026-10-12", "report_only": False})
        self.assert_canonical("window.json")

    def test_a_sunday_run_stays_in_the_week_it_ends(self):
        window = self.computed_window("2026-10-18T21:30:00Z")

        self.assertEqual((window["from_ts"], window["week_start"]), (ts(WEEK_START), "2026-10-12"))

    def test_a_run_after_midnight_in_the_zone_starts_the_next_week(self):
        window = self.computed_window("2026-10-18T22:30:00Z")

        self.assertEqual((window["from_ts"], window["week_start"]), (ts("2026-10-18T22:00:00Z"), "2026-10-19"))

    def test_a_week_ending_a_summer_time_keeps_its_monday_midnight(self):
        window = self.computed_window("2026-10-25T20:00:00Z")

        self.assertEqual((window["from_ts"], window["week_start"]), (ts("2026-10-18T22:00:00Z"), "2026-10-19"))

    def test_a_week_starting_a_summer_time_keeps_its_monday_midnight(self):
        window = self.computed_window("2026-03-29T20:00:00Z")

        self.assertEqual((window["from_ts"], window["week_start"]), (ts("2026-03-22T23:00:00Z"), "2026-03-23"))

    def test_report_only_marks_the_window_and_keeps_its_bounds(self):
        window = self.computed_window(NOW, "--report-only")

        self.assertEqual(window, {**self.computed_window(NOW), "report_only": True})

    def test_refuses_a_time_that_is_not_utc(self):
        for now in ("2026-10-16T16:00:00+02:00", "2026-10-16T14:00:00", "yesterday"):
            with self.subTest(now=now):
                code, _, err = self.window_of(now)

                self.assertEqual(code, 2)
                self.assertIn("--now", err)

    def test_refuses_an_unknown_zone(self):
        code, _, err = self.window_of(NOW, tz="Nowhere/Land")

        self.assertEqual(code, 2)
        self.assertIn("--tz", err)

    def test_rejects_a_state_holding_a_text_field_naming_its_key_path(self):
        document = {"schema": "weekly-1", "digest": SLUG, "last_run": {"run_at": NOW, "week_start": "2026-10-12", "text": "done"}}

        code, _, err = self.window_of(NOW, document=document)

        self.assertEqual(code, 3)
        self.assertIn("last_run.text", err)

    def test_rejects_a_state_of_another_schema(self):
        code, _, err = self.window_of(NOW, document={"schema": "recap-1", "digest": SLUG, "last_run": None})

        self.assertEqual(code, 3)
        self.assertIn("schema weekly-1 at schema", err)

    def test_rejects_a_last_run_with_a_bad_week_start(self):
        document = {"schema": "weekly-1", "digest": SLUG, "last_run": {"run_at": NOW, "week_start": "2026-13-40"}}

        code, _, err = self.window_of(NOW, document=document)

        self.assertEqual(code, 3)
        self.assertIn("last_run.week_start", err)

    def test_accepts_a_state_with_a_last_run(self):
        document = {"schema": "weekly-1", "digest": SLUG, "last_run": {"run_at": NOW, "week_start": "2026-10-12"}}

        code, _, err = self.window_of(NOW, document=document)

        self.assertEqual((code, err), (0, ""))


class FeaturesCase(WeeklyCase):
    def run_features(self, collections=None, window=None, config=None, recap=None, records=None):
        window = window or make_window()
        self.write("config.json", config or make_config())
        self.write("window.json", window)
        os.makedirs(self.path("collections"), exist_ok=True)
        for name, document in (collections or {}).items():
            self.write(f"collections/{name}.json", document)
        flags = []
        if recap is not None:
            os.makedirs(self.path("recap/runs"), exist_ok=True)
            self.write("recap/state.json", recap)
            for index, record in enumerate(records or []):
                self.write(f"recap/runs/{index}.json", record)
            flags = ["--recap", self.path("recap")]
        return self.run_weekly(
            "features", "--config", self.path("config.json"), "--routine", SLUG, "--window", self.path("window.json"),
            "--collections", self.path("collections"), "--out", self.path("features.json"), *flags,
        )

    def computed(self, **options):
        code, _, err = self.run_features(**options)
        self.assertEqual((code, err), (0, ""))
        return self.read("features.json")

    def items(self, **options):
        return self.computed(**options)["items"]

    def collection(self, name, **records):
        return {name: make_collection(name, make_window(), records)}


class IssueFeaturesTest(FeaturesCase):
    def test_an_issue_updated_in_the_week_is_an_item(self):
        items = self.items(collections=self.collection("issues", issues=[make_issue()]))

        self.assertEqual(
            items["issue:PROJ-12"],
            {
                "source": "issues",
                "role": "issue_tracker",
                "kind": "issue",
                "title": "Checkout fails",
                "status": "In Progress",
                "link": "https://tracker.example.test/browse/PROJ-12",
                "when": "2026-10-14T09:30:00Z",
                "people": [],
                "excerpts": [],
                "channel_name": None,
            },
        )

    def test_an_issue_updated_before_the_week_makes_no_item(self):
        self.assertEqual(self.items(collections=self.collection("issues", issues=[make_issue(updated="2026-10-05T09:30:00Z")])), {})

    def test_an_issue_updated_after_the_window_makes_no_item(self):
        self.assertEqual(self.items(collections=self.collection("issues", issues=[make_issue(updated="2026-10-16T14:00:01Z")])), {})

    def test_features_carry_the_window_and_the_week_start(self):
        document = self.computed(collections=self.collection("issues", issues=[make_issue()]))

        self.assertEqual((document["schema"], document["window"], document["week_start"]), (1, make_window(), "2026-10-12"))
        self.assert_canonical("features.json")


class PullRequestFeaturesTest(FeaturesCase):
    def pull_request(self, *activity, **request):
        return self.items(collections=self.collection("code", pull_requests=[make_request(**request)], activity=list(activity)))["pr:example-org/service#7"]

    def test_a_pull_request_with_activity_is_an_item_with_the_activity_as_excerpts(self):
        item = self.pull_request(
            make_activity("2026-10-13T10:00:00Z", author="alice", text="First comment"),
            make_activity("2026-10-15T10:00:00Z", author="bob", text="Approved"),
        )

        self.assertEqual(
            {key: item[key] for key in ("source", "role", "kind", "title", "status", "link", "when", "people")},
            {
                "source": "code",
                "role": "code_host",
                "kind": "pull_request",
                "title": "Fix the export",
                "status": "open",
                "link": "https://code.example.test/example-org/service/pull/7",
                "when": "2026-10-15T10:00:00Z",
                "people": ["alice", "bob"],
            },
        )
        self.assertEqual(
            item["excerpts"],
            [
                {"by": "bob", "at": "2026-10-15T10:00:00Z", "text": "Approved"},
                {"by": "alice", "at": "2026-10-13T10:00:00Z", "text": "First comment"},
            ],
        )

    def test_an_excerpt_is_cut_to_500_characters(self):
        item = self.pull_request(make_activity("2026-10-15T10:00:00Z", text="x" * 501))

        self.assertEqual(len(item["excerpts"][0]["text"]), 500)

    def test_excerpts_keep_the_ten_newest_activities(self):
        activity = [make_activity(f"2026-10-14T{hour:02d}:00:00Z", text=f"note {hour}") for hour in range(1, 13)]

        item = self.pull_request(*activity)

        self.assertEqual([excerpt["text"] for excerpt in item["excerpts"]], [f"note {hour}" for hour in range(12, 2, -1)])

    def test_activity_before_the_week_is_not_an_excerpt(self):
        item = self.pull_request(make_activity("2026-10-01T10:00:00Z"), make_activity("2026-10-15T10:00:00Z", text="recent"))

        self.assertEqual([excerpt["text"] for excerpt in item["excerpts"]], ["recent"])

    def test_activity_of_another_pull_request_is_not_an_excerpt(self):
        item = self.pull_request(make_activity("2026-10-15T10:00:00Z", number=8))

        self.assertEqual((item["excerpts"], item["when"]), ([], "2026-10-14T09:30:00Z"))

    def test_a_pull_request_without_activity_in_the_week_falls_back_to_its_update_time(self):
        item = self.pull_request(make_activity("2026-10-01T10:00:00Z"))

        self.assertEqual((item["when"], item["people"], item["excerpts"]), ("2026-10-14T09:30:00Z", [], []))

    def test_a_collection_without_activity_still_gives_the_pull_request(self):
        document = make_collection("code", make_window(), {"pull_requests": [make_request()]})

        self.assertEqual(list(self.items(collections={"code": document})), ["pr:example-org/service#7"])

    def test_activity_outside_the_window_and_an_old_update_make_no_item(self):
        records = {"pull_requests": [make_request(updated_at="2026-10-05T09:30:00Z")], "activity": [make_activity("2026-10-05T09:30:00Z")]}

        self.assertEqual(self.items(collections=self.collection("code", **records)), {})


class PageFeaturesTest(FeaturesCase):
    def test_a_page_edited_in_the_week_is_an_item_with_its_text_as_one_excerpt(self):
        item = self.items(collections=self.collection("docs", pages=[make_page()]))["page:page-ab12"]

        self.assertEqual(
            item,
            {
                "source": "docs",
                "role": "document_store",
                "kind": "page",
                "title": "Launch plan",
                "status": None,
                "link": "https://docs.example.test/page-ab12",
                "when": "2026-10-15T08:00:00Z",
                "people": [],
                "excerpts": [{"by": None, "at": "2026-10-15T08:00:00Z", "text": "Plan\nShip it"}],
                "channel_name": None,
            },
        )

    def test_the_page_excerpt_is_cut_to_1000_characters(self):
        page = make_page(texts=("y" * 800, "z" * 800))

        item = self.items(collections=self.collection("docs", pages=[page]))["page:page-ab12"]

        self.assertEqual(item["excerpts"][0]["text"], "y" * 800 + "\n" + "z" * 199)

    def test_a_page_without_text_has_no_excerpt(self):
        item = self.items(collections=self.collection("docs", pages=[make_page(texts=())]))["page:page-ab12"]

        self.assertEqual(item["excerpts"], [])

    def test_a_page_edited_before_the_week_makes_no_item(self):
        self.assertEqual(self.items(collections=self.collection("docs", pages=[make_page(last_edited="2026-10-05T08:00:00Z")])), {})


class RecapFeaturesTest(FeaturesCase):
    def stored(self, **units):
        return make_stored(**units)

    def test_a_recap_thread_seen_in_the_week_is_an_item_with_its_title_status_and_link(self):
        unit = make_unit(kind="thread", channel=CHAN, channel_name="#export", status="waiting", title="Review the export plan", person={"id": PEER, "name": NAMES[PEER]}, **RECAP_FRESH)

        item = self.items(recap=self.stored(**{THREAD_KEY: unit}))[f"chat:{THREAD_KEY}"]

        last = RECAP_FRESH["last_ts"]
        self.assertEqual(
            item,
            {
                "source": "recap",
                "role": "chat",
                "kind": "thread",
                "title": "Review the export plan",
                "status": "waiting",
                "link": f"https://{HOST}/archives/{CHAN}/p{last.replace('.', '')}?thread_ts={ROOT}&cid={CHAN}",
                "when": "2026-10-14T09:00:00Z",
                "people": ["Peer Name"],
                "excerpts": [],
                "channel_name": "#export",
            },
        )

    def test_a_recap_dm_links_to_its_last_message_without_a_thread(self):
        unit = make_unit(kind="dm", channel=DM, **RECAP_FRESH)

        item = self.items(recap=self.stored(**{DM_KEY: unit}))[f"chat:{DM_KEY}"]

        self.assertEqual((item["kind"], item["people"], item["link"]), ("dm", [], f"https://{HOST}/archives/{DM}/p{RECAP_FRESH['last_ts'].replace('.', '')}"))

    def test_a_recap_unit_first_seen_in_the_week_is_an_item_even_with_an_older_message(self):
        unit = make_unit(kind="dm", channel=DM, first_seen="2026-10-13T08:00:00Z", last_ts=RECAP_STALE["last_ts"])

        item = self.items(recap=self.stored(**{DM_KEY: unit}))[f"chat:{DM_KEY}"]

        self.assertEqual(item["when"], "2026-10-13T08:00:00Z")

    def test_a_recap_unit_outside_the_week_makes_no_item(self):
        unit = make_unit(kind="dm", channel=DM, **RECAP_STALE)

        self.assertEqual(self.items(recap=self.stored(**{DM_KEY: unit})), {})

    def test_a_recap_unit_of_an_excluded_channel_is_dropped(self):
        unit = make_unit(kind="dm", channel=EXCLUDED, **RECAP_FRESH)

        self.assertEqual(self.items(recap=self.stored(**{f"dm-{EXCLUDED}": unit})), {})

    def test_recap_counts_cover_the_records_of_the_week_only(self):
        records = [
            make_record("2026-10-13T08:00:00Z", new=[DM_KEY, THREAD_KEY], resolved=[DM_KEY], handled=[THREAD_KEY]),
            make_record("2026-10-15T08:00:00Z", new=[DM_KEY], handled=[f"dm-D{'2' * 6}"]),
            make_record("2026-10-09T08:00:00Z", new=["dm-D777777"], resolved=["dm-D777777"], handled=["dm-D777777"]),
        ]

        counts = self.computed(recap=self.stored(), records=records)["recap_counts"]

        self.assertEqual(counts, {"new": 2, "resolved": 1, "handled": 2})

    def test_recap_counts_skip_the_keys_of_an_excluded_channel(self):
        records = [make_record("2026-10-13T08:00:00Z", new=[DM_KEY, f"dm-{EXCLUDED}"])]

        self.assertEqual(self.computed(recap=self.stored(), records=records)["recap_counts"]["new"], 1)

    def test_recap_counts_are_zero_without_a_recap(self):
        self.assertEqual(self.computed()["recap_counts"], {"new": 0, "resolved": 0, "handled": 0})

    def test_a_recap_folder_without_runs_counts_nothing(self):
        self.write("config.json", make_config())
        os.makedirs(self.path("recap"))
        self.write("recap/state.json", self.stored())

        code, _, err = self.run_weekly(
            "features", "--config", self.path("config.json"), "--routine", SLUG, "--window", self.write("window.json", make_window()),
            "--collections", self.path("collections"), "--out", self.path("features.json"), "--recap", self.path("recap"),
        )

        self.assertEqual((code, err, self.read("features.json")["recap_counts"]), (0, "", {"new": 0, "resolved": 0, "handled": 0}))

    def test_rejects_a_recap_state_naming_its_key_path(self):
        document = self.stored()
        document["run"]["window"] = {"from_ts": 5, "to_ts": 1}

        code, _, err = self.run_features(recap=document)

        self.assertEqual(code, 3)
        self.assertIn("run.window", err)

    def test_rejects_a_recap_record_naming_its_key_path(self):
        code, _, err = self.run_features(recap=self.stored(), records=[{"run_at": "later", "new": [], "resolved": [], "handled": []}])

        self.assertEqual(code, 3)
        self.assertRegex(err, r"recap record: .*0\.json.*run_at|recap record: .*run_at")


class DirectChatFeaturesTest(FeaturesCase):
    def chat(self, *units, **options):
        return self.items(collections=self.collection("chat", units=list(units)), **options)

    def test_a_direct_unit_adds_its_messages_to_the_recap_item_of_the_same_key(self):
        unit = make_unit(kind="thread", channel=CHAN, **RECAP_FRESH)
        first, reply = stamp("2026-10-13T09:00:00Z"), stamp("2026-10-14T09:00:00Z", 200)
        thread = make_chat_unit(CHAN, "#ops", make_message(PEER, first, "first", root=ROOT), make_message(OWNER, reply, "reply", root=ROOT))

        item = self.chat(thread, recap=make_stored(**{THREAD_KEY: unit}))[f"chat:{THREAD_KEY}"]

        self.assertEqual(item["source"], "recap")
        self.assertEqual(
            item["excerpts"],
            [{"by": "Owner Name", "at": "2026-10-14T09:00:00Z", "text": "reply"}, {"by": "Peer Name", "at": "2026-10-13T09:00:00Z", "text": "first"}],
        )

    def test_a_direct_unit_without_a_recap_item_makes_its_own_item_titled_by_its_first_message(self):
        root, reply = stamp("2026-10-13T09:00:00Z", 1), stamp("2026-10-14T09:00:00Z", 2)
        thread = make_chat_unit(CHAN, "#ops", make_message(PEER, root, "Can you look\nat the   export? " + "z" * 100, root=root), make_message(OWNER, reply, "on it", root=root))

        item = self.chat(thread)[f"chat:thread-{CHAN}-{root}"]

        self.assertEqual(
            {key: item[key] for key in ("source", "role", "kind", "status", "when", "people", "link")},
            {
                "source": "chat",
                "role": "chat",
                "kind": "thread",
                "status": None,
                "when": "2026-10-14T09:00:00Z",
                "people": ["Owner Name", "Peer Name"],
                "link": f"https://{HOST}/archives/{CHAN}/p{reply.replace('.', '')}?thread_ts={root}&cid={CHAN}",
            },
        )
        self.assertEqual(item["title"], ("Can you look at the export? " + "z" * 100)[:80])

    def test_a_direct_dm_makes_a_dm_item(self):
        at = stamp("2026-10-14T09:00:00Z")

        item = self.chat(make_chat_unit(DM, "DM", make_message(PEER, at, "ping")))[f"chat:{DM_KEY}"]

        self.assertEqual((item["kind"], item["link"]), ("dm", f"https://{HOST}/archives/{DM}/p{at.replace('.', '')}"))

    def test_messages_cap_at_fifteen_newest_and_500_characters(self):
        messages = [make_message(PEER, stamp(f"2026-10-14T{hour:02d}:00:00Z"), f"m{hour}" + "w" * 600) for hour in range(1, 18)]

        item = self.chat(make_chat_unit(DM, "DM", *messages))[f"chat:{DM_KEY}"]

        self.assertEqual([excerpt["text"][:3].rstrip("w") for excerpt in item["excerpts"]][:2], ["m17", "m16"])
        self.assertEqual((len(item["excerpts"]), {len(excerpt["text"]) for excerpt in item["excerpts"]}), (15, {500}))

    def test_a_message_from_before_the_week_is_no_excerpt_and_no_item(self):
        old = stamp("2026-10-05T09:00:00Z")

        self.assertEqual(self.chat(make_chat_unit(DM, "DM", make_message(PEER, old))), {})

    def test_a_direct_unit_of_an_excluded_channel_is_dropped(self):
        at = stamp("2026-10-14T09:00:00Z")

        self.assertEqual(self.chat(make_chat_unit(EXCLUDED, "DM", make_message(PEER, at))), {})

    def test_a_message_found_twice_is_one_excerpt(self):
        at = stamp("2026-10-14T09:00:00Z")
        unit = make_chat_unit(DM, "DM", make_message(PEER, at))

        item = self.chat(unit, unit)[f"chat:{DM_KEY}"]

        self.assertEqual(len(item["excerpts"]), 1)


class SourcesFeaturesTest(FeaturesCase):
    def test_every_source_is_listed_with_its_read_state_and_reason(self):
        collections = {
            "issues": make_collection("issues", make_window()),
            "code": make_collection("code", make_window(), read=False, reason="http 503"),
            "chat": make_collection("chat", make_window()),
        }

        sources = self.computed(collections=collections)["sources"]

        self.assertEqual(
            sources,
            [
                {"source": "chat", "role": "chat", "read": True, "reason": None},
                {"source": "code", "role": "code_host", "read": False, "reason": "http 503"},
                {"source": "docs", "role": "document_store", "read": False, "reason": "no collection"},
                {"source": "issues", "role": "issue_tracker", "read": True, "reason": None},
            ],
        )

    def test_a_missing_collection_makes_no_item_and_does_not_stop_the_others(self):
        items = self.items(collections=self.collection("issues", issues=[make_issue()]))

        self.assertEqual(list(items), ["issue:PROJ-12"])

    def test_a_source_not_read_makes_no_item(self):
        collections = {"issues": make_collection("issues", make_window(), read=False, reason="http 503")}

        self.assertEqual(self.items(collections=collections), {})

    def test_rejects_a_collection_that_fails_its_checks_naming_the_file_and_key_path(self):
        document = make_collection("issues", make_window(), {"issues": [make_issue(updated="yesterday")]})

        code, _, err = self.run_features(collections={"issues": document})

        self.assertEqual(code, 3)
        self.assertRegex(err, r"collection .*issues\.json: records\.issues\[0\]\.updated")

    def test_rejects_a_collection_of_another_window(self):
        document = make_collection("issues", make_window(from_ts=1))

        code, _, err = self.run_features(collections={"issues": document})

        self.assertEqual(code, 3)
        self.assertRegex(err, r"issues\.json: window")

    def test_a_collection_that_is_not_json_is_an_input_error(self):
        os.makedirs(self.path("collections"))
        with open(self.path("collections/issues.json"), "w", encoding="utf-8") as handle:
            handle.write("{")

        code, _, err = self.run_features()

        self.assertEqual(code, 2)
        self.assertRegex(err, r"collection .*issues\.json: invalid JSON")

    def test_a_missing_window_is_an_input_error(self):
        self.write("config.json", make_config())

        code, _, err = self.run_weekly(
            "features", "--config", self.path("config.json"), "--routine", SLUG, "--window", self.path("none.json"),
            "--collections", self.path("collections"), "--out", self.path("features.json"),
        )

        self.assertEqual(code, 2)
        self.assertIn("none.json", err)

    def test_rejects_a_window_naming_its_key_path(self):
        code, _, err = self.run_features(window={**make_window(), "week_start": "soon"})

        self.assertEqual(code, 3)
        self.assertIn("week_start", err)

    def test_rejects_a_routine_of_another_engine(self):
        code, _, err = self.run_features(config=make_config(engine="watch"))

        self.assertEqual(code, 2)
        self.assertRegex(err, re.escape(f"routine {SLUG}"))


class JudgeCase(WeeklyCase):
    def judge(self, judgment, features=None):
        self.write("features.json", features or make_features_document())
        self.write("judgment.json", judgment)
        return self.run_weekly("judge", "--features", self.path("features.json"), "--judgment", self.path("judgment.json"), "--out", self.path("summary.json"))

    def accepted(self, judgment, features=None):
        code, _, err = self.judge(judgment, features)
        self.assertEqual((code, err), (0, ""))
        return self.read("summary.json")

    def rejection(self, judgment, features=None):
        code, _, err = self.judge(judgment, features)
        self.assertEqual(code, 3)
        self.assertFalse(os.path.exists(self.path("summary.json")))
        return err

    def changed(self, mutate, features=None):
        judgment = make_judgment()
        mutate(judgment)
        return self.rejection(judgment, features)

    def assert_rejected_at(self, mutate, path, features=None):
        self.assertRegex(self.changed(mutate, features), r"rejected: judgment: " + re.escape(path) + r": ")


class JudgeAcceptTest(JudgeCase):
    def test_a_valid_judgment_writes_the_summary_with_the_features_context(self):
        summary = self.accepted(make_judgment())

        self.assertEqual(summary, make_summary())
        self.assert_canonical("summary.json")

    def test_an_empty_week_accepts_no_accomplishment(self):
        judgment = {"schema": 1, "accomplishments": [], "decisions": [], "open": []}

        summary = self.accepted(judgment, make_features_document(items={}))

        self.assertEqual(summary["accomplishments"], [])

    def test_a_text_of_200_characters_is_accepted(self):
        judgment = make_judgment()
        judgment["decisions"][0]["text"] = "x" * 200

        self.assertEqual(self.accepted(judgment)["decisions"][0]["text"], "x" * 200)

    def test_an_owner_of_60_characters_is_accepted(self):
        judgment = make_judgment()
        judgment["open"][0]["owner"] = "x" * 60

        self.assertEqual(self.accepted(judgment)["open"][0]["owner"], "x" * 60)

    def test_an_open_bullet_without_owner_is_accepted(self):
        judgment = make_judgment()
        judgment["open"][0]["owner"] = None

        self.assertIsNone(self.accepted(judgment)["open"][0]["owner"])

    def test_texts_of_220_words_together_are_accepted(self):
        judgment = make_judgment()
        judgment["accomplishments"][0]["text"] = words(74)
        judgment["decisions"][0]["text"] = words(73)
        judgment["open"][0]["text"] = words(73)

        self.assertEqual(self.accepted(judgment)["open"][0]["text"], words(73))

    def test_six_accomplishments_six_decisions_and_eight_open_are_accepted(self):
        judgment = make_judgment()
        judgment["accomplishments"] = [{"text": f"Done {index}", "cites": [ISSUE_KEY]} for index in range(6)]
        judgment["decisions"] = [{"text": f"Decided {index}", "cites": [ISSUE_KEY]} for index in range(6)]
        judgment["open"] = [{"text": f"Open {index}", "owner": None, "cites": [ISSUE_KEY]} for index in range(8)]

        self.assertEqual(len(self.accepted(judgment)["open"]), 8)


class JudgeShapeTest(JudgeCase):
    def test_rejects_a_judgment_that_is_not_json(self):
        self.write("features.json", make_features_document())
        with open(self.path("judgment.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")

        code, _, err = self.run_weekly("judge", "--features", self.path("features.json"), "--judgment", self.path("judgment.json"), "--out", self.path("summary.json"))

        self.assertEqual(code, 3)
        self.assertRegex(err, r"judgment: invalid JSON in .*judgment\.json")

    def test_rejects_a_judgment_that_is_not_an_object(self):
        self.assertRegex(self.rejection([]), r"judgment: <root>: expected an object")

    def test_rejects_another_schema(self):
        err = self.changed(lambda doc: doc.update(schema=2))

        self.assertIn("judgment: expected schema 1 at schema", err)

    def test_rejects_an_unknown_key(self):
        self.assert_rejected_at(lambda doc: doc.update(risks=[]), "risks")

    def test_rejects_a_missing_section(self):
        self.assert_rejected_at(lambda doc: doc.pop("decisions"), "decisions")

    def test_rejects_an_unknown_bullet_field(self):
        self.assert_rejected_at(lambda doc: doc["accomplishments"][0].update(owner="Ada"), "accomplishments[0].owner")

    def test_rejects_an_open_bullet_without_owner_field(self):
        self.assert_rejected_at(lambda doc: doc["open"][0].pop("owner"), "open[0].owner")

    def test_rejects_a_section_that_is_not_a_list(self):
        self.assert_rejected_at(lambda doc: doc.update(decisions={}), "decisions")

    def test_rejects_a_bullet_that_is_not_an_object(self):
        self.assert_rejected_at(lambda doc: doc["decisions"].append("text"), "decisions[1]")


class JudgeCountTest(JudgeCase):
    def test_rejects_no_accomplishment_when_the_features_hold_items(self):
        self.assert_rejected_at(lambda doc: doc.update(accomplishments=[]), "accomplishments")

    def test_rejects_seven_accomplishments(self):
        self.assert_rejected_at(lambda doc: doc.update(accomplishments=[doc["accomplishments"][0]] * 7), "accomplishments")

    def test_rejects_an_accomplishment_when_the_features_hold_no_item(self):
        judgment = {"schema": 1, "accomplishments": make_judgment()["accomplishments"], "decisions": [], "open": []}

        self.assertRegex(self.rejection(judgment, make_features_document(items={})), r"judgment: accomplishments: ")

    def test_rejects_seven_decisions(self):
        self.assert_rejected_at(lambda doc: doc.update(decisions=[doc["decisions"][0]] * 7), "decisions")

    def test_rejects_nine_open_bullets(self):
        self.assert_rejected_at(lambda doc: doc.update(open=[doc["open"][0]] * 9), "open")


class JudgeTextTest(JudgeCase):
    def text_rejected(self, text):
        self.assert_rejected_at(lambda doc: doc["decisions"][0].update(text=text), "decisions[0].text")

    def test_rejects_a_text_that_is_not_a_string(self):
        self.text_rejected(7)

    def test_rejects_an_empty_text(self):
        self.text_rejected("")

    def test_rejects_a_blank_text(self):
        self.text_rejected("   ")

    def test_rejects_a_text_of_201_characters(self):
        self.text_rejected("x" * 201)

    def test_rejects_a_text_with_an_https_url(self):
        self.text_rejected("See https://example.test/page for details")

    def test_rejects_a_text_with_an_http_url_in_capitals(self):
        self.text_rejected("See HTTP://example.test for details")

    def test_rejects_a_text_with_a_www_address(self):
        self.text_rejected("See www.example.test for details")

    def test_rejects_a_text_with_a_line_break(self):
        self.text_rejected("First line\nSecond line")

    def test_rejects_a_text_with_a_control_character(self):
        self.text_rejected("Tabbed\ttext")

    def test_rejects_a_text_with_a_zero_width_character(self):
        self.text_rejected("Hidden​text")

    def test_names_the_open_bullet_text_path(self):
        self.assert_rejected_at(lambda doc: doc["open"][0].update(text="x" * 201), "open[0].text")

    def test_rejects_texts_of_221_words_together_naming_the_bullet_that_crosses_the_cap(self):
        def mutate(doc):
            doc["accomplishments"][0]["text"] = words(74)
            doc["decisions"][0]["text"] = words(73)
            doc["open"][0]["text"] = words(74)

        self.assert_rejected_at(mutate, "open[0].text")


class JudgeOwnerTest(JudgeCase):
    def owner_rejected(self, owner):
        self.assert_rejected_at(lambda doc: doc["open"][0].update(owner=owner), "open[0].owner")

    def test_rejects_an_owner_of_61_characters(self):
        self.owner_rejected("x" * 61)

    def test_rejects_a_blank_owner(self):
        self.owner_rejected("  ")

    def test_rejects_an_owner_that_is_not_a_string(self):
        self.owner_rejected(7)

    def test_rejects_an_owner_with_a_line_break(self):
        self.owner_rejected("Ada\nLovelace")


class JudgeCitesTest(JudgeCase):
    def test_rejects_a_cite_that_is_not_an_item_key(self):
        def mutate(doc):
            doc["accomplishments"][0]["cites"] = [ISSUE_KEY, "issue:OTHER-1"]

        self.assert_rejected_at(mutate, "accomplishments[0].cites[1]")

    def test_the_rejection_names_the_unknown_cite(self):
        err = self.changed(lambda doc: doc["decisions"][0].update(cites=["issue:OTHER-1"]))

        self.assertIn("issue:OTHER-1 is not an item of the features", err)

    def test_rejects_a_cite_repeated_within_a_bullet(self):
        self.assert_rejected_at(lambda doc: doc["accomplishments"][0].update(cites=[ISSUE_KEY, PR_KEY, ISSUE_KEY]), "accomplishments[0].cites[2]")

    def test_the_same_item_may_be_cited_by_two_bullets(self):
        judgment = make_judgment()
        judgment["decisions"][0]["cites"] = [ISSUE_KEY]

        self.assertEqual(self.accepted(judgment)["decisions"][0]["cites"], [ISSUE_KEY])

    def test_rejects_empty_cites(self):
        self.assert_rejected_at(lambda doc: doc["open"][0].update(cites=[]), "open[0].cites")

    def test_rejects_cites_that_are_not_a_list(self):
        self.assert_rejected_at(lambda doc: doc["open"][0].update(cites=ISSUE_KEY), "open[0].cites")

    def test_rejects_a_cite_that_is_not_a_string(self):
        self.assert_rejected_at(lambda doc: doc["open"][0].update(cites=[["x"]]), "open[0].cites[0]")

    def test_cleans_the_key_of_an_unknown_cite_before_naming_it(self):
        err = self.changed(lambda doc: doc["open"][0].update(cites=["issue:\nforged: ok"]))

        self.assertNotIn("\nforged", err)


class JudgeInputTest(JudgeCase):
    def test_a_missing_judgment_file_is_an_input_error_naming_the_file(self):
        self.write("features.json", make_features_document())

        code, _, err = self.run_weekly("judge", "--features", self.path("features.json"), "--judgment", self.path("none.json"), "--out", self.path("summary.json"))

        self.assertEqual(code, 2)
        self.assertIn("none.json", err)

    def test_features_missing_a_key_are_an_input_error_naming_the_key_path(self):
        features = make_features_document()
        del features["recap_counts"]

        code, _, err = self.judge(make_judgment(), features)

        self.assertEqual(code, 2)
        self.assertIn("recap_counts", err)


class ApplyCase(WeeklyCase):
    def apply(self, summary=None, state_document=None, window=None):
        self.write("state.json", state_document or {"schema": "weekly-1", "digest": SLUG, "last_run": None})
        self.write("summary.json", summary or make_summary())
        self.write("window.json", window or make_window())
        return self.run_weekly(
            "apply", "--state", self.path("state.json"), "--summary", self.path("summary.json"), "--window", self.path("window.json"),
            "--out", self.path("next.json"), "--record", self.path("record.json"),
        )

    def applied(self, **options):
        code, _, err = self.apply(**options)
        self.assertEqual((code, err), (0, ""))


class ApplyStateTest(ApplyCase):
    def test_the_next_state_records_the_run_time_and_the_week(self):
        self.applied()

        self.assertEqual(
            self.read("next.json"),
            {"schema": "weekly-1", "digest": SLUG, "last_run": {"run_at": NOW, "week_start": "2026-10-12"}},
        )
        self.assert_canonical("next.json")

    def test_the_next_state_replaces_the_previous_last_run(self):
        previous = {"schema": "weekly-1", "digest": SLUG, "last_run": {"run_at": "2026-10-09T14:00:00Z", "week_start": "2026-10-05"}}

        self.applied(state_document=previous)

        self.assertEqual(self.read("next.json")["last_run"], {"run_at": NOW, "week_start": "2026-10-12"})

    def test_a_report_only_window_keeps_the_state(self):
        previous = {"schema": "weekly-1", "digest": SLUG, "last_run": {"run_at": "2026-10-09T14:00:00Z", "week_start": "2026-10-05"}}

        self.applied(state_document=previous, window=make_window(report_only=True))

        with open(self.path("state.json"), "rb") as source, open(self.path("next.json"), "rb") as written:
            self.assertEqual(written.read(), source.read())

    def test_rejects_a_state_naming_the_file_and_key_path(self):
        code, _, err = self.apply(state_document={"schema": "weekly-1", "digest": SLUG, "last_run": {"run_at": "soon", "week_start": "2026-10-12"}})

        self.assertEqual(code, 3)
        self.assertRegex(err, r"state: .*last_run\.run_at")
        self.assertFalse(os.path.exists(self.path("record.json")))

    def test_a_summary_missing_a_key_is_an_input_error_naming_the_key_path(self):
        summary = make_summary()
        del summary["open"]

        code, _, err = self.apply(summary=summary)

        self.assertEqual(code, 2)
        self.assertIn("open", err)

    def test_rejects_a_window_naming_its_key_path(self):
        code, _, err = self.apply(window={**make_window(), "week_start": "soon"})

        self.assertEqual(code, 3)
        self.assertIn("week_start", err)


class ApplyRecordTest(ApplyCase):
    def test_the_record_holds_the_window_the_counts_the_cited_keys_and_the_sources(self):
        self.applied()

        self.assertEqual(
            self.read("record.json"),
            {
                "schema": 1,
                "run_at": NOW,
                "window": make_window(),
                "week_start": "2026-10-12",
                "report_only": False,
                "counts": {
                    "items": {"issue_tracker": 1, "code_host": 1, "chat": 1, "document_store": 1},
                    "sections": {"accomplishments": 1, "decisions": 1, "open": 1},
                },
                "cited": sorted([ISSUE_KEY, PR_KEY, PAGE_KEY, THREAD_ITEM]),
                "sources": [
                    {"source": "chat", "read": True, "reason": None},
                    {"source": "code", "read": True, "reason": None},
                    {"source": "docs", "read": True, "reason": None},
                    {"source": "issues", "read": True, "reason": None},
                ],
            },
        )
        self.assert_canonical("record.json")

    def test_an_item_cited_by_two_bullets_counts_once(self):
        judgment = make_judgment()
        judgment["decisions"][0]["cites"] = [ISSUE_KEY]

        self.applied(summary=make_summary(judgment))

        self.assertEqual(self.read("record.json")["counts"]["items"]["issue_tracker"], 1)

    def test_a_source_not_read_keeps_its_reason(self):
        features = make_features_document(sources=make_source_rows(code={"read": False, "reason": "http 503"}))

        self.applied(summary=make_summary(features=features))

        self.assertIn({"source": "code", "read": False, "reason": "http 503"}, self.read("record.json")["sources"])

    def test_the_record_of_a_report_only_run_is_marked(self):
        self.applied(window=make_window(report_only=True))

        self.assertTrue(self.read("record.json")["report_only"])

    def test_neither_file_holds_a_bullet_text_a_title_or_an_owner_name(self):
        self.applied()

        with open(self.path("record.json"), encoding="utf-8") as record, open(self.path("next.json"), encoding="utf-8") as written:
            kept = record.read() + written.read()
        texts = [entry["text"] for section in ("accomplishments", "decisions", "open") for entry in make_judgment()[section]]
        titles = [item["title"] for item in make_features_items().values()]
        for text in [*texts, *titles, OWNER_NAME]:
            self.assertNotIn(text, kept)


if __name__ == "__main__":
    unittest.main()
