import contextlib
import io
import json
import os
import pathlib
import socket
import stat
import tempfile
import unittest
from unittest import mock

import state
import store
from providers import slack

FIXTURES = pathlib.Path(__file__).parent / "providers" / "fixtures" / "slack"
ROOT_TS = "1760002000.000200"
WINDOW_SPAN = ("1760000500.000050", "1760010800")

RUN = "20261020T073004Z-z1x7pc"
OTHER_RUN = "20261019T120003Z-p8m1za"
FETCHED_AT = "2026-10-20T07:30:09Z"
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

    def session(self, source="channels", transport="mcp", run=RUN):
        return store.ReadSession(self.root, "chat", run, source, "slack", transport, clock=lambda: FETCHED_AT, runtime="ab" * 20)

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


if __name__ == "__main__":
    unittest.main()
