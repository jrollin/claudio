import contextlib
import errno
import io
import json
import os
import pathlib
import shutil
import socket
import stat
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from unittest import mock

import days
import state
import store
from providers import slack

FIXTURES = pathlib.Path(__file__).parent / "providers" / "fixtures" / "slack"
ROOT_TS = "1760002000.000200"
WINDOW_SPAN = ("1760000500.000050", "1760010800")

RUN = "20261020T073004Z-z1x7pc"
OTHER_RUN = "20261019T120003Z-p8m1za"
FETCHED_AT = "2026-10-20T07:30:09Z"
FETCHED_EPOCH = int(datetime(2026, 10, 20, 7, 30, 9, tzinfo=timezone.utc).timestamp())
WINDOW_END = FETCHED_EPOCH + 600
HISTORY = (("channel", "C0TRIBE1"),)
THREAD = (("channel", "C0TRIBE1"), ("root", "1792394100.000200"))
SPAN = ("1792394810.000400", "1792481400")
REQUEST = {"tool": "slack_read_channel", "arguments": {"channel_id": "C0TRIBE1", "limit": 30}}
NEXT_REQUEST = {"tool": "slack_read_channel", "arguments": {"channel_id": "C0TRIBE1", "cursor": "c2", "limit": 30}}
RECORDS = [
    {"ts": "1792394810.000400", "author": "U0BOB", "text": "Release notes", "thread_ts": None, "name": "", "bot": False},
    {"ts": "1792400000.000100", "author": "U0CAROL", "text": "Done", "thread_ts": None, "name": "", "bot": False},
]


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "store")
        self.shared = os.path.join(self.tmp.name, "shared")

    def session(self, source="channels", transport="mcp", run=RUN, shared=None, provider="chat", root=None):
        return store.ReadSession(
            root or self.root, provider, run, source, "slack", transport, clock=lambda: FETCHED_AT, runtime="ab" * 20, shared=shared
        )

    def finished(self, session, entity=HISTORY, span=SPAN, records=RECORDS, kind="history"):
        handle = session.open(kind, entity, span)
        handle.page(REQUEST, fetch=lambda: b"page one")
        handle.finish("complete", None, records)
        return handle

    def read_json(self, handle):
        with open(os.path.join(handle.folder, store.READ_FILE), encoding="utf-8") as stream:
            return json.load(stream)


class FolderNameTest(StoreCase):
    def test_names_a_spanned_read_with_hive_folders(self):
        handle = self.session().open("history", HISTORY, SPAN)

        self.assertEqual(
            handle.relative,
            "kind=history/channel=C0TRIBE1/read=1792394810.000400_1792481400-20261020T073004Z-z1x7pc.channels",
        )

    def test_places_the_read_under_its_provider_key(self):
        handle = self.session().open("thread", THREAD, SPAN)

        self.assertEqual(
            os.path.relpath(handle.folder, self.root),
            "provider=chat/kind=thread/channel=C0TRIBE1/root=1792394100.000200/"
            "read=1792394810.000400_1792481400-20261020T073004Z-z1x7pc.channels",
        )

    def test_names_a_read_without_span_by_its_fetch_id(self):
        handle = self.session().open("members", (("channel", "D0DM1"),), None)

        self.assertEqual(handle.relative, "kind=members/channel=D0DM1/read=20261020T073004Z-z1x7pc.channels")

    def test_gives_two_sources_of_one_run_two_folders_for_the_same_read(self):
        first = self.session("channels").open("history", HISTORY, SPAN)
        second = self.session("chat").open("history", HISTORY, SPAN)

        self.assertNotEqual(first.folder, second.folder)

    def test_refuses_a_value_that_would_leave_its_folder(self):
        for value in ("..", ".", "a/b", "", "a\x00b"):
            with self.subTest(value=value), self.assertRaises(state.Rejected):
                self.session().open("history", (("channel", value),), SPAN)

    def test_refuses_a_key_that_is_not_lowercase_words(self):
        for key in ("Channel", "chan-nel", "", "a=b"):
            with self.subTest(key=key), self.assertRaises(state.Rejected):
                self.session().open("history", ((key, "C0TRIBE1"),), SPAN)

    def test_never_names_the_refused_value(self):
        with self.assertRaises(state.Rejected) as caught:
            self.session().open("history", (("channel", "../secret"),), SPAN)

        self.assertNotIn("secret", str(caught.exception))

    def test_refuses_a_span_bound_that_is_not_a_ts(self):
        with self.assertRaises(state.Rejected):
            self.session().open("history", HISTORY, ("1792394810.000400", "../x"))


class PageTest(StoreCase):
    def test_fetches_and_saves_a_missing_page(self):
        handle = self.session().open("history", HISTORY, SPAN)

        data = handle.page(REQUEST, fetch=lambda: b"page one")

        self.assertEqual(data, b"page one")
        with open(os.path.join(handle.folder, "page-001.txt"), "rb") as stream:
            self.assertEqual(stream.read(), b"page one")

    def test_saves_an_api_page_as_json(self):
        handle = self.session(transport="api").open("history", HISTORY, SPAN)

        handle.page({"method": "GET", "path": "/api/conversations.history", "query": "", "body": None}, fetch=lambda: b"{}\n")

        self.assertTrue(os.path.exists(os.path.join(handle.folder, "page-001.json")))

    def test_serves_a_saved_page_to_a_later_walk_without_fetching(self):
        self.session().open("history", HISTORY, SPAN).page(REQUEST, fetch=lambda: b"page one")
        fetch = mock.Mock(return_value=b"other")

        data = self.session().open("history", HISTORY, SPAN).page(REQUEST, fetch=fetch)

        self.assertEqual((data, fetch.called), (b"page one", False))

    def test_raises_a_pending_call_naming_the_save_path_of_a_missing_page(self):
        handle = self.session().open("history", HISTORY, SPAN)
        handle.page(REQUEST, fetch=lambda: b"page one")

        with self.assertRaises(store.PagePending) as caught:
            handle.page(NEXT_REQUEST)

        pending = caught.exception
        self.assertEqual(
            (pending.call_id, pending.path, pending.request),
            (handle.relative + "/page-002", os.path.join(handle.folder, "page-002.txt"), NEXT_REQUEST),
        )

    def test_names_the_page_it_served_last(self):
        handle = self.session().open("history", HISTORY, SPAN)
        handle.page(REQUEST, fetch=lambda: b"one")
        handle.page(NEXT_REQUEST, fetch=lambda: b"two")

        self.assertEqual(handle.last_id, handle.relative + "/page-002")

    def test_numbers_pages_in_call_order(self):
        handle = self.session().open("history", HISTORY, SPAN)
        handle.page(REQUEST, fetch=lambda: b"one")
        handle.page(NEXT_REQUEST, fetch=lambda: b"two")
        handle.finish("complete", None, RECORDS)

        self.assertEqual(
            self.read_json(handle)["pages"],
            [{"file": "page-001.txt", "request": REQUEST}, {"file": "page-002.txt", "request": NEXT_REQUEST}],
        )


