import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from unittest import mock

import days
import providers
import store

DAY_26 = 1792972800
DAY_27 = DAY_26 + 86400
RUN = "20261027T070000Z-a1b2c3"
LATER_RUN = "20261027T090000Z-d4e5f6"
FETCHED_AT = "2026-10-27T07:00:05Z"
LATER_AT = "2026-10-27T09:00:05Z"
CHANNEL = (("channel", "C0TRIBE1"),)
HISTORY_DIR = "provider=chat/kind=history/year=2026/month=10/day=26/channel=C0TRIBE1"
NEXT_HISTORY_DIR = "provider=chat/kind=history/year=2026/month=10/day=27/channel=C0TRIBE1"
REQUEST = {"tool": "slack_read_channel", "arguments": {"channel_id": "C0TRIBE1"}}


def message(ts, text="hi", author="U0BOB"):
    return {"ts": ts, "author": author, "text": text, "thread_ts": None, "name": "", "bot": False}


def reply(ts, text="hi"):
    return {"ts": ts, "author": "U0BOB", "text": text, "name": "", "bot": False}


class DayCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.store_dir = os.path.join(self.tmp, "shared")
        self.layer = days.DayLayer(self.store_dir)

    def read(self, records, kind="history", entity=CHANNEL, span=(str(DAY_26), str(DAY_27)), run=RUN, at=FETCHED_AT, transport="mcp", status="complete", shared=None):
        root = os.path.join(self.tmp, "runs", run, kind)
        session = store.ReadSession(root, "chat", run, "channels", "slack", transport, clock=lambda: at, runtime="ab" * 20, shared=shared)
        handle = session.open(kind, entity, span)
        handle.page(REQUEST, fetch=lambda: b"page")
        handle.finish(status, None if status == "complete" else "why", records)
        return handle

    def merged(self, *args, **kwargs):
        handle = self.read(*args, **kwargs)
        self.layer.merge(handle.folder, handle.document())
        return handle

    def published(self, *args, **kwargs):
        return self.read(*args, shared=self.store_dir, **kwargs)

    def cli(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            code = days.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def day_path(self, relative, name=days.RECORDS_FILE):
        return os.path.join(self.store_dir, days.DAYS_DIR, *relative.split("/"), name)

    def rows(self, relative):
        with open(self.day_path(relative), encoding="utf-8") as stream:
            return [json.loads(line) for line in stream]

    def coverage(self, relative):
        with open(self.day_path(relative, days.COVERAGE_FILE), encoding="utf-8") as stream:
            return json.load(stream)

    def texts(self, relative):
        return [(row["ts"], row["text"]) for row in self.rows(relative)]


class FileByDayTest(DayCase):
    def test_files_a_history_record_under_its_channel_and_day(self):
        self.merged([message(f"{DAY_26 + 60}.000100")])

        self.assertEqual(self.texts(HISTORY_DIR), [(f"{DAY_26 + 60}.000100", "hi")])

    def test_files_the_last_microsecond_of_a_day_in_that_day(self):
        self.merged([message(f"{DAY_27 - 1}.999999")])

        self.assertEqual(self.texts(HISTORY_DIR), [(f"{DAY_27 - 1}.999999", "hi")])

    def test_files_midnight_in_the_next_day(self):
        self.merged([message(f"{DAY_27}.000000")], span=(str(DAY_26), str(DAY_27 + 60)))

        self.assertEqual(self.texts(NEXT_HISTORY_DIR), [(f"{DAY_27}.000000", "hi")])

    def test_files_thread_replies_by_their_own_day(self):
        root = f"{DAY_26 + 10}.000100"
        entity = (("channel", "C0TRIBE1"), ("root", root))
        self.merged([reply(root), reply(f"{DAY_27 + 10}.000100"), reply(f"{DAY_27 + 86400 + 10}.000100")], kind="thread", entity=entity, span=(root, str(DAY_27 + 2 * 86400)))

        folders = [f"provider=chat/kind=thread/year=2026/month=10/day={day}/channel=C0TRIBE1/root={root}" for day in ("26", "27", "28")]
        self.assertEqual([len(self.rows(folder)) for folder in folders], [1, 1, 1])

    def test_files_a_search_hit_under_its_search_and_message_day(self):
        item = message(f"{DAY_26 + 30}.000100")
        hit = {"channel": "C0OTHER", "name": "other", "kind": None, "participants": [], "root": None, "kind_type": None, "item": item}
        self.merged([hit], kind="search", entity=(("search", "mentions"),))

        self.assertEqual(len(self.rows("provider=chat/kind=search/year=2026/month=10/day=26/search=mentions")), 1)

    def test_files_reactions_under_the_day_of_their_message(self):
        entity = (("channel", "C0TRIBE1"), ("message", f"{DAY_26 + 30}.000100"))
        self.merged([{"user": "U0BOB"}], kind="reactions", entity=entity, span=None)

        folder = f"provider=chat/kind=reactions/year=2026/month=10/day=26/channel=C0TRIBE1/message={DAY_26 + 30}.000100"
        self.assertEqual([row["user"] for row in self.rows(folder)], ["U0BOB"])

    def test_files_an_empty_reaction_set_under_the_day_of_its_message(self):
        entity = (("channel", "C0TRIBE1"), ("message", f"{DAY_26 + 30}.000100"))
        self.merged([], kind="reactions", entity=entity, span=None)

        folder = f"provider=chat/kind=reactions/year=2026/month=10/day=26/channel=C0TRIBE1/message={DAY_26 + 30}.000100"
        self.assertEqual((self.rows(folder), self.coverage(folder)["snapshot"]["fetch_id"]), ([], f"{RUN}.channels"))

    def test_files_no_members_read(self):
        self.merged([{"id": "U0BOB"}], kind="members", span=None)

        self.assertFalse(os.path.exists(os.path.join(self.store_dir, days.DAYS_DIR, "provider=chat", "kind=members")))

    def test_files_no_partial_read(self):
        self.merged([message(f"{DAY_26 + 60}.000100")], status="partial")

        self.assertFalse(os.path.exists(os.path.join(self.store_dir, days.DAYS_DIR, "provider=chat")))

    def test_files_no_failed_read(self):
        self.merged([], status="failed")

        self.assertFalse(os.path.exists(os.path.join(self.store_dir, days.DAYS_DIR, "provider=chat")))

    def test_writes_a_quiet_day_with_coverage_and_no_record(self):
        self.merged([])

        self.assertEqual((self.rows(HISTORY_DIR), self.coverage(HISTORY_DIR)["spans"]), ([], {"mcp": [[str(DAY_26), str(DAY_27)]]}))

    def test_leaves_the_path_values_out_of_a_record(self):
        self.merged([message(f"{DAY_26 + 60}.000100")])

        self.assertNotIn("channel", self.rows(HISTORY_DIR)[0])

    def test_names_the_fetch_of_each_record(self):
        self.merged([message(f"{DAY_26 + 60}.000100")])

        row = self.rows(HISTORY_DIR)[0]
        self.assertEqual((row["fetch_id"], row["fetched_at"], row["transport"]), (f"{RUN}.channels", FETCHED_AT, "mcp"))

    def test_keeps_day_files_private(self):
        self.merged([message(f"{DAY_26 + 60}.000100")])

        modes = [stat.S_IMODE(os.stat(self.day_path(HISTORY_DIR, name)).st_mode) for name in (days.RECORDS_FILE, days.COVERAGE_FILE)]
        self.assertEqual(modes + [stat.S_IMODE(os.stat(os.path.dirname(self.day_path(HISTORY_DIR))).st_mode)], [0o600, 0o600, 0o700])


class MergeTest(DayCase):
    def test_keeps_a_ts_seen_by_two_overlapping_reads_once(self):
        ts = f"{DAY_26 + 60}.000100"
        self.merged([message(ts)], span=(str(DAY_26), str(DAY_26 + 120)))
        self.merged([message(ts)], span=(str(DAY_26 + 30), str(DAY_27)), run=LATER_RUN, at=LATER_AT)

        self.assertEqual(len(self.rows(HISTORY_DIR)), 1)

    def test_keeps_the_text_of_the_newer_fetch(self):
        ts = f"{DAY_26 + 60}.000100"
        self.merged([message(ts, "draft")])
        self.merged([message(ts, "edited")], run=LATER_RUN, at=LATER_AT)

        self.assertEqual(self.texts(HISTORY_DIR), [(ts, "edited")])

    def test_drops_a_record_of_an_older_fetch(self):
        ts = f"{DAY_26 + 60}.000100"
        self.merged([message(ts, "edited")], run=LATER_RUN, at=LATER_AT)
        self.merged([message(ts, "draft")])

        self.assertEqual(self.texts(HISTORY_DIR), [(ts, "edited")])

    def test_replaces_the_whole_reaction_set_with_the_newer_read(self):
        entity = (("channel", "C0TRIBE1"), ("message", f"{DAY_26 + 30}.000100"))
        self.merged([{"user": "U0BOB"}, {"user": "U0CAROL"}], kind="reactions", entity=entity, span=None)
        self.merged([{"user": "U0CAROL"}], kind="reactions", entity=entity, span=None, run=LATER_RUN, at=LATER_AT)

        folder = f"provider=chat/kind=reactions/year=2026/month=10/day=26/channel=C0TRIBE1/message={DAY_26 + 30}.000100"
        self.assertEqual([row["user"] for row in self.rows(folder)], ["U0CAROL"])

    def test_keeps_the_reaction_set_of_the_newer_read_against_an_older_one(self):
        entity = (("channel", "C0TRIBE1"), ("message", f"{DAY_26 + 30}.000100"))
        self.merged([{"user": "U0CAROL"}], kind="reactions", entity=entity, span=None, run=LATER_RUN, at=LATER_AT)
        self.merged([{"user": "U0BOB"}], kind="reactions", entity=entity, span=None)

        folder = f"provider=chat/kind=reactions/year=2026/month=10/day=26/channel=C0TRIBE1/message={DAY_26 + 30}.000100"
        self.assertEqual([row["user"] for row in self.rows(folder)], ["U0CAROL"])

    def test_replaces_the_records_of_the_same_fetch(self):
        handle = self.merged([message(f"{DAY_26 + 60}.000100"), message(f"{DAY_26 + 90}.000100")])
        store.state.write_all([(os.path.join(handle.folder, store.RECORDS_FILE), store.dump_lines([message(f"{DAY_26 + 60}.000100")]))])
        self.layer.merge(handle.folder, handle.document())

        self.assertEqual(self.texts(HISTORY_DIR), [(f"{DAY_26 + 60}.000100", "hi")])

    def test_orders_records_by_ts(self):
        self.merged([message(f"{DAY_26 + 900}.000100"), message(f"{DAY_26 + 60}.000100")])

        self.assertEqual([ts for ts, _ in self.texts(HISTORY_DIR)], [f"{DAY_26 + 60}.000100", f"{DAY_26 + 900}.000100"])

    def test_writes_the_same_bytes_in_any_publish_order(self):
        first = self.read([message(f"{DAY_26 + 60}.000100", "a")], span=(str(DAY_26), str(DAY_26 + 120)))
        second = self.read([message(f"{DAY_26 + 60}.000100", "b"), message(f"{DAY_26 + 200}.000100")], run=LATER_RUN, at=LATER_AT)
        outputs = []
        for order in ((first, second), (second, first)):
            layer = days.DayLayer(os.path.join(self.tmp, f"order-{len(outputs)}"))
            for handle in order:
                layer.merge(handle.folder, handle.document())
            outputs.append([open(os.path.join(layer.base, *HISTORY_DIR.split("/"), name), "rb").read() for name in (days.RECORDS_FILE, days.COVERAGE_FILE)])

        self.assertEqual(outputs[0], outputs[1])


class CoverageTest(DayCase):
    def test_clips_a_span_to_each_day_it_covers(self):
        self.merged([], span=(str(DAY_26 + 100), str(DAY_27 + 100)))

        spans = [self.coverage(folder)["spans"]["mcp"] for folder in (HISTORY_DIR, NEXT_HISTORY_DIR)]
        self.assertEqual(spans, [[[str(DAY_26 + 100), str(DAY_27)]], [[str(DAY_27), str(DAY_27 + 100)]]])

    def test_skips_a_day_the_span_only_touches_at_its_end(self):
        self.merged([], span=(str(DAY_26 + 100), str(DAY_27)))

        self.assertFalse(os.path.exists(self.day_path(NEXT_HISTORY_DIR)))

    def test_merges_touching_spans(self):
        self.merged([], span=(str(DAY_26), str(DAY_26 + 100)))
        self.merged([], span=(str(DAY_26 + 100), str(DAY_26 + 200)), run=LATER_RUN, at=LATER_AT)

        self.assertEqual(self.coverage(HISTORY_DIR)["spans"], {"mcp": [[str(DAY_26), str(DAY_26 + 200)]]})

    def test_keeps_disjoint_spans_apart(self):
        self.merged([], span=(str(DAY_26), str(DAY_26 + 100)))
        self.merged([], span=(str(DAY_26 + 300), str(DAY_26 + 400)), run=LATER_RUN, at=LATER_AT)

        self.assertEqual(self.coverage(HISTORY_DIR)["spans"], {"mcp": [[str(DAY_26), str(DAY_26 + 100)], [str(DAY_26 + 300), str(DAY_26 + 400)]]})

    def test_keeps_spans_of_each_transport_apart(self):
        self.merged([], span=(str(DAY_26), str(DAY_26 + 100)))
        self.merged([], span=(str(DAY_26 + 50), str(DAY_26 + 200)), run=LATER_RUN, at=LATER_AT, transport="api")

        self.assertEqual(self.coverage(HISTORY_DIR)["spans"], {"api": [[str(DAY_26 + 50), str(DAY_26 + 200)]], "mcp": [[str(DAY_26), str(DAY_26 + 100)]]})

    def test_lists_the_fetches_that_covered_a_day(self):
        self.merged([])
        self.merged([], run=LATER_RUN, at=LATER_AT)

        self.assertEqual(self.coverage(HISTORY_DIR)["fetch_ids"], [f"{RUN}.channels", f"{LATER_RUN}.channels"])

    def test_records_the_newest_reactions_read_without_span(self):
        entity = (("channel", "C0TRIBE1"), ("message", f"{DAY_26 + 30}.000100"))
        self.merged([{"user": "U0BOB"}], kind="reactions", entity=entity, span=None)

        folder = f"provider=chat/kind=reactions/year=2026/month=10/day=26/channel=C0TRIBE1/message={DAY_26 + 30}.000100"
        expected = {"fetch_id": f"{RUN}.channels", "fetched_at": FETCHED_AT, "transport": "mcp"}
        self.assertEqual((self.coverage(folder)["spans"], self.coverage(folder)["snapshot"]), ({}, expected))

    def test_names_the_provider_kind_entity_and_day(self):
        self.merged([])

        document = self.coverage(HISTORY_DIR)
        named = {key: document[key] for key in ("provider", "kind", "entity", "day")}
        self.assertEqual(named, {"provider": "chat", "kind": "history", "entity": {"channel": "C0TRIBE1"}, "day": "2026-10-26"})


class ClosedFoldersTest(DayCase):
    NEEDED = (str(DAY_26 + 100), str(DAY_27 + 100))

    def closed(self, window_end=DAY_27 + 3600, needed=NEEDED, kind="history", entity=None):
        return self.layer.closed_folders("chat", kind, entity or dict(CHANNEL), needed, window_end)

    def test_lists_a_closed_day_overlapping_the_need(self):
        self.merged([])

        self.assertEqual(self.closed(), [f"{days.DAYS_DIR}/{HISTORY_DIR}"])

    def test_skips_a_day_that_ends_after_the_window_end(self):
        self.merged([])

        self.assertEqual(self.closed(window_end=DAY_27 - 1), [])

    def test_lists_a_day_ending_exactly_at_the_window_end(self):
        self.merged([])

        self.assertEqual(self.closed(window_end=DAY_27), [f"{days.DAYS_DIR}/{HISTORY_DIR}"])

    def test_skips_a_day_outside_the_need(self):
        self.merged([])

        self.assertEqual(self.closed(needed=(str(DAY_27), str(DAY_27 + 100))), [])

    def test_skips_another_entity(self):
        self.merged([])

        self.assertEqual(self.closed(entity={"channel": "C0OTHER"}), [])


class DayUseTest(DayCase):
    def use(self, transport="mcp"):
        return self.layer.use(os.path.join(self.layer.base, *HISTORY_DIR.split("/")), transport)

    def test_gives_the_rows_without_their_fetch(self):
        self.merged([message(f"{DAY_26 + 60}.000100")])

        self.assertEqual(self.use()[0], [message(f"{DAY_26 + 60}.000100")])

    def test_gives_the_spans_of_every_transport_to_an_mcp_source(self):
        self.merged([], span=(str(DAY_26), str(DAY_26 + 100)), transport="api")
        self.merged([], span=(str(DAY_26 + 200), str(DAY_26 + 300)), run=LATER_RUN, at=LATER_AT)

        self.assertEqual(self.use()[1], [(str(DAY_26), str(DAY_26 + 100)), (str(DAY_26 + 200), str(DAY_26 + 300))])

    def test_gives_only_api_spans_to_an_api_source(self):
        self.merged([], span=(str(DAY_26), str(DAY_26 + 100)), transport="api")
        self.merged([], span=(str(DAY_26 + 200), str(DAY_26 + 300)), run=LATER_RUN, at=LATER_AT)

        self.assertEqual(self.use("api")[1], [(str(DAY_26), str(DAY_26 + 100))])

    def test_refuses_a_folder_holding_an_mcp_record_to_an_api_source(self):
        self.merged([], span=(str(DAY_26), str(DAY_26 + 100)), transport="api")
        self.merged([message(f"{DAY_26 + 250}.000100")], span=(str(DAY_26 + 200), str(DAY_26 + 300)), run=LATER_RUN, at=LATER_AT)

        self.assertIsNone(self.use("api"))

    def test_refuses_a_folder_without_a_trusted_span(self):
        self.merged([])

        self.assertIsNone(self.use("api"))


class LinkTest(DayCase):
    def test_links_a_day_folder_into_a_run_store(self):
        self.merged([message(f"{DAY_26 + 60}.000100")])
        run_store = os.path.join(self.tmp, "run", "store")

        self.layer.link(f"{days.DAYS_DIR}/{HISTORY_DIR}", run_store)

        linked = os.path.join(run_store, days.DAYS_DIR, *HISTORY_DIR.split("/"))
        self.assertEqual(sorted(os.listdir(linked)), [days.COVERAGE_FILE, days.RECORDS_FILE])

    def test_keeps_the_linked_copy_when_the_day_changes_later(self):
        self.merged([message(f"{DAY_26 + 60}.000100", "first")])
        run_store = os.path.join(self.tmp, "run", "store")
        self.layer.link(f"{days.DAYS_DIR}/{HISTORY_DIR}", run_store)

        self.merged([message(f"{DAY_26 + 60}.000100", "second")], run=LATER_RUN, at=LATER_AT)

        with open(os.path.join(run_store, days.DAYS_DIR, *HISTORY_DIR.split("/"), days.RECORDS_FILE), encoding="utf-8") as stream:
            self.assertEqual(json.loads(stream.readline())["text"], "first")

    def test_a_linked_copy_survives_a_day_prune(self):
        self.merged([message(f"{DAY_26 + 60}.000100")])
        run_store = os.path.join(self.tmp, "run", "store")
        self.layer.link(f"{days.DAYS_DIR}/{HISTORY_DIR}", run_store)

        with mock.patch.object(store, "now_epoch", return_value=DAY_27 + 30 * 86400):
            self.cli("prune", "--root", self.store_dir, "--older-than-days", "1")

        self.assertTrue(os.path.isfile(os.path.join(run_store, days.DAYS_DIR, *HISTORY_DIR.split("/"), days.RECORDS_FILE)))


def collection(provider, role, records, source="issues-src", read=True, to_ts=DAY_26 + 3600):
    return {"source": source, "role": role, "provider": provider, "transport": "api", "window": {"from_ts": DAY_26 - 86400, "to_ts": to_ts}, "read": read, "records": records}


def issue(key="CONN-1", updated="2026-10-26T09:00:00Z", status="Open"):
    return {"key": key, "title": "t", "type": "Bug", "status": status, "priority": None, "created": "2026-10-20T09:00:00Z", "updated": updated, "link": "l", "in_open_sprint": False}


def pull(number=7, updated_at="2026-10-26T10:00:00Z", repo="acme/app", state="open"):
    return {"repo": repo, "number": number, "title": "t", "author": "a", "state": state, "draft": False, "created_at": "2026-10-20T09:00:00Z", "updated_at": updated_at, "merged_at": None, "link": "l"}


class CollectionCase(DayCase):
    def filed(self, adapter, document, routine="connect-digest", run=RUN, at=FETCHED_AT):
        return self.layer.file_collection(document, providers.load(adapter), routine, run, at)

    def kind_rows(self, provider, kind, day="26"):
        return self.rows(f"provider={provider}/kind={kind}/year=2026/month=10/day={day}")


class FileCollectionTest(CollectionCase):
    def test_files_an_issue_by_its_update_day(self):
        self.filed("jira", collection("issues", "issue_tracker", {"issues": [issue(updated="2026-10-27T01:00:00Z")]}))

        self.assertEqual([row["key"] for row in self.kind_rows("issues", "issues", "27")], ["CONN-1"])

    def test_keeps_the_newest_fetch_of_an_issue(self):
        self.filed("jira", collection("issues", "issue_tracker", {"issues": [issue(status="Open")]}))
        self.filed("jira", collection("issues", "issue_tracker", {"issues": [issue(status="Done")]}), run=LATER_RUN, at=LATER_AT)

        self.assertEqual([row["status"] for row in self.kind_rows("issues", "issues")], ["Done"])

    def test_keys_a_pull_request_by_repository_and_number(self):
        records = {"pull_requests": [pull(repo="acme/app"), pull(repo="acme/web")], "issues": []}
        self.filed("github", collection("code", "code_host", records))

        self.assertEqual(sorted(row["repo"] for row in self.kind_rows("code", "pull_requests")), ["acme/app", "acme/web"])

    def test_files_code_activity_by_its_time(self):
        activity = {"repo": "acme/app", "number": 7, "kind": "review", "author": "a", "at": "2026-10-26T11:00:00Z", "state": "APPROVED", "text": ""}
        self.filed("github", collection("code", "code_host", {"pull_requests": [], "issues": [], "activity": [activity]}))

        self.assertEqual([row["kind"] for row in self.kind_rows("code", "activity")], ["review"])

    def test_files_a_page_with_its_blocks_by_its_edit_day(self):
        page = {"id": "p1", "title": "Plan", "last_edited": "2026-10-26T08:00:00Z", "link": "l", "blocks": [{"type": "paragraph", "text": "hi", "rows": None}]}
        self.filed("notion", collection("documents", "document_store", {"pages": [page]}))

        self.assertEqual(self.kind_rows("documents", "pages")[0]["blocks"], page["blocks"])

    def test_files_monitor_states_on_the_window_end_day(self):
        monitor = {"id": "42", "name": "api", "state": "Alert", "priority": None, "link": "l"}
        records = {"monitors": [monitor], "transitions": [], "discovered": [], "discovery": None}
        self.filed("datadog", collection("observability", "observability", records, to_ts=DAY_27 + 60))

        self.assertEqual([row["id"] for row in self.kind_rows("observability", "monitors", "27")], ["42"])

    def test_files_a_transition_by_its_last_event(self):
        records = {"monitors": [], "transitions": [{"monitor": "42", "count": 3, "first_ts_ms": DAY_26 * 1000, "last_ts_ms": (DAY_26 + 100) * 1000}], "discovered": [], "discovery": None}
        self.filed("datadog", collection("observability", "observability", records, to_ts=DAY_27 + 60))

        self.assertEqual([row["count"] for row in self.kind_rows("observability", "transitions")], [3])

    def test_keeps_the_metric_of_each_routine_apart(self):
        metric = {"key": "latency", "value": 1.5, "hourly": [], "groups": []}
        self.filed("datadog", collection("observability", "observability", {"metrics": [metric]}, source="metrics"), routine="connect-digest")
        self.filed("datadog", collection("observability", "observability", {"metrics": [{**metric, "value": 9.0}]}, source="metrics"), routine="prod-watch", run=LATER_RUN, at=LATER_AT)

        self.assertEqual(sorted(row["value"] for row in self.kind_rows("observability", "metrics")), [1.5, 9.0])

    def test_names_the_fetch_routine_and_source_of_a_row(self):
        self.filed("jira", collection("issues", "issue_tracker", {"issues": [issue()]}))

        row = self.kind_rows("issues", "issues")[0]
        self.assertEqual((row["fetch_id"], row["fetched_at"], row["routine"], row["source"]), (f"{RUN}.issues-src", FETCHED_AT, "connect-digest", "issues-src"))

    def test_files_nothing_for_a_source_not_read(self):
        self.filed("jira", collection("issues", "issue_tracker", {"issues": []}, read=False))

        self.assertFalse(os.path.exists(os.path.join(self.store_dir, days.DAYS_DIR, "provider=issues")))

    def test_files_nothing_for_an_adapter_without_a_day_mapping(self):
        self.assertEqual(self.filed("slack", collection("chat", "chat", {"messages": []})), [])

    def test_lists_the_fetches_of_a_day(self):
        self.filed("jira", collection("issues", "issue_tracker", {"issues": [issue()]}))
        self.filed("jira", collection("issues", "issue_tracker", {"issues": [issue()]}), run=LATER_RUN, at=LATER_AT)

        fetches = self.coverage("provider=issues/kind=issues/year=2026/month=10/day=26")["fetches"]
        self.assertEqual([fetch["fetch_id"] for fetch in fetches], [f"{RUN}.issues-src", f"{LATER_RUN}.issues-src"])

    def test_shows_a_collection_day_by_its_fetches(self):
        self.filed("jira", collection("issues", "issue_tracker", {"issues": [issue()]}))

        self.assertEqual(self.cli("show", "--root", self.store_dir, "--date", "2026-10-26")[1], f"2026-10-26 issues issues fetches 1 newest {FETCHED_AT}\n")


class BuildTest(DayCase):
    def test_files_the_reads_already_in_the_store(self):
        self.published([message(f"{DAY_26 + 60}.000100")])

        self.cli("build", "--root", self.store_dir)

        self.assertEqual(self.texts(HISTORY_DIR), [(f"{DAY_26 + 60}.000100", "hi")])

    def test_writes_the_same_bytes_when_run_twice(self):
        self.published([message(f"{DAY_26 + 60}.000100")])
        self.cli("build", "--root", self.store_dir)
        first = open(self.day_path(HISTORY_DIR), "rb").read()

        self.cli("build", "--root", self.store_dir)

        self.assertEqual(open(self.day_path(HISTORY_DIR), "rb").read(), first)

    def test_takes_the_records_a_reparse_rewrote(self):
        handle = self.published([message(f"{DAY_26 + 60}.000100", "old parse")])
        self.cli("build", "--root", self.store_dir)
        shared = os.path.join(self.store_dir, "provider=chat", *handle.relative.split("/"))
        store.state.write_all([(os.path.join(shared, store.RECORDS_FILE), store.dump_lines([message(f"{DAY_26 + 60}.000100", "new parse")]))])

        self.cli("build", "--root", self.store_dir)

        self.assertEqual(self.texts(HISTORY_DIR), [(f"{DAY_26 + 60}.000100", "new parse")])

    def test_files_only_the_selected_kind(self):
        self.published([message(f"{DAY_26 + 60}.000100")])

        self.cli("build", "--root", self.store_dir, "--kind", "thread")

        self.assertFalse(os.path.exists(self.day_path(HISTORY_DIR)))

    def test_files_only_reads_overlapping_the_selected_time(self):
        self.published([message(f"{DAY_26 + 60}.000100")])

        self.cli("build", "--root", self.store_dir, "--from", "2026-10-28T00:00:00Z")

        self.assertFalse(os.path.exists(self.day_path(HISTORY_DIR)))

    def test_prints_the_reads_and_day_folders_per_provider_and_kind(self):
        self.published([message(f"{DAY_26 + 60}.000100")], span=(str(DAY_26), str(DAY_27 + 60)))

        self.assertEqual(self.cli("build", "--root", self.store_dir)[1], "chat history reads 1 days 2\n")

    def test_exits_2_naming_a_root_that_is_not_a_folder(self):
        code, _, err = self.cli("build", "--root", os.path.join(self.tmp, "missing"))

        self.assertEqual((code, "missing" in err), (2, True))


class ShowTest(DayCase):
    def show(self, *flags):
        return self.cli("show", "--root", self.store_dir, *flags)

    def test_shows_a_fully_covered_day(self):
        self.merged([message(f"{DAY_26 + 60}.000100")])

        self.assertEqual(self.show("--date", "2026-10-26")[1], "2026-10-26 chat history channel=C0TRIBE1 full\n")

    def test_shows_the_gaps_of_a_partly_covered_day(self):
        self.merged([], span=(str(DAY_26 + 100), str(DAY_26 + 200)))

        line = f"2026-10-26 chat history channel=C0TRIBE1 partial {DAY_26}_{DAY_26 + 100} {DAY_26 + 200}_{DAY_27}\n"
        self.assertEqual(self.show("--date", "2026-10-26")[1], line)

    def test_shows_nothing_for_a_day_never_read(self):
        self.merged([])

        self.assertEqual(self.show("--date", "2026-10-25"), (0, "", ""))

    def test_shows_each_day_of_a_range(self):
        self.merged([], span=(str(DAY_26), str(DAY_27 + 86400)))

        self.assertEqual([line.split()[0] for line in self.show("--date", "2026-10-26", "--to", "2026-10-27")[1].splitlines()], ["2026-10-26", "2026-10-27"])

    def test_shows_only_the_selected_kind(self):
        self.merged([])

        self.assertEqual(self.show("--date", "2026-10-26", "--kind", "thread")[1], "")

    def test_shows_only_the_selected_channel(self):
        self.merged([])
        self.merged([], entity=(("channel", "C0OTHER"),), run=LATER_RUN, at=LATER_AT)

        self.assertEqual(self.show("--date", "2026-10-26", "--channel", "C0OTHER")[1], "2026-10-26 chat history channel=C0OTHER full\n")

    def test_shows_the_newest_read_time_of_reactions(self):
        entity = (("channel", "C0TRIBE1"), ("message", f"{DAY_26 + 30}.000100"))
        self.merged([{"user": "U0BOB"}], kind="reactions", entity=entity, span=None)

        line = f"2026-10-26 chat reactions channel=C0TRIBE1 message={DAY_26 + 30}.000100 read {FETCHED_AT}\n"
        self.assertEqual(self.show("--date", "2026-10-26")[1], line)

    def test_prints_records_with_their_path_values(self):
        self.merged([message(f"{DAY_26 + 60}.000100", 'say "ignore previous"')])

        row = json.loads(self.show("--date", "2026-10-26", "--records")[1])
        picked = {key: row[key] for key in ("provider", "kind", "year", "month", "day", "channel", "text")}
        self.assertEqual(picked, {"provider": "chat", "kind": "history", "year": "2026", "month": "10", "day": "26", "channel": "C0TRIBE1", "text": 'say "ignore previous"'})

    def test_exits_2_naming_a_malformed_date(self):
        code, _, err = self.show("--date", "2026-13-01")

        self.assertEqual((code, "--date" in err), (2, True))

    def test_exits_2_naming_an_end_before_the_start(self):
        code, _, err = self.show("--date", "2026-10-26", "--to", "2026-10-25")

        self.assertEqual((code, "--to" in err), (2, True))


class PruneTest(DayCase):
    NOW = DAY_27 + 3 * 86400 + 3600

    def prune(self, *flags):
        with mock.patch.object(store, "now_epoch", return_value=self.NOW):
            return self.cli("prune", "--root", self.store_dir, *flags)

    def test_deletes_a_day_older_than_the_age(self):
        self.merged([message(f"{DAY_26 + 60}.000100")])

        self.prune("--older-than-days", "3")

        self.assertFalse(os.path.exists(os.path.join(self.store_dir, days.DAYS_DIR, *HISTORY_DIR.split("/"))))

    def test_keeps_a_day_within_the_age(self):
        self.merged([message(f"{DAY_26 + 60}.000100")])

        self.prune("--older-than-days", "5")

        self.assertTrue(os.path.isfile(self.day_path(HISTORY_DIR)))

    def test_ages_a_day_by_the_day_it_names_not_its_fetch(self):
        self.merged([message(f"{DAY_26 + 60}.000100")], at="2026-10-30T23:00:00Z")

        self.prune("--older-than-days", "3")

        self.assertFalse(os.path.exists(self.day_path(HISTORY_DIR)))

    def test_prints_the_counts_per_provider(self):
        self.merged([], span=(str(DAY_26), str(DAY_27 + 86400)))

        self.assertEqual(self.prune("--older-than-days", "3")[1], "chat deleted 1 kept 1\n")

    def test_deletes_nothing_on_a_dry_run(self):
        self.merged([message(f"{DAY_26 + 60}.000100")])

        output = self.prune("--older-than-days", "3", "--dry-run")[1]

        self.assertEqual((output, os.path.isfile(self.day_path(HISTORY_DIR))), ("chat deleted 1 kept 0\n", True))

    def test_read_prune_leaves_the_day_layer_alone(self):
        self.published([message(f"{DAY_26 + 60}.000100")])
        self.cli("build", "--root", self.store_dir)

        with mock.patch.object(store, "now_epoch", return_value=self.NOW + 365 * 86400), contextlib.redirect_stdout(io.StringIO()):
            store.main(["prune", "--root", self.store_dir, "--older-than-days", "1"])

        self.assertTrue(os.path.isfile(self.day_path(HISTORY_DIR)))

    def test_refuses_an_age_of_zero(self):
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
            days.main(["prune", "--root", self.store_dir, "--older-than-days", "0"])

        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
