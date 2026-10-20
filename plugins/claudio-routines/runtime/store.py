import collections
import decimal
import json
import os
import re
from datetime import datetime, timezone

import state

SCHEMA = 1
READ_FILE = "read.json"
RECORDS_FILE = "records.jsonl"
MANIFEST_FILE = "manifest.json"
PAGE_SUFFIXES = {"api": ".json", "mcp": ".txt"}
STATUSES = ("complete", "failed", "partial")
FOLDER_MODE = 0o700
PART_CAP = 200
BARRED_IN_PART = ("/", "\\", "=", "\x00")
KEY = re.compile(r"[a-z][a-z0-9_]*")
TS = re.compile(r"[0-9]{1,16}(?:\.[0-9]{1,9})?")
READ_NAME = re.compile(r"read=(?:(?P<start>[0-9.]+)_(?P<end>[0-9.]+)-)?(?P<fetch>[^/]+)")
LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")
REPLACEMENT = "�"
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

SCHEMA_ONE = state.leaf(lambda value: state.is_integer(value) and value == SCHEMA, f"schema {SCHEMA}")
COUNT = state.leaf(lambda value: state.is_integer(value) and value >= 0, "a non-negative integer")
STATUS = state.leaf(lambda value: value in STATUSES, "one of " + ", ".join(STATUSES))
READ_SPEC = {
    "schema": SCHEMA_ONE,
    "adapter": state.TEXT,
    "provider": state.TEXT,
    "kind": state.TEXT,
    "entity": {"*": state.TEXT},
    "span": state.Nullable({"from": state.TEXT, "to": state.TEXT}),
    "transport": state.TRANSPORT,
    "run": state.TEXT,
    "source": state.TEXT,
    "fetched_at": state.TEXT,
    "pages": [{"file": state.TEXT, "request": state.PRESENT}],
    "outcome": {"status": STATUS, "reason": state.Nullable(state.TEXT)},
    "parsed_by": state.Nullable(state.TEXT),
}
MANIFEST_SPEC = {"schema": SCHEMA_ONE, "sources": {"*": {"reads": [state.TEXT], "fetched": COUNT, "reused": COUNT}}}

StoredRead = collections.namedtuple("StoredRead", "folder stored span fetch_id document")


class PagePending(Exception):
    def __init__(self, call_id, path, request):
        super().__init__(call_id)
        self.call_id = call_id
        self.path = path
        self.request = request


def utc_now():
    return datetime.now(timezone.utc).strftime(UTC_FORMAT)


def is_safe(value):
    return (
        isinstance(value, str)
        and value not in ("", ".", "..")
        and len(value.encode("utf-8", "surrogatepass")) <= PART_CAP
        and not any(barred in value for barred in BARRED_IN_PART)
    )


def folder_part(key, value):
    if not isinstance(key, str) or KEY.fullmatch(key) is None:
        raise state.Rejected("store: a folder key must be lowercase words")
    if not is_safe(value):
        raise state.Rejected(f"store: unsafe {key} value")
    return f"{key}={value}"


def read_part(span, fetch_id):
    if span is None:
        return f"read={fetch_id}"
    if len(span) != 2 or not all(isinstance(bound, str) and TS.fullmatch(bound) for bound in span):
        raise state.Rejected("store: a span bound must be a ts")
    return f"read={span[0]}_{span[1]}-{fetch_id}"


def replaced(value):
    if isinstance(value, str):
        return LONE_SURROGATE.sub(REPLACEMENT, value)
    if isinstance(value, list):
        return [replaced(item) for item in value]
    if isinstance(value, dict):
        return {replaced(key): replaced(item) for key, item in value.items()}
    return value