class PagePathTest(StoreCase):
    def test_maps_a_call_id_to_its_page_file(self):
        session = self.session()
        handle = session.open("history", HISTORY, SPAN)

        self.assertEqual(session.page_path(handle.relative + "/page-002"), os.path.join(handle.folder, "page-002.txt"))

    def test_refuses_a_call_id_that_leaves_the_store(self):
        for call_id in ("../escape/page-001", "kind=history/../../page-001", "kind=history//page-001", ""):
            with self.subTest(call_id=call_id), self.assertRaises(state.Rejected):
                self.session().page_path(call_id)

    def test_counts_the_pages_this_source_saved_in_the_run(self):
        session = self.session()
        handle = session.open("history", HISTORY, SPAN)
        handle.page(REQUEST, fetch=lambda: b"one")
        handle.page(NEXT_REQUEST, fetch=lambda: b"two")
        self.session("chat").open("history", HISTORY, SPAN).page(REQUEST, fetch=lambda: b"other source")

        self.assertEqual(session.saved_pages(), 2)


class PageGuardTest(StoreCase):
    def test_refuses_a_page_that_is_a_link(self):
        handle = self.session().open("history", HISTORY, SPAN)
        store.make_folders(handle.folder)
        target = os.path.join(self.tmp.name, "elsewhere.txt")
        with open(target, "wb") as stream:
            stream.write(b"secret")
        os.symlink(target, os.path.join(handle.folder, "page-001.txt"))

        with self.assertRaises(store.SourceUnreadable) as caught:
            handle.page(REQUEST)

        self.assertIn("is not a regular file", str(caught.exception))

    def test_cuts_a_read_at_a_page_over_the_size_cap(self):
        handle = self.session().open("history", HISTORY, SPAN)
        store.make_folders(handle.folder)
        with open(os.path.join(handle.folder, "page-001.txt"), "wb") as stream:
            stream.truncate(store.BODY_CAP + 1)

        with self.assertRaises(store.PartialRead):
            handle.page(REQUEST)


class FinishTest(StoreCase):
    def test_writes_one_canonical_line_per_record(self):
        handle = self.finished(self.session())

        with open(os.path.join(handle.folder, store.RECORDS_FILE), "rb") as stream:
            lines = stream.read().decode("utf-8").splitlines()
        self.assertEqual(lines, [json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for record in RECORDS])

    def test_writes_the_read_document(self):
        handle = self.finished(self.session())

        self.assertEqual(
            self.read_json(handle),
            {
                "adapter": "slack",
                "entity": {"channel": "C0TRIBE1"},
                "fetched_at": FETCHED_AT,
                "kind": "history",
                "outcome": {"reason": None, "status": "complete"},
                "pages": [{"file": "page-001.txt", "request": REQUEST}],
                "parsed_by": "ab" * 20,
                "provider": "chat",
                "run": RUN,
                "schema": 1,
                "source": "channels",
                "span": {"from": SPAN[0], "to": SPAN[1]},
                "transport": "mcp",
            },
        )

    def test_writes_the_read_document_canonically(self):
        handle = self.finished(self.session())

        with open(os.path.join(handle.folder, store.READ_FILE), "rb") as stream:
            raw = stream.read()
        self.assertEqual(raw, state.dump(json.loads(raw)))

    def test_writes_the_records_before_the_read_document(self):
        written = []
        real = state.write_all
        handle = self.session().open("history", HISTORY, SPAN)
        handle.page(REQUEST, fetch=lambda: b"page one")

        with mock.patch.object(state, "write_all", side_effect=lambda documents: (written.extend(os.path.basename(path) for path, _ in documents), real(documents))):
            handle.finish("complete", None, RECORDS)

        self.assertEqual(written, [store.RECORDS_FILE, store.READ_FILE])

    def test_leaves_no_read_document_when_the_records_cannot_be_written(self):
        handle = self.session().open("history", HISTORY, SPAN)
        handle.page(REQUEST, fetch=lambda: b"page one")

        with mock.patch.object(state, "write_all", side_effect=state.InputError("disk full")), self.assertRaises(state.InputError):
            handle.finish("complete", None, RECORDS)

        self.assertFalse(os.path.exists(os.path.join(handle.folder, store.READ_FILE)))

    def test_writes_no_records_for_a_failed_read(self):
        handle = self.session().open("history", HISTORY, SPAN)
        handle.page(REQUEST, fetch=lambda: b"not_in_channel")

        handle.finish("failed", "not_in_channel")

        self.assertEqual(
            (os.path.exists(os.path.join(handle.folder, store.RECORDS_FILE)), self.read_json(handle)["outcome"]),
            (False, {"reason": "not_in_channel", "status": "failed"}),
        )

    def test_writes_no_records_for_a_partial_read(self):
        handle = self.session().open("history", HISTORY, SPAN)
        handle.page(REQUEST, fetch=lambda: b"page one")

        handle.finish("partial", "partial: page cap")

        self.assertFalse(os.path.exists(os.path.join(handle.folder, store.RECORDS_FILE)))

    def test_refuses_an_unknown_outcome(self):
        handle = self.session().open("history", HISTORY, SPAN)

        with self.assertRaises(state.Rejected):
            handle.finish("done", None, RECORDS)

    def test_keeps_a_finished_read_as_written_when_a_later_walk_finishes_it_again(self):
        self.finished(self.session())
        later = store.ReadSession(self.root, "chat", RUN, "channels", "slack", "mcp", clock=lambda: "2026-10-20T08:00:00Z")
        handle = later.open("history", HISTORY, SPAN)
        handle.page(REQUEST, fetch=lambda: b"other")

        handle.finish("complete", None, [])

        self.assertEqual((self.read_json(handle)["fetched_at"], handle.records()), (FETCHED_AT, RECORDS))

    def test_writes_a_lone_surrogate_as_the_replacement_character(self):
        handle = self.finished(self.session(), records=[{"ts": "1.1", "text": "bad \ud800 text"}])

        with open(os.path.join(handle.folder, store.RECORDS_FILE), "rb") as stream:
            self.assertIn("bad � text".encode("utf-8"), stream.read())

    def test_reads_back_the_records_of_a_complete_read(self):
        handle = self.finished(self.session())

        self.assertEqual(self.session().open("history", HISTORY, SPAN).records(), RECORDS)

    def test_reads_back_no_record_of_an_empty_read(self):
        handle = self.finished(self.session(), records=[])

        self.assertEqual(handle.records(), [])

    def test_creates_every_folder_for_the_owner_only(self):
        handle = self.finished(self.session())

        folders = [self.root, os.path.join(self.root, "provider=chat"), os.path.join(self.root, "provider=chat", "kind=history"), handle.folder]
        self.assertEqual({stat.S_IMODE(os.stat(path).st_mode) for path in folders}, {0o700})

    def test_creates_every_file_for_the_owner_only(self):
        handle = self.finished(self.session())

        files = [os.path.join(handle.folder, name) for name in ("page-001.txt", store.RECORDS_FILE, store.READ_FILE)]
        self.assertEqual({stat.S_IMODE(os.stat(path).st_mode) for path in files}, {0o600})


class ListingTest(StoreCase):
    def test_lists_the_complete_reads_of_an_entity(self):
        self.finished(self.session())
        self.finished(self.session(run=OTHER_RUN), span=("1792308600", "1792394810.000400"))

        listed = self.session().reads("history", HISTORY)

        self.assertEqual(
            [(read.span, read.fetch_id) for read in listed],
            [(("1792308600", "1792394810.000400"), OTHER_RUN + ".channels"), (SPAN, RUN + ".channels")],
        )

    def test_skips_a_read_without_its_read_document(self):
        self.session().open("history", HISTORY, SPAN).page(REQUEST, fetch=lambda: b"page one")

        self.assertEqual(self.session().reads("history", HISTORY), [])

    def test_lists_nothing_for_an_entity_never_read(self):
        self.assertEqual(self.session().reads("history", (("channel", "C0NEVER"),)), [])

    def test_lists_a_read_without_span(self):
        handle = self.session().open("members", (("channel", "D0DM1"),), None)
        handle.page(REQUEST, fetch=lambda: b"members")
        handle.finish("complete", None, [{"id": "U1", "name": "Alice"}])

        listed = self.session().reads("members", (("channel", "D0DM1"),))

        self.assertEqual([(read.span, read.fetch_id, read.document["outcome"]["status"]) for read in listed], [(None, RUN + ".channels", "complete")])


class ReplaySessionTest(StoreCase):
    def replay(self, reads=None, transport="mcp"):
        recorded = ["provider=chat/" + self.session(transport=transport).open("history", HISTORY, SPAN).relative] if reads is None else reads
        return store.ReplaySession(self.root, "chat", RUN, "channels", "slack", transport, recorded)

    def test_serves_the_pages_of_a_read_the_run_made(self):
        self.finished(self.session())

        self.assertEqual(self.replay().open("history", HISTORY, SPAN).page(REQUEST), b"page one")

    def test_refuses_a_read_the_run_did_not_make(self):
        with self.assertRaises(store.ReplayMismatch) as caught:
            self.replay(reads=[]).open("history", HISTORY, SPAN)

        self.assertIn("kind=history/channel=C0TRIBE1/read=", str(caught.exception))

    def test_refuses_a_request_that_differs_from_its_record(self):
        self.finished(self.session())

        with self.assertRaises(store.ReplayMismatch) as caught:
            self.replay().open("history", HISTORY, SPAN).page({**REQUEST, "arguments": {**REQUEST["arguments"], "limit": 99}})

        self.assertTrue(str(caught.exception).endswith("call 1 slack_read_channel: request differs from its record in arguments"))

    def test_names_no_value_of_a_differing_request(self):
        self.finished(self.session())

        with self.assertRaises(store.ReplayMismatch) as caught:
            self.replay().open("history", HISTORY, SPAN).page({**REQUEST, "arguments": {"channel_id": "C0SECRET"}})

        self.assertNotIn("C0SECRET", str(caught.exception))

    def test_refuses_a_call_past_the_last_recorded_page(self):
        handle = self.replay().open("history", HISTORY, SPAN)
        self.finished(self.session())
        handle.page(REQUEST)

        with self.assertRaises(store.ReplayMismatch) as caught:
            handle.page(NEXT_REQUEST)

        self.assertIn("call 2 slack_read_channel: no record, 1 recorded", str(caught.exception))

    def test_names_the_method_and_path_of_an_api_call(self):
        request = {"method": "GET", "path": "/api/conversations.history", "query": "limit=200", "body": None}
        handle = self.session(transport="api").open("history", HISTORY, SPAN)
        handle.page(request, fetch=lambda: b"{}")
        handle.finish("complete", None, [])

        with self.assertRaises(store.ReplayMismatch) as caught:
            self.replay(transport="api").open("history", HISTORY, SPAN).page({**request, "query": "limit=1"})

        self.assertIn("call 1 GET /api/conversations.history: request differs from its record in query", str(caught.exception))

    def test_leaves_a_missing_page_of_an_unfinished_read_pending(self):
        self.session().open("history", HISTORY, SPAN).page(REQUEST, fetch=lambda: b"page one")
        handle = self.replay().open("history", HISTORY, SPAN)
        handle.page(REQUEST)

        with self.assertRaises(store.PagePending):
            handle.page(NEXT_REQUEST)

    def test_writes_nothing_into_the_run(self):
        self.session().open("history", HISTORY, SPAN).page(REQUEST, fetch=lambda: b"page one")
        handle = self.replay().open("history", HISTORY, SPAN)
        handle.page(REQUEST)

        handle.finish("complete", None, RECORDS)

        self.assertFalse(handle.done())


class CountTest(StoreCase):
    def test_counts_the_reads_this_source_opened(self):
        session = self.session()
        self.finished(session)
        self.finished(session, entity=THREAD, kind="thread")

        self.assertEqual(session.counts(), {"fetched": 2, "reused": 0})

    def test_counts_a_read_opened_twice_in_one_walk_once(self):
        session = self.session()
        self.finished(session)
        self.finished(session)

        self.assertEqual((session.counts(), session.used()), ({"fetched": 1, "reused": 0}, ["provider=chat/" + self.session().open("history", HISTORY, SPAN).relative]))


class ManifestTest(StoreCase):
    def manifest(self):
        with open(os.path.join(self.tmp.name, store.MANIFEST_FILE), encoding="utf-8") as stream:
            return json.load(stream)

    def test_writes_the_reads_of_a_source(self):
        session = self.session()
        handle = self.finished(session)

        store.write_manifest(self.tmp.name, "channels", session)

        self.assertEqual(
            self.manifest(),
            {"schema": 1, "sources": {"channels": {"fetched": 1, "reads": ["provider=chat/" + handle.relative], "reused": 0}}},
        )

    def test_keeps_the_other_sources_of_the_run(self):
        first, second = self.session("channels"), self.session("chat")
        self.finished(first)
        self.finished(second, entity=THREAD, kind="thread")

        store.write_manifest(self.tmp.name, "channels", first)
        store.write_manifest(self.tmp.name, "chat", second)

        self.assertEqual(sorted(self.manifest()["sources"]), ["channels", "chat"])

    def test_replaces_the_entry_of_a_source_written_again(self):
        session = self.session()
        self.finished(session)
        store.write_manifest(self.tmp.name, "channels", session)
        again = self.session()

        store.write_manifest(self.tmp.name, "channels", again)

        self.assertEqual(self.manifest()["sources"]["channels"], {"fetched": 0, "reads": [], "reused": 0})

    def test_writes_the_manifest_canonically(self):
        session = self.session()
        self.finished(session)

        store.write_manifest(self.tmp.name, "channels", session)

        with open(os.path.join(self.tmp.name, store.MANIFEST_FILE), "rb") as stream:
            raw = stream.read()
        self.assertEqual(raw, state.dump(json.loads(raw)))

    def test_refuses_a_manifest_that_is_not_one(self):
        with open(os.path.join(self.tmp.name, store.MANIFEST_FILE), "w", encoding="utf-8") as stream:
            stream.write('{"schema": 1, "sources": []}')

        with self.assertRaises(state.Rejected):
            store.write_manifest(self.tmp.name, "channels", self.session())