def dump_lines(records):
    lines = (json.dumps(replaced(record), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n" for record in records)
    return "".join(lines).encode("utf-8")


def make_folders(folder):
    missing, path = [], folder
    while not os.path.isdir(path):
        missing.append(path)
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    for path in reversed(missing):
        try:
            os.mkdir(path, FOLDER_MODE)
        except FileExistsError:
            continue
        except OSError as error:
            raise state.InputError(f"store: cannot create {path}: {error.strerror}") from error
        os.chmod(path, FOLDER_MODE)


def saved_bytes(path):
    try:
        with open(path, "rb") as stream:
            return stream.read()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise state.InputError(f"store: cannot read {path}: {error.strerror}") from error


def check_read(document):
    state.check(document, READ_SPEC, "")


def check_manifest(document):
    state.check(document, MANIFEST_SPEC, "")


def load_document(folder):
    return state.load(os.path.join(folder, READ_FILE), "read", check_read)


def load_records(folder):
    path = os.path.join(folder, RECORDS_FILE)
    raw = saved_bytes(path)
    if raw is None:
        raise state.InputError(f"store: {path} is missing")
    records = []
    for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        try:
            record = json.loads(line)
        except ValueError as error:
            raise state.InvalidJson(f"store: invalid JSON in {path} line {number}: {error}") from error
        if not isinstance(record, dict):
            raise state.Rejected(f"store: {path} line {number} is not an object")
        records.append(record)
    return records


def read_order(read):
    if read.span is None:
        return (decimal.Decimal(-1), decimal.Decimal(-1), read.fetch_id)
    return (decimal.Decimal(read.span[0]), decimal.Decimal(read.span[1]), read.fetch_id)


def list_reads(root, folder):
    try:
        names = os.listdir(folder)
    except FileNotFoundError:
        return []
    except OSError as error:
        raise state.InputError(f"store: cannot list {folder}: {error.strerror}") from error
    found = []
    for name in names:
        match = READ_NAME.fullmatch(name)
        path = os.path.join(folder, name)
        if match is None or not os.path.isfile(os.path.join(path, READ_FILE)):
            continue
        span = None if match["start"] is None else (match["start"], match["end"])
        stored = os.path.relpath(path, root).replace(os.sep, "/")
        found.append(StoredRead(path, stored, span, match["fetch"], load_document(path)))
    return sorted(found, key=read_order)


class ReadSession:
    def __init__(self, root, provider, run, source, adapter, transport, clock=None, runtime=None):
        if transport not in PAGE_SUFFIXES:
            raise state.Rejected(f"store: unknown transport {transport}")
        if not is_safe(run) or not is_safe(source):
            raise state.Rejected("store: unsafe run or source name")
        self.root = root
        self.provider = provider
        self.base = os.path.join(root, folder_part("provider", provider))
        self.run = run
        self.source = source
        self.fetch_id = f"{run}.{source}"
        self.adapter = adapter
        self.transport = transport
        self.suffix = PAGE_SUFFIXES[transport]
        self.clock = clock or utc_now
        self.runtime = runtime
        self._used = {}

    def entity_folder(self, kind, entity):
        return os.path.join(self.base, folder_part("kind", kind), *(folder_part(key, value) for key, value in entity))

    def open(self, kind, entity, span=None):
        parts = [folder_part("kind", kind), *(folder_part(key, value) for key, value in entity), read_part(span, self.fetch_id)]
        handle = ReadHandle(self, kind, dict(entity), span, parts)
        self._used.setdefault(handle.stored, self.fetch_id)
        return handle

    def reads(self, kind, entity):
        return list_reads(self.root, self.entity_folder(kind, entity))

    def used(self):
        return list(self._used)

    def counts(self):
        fetched = sum(1 for fetch_id in self._used.values() if fetch_id == self.fetch_id)
        return {"fetched": fetched, "reused": len(self._used) - fetched}


class ReadHandle:
    def __init__(self, session, kind, entity, span, parts):
        self.session = session
        self.kind = kind
        self.entity = entity
        self.span = span
        self.relative = "/".join(parts)
        self.stored = "/".join((os.path.basename(session.base), *parts))
        self.folder = os.path.join(session.base, *parts)
        self.last_id = None
        self._pages = []

    def done(self):
        return os.path.isfile(os.path.join(self.folder, READ_FILE))

    def page(self, request, fetch=None):
        number = len(self._pages) + 1
        name = f"page-{number:03d}{self.session.suffix}"
        self._pages.append({"file": name, "request": request})
        self.last_id = f"{self.relative}/page-{number:03d}"
        path = os.path.join(self.folder, name)
        saved = saved_bytes(path)
        if saved is not None:
            return saved
        if fetch is None:
            raise PagePending(self.last_id, path, request)
        data = fetch()
        make_folders(self.folder)
        state.write_all([(path, data)])
        return data

    def finish(self, status, reason=None, records=None):
        if status not in STATUSES:
            raise state.Rejected(f"store: unknown read status {status}")
        if self.done():
            return
        make_folders(self.folder)
        if status == "complete":
            state.write_all([(os.path.join(self.folder, RECORDS_FILE), dump_lines(records or []))])
        state.write_all([(os.path.join(self.folder, READ_FILE), state.dump(replaced(self._document(status, reason))))])

    def document(self):
        return load_document(self.folder)

    def records(self):
        if self.document()["outcome"]["status"] != "complete":
            raise state.InputError(f"store: {self.relative} holds no records")
        return load_records(self.folder)

    def _document(self, status, reason):
        session = self.session
        return {
            "schema": SCHEMA,
            "adapter": session.adapter,
            "provider": session.provider,
            "kind": self.kind,
            "entity": self.entity,
            "span": None if self.span is None else {"from": self.span[0], "to": self.span[1]},
            "transport": session.transport,
            "run": session.run,
            "source": session.source,
            "fetched_at": session.clock(),
            "pages": list(self._pages),
            "outcome": {"status": status, "reason": reason},
            "parsed_by": session.runtime,
        }


def write_manifest(run_dir, source, session):
    path = os.path.join(run_dir, MANIFEST_FILE)
    document = state.load(path, "manifest", check_manifest) if os.path.exists(path) else {"schema": SCHEMA, "sources": {}}
    entry = {"reads": session.used(), **session.counts()}
    state.write_all([(path, state.dump({"schema": SCHEMA, "sources": {**document["sources"], source: entry}}))])