class ReparseTest(StoreCase):
    def write_read(self, kind, entity, span, tool, fixtures):
        session = store.ReadSession(self.root, "chat", RUN, "channels", "slack", "mcp", clock=lambda: FETCHED_AT, runtime="ab" * 20)
        handle = session.open(kind, entity, span)
        pages = [(FIXTURES / name).read_bytes() for name in fixtures]
        for number, data in enumerate(pages):
            handle.page({"tool": tool, "arguments": {"page": number}}, fetch=lambda data=data: data)
        handle.finish("complete", None, [])
        rows = slack.to_rows(kind, slack.parse_read(kind, handle.document(), pages))
        state.write_all([(os.path.join(handle.folder, store.RECORDS_FILE), store.dump_lines(rows))])
        return handle

    def history(self, channel="CHAN1", fixtures=("read_chan1_page_1.json", "read_chan1_page_2.json"), span=WINDOW_SPAN):
        return self.write_read("history", (("channel", channel),), span, "slack_read_channel", fixtures)

    def thread(self):
        return self.write_read("thread", (("channel", "CHAN1"), ("root", ROOT_TS)), (ROOT_TS, WINDOW_SPAN[1]), "slack_read_thread", ("thread_chan1_page_1.json", "thread_chan1_page_2.json"))

    def reparse(self, *filters):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(store, "runtime_commit", return_value="ab" * 20):
            code = store.main(["reparse", "--root", self.root, *filters])
        return code, out.getvalue().splitlines(), err.getvalue()

    def files(self, handle):
        return {name: (pathlib.Path(handle.folder) / name).read_bytes() for name in (store.RECORDS_FILE, store.READ_FILE)}

    def test_changes_no_byte_with_an_unchanged_parser(self):
        handle = self.history()
        before = self.files(handle)

        self.reparse()

        self.assertEqual(self.files(handle), before)

    def test_reports_a_read_whose_records_are_unchanged(self):
        handle = self.history()

        self.assertEqual(self.reparse(), (0, [f"same {handle.stored}", "reparsed 1, changed 0, rejected 0"], ""))

    def test_rewrites_and_reports_records_that_differ_from_the_pages(self):
        handle = self.history()
        expected = self.files(handle)[store.RECORDS_FILE]
        state.write_all([(os.path.join(handle.folder, store.RECORDS_FILE), b"{}\n")])

        code, lines, _ = self.reparse()

        self.assertEqual((code, lines[0], self.files(handle)[store.RECORDS_FILE]), (0, f"changed {handle.stored}", expected))

    def test_records_the_runtime_that_parsed_the_records(self):
        handle = self.history()
        document = handle.document()
        state.write_all([(os.path.join(handle.folder, store.READ_FILE), state.dump({**document, "parsed_by": "cd" * 20}))])

        self.reparse()

        self.assertEqual(handle.document()["parsed_by"], "ab" * 20)

    def test_selects_the_reads_of_a_channel(self):
        first, second = self.history(), self.history(channel="CHAN2", fixtures=("read_chan2.json",))

        _, lines, _ = self.reparse("--channel", "CHAN2")

        self.assertEqual(lines[:-1], [f"same {second.stored}"])

    def test_selects_the_reads_of_a_kind(self):
        self.history()
        thread = self.thread()

        _, lines, _ = self.reparse("--kind", "thread")

        self.assertEqual(lines[:-1], [f"same {thread.stored}"])

    def test_selects_the_reads_of_a_thread(self):
        self.history()
        thread = self.thread()

        _, lines, _ = self.reparse("--thread", f"CHAN1:{ROOT_TS}")

        self.assertEqual(lines[:-1], [f"same {thread.stored}"])

    def test_selects_the_reads_whose_span_overlaps_the_time_range(self):
        early = self.history(span=("1760000000", "1760001500"))
        self.history(channel="CHAN2", fixtures=("read_chan2.json",), span=("1760003500", "1760010800"))

        _, lines, _ = self.reparse("--from", "2025-10-09T09:00:00Z", "--to", "2025-10-09T09:30:00Z")

        self.assertEqual(lines[:-1], [f"same {early.stored}"])

    def test_selects_the_reads_of_a_provider(self):
        handle = self.history()

        self.assertEqual(self.reparse("--provider", "chat")[1][:-1], [f"same {handle.stored}"])

    def test_combines_the_filters(self):
        self.history()
        self.thread()

        code, _, err = self.reparse("--kind", "thread", "--channel", "CHAN2")

        self.assertEqual((code, "no read matches --channel CHAN2 --kind thread" in err), (2, True))

    def test_exits_2_when_no_read_matches(self):
        self.history()

        code, lines, err = self.reparse("--provider", "docs")

        self.assertEqual((code, lines, "no read matches --provider docs" in err), (2, [], True))

    def test_exits_3_on_a_rejected_read_and_still_reparses_the_others(self):
        broken, kept = self.history(), self.history(channel="CHAN2", fixtures=("read_chan2.json",))
        state.write_all([(os.path.join(broken.folder, "page-001.txt"), b"not json")])
        before = self.files(broken)

        code, lines, _ = self.reparse()

        self.assertEqual(
            (code, lines[0].startswith(f"rejected {broken.stored}: "), lines[1], lines[2], self.files(broken)),
            (3, True, f"same {kept.stored}", "reparsed 1, changed 0, rejected 1", before),
        )

    def test_skips_a_read_that_did_not_complete(self):
        session = self.session()
        handle = session.open("history", (("channel", "CHAN1"),), WINDOW_SPAN)
        handle.page(REQUEST, fetch=lambda: b"not_in_channel")
        handle.finish("failed", "not_in_channel")

        self.assertEqual(self.reparse()[0], 2)

    def test_reads_no_environment_and_opens_no_connection(self):
        handle = self.history()

        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(socket, "socket", side_effect=AssertionError("network")):
            code, lines, _ = self.reparse()

        self.assertEqual((code, lines[0]), (0, f"same {handle.stored}"))

    def test_exits_2_on_a_root_that_does_not_exist(self):
        code, _, err = self.reparse_root(os.path.join(self.tmp.name, "missing"))

        self.assertEqual((code, "missing" in err), (2, True))

    def reparse_root(self, root):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = store.main(["reparse", "--root", root])
        return code, None, err.getvalue()


def mode(path):
    return stat.S_IMODE(os.lstat(path).st_mode)


def folder_files(folder):
    return {name: pathlib.Path(folder, name).read_bytes() for name in sorted(os.listdir(folder))}


class SharedStoreCase(StoreCase):
    def sharing(self, run=RUN, provider="chat", root=None):
        return self.session(run=run, shared=self.shared, provider=provider, root=root)

    def shared_folder(self, handle, provider="chat"):
        return os.path.join(self.shared, f"provider={provider}", *handle.relative.split("/"))

    def incoming(self, provider="chat"):
        return os.path.join(self.shared, f"provider={provider}", store.INCOMING)


class DayHookTest(SharedStoreCase):
    def filing(self):
        return store.ReadSession(self.root, "chat", RUN, "channels", "slack", "mcp", clock=lambda: FETCHED_AT, shared=self.shared, days=days.DayLayer(self.shared))

    def test_files_a_published_read_by_day(self):
        self.finished(self.filing())

        self.assertTrue(os.path.isfile(os.path.join(self.shared, days.DAYS_DIR, "provider=chat", "kind=history", "year=2026", "month=10", "day=19", "channel=C0TRIBE1", days.RECORDS_FILE)))

    def test_files_nothing_by_day_without_a_day_layer(self):
        self.finished(self.sharing())

        self.assertFalse(os.path.exists(os.path.join(self.shared, days.DAYS_DIR)))

    def test_keeps_the_read_published_when_filing_by_day_fails(self):
        os.makedirs(self.shared)
        open(os.path.join(self.shared, days.DAYS_DIR), "w").close()
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            handle = self.finished(self.filing())

        self.assertEqual((os.path.isfile(os.path.join(self.shared_folder(handle), store.READ_FILE)), "days:" in stderr.getvalue()), (True, True))


class ClosedDaysTest(SharedStoreCase):
    DAY_19 = 1792368000
    DAY_SPAN = (str(DAY_19), str(DAY_19 + 86400))
    STORED_DAY = f"{days.DAYS_DIR}/provider=chat/kind=history/year=2026/month=10/day=19/channel=C0TRIBE1"
    NEEDED = (str(DAY_19 + 100), str(DAY_19 + 86400 + 100))
    WINDOW_END = DAY_19 + 2 * 86400

    def filing(self, run=OTHER_RUN, root=None):
        return store.ReadSession(
            root or os.path.join(self.tmp.name, "runs", run), "chat", run, "channels", "slack", "mcp", clock=lambda: FETCHED_AT, shared=self.shared, days=days.DayLayer(self.shared)
        )

    def earlier_read(self):
        self.finished(self.filing(), span=self.DAY_SPAN)

    def mine(self):
        return self.filing(run=RUN, root=self.root)

    def test_reuses_a_closed_day_another_run_filed(self):
        self.earlier_read()

        reused = self.mine().closed_days("history", HISTORY, self.NEEDED, self.WINDOW_END)

        self.assertEqual([(use.rows, use.spans) for use in reused], [(RECORDS, [self.DAY_SPAN])])

    def test_counts_a_reused_day_as_reused(self):
        self.earlier_read()
        session = self.mine()

        session.closed_days("history", HISTORY, self.NEEDED, self.WINDOW_END)

        self.assertEqual((session.used(), session.counts()), ([self.STORED_DAY], {"fetched": 0, "reused": 1}))

    def test_links_the_reused_day_into_the_run_store(self):
        self.earlier_read()

        self.mine().closed_days("history", HISTORY, self.NEEDED, self.WINDOW_END)

        self.assertTrue(os.path.isfile(os.path.join(self.root, *self.STORED_DAY.split("/"), days.RECORDS_FILE)))

    def test_reuses_nothing_without_a_day_layer(self):
        self.earlier_read()

        self.assertEqual(self.sharing().closed_days("history", HISTORY, self.NEEDED, self.WINDOW_END), [])

    def test_skips_a_day_its_own_publish_filed(self):
        session = self.mine()
        self.finished(session, span=self.DAY_SPAN)

        self.assertEqual(session.closed_days("history", HISTORY, self.NEEDED, self.WINDOW_END), [])

    def test_skips_a_day_its_own_publish_filed_in_an_earlier_process(self):
        self.finished(self.mine(), span=self.DAY_SPAN)

        self.assertEqual(self.mine().closed_days("history", HISTORY, self.NEEDED, self.WINDOW_END), [])

    def test_keeps_reusing_its_linked_copy_after_its_own_publish(self):
        self.earlier_read()
        session = self.mine()
        session.closed_days("history", HISTORY, self.NEEDED, self.WINDOW_END)
        self.finished(session, span=self.DAY_SPAN, records=[])

        self.assertEqual([use.rows for use in session.closed_days("history", HISTORY, self.NEEDED, self.WINDOW_END)], [RECORDS])

    def replaying(self, recorded):
        return store.ReplaySession(self.root, "chat", RUN, "channels", "slack", "mcp", recorded, days=days.DayLayer(self.root))

    def test_replay_reuses_the_recorded_copy(self):
        self.earlier_read()
        self.mine().closed_days("history", HISTORY, self.NEEDED, self.WINDOW_END)
        shutil.rmtree(self.shared)

        reused = self.replaying([self.STORED_DAY]).closed_days("history", HISTORY, self.NEEDED, self.WINDOW_END)

        self.assertEqual([use.rows for use in reused], [RECORDS])

    def test_replay_ignores_a_day_copy_the_run_did_not_record(self):
        self.earlier_read()
        self.mine().closed_days("history", HISTORY, self.NEEDED, self.WINDOW_END)

        self.assertEqual(self.replaying([]).closed_days("history", HISTORY, self.NEEDED, self.WINDOW_END), [])


class PublishTest(SharedStoreCase):
    def test_publishes_a_finished_read_to_the_shared_store(self):
        handle = self.finished(self.sharing())

        self.assertEqual(folder_files(self.shared_folder(handle)), folder_files(handle.folder))

    def test_publishes_a_failed_read_with_its_pages(self):
        handle = self.sharing().open("history", HISTORY, SPAN)
        handle.page(REQUEST, fetch=lambda: b"not_in_channel")
        handle.finish("failed", "not_in_channel")

        self.assertEqual(sorted(os.listdir(self.shared_folder(handle))), ["page-001.txt", store.READ_FILE])

    def test_writes_nothing_outside_the_run_store_without_a_shared_root(self):
        self.finished(self.session())

        self.assertFalse(os.path.exists(self.shared))

    def test_links_the_published_files_to_the_run_store_files(self):
        handle = self.finished(self.sharing())

        published = os.path.join(self.shared_folder(handle), store.RECORDS_FILE)
        self.assertTrue(os.path.samefile(published, os.path.join(handle.folder, store.RECORDS_FILE)))

    def test_creates_the_shared_folders_0700(self):
        handle = self.finished(self.sharing())

        modes = {mode(self.shared_folder(handle)), mode(os.path.join(self.shared, "provider=chat")), mode(self.incoming())}
        self.assertEqual(modes, {0o700})

    def test_leaves_no_staging_folder_behind(self):
        self.finished(self.sharing())

        self.assertEqual(os.listdir(self.incoming()), [])

    def test_publishes_a_read_once_when_its_walk_finishes_it_again(self):
        session = self.sharing()
        handle = self.finished(session)
        before = folder_files(self.shared_folder(handle))

        session.open("history", HISTORY, SPAN).finish("complete", None, [])

        self.assertEqual(folder_files(self.shared_folder(handle)), before)

    def test_publishes_a_read_finished_before_the_store_was_shared(self):
        handle = self.finished(self.session())

        self.sharing().open("history", HISTORY, SPAN).finish("complete", None, RECORDS)

        self.assertEqual(folder_files(self.shared_folder(handle)), folder_files(handle.folder))

    def test_never_lists_a_read_while_its_files_are_linked(self):
        session = self.sharing()
        seen = []
        real_link = os.link

        def watched_link(source, target):
            real_link(source, target)
            seen.append(len(list(store.walk_reads(self.shared))))

        with mock.patch.object(store.os, "link", watched_link):
            self.finished(session)

        self.assertEqual((seen, len(list(store.walk_reads(self.shared)))), ([0, 0, 0], 1))


class PublishFallbackTest(SharedStoreCase):
    def publish_failing_links(self, number):
        with mock.patch.object(store.os, "link", side_effect=OSError(number, os.strerror(number))):
            return self.finished(self.sharing())

    def test_copies_the_files_across_file_systems(self):
        handle = self.publish_failing_links(errno.EXDEV)

        self.assertEqual(folder_files(self.shared_folder(handle)), folder_files(handle.folder))

    def test_copies_the_files_where_links_are_not_permitted(self):
        handle = self.publish_failing_links(errno.EPERM)

        self.assertEqual(folder_files(self.shared_folder(handle)), folder_files(handle.folder))

    def test_writes_copied_files_0600(self):
        handle = self.publish_failing_links(errno.EXDEV)

        folder = self.shared_folder(handle)
        self.assertEqual({mode(os.path.join(folder, name)) for name in os.listdir(folder)}, {0o600})

    def test_fails_on_another_link_error_and_cleans_its_staging_folder(self):
        with self.assertRaises(state.InputError):
            self.publish_failing_links(errno.EACCES)

        self.assertEqual((os.listdir(self.incoming()), list(store.walk_reads(self.shared))), ([], []))


class ConcurrentPublishTest(SharedStoreCase):
    def test_two_sessions_publishing_at_once_both_land_complete(self):
        barrier = threading.Barrier(2)
        sessions = [self.sharing(run=RUN, root=os.path.join(self.tmp.name, "a")), self.sharing(run=OTHER_RUN, root=os.path.join(self.tmp.name, "b"))]
        failures = []

        def publish(session):
            try:
                handle = session.open("history", HISTORY, SPAN)
                handle.page(REQUEST, fetch=lambda: b"page one")
                barrier.wait()
                handle.finish("complete", None, RECORDS)
            except Exception as error:
                failures.append(error)

        threads = [threading.Thread(target=publish, args=(session,)) for session in sessions]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        listed = [(read.fetch_id, read.document["outcome"]["status"]) for read in self.sharing().shared_reads("history", HISTORY)]
        self.assertEqual((failures, sorted(listed)), ([], [(OTHER_RUN + ".channels", "complete"), (RUN + ".channels", "complete")]))

    def test_a_partial_staging_folder_is_never_listed(self):
        handle = self.finished(self.session())
        staging = os.path.join(self.incoming(), "read-partial")
        shutil.copytree(handle.folder, staging)

        listed = (list(store.walk_reads(self.shared)), self.sharing().shared_reads("history", HISTORY))
        self.assertEqual(listed, ([], []))


class LinkInTest(SharedStoreCase):
    def published(self):
        self.finished(self.sharing(run=OTHER_RUN, root=os.path.join(self.tmp.name, "other")))
        return self.sharing().shared_reads("history", HISTORY)[0]

    def test_links_a_shared_read_into_the_run_store(self):
        read = self.published()

        linked = self.sharing().link_in(read)

        self.assertEqual((linked.folder, folder_files(linked.folder)), (os.path.join(self.root, *read.stored.split("/")), folder_files(read.folder)))

    def test_counts_a_linked_read_as_reused(self):
        session = self.sharing()

        session.link_in(self.published())

        self.assertEqual(session.counts(), {"fetched": 0, "reused": 1})

    def test_lists_a_linked_read_among_the_reads_the_run_used(self):
        session = self.sharing()
        read = self.published()

        session.link_in(read)

        self.assertEqual(session.used(), [read.stored])

    def test_a_deletion_in_the_shared_store_leaves_the_linked_read_intact(self):
        session = self.sharing()
        read = self.published()
        linked = session.link_in(read)

        shutil.rmtree(read.folder)

        self.assertEqual(store.load_records(linked.folder), RECORDS)

    def test_completes_a_link_interrupted_before_its_read_document(self):
        read = self.published()
        target = os.path.join(self.root, *read.stored.split("/"))
        os.makedirs(target)
        os.link(os.path.join(read.folder, "page-001.txt"), os.path.join(target, "page-001.txt"))

        linked = self.sharing().link_in(read)

        self.assertEqual(folder_files(linked.folder), folder_files(read.folder))

    def test_refuses_a_page_name_that_leaves_the_read_folder(self):
        read = self.published()
        document = {**read.document, "pages": [{"file": "../escape.txt", "request": REQUEST}]}

        with self.assertRaises(state.Rejected):
            self.sharing().link_in(read._replace(document=document))


class ProviderIsolationTest(SharedStoreCase):
    def test_a_provider_key_never_lists_the_reads_of_another(self):
        self.finished(self.sharing(provider="chat"))

        listed = (len(self.sharing(provider="chat").shared_reads("history", HISTORY)), self.sharing(provider="chat_two").shared_reads("history", HISTORY))
        self.assertEqual(listed, (1, []))

    def test_lists_nothing_without_a_shared_root(self):
        self.finished(self.sharing())

        self.assertEqual(self.session().shared_reads("history", HISTORY), [])


class StoreDirCheckTest(StoreCase):
    LABEL = "places.local.store_dir"

    def refusal(self, path):
        with self.assertRaises(state.InputError) as caught:
            store.check_store_dir(path, self.LABEL)
        return str(caught.exception)

    def test_accepts_a_folder_that_does_not_exist_yet(self):
        self.assertIsNone(store.check_store_dir(os.path.join(self.tmp.name, "missing", "store"), self.LABEL))

    def test_accepts_an_own_folder(self):
        os.mkdir(self.shared, 0o700)

        self.assertIsNone(store.check_store_dir(self.shared, self.LABEL))

    def test_refuses_a_link(self):
        os.mkdir(self.shared, 0o700)
        linked = os.path.join(self.tmp.name, "linked")
        os.symlink(self.shared, linked)

        self.assertTrue(self.refusal(linked).startswith(self.LABEL + ": "))

    def test_refuses_a_file(self):
        pathlib.Path(self.shared).write_text("", encoding="utf-8")

        self.assertTrue(self.refusal(self.shared).startswith(self.LABEL + ": "))

    def test_refuses_another_users_folder(self):
        os.mkdir(self.shared, 0o700)

        with mock.patch.object(store.os, "getuid", return_value=os.getuid() + 1):
            self.assertTrue(self.refusal(self.shared).startswith(self.LABEL + ": "))

    def test_refuses_a_folder_inside_a_git_working_tree(self):
        repository = os.path.join(self.tmp.name, "repository")
        subprocess.run(["git", "init", "--quiet", repository], check=True)

        self.assertTrue(self.refusal(os.path.join(repository, "store", "chat")).startswith(self.LABEL + ": "))

    def ignoring(self, pattern):
        repository = os.path.join(self.tmp.name, "repository")
        subprocess.run(["git", "init", "--quiet", repository], check=True)
        pathlib.Path(repository, ".gitignore").write_text(pattern + "\n", encoding="utf-8")
        return repository

    def test_accepts_a_git_ignored_folder_inside_a_working_tree(self):
        repository = self.ignoring("store-local/")
        os.mkdir(os.path.join(repository, "store-local"), 0o700)

        self.assertIsNone(store.check_store_dir(os.path.join(repository, "store-local"), self.LABEL))

    def test_accepts_a_git_ignored_folder_that_does_not_exist_yet(self):
        repository = self.ignoring("store-local/")

        self.assertIsNone(store.check_store_dir(os.path.join(repository, "store-local"), self.LABEL))

    def test_refuses_a_folder_git_ignores_only_in_part(self):
        repository = self.ignoring("store-local/*.json")

        self.assertTrue(self.refusal(os.path.join(repository, "store-local")).startswith(self.LABEL + ": "))

    def test_never_shows_the_path_in_a_refusal(self):
        pathlib.Path(self.shared).write_text("", encoding="utf-8")

        self.assertNotIn(self.shared, self.refusal(self.shared))


class GapsTest(unittest.TestCase):
    NEEDED = ("1792394810.000400", "1792481400")

    def test_gives_the_needed_span_without_coverage(self):
        self.assertEqual(store.gaps(self.NEEDED, []), [self.NEEDED])

    def test_gives_nothing_for_a_covered_span(self):
        self.assertEqual(store.gaps(self.NEEDED, [("1792300000", "1792500000")]), [])

    def test_gives_the_tail_after_a_span_covering_the_start(self):
        self.assertEqual(store.gaps(self.NEEDED, [("1792394810.000400", "1792400000.5")]), [("1792400000.5", "1792481400")])

    def test_gives_nothing_for_adjacent_spans_covering_the_need(self):
        spans = [("1792394810.000400", "1792400000"), ("1792400000", "1792481400")]
        self.assertEqual(store.gaps(self.NEEDED, spans), [])

    def test_joins_overlapping_spans(self):
        spans = [("1792394000", "1792420000"), ("1792410000", "1792481400")]
        self.assertEqual(store.gaps(self.NEEDED, spans), [])

    def test_gives_the_hole_between_two_spans(self):
        spans = [("1792394810.000400", "1792400000"), ("1792450000", "1792481400")]
        self.assertEqual(store.gaps(self.NEEDED, spans), [("1792400000", "1792450000")])

    def test_ignores_a_span_outside_the_need(self):
        self.assertEqual(store.gaps(self.NEEDED, [("1792000000", "1792100000")]), [self.NEEDED])

    def test_gives_every_gap_in_ascending_order(self):
        spans = [("1792450000", "1792460000"), ("1792400000", "1792410000")]
        expected = [("1792394810.000400", "1792400000"), ("1792410000", "1792450000"), ("1792460000", "1792481400")]
        self.assertEqual(store.gaps(self.NEEDED, spans), expected)


class MergeNewestTest(unittest.TestCase):
    def test_keeps_the_record_of_the_newer_group_for_one_key(self):
        merged = store.merge_newest([[{"ts": "1.1", "text": "old"}], [{"ts": "1.1", "text": "new"}]], lambda record: record["ts"])
        self.assertEqual(merged, [{"ts": "1.1", "text": "new"}])

    def test_orders_the_records_by_ascending_key(self):
        merged = store.merge_newest([[{"ts": "10.5"}, {"ts": "9.9"}], [{"ts": "2.0"}]], lambda record: record["ts"])
        self.assertEqual([record["ts"] for record in merged], ["2.0", "9.9", "10.5"])


class EligibleCase(SharedStoreCase):
    def stored(self, run=OTHER_RUN, source="channels", transport="mcp", fetched_at=FETCHED_AT, status="complete", span=SPAN, runtime="ab" * 20):
        root = os.path.join(self.tmp.name, "runs", f"{run}-{source}")
        session = store.ReadSession(root, "chat", run, source, "slack", transport, clock=lambda: fetched_at, runtime=runtime, shared=self.shared)
        handle = session.open("history", HISTORY, span)
        handle.page(REQUEST, fetch=lambda: b"page one")
        handle.finish(status, None if status == "complete" else "why", RECORDS)
        return handle

    def mine(self, transport="mcp", run=RUN, source="channels", runtime="ab" * 20):
        return store.ReadSession(self.root, "chat", run, source, "slack", transport, clock=lambda: FETCHED_AT, runtime=runtime, shared=self.shared)

    def eligible(self, session=None, minutes=60, window_end=WINDOW_END, span=SPAN):
        return (session or self.mine()).eligible("history", HISTORY, span, minutes, window_end)

    def fetch_ids(self, reused):
        return [use.read.fetch_id for use in reused]


class EligibleTest(EligibleCase):
    def test_reuses_a_complete_read_fetched_within_max_age(self):
        self.stored()

        self.assertEqual([(use.read.fetch_id, use.rows) for use in self.eligible()], [(OTHER_RUN + ".channels", RECORDS)])

    def test_gives_the_span_of_a_reused_read(self):
        self.stored()

        self.assertEqual([use.spans for use in self.eligible()], [[SPAN]])

    def test_reuses_nothing_with_a_max_age_of_zero(self):
        self.stored()

        self.assertEqual(self.eligible(minutes=0), [])

    def test_ignores_a_read_older_than_max_age(self):
        self.stored()

        self.assertEqual(self.eligible(minutes=9), [])

    def test_reuses_a_read_exactly_max_age_old(self):
        self.stored()

        self.assertEqual(self.fetch_ids(self.eligible(minutes=10)), [OTHER_RUN + ".channels"])

    def test_ignores_a_read_another_run_fetched_after_the_window_end(self):
        self.stored()

        self.assertEqual(self.eligible(window_end=FETCHED_EPOCH - 1), [])

    def test_reuses_a_read_another_source_of_the_run_fetched_after_the_window_end(self):
        self.stored(run=RUN, source="digest")

        self.assertEqual(self.fetch_ids(self.eligible(window_end=FETCHED_EPOCH - 1)), [RUN + ".digest"])

    def test_an_api_source_skips_a_connector_read(self):
        self.stored(transport="mcp")

        self.assertEqual(self.eligible(self.mine(transport="api")), [])

    def test_an_api_source_reuses_an_api_read(self):
        self.stored(transport="api")

        self.assertEqual(self.fetch_ids(self.eligible(self.mine(transport="api"))), [OTHER_RUN + ".channels"])

    def test_a_connector_source_reuses_an_api_read(self):
        self.stored(transport="api")

        self.assertEqual(self.fetch_ids(self.eligible(self.mine(transport="mcp"))), [OTHER_RUN + ".channels"])

    def test_ignores_a_failed_read(self):
        self.stored(status="failed")

        self.assertEqual(self.eligible(), [])

    def test_ignores_a_partial_read(self):
        self.stored(status="partial")

        self.assertEqual(self.eligible(), [])

    def test_never_reuses_its_own_reads(self):
        session = self.mine()
        self.finished(session)

        self.assertEqual(self.eligible(session), [])

    def test_ignores_a_read_whose_span_lies_outside_the_need(self):
        self.stored(span=("1792000000", "1792100000"))

        self.assertEqual(self.eligible(), [])

    def test_orders_reused_reads_oldest_fetch_first(self):
        self.stored(run=OTHER_RUN, fetched_at="2026-10-20T07:30:09Z")
        self.stored(run="20261020T072000Z-a1b2c3", fetched_at="2026-10-20T07:25:00Z")

        self.assertEqual(self.fetch_ids(self.eligible()), ["20261020T072000Z-a1b2c3.channels", OTHER_RUN + ".channels"])

    def test_links_a_reused_read_into_the_run_store(self):
        handle = self.stored()

        reused = self.eligible()

        self.assertEqual(reused[0].read.folder, os.path.join(self.root, "provider=chat", *handle.relative.split("/")))

    def test_counts_a_reused_read(self):
        session = self.mine()
        self.stored()

        self.eligible(session)

        self.assertEqual(session.counts(), {"fetched": 0, "reused": 1})

    def test_reuses_a_read_of_another_source_in_the_run_store_without_a_shared_root(self):
        root = self.root
        other = store.ReadSession(root, "chat", RUN, "digest", "slack", "mcp", clock=lambda: FETCHED_AT, runtime="ab" * 20)
        self.finished(other)
        session = store.ReadSession(root, "chat", RUN, "channels", "slack", "mcp", clock=lambda: FETCHED_AT, runtime="ab" * 20)

        self.assertEqual(self.fetch_ids(self.eligible(session)), [RUN + ".digest"])


class EligibleReparseTest(EligibleCase):
    PAGES = ("read_chan1_page_1.json", "read_chan1_page_2.json")
    ENTITY = (("channel", "CHAN1"),)

    def stored_real(self, runtime, pages=PAGES):
        root = os.path.join(self.tmp.name, "runs", "other")
        session = store.ReadSession(root, "chat", OTHER_RUN, "channels", "slack", "mcp", clock=lambda: FETCHED_AT, runtime=runtime, shared=self.shared)
        handle = session.open("history", self.ENTITY, WINDOW_SPAN)
        data = [(FIXTURES / name).read_bytes() for name in pages]
        for number, page in enumerate(data):
            handle.page({"tool": "slack_read_channel", "arguments": {"page": number}}, fetch=lambda page=page: page)
        handle.finish("complete", None, [{"tampered": True}])
        return slack.to_rows("history", slack.parse_read("history", handle.document(), data))

    def reused_rows(self, runtime="ab" * 20):
        return [use.rows for use in self.mine(runtime=runtime).eligible("history", self.ENTITY, WINDOW_SPAN, 60, WINDOW_END)]

    def test_trusts_the_records_parsed_by_the_same_runtime(self):
        self.stored_real("ab" * 20)

        self.assertEqual(self.reused_rows(), [[{"tampered": True}]])

    def test_reparses_records_another_runtime_parsed(self):
        expected = self.stored_real("cd" * 20)

        self.assertEqual(self.reused_rows(), [expected])

    def test_reparses_records_of_an_unknown_runtime(self):
        expected = self.stored_real(None)

        self.assertEqual(self.reused_rows(), [expected])

    def test_skips_a_read_whose_pages_no_longer_parse(self):
        self.stored()
        handle_rows = self.mine(runtime="cd" * 20).eligible("history", HISTORY, SPAN, 60, WINDOW_END)

        self.assertEqual(handle_rows, [])


class ReplayEligibleTest(EligibleCase):
    def test_replays_only_the_reused_reads_the_run_recorded(self):
        recorded = self.stored(run=OTHER_RUN)
        self.eligible()
        self.stored(run="20261020T072000Z-a1b2c3", fetched_at="2026-10-20T07:25:00Z")
        self.mine().eligible("history", HISTORY, SPAN, 60, WINDOW_END)
        replay = store.ReplaySession(self.root, "chat", RUN, "channels", "slack", "mcp", ["provider=chat/" + recorded.relative], runtime="ab" * 20)

        reused = replay.eligible("history", HISTORY, SPAN, 60, WINDOW_END)

        self.assertEqual(self.fetch_ids(reused), [OTHER_RUN + ".channels"])


DAY = 86400
PRUNE_NOW = FETCHED_EPOCH + 10 * DAY
OLD_AT = "2026-10-20T07:30:09Z"
NEW_AT = "2026-10-29T07:30:09Z"


class PruneTest(SharedStoreCase):
    def stored_at(self, fetched_at, run=OTHER_RUN, provider="chat", span=SPAN):
        root = os.path.join(self.tmp.name, "runs", f"{run}-{provider}")
        session = store.ReadSession(root, provider, run, "channels", "slack", "mcp", clock=lambda: fetched_at, runtime="ab" * 20, shared=self.shared)
        return self.finished(session, span=span)

    def prune(self, *flags, days="5", root=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(store, "now_epoch", return_value=PRUNE_NOW):
            try:
                code = store.main(["prune", "--root", root or self.shared, "--older-than-days", days, *flags])
            except SystemExit as exit_:
                code = exit_.code
        return code, out.getvalue().splitlines(), err.getvalue()

    def fetch_ids(self):
        return sorted(read.fetch_id for read in store.walk_reads(self.shared))

    def aged(self, path, days):
        moment = PRUNE_NOW - days * DAY
        os.utime(path, (moment, moment))

    def test_deletes_the_reads_fetched_before_the_age(self):
        self.stored_at(OLD_AT, run=OTHER_RUN)
        self.stored_at(NEW_AT, run=RUN)

        self.prune()

        self.assertEqual(self.fetch_ids(), [RUN + ".channels"])

    def test_prints_the_counts_per_provider(self):
        self.stored_at(OLD_AT, run=OTHER_RUN, provider="chat")
        self.stored_at(NEW_AT, run=RUN, provider="chat")
        self.stored_at(NEW_AT, run=RUN, provider="chat_two")

        self.assertEqual(self.prune(), (0, ["chat deleted 1 kept 1", "chat_two deleted 0 kept 1"], ""))

    def test_a_dry_run_prints_the_counts_and_deletes_nothing(self):
        self.stored_at(OLD_AT, run=OTHER_RUN)
        self.stored_at(NEW_AT, run=RUN)

        code, lines, _ = self.prune("--dry-run")

        self.assertEqual((code, lines, self.fetch_ids()), (0, ["chat deleted 1 kept 1"], sorted([OTHER_RUN + ".channels", RUN + ".channels"])))

    def test_deletes_a_folder_without_its_read_document_older_than_the_age(self):
        folder = os.path.join(self.shared, "provider=chat", "kind=history", "channel=C0TRIBE1", "read=1_2-" + OTHER_RUN + ".channels")
        os.makedirs(folder)
        self.aged(folder, 6)

        self.prune()

        self.assertFalse(os.path.exists(folder))

    def test_keeps_a_folder_without_its_read_document_younger_than_the_age(self):
        folder = os.path.join(self.shared, "provider=chat", "kind=history", "channel=C0TRIBE1", "read=1_2-" + OTHER_RUN + ".channels")
        os.makedirs(folder)
        self.aged(folder, 4)

        self.prune()

        self.assertTrue(os.path.isdir(folder))

    def test_deletes_a_staging_leftover_older_than_the_age(self):
        staging = os.path.join(self.incoming(), "read-left")
        os.makedirs(staging)
        self.aged(staging, 6)

        self.prune()

        self.assertFalse(os.path.exists(staging))

    def test_deletes_whole_read_folders_only(self):
        handle = self.stored_at(OLD_AT)

        self.prune()

        self.assertEqual((os.path.exists(self.shared_folder(handle)), os.path.isdir(os.path.dirname(self.shared_folder(handle)))), (False, True))

    def test_a_run_store_keeps_its_linked_reads_after_a_prune(self):
        self.stored_at(OLD_AT)
        session = self.sharing(run=RUN)
        linked = session.link_in(session.shared_reads("history", HISTORY)[0])

        self.prune()

        self.assertEqual((self.fetch_ids(), store.load_records(linked.folder)), ([], RECORDS))

    def test_an_age_of_zero_exits_2(self):
        self.assertEqual(self.prune(days="0")[0], 2)

    def test_a_fractional_age_exits_2(self):
        self.assertEqual(self.prune(days="1.5")[0], 2)

    def test_a_negative_age_exits_2(self):
        self.assertEqual(self.prune(days="-3")[0], 2)

    def test_a_root_that_is_not_a_folder_exits_2(self):
        code, _, err = self.prune(root=os.path.join(self.tmp.name, "missing"))

        self.assertEqual((code, "missing" in err), (2, True))


if __name__ == "__main__":
    unittest.main()
